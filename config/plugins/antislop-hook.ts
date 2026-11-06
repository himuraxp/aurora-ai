import { readFileSync, statSync } from "node:fs"

// antislop-hook OpenCode plugin — advisory gate against AI-slop comments.
//
// The `antislop-code` skill (skills/antislop-code/SKILL.md) documents the
// comment-hygiene rules, but skills are opt-in: an agent that never loads the
// skill writes with its defaults. This plugin adds deterministic enforcement
// on top of the rule (same layering as chatgpt-autocowork): every edit/write
// through the edit/write tools is scanned for slop comments, and the tool
// result gets an advisory warning appended — visible to whichever agent wrote
// the code, orchestrator and sub-agents alike (hooks fire session-wide).
//
// Runtime contract (verified against oh-my-opencode-slim@3.0.4 dist/index.js,
// createToolExecuteBridges / afterBridge):
//   ctx.tool.hook("execute.after", handler) — handler receives the raw event
//   { tool, sessionID, id, status, input, result, error }; mutations to the
//   live `result.content` are persisted by the runtime (afterBridge writes
//   result.content itself, proving the read-back). Same mutation-style engine
//   as execute.before (rtk.ts) and session.prompt (chatgpt-autocowork.ts).
//
// Semantics:
//   - Advisory only: never blocks, never rewrites the file. The warning is
//     appended to the tool output so the model can self-correct.
//   - Diff-aware: only ADDED lines are scanned (multiset line diff), so
//     pre-existing comments are never re-flagged.
//   - Allowlist of source extensions; docs/data formats are skipped.
//   - Fail-open: any internal error is swallowed (advisory must not break
//     writes). Silent when no finding.
//
// Reception suite: scripts/test-antislop-hook.mjs (wired into
// scripts/health-check.sh, pattern test-chatgpt-autocowork.mjs).

type V2ToolHookEvent = {
  tool?: string
  id?: string
  status?: string
  input?: Record<string, unknown> | null
  result?: { content?: unknown; output?: unknown } | null
  output?: { output?: unknown } | null
}

type V2ToolHooks = {
  hook: (
    name: "execute.before" | "execute.after",
    handler: (event: V2ToolHookEvent) => Promise<void> | void,
  ) => Promise<{ dispose: () => void } | undefined>
}

type V2SetupContext = {
  tool?: V2ToolHooks
}

// Language surface

type MarkerKind = "slash" | "hash" | "dash"

const EXT_MARKERS: Record<string, MarkerKind> = {
  // slash: line "//" + block "/* */"
  ts: "slash", tsx: "slash", js: "slash", jsx: "slash", mjs: "slash", cjs: "slash",
  vue: "slash", svelte: "slash", astro: "slash",
  css: "slash", scss: "slash", less: "slash",
  c: "slash", h: "slash", cpp: "slash", hpp: "slash", cc: "slash", hh: "slash",
  cs: "slash", go: "slash", rs: "slash", java: "slash", kt: "slash", kts: "slash",
  swift: "slash", scala: "slash", dart: "slash", php: "slash", zig: "slash",
  hcl: "slash", tf: "slash", graphql: "slash", gql: "slash",
  // hash: line "#"
  py: "hash", pyi: "hash", rb: "hash", yml: "hash", yaml: "hash", toml: "hash",
  sh: "hash", bash: "hash", zsh: "hash", pl: "hash", pm: "hash", r: "hash",
  mk: "hash",
  // ini/cfg/conf/env deliberately NOT scanned: their "#" conventions are
  // human section banners (false-positive magnet), little agent traffic.
  // dash: line "--"
  sql: "dash", lua: "dash", hs: "dash",
}

const BASE_MARKERS: Record<string, MarkerKind> = {
  dockerfile: "hash",
  makefile: "hash",
}

const SKIP_DIR =
  /(^|\/)(?:node_modules|\.git|dist|build|out|coverage|vendor|__pycache__|\.venv|venv)(\/|$)/

export function markersForPath(path: string): MarkerKind | null {
  const segments = path.split("/")
  const lower = (segments[segments.length - 1] ?? "").toLowerCase()
  const baseKind = BASE_MARKERS[lower]
  if (baseKind) return baseKind
  const dot = lower.lastIndexOf(".")
  if (dot === -1) return null
  return EXT_MARKERS[lower.slice(dot + 1)] ?? null
}

export function isScannablePath(path: string): boolean {
  if (typeof path !== "string" || path.length === 0) return false
  if (SKIP_DIR.test(path)) return false
  return markersForPath(path) !== null
}

// Comment extraction

/** Trailing comment after code: token must follow whitespace, with balanced
 * quote parity before it (skips `//` and `#` inside string literals, URLs). */
function trailingComment(line: string, token: string): string | null {
  let from = 0
  for (;;) {
    const idx = line.indexOf(token, from)
    if (idx === -1) return null
    const prev = idx === 0 ? " " : line[idx - 1]
    if (prev === " " || prev === "\t") {
      const before = line.slice(0, idx)
      const quotes = (before.match(/["'`]/g) ?? []).length
      if (quotes % 2 === 0) return line.slice(idx + token.length)
    }
    from = idx + 1
  }
}

function normalizeCommentText(text: string): string {
  return text
    .replace(/\*+\/\s*$/, "")
    .trim()
    .replace(/^\*+\s*/, "")
    .trim()
}

function stripJsdocStar(line: string): string {
  return line.replace(/^\s*\*+\s?/, "")
}

/** Normalized comment texts from raw source lines. Block-comment state is
 * tracked across the array; only added fragments are ever passed in, so
 * state never leaks between scans. */
export function commentTextsFrom(lines: string[], kind: MarkerKind): string[] {
  const out: string[] = []
  let inBlock = false
  for (const line of lines) {
    if (kind === "slash" && inBlock) {
      const end = line.indexOf("*/")
      if (end === -1) {
        out.push(stripJsdocStar(line))
        continue
      }
      out.push(stripJsdocStar(line.slice(0, end)))
      inBlock = false
      out.push(trailingComment(line.slice(end + 2), "//") ?? "")
      continue
    }
    const t = line.trim()
    if (kind === "slash") {
      if (t.startsWith("//")) {
        out.push(t.slice(2))
        continue
      }
      if (t.startsWith("/*")) {
        const open = line.indexOf("/*")
        const end = line.indexOf("*/", open + 2)
        if (end === -1) {
          out.push(line.slice(open + 2))
          inBlock = true
          continue
        }
        out.push(line.slice(open + 2, end))
        out.push(trailingComment(line.slice(end + 2), "//") ?? "")
        continue
      }
      out.push(trailingComment(line, "//") ?? "")
      continue
    }
    if (kind === "hash") {
      if (t.startsWith("#!")) continue
      if (t.startsWith("#")) {
        out.push(t.slice(1))
        continue
      }
      out.push(trailingComment(line, "#") ?? "")
      continue
    }
    if (t.startsWith("--")) {
      out.push(t.slice(2))
      continue
    }
    out.push(trailingComment(line, "--") ?? "")
  }
  return out.map(normalizeCommentText).filter((t) => t.length > 0)
}

// Classification (from skills/antislop-code/SKILL.md)

const EMOJI =
  /[\u2705\u274C\u26A1\u26A0\u{1F680}\u{1F512}\u{1F4DD}\u{1F3AF}\u{1F4AF}]/u

const EMPTY_LABEL =
  /^(?:(?:main|core|business|helper|shared|common|general|utility) (?:logic|code|section|part|functions?|methods?|helpers?)|helper functions?|entry point|main entry|error handling|error handler|validation|data processing|state management|event handlers?|imports|exports|constants|types|interfaces|private methods?|public api|api endpoints?|routes|middleware|models|views|controllers|services|utils|helpers|setup|teardown|main|init)\s*$/i

const VAGUE_PLACEHOLDER =
  /^(?:future (?:improvements?|work|enhancements?)|additional (?:optimization|validation|features)|further (?:optimization|improvements?)|to be (?:implemented|done|defined)|not (?:yet )?implemented(?: yet)?|placeholder(?: implementation)?|for future (?:use|reference)|add (?:more )?(?:validation|error handling|tests?|features)(?: here)?)\s*$/i

// TODO hygiene (R-31): a TODO naming a concrete task stays; a TODO that names
// a feeling ("improve this", "handle later") goes. Specific task = verb
// followed by more than a filler tail, or a long body.
const TODO_BODY_VAGUE =
  /^(?:improve|refactor|clean ?up|optimize|fix|implement)\b/i
const TODO_BODY_TAIL = /\b(?:this|that|it|later|more|soon|stuff|things)\b\s*$/i
const TODO_BODY_FOOD =
  /^(?:add|handle|support)\s+(?:more\s+)?(?:validation|error handling|errors|tests?|features)\s*$/i
const TODO_BODY_LATER = /^(?:future|someday|eventually|later)\b/i

const END_MARKER =
  /^end (?:of |)(?:the )?(?:if|else|for(?:each)?|while|switch|case|try|catch|finally|function|func|method|class|block|loop|test)\b/i

const END_MARKER_TAIL =
  /^(?:if|else|for|while|switch|try|function|method|class|loop) end$/i

const CAPS_LABEL = /^[A-Z][A-Z0-9 &'\-]{2,47}$/

// "RFC 5322", "HTTP 204" — protocol references from the skill's preserve
// list, not shouting. A purely numeric token means the line carries facts.
const NUMERIC_TOKEN = /^\d+$/u

const STIFF =
  /^(?:this (?:function|method|class|module|component|service|endpoint) (?:is (?:responsible|used|designed|intended)|will be used|serves as|acts as|handles)|in order to\b|please note that\b|note that this\b|the following (?:code|function|method|section|snippet|block)\b|let'?s (?:start|begin|define|create|write|add|implement|build)\b|now (?:let'?s|we)(?:'ll)? (?:define|create|add|write|implement|build)\b)/i

// Narration is short by nature; a long comment starting "First," usually
// carries an ordering constraint ("First, dedupe by event ID; the API...").
const NARRATION_MAX = 45

// Box-drawing range (\u2500-\u257F) — the "// ─── X ───" separator style.
const DECO = "\\-=*_~\\u2500-\\u257F"
const PURE_DECO = new RegExp(`^[${DECO}\\s]{5,}$`, "u")
const WRAPPED_DECO = new RegExp(`^[${DECO}]{2,}[^${DECO}]{1,48}[${DECO}]{2,}$`, "u")

/** Returns the slop category for a normalized comment text, or null when the
 * comment passes (high-precision rules — advisory warnings must not nag). */
export function classifyComment(text: string): string | null {
  const t = text.replace(/\s+/g, " ").trim()
  if (!t) return null
  if (EMOJI.test(t)) return "decorative emoji"
  // PEM/PGP block markers ("-----BEGIN CERTIFICATE-----") are data, not banners —
  // guard BEFORE the separator tests, which they would otherwise match.
  if (/^-----+(?:BEGIN|END)\b/i.test(t)) return null
  if (PURE_DECO.test(t)) return "decorative separator"
  if (WRAPPED_DECO.test(t)) return "decorative separator"
  if (END_MARKER.test(t) || END_MARKER_TAIL.test(t)) return "end marker"
  if (/^step\s*\d+\s*[:.)-]/i.test(t)) return "workflow narration"
  if (t.length <= NARRATION_MAX && /^(?:first|next|then|finally|lastly)\s*[,;:]/i.test(t)) {
    return "workflow narration"
  }
  if (/^todo\b/i.test(t)) {
    const body = t.replace(/^todo\b\s*:?/i, "").trim()
    if (
      body.length === 0 ||
      TODO_BODY_FOOD.test(body) ||
      TODO_BODY_LATER.test(body) ||
      TODO_BODY_TAIL.test(body)
    ) {
      return "vague placeholder"
    }
    if (TODO_BODY_VAGUE.test(body) && (body.length <= 20 || TODO_BODY_TAIL.test(body))) {
      return "vague placeholder"
    }
    return null
  }
  if (VAGUE_PLACEHOLDER.test(t)) return "vague placeholder"
  if (EMPTY_LABEL.test(t)) return "empty label"
  if (CAPS_LABEL.test(t) && !/^(?:TODO|FIXME|NOTE|WARNING|CAUTION|IMPORTANT)\b/.test(t)) {
    const words = t.split(" ")
    const hasFactToken = words.some((w) => NUMERIC_TOKEN.test(w))
    if (!hasFactToken && (words.length >= 2 || t.length >= 8)) return "shouting label"
  }
  if (STIFF.test(t)) return "over-formal wording"
  const param = t.match(/^@param\s+(.*)$/i)
  if (param) {
    // JSDoc orders: "@param name desc", "@param {type} name - desc".
    const braced = param[1].match(/^\{[^}]*\}\s*(.*)$/)
    const rest = braced ? braced[1] : param[1]
    const parts = rest.trim().split(/\s+/)
    const name = (parts.shift() ?? "").toLowerCase()
    const desc = parts
      .join(" ")
      .replace(/^-\s*/, "")
      .replace(/[.:]\s*$/, "")
      .trim()
      .toLowerCase()
    if (name && (desc === name || desc === `the ${name}`)) return "signature echo"
  }
  return null
}

// Diff-aware scanning

export type SlopFinding = { text: string; category: string }

/** Multiset line diff: lines present in newLines beyond the occurrences kept
 * from oldLines. Duplicate lines are matched by count, not by set. */
export function addedLinesBetween(oldLines: string[], newLines: string[]): string[] {
  const kept = new Map<string, number>()
  for (const line of oldLines) kept.set(line, (kept.get(line) ?? 0) + 1)
  const added: string[] = []
  for (const line of newLines) {
    const count = kept.get(line) ?? 0
    if (count > 0) kept.set(line, count - 1)
    else added.push(line)
  }
  return added
}

export function scanAddedLines(rawLines: string[], kind: MarkerKind): SlopFinding[] {
  const findings: SlopFinding[] = []
  for (const text of commentTextsFrom(rawLines, kind)) {
    const category = classifyComment(text)
    if (category) findings.push({ text, category })
  }
  return findings
}

// Warning rendering

const MAX_SHOWN = 4
const MAX_SNIPPET = 60

export function buildWarning(findings: SlopFinding[], filePath: string): string {
  const shown = findings.slice(0, MAX_SHOWN)
  const more = findings.length - shown.length
  const bullets = shown.map((f) => {
    const snippet = f.text
      .replace(/[\r\n\t]+/g, " ")
      .trim()
      .slice(0, MAX_SNIPPET)
    return `  • "${snippet}" — ${f.category}`
  })
  if (more > 0) bullets.push(`  • … and ${more} more`)
  const plural = findings.length > 1 ? "s" : ""
  return (
    `\n\n[antislop-hook] ${findings.length} slop comment${plural} detected in ${filePath}` +
    ` (advisory — antislop-code rules):\n` +
    bullets.join("\n") +
    `\nOnly comments that explain why/constraints earn their place; remove or rewrite the rest.`
  )
}

// Tool hooks

type PendingWrite = { path: string; oldContent: string | null; skipScan: boolean }

const pendingWrites = new Map<string, PendingWrite>()
const MAX_PENDING = 200
const MAX_SCAN_BYTES = 2 * 1024 * 1024

function evictPending(): void {
  if (pendingWrites.size >= MAX_PENDING) {
    const oldest = pendingWrites.keys().next()
    if (!oldest.done) pendingWrites.delete(oldest.value)
  }
}

function argsString(args: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = args[key]
    if (typeof value === "string" && value) return value
  }
  return null
}

function persistWarning(event: V2ToolHookEvent, warning: string): void {
  const result = event?.result
  if (result && typeof result === "object") {
    const r = result as { content?: unknown; output?: unknown }
    if (typeof r.content === "string") {
      r.content += warning
      return
    }
    if (Array.isArray(r.content)) {
      r.content.push({ type: "text", text: warning })
      return
    }
    if (typeof r.output === "string") {
      r.output += warning
      return
    }
  }
  const output = event?.output
  if (output && typeof output === "object") {
    const o = output as { output?: unknown }
    if (typeof o.output === "string") o.output += warning
  }
}

/** Pure-ish seam for the reception suite: returns the warning text the after
 * hook would append for this event, or null (no warning). `pending` lets a
 * test supply its own write-snapshot map; defaults to a fresh one. */
export function scanToolCall(
  event: V2ToolHookEvent,
  pending?: Map<string, PendingWrite>,
): string | null {
  const map = pending ?? new Map<string, PendingWrite>()
  const callID = String(event?.id ?? "")
  const snapshot = callID ? map.get(callID) ?? null : null
  const probe = { ...event, result: { content: "" } } as V2ToolHookEvent
  scanAndWarn(probe, snapshot, callID, map)
  const text = probe.result?.content
  return typeof text === "string" && text.length > 0 ? text : null
}

/** Shared core: consume the snapshot, scan the call, append the advisory to
 * the live result. Never throws (callers wrap in try/catch). */
function scanAndWarn(
  event: V2ToolHookEvent,
  snapshot: PendingWrite | null,
  callID: string,
  map: Map<string, PendingWrite>,
): void {
  const tool = String(event?.tool ?? "").toLowerCase()
  if (tool !== "edit" && tool !== "write") return
  if (callID) map.delete(callID)
  if (String(event?.status ?? "") === "error") return
  const args = event?.input
  if (!args || typeof args !== "object") return
  const record = args as Record<string, unknown>
  const path = argsString(record, ["path", "filePath", "file_path"])
  if (!path || !isScannablePath(path)) return
  const kind = markersForPath(path)
  if (!kind) return
  if (snapshot && snapshot.skipScan) return

  let added: string[] | null = null
  if (tool === "edit") {
    const oldStr = argsString(record, ["oldString", "old_string", "oldText"])
    const newStr = argsString(record, ["newString", "new_string", "newText"])
    if (oldStr === null || newStr === null) return
    added = addedLinesBetween(oldStr.split("\n"), newStr.split("\n"))
  } else {
    const content = argsString(record, ["content", "file_content", "contents"])
    if (content === null) return
    const oldLines =
      snapshot && typeof snapshot.oldContent === "string" ? snapshot.oldContent.split("\n") : []
    added = addedLinesBetween(oldLines, content.split("\n"))
  }

  const findings = scanAddedLines(added, kind)
  if (findings.length === 0) return
  persistWarning(event, buildWarning(findings, path))
}

function handleAfter(event: V2ToolHookEvent): void {
  const callID = String(event?.id ?? "")
  const snapshot = callID ? pendingWrites.get(callID) ?? null : null
  scanAndWarn(event, snapshot, callID, pendingWrites)
}

const antislopHookPlugin = {
  id: "antislop-hook",
  setup: async (ctx: V2SetupContext) => {
    if (!ctx?.tool?.hook) {
      console.warn("[antislop-hook] tool hooks unavailable — plugin disabled")
      return
    }
    const regBefore = await ctx.tool.hook("execute.before", (event) => {
      try {
        const tool = String(event?.tool ?? "").toLowerCase()
        if (tool !== "write") return
        const callID = String(event?.id ?? "")
        if (!callID) return
        const args = event?.input
        if (!args || typeof args !== "object") return
        const record = args as Record<string, unknown>
        const path = argsString(record, ["path", "filePath", "file_path"])
        if (!path || !isScannablePath(path)) return
        // Relative paths resolve against the opencode process cwd (project root).
        let oldContent: string | null = null
        let skipScan = false
        try {
          const stat = statSync(path)
          if (stat.size > MAX_SCAN_BYTES) {
            skipScan = true
          } else {
            oldContent = readFileSync(path, "utf8")
          }
        } catch (err) {
          if ((err as NodeJS.ErrnoException)?.code === "ENOENT") {
            oldContent = null // new file: every comment line is added
          } else {
            skipScan = true // unreadable (perms, cwd drift): no diff basis, fail-open
          }
        }
        evictPending()
        pendingWrites.set(callID, { path, oldContent, skipScan })
      } catch {
        // fail-open — advisory must never break a write
      }
    })
    const regAfter = await ctx.tool.hook("execute.after", (event) => {
      try {
        handleAfter(event)
      } catch {
        // fail-open
      }
    })
    return () => {
      regBefore?.dispose()
      regAfter?.dispose()
    }
  },
}

export default antislopHookPlugin
