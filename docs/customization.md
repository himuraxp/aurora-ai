# Customization — How to customize and extend

## Customize the agents

The specialized agents live in `agents/` of the forked repo. Each has a precise role:

| Agent | Role |
|-------|------|
| `aurora.md` | Main agent — loading and coordination |
| `aurora-heavy.md` | Agent for complex tasks (euria-code) |
| `reviewer.md` | Strict code review (checklist, verdict) |
| `tester.md` | Quality tests (Jest, Angular standalone) |
| `security.md` | Defensive cybersecurity — AppSec, threat modeling, DevSecOps |
| `cybersec.md` | Offensive cybersecurity — pentest, Red Team, exploitation, recon |
| `architect.md` | Technical breakdown |
| `spark.md` | Lightweight subagent (commit, MR, CLI skills) |
| `vision.md` | Multimodal subagent (images, screenshots) |
| `atlas.md` | SEO Strategy — strategy, keyword research, content gaps |
| `crawler.md` | Technical SEO — technical SEO audit and fixes |
| `sage.md` | AIO / GEO — optimization for generative search engines |
| `scribe.md` | SEO Content — editorial production and optimization |
| `pulse.md` | Growth Marketing — acquisition, conversion, funnel |
| `echo.md` | Social Distribution — multi-channel distribution |
| `beacon.md` | Analytics — SEO and marketing measurement |
| `designer.md` | UX/UI Designer — interface design, art direction, design system, accessibility |
| `mobile.md` | Mobile Engineer — iOS, Android, React Native, Flutter |

To customize:

1. Edit the file in the forked repo
2. Run `npm run update` (or `./scripts/install.sh`)
3. The files are copied to `~/.config/opencode/agents/`

After renaming or removing an artifact, use:

```bash
npm run prune
# or: ./scripts/install.sh --prune
```

## Add a framework

In `frameworks/`, the per-stack technical rules:

```txt
frameworks/
├── angular-20.md   # Angular 20 stand-alone, signals, inject(), etc.
├── nodejs.md       # Node.js API / TypeScript
├── nestjs.md       # Modular NestJS architecture
└── astro.md        # Astro static sites, SEO, i18n
```

To add a framework:

1. Create `frameworks/<my-framework>.md`
2. Adapt `templates/AGENTS.md` to reference the framework
3. Run `npm run update` (or `./scripts/install.sh`)

The `AGENTS.md` template must state which framework is active for the project:

```md
## Node.js — Conventions

- [specific rules]
```

## Create a new rule

### Universal rule (applicable to any project)

Create a file in `standards/`:

```txt
standards/
├── artifact-authoring.md
├── audit.md
├── workflow.md
├── memory-session-flow.md
├── memory-auto-update.md
├── memory-checklist.md
├── verification.md
├── communication.md
├── escalation.md
├── commits.md
├── review-before-done.md
├── exploration-limits.md
├── error-correction.md
├── anti-patterns.md
├── delegation-failure.md
├── agent-output.md
└── my-rule.md   ← here
```

The standard will be automatically copied to `~/.config/opencode/standards/` by `install.sh`.

Before creating a new artifact, apply `standards/artifact-authoring.md`:

1. Check that an existing standard, agent or framework doesn't already cover the need.
2. Define the exact trigger.
3. Keep the content short, actionable and verifiable.
4. Update `README.md`, `templates/AGENTS.md` and this page if the artifact becomes public.

### Specialized rule (dedicated agent)

Create a file in `agents/` with the frontmatter:

```md
---
description: My specialized agent
mode: subagent
---

# My Agent

[Content]
```

The `aurora.md` agent will load it automatically if needed.

## Customize the session workflow

Edit `standards/workflow.md` and `standards/memory-session-flow.md` to adapt:

- The work cycle (currently: Explore → Plan → Implement → [PARALLEL GATE] → Commit)
- Memory handling (docs/ai/)
- Mandatory checks (verification.md)
- Communication formats (communication.md)

## Typical extension example

**Adding an Angular performance rule:**

```bash
# In the forked repo
cat > frameworks/angular-performance.md << 'EOF'
# Angular Performance

- Use `OnPush` by default on components.
- Avoid unnecessary change detections.
- Lazy-loading of routes.
EOF

npm run update
# or: ./scripts/install.sh
```

In the original `frameworks/angular-20.md`, add a reference:

```md
## Performance

See `frameworks/angular-performance.md` for details.
```

## New Session Documents (BUFFER, INDEX, WARNINGS)

Aurora automatically detects `docs/ai/` at startup and loads these documents in the order defined in `standards/memory-session-flow.md`. No configuration in the local `AGENTS.md` is required to enable this discovery.

### Why use them?

In addition to `PLAN.md`, `STATUS.md`, `DECISIONS.md` and `CHANGELOG.md`, each project can now manage: `BUFFER.md`, `INDEX.md` and `WARNINGS.md`.

- **INDEX.md**: Project map. Saves the agent from scanning the whole codebase at every session. Updated if the structure changes significantly.
- **BUFFER.md**: Temporary buffer. Out-of-scope discoveries, temporary micro-decisions, recovery snapshot after an interruption. Emptied or archived at session end.
- **WARNINGS.md**: Active alerts and technical debt. Sensitive zones of the project, known workarounds. Must be consulted before any change in these zones.

### When to modify them

- **INDEX.md**: When the structure changes significantly or at initial creation.
- **BUFFER.md**: At session start when resuming, at session end to note out-of-scope topics.
- **WARNINGS.md**: When new debt or a risk zone is identified. Archive when resolved.

### Differences between the documents

| Document | When to read | When to write | Content |
|----------|-------------|---------------|---------|
| STATUS.md | Session start | Session end | Progress state, blockers |
| PLAN.md | Session start | During planning | Technical plan, steps, risks, status |
| DECISIONS.md | When a choice arises | After a structural decision | Decision, context, impact |
| CHANGELOG.md | Rarely | Session end (if significant) | Change history |
| BUFFER.md | If resuming/in progress | Session end | Temporary, micro-decisions, snapshot |
| INDEX.md | Session start, if lost | If the structure changes | Project map |
| WARNINGS.md | Before any change in a sensitive zone | When a risk is identified | Active alerts, debt |

### Proven capabilities in INDEX.md

`INDEX.md` can document the project's capabilities only when a concrete signal exists: UI, API, database, auth, CLI, package, monorepo, infra, data, etc.

Never add a capability based on business intuition. Example: a product with users doesn't necessarily have an `auth` capability as long as no authentication code exists.

## Recommendations

- **Never edit** `~/.config/opencode/*` **directly**.
- **`.new` files** generated by `sync-project.sh` are not read automatically by OpenCode. Merge them manually into the existing files before deleting them.
- If a `.new` file already exists, `sync-project.sh` creates a timestamped proposal instead of overwriting it.
- Make changes in the forked repo, then `npm run update` (or `./scripts/install.sh`).
- Version your fork to track your customizations.
- Use `git pull` to fetch upstream updates.
