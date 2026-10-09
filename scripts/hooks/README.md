# scripts/hooks/

> **Language note:** the hook scripts referenced here contain French comments — the maintainer's working language. Public-facing docs: the [root README](../../README.md) and [`docs/`](../../docs/).

Git hooks for security and quality. These scripts install into `.git/hooks/` or via `core.hooksPath`.

## Hooks

### pre-commit-secrets.sh

Git pre-commit hook that detects secrets accidentally committed.

**Detected patterns:**
- API keys (OpenAI, Google, Stripe, AWS, GitHub, GitLab)
- Infomaniak tokens (`INFOMANIAK_API_TOKEN=`, `INFOMANIAK_PREPROD_API_TOKEN=`, `pk.` app tokens, internal GitLab `PAT….01.…` format)
- Figma tokens (`figd_`, `FIGMA_TOKEN=`), GitLab tokens (`glpat-`, `GITLAB_TOKEN=`)
- Bearer tokens, JWT
- Private keys (`BEGIN PRIVATE KEY`, `BEGIN RSA PRIVATE KEY`)
- Passwords in config (`password=`, `passwd=`, `pwd=`)
- Connection strings with credentials (`mongodb://`, `postgresql://`, `mysql://`, `redis://`)
- Slack tokens (`xox[baprs]-`)

Patterns are **ERE** (`grep -E`, BSD-compatible: use `[[:space:]]`, never `\s`, and no BRE escapes like `\+` or `\{n\}` — they are literal in ERE and silently disable the pattern).

**Installation:**

```bash
# Method 1: direct copy
cp scripts/hooks/pre-commit-secrets.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# Method 2: core.hooksPath (recommended)
git config core.hooksPath scripts/hooks
```

**Ignored files:**
- `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
- `.env.example`
- `test-pre-commit-patterns.sh` (fixture suite — contains sample secret SHAPES by design)
- Binary files, images

**Deep scan (gitleaks):**

When `gitleaks` is installed, the hook runs `gitleaks protect --staged --redact` first (far more detectors than the regex layer). Configuration lives in the root `.gitleaks.toml` (allowlists the fixture suite). Set `HOOK_SKIP_GITLEAKS=1` to force regex-only mode (used by the fixture suite for determinism).

**Validation:**

`scripts/hooks/test-pre-commit-patterns.sh` is an end-to-end fixture suite: it builds a sandbox git repo, runs REAL commits with positive fixtures (26 cases — each must be blocked and reported by case id), negative fixtures (must pass), and a rename-bypass case (`git mv` + appended secret). It is executed by `scripts/health-check.sh` (section "Git hooks").

**False positives:**

If a detection is a false positive, commit with `--no-verify`:

```bash
git commit --no-verify
```

## Adding a hook

1. Create a `<hook-name>.sh` file in this folder
2. Make it executable (`chmod +x`)
3. Document the patterns and installation
4. Run `npm run update` (or `./scripts/install.sh`) to deploy
