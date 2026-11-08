#!/usr/bin/env node
/**
 * test-chatgpt-watch.mjs — Reception suite for the chatgpt-watch skill and
 * daemon (pure logic + source guards, no CDP/browser/OpenCode runtime).
 *
 * Covers: arm-token normalization (mobile autocorrect tolerance), instruction
 * parsing (armed / control / ignored / project: extraction / mid-text marker
 * NOT armed), conversation id extraction (c / g-projects / legacy / bare id),
 * unseen-message selection (fail-closed first scan, never replay), run-prompt
 * encapsulation (untrusted-channel framing), backoff, task-dir resolution,
 * state roundtrip + corruption recovery, CLI parse/validate, status format,
 * and source guards (no permission bypass, localhost-only CDP, no direct
 * ChatGPT fetch from Node).
 *
 * Run: node scripts/test-chatgpt-watch.mjs   (node >= 22, native WebSocket)
 */

import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { homedir, tmpdir } from "node:os"
import { resolve } from "node:path"
import {
  DEFAULTS,
  backoffDelay,
  buildRunPrompt,
  defaultStatePath,
  extractConversationId,
  formatStatus,
  loadState,
  normalizeArmToken,
  parseArgs,
  parseInstruction,
  pickNewUserMessages,
  resolveTaskDir,
  sanitizeForLog,
  saveState,
  selectFresh,
  resyncState,
  validateArgs,
} from "../scripts/chatgpt-watch.mjs"

const tmp = mkdtempSync(resolve(tmpdir(), "chatgpt-watch-test-"))

// ── 1. Arm-token normalization ─────────────────────────────────────────────
assert.equal(DEFAULTS.armToken, "AURORA:")
const norm = normalizeArmToken("AURORA:")
assert.equal(norm, "AURORA(?:\\s*[:：]\\s*|\\s+|$)")
assert.equal(normalizeArmToken("AURORA"), norm, "token without colon normalized the same")
assert.equal(normalizeArmToken("GO :"), "GO(?:\\s*[:：]\\s*|\\s+|$)", "custom token + french space tolerated")
assert.throws(() => normalizeArmToken("   "), "empty token rejected")

// ── 2. parseInstruction: not armed → ignored ───────────────────────────────
assert.equal(parseInstruction("corrige la pagination").kind, "ignored")
assert.equal(parseInstruction("aurora, corrige la pagination").kind, "ignored", "bare mention without token is ignored")
assert.equal(parseInstruction("").kind, "empty")
assert.equal(parseInstruction(null).kind, "empty")

// ── 3. parseInstruction: armed task ────────────────────────────────────────
{
  const r = parseInstruction("AURORA: corrige la pagination sur les factures")
  assert.equal(r.kind, "task")
  assert.equal(r.dir, null)
  assert.equal(r.instruction, "corrige la pagination sur les factures")
}
{
  const r = parseInstruction("aurora : relance les tests")
  assert.equal(r.kind, "task", "mobile autocorrect space before colon tolerated")
  assert.equal(r.instruction, "relance les tests")
}
{
  const r = parseInstruction("AURORA:\u00A0relance les tests") // non-breaking space
  assert.equal(r.kind, "task", "non-breaking space after token tolerated")
}
{
  const r = parseInstruction("AURORA: projet ~/dev/foo — corrige le bug X")
  assert.equal(r.kind, "task")
  assert.equal(r.dir, "~/dev/foo")
  assert.equal(r.instruction, "corrige le bug X")
}
{
  const r = parseInstruction("AURORA: project: /abs/path - do the thing")
  assert.equal(r.kind, "task")
  assert.equal(r.dir, "/abs/path")
  assert.equal(r.instruction, "do the thing")
}

// ── 4. parseInstruction: control commands ──────────────────────────────────
for (const [msg, cmd] of [
  ["AURORA: status", "status"],
  ["AURORA: pause", "pause"],
  ["AURORA: resume", "resume"],
  ["AURORA: stop", "stop"],
  ["AURORA:", "status"], // bare marker → status
  ["AURORA: projet", "status"], // no instruction body → status
]) {
  const r = parseInstruction(msg)
  assert.equal(r.kind, "control", msg)
  assert.equal(r.command, cmd, msg)
}

// ── 5. parseInstruction: control lookalikes are tasks (word boundary) ──────
{
  const r = parseInstruction("AURORA: stoppe la purge des logs")
  assert.equal(r.kind, "task", "'stoppe' must not match the stop command (word boundary)")
  assert.equal(r.instruction, "stoppe la purge des logs")
}
{
  const r = parseInstruction("AURORA: résume le document")
  assert.equal(r.kind, "task", "'résume' must not match the resume command")
}

// ── 6. Mid-text marker does NOT arm (head-anchored) ────────────────────────
assert.equal(parseInstruction("blabla\nAURORA: status").kind, "ignored", "marker mid-text is not an instruction")
assert.equal(parseInstruction("voir https://example.com AURORA: stop").kind, "ignored")

// ── 7. extractConversationId ───────────────────────────────────────────────
assert.equal(extractConversationId("https://chatgpt.com/c/6adb9882-d0ac-83ed-a0a6-64eb14998189"), "6adb9882-d0ac-83ed-a0a6-64eb14998189")
assert.equal(extractConversationId("https://chatgpt.com/g/g-p-68a1/c/uuid-42"), "uuid-42")
assert.equal(extractConversationId("https://chat.openai.com/c/legacy-id-9"), "legacy-id-9")
assert.equal(extractConversationId("6adb9882-d0ac-83ed-a0a6-64eb14998189"), "6adb9882-d0ac-83ed-a0a6-64eb14998189", "bare id accepted")
assert.equal(extractConversationId("https://chatgpt.com/"), null)
assert.equal(extractConversationId("https://mychatgpt.com/c/abc123"), null, "lookalike host rejected")
assert.equal(extractConversationId(""), null)
assert.equal(extractConversationId(undefined), null)

// ── 8. selectFresh: replay exactly once (F-01 — perpetual-loop regression) ──
const msgs = [
  { id: "m1", text: "AURORA: task one" },
  { id: "m2", text: "hello" },
  { id: "m3", text: "AURORA: task two" },
]
{
  const st = { lastSeenId: null }
  const cfgReplay = { replayLast: true }
  const pass1 = selectFresh(msgs, st, cfgReplay)
  assert.deepEqual(pass1.fresh, [msgs[2]], "replay-last yields the last message once")
  assert.equal(pass1.markAllSeenId, "m3")
  // simulate the main loop applying the returned state
  const st2 = { lastSeenId: pass1.markAllSeenId }
  const pass2 = selectFresh(msgs, st2, cfgReplay)
  assert.deepEqual(pass2.fresh, [], "replayed instruction MUST NOT be re-executed on the next pass")
  assert.equal(pass2.markAllSeenId, null)
}
{
  const st = { lastSeenId: null }
  const pass1 = selectFresh(msgs, st, { replayLast: false })
  assert.deepEqual(pass1.fresh, [], "default first scan executes nothing")
  assert.equal(pass1.markAllSeenId, "m3", "existing tail marked seen")
  assert.deepEqual(selectFresh(msgs, { lastSeenId: pass1.markAllSeenId }, { replayLast: false }).fresh, [])
}
{
  // empty conversation on first scan → nothing marked, retried next pass
  const pass1 = selectFresh([], { lastSeenId: null }, { replayLast: false })
  assert.deepEqual(pass1.fresh, [])
  assert.equal(pass1.markAllSeenId, null)
}
{
  // stale lastSeenId (compacted conversation / DOM id switch) → resync, never execute (R-02)
  const r = resyncState(msgs)
  assert.deepEqual(r.fresh, [], "resync never executes anything")
  assert.equal(r.markAllSeenId, "m3", "tail becomes the new watermark")
  assert.equal(r.resynced, true)
  // wired through selectFresh
  const stale = selectFresh(msgs, { lastSeenId: "gone" }, { replayLast: false })
  assert.deepEqual(stale.fresh, [])
  assert.equal(stale.markAllSeenId, "m3")
  assert.equal(stale.resynced, true)
  // replay-last never replays on an existing state (semantic pin)
  assert.deepEqual(selectFresh(msgs, { lastSeenId: "m3" }, { replayLast: true }).fresh, [])
}
{
  // multi-word custom tokens are functional (R-01 — double-escaping regression)
  const norm2 = normalizeArmToken("WATCH GO")
  assert.equal(norm2, "WATCH\\s+GO(?:\\s*[:：]\\s*|\\s+|$)")
  assert.equal(parseInstruction("WATCH GO: fait X", "WATCH GO").kind, "task", "multi-word token arms its message")
  assert.equal(parseInstruction("WATCHGO: fait X", "WATCH GO").kind, "ignored", "collapsed form not armed")
}

// ── 9. pickNewUserMessages: fail-closed semantics ───────────────────────────
assert.deepEqual(pickNewUserMessages(msgs, null), [], "first scan without state marks all seen (never replay)")
assert.deepEqual(pickNewUserMessages(msgs, null, true), [msgs[2]], "--replay-last yields only the last message")
assert.deepEqual(pickNewUserMessages(msgs, "m1"), [msgs[1], msgs[2]], "everything after lastSeen")
assert.deepEqual(pickNewUserMessages(msgs, "m3"), [], "nothing new after last seen")
assert.deepEqual(pickNewUserMessages(msgs, "gone"), [], "lastSeen not found (compacted convo) → fail-closed, nothing picked")
assert.deepEqual(pickNewUserMessages(null, "m1"), [], "malformed input tolerated")
assert.deepEqual(pickNewUserMessages([{ text: "no id" }, { id: "m0", text: "ok" }], null), [], "entries without id dropped")

// ── 9. buildRunPrompt: untrusted-channel encapsulation ─────────────────────
{
  const p = buildRunPrompt({
    instruction: "corrige le bug X",
    projectDir: "/work/foo",
    convUrl: "https://chatgpt.com/c/conv-1",
  })
  assert.ok(p.includes("corrige le bug X"), "instruction embedded")
  assert.ok(p.includes("/work/foo"), "project dir embedded")
  assert.ok(p.includes("https://chatgpt.com/c/conv-1"), "conversation url embedded")
  assert.ok(p.includes("browser-debug"), "summary post protocol names browser-debug")
  assert.ok(p.includes("chrome-devtools"), "summary post protocol forbids chrome-devtools by name")
  assert.ok(p.includes("DONNÉE"), "instruction framed as data, not a rule override")
  assert.ok(p.includes("AGENTS.md"), "project AGENTS.md referenced")
}

// ── 10. Arm-token metacharacters (custom tokens are regex-escaped) ─────────
{
  assert.equal(normalizeArmToken("A(B)"), "A\\(B\\)(?:\\s*[:：]\\s*|\\s+|$)", "metacharacters escaped")
  const r = parseInstruction("A(B): fait X", "A(B)")
  assert.equal(r.kind, "task", "escaped custom token matches itself")
  assert.equal(r.instruction, "fait X")
  assert.equal(parseInstruction("AB: fait X", "A(B)").kind, "ignored", "escaped token does not over-match")
}
{
  assert.equal(parseInstruction("GOT: fait X", "GO.").kind, "ignored", "literal 'GO.' must not arm 'GOT: …'")
  const r = parseInstruction("GO. fait X", "GO.")
  assert.equal(r.kind, "task", "literal token matches itself")
  assert.equal(r.instruction, "fait X")
}

// ── 11. Instruction length cap (argv E2BIG protection) ─────────────────────
{
  const big = "AURORA: " + "x".repeat(DEFAULTS.maxInstructionChars + 1)
  const r = parseInstruction(big)
  assert.equal(r.kind, "overflow")
  assert.equal(r.length, DEFAULTS.maxInstructionChars + 1)
  const ok = parseInstruction("AURORA: " + "x".repeat(DEFAULTS.maxInstructionChars))
  assert.equal(ok.kind, "task", "at-cap instruction accepted")
}

// ── 12. backoffDelay ───────────────────────────────────────────────────────
assert.ok(backoffDelay(0, 5000, 60_000) === 5000, "attempt 0 = base")
assert.ok(backoffDelay(1) === 10_000 && backoffDelay(2) === 20_000, "exponential growth")
assert.ok(backoffDelay(30) === 60_000, "capped")

// ── 13. resolveTaskDir (real fs) ───────────────────────────────────────────
{
  const def = tmp
  const r1 = resolveTaskDir("subdir-exists-check", def)
  assert.ok(r1.error, "non-existent dir rejected")
  const r2 = resolveTaskDir("", def)
  assert.equal(r2.dir, resolve(def), "empty input → default")
  const r3 = resolveTaskDir(tmp, def)
  assert.equal(r3.dir, resolve(tmp), "absolute existing dir accepted")
  assert.ok(resolveTaskDir("~", def).dir === homedir(), "~ expanded")
  assert.equal(resolveTaskDir("~/definitely-not-here-42", def).error, "directory not found: ~/definitely-not-here-42")
  const filePath = resolve(tmp, "a-file.txt")
  writeFileSync(filePath, "x")
  assert.ok(resolveTaskDir(filePath, def).error, "a FILE path is rejected (not a directory)")
}

// ── 14. state roundtrip + recovery ─────────────────────────────────────────
{
  const p = resolve(tmp, "state-conv1.json")
  const convId = "conv1"
  const st = loadState(p, convId)
  assert.equal(st.lastSeenId, null, "fresh state on missing file")
  assert.deepEqual(st.queue, [], "fresh queue")
  st.lastSeenId = "m9"
  st.queue.push({ instruction: "x", dir: "/w", id: "m9" })
  st.paused = true
  saveState(p, st)
  const reloaded = loadState(p, convId)
  assert.equal(reloaded.lastSeenId, "m9")
  assert.equal(reloaded.paused, true)
  assert.equal(reloaded.queue.length, 1)
  assert.equal(loadState(p, "other-conv").lastSeenId, null, "conversation mismatch → fresh")
  writeFileSync(p, "{corrupted")
  assert.equal(loadState(p, convId).lastSeenId, null, "corrupted state → fresh (fail-closed first scan)")
  assert.ok(defaultStatePath("abc").includes("chatgpt-watch"), "state path is under the config tree")
}

// ── 15. CLI parse + validate ───────────────────────────────────────────────
{
  const args = parseArgs([
    "--conversation", "https://chatgpt.com/c/abc-123",
    "--interval", "45",
    "--project", "/work/bar",
    "--arm-token", "GO:",
    "--max-queue", "5",
    "--timeout", "600",
    "--once",
    "--replay-last",
    "--verbose",
  ])
  assert.equal(args.conversation, "https://chatgpt.com/c/abc-123")
  assert.equal(args.interval, 45)
  assert.equal(args.project, "/work/bar")
  assert.equal(args.armToken, "GO:")
  assert.equal(args.maxQueue, 5)
  assert.equal(args.timeout, 600)
  assert.equal(args.once, true)
  assert.equal(args.replayLast, true)
  assert.equal(args.agent, "aurora", "agent default")
  const { convId, errors } = validateArgs(args)
  assert.equal(convId, "abc-123")
  assert.deepEqual(errors, [])
}
{
  const bad = parseArgs([])
  assert.ok(validateArgs(bad).errors.length >= 1, "missing conversation rejected")
  const slow = parseArgs(["--conversation", "abc", "--interval", "5"])
  assert.ok(validateArgs(slow).errors.some((e) => e.includes("--interval")), "interval below floor rejected")
  assert.equal(validateArgs(parseArgs(["--conversation", "0b8f6a2e-11c1-4e5d-9a9b-77f2c3d4e5f6"])).convId, "0b8f6a2e-11c1-4e5d-9a9b-77f2c3d4e5f6", "bare id validates")
}

// ── 16. formatStatus ───────────────────────────────────────────────────────
{
  const s = formatStatus({
    state: { conversationId: "c1", queue: [{}], paused: true },
    cfg: { interval: 30, maxQueue: 3 },
    uptimeMs: 125_000,
    running: null,
  })
  assert.ok(s.includes("paused"), "paused state surfaced")
  assert.ok(s.includes("queue: 1/3"), "queue usage surfaced")
  assert.ok(s.includes("idle"), "idle run surfaced")
}

// ── 17. sanitizeForLog ─────────────────────────────────────────────────────
assert.equal(sanitizeForLog("a\n  b\tc"), "a b c", "single line")
assert.ok(sanitizeForLog("x".repeat(500)).length <= 121, "truncated")
assert.equal(sanitizeForLog("x".repeat(500), { maxLen: 500 }).length, 500, "under limit kept")

// ── 18. Source guards: security invariants of the daemon ───────────────────
{
  const src = readFileSync(new URL("../scripts/chatgpt-watch.mjs", import.meta.url), "utf8")
  assert.ok(!src.includes('"--auto"'), "never spawns runs with permission auto-approval")
  assert.ok(!src.includes("--dangerously-skip-permissions"), "never bypasses permissions")
  assert.equal(DEFAULTS.cdpHost, "127.0.0.1", "CDP is localhost-only")
  assert.ok(!/fetch\(\s*[`"']https?:\/\//.test(src), "no direct HTTP fetch to remote hosts from Node (CDP + in-page fetch only)")
  assert.ok(src.includes("is_visually_hidden_from_conversation"), "hidden ChatGPT internal messages filtered")
  assert.ok(src.includes("SIGTERM") && src.includes("SIGINT"), "graceful shutdown signals handled")
  assert.ok(src.includes("process.argv[1]"), "main() guarded against import (reception suite safety)")
  assert.ok(src.includes('.on("error"'), "spawn error handlers present — unhandled 'error' event would kill the daemon (F-02)")
  assert.ok(/if \(stopping\) return/.test(src), "stopping guard before spawning work (F-06)")
  assert.ok(
    src.includes("if (stopping || running || state.paused || !state.queue.length) return"),
    "composed stopping guard in runNext pinned (F-06)",
  )
  assert.ok(src.includes("0o600"), "state file written owner-only (armed content persisted)")
  assert.ok(src.includes("isDirectory()"), "task dir must be a directory, not a file")
  assert.ok(src.includes("SIGKILL"), "timeout escalation SIGTERM → SIGKILL (F-03)")
  assert.ok(src.includes("selectFresh("), "fresh selection goes through the pure, tested helper (F-01)")
  assert.ok(src.includes("escapeRegExp"), "custom arm tokens are regex-escaped (F-05)")
  {
    const hc = readFileSync(new URL("../scripts/health-check.sh", import.meta.url), "utf8")
    assert.ok(hc.includes("test-chatgpt-watch.mjs"), "reception suite wired into health-check (F-07)")
  }
}

// ── 19. Skill file: hard rules present ─────────────────────────────────────
{
  const skill = readFileSync(new URL("../skills/chatgpt-watch/SKILL.md", import.meta.url), "utf8")
  assert.ok(skill.includes("Armement obligatoire"), "hard rule 1 present")
  assert.ok(skill.includes("donnée non fiable"), "untrusted-channel rule present")
  assert.ok(skill.includes("tout le disque"), "owner's no-directory-restriction choice documented as residual risk")
  assert.ok(skill.includes("auto-approbation"), "permission-bypass ban documented")
  assert.ok(skill.includes("chatgpt-watch.mjs"), "script path referenced")
  assert.ok(skill.includes("browser-debug"), "browser-debug MCP referenced (server rule)")
  assert.ok(skill.includes("jamais"), "hard-rule wording present")
}

console.log("ALL TESTS PASSED (chatgpt-watch reception suite)")
