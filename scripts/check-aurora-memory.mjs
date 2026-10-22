#!/usr/bin/env node
/**
 * check-aurora-memory.mjs — aurora-memory liveness invariant (2026-10-22).
 *
 * Why: the memory bridge (config/plugins/aurora-memory.ts) spawns the server
 * per call and the server maps tool failures to MCP `isError` with EMPTY text.
 * A stopped PostgreSQL container therefore degrades every memory operation
 * silently — observed 2026-10-14 → 2026-10-22: container down 8 days,
 * aurora_memory returned `{"result":{"content":[{"text":""}],"isError":true}}`
 * with no hint. This check makes the failure loud and actionable.
 *
 * Checks:
 *   C1: server bundle spawns and completes MCP initialize
 *   C2: goal_list (cheap read, no embedding call) returns non-error JSON
 *       content (payload must parse as JSON — an isError:false EMPTY result
 *       would be a new silent-degradation shape, not a success)
 *   C3: if docker + the PG container exist — restart policy must prevent a
 *       silent stop on host reboot (unless-stopped/always) → WARN otherwise
 *
 * Exit 0 = operational (C3 may add WARN lines) · 1 = broken (FAIL + remediation)
 *         2 = skip — server bundle absent (aurora-core not installed; optional
 *             infrastructure, absent on CI runners too)
 *
 * Never prints credentials: DATABASE_URL values are parsed to host:port only,
 * and any echoed stderr is redacted (user:password@ → ***@) — driver and
 * env-validation errors commonly embed the full DSN.
 *
 * Env overrides:
 *   AURORA_MEMORY_SERVER       server bundle path
 *                              (default ~/dev/aurora-core/services/aurora-memory/dist/index.mjs)
 *   AURORA_MEMORY_PG_CONTAINER docker container name (default aurora-core-postgres)
 *
 * Classification harness: scripts/tests/test-check-aurora-memory.sh injects
 * fake MCP servers via AURORA_MEMORY_SERVER to pin every classification
 * (CI-runnable, stdlib only, no docker required).
 *
 * Usage: node scripts/check-aurora-memory.mjs
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import net from "node:net";

const SERVER = process.env.AURORA_MEMORY_SERVER
  || join(homedir(), "dev", "aurora-core", "services", "aurora-memory", "dist", "index.mjs");
const PG_CONTAINER = process.env.AURORA_MEMORY_PG_CONTAINER || "aurora-core-postgres";
const CALL_TIMEOUT_MS = 20_000;

let failed = false;
const line = (prefix, name, detail) =>
  console.log(`${prefix} ${name}${detail ? " — " + detail : ""}`);
const pass = (name, detail) => line("PASS", name, detail);
const fail = (name, detail) => { line("FAIL", name, detail); failed = true; };
const warn = (name, detail) => line("WARN", name, detail);

/** Redact credentials from any uncontrolled channel (driver/env errors embed
 * the full DSN: postgres://user:password@host:port/db → postgres://***@…). */
const redact = (s) => String(s).replace(/\/\/[^@/\s"']+@/g, "//***@");

/** Parse host:port out of the repo-root .env (same file the server loads via
 * dotenv `../../../.env` relative to the bundle). Returns {host, port} or null. */
function probeTarget() {
  try {
    // dirname(bundle)/../../.. = repo root (mirrors src/index.ts dotenv path:
    // URL-relative '../../../' resolves from the FILE, path.join counts
    // index.mjs as a segment — hence the explicit dirname first).
    const envPath = join(dirname(SERVER), "../../..", ".env");
    if (!existsSync(envPath)) return null;
    const m = readFileSync(envPath, "utf-8").match(/^DATABASE_URL\s*=\s*(.+)$/m);
    if (!m) return null;
    const url = new URL(m[1].trim());
    return { host: url.hostname, port: Number(url.port) || 5432 };
  } catch {
    return null;
  }
}

/** TCP connect probe — never prints credentials, only host:port. */
function tcpProbe({ host, port }, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    const done = (ok) => { socket.destroy(); resolve(ok); };
    socket.setTimeout(timeoutMs, () => done(false));
    socket.once("connect", () => done(true));
    socket.once("error", () => done(false));
  });
}

/** docker inspect — null when docker or the container are unavailable. */
function dockerInspect(container) {
  return new Promise((resolve) => {
    const proc = spawn("docker", ["inspect", container], { stdio: ["ignore", "pipe", "ignore"] });
    let out = "";
    const timer = setTimeout(() => { proc.kill(); resolve(null); }, 5000);
    proc.stdout.on("data", (c) => { out += c; });
    proc.on("error", () => { clearTimeout(timer); resolve(null); });
    proc.on("exit", (code) => {
      clearTimeout(timer);
      if (code !== 0) return resolve(null);
      try {
        const info = JSON.parse(out)[0];
        resolve({
          running: info?.State?.Running === true,
          restartPolicy: info?.HostConfig?.RestartPolicy?.Name ?? "unknown",
        });
      } catch {
        resolve(null);
      }
    });
  });
}

if (!existsSync(SERVER)) {
  line("SKIP", "aurora-memory bundle absent", `${SERVER} — aurora-core not installed (optional infra)`);
  process.exit(2);
}

// One server process handles both probes (stateless stdio, same pattern as
// check-infomaniak-write-gate.mjs / the bridge plugin).
const result = await new Promise((resolve) => {
  const proc = spawn("node", [SERVER], { stdio: ["pipe", "pipe", "pipe"] });
  // The server may die between our writes (crash, early exit) — a write on a
  // dead stdin emits EPIPE → uncaught exception → exit 1 without FAIL lines
  // (the exact fail-open shape this check must never produce). Swallow it:
  // the close/timeout handlers classify the failure.
  proc.stdin.on("error", () => {});
  let out = Buffer.alloc(0);
  let stderr = "";
  const timer = setTimeout(() => {
    proc.kill("SIGKILL");
    resolve({ kind: "timeout" });
  }, CALL_TIMEOUT_MS);
  proc.stderr.on("data", (c) => { stderr += c.toString(); });
  proc.on("error", (e) => { clearTimeout(timer); resolve({ kind: "spawn-error", detail: e.message }); });
  const finish = (r) => {
    // Promise settles once — later calls are no-ops. SIGKILL (not SIGTERM):
    // we already have our answer, never leave an orphan behind.
    clearTimeout(timer);
    proc.kill("SIGKILL");
    resolve(r);
  };
  proc.stdout.on("data", (c) => {
    out = Buffer.concat([out, c]);
    for (;;) {
      const nl = out.indexOf("\n");
      if (nl === -1) break;
      const raw = out.subarray(0, nl).toString().trim();
      out = out.subarray(nl + 1);
      if (!raw) continue;
      let msg;
      try { msg = JSON.parse(raw); } catch { continue; }
      if (msg.id === 1) {
        if (msg.error) return finish({ kind: "init-error", detail: JSON.stringify(msg.error), stderr });
        proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
        proc.stdin.write(JSON.stringify({
          jsonrpc: "2.0", id: 2, method: "tools/call",
          params: { name: "goal_list", arguments: { limit: 1 } },
        }) + "\n");
      } else if (msg.id === 2) {
        if (msg.error) return finish({ kind: "rpc-error", detail: JSON.stringify(msg.error), stderr });
        const text = (msg.result?.content ?? []).map((x) => x.text ?? "").join("\n");
        if (msg.result?.isError) return finish({ kind: "tool-error", text, stderr });
        return finish({ kind: "ok", text, stderr });
      }
    }
  });
  // 'close' (not 'exit'): close fires after stdio streams are flushed, so a
  // server crashing right after writing the id=2 answer is classified from
  // its OUTPUT, not from the exit race.
  proc.on("close", (code) => {
    if (out.length > 0) return; // buffered data will still be parsed by the data handler
    if (code === 0) {
      finish({ kind: "server-exit", code, stderr, answered: false });
    } else if (code !== null) {
      finish({ kind: "server-exit", code, stderr });
    }
  });
  proc.stdin.write(JSON.stringify({
    jsonrpc: "2.0", id: 1, method: "initialize",
    params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "aurora-memory-check", version: "0.0.1" } },
  }) + "\n");
});

function classifyOk(text) {
  // C2 payload contract: goal_list returns a JSON document. An isError:false
  // EMPTY/None-JSON result would be a new silent-degradation shape — refuse it.
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}

if (result.kind === "ok") {
  pass("C1 server init", "bundle spawned, MCP initialize completed");
  if (classifyOk(result.text)) {
    pass("C2 goal_list", "cheap read returned non-error JSON content");
  } else {
    fail("C2 goal_list", `isError:false but payload is not JSON (${result.text ? `unexpected shape: ${redact(result.text).slice(0, 80)}` : "EMPTY content — new silent-degradation shape?"})`);
  }
} else {
  if (result.kind === "tool-error") {
    // Initialize succeeded — C1 holds, the failure is at the DB layer.
    pass("C1 server init", "bundle spawned, MCP initialize completed");
  }
  const target = probeTarget();
  const reachable = target ? await tcpProbe(target) : null;
  const where = target ? `${target.host}:${target.port}` : "DATABASE_URL target";
  const dbHint = reachable === false
    ? `PostgreSQL ${where} unreachable`
    : reachable === true
      ? `PostgreSQL ${where} reachable but the query failed`
      : `PostgreSQL ${where} status unknown`;
  const dockerInfo = result.kind === "tool-error" ? await dockerInspect(PG_CONTAINER) : null;
  const containerHint = dockerInfo === null
    ? ""
    : dockerInfo.running
      ? ""
      : ` — container '${PG_CONTAINER}' is STOPPED, run: docker start ${PG_CONTAINER} && docker update --restart unless-stopped ${PG_CONTAINER}`;
  const stderrHead = result.stderr ? redact(result.stderr.trim().split("\n")[0]).slice(0, 200) : "";

  switch (result.kind) {
    case "timeout":
      fail("C1 server init", `no MCP response within ${CALL_TIMEOUT_MS}ms (DB connect hanging?)`);
      break;
    case "spawn-error":
      fail("C1 server init", `cannot spawn node ${SERVER} — ${redact(result.detail)}`);
      break;
    case "server-exit":
      fail(
        "C1 server init",
        result.answered === false
          ? `exited cleanly (code 0) without answering tools/call — broken server?${stderrHead ? " — " + stderrHead : ""}`
          : `exited code ${result.code}${stderrHead ? " — " + stderrHead : ""}`,
      );
      if (/Configuration invalide/.test(result.stderr ?? "")) {
        fail("C1 env", "server env validation failed — check DATABASE_URL in the aurora-core repo-root .env");
      }
      break;
    case "init-error":
    case "rpc-error":
      fail("C1 server init", `${result.kind}${result.detail ? " — " + redact(result.detail).slice(0, 200) : ""}`);
      break;
    case "tool-error":
      fail("C2 goal_list", `tool returned isError with ${result.text ? "message" : "EMPTY message (known silent-degradation shape)"} — ${dbHint}${containerHint}`);
      break;
    default:
      fail("C1 server init", `unexpected result kind ${result.kind}`);
  }
}

// C3 — restart policy: prevents the silent stop that motivated this check.
// Only meaningful where docker exists (CI runners: dockerInspect → null, no line).
if (result.kind === "ok") {
  const info = await dockerInspect(PG_CONTAINER);
  if (info !== null) {
    if (!info.running) {
      // Operational now but the container we probed says stopped — impossible
      // in practice (goal_list just hit the DB); report defensively.
      warn("C3 container state", `'${PG_CONTAINER}' reports stopped although goal_list succeeded — docker state desynchronized?`);
    } else if (info.restartPolicy === "unless-stopped" || info.restartPolicy === "always") {
      pass("C3 restart policy", `'${PG_CONTAINER}' survives host reboots (${info.restartPolicy})`);
    } else {
      warn("C3 restart policy", `'${PG_CONTAINER}' policy '${info.restartPolicy}' — a host reboot stops the memory silently; run: docker update --restart unless-stopped ${PG_CONTAINER}`);
    }
  }
}

process.exit(failed ? 1 : 0);
