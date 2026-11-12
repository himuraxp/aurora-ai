#!/usr/bin/env node
/**
 * test-antislop-hook.mjs — Reception suite for the antislop-hook plugin
 * (pure logic, no OpenCode runtime required).
 *
 * Covers: slop classification per category (banner, narration, empty label,
 * vague TODO, emoji, end marker, caps, stiff wording, signature echo),
 * FALSE-POSITIVE guards (the no-slop-comments "preserve" list: workarounds,
 * constraints, specific TODOs, PEM markers, eslint directives),
 * comment extraction (block state, JSDoc stars, quote parity, shebang),
 * multiset line diff, path allowlist, warning rendering (cap + marker).
 *
 * Run: node scripts/test-antislop-hook.mjs   (node >= 22;
 *      add --experimental-strip-types on node 22)
 */

import assert from "node:assert/strict"
import {
  addedLinesBetween,
  buildWarning,
  classifyComment,
  commentTextsFrom,
  isScannablePath,
  markersForPath,
  scanAddedLines,
  scanToolCall,
} from "../config/plugins/antislop-hook.ts"

// 1. Classification: slop detected (per no-slop-comments category)

assert.equal(classifyComment("Step 1: Validate input"), "workflow narration")
assert.equal(classifyComment("step 2) process request"), "workflow narration")
assert.equal(classifyComment("First, load the config"), "workflow narration")
assert.equal(classifyComment("Next, fetch the user"), "workflow narration")
assert.equal(classifyComment("Finally, return the response"), "workflow narration")

assert.equal(classifyComment("==============="), "decorative separator")
assert.equal(classifyComment("-----"), "decorative separator")
assert.equal(classifyComment("---- Routes ----"), "decorative separator")
assert.equal(classifyComment("===== API ====="), "decorative separator")

assert.equal(classifyComment("Main logic"), "empty label")
assert.equal(classifyComment("Core logic"), "empty label")
assert.equal(classifyComment("helper functions"), "empty label")
assert.equal(classifyComment("Error handling"), "empty label")
assert.equal(classifyComment("constants"), "empty label")
assert.equal(classifyComment("init"), "empty label")

assert.equal(classifyComment("TODO"), "vague placeholder")
assert.equal(classifyComment("TODO: improve this"), "vague placeholder")
assert.equal(classifyComment("TODO: refactor"), "vague placeholder")
assert.equal(classifyComment("Add more validation"), "vague placeholder")
assert.equal(classifyComment("Add more validation here"), "vague placeholder")
assert.equal(classifyComment("future improvements"), "vague placeholder")
assert.equal(classifyComment("not implemented yet"), "vague placeholder")
assert.equal(classifyComment("TODO: handle later"), "vague placeholder")

assert.equal(classifyComment("✅ Validation"), "decorative emoji")
assert.equal(classifyComment("🚀 Performance"), "decorative emoji")

assert.equal(classifyComment("end if"), "end marker")
assert.equal(classifyComment("End of function"), "end marker")
// Trailing end-marker through the real extraction path (review F-07).
const trailingEnd = commentTextsFrom(["} // end if"], "slash")
assert.deepEqual(trailingEnd, ["end if"])
assert.equal(classifyComment(trailingEnd[0]), "end marker")

assert.equal(classifyComment("MAIN LOGIC"), "empty label") // anchored label wins over caps
assert.equal(classifyComment("WORKFLOW"), "shouting label")

assert.equal(
  classifyComment("This function is responsible for validating the credentials"),
  "over-formal wording",
)
assert.equal(classifyComment("In order to validate, we call X"), "over-formal wording")
assert.equal(classifyComment("Let's define the model"), "over-formal wording")
assert.equal(
  classifyComment("Here's the updated component"),
  null,
  "F-04: 'here's' wording removed from STIFF — can carry real content",
)

assert.equal(classifyComment("@param price The price."), "signature echo")
assert.equal(classifyComment("@param price price"), "signature echo")
assert.equal(classifyComment("@param {number} price - The price"), "signature echo")

// 2. Classification: PRESERVE list — legitimate comments must pass

assert.equal(
  classifyComment("Stripe may retry webhook deliveries for up to three days."),
  null,
)
assert.equal(classifyComment("Ignore duplicate events using the event ID."), null)
assert.equal(classifyComment("Validate credentials before issuing a token."), null)
assert.equal(classifyComment("Retry only on 5xx — the API throttles bursts."), null)
assert.equal(classifyComment("NOTE: retries happen only on 5xx"), null)
assert.equal(classifyComment("Legacy parser: do NOT change the column order."), null)
assert.equal(classifyComment("TODO(ym): handle 429 with exponential backoff"), null)
assert.equal(classifyComment("TODO: implement rate limiting (429s)"), null)
assert.equal(classifyComment("TODO: fix the race in the retry loop"), null)
assert.equal(classifyComment("TODO: extract into a shared module once auth ships"), null)
assert.equal(classifyComment("Add validation for retry paths"), null)
assert.equal(classifyComment("This is the user's display name"), null)
assert.equal(classifyComment("-----BEGIN CERTIFICATE-----"), null)
assert.equal(classifyComment("-----END PRIVATE KEY-----"), null)
assert.equal(classifyComment("end of the legacy support window — do not remove"), null)
assert.equal(classifyComment("50"), null)
assert.equal(classifyComment("multiplier applied before rounding"), null)
assert.equal(classifyComment("IMPORTANT: the token is single-use"), null)
assert.equal(classifyComment("eslint-disable-next-line no-console"), null)

// Boundary cases pinned after the adversarial review (F-01/F-02/F-04/F-05).
assert.equal(classifyComment("RFC 5322"), null, "protocol ref, numeric token")
assert.equal(classifyComment("HTTP 204"), null, "protocol ref, numeric token")
assert.equal(classifyComment("─".repeat(3) + " Routes " + "─".repeat(3)), "decorative separator")
assert.equal(classifyComment("── Section ──"), "decorative separator", "box drawing caught")
assert.equal(
  classifyComment("Here's how the retry loop avoids the thundering herd"),
  null,
  "heredoc explanation, not stiff wording",
)
assert.equal(
  classifyComment("First, dedupe by event ID; the API retries deliveries"),
  null,
  "long ordering constraint, not narration",
)
assert.equal(classifyComment("Step 1.5: interleave"), "workflow narration")
assert.equal(classifyComment("Setup: see docs/auth.md"), null, "pointer, not empty label")
assert.equal(classifyComment("# ---- DB ----".replace(/^#\s*/, "")), "decorative separator")

// ── 3. Extraction: block state, JSDoc stars, trailing parity, shebang ──────

// Block comment opened and closed across lines (empty fragments filtered).
assert.deepEqual(commentTextsFrom(["/* one", " * two", " */"], "slash"), ["one", "two"])

// JSDoc stars stripped; classification sees the directive only.
assert.deepEqual(
  commentTextsFrom(["/**", " * Step 1: load", " */"], "slash"),
  ["Step 1: load"],
)

// `//` inside a string literal is NOT a comment (odd quote parity before it).
assert.deepEqual(
  commentTextsFrom(['const url = "https://example.com"'], "slash"),
  [],
)
// Trailing comment after a string literal IS extracted (even parity).
assert.deepEqual(
  commentTextsFrom(['const url = "https://example.com" // prod endpoint'], "slash"),
  ["prod endpoint"],
)

// Shebang never scanned; plain `#` trailing comment in YAML is.
assert.deepEqual(commentTextsFrom(["#!/usr/bin/env node"], "hash"), [])
assert.deepEqual(
  commentTextsFrom(["retries: 3  # match API contract"], "hash"),
  ["match API contract"],
)
// `#` inside an unquoted URL value (no whitespace before) is skipped.
assert.deepEqual(commentTextsFrom(["base: http://x#frag"], "hash"), [])

// SQL line comments.
assert.deepEqual(commentTextsFrom(["-- main query"], "dash"), ["main query"])

// 4. Multiset line diff: duplicates matched by count

assert.deepEqual(addedLinesBetween(["a", "b"], ["a", "b", "c"]), ["c"])
// One kept `x`, the second occurrence is added.
assert.deepEqual(addedLinesBetween(["x"], ["x", "x"]), ["x"])
// Nothing added when content is unchanged.
assert.deepEqual(addedLinesBetween(["a", "a"], ["a", "a"]), [])

// 5. End-to-end scan of an added block

const slopBlock = [
  "function load() {",
  "  // Step 1: read config",
  "  const config = readConfig()",
  "  // ---- helpers ----",
  "  const help = noop()",
  "}",
]
assert.deepEqual(scanAddedLines(slopBlock, "slash"), [
  { text: "Step 1: read config", category: "workflow narration" },
  { text: "---- helpers ----", category: "decorative separator" },
])

// 6. Path allowlist

assert.equal(markersForPath("src/app.ts"), "slash")
assert.equal(markersForPath("conf/service.yml"), "hash")
assert.equal(markersForPath("db/migrations/001.sql"), "dash")
assert.equal(markersForPath("Dockerfile"), "hash")
assert.equal(markersForPath("Makefile"), "hash")
assert.equal(markersForPath("docs/readme.md"), null)
assert.equal(markersForPath("data.json"), null)

assert.ok(isScannablePath("src/index.ts"))
assert.ok(isScannablePath("scripts/deploy.sh"))
assert.ok(!isScannablePath("node_modules/pkg/index.js"))
assert.ok(!isScannablePath("dist/bundle.js"))
assert.ok(!isScannablePath("docs/guide.md"))
assert.ok(!isScannablePath("assets/logo.svg"))

// 7. Warning rendering: marker, cap, snippet truncation

const warning = buildWarning(
  [
    { text: "Step 1: read config", category: "workflow narration" },
    { text: "---- helpers ----", category: "decorative separator" },
  ],
  "src/app.ts",
)
assert.ok(warning.includes("[antislop-hook]"), "hook marker present")
assert.ok(warning.includes("2 slop comments"), "count with plural")
assert.ok(warning.includes("src/app.ts"), "file path echoed")
assert.ok(warning.includes("advisory"), "advisory semantics stated")

const many = Array.from({ length: 7 }, (_, i) => ({
  text: `TODO: filler ${i}`,
  category: "vague placeholder",
}))
const capped = buildWarning(many, "a.py")
assert.ok(capped.includes("… and 3 more"), "cap at 4 shown + overflow line")

const truncated = buildWarning([{ text: "x".repeat(200), category: "empty label" }], "a.py")
assert.ok(truncated.length < 400, "snippet truncated to keep the warning short")

// 8. Hook wiring seam (scanToolCall): tool filter, arg aliases, error skip,
//    write snapshot diff, skipScan, path filter.

const slopEdit = {
  tool: "edit",
  id: "c2",
  input: { path: "src/a.ts", oldString: "const a = 1", newString: "const a = 1\n// Step 1: init" },
}
const slopEditWarning = scanToolCall(slopEdit)
assert.ok(slopEditWarning?.includes("[antislop-hook]"), "slop edit produces the advisory")
assert.ok(slopEditWarning?.includes("Step 1: init"), "offending comment echoed in warning")

// snake_case arg aliases (runtime variants).
const aliasEdit = {
  tool: "edit",
  id: "c2b",
  input: { path: "src/a.ts", old_string: "x", new_string: "x\n// Step 1: init" },
}
assert.ok(scanToolCall(aliasEdit)?.includes("[antislop-hook]"), "snake_case args accepted")

// Clean edit → no warning.
assert.equal(
  scanToolCall({
    tool: "edit",
    id: "c2c",
    input: { path: "src/a.ts", oldString: "x", newString: "x\n// retry only on 5xx" },
  }),
  null,
)

// Non-edit tool never scanned.
assert.equal(scanToolCall({ tool: "bash", id: "c1", input: {} }), null)

// Errored call skipped (and snapshot consumed).
assert.equal(
  scanToolCall({
    ...slopEdit,
    id: "c4",
    status: "error",
  }),
  null,
)

// Write with snapshot: only ADDED lines scanned (pre-existing comment kept).
const pending = new Map([
  ["c3", { path: "src/a.ts", oldContent: "// kept note\nconst x = 1", skipScan: false }],
])
const writeWarning = scanToolCall(
  {
    tool: "write",
    id: "c3",
    input: { path: "src/a.ts", content: "// kept note\nconst x = 1\n// TODO: improve this" },
  },
  pending,
)
assert.ok(writeWarning?.includes("TODO: improve this"), "added slop comment flagged")
assert.ok(!writeWarning?.includes("kept note"), "pre-existing comment not re-flagged")
assert.ok(!pending.has("c3"), "snapshot consumed after the call")

// Write WITHOUT snapshot (new file): every comment line is a candidate.
assert.ok(
  scanToolCall({
    tool: "write",
    id: "c5",
    input: { path: "src/new.ts", content: "const x = 1\n// Step 2: load" },
  })?.includes("[antislop-hook]"),
)

// skipScan (oversized/unreadable file): no scan, no warning.
const skipped = new Map([["c6", { path: "src/big.ts", oldContent: null, skipScan: true }]])
assert.equal(
  scanToolCall(
    { tool: "write", id: "c6", input: { path: "src/big.ts", content: "// Step 1: x" } },
    skipped,
  ),
  null,
)

// Non-scannable path (docs/data formats) never warned.
assert.equal(
  scanToolCall({
    tool: "edit",
    id: "c7",
    input: { path: "docs/guide.md", oldString: "x", newString: "x\n// Step 1: init" },
  }),
  null,
)

console.log("antislop-hook reception suite: all assertions passed")
