---
name: antislop-code
description: "Zero-comment default for AI coding agents: code must be self-explanatory — no comments in written code, the only exceptions being mathematical reasoning and complex logic. Also detects and strips AI-slop comments when editing existing code. Use when writing or editing code, comments, JSDoc, docstrings, or TODOs. Load with the core."
allowed-tools: Read Write Edit Glob Grep
---
<!-- Vendored from https://github.com/miqdadbadjuber/anti-slop v3.2.21 (skills/antislop-code/SKILL.md).
     Adaptations (re-apply on every upstream resync):
     - upstream `antislop.md` self-references repointed to the vendored core
       `skills/antislop/SKILL.md` (2026-10-22)
     - frontmatter `description` extended with trigger phrases (2026-10-26)
     - 2026-11-09 operator override: the upstream "Not a Ban (preserve these)"
       section is REMOVED and superseded by the "Zero-Comment Default" contract.
       Generated code must contain no comments except mathematical reasoning and
       complex logic. Fix lines of the upstream pattern sections hardened to
       "remove". This override is the operator's standing directive — never
       revert it during a resync. -->
# antislop-code

> Anti Slop: Rules for AI Coding Agents. Code Comments skill — zero-comment default.

> Part of the antislop system. Read together with the `antislop` core skill (`skills/antislop/SKILL.md`). The core holds the mechanism (the purpose test, the three tiers, the Delivery Gate); this skill holds the comment contract. It references core rules by number and never duplicates or renumbers them. Load it when the task writes or edits code comments.

## Zero-Comment Default (governs everything below)

The default is **zero comments**. Assume the code is already expressive enough: if a reader needs a comment to understand a line, first try a better name, a clearer structure, a type, a test, or a smaller function — the code should carry the meaning.

A comment is an exception, not a decoration. Before writing one, pass the **two-question test**:

1. **Is this mathematical reasoning or complex-logic intent?** If no — do not write the comment.
2. **Could a name, a type, or a small extraction carry this — or is it a one-off rationale for a commit message or PR description?** If yes — do not write it. A permanent fact, by contrast, lives next to the code: that is the complex-logic exception.

Both answers must survive scrutiny before a comment exists. When in doubt, write no comment.

## The Only Permitted Comments

Two categories. Everything else is forbidden in written code.

### 1. Mathematical reasoning

Formula derivations, sources of magic constants, proof sketches, unit or precision subtleties, complexity bounds — anything the formula hides.

```ts
// 0.2126 / 0.7152 / 0.0722: linear-light Rec. 709 luminance weights (ITU-R BT.709).
const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
```

### 2. Complex-logic intent

Non-obvious invariants, algorithm assumptions, behavioral traps the code cannot show — facts that prevent a real bug if the code is "simplified" by the next reader.

```js
// Stripe may retry webhook deliveries for up to three days; duplicates are legal.
```

Rules for both:

- **One line; two only when the second carries a new fact.** Never three — except mathematical derivation (category 1 above), kept to the strict minimum it genuinely requires.
- **Why, not what.** The comment explains the reasoning or the trap, never restates the code.
- **No narration**: no `// Step 1:`, no `// First...`, no per-line commentary.
- **No TODOs in code.** A TODO is a task — it belongs to the issue tracker, not to a comment.
- **No JSDoc/docstring echo.** Signature-restating documentation is banned; write none.

## Where the "Why" Goes Instead

A comment is not a dump for context. Under this contract, the reason behind a change lives outside the code:

- **Commit message** — why the change exists, the constraint behind it, the trade-off chosen.
- **PR/MR description** — business context, architectural decision, alternatives rejected.
- **Project docs** (`docs/`, `docs/ai/DECISIONS.md`, README) — durable decisions and contracts.
- **The code itself** — for values a name can fully capture, a named constant `STRIPE_RETRY_WINDOW_DAYS = 3` beats a comment; the constant's mathematical *source* is exception 1 and may legitimately be a comment.

If the "why" cannot go in any of these places, that is a reason to reconsider the change, not to write a comment.

## Carve-outs (a comment may exist here, despite the default)

- **Project conventions win** (golden rule): if the local `AGENTS.md` or the codebase requires docstrings, license headers, copyright notices, or generated-code markers, follow the project — the zero-comment default never overrides a local convention. Where to spot them: the project's `AGENTS.md` or `CONTRIBUTING`, the linter configuration (eslint-plugin-jsdoc, pydocstyle, …), and the docstring density of the module being edited — ask the author when in doubt.
- **Functional JSDoc tags** (`@deprecated`, `@throws`, `@internal`): these are machine-consumed metadata (IDEs, linters, documentation generators), not comments under this contract — they stay on the symbol.
- **The two whitelist categories above.** Nothing else.

## Editing Existing Code

- **Never add** a comment outside the whitelist, even when the surrounding code has many.
- **Remove slop you touch**: when the edit rewrites a line or block that carries a slop comment (patterns below), delete the comment in the same edit.
- **No drive-by stripping**: do not purge comments from untouched parts of a file — mass comment removals create review noise and mix refactoring into targeted fixes. Cleanup en masse only when the task explicitly asks for it.
- **Prefer migration**: when deleting a comment that holds a real fact, move that fact to the commit message or PR description — information is relocated, not destroyed.

## Slop Patterns (detection — what you must never write, and must strip when touched)

Each entry: **Tell** (the pattern), **Why** (why it reads as slop), **Fix** (always remove, under this contract).

### Decorative Separators

- **Tell:** banner comments built from repeated characters, ALL CAPS labels, or box drawing: `// =======================` around `Authentication`, `// -------- WORKFLOW --------`, `/* ---- ROUTES ---- */`.
- **Why:** the decoration is the message. A label wrapped in `=` or `-` signals "AI made this" without adding information.
- **Fix:** remove entirely (R-31).

### Restating the Obvious

- **Tell:** `// Initialize the variable` above `let count = 0`, `// User class` above `class User {}`, `const userAge = 25; // User age is 25`.
- **Why:** it doubles the reading load without adding anything. The code already says it.
- **Fix:** remove.

### Workflow Narration

- **Tell:** `// Step 1: Validate input`, `// Step 2: Process request`, `// First...`, `// Next...`, `// Finally...`.
- **Why:** the control flow is visible in the code itself. Numbering it reads as a checklist, not an explanation.
- **Fix:** remove. If the flow is genuinely hard to follow, that is a structure problem — restructure the code.

### Empty Labels

- **Tell:** `// Main logic`, `// Core logic`, `// Helper function`, `// Entry point`, `// Error handling`, `// Note: This is important.`
- **Why:** the label names a category, not a fact. It tells the reader nothing the code does not.
- **Fix:** remove.

### Vague Placeholders

- **Tell:** `// TODO: Improve this`, `// Future improvements`, `// Additional optimization can be added here`, `// Add more validation`.
- **Why:** a vague TODO names a feeling instead of a task.
- **Fix:** remove. All TODOs go to the issue tracker.

### Signature Echo

- **Tell:** JSDoc/docstring blocks that repeat `@param price The price.`, `@returns Total price.` for a function whose name and parameters already say it.
- **Why:** docs that echo the signature add length, not understanding.
- **Fix:** remove. Real documentation of API contracts belongs to project docs, not to echo blocks.

### Decorative Emoji

- **Tell:** `// ✅ Validation`, `// 🚀 Performance`.
- **Why:** visual noise in code; the specific set (✅, 🚀, 🔒) is the AI default vocabulary.
- **Fix:** remove.

### End Markers

- **Tell:** `} // end if`, `# End of function`, `// End processOrder`.
- **Why:** the closing brace already ends the block.
- **Fix:** remove.

### Over-Explained Comments

- **Tell:** a multi-line block stacking reasons, context, and history around a fact that fits in one line: a four-line paragraph explaining that a stub sits on PATH, which release introduced the workaround, and what broke before it.
- **Why:** padding a one-line fact into a paragraph buries the line that matters under the lines that do not.
- **Fix:** cut to the constraint alone — one line, two at most — and only if it passes the two-question test. The issue number, the version history, and the reasoning chain go to the commit message or PR description.

### Line-by-Line Narration

- **Tell:** `// Initialize count`, then `// Loop items`, then `// Get item`, then `// Increment`, then `// Return result`.
- **Why:** when every line is commented, none of the comments matter.
- **Fix:** remove entirely. A "one comment per logical block" habit still produces comments that fail the two-question test.

### Stiff or Loud Wording

- **Tell:** "This function is responsible for validating whether the supplied credentials are valid before continuing with the authentication process", or `// MAIN LOGIC` in caps.
- **Why:** formal and loud wording reads as generated, not as an engineer leaving a note.
- **Fix:** remove. A surviving whitelist comment reads short, sentence-case, natural.

## Zero-Comment Checklist

Run alongside the core Delivery Gate when the task touches code. All answers must be **yes**:

- [ ] Did I write **zero** new comments outside the two permitted categories? (Zero-Comment Default)
- [ ] Does every remaining comment pass the whitelist: mathematical reasoning or complex-logic intent only?
- [ ] Did every comment pass the two-question test (a one-off rationale is carried by the commit/PR; a permanent fact lives next to the code under the whitelist)?
- [ ] Are surviving comments one line (two max — mathematical derivation: as long as the derivation genuinely requires), short, sentence case?
- [ ] Did every removed "why" land somewhere durable (commit message, PR description, project docs) rather than being deleted?
- [ ] Are there zero TODO comments in written code (tasks live in the tracker)?
- [ ] Did I respect local conventions (project-required docstrings, license headers, generated markers)?
- [ ] When editing existing code: no drive-by stripping of comments in untouched lines?
- [ ] Is the code itself self-explanatory: names, types, structure, tests carry the meaning?
