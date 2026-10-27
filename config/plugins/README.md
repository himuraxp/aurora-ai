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

### chatgpt-autocowork.ts

Auto-invokes the `ai-cowork` skill when the user sends a ChatGPT conversation link — the user no longer has to ask for the cowork loop explicitly.

**How it works:**
1. Hooks `session.hook("prompt")` (user message, before resolution — verified against opencode v2.1.4)
2. Detects ChatGPT conversation URLs: `chatgpt.com/c/…`, `chatgpt.com/g/<gid>/c/…` (projects), `chatgpt.com/share/…` (public snapshot), legacy `chat.openai.com/c/…` — lookalike hosts rejected by lookbehind (`mychatgpt.com`, `evil-chatgpt.com`)
3. Appends a `<system-reminder>` instructing the model to invoke the `ai-cowork` skill with the detected URL (« URL conversation ChatGPT » parameter) and to carry a **detailed summary of Aurora's current working context** in the initial brief — the ChatGPT conversation may be in an active state whose context differs from the current request; the summary lets ChatGPT adapt without losing its own context. Never rewrites user text — only appends. Only the first link is echoed into the reminder; a second link stays in the original text.
4. Root-session gate (best effort): `ctx.session.get` → sessions with a `parentID` (task-tool subagent briefs) are never annotated. Lookup failure → fail-open (annotate).
5. Idempotent: a text already carrying the marker is never re-annotated.

**Scope & accepted risks:** any occurrence of the pattern triggers, including meta-questions and quoted links (the reminder tells the model to answer questions ABOUT the link normally; an explicit user refusal always wins). `/share/` snapshots are public/forgeable and a third-party-pasted link remains a potential objective-injection channel — mitigated by the skill's hard rules (read-only share handling, AGENTS.md veto, unchanged permissions). The persisted session transcript may include the reminder (live-prompt annotation, not a rewrite).

**Dependency:** none. Silent no-op if the `session` hook namespace is unavailable.

**Semantic source of truth:** `agents/aurora.md` (« Règles strictes ») — the plugin adds deterministic enforcement on top of the rule.

**Reception suite:** `scripts/test-chatgpt-autocowork.mjs` (wired into `scripts/health-check.sh`, pattern `test-product-authority.mjs`).

## Adding a plugin

1. Create a `<plugin-name>.ts` file in this folder
2. Default-export an object `{ id, setup }` — `setup(ctx)` registers hooks on the ctx namespaces and may return a dispose function
3. Keep the TypeScript erasable (types are stripped at runtime — no enums, no namespaces, no param properties); declare minimal structural types for the hooks you use, following the sibling plugins
4. Add npm dependencies in `config/package.json` only if you import a runtime package (plugin-only code needs none)
5. Run `npm run update` (or `./scripts/install.sh`) to deploy — plugins are auto-loaded from the live `plugins/` directory
6. Reference the plugin in `config/oh-my-opencode-slim.json` only if it belongs to the OMO plugin suite

## Plugin API (v2 runtime, verified against opencode v2.1.4)

```typescript
const plugin = {
  id: "my-plugin",
  setup: async (ctx) => {
    // ctx.tool.hook("execute.before", handler)    — intercept tool inputs (handler mutates event.input)
    // ctx.tool.transform(draft => draft.add(…))   — register a custom tool
    // ctx.session.hook("prompt", handler)         — annotate the user prompt (event.prompt.text is mutable and read back by the runtime)
    const registration = await ctx.tool.hook(/* … */)
    return () => registration?.dispose() // optional cleanup
  },
}

export default plugin
```
