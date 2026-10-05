# agents/

> **Language note:** the agent definition files (`.md`) in this folder are written in French — the maintainer's working language. The agent runtime consumes them language-agnostically, so behavior is unaffected. Public-facing docs: the [root README](../README.md) and [`docs/`](../docs/).

Specialized OpenCode personalities. Each `.md` file defines an agent with its role, model, permissions and delegation rules.

## Agents

### Orchestrators

| Agent | Model | Role |
|-------|-------|------|
| `aurora` | euria-code | Main orchestrator. Multi-agent coordinator, automatic delegation via trigger keywords |
| `aurora-heavy` | euria-code | Advanced reasoning. Critical architecture, complex legacy |

### Engineering

| Agent | Model | Role |
|-------|-------|------|
| `architect` | euria-code | Technical breakdown, structure, coupling, technical debt, migration |
| `reviewer` | euria-code | Adversarial code review before merge |
| `tester` | euria-code | Unit tests, integration, coverage (Jest, Cypress, Vitest) |
| `security` | euria-code | Defensive security — AppSec, threat modeling, OWASP, secure code review |
| `cybersec` | euria-code | Offensive security — pentest, exploitation, Red Team, recon |
| `mobile` | euria-code | iOS, Android, React Native, Flutter — mobile patterns, device performance |
| `designer` | Qwen 3.5-397B | UX/UI, design system, accessibility, mockup analysis |
| `vision` | Qwen 3.5-397B | Non-UI visual analysis — diagrams, photos, charts, schematics |
| `spark` | Mistral-Small-4 | Lightweight tasks — commits, simple CLI skills |

### Search & Growth

| Agent | Model | Role |
|-------|-------|------|
| `atlas` | euria-code | SEO strategy — keyword research, content gaps, topical authority |
| `crawler` | Mistral-Small-4 | Technical SEO — indexing, Core Web Vitals, SSR, structured data |
| `sage` | euria-code | AIO/GEO — AI Overviews, ChatGPT Search, Perplexity, Gemini |
| `scribe` | Mistral-Small-4 | SEO content — copywriting, meta, H1-H3, FAQ |
| `pulse` | Mistral-Small-4 | Growth marketing — acquisition, funnels, A/B testing, landing pages |
| `echo` | Mistral-Small-4 | Social distribution — LinkedIn, Instagram, X, TikTok, Reddit |
| `beacon` | Mistral-Small-4 | Analytics — GSC, GA4, PageSpeed, rank tracking, conversion |

## Collaboration architecture

```
                         Aurora
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
     Engineering          Search           Growth
          │                 │                 │
      Architect           Atlas             Pulse
      Reviewer           Crawler             Echo
      Security           Sage             Beacon
      Cybersec           Scribe
      Tester
      Fixer
      Oracle
      Explorer
      Librarian
      Vision
      Spark
      Designer
      Mobile
```

## Automatic delegation

Aurora detects keywords in the user request and delegates to specialists. See `agents/aurora.md` for the full table of trigger keywords and multi-agent routing.

## Adding an agent

1. Create a `<name>.md` file in this folder
2. Define the frontmatter: `model`, `mode`, `permission`
3. Define the system prompt (role, rules, style)
4. Add the entry in `config/opencode.json` → `agent.<name>`
5. Document the delegation in `agents/aurora.md` if applicable
6. Run `npm run update` (or `./scripts/install.sh`) to deploy

## Authority hierarchy

Instructions apply in descending order (most specific wins):

```
Global standards → Global agents → Frameworks → Project AGENTS.md → docs/ai/
```
