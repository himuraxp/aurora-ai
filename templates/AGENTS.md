# AGENTS.md — Project

This file is the source of truth for agents working on this project.

## Role of this file

Aurora automatically loads the global standards and discovers `docs/ai/` without additional configuration.
This file does **not** need to duplicate the memory logic (reading order, document roles...).

Focus here on:

- **Business context**: product, users, constraints.
- **Specific rules**: conventions not covered by the global standards.
- **Local conventions**: architecture, naming, preferred patterns.
- **Project exceptions**: temporary deviations or risk zones specific to this project.

## Project goal

Describe here the product, the business context and the main constraints.

## General rules

- Respect the existing style.
- Keep changes targeted.
- No unrequested massive refactoring.
- No dependency added without clear justification.
- Preserve existing behaviors.
- Add or adapt tests when the logic changes.
- Always favor a simple, maintainable and readable solution.
- Never read huge files wholesale if a targeted search is enough.
- Use `INDEX.md` to understand where to look before scanning the project.
- Don't pollute `DECISIONS.md` with temporary micro-decisions.
- **Run an adversarial review before declaring a task done**.
- **Stop and reset after 2 failed corrections** on the same problem.
- **Recognize anti-patterns** (catch-all session, over-specified config, infinite exploration, etc.) and apply the correction immediately.

## Global standards

The following standards are loaded automatically by the main agent (Aurora):

- **workflow**: Explore → Plan → Implement → [PARALLEL GATE] → Commit cycle (Review + Verify in parallel)
- **verification**: mandatory build/lint/test checks before considering a task done
- **communication**: directness, ownership, constructive pushback, markdown output format
- **escalation**: blocker handling and clean stop
- **commits**: commit format and rules
- **review-before-done**: mandatory adversarial review before declaring done (4 axes: code, functional, relevance, markdown)
- **audit**: multi-axis read-only audit for health-checks and technical debt
- **exploration-limits**: scope the investigations, use subagents for heavy exploration
- **error-correction**: reset after 2 failed corrections, never fix without a root cause
- **anti-patterns**: recognize and stop the 5 common failure patterns
- **artifact-authoring**: consistent authoring of standards, agents, frameworks and templates
- **delegation-failure**: mandatory procedure after subagent failure
- **agent-output**: structured JSON output format for subagents

These standards are stored in `~/.config/opencode/standards/` by the global installation.

## Work modes

### EXECUTION mode (default)

Goal: apply the existing plan.

Rules:
- Modify only the files within scope.
- Verify build/lint/test after each logical change.
- Document deviations in `BUFFER.md`.
- Stop immediately if contradicted by `DECISIONS.md` or `WARNINGS.md`.
- Consult `INDEX.md` before touching a file unknown to the project.
- **Run an adversarial review before considering the task done** via subagent or the `code-review` skill.
- **Stop and reset after 2 failed corrections** on the same problem (see global standard `error-correction.md`).

### BRAINSTORM mode

Goal: design, plan, architect.

Rules:
- No source code modification.
- Documentation, architecture and planning only.
- Allowed to modify: `PLAN.md`, `DECISIONS.md`, `INDEX.md`.
- Exit the mode when the plan is validated and clear.

### AUDIT mode

Goal: diagnose without modifying.

Rules:
- Read `INDEX.md` and `WARNINGS.md` before exploring.
- Choose the relevant axes: quality, architecture, security, dependencies, performance, tests, UI/accessibility.
- Produce a prioritized report with evidence.
- Do not fix during the audit; propose a separate action plan.
- **Exception**: SEO/AIO/Growth audits are delegated to the specialist agents (Atlas, Crawler, Sage, Pulse, Beacon) — see the global `AGENTS.md` "Search & Growth Agents" section.

## AI Documentation

Aurora detects `docs/ai/` at startup and applies the reading order defined in the global standards (`~/.config/opencode/standards/memory-session-flow.md`). The update (persistence) order is defined in `memory-auto-update.md` and the verification in `memory-checklist.md`.
The local AGENTS.md does **not** need to repeat these rules.

## Framework / Stack

Describe here the project-specific technical conventions, or reference a global standard in `~/.config/opencode/frameworks/`.

Examples:

- Angular: apply `frameworks/angular-20.md`.
- Node.js API: apply `frameworks/nodejs.md`.
- NestJS: apply `frameworks/nestjs.md`.
- Astro: apply `frameworks/astro.md`.

## Expected workflow

For a complex task:

1. Read the existing context (docs/ai/ then INDEX.md).
2. Identify the impacted files.
3. Propose a short plan (for >2 files).
4. Implement with small changes.
5. Run an adversarial review if code or rules change.
6. Run or point to the relevant tests.
7. Clearly summarize the modifications.
