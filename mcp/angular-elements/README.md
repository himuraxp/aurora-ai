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

## Configuration

Every setting is resolved in this order:

1. The process environment — including values injected by the MCP `env` config in `config/opencode.json` (`{env:VAR}` interpolation)
2. `~/.config/opencode/.env` (read directly by the client)

| Variable | Required | Description |
|----------|----------|-------------|
| `GITLAB_TOKEN` | ✅ | GitLab private token — create one at `https://<your-gitlab-host>/-/profile/personal_access_tokens` |
| `ANGULAR_ELEMENTS_GITLAB_API` | ✅ | GitLab API base, e.g. `https://gitlab.example.com/api/v4` |
| `ANGULAR_ELEMENTS_PROJECT_ID` | ✅ | Numeric id of the GitLab project hosting the design system sources |
| `ANGULAR_ELEMENTS_STORYBOOK_BASE` | ✅ | Base URL exposing the built Storybook `index.json` |
| `ANGULAR_ELEMENTS_REF` | — | Git ref to read (default: `master`) |

Missing required variables fail with an explicit error listing the variable name.

### OpenCode config

Configured in `config/opencode.json`:

```json
{
  "mcp": {
    "angular-elements": {
      "type": "local",
      "command": ["node", "{env:HOME}/.config/opencode-config/mcp/angular-elements/dist/index.js"],
      "enabled": true,
      "timeout": 30000,
      "env": {
        "GITLAB_TOKEN": "{env:GITLAB_TOKEN}"
      }
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
