# scripts/

> **Language note:** the shell scripts referenced here contain French comments and UI strings — the maintainer's working language. The agent runtime consumes them language-agnostically, so behavior is unaffected. Public-facing docs: the [root README](../README.md) and [`docs/`](../docs/).

Installation, maintenance and automation scripts for opencode-config.

## Scripts

| Script | Usage | Description |
|--------|-------|-------------|
| `setup.sh` | `./scripts/setup.sh [--force] [--no-animation]` | First install on a machine. Interactive: installs opencode-ai, rtk, MCP servers, copies the config, collects secrets |
| `install.sh` | `./scripts/install.sh [--prune] [--no-config] [--dry-run]` | Update. Copies only modified files to `~/.config/opencode/` |
| `configure-models.sh` | `./scripts/configure-models.sh [--yes] [--dry-run] [--providers LIST] [--force]` | Detects which models the configured API keys can actually use (real probes) and maps them to agent roles — Infomaniak, OpenAI, Anthropic, Google, OpenRouter, local Ollama. Preserves existing verified setups; fail-closed (writes nothing if a required role can't be resolved) |
| `init-project.sh` | `./scripts/init-project.sh [--dry-run]` | Initializes a project: copies `AGENTS.md`, detects the stack, adds the framework |
| `sync-project.sh` | `./scripts/sync-project.sh [--dry-run]` | Syncs a project's templates (creates `.new` on conflict) |
| `health-check.sh` | `./scripts/health-check.sh [--installed] [--quiet]` | Consistency checks: valid JSON, agents, models, orphans |
| `permissions-matrix.sh` | `./scripts/permissions-matrix.sh [--output FILE]` | Generates a markdown table of all agents' permissions |
| `validate-memory.sh` | `./scripts/validate-memory.sh [PROJECT_DIR]` | Verifies `docs/ai/` is well-formed (required files, sections) |
| `ui.sh` | `source scripts/ui.sh` | Shared UI library (colors, animations, progress bars) |

## Sub-folders

| Folder | Description |
|--------|-------------|
| `lib/` | Model configuration engine: role policy (`model-roles.json` in `config/`), Python engine `configure_models.py`, provider adapters in `lib/providers/`, contract tests `test_probes.py` (no network required) |
| `create-mr/` | Merge request creation scripts (see `create-mr/README.md`) |
| `hooks/` | Git hooks (see `hooks/README.md`) |

## Installation

### First install (new machine)

```bash
git clone https://github.com/himuraxp/aurora-ai.git ~/.config/opencode-config
cd ~/.config/opencode-config
npm run setup
# or: ./scripts/setup.sh
```

### Update

```bash
cd ~/.config/opencode-config && git pull && npm run update
# or: ./scripts/install.sh
```

### Initialize a project

```bash
cd /path/to/project
~/.config/opencode-config/scripts/init-project.sh
# or from the repo: npm run init-project
```

### Available npm commands

| Command | Equivalent bash script | Description |
|---------|------------------------|-------------|
| `npm run setup` | `scripts/setup.sh` | Full interactive install |
| `npm run update` | `scripts/install.sh` | Update config files |
| `npm run prune` | `scripts/install.sh --prune` | Update + remove orphans |
| `npm run dry-run` | `scripts/install.sh --dry-run` | Preview changes |
| `npm run init-project` | `scripts/init-project.sh` | Initialize a project |
| `npm run sync` | `scripts/sync-project.sh` | Sync templates |
| `npm run health-check` | `scripts/health-check.sh` | Consistency check |
| `npm run permissions` | `scripts/permissions-matrix.sh` | Generate permission matrix |
| `npm run validate-memory` | `scripts/validate-memory.sh` | Validate a project's docs/ai/ |

> Extra flags can be passed via `--`: `npm run setup -- --force`

## Dependencies

- **Node.js** >= 18 (for opencode-ai and MCP servers)
- **npm** (for opencode-ai and plugins)
- **rtk** (optional, installed by setup.sh — saves tokens via rewriting)
- **glab** (optional, for GitLab skills)
- **ImageMagick** (optional, for the image-transparent-background skill)
- **idb-companion** + **fb-idb** (optional, macOS, for the iOS Simulator MCP)

## ui.sh — shared UI library

Used by `setup.sh` and `install.sh` for animations and colors. 100% bash, zero external dependencies. Compatible macOS (bash 3.2+) and Linux (bash 4+).

```bash
source "$(dirname "${BASH_SOURCE[0]}")/ui.sh"
ui_logo
ui_section "System Check"
ui_info "Checking prerequisites..."
ui_run "Installing opencode-ai" npm install -g opencode-ai
ui_ok "Done"
```
