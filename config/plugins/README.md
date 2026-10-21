# config/plugins/

> **Language note:** OpenCode plugins are TypeScript code (language-neutral); this documentation and code comments may reference French — the maintainer's working language. Public-facing docs: the [root README](../../README.md) and [`docs/`](../../docs/).

OpenCode plugins written in TypeScript. Plugins extend OpenCode's behavior via hooks on the tool lifecycle.

## Plugins

### rtk.ts

RTK plugin (Rewrite ToolKit) — rewrites bash commands to save tokens.

**How it works:**
1. Intercepts `tool.execute.before` for the `bash`/`shell` tools
2. Delegates to `rtk rewrite <command>` for rewriting
3. Replaces the command if `rtk` produced a rewritten version
4. Silent passthrough if `rtk` is not installed or fails

**Dependency:**
- `rtk` >= 0.23.0 in `PATH`

**Source of truth:**
All rewriting logic lives in `rtk` (Rust, `src/discover/registry.rs`). This plugin is a thin delegator — to change rewriting rules, edit the Rust registry, not this file.

**Installation:**
- `setup.sh` installs `rtk` automatically
- The plugin is loaded via `config/oh-my-opencode-slim.json` → `plugin`

## Adding a plugin

1. Create a `<plugin-name>.ts` file in this folder
2. Export a `Plugin` object from `@opencode-ai/plugin`
3. Implement the needed hooks (`tool.execute.before`, `tool.execute.after`, etc.)
4. Add npm dependencies in `config/package.json`
5. Run `npm run update` (or `./scripts/install.sh`) to deploy
6. Reference the plugin in `config/oh-my-opencode-slim.json` if applicable

## Plugin API

```typescript
import type { Plugin } from "@opencode-ai/plugin"

export const MyPlugin: Plugin = async ({ $ }) => {
  return {
    "tool.execute.before": async (input, output) => {
      // Intercept before execution
    },
    "tool.execute.after": async (input, output) => {
      // Intercept after execution
    },
  }
}
```

## Runtime hooks (vérifié par sonde E2E, 2026-10-21 — opencode v2.1.2)

- **`tool.execute.after` ne fire qu'en format V1** (fonction plugin
  retournant l'objet Hooks, ci-dessus). L'API v2
  `ctx.tool.hook("execute.after", handler)` (pattern `rtk.ts`) s'enregistre
  **sans erreur mais ne fire pas** — seul `execute.before` est routé par
  `ctx.tool.hook`.
- **Shape runtime réelle** du handler (1er argument) :
  `{ tool, sessionID, agent, messageID, id, input, status, result }` —
  `sessionID` présent ; les args du tool vivent dans `input` (pas de
  `args` top-level comme dans le paquet npm `@opencode-ai/plugin >= 1.3.3`).
- Les `console.log/error` des plugins ne sortent **ni** dans stderr du run
  **ni** visiblement dans `opencode.log` — écrire dans un fichier pour
  diagnostiquer (pattern sonde `wd-probe`).
- Les plugins locaux se chargent via `msg="loading plugin"` (log serveur) —
  une erreur de chargement y est tracée, le runtime continue sans le plugin.
