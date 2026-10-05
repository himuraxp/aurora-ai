# skills/

> **Language note:** the skill `SKILL.md` workflow files referenced here are written in French — the maintainer's working language. The agent runtime consumes them language-agnostically, so behavior is unaffected. Public-facing docs: the [root README](../README.md) and [`docs/`](../docs/).

Reusable skills for OpenCode. Each skill is a folder containing at least a `SKILL.md` file that describes the workflow to run.

## Available skills

### Git & CI

| Skill | Description |
|-------|-------------|
| `commit` | Commit messages following Conventional Commits + Infomaniak conventions |
| `create-mr` | Merge request creation with Infomaniak-formatted title/description |
| `mr-review` | GitLab MR review with inline comments (delegates to Oracle) |
| `mr-review-feedback` | Automatic application of MR review feedback |
| `pre-mr-review` | Pre-MR quality review (dead code, duplications, simplifications) |
| `code-review` | Adversarial review — forces finding real issues |
| `deployment-changelog` | Deployment changelog for the day's commits |
| `new-worktree` | Branch + worktree from a single intent (`feat podcast Gestion des...` → `feat/podcast--dynamic-form-and-config-management` + Orca-ready worktree), auto-detected base, never destructive |
| `gitlab-ci` | GitLab CI/CD interaction (pipelines, jobs) via glab CLI |
| `gitlab-issues` | GitLab issue management via glab CLI |
| `gitlab-summary` | GitLab activity summary (daily standup) |
| `worktrees` | Git worktrees as isolated coding lanes (OMO protocol) |

### Product planning

| Skill | Description |
|-------|-------------|
| `gitlab-feature-planner` | Turns an estimation table (Excel/CSV/Markdown) + Figma mockups into a structured GitLab issue proposal (1 issue = 1 page/functional block, rows → checklists) + suggested MR groupings; mandatory human validation before creation |

### Accessibility

| Skill | Description |
|-------|-------------|
| `accessibility` | Accessibility suite — 17 sub-skills orchestrated via `accessibility-orchestrator` (aria, contrast, focus, keyboard, forms, motion, structure, responsive…) |

### Documentation

| Skill | Description |
|-------|-------------|
| `readme` | README.md generation for projects (template-based approach) |
| `translate-doc` | Documentation translation between languages |
| `user-stories` | Writing well-structured user stories |

### Media & image

| Skill | Description |
|-------|-------------|
| `image-transparent-background` | White background removal via ImageMagick |
| `radio-tag-genres` | Musical genre tagging for radio AutoDJ playlists |

### Design System

| Skill | Description |
|-------|-------------|
| `figma-ds-sync` | Infomaniak Figma design system sync to local JSON snapshots (check/sync/diff/mapping) |

### Code quality & workflow

| Skill | Description |
|-------|-------------|
| `codemap` | Hierarchical codemaps to navigate an unfamiliar repo (expensive operation, on demand) |
| `clonedeps` | Clone dependency sources into a local workspace to inspect library internals |
| `deepwork` | Orchestrated multi-phase workflow with review gates for large, risky efforts |
| `loop-engineering` | Grill + Monitor runtime for engineering loops |
| `reflect` | Analyze recent sessions → recurring patterns, reusable skills/agents/config to propose |
| `review-gap-analyzer` | Review feedback (MR, bots) → improved AGENTS.md rules and pre-mr-review greps, without false positives |
| `simplify` | Code simplification for readability, without behavior change |
| `verification-planning` | Plan verification (project-specific evidence path) before a non-trivial code change |

### Frameworks

| Skill | Description |
|-------|-------------|
| `laravel-cruddy-by-design` | Strictly RESTful Laravel controllers and routes (max 7 methods, resource-based routing) |

### AI collaboration

| Skill | Description |
|-------|-------------|
| `ai-cowork` | Aurora ↔ ChatGPT co-working: autonomous work loop via the `browser-debug` MCP (debug browser :9222) — ChatGPT briefs and validates (`VERDICT: ITERATE\|APPROVED`), Aurora works; negotiated veto on AGENTS.md rules, final report with conversation link |

### Configuration

| Skill | Description |
|-------|-------------|
| `allow-command` | Pre-approve shell commands in opencode.json |
| `oh-my-opencode-slim` | Configure and improve the oh-my-opencode-slim plugin (agents, models, presets, MCP) |
| `release-smoke-test` | oh-my-opencode-slim release validation |

## Skill structure

```
skills/
└── my-skill/
    └── SKILL.md    # Instructions + workflow (required)
```

The `SKILL.md` file contains:
- **When to use** — triggers and context
- **Procedure** — detailed steps
- **Examples** — concrete use cases

## Usage

Skills are invoked via the `skill` tool with the `name` parameter. OpenCode loads the `SKILL.md` and injects the instructions into the context.

```typescript
// Example: invoke the commit skill
skill({ name: "commit" })
```

## Adding a skill

1. Create a `skills/<skill-name>/` folder
2. Write a `SKILL.md` file with the workflow
3. Run `npm run update` (or `./scripts/install.sh`) to deploy to `~/.config/opencode/skills/`
4. The skill is automatically available via `skill({ name: "<skill-name>" })`

See `standards/artifact-authoring.md` for consistent creation rules.
