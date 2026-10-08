#!/usr/bin/env node
/**
 * check-infomaniak-write-gate.mjs — Security Gate S-02 invariant test.
 *
 * Verifies that the global Infomaniak MCP server is effectively read-only:
 *   R1: GET (read) without INFOMANIAK_MCP_ALLOW_WRITES          → must succeed
 *   R2: POST (write) without INFOMANIAK_MCP_ALLOW_WRITES        → must be refused with "Write blocked"
 *   R3: POST with INFOMANIAK_MCP_ALLOW_WRITES=1                 → gate opens (idempotent probe body ignored by the API)
 *   R4: GET with INFOMANIAK_MCP_ALLOW_WRITES=1                  → still works (read path unaffected)
 *
 * Exit 0 = all pass; exit 1 = any failure (health-check.sh reports it).
 * The probe body uses a field name no API consumer reads → no side effect.
 *
 * Usage: node scripts/check-infomaniak-write-gate.mjs
 */
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const SERVER = process.env.INFOMANIAK_MCP_SERVER
  ?? join(homedir(), ".config", "opencode-config", "mcp", "infomaniak", "dist", "index.js");

function resolveToken() {
  if (process.env.INFOMANIAK_API_TOKEN) return process.env.INFOMANIAK_API_TOKEN;
  const content = readFileSync(join(homedir(), ".config", "opencode", ".env"), "utf-8");
  const m = content.match(/^INFOMANIAK_API_TOKEN\s*=\s*(.+)$/m);
  return m?.[1]?.trim().replace(/^["']|["']$/g, "") ?? "";
}

function call(env, toolName, args) {
  return new Promise((resolve, reject) => {
    const proc = spawn("node", [SERVER], {
      env: { ...process.env, INFOMANIAK_API_TOKEN: resolveToken(), ...env },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let out = Buffer.alloc(0);
    const timer = setTimeout(() => { proc.kill(); reject(new Error("server timeout")); }, 30_000);
    proc.on("error", (e) => { clearTimeout(timer); reject(e); });
    proc.stdout.on("data", (c) => {
      out = Buffer.concat([out, c]);
      for (;;) {
        const nl = out.indexOf("\n");
        if (nl === -1) break;
        const line = out.subarray(0, nl).toString().trim();
        out = out.subarray(nl + 1);
        if (!line) continue;
        let msg;
        try { msg = JSON.parse(line); } catch { continue; }
        if (msg.id === 1) {
          proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
          proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: toolName, arguments: args } }) + "\n");
        } else if (msg.id === 2) {
          clearTimeout(timer);
          proc.kill();
          resolve({
            text: (msg.result?.content ?? []).map((x) => x.text ?? "").join("\n"),
            err: msg.error ? JSON.stringify(msg.error) : null,
          });
        }
      }
    });
    proc.stdin.on("error", () => { /* surfaced via timeout/exit */ });
    proc.on("exit", (code) => { if (code !== 0 && code !== null) { clearTimeout(timer); reject(new Error(`server exited code ${code}`)); } });
    proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "gate-check", version: "0.0.1" } } }) + "\n");
  });
}

const NO_VAR = {};
const VAR_ON = { INFOMANIAK_MCP_ALLOW_WRITES: "1" };
const PROBE_BODY = { __aurora_gate_probe: 1 }; // unknown field — ignored by the API, no side effect

let failed = false;
const check = (name, ok, detail) => {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${ok ? "" : " — " + detail}`);
  if (!ok) failed = true;
};

try {
  const r1 = await call(NO_VAR, "get_profile", {});
  check("R1 read (GET) without var", (r1.text || "").includes('"result"'), JSON.stringify(r1).slice(0, 150));

  const r2 = await call(NO_VAR, "update_profile", { body: PROBE_BODY });
  const r2msg = r2.err || r2.text || "";
  check("R2 write (POST) without var → blocked", r2msg.includes("Write blocked"), r2msg.slice(0, 150));

  const r3 = await call(VAR_ON, "update_profile", { body: PROBE_BODY });
  check("R3 write (POST) with var=1 → gate open", !(r3.err || r3.text || "").includes("Write blocked"), JSON.stringify(r3).slice(0, 150));

  const r4 = await call(VAR_ON, "get_profile", {});
  check("R4 read (GET) with var=1", (r4.text || "").includes('"result"'), JSON.stringify(r4).slice(0, 150));
} catch (e) {
  console.log(`FAIL exception — ${e.message}`);
  failed = true;
}

process.exit(failed ? 1 : 0);
