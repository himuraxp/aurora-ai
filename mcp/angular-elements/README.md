# @opencode/mcp-angular-elements

MCP server for the Infomaniak Angular Elements design system. Exposes component documentation, TypeScript API, Storybook stories, and install metadata from the GitLab repository via the Model Context Protocol (stdio transport).

## Architecture

```
src/
├── index.ts            # Entry point — MCP server setup, tool registration
├── types.ts            # Shared ToolDef interface
├── client.ts           # GitLab API client + Storybook index fetcher (with caching)
└── modules/
    └── elements.ts     # 7 tool definitions + TypeScript parsing helpers
```

### Data sources

| Source | URL | Usage |
|--------|-----|-------|
| GitLab API | `$ANGULAR_ELEMENTS_GITLAB_API/projects/$ANGULAR_ELEMENTS_PROJECT_ID` | Component source files (`.component.ts`, `Docs.mdx`, `package.json`, `CHANGELOG.md`) |
| Storybook index | `$ANGULAR_ELEMENTS_STORYBOOK_BASE/index.json` | Component catalog, story entries, docs entries |

All API responses are cached in-memory for 1 hour (TTL: 3600s).

## Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `list_components` | List all ~37 UI components and ~4 utilities with their Storybook hierarchy | — |
| `search_components` | Search components by name or keyword | `query: string` (required) |
| `get_component_docs` | Get full MDX documentation (intro, usage, API table, variants, theming) | `component: string` (required), `subComponent?: string` |
| `get_component_api` | Extract TypeScript API — inputs (`InputSignal`), outputs (`OutputEmitterRef`), public methods, selector | `component: string` (required), `subComponent?: string` |
| `get_component_stories` | Get Storybook stories metadata — story names, argTypes, default args | `component: string` (required) |
| `get_install_info` | Get `package.json` info — npm name, version, peer deps, install commands | `component: string` (required) |
| `get_changelog` | Get `CHANGELOG.md` content — version history, features, fixes, breaking changes | `component: string` (required) |

### Parameter conventions

- `component` — Folder name in the `projects/` directory (e.g. `button`, `alert`, `actions-menu`, `select`)
- `subComponent` — Optional sub-component selector (e.g. `ik-button`, `ik-buttons-group`)

## Installation

Requires Node.js >= 18.

```bash
git clone https://github.com/himuraxp/aurora-ai.git
cd aurora-ai/mcp/angular-elements
npm ci         # dependencies are pinned by package-lock.json
npm run build  # outputs dist/index.js
```

## Configuration

Every setting is resolved in this order:

1. The process environment — including values injected by the MCP `env` config in `opencode.json` (`{env:VAR}` interpolation)
2. `~/.config/opencode/.env` (read directly by the client)

| Variable | Required | Description |
|----------|----------|-------------|
| `ANGULAR_ELEMENTS_GITLAB_TOKEN` | ✅ | GitLab private token (nominal) — create a **dedicated** one (scope `read_api`, with expiry) at `https://<your-gitlab-host>/-/profile/personal_access_tokens` |
| `GITLAB_TOKEN` | — | Deprecated transitional fallback for the token. It is the canonical variable of other tooling (e.g. `glab`) and usually carries a broader scope — a one-time startup warning is logged; removal planned in a future release |
| `ANGULAR_ELEMENTS_GITLAB_API` | ✅ | GitLab API base, e.g. `https://gitlab.example.com/api/v4` |
| `ANGULAR_ELEMENTS_PROJECT_ID` | ✅ | Numeric id of the GitLab project hosting the design system sources |
| `ANGULAR_ELEMENTS_STORYBOOK_BASE` | ✅ | Base URL exposing the built Storybook `index.json` |
| `ANGULAR_ELEMENTS_ALLOWED_ORIGINS` | ✅ | Comma-separated exact HTTPS origins the MCP may contact (startup allowlist) |
| `ANGULAR_ELEMENTS_REF` | — | Git ref to read (default: `master`) |
| `ANGULAR_ELEMENTS_ENV_FILE` | — | Advanced: override of the `.env` file path (tests, custom setups) |

Example `~/.config/opencode/.env` — the client reads this file directly, no `env` block needed in `opencode.json`:

```sh
ANGULAR_ELEMENTS_GITLAB_TOKEN=<your-personal-access-token>
ANGULAR_ELEMENTS_GITLAB_API=https://gitlab.example.com/api/v4
ANGULAR_ELEMENTS_PROJECT_ID=1234
ANGULAR_ELEMENTS_STORYBOOK_BASE=https://<your-gitlab-host>/front/angular-elements
ANGULAR_ELEMENTS_ALLOWED_ORIGINS=https://gitlab.example.com,https://<your-pages-host>
# ANGULAR_ELEMENTS_REF=master   # optional
# GITLAB_TOKEN=...             # deprecated fallback — avoid it (broader scope, shared tooling)
```

Missing required variables fail closed at startup with an explicit error listing the variable name.

## Security policy

Enforced at startup, fail-closed — a misconfigured server never reaches the network layer:

- **Endpoint allowlist** — both endpoints must be exact HTTPS origins listed in `ANGULAR_ELEMENTS_ALLOWED_ORIGINS`, without embedded credentials; the GitLab API path must be exactly `/api/v4` and the Storybook base must not be the host root.
- **Token scoping** — the nominal `ANGULAR_ELEMENTS_GITLAB_TOKEN` is a dedicated, least-privilege token (scope `read_api`); the legacy `GITLAB_TOKEN` is only a deprecated transitional fallback and logs a warning.
- **Token confinement** — the token is sent only to the validated GitLab API origin (explicit guard), in the request header, never in URLs; HTTP redirects are refused (`redirect: "error"`) so it cannot leak to another destination.
- **Injection-resistant URLs** — refs and paths are encoded once via `URLSearchParams`/`encodeURIComponent`; the project id must be numeric.

### Tests

```bash
npm test  # compiles src/ then runs node:test suites (allowlist, URL encoding, token resolution)
```

### OpenCode config

Declare the MCP in `opencode.json`, pointing at your clone of this repository:

```json
{
  "mcp": {
    "angular-elements": {
      "type": "local",
      "command": ["node", "/path/to/aurora-ai/mcp/angular-elements/dist/index.js"],
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

## Development

### Prerequisites

- Node.js >= 18
- TypeScript >= 5.5

### Build

```bash
npm run build
```

### Dev (watch mode)

```bash
npm run dev
```

### Run

```bash
npm start
```

## How it works

1. **Component discovery** — Fetches the Storybook `index.json` to enumerate all components. Entries are grouped by Storybook title hierarchy (`Elements/Button/ik-button` -> folder `button`).

2. **Documentation** — Resolves the `Docs.mdx` file path from the Storybook entry's `importPath`, then fetches raw content from GitLab.

3. **API extraction** — Reads the GitLab repository tree to find all `.component.ts` files under `projects/<component>/src/`. Parses TypeScript source with regex to extract:
   - `@Component({ selector: '...' })`
   - `InputSignal<T>` inputs with default values and JSDoc descriptions
   - `output<T>()` and `EventEmitter<T>` outputs
   - Public methods (excludes constructor, lifecycle hooks, private members)

4. **Stories** — Finds the `.stories.ts` file via `storiesImports` in the Storybook index, then parses argTypes, default args, and story names.

5. **Install info** — Reads `projects/<component>/package.json` for npm package name, version, and dependency tree. Also attempts to fetch `README.md` for install instructions.

6. **Changelog** — Reads `projects/<component>/CHANGELOG.md` directly.

## Caching

| Cache | TTL | Scope |
|-------|-----|-------|
| Storybook `index.json` | 1 hour | Global (all components) |
| GitLab file content | 1 hour | Per file path |
| GitLab tree listings | 1 hour | Per directory path |

Caches are in-memory and reset on server restart.
