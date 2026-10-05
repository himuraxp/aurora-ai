# config/

> **Language note:** the config files here are language-neutral (JSON); scripts and inline comments they reference are partially in French — the maintainer's working language. The agent runtime consumes them language-agnostically, so behavior is unaffected. Public-facing docs: the [root README](../README.md) and [`docs/`](../docs/).

Global OpenCode configuration. This folder holds the main config, environment variables, plugins and the oh-my-opencode-slim plugin config.

## Files

| File | Description |
|------|-------------|
| `opencode.json` | Main configuration — providers, models, agents, permissions, MCP servers |
| `.env.example` | Environment variable template (no secrets). Copy to `~/.config/opencode/.env` |
| `oh-my-opencode-slim.json` | oh-my-opencode-slim plugin configuration (presets, models, skills) |
| `package.json` | npm dependencies for plugins |

## Sub-folders

| Folder | Description |
|--------|-------------|
| `plugins/` | OpenCode plugins (see `plugins/README.md`) |

## Environment variables

OpenCode does **not** load `.env` files: `{env:VAR}` references in `opencode.json`
read only the shell environment. Hence the model:

- **Infomaniak AI API key**: a single copy, exported in the user's shell rc
  (`~/.zshrc`, managed block written by `setup.sh`, idempotent). Read via
  `{env:OPENAI_API_KEY_INFOMANIAK}`. No duplication (neither `.env` nor a separate file).
- **Other variables**: in `~/.config/opencode/.env` (template `.env.example`),
  read by the MCP servers (manual fallback in their code) and tools (figma-ds).

> **Important**: never duplicate the key elsewhere (no copy in `.env`
> or a `secrets/` file). To change the key: `setup.sh --force` (Enter
> to keep, or a new value).
>
> **Pre-existing export**: if the key is already freely exported in the rc (outside the
> managed block), `setup.sh` **moves** it into the block — it is never duplicated.
> A `$VAR` reference (e.g. `"$OPENAI_API_KEY"`) is preserved as-is; the source
> variable itself is left untouched.

### Required (shell rc, managed block by setup.sh)

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY_INFOMANIAK` | Infomaniak AI API key (Infomaniak console) — exported in the shell rc |
| `IDB_UDID` | iOS simulator UDID (ios-simulator MCP — reads only the environment, no `.env` fallback) |
| `IDB_PATH` | PATH to idb binaries (ios-simulator MCP) |

### Optional (in `~/.config/opencode/.env`)

| Variable | Description |
|----------|-------------|
| `INFOMANIAK_API_TOKEN` | Infomaniak API token (infomaniak MCP — `.env` fallback in its code) |
| `GITLAB_TOKEN` | GitLab token (angular-elements MCP — `.env` fallback in its code) |
| `FIGMA_TOKEN` | Figma token (figma-ds) |

The Infomaniak API endpoints (standard + B300) are defined directly in `opencode.json`
(non-secret, stable values).

**Known trade-off**: OpenCode launched from a GUI that does not inherit the shell
(launcher, Spotlight) will not have the key → 401 on the Infomaniak provider.
Terminals (TUI, VS Code) are login shells and work.

## Security

- The Infomaniak AI API key lives in the user's shell rc (managed block by `setup.sh`, single copy) and is read via `{env:...}` in `opencode.json`
- The real `.env` file is stored in `~/.config/opencode/.env` (never in the repo)
- `setup.sh --force` reconfigures the variables interactively
- The `pre-commit-secrets.sh` hook detects accidental leaks

## Installation

```bash
# setup copies the config interactively
npm run setup
# or: ~/.config/opencode-config/scripts/setup.sh

# install updates without interaction
npm run update
# or: ~/.config/opencode-config/scripts/install.sh
```

The config is copied to `~/.config/opencode/opencode.json`.
