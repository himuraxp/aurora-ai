# Workflow — How the work cycle works

## The universal cycle

Every AI session imperatively follows the cycle defined in `standards/workflow.md`:

```txt
Explore → Plan → Implement → [PARALLEL GATE] → Commit
                              ├── Review (adversarial)
                              └── Verify (build + lint + test)
```

### Session-start reading

Mandatory order when `docs/ai/` is discovered:

```txt
1. STATUS.md   → current state, blockers, next step
2. PLAN.md     → current plan
3. WARNINGS.md → active alerts before touching anything
4. INDEX.md    → understand the project structure without scanning
5. BUFFER.md   → only when resuming an interrupted session, blocker, or explicit request
```

Aurora automatically detects `docs/ai/` at startup and applies this order without any configuration in `AGENTS.md`.

### Session-end update

Aurora systematically updates the 7 files of `docs/ai/` (per `standards/memory-auto-update.md`):

```txt
1. STATUS.md     → summarize work done, in progress, blocked, next action
2. PLAN.md       → check completed steps, update the status
3. CHANGELOG.md  → dated entry of significant changes
4. INDEX.md      → add key modules/files discovered
5. BUFFER.md     → recovery snapshot, empty temporary notes
6. WARNINGS.md   → add sensitive zones and debt identified
7. DECISIONS.md  → document architectural decisions made
```

### Delegation and output format

When Aurora delegates to a subagent via `task`, the subagent MUST return a result in the structured JSON format defined in `standards/agent-output.md`. Aurora parses, consolidates and displays results deterministically. A response without JSON is a partial failure (see `standards/delegation-failure.md`).

### Use INDEX.md to avoid global scans

- Before searching the project, check whether `INDEX.md` already contains the target module/file.
- Never scan the whole codebase if a targeted search or INDEX.md is enough.
- Update INDEX.md only if the project structure changes significantly.

### Manage BUFFER.md

- Use for micro-decisions made during the session, out-of-scope discoveries, the snapshot if interrupted.
- Empty or archive at session end if resolved or empty.
- **Promote any persistent risk** from `BUFFER.md` to `WARNINGS.md`.
- Never put micro-decisions in `DECISIONS.md`.

### Explore

Read the existing code before any change. Identify:
- The impacted files
- The conventions in force
- The existing patterns
- The dangerous zones via `WARNINGS.md`

**Never implement directly without understanding the context.**

### Plan

If the change touches more than 2 files, a plan is mandatory.

The plan must contain:
- Goal
- Impacted files
- Risks
- Expected tests
- Status: `pending`, `in-progress`, `implemented`, `reviewed` or `blocked`

Store it in `docs/ai/PLAN.md`.

### Implement

- One logical change at a time
- Incremental work
- Preserve existing behaviors
- Never break the build on purpose

### Review

Before declaring done, run an adversarial review on three axes:

- **Code**: correctness, maintainability, security, conventions
- **Functional**: plan compliance, acceptance criteria, edge cases
- **Relevance**: meets the real need, no out-of-scope, no over-engineering

The plan only moves to `reviewed` after review and checks.

### Verify

Before declaring a task done, systematically run:

```bash
build
lint
test
```

Never claim a change works without executable proof.

### Commit

- One logical change per commit
- Format: `type(scope): summary`
- Never commit with a broken build or failing tests

## Work modes

### EXECUTION mode (default)

Apply the plan. Modify files within scope, verify, document deviations in `BUFFER.md`.

### BRAINSTORM mode

Design only. No code modified. Allowed to modify `PLAN.md`, `DECISIONS.md`, `INDEX.md`. Exit when the plan is validated.

### AUDIT mode

Read-only diagnosis. No code modified. Choose the relevant axes: quality, architecture, security, dependencies, performance, tests, UI/accessibility. Produce a prioritized report with evidence.

## Common anti-patterns

- ❌ Implement without reading the existing code
- ❌ Modify 10 files without a plan
- ❌ Declare done without checks
- ❌ Declare done without an adversarial review
- ❌ Fix code during a read-only audit
- ❌ Commit with failing tests
- ❌ Scan the whole project if INDEX.md is enough
- ❌ Put micro-decisions in DECISIONS.md
- ❌ Read a `.new` file automatically (manual merge proposals only)
