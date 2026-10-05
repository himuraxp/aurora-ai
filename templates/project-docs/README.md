# templates/project-docs/

Templates for the self-maintaining project memory. These files are copied to `<project>/docs/ai/` by `scripts/init-project.sh` and then dynamically maintained by Aurora.

## Templates

| Template | Destination | Description |
|----------|-------------|-------------|
| `BUFFER.md` | `<project>/docs/ai/BUFFER.md` | Recovery snapshot — context for resuming an interrupted session |
| `INDEX.md` | `<project>/docs/ai/INDEX.md` | Modules, components and key files discovered in the project |
| `WARNINGS.md` | `<project>/docs/ai/WARNINGS.md` | Sensitive zones, technical debt, active warnings |

## Life cycle

1. **Initialization** — `init-project.sh` copies the templates if missing
2. **Session** — Aurora reads the 4 session files (STATUS, PLAN, WARNINGS, INDEX) at startup
3. **Session end** — Aurora updates the 7 files in parallel (STATUS, PLAN, CHANGELOG, BUFFER, INDEX, WARNINGS, DECISIONS)
4. **Validation** — `validate-memory.sh` checks consistency

## Session files (not templates)

The following files are created by `templates/` directly (parent level):

- `STATUS.md` — Current state
- `PLAN.md` — Progress plan
- `CHANGELOG.md` — History
- `DECISIONS.md` — Architectural decisions

## BUFFER.md — Recovery snapshot

Contains the context needed to resume an interrupted session:
- Task in progress
- Impacted files
- Last action
- Next step

Read only if: previous session interrupted, `STATUS.md` reports a blocker, or the user explicitly asks to resume.

## INDEX.md — Project map

Lists the modules, components, services and key files discovered. Serves as the project's table of contents.

## WARNINGS.md — Sensitive zones

Documents technical debt, warnings and risk zones. If an active critical warning concerns the working zone, Aurora blocks modifications until it is resolved.

## Validation

```bash
# Check that a project has a well-formed memory
npm run validate-memory --prefix ~/.config/opencode-config -- /path/to/project
# or: ~/.config/opencode-config/scripts/validate-memory.sh /path/to/project
```
