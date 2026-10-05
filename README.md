<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/aurora-logo-with-name-dark.png">
    <img src=".github/assets/aurora-logo-with-name.png" width="300" alt="Aurora — OpenCode orchestrator agent">
  </picture>

  [![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE) [![Last Commit](https://img.shields.io/github/last-commit/himuraxp/opencode-config.svg)](https://github.com/himuraxp/opencode-config/commits/main) [![OpenCode Compatible](https://img.shields.io/badge/OpenCode-Compatible-brightgreen.svg)](https://opencode.ai)

  > **The OpenCode reference for production AI workflows — Angular, Node.js, NestJS, Astro.**

  Forkable. Multi-layered. Ready to use.

  **English** · [Français](README.fr.md)
</div>

---

## Agent State Layer

AI agents lose context at every new session. This repository solves that with a persistent memory layer:

| Document | Problem solved |
|----------|---------------|
| **BUFFER.md** | Session interruptions — recovery snapshot |
| **INDEX.md** | Wasted reads — project mapped at a glance |
| **WARNINGS.md** | Regressions — active alerts before any change |
| **STATUS.md** | Continuity — progress state across sessions |
| **PLAN.md** | Direction — current technical plan |
| **DECISIONS.md** | Traceability — justified structural decisions |

Session cycle (updated with the REVIEW step):

```txt
EXPLORER → PLAN → IMPLEMENT → [REVIEW] → VERIFY → COMMIT
```

With the **REVIEW** step (adversarial review) mandatory before considering a task done.

---

## Why this project?

AI agents (OpenCode, Cursor, Claude...) don't know which standard to follow unless you tell them.

This repo provides:

- **Specialized agents** (repo): aurora (main), aurora-heavy (complex tasks), reviewer, tester, security (defensive), cybersec (offensive/pentest), architect, spark (lightweight subagent), vision (multimodal), designer (UX/UI/art direction/DS), mobile (iOS/Android/RN/Flutter) — **plus the oh-my-opencode-slim plugin agents**: explorer (codebase search), fixer (spec execution), librarian (external docs), oracle (technical advisory)
- **Search & Growth team**: atlas (SEO strategy), crawler (technical SEO), sage (AIO/GEO), scribe (SEO content), pulse (growth marketing), echo (social distribution), beacon (analytics)
- **Development standards**: workflow, communication, verification, escalation, commits, audit, artifact authoring, session memory, exploration limits, error correction, anti-patterns, structured JSON output format for subagents
- **Reusable skills**: accessibility, ai-cowork, allow-command, clonedeps, code-review, codemap, commit, create-mr, deepwork, deployment-changelog, figma-ds-sync, gitlab-ci, gitlab-feature-planner, gitlab-issues, gitlab-summary, image-transparent-background, laravel-cruddy-by-design, loop-engineering, mr-review, mr-review-feedback, new-worktree, oh-my-opencode-slim, pre-mr-review, radio-tag-genres, readme, reflect, release-smoke-test, review-gap-analyzer, simplify, translate-doc, user-stories, verification-planning, worktrees
- **AI co-working**: skill `ai-cowork` — autonomous Aurora ↔ ChatGPT collaboration loop (ChatGPT briefs and validates, Aurora works) driven through the `browser-debug` MCP
- **Angular 20+ conventions**: standalone, signals, inject(), Jest tests
- **Adversarial review**: mandatory adversarial review before declaring a task done
- **Read-only audit**: multi-axis health check without code changes
- **Exploration limits**: strictly scoped investigations, subagents for heavy searches (> 15 files)
- **Persistent memory for AI agents**: 7 session documents (PLAN, STATUS, DECISIONS, CHANGELOG, BUFFER, INDEX, WARNINGS)
- **Anti-patterns**: detection of the 5 common failure patterns (catch-all session, correction spiral, over-specification, trust without verification, infinite exploration)
- **Consistent artifact authoring**: rules for adding standards, agents, frameworks and templates without duplicates
- **Subagent failure handling**: mandatory procedure notice → diagnose → act → inform (see `delegation-failure.md`)
- **Structured output format**: all subagents return parseable JSON for deterministic consolidation, no exceptions (see `agent-output.md`)
- **Ready-to-use examples**: Angular, Node.js API and monorepo projects (in `examples/`)
- **Reproducible setup**: identical behavior across machines and projects

---

## Quick Start

### 1. Install the full configuration (first time)

```bash
git clone https://github.com/himuraxp/opencode-config.git ~/.config/opencode-config
cd ~/.config/opencode-config
npm run setup
```

> Bash equivalent: `~/.config/opencode-config/scripts/setup.sh`

`setup.sh` is an interactive script that:
- Checks prerequisites (Node.js 18+, npm)
- Installs or updates `opencode-ai` (npm global) and `rtk` (Homebrew on macOS)
- Offers to install the MCP servers (chrome-devtools auto, optional iOS Simulator with idb-companion + fb-idb)
- Copies agents, standards, frameworks and config files
- Installs the npm dependencies of the plugins
- Interactively asks for environment variables (API key, endpoints)
- Writes `~/.config/opencode/.env` (permissions 600, never versioned)
- Writes the **managed block** to the shell rc (`~/.zshrc` on zsh): exports the
  Infomaniak AI API key and the iOS MCP `IDB_*` values. Idempotent (never
  duplicated) and automatically moves pre-existing exports of these variables
  into the block — the key never exists in two copies
- Verifies that everything works

If `.env` already exists and contains the required variables, the configuration step is automatically skipped. Use `--force` to reconfigure:

```bash
npm run setup -- --force
# or: ~/.config/opencode-config/scripts/setup.sh --force
```

If an update of `opencode-ai` or `rtk` is available, `setup.sh` offers to apply it.

### 2. Update the configuration (subsequent changes)

```bash
cd ~/.config/opencode-config
git pull
npm run update
```

> Bash equivalent: `./scripts/install.sh`

`install.sh` reports each file as `new`, `updated` or `unchanged`. Only modified files are rewritten.

For a full update (config + dependencies + checks):

```bash
cd ~/.config/opencode-config
git pull
npm run setup
```

After renaming or removing a standard, clean up the old installed files:

```bash
npm run prune
# or: ./scripts/install.sh --prune
```

To update without touching the config files (`opencode.json`, plugins):

```bash
npm run update -- --no-config
# or: ./scripts/install.sh --no-config
```

This installs into `~/.config/opencode/`:

```txt
~/.config/opencode/
├── agents/                    # AI personalities
├── standards/                 # Universal behaviors
├── frameworks/                # Per-stack technical rules
├── opencode.json              # Main config (providers, models, permissions, MCP)
├── oh-my-opencode-slim.json   # Subagent presets
├── package.json               # Plugin dependencies
├── plugins/
│   └── rtk.ts                 # RTK plugin (token savings)
├── .env                       # Secrets (never versioned)
└── .env.example               # Environment variable template
```

### 3. Environment variables

OpenCode does **not** load `.env` files: the `{env:...}` references in
`opencode.json` only read the shell environment. Hence two locations:

- **Shell rc (block managed by `setup.sh`)**: the Infomaniak AI API key (**single
  copy**) and the iOS MCP `IDB_*` values, since the iOS MCP only reads its process
  environment (no `.env` fallback). The block is idempotent: pre-existing exports
  of these variables are moved into the block, never duplicated.
- **`~/.config/opencode/.env`**: variables read directly by the MCP servers
  and tools (internal fallback in their own code).

| Variable | Location | Usage | Required |
|----------|----------|-------|----------|
| `OPENAI_API_KEY_INFOMANIAK` | shell rc (managed block) | Infomaniak AI API key | Yes |
| `IDB_UDID` | shell rc (managed block) | iOS simulator UDID (ios-simulator MCP) | No |
| `IDB_PATH` | shell rc (managed block) | idb binaries path (ios-simulator MCP) | No |
| `INFOMANIAK_API_TOKEN` | `.env` | Infomaniak API token (infomaniak MCP — `.env` fallback) | No |
| `GITLAB_TOKEN` | shell rc or `.env` | GitLab token (angular-elements MCP — `.env` fallback) | No |
| `FIGMA_TOKEN` | `.env` | Figma API token (`figma-ds-sync` skill — design system sync) | No |

`setup.sh` asks for these values interactively. For the `.env` variables
(`INFOMANIAK_API_TOKEN`, `FIGMA_TOKEN`, ...), edit `~/.config/opencode/.env`
directly. For the API key and the `IDB_*` values, use `setup.sh --force`
(Enter to keep, new value to replace) — or edit the managed block in the
shell rc.

### 4. MCP Servers

The configuration includes six MCP servers in `opencode.json`:

| MCP Server | Role | Installation |
|------------|------|-------------|
| `chrome-devtools` | Browsing, screenshots, Lighthouse audits, Chrome debugging (isolated headless browser) | Auto-installed via `npx` on first launch |
| `browser-debug` | Connects to a browser in debug mode (`http://127.0.0.1:9222`) — used by the `ai-cowork` skill (Aurora ↔ ChatGPT) | Auto-installed via `npx`; requires a browser started in debug mode (see below) |
| `ios-simulator` | iOS simulator interaction (tap, swipe, screenshots, UI tree) | Optional — requires `idb-companion` + `fb-idb` |
| `context7` | Up-to-date library and framework documentation | Auto-installed via `npx` |
| `infomaniak` | Infomaniak API — radio, VOD, newsletter, DNS, events, AI | Local (see `mcp/infomaniak/README.md`) |
| `angular-elements` | Angular Elements design system — components, API, stories | Local (see `mcp/angular-elements/README.md`) |

#### chrome-devtools-mcp

No manual installation needed. The `chrome-devtools-mcp` package is downloaded automatically by `npx` on first call.

Two instances coexist (tools prefixed with the server name):
- `chrome-devtools_*` — isolated headless (Designer, audits)
- `browser-debug_*` — connected to `http://127.0.0.1:9222` (`ai-cowork` skill)

For debug mode (persistent browser session, ChatGPT login preserved):

```bash
"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/opencode/brave-debug-profile"
```

> The dedicated `--user-data-dir` is **mandatory** (Chromium ≥136 ignores `--remote-debugging-port` on the default profile).

#### ios-simulator-mcp (macOS only)

This MCP requires 3 external dependencies:

| Dependency | Installation |
|------------|-------------|
| Xcode | App Store (required for `xcrun simctl`) |
| `idb-companion` | `brew tap facebook/fb && brew install idb-companion` |
| `fb-idb` | `python3 -m venv ~/.local/idb-venv && ~/.local/idb-venv/bin/pip install fb-idb` |

`setup.sh` offers to install these dependencies automatically. If you decline or are on Linux, the MCP stays configured in `opencode.json` but will fail at runtime — you can disable it by setting `"enabled": false`.

Related environment variables (shell rc, block managed by `setup.sh` — the
ios-simulator MCP does not read `.env`):

| Variable | Usage |
|----------|-------|
| `IDB_UDID` | Target iOS simulator UDID (auto-detected by `setup.sh`) |
| `IDB_PATH` | Path to the `idb` binaries (default: `~/.local/idb-venv/bin:...`) |

### 5. Initialize a project

```bash
cd my-project
~/.config/opencode-config/scripts/init-project.sh
# or from the repo: npm run init-project
```

To preview without changing anything:

```bash
~/.config/opencode-config/scripts/init-project.sh --dry-run
# or from the repo: npm run init-project -- --dry-run
```

Result:

```txt
my-project/
├── AGENTS.md
└── docs/
    └── ai/
        ├── PLAN.md       → current technical plan
        ├── STATUS.md     → progress state
        ├── DECISIONS.md  → structural decisions
        ├── CHANGELOG.md  → session history
        ├── BUFFER.md     → session buffer
        ├── INDEX.md      → project map
        └── WARNINGS.md   → alerts and technical debt
```

### 6. Sync an existing project

```bash
~/.config/opencode-config/scripts/sync-project.sh
# or from the repo: npm run sync
```

To preview without changing anything:

```bash
~/.config/opencode-config/scripts/sync-project.sh --dry-run
# or from the repo: npm run sync -- --dry-run
```

By default, the script does not overwrite existing files. It creates `.new` files if a version already exists. If a `.new` file already exists, it creates a timestamped file to avoid overwriting an in-progress merge.

Operational in under 2 minutes.

## Models and Fallback

### 17 configured models

The configuration uses **17 models** across 6 categories:

| Category | Models | Max context | Cost (input/output) | Usage |
|----------|--------|-------------|---------------------|-------|
| **Expert** | euria-code (GLM-5.2) | 250k | $0.60 / $3.00 | Complex reasoning, architecture, security, review, code |
| | euria-code-tiny | 200k | $0.30 / $0.40 | Lightweight version of euria-code, multimodal (image) |
| **Intermediate** | Mistral-Small-4 (119B) | 256k | $0.20 / $0.75 | Commits, CLI skills, technical SEO, content |
| | Kimi-K2.6 | 256k | $0.60 / $3.00 | Large-context fallback |
| | Qwen3.5-397B | 204k | $0.80 / $3.60 | Native multimodal (image+video), available on request |
| | Qwen3.5-122B | 200k | $0.40 / $3.20 | Intermediate Qwen, 100k output |
| **Light** | Ministral-3 (14B) | 80k | $0.30 / $0.40 | Light model (not used by default) |
| | Gemma-4-31B | 100k | $0.20 / $0.40 | General tasks |
| | Apertus-70B | 100k | $0.70 / $2.50 | General tasks |
| **Ultra-light** | **Nemotron-3-Nano (30B)** | **1M** | **$0.05 / $0.20** | **Ultimate fallback, large contexts** |
| **Embedding** | Qwen3-Embedding-8B | 32k | $0.01 / $0 | Vectorization (recommended) |
| | bge_multilingual_gemma2 | 8k | $0.01 / $0 | Multilingual FR/EN |
| | mini_lm_l12_v2 | 512 | $0.005 / $0 | Short texts |
| **Transcription** | whisper | 448k | $0.006 / $0 | Audio → text |

### Automatic fallback

When a prompt exceeds a model's context limit, OpenCode switches **automatically** to a model with more context:

```
Ministral-3 (80k)      → Mistral-Small-4 (256k) → Kimi-K2.6 → Nemotron-3-Nano (1M)
euria-code (250k)      → Kimi-K2.6 (256k)       → Nemotron-3-Nano (1M)
Gemma-4 (100k)         → Mistral-Small-4 (256k) → Kimi-K2.6 → Nemotron-3-Nano (1M)
Qwen3.5-397B (204k)    → Kimi-K2.6 (256k)       → Nemotron-3-Nano (1M)
```

> **Benefit**: the ultimate fallback (Nemotron-3-Nano) is the **cheapest** model ($0.05/1M tokens). Very large contexts actually cost *less*.

### Agent assignment

| Agent | Model | Why |
|-------|-------|-----|
| `aurora`, `aurora-heavy`, `architect`, `security`, `cybersec`, `reviewer`, `atlas`, `sage`, `mobile`, `tester`, `build`, `plan` | euria-code (GLM-5.2) | Expert reasoning, code, security, native 1M long-context |
| `designer`, `vision` | Qwen3.5-397B | Native multimodal (image+video), screenshot and mockup analysis |
| `echo`, `scribe`, `pulse`, `beacon`, `crawler` | Mistral-Small-4 (119B) | Good cost/performance/creativity balance |
| `spark` | Mistral-Small-4 (119B) | Commits, CLI skills — 256k context avoids the compaction loop |
| `oracle` (plugin) | euria-code (high variant) | Strategic advisory, adversarial review |
| `fixer` (plugin) | Qwen3.5-122B | Fast spec execution |
| `explorer`, `librarian` (plugin) | Ministral-3 (14B) | Fast codebase / external docs search |

---

## Automatic Project Memory Discovery

Aurora automatically detects the `docs/ai/` folder at the project root at the start of every session.

### Automatic read at bootstrap

If `docs/ai/` exists, Aurora immediately loads:

1. `STATUS.md` — current state, blockers, next step
2. `PLAN.md` — current technical plan
3. `WARNINGS.md` — active alerts and risk zones
4. `INDEX.md` — project map

### Conditional reads

- **BUFFER.md**: loaded only when resuming an interrupted session, when `STATUS.md` reports a blocker, or when the user explicitly asks to resume a task.
- **DECISIONS.md**: consulted JIT (Just-In-Time) when a structural decision, a contradiction or an architecture overhaul is detected.
- **CHANGELOG.md**: consulted JIT when a regression is suspected or the user asks for history.

### Why `.new` files are never read

During a sync (`sync-project.sh`), existing files are not overwritten. The script generates `.new` files as update proposals, or `.new.YYYYMMDD-HHMMSS` if a proposal already exists.
**OpenCode never reads `.new` files automatically.** They must be merged manually into the official files.

### Existing Project Adoption Checklist

To adopt project memory on an existing project that already has `docs/ai/`:

1. Run `init-project.sh` in the existing project.
2. Check the files created in `docs/ai/`.
3. Compare any generated `.new` files.
4. Manually merge the useful sections.
5. Delete the `.new` files once processed.
6. Start OpenCode with Aurora.
7. Verify that Aurora announces the detected project memory.

---

## Architecture

```txt
Global Configuration
        ↓
     Standards    (workflow, memory-session-flow, memory-auto-update, memory-checklist, verification, communication, escalation, commits, review-before-done, audit, exploration-limits, error-correction, anti-patterns, artifact-authoring, delegation-failure, agent-output)
        ↓
          Agents       (aurora, aurora-heavy, reviewer, tester, security, cybersec, architect, spark, vision, atlas, crawler, sage, scribe, pulse, echo, beacon, designer, mobile) + plugin (explorer, fixer, librarian, oracle)
        ↓
    Frameworks     (angular-20, nodejs, nestjs, astro...)
        ↓
 Project AGENTS.md (local source of truth)
        ↓
   Project Docs    (PLAN, STATUS, DECISIONS, CHANGELOG, BUFFER, INDEX, WARNINGS)
```

**Standards**: universal behaviors applicable to any project.
**Agents**: specialized personalities for specific tasks.
**Frameworks**: technical rules per stack (Angular, Node.js, NestJS, Astro).
**Project AGENTS.md**: ultimate source of truth, local always takes precedence.
**Project Docs**: persistent session memory across AI conversations.

---

## What's in it for you?

| Benefit | Description |
|---------|-------------|
| **Consistency** | Identical agent behavior on every machine |
| **Time savings** | Project initialization in 3 seconds |
| **Quality** | Built-in Angular 20+ standards + adversarial review + read-only audit + exploration limits |
| **Traceability** | Every agent documents its plan, decisions and progress |
| **Security** | Automatic security checklist at every review |
| **Session memory** | BUFFER, INDEX and WARNINGS for long and complex projects |
| **Teamwork** | Universal workflow: Explore → Plan → Implement → [PARALLEL GATE] → Commit |

---

## How to use it

After installation, the Aurora agent (main) automatically loads:

```txt
1. Global standards (workflow, communication, verification...)
2. Global agents (aurora, aurora-heavy, reviewer, tester, security, cybersec, architect, spark, vision, atlas, crawler, sage, scribe, pulse, echo, beacon, designer, mobile) + plugin agents (explorer, fixer, librarian, oracle)
3. Targeted framework (Angular 20+, Node.js, etc.)
4. Company standards (if configured)
5. Local AGENTS.md + docs/ai/
```

The golden rule: **local always takes precedence**. The `AGENTS.md` at the project root is the ultimate source of truth.

---

## How to customize

### Customize the agents

Edit the files in the cloned repo, then run `npm run update` (or `./scripts/install.sh`).

The available agents live in `agents/`:

| Agent | Role |
|-------|------|
| `aurora.md` | Main agent — loading and coordination |
| `aurora-heavy.md` | Agent for complex tasks (euria-code) |
| `reviewer.md` | Strict code review |
| `tester.md` | Quality tests |
| `security.md` | Defensive cybersecurity — AppSec, threat modeling, secure code review, DevSecOps, hardening |
| `cybersec.md` | Offensive cybersecurity — pentest, Red Team, exploitation, recon, bypass, privesc |
| `architect.md` | Technical breakdown |
| `spark.md` | Lightweight subagent (commit, MR) |
| `vision.md` | Multimodal subagent (images, screenshots) |
| `atlas.md` | SEO Strategy — strategy, keyword research, content gaps |
| `crawler.md` | Technical SEO — technical SEO audit and fixes |
| `sage.md` | AIO / GEO — optimization for generative search engines |
| `scribe.md` | SEO Content — editorial production and optimization |
| `pulse.md` | Growth Marketing — acquisition, conversion, funnel |
| `echo.md` | Social Distribution — multi-channel distribution |
| `beacon.md` | Analytics — SEO and marketing measurement |
| `designer.md` | UX/UI Designer — interface design, art direction, design system, accessibility (2 modes: standalone / Infomaniak DS) |
| `mobile.md` | Mobile Engineer — iOS, Android, React Native, Flutter |

> Agents **provided by the plugin** `oh-my-opencode-slim` (config `config/oh-my-opencode-slim.json`): `explorer` (codebase search), `fixer` (fast spec execution), `librarian` (external docs search), `oracle` (strategic technical advisory, adversarial review).

### Add a framework

Create a `frameworks/<my-framework>.md` file in the repo:

```txt
frameworks/
├── angular-20.md   # Angular 20+ stand-alone
├── nodejs.md       # Node.js API / Express
├── nestjs.md       # Modular NestJS architecture
└── astro.md        # Astro static sites, SEO, i18n
```

The file name becomes the framework name. Run `npm run update` (or `./scripts/install.sh`) to deploy it.

### Create a new rule

1. In the `~/.config/opencode-config` repo
2. Create a file in `standards/` (universal) or `agents/` (specialized role)
3. Run `npm run update` (or `./scripts/install.sh`)
4. Reference it in the `AGENTS.md` of the relevant project

### Customize the session workflow

Edit `standards/workflow.md` and `standards/memory-session-flow.md` to adapt the work cycle and session memory handling.

### Adapt a project's stack

The `AGENTS.md` template is intentionally generic. Add the useful stack conventions to the local `AGENTS.md`, or reference a global framework:

- `frameworks/angular-20.md`
- `frameworks/nodejs.md`
- `frameworks/nestjs.md`
- `frameworks/astro.md`

---

## Repository structure

```txt
opencode-config/
│
├── README.md
├── LICENSE
├── CHANGELOG.md
│
├── config/                     OpenCode config (versioned, no secrets)
│   ├── opencode.json             Providers, models, permissions, MCP servers
│   ├── oh-my-opencode-slim.json  Subagent presets (euria-code)
│   ├── package.json              @opencode-ai/plugin dependency
│   ├── .env.example              Environment variable template
│   └── plugins/
│       └── rtk.ts                RTK plugin (token savings via rtk rewrite)
│
├── standards/               Universal behaviors
│   ├── workflow.md            Explore→Plan→Implement→[PARALLEL GATE]→Commit cycle
│   ├── error-correction.md    Stop after 2 failures to avoid the spiral
│   ├── anti-patterns.md       Stop the 5 typical session patterns
│   ├── artifact-authoring.md  Create standards/agents/frameworks without duplicates
│   ├── delegation-failure.md  Mandatory procedure after subagent failure
│   ├── agent-output.md        Structured JSON output format for subagents
│   ├── audit.md               Multi-axis read-only audit
│   ├── review-before-done.md  Adversarial review before declaring done
│   ├── exploration-limits.md  Targeted exploration and subagents
│   ├── memory-session-flow.md     Automatic docs/ai/ reading order at session start
│   ├── memory-checklist.md        Memory checklist at session end
│   ├── memory-auto-update.md      Memory persistence standard
│   ├── verification.md            Mandatory build/lint/test checks
│   ├── communication.md           Directness, ownership, pushback
│   ├── escalation.md              Blocker handling
│   └── commits.md                 Commit format and rules
│
├── agents/                    Specialized personalities
│   ├── aurora.md              Main agent and coordinator
│   ├── aurora-heavy.md        Agent for complex tasks (euria-code)
│   ├── reviewer.md            Strict code review
│   ├── tester.md              Jest + Angular tests
│   ├── security.md            Defensive cybersecurity (AppSec, threat modeling, DevSecOps)
│   ├── cybersec.md             Offensive cybersecurity (pentest, Red Team, exploitation)
│   ├── architect.md           Technical breakdown
│   ├── spark.md               Lightweight subagent (commit, MR)
│   ├── vision.md              Multimodal subagent (images, screenshots)
│   ├── atlas.md               SEO Strategy
│   ├── crawler.md             Technical SEO
│   ├── sage.md               AIO / GEO
│   ├── scribe.md              SEO Content
│   ├── pulse.md              Growth Marketing
│   ├── echo.md                Social Distribution
│   ├── beacon.md              Analytics
│   ├── designer.md            UX/UI Designer, art direction, Design System (2 modes)
│   └── mobile.md              Mobile Engineer (iOS/Android/RN/Flutter)
│
├── frameworks/                Per-stack technical rules
│   ├── angular-20.md          Angular 20+ stand-alone conventions
│   ├── nodejs.md              Node.js API conventions
│   ├── nestjs.md              NestJS conventions
│   └── astro.md               Astro conventions
│
├── templates/                 What every project receives
│   ├── AGENTS.md              Root template for every project
│   ├── PLAN.md                Current technical plan
│   ├── STATUS.md              Progress state
│   ├── DECISIONS.md           Structural decisions
│   ├── CHANGELOG.md           Agent journal
│   └── project-docs/
│       ├── BUFFER.md          Session buffer
│       ├── INDEX.md           Project map
│       └── WARNINGS.md        Alerts and technical debt
│
├── examples/                  Ready-to-use examples
│   ├── angular-app/           Complete Angular 20+ project (AGENTS.md + docs/ai/)
│   ├── node-api/              Node.js API project (AGENTS.md + README)
│   └── monorepo/              Multi-package monorepo (AGENTS.md + README)
│
├── mcp/                       Local MCP servers
│   ├── infomaniak/            Infomaniak API (radio, VOD, newsletter, DNS, events, AI)
│   └── angular-elements/      Angular Elements design system (components, API, stories)
│
├── tools/                     Infrastructure CLIs (repo-only, not installed as agents)
│   └── figma-ds/              Infomaniak Figma design system sync CLI
│       ├── src/               Strict TypeScript (check / sync / diff / mapping)
│       ├── tests/             node:test suite (53 tests)
│       └── *-reference.json   Manual references (Figma families, ik-* components)
│
├── skills/                    Reusable skills
│   ├── accessibility/         Accessibility suite (17 orchestrated sub-skills: aria, contrast, focus, keyboard, forms…)
│   ├── ai-cowork/             Aurora ↔ ChatGPT co-working (autonomous review loop via browser-debug)
│   ├── allow-command/         Pre-approve shell commands in opencode.json
│   ├── clonedeps/             Clone dependency sources to inspect library internals
│   ├── code-review/           Adversarial code review
│   ├── codemap/               Hierarchical code maps for unknown repos
│   ├── commit/                Commit messages (Infomaniak conventions)
│   ├── create-mr/             Merge request creation (scripts + tests)
│   ├── deepwork/              Orchestrated multi-phase workflow with review gates (heavy efforts)
│   ├── deployment-changelog/  Deployment changelog
│   ├── figma-ds-sync/         Infomaniak Figma design system sync (check/sync/diff/mapping)
│   ├── gitlab-ci/             GitLab CI/CD interaction (glab)
│   ├── gitlab-feature-planner/  GitLab issues from an estimation table + MR grouping suggestions
│   ├── gitlab-issues/         GitLab issue management (glab)
│   ├── gitlab-summary/        GitLab activity summary
│   ├── image-transparent-background/  White background removal (ImageMagick)
│   ├── laravel-cruddy-by-design/  Strict RESTful Laravel controllers/routes (max 7 methods)
│   ├── loop-engineering/      Grill + Monitor runtime for engineering loops
│   ├── mr-review/             MR review with inline comments
│   ├── mr-review-feedback/    Apply MR review feedback
│   ├── new-worktree/          Branch + worktree from a single intent (never destructive)
│   ├── oh-my-opencode-slim/   Configuration and tuning of the oh-my-opencode-slim plugin
│   ├── pre-mr-review/         Pre-MR quality review
│   ├── radio-tag-genres/      Music genre tagging for radio playlists
│   ├── readme/                 README generation
│   ├── reflect/               Past session analysis → reusable skills/config
│   ├── release-smoke-test/    oh-my-opencode-slim release validation
│   ├── review-gap-analyzer/   Review feedback → AGENTS.md/pre-mr-review rule improvements
│   ├── simplify/              Code simplification without behavior change
│   ├── translate-doc/         Documentation translation
│   ├── user-stories/          User story writing
│   ├── verification-planning/ Verification plan before non-trivial code changes
│   └── worktrees/             Git worktrees as isolated lanes (OMO protocol)
│
├── scripts/                   Automation
│   ├── setup.sh                Full installation (first time, interactive)
│   ├── install.sh              Install/update the global config
│   ├── init-project.sh         Initialize a new project (stack auto-detection)
│   ├── sync-project.sh         Sync the templates
│   ├── health-check.sh         Check config consistency (JSON, agents, models)
│   ├── permissions-matrix.sh   Generate an agent permissions table
│   ├── validate-memory.sh     Validate a project's docs/ai/ structure
│   ├── create-mr/              MR creation scripts (build_body, check_workspace, detect_target_branch, detect_template, push_branch, tests, upload_media, validate_title)
│   └── hooks/
│       └── pre-commit-secrets.sh  Git hook against secret leaks
│
└── docs/                      User guides
    ├── ai/                   Repo project memory (PLAN, STATUS, DECISIONS, CHANGELOG, BUFFER, INDEX, WARNINGS)
    ├── workflow.md            How the work cycle works
    ├── customization.md        How to customize and extend
    ├── angular-20.md          Detailed Angular 20+ rules
    ├── code-review.md         Code review guide
    ├── testing.md             Testing guide
    └── architecture.md        Architecture guide
```

---

## Priority order

The agent receives and applies in this order (from most general to most specific; the most specific wins):

1. Global **Standards** `~/.config/opencode/standards/` (workflow, memory-session-flow, memory-auto-update, memory-checklist, verification, communication, escalation, commits, review-before-done, audit, exploration-limits, error-correction, anti-patterns, artifact-authoring, delegation-failure, agent-output).
2. Global **Agents** `~/.config/opencode/agents/` (aurora, aurora-heavy, reviewer, tester, security, cybersec, architect, spark, vision, atlas, crawler, sage, scribe, pulse, echo, beacon, designer, mobile) + oh-my-opencode-slim plugin agents (explorer, fixer, librarian, oracle).
3. Global **Frameworks** `~/.config/opencode/frameworks/` (angular-20, nodejs, nestjs, astro).
4. Company standards (if configured).
5. Project-local **`AGENTS.md`**.
6. Explicit instructions of the current task.

---

## License

MIT
