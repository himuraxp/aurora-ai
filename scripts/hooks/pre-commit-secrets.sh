#!/usr/bin/env bash
set -euo pipefail

# hooks/pre-commit-secrets.sh — Git pre-commit hook to detect accidental secrets.
#
# Patterns detected:
#   - API keys (OPENAI_API_KEY=, Bearer tokens, JWT, Google, Stripe, AWS, GitHub, GitLab)
#   - Private keys (BEGIN PRIVATE KEY, BEGIN RSA PRIVATE KEY)
#   - Passwords in config (password=, passwd=, pwd=)
#   - Connection strings (mongodb://, postgresql:// with credentials)
#   - Slack tokens
#
# Installation:
#   cp scripts/hooks/pre-commit-secrets.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Or via core.hooksPath:
#   git config core.hooksPath scripts/hooks

# Patterns that indicate potential secrets
# NOTE: use [[:space:]] instead of \s for BSD grep (macOS) compatibility
# NOTE: patterns are evaluated with `grep -E` (ERE). Do NOT use BRE escapes
#       (\+, \{n\}) — they are LITERAL characters in ERE and silently disable
#       the pattern (audited 2026-10-09). Every pattern here is validated by
#       scripts/hooks/test-pre-commit-patterns.sh (run in health-check).
# NOTE: name-assignment patterns require a value-looking prefix (["']?[A-Za-z0-9])
#       so that prose like `export GITLAB_TOKEN="$(...)"` or empty placeholders
#       in .env.example do not trigger false positives.
PATTERNS=(
  '(^|[^A-Za-z0-9_])OPENAI_API_KEY[A-Za-z_]*=[A-Za-z0-9]'
  'Bearer[[:space:]]+[A-Za-z0-9._-]{20,}'
  '-----BEGIN[A-Z ]*PRIVATE KEY-----'
  'password[[:space:]]*[:=][[:space:]]*[A-Za-z0-9]'
  'passwd[[:space:]]*[:=][[:space:]]*[A-Za-z0-9]'
  'pwd[[:space:]]*[:=][[:space:]]*[A-Za-z0-9]'
  'mongodb://[^:]+:[^@]+@'
  'postgresql://[^:]+:[^@]+@'
  'mysql://[^:]+:[^@]+@'
  'redis://[^:]+:[^@]+@'
  'xox[baprs]-[A-Za-z0-9-]'                            # Slack tokens
  'gh[pu]_[A-Za-z0-9]{36}'                             # GitHub tokens
  'AKIA[A-Z0-9]{16}'                                   # AWS access keys
  'glpat-[A-Za-z0-9_-]{20}'                            # GitLab PAT
  'PAT[A-Za-z0-9_.-]{10,}\.01\.'                       # GitLab internal PAT format
  'figd_[A-Za-z0-9._-]{16,}'                           # Figma personal access token
  '(^|[^A-Za-z0-9_])INFOMANIAK_API_TOKEN[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9]'         # Infomaniak API token assignment
  '(^|[^A-Za-z0-9_])INFOMANIAK_PREPROD_API_TOKEN[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9]' # Infomaniak preprod token assignment
  '(^|[^A-Za-z0-9_])FIGMA_TOKEN[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9]'                  # Figma token assignment
  '(^|[^A-Za-z0-9_])GITLAB_TOKEN[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9]'                 # GitLab token assignment
  'AIza[0-9A-Za-z_-]{35}'                              # Google API keys
  'sk_live_[A-Za-z0-9]{24,}'                           # Stripe secret keys
  'sk-proj-[A-Za-z0-9_-]{20,}'                         # OpenAI project keys (bare)
  'sk-ant-[A-Za-z0-9_-]{20,}'                          # Anthropic keys (bare)
  'pk\.[a-z0-9]{1,12}\.[A-Za-z0-9]{20,}'               # Infomaniak app tokens (bare)
  'eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*'  # JWT tokens
)

# File extensions to check (skip binaries, images, lock files)
CHECK_EXT=(
  .ts .js .json .md .yml .yaml .env .sh .py .rb .go .rs .java .kt .swift .php .css .scss .html .xml .toml .ini .cfg .conf
)

# Files to skip entirely
SKIP_FILES=(
  package-lock.json
  yarn.lock
  pnpm-lock.yaml
  .env.example
  test-pre-commit-patterns.sh   # fixture suite: contains sample secret SHAPES by design
)

# Get staged files
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

# Optional deep scan: gitleaks covers far more detectors than the regex list
# below. FAIL-CLOSED by design (audited 2026-10-09): a missing tool or a
# tool error BLOCKS the commit. Explicit escape hatch for a single commit:
#   HOOK_SKIP_GITLEAKS=1 git commit ...   (regex-only, warning printed)
if [[ "${HOOK_SKIP_GITLEAKS:-0}" == "1" ]]; then
  echo "pre-commit: gitleaks deep scan skipped (HOOK_SKIP_GITLEAKS=1)"
elif command -v gitleaks >/dev/null 2>&1; then
  echo "pre-commit: gitleaks deep scan on staged changes…"
  set +e
  gitleaks protect --staged --redact -v
  gitleaks_rc=$?
  set -e
  if [[ $gitleaks_rc -eq 1 ]]; then
    echo ""
    echo "gitleaks detected potential secrets in staged changes."
    echo "Review the report above. If these are false positives, add an"
    echo "allowlist entry to .gitleaksignore, or commit with --no-verify."
    exit 1
  elif [[ $gitleaks_rc -ne 0 ]]; then
    echo ""
    echo "gitleaks failed (exit $gitleaks_rc) — blocking commit (fail-closed)."
    echo "Fix the gitleaks installation/config, or use HOOK_SKIP_GITLEAKS=1."
    exit 1
  fi
else
  echo "pre-commit: gitleaks NOT installed — blocking commit (fail-closed)." >&2
  echo "  Install it: brew install gitleaks" >&2
  echo "  Or accept regex-only for THIS commit: HOOK_SKIP_GITLEAKS=1 git commit ..." >&2
  exit 1
fi

found_secrets=0

# Use null-terminated output to handle filenames with spaces
while IFS= read -r -d '' file; do
  # Check if file should be skipped by name
  basename_file=$(basename "$file")
  skip_file=false
  for skip in "${SKIP_FILES[@]}"; do
    [[ "$basename_file" == "$skip" ]] && skip_file=true && break
  done
  [[ "$skip_file" == true ]] && continue

  # Check if it's a .env file (catches .env, .env.local, .env.production, etc.)
  is_env=false
  [[ "$basename_file" == .env* ]] && is_env=true

  # Check extension (unless it's a .env file)
  should_check=false
  if [[ "$is_env" == true ]]; then
    # .env files are always checked (except .env.example which is skipped above)
    should_check=true
  else
    ext="${file##*.}"
    for check_ext in "${CHECK_EXT[@]}"; do
      [[ ".$ext" == "$check_ext" ]] && should_check=true && break
    done
  fi
  [[ "$should_check" == false ]] && continue

  # Check each pattern in the staged diff (-e so patterns starting with "--" are not parsed as options)
  for pattern in "${PATTERNS[@]}"; do
    matches=$(git diff --cached -- "$file" 2>/dev/null | grep -E "^\+" | grep -Ee "$pattern" || true)
    if [[ -n "$matches" ]]; then
      echo "WARNING: Potential secret in $file:"
      echo "$matches" | head -3 | sed 's/^/  /'
      found_secrets=$((found_secrets + 1))
    fi
  done
done < <(git diff --cached --name-only --diff-filter=ACMR -z 2>/dev/null || true)

if [[ $found_secrets -gt 0 ]]; then
  echo ""
  echo "Found $found_secrets potential secret(s) in staged files."
  echo "If these are false positives, commit with --no-verify."
  echo "Otherwise, move secrets to your shell rc (shell exports) or"
  echo "~/.config/opencode/.env (vars for MCP/tools, read manually by their clients)."
  exit 1
fi

exit 0
