# scripts/hooks/

> **Language note:** the hook scripts referenced here contain French comments — the maintainer's working language. Public-facing docs: the [root README](../../README.md) and [`docs/`](../../docs/).

Git hooks for security and quality. These scripts install into `.git/hooks/` or via `core.hooksPath`.

## Hooks

### pre-commit-secrets.sh

Git pre-commit hook that detects secrets accidentally committed.

**Detected patterns:**
- API keys (OpenAI, Google, Stripe, AWS, GitHub, GitLab)
- Bearer tokens, JWT
- Private keys (`BEGIN PRIVATE KEY`, `BEGIN RSA PRIVATE KEY`)
- Passwords in config (`password=`, `passwd=`, `pwd=`)
- Connection strings with credentials (`mongodb://`, `postgresql://`, `mysql://`, `redis://`)
- Slack tokens (`xox[baprs]-`)

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
- Binary files, images

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
