# templates/

Templates injected into projects via `scripts/init-project.sh` and `scripts/sync-project.sh`. These files are copied to the target project root to initialize or update the OpenCode configuration.

## Files

| Template | Destination | Description |
|----------|-------------|-------------|
| `AGENTS.md` | `<project>/AGENTS.md` | Main project configuration — rules, architecture, memory |
| `STATUS.md` | `<project>/docs/ai/STATUS.md` | Current state — in-progress / done / blocked / next action |
| `PLAN.md` | `<project>/docs/ai/PLAN.md` | Step progress |
| `CHANGELOG.md` | `<project>/docs/ai/CHANGELOG.md` | Dated change entries |
| `DECISIONS.md` | `<project>/docs/ai/DECISIONS.md` | Architectural decisions made |

## Sub-folders

| Folder | Description |
|--------|-------------|
| `project-docs/` | Templates for project memory (see `project-docs/README.md`) |

## Workflow

### Initialization (new project)

```bash
cd /path/to/project
npm run init-project --prefix ~/.config/opencode-config
# or: ~/.config/opencode-config/scripts/init-project.sh
```

Copies the missing templates, detects the stack, adds the framework. Never replaces existing files.

### Sync (update)

```bash
cd /path/to/project
npm run sync --prefix ~/.config/opencode-config
# or: ~/.config/opencode-config/scripts/sync-project.sh
```

Compares the templates with the existing files. On difference, creates a `.new` file next to the original for manual review.

## Generated structure

```
project/
├── AGENTS.md              # Project rules
└── docs/ai/
    ├── STATUS.md          # Current state
    ├── PLAN.md            # Progress plan
    ├── CHANGELOG.md       # Change history
    ├── DECISIONS.md       # Architectural decisions
    ├── BUFFER.md          # Recovery snapshot (project-docs/)
    ├── INDEX.md           # Key modules and files (project-docs/)
    └── WARNINGS.md        # Sensitive zones (project-docs/)
```

## Template delegation

Project memory (`docs/ai/`) is self-maintained by Aurora per `standards/memory-session-flow.md` and `standards/memory-auto-update.md`. The templates are a starting point — the content is then maintained dynamically.
