# standards/

> **Language note:** the standard rule files referenced here are written in French — the maintainer's working language. The agent runtime consumes them language-agnostically, so behavior is unaffected. Public-facing docs: the [root README](../README.md) and [`docs/`](../docs/).

Universal behaviors applied systematically by Aurora and all sub-agents. These standards define the work cycle, communication rules, verification, memory and error handling.

## Standards

### Work cycle

| Standard | Description |
|----------|-------------|
| `workflow.md` | Full cycle: Explore → Plan → Implement → Parallel Gate (Review + Verify) → Commit |
| `verification.md` | Mandatory build/lint/test checks before sign-off |
| `review-before-done.md` | Adversarial review before declaring a task done |

### Communication & style

| Standard | Description |
|----------|-------------|
| `communication.md` | Response style — direct, concise, structured, action-oriented |

### Project memory

| Standard | Description |
|----------|-------------|
| `memory-session-flow.md` | Memory reading at session start (STATUS → PLAN → WARNINGS → INDEX) |
| `memory-auto-update.md` | Memory persistence at session end (7 files in parallel) |
| `memory-checklist.md` | End-of-session checklist — verify memory is persisted |

### Quality & errors

| Standard | Description |
|----------|-------------|
| `error-correction.md` | 2-failed-corrections rule — stop and reset after 2 failures |
| `anti-patterns.md` | Failure pattern detection (catch-all session, infinite exploration...) |
| `escalation.md` | Blocker handling — when and how to escalate |
| `delegation-failure.md` | Procedure after a sub-agent failure — notice, diagnose, act |

### Audit & exploration

| Standard | Description |
|----------|-------------|
| `audit.md` | Read-only multi-axis audit (quality, architecture, dependencies, performance) |
| `exploration-limits.md` | Investigation boundaries — no global scan without a precise objective |

### Artifacts & format

| Standard | Description |
|----------|-------------|
| `artifact-authoring.md` | Consistent creation of new standards/agents/frameworks |
| `agent-output.md` | Structured JSON return format for sub-agents |
| `commits.md` | Commit format and rules (Conventional Commits + Infomaniak conventions) |

## Application order

Standards are applied in descending order of specificity:

```
Global standards → Global agents → Global frameworks → Project AGENTS.md → docs/ai/
```

The project's local `AGENTS.md` is the source of truth — local always wins.
