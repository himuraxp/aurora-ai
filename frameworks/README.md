# frameworks/

> **Language note:** the framework rule files referenced here are written in French — the maintainer's working language. The agent runtime consumes them language-agnostically, so behavior is unaffected. Public-facing docs: the [root README](../README.md) and [`docs/`](../docs/).

Per-stack rules and conventions. Each file defines the patterns, structures and best practices to apply when a project uses the matching stack.

## Supported frameworks

| Framework | File | Detection |
|-----------|------|-----------|
| Angular 20 | `angular-20.md` | `angular.json` or `.angular-cli.json` |
| NestJS | `nestjs.md` | `nest-cli.json` |
| Astro | `astro.md` | `astro.config.*` |
| Node.js | `nodejs.md` | `package.json` (fallback) |

## Automatic detection

The `scripts/init-project.sh` script detects the project's stack and automatically adds the matching framework reference to the local `AGENTS.md`.

```bash
cd /path/to/project
npm run init-project --prefix ~/.config/opencode-config
# or: ~/.config/opencode-config/scripts/init-project.sh
```

## Application

Frameworks are applied in descending order of specificity:

```
Global standards → Global agents → Global frameworks → Project AGENTS.md
```

The framework provides stack-specific rules (folder structure, naming, test patterns, etc.) that extend the global standards without replacing them.

## Adding a framework

1. Create a `<framework-name>.md` file
2. Document: structure, conventions, patterns, tests, dependencies
3. Add detection in `scripts/init-project.sh`
4. Run `npm run update` (or `./scripts/install.sh`) to deploy

See `standards/artifact-authoring.md` for consistent creation rules.
