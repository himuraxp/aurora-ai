---
name: "code-review"
description: Adversarial code review that forces to find real issues instead of rubber-stamping. Use when the user wants to review code or get critical feedback on their changes.
---

# Adversarial Code Review

A review technique where you **must** find issues. No "looks good" allowed. Assume problems exist — your job is to find them.

**Core rule:** Zero findings = re-analyze. If you genuinely find nothing, explain precisely why each category was checked and came up clean.

## Step 1 — Get the diff

~~~bash
git diff main || git diff master
# or if main isn't the base:
git diff $(git merge-base HEAD origin/main) || git diff $(git merge-base HEAD origin/master)
~~~

Also check:
~~~bash
git status          # untracked or unstaged files
git log --oneline origin/main..HEAD  # commits in this branch
~~~

## Step 2 — Architectural review

Before diving into line-by-line issues, zoom out and assess the shape of the changes:

- **Scope creep** — Does this PR do one thing, or many? Should it be split?
- **Wrong abstraction** — Is the solution overly complex for the problem? Is it solving the right problem?
- **Coupling** — Do these changes introduce tight coupling between modules that should be independent?
- **Boundaries** — Are responsibilities well-separated? Does logic land in the right layer (e.g. business logic leaking into controllers)?
- **Reversibility** — Are there breaking changes, schema migrations, or API changes that can't easily be undone?
- **Missing pieces** — Does this change imply other changes that aren't here? (e.g. a new endpoint with no auth, a DB change with no migration)

## Step 3 — Analyze across every category

Go through every relevant category for the codebase at hand. Don't skip any. Think broadly — security, error handling, logic, missing code, performance, consistency, maintainability, and anything else that applies.

**Key question for each file:** *What's missing here, not just what's wrong?*

## Step 4 — Output format

Report findings grouped by severity. Always include file + line number.

~~~
## Review — <branch name>

### 🏗️ Architecture
- The change mixes concerns X and Y — consider splitting into two PRs.
- New `UserService` duplicates logic already in `AuthService`.

### 🔴 HIGH
1. `path/to/file.ts:47` — No rate limiting on failed attempts. Brute-force possible.
2. `path/to/auth.ts:12` — JWT secret hardcoded. Rotate immediately.

### 🟡 MEDIUM  
3. `path/to/api.ts:89` — Missing input validation on `userId`. Accepts arbitrary strings.

### 🔵 LOW
4. `path/to/utils.ts:23` — Magic number `3600` should be `SESSION_TIMEOUT_SECONDS`.

---
**Summary:** X architectural concerns, X high, X medium, X low findings.
**Recommended before merge:** Fix all HIGH, review MEDIUM, consider architectural notes.
~~~

## Step 5 — Iterate if asked

A second pass after fixes often catches more. A third is usually diminishing returns.
Offer a re-review after the user addresses HIGH findings.

## Important

- The AI is instructed to find problems — expect occasional false positives
- The human decides what's real: review each finding, dismiss noise, fix what matters
- Never approve with "looks good" — if something is genuinely clean, explain *why* per category