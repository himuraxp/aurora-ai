#!/usr/bin/env bash
set -euo pipefail

# hooks/test-pre-commit-patterns.sh — end-to-end validation of pre-commit-secrets.sh.
#
# Builds a sandbox git repo (core.hooksPath pointed at this folder), stages
# positive fixtures (each must be BLOCKED and reported by case id) and negative
# fixtures (must commit cleanly), then runs REAL commits — a hook is only
# proven by a real commit, never by manual execution.
#
# The regex layer runs with HOOK_SKIP_GITLEAKS=1 so results stay deterministic.
# The gitleaks layer is validated separately below: absence must fail-closed,
# tool errors must fail-closed, and a gitleaks-only detector must be caught.
#
# Positive fixtures necessarily contain sample secret SHAPES — those shapes are
# assembled at RUNTIME inside the sandbox (this file must never contain a
# complete signature: GitHub Push Protection blocks pushes that carry one). The
# file is also excluded from its own scan (see SKIP_FILES in the hook).

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$DIR/pre-commit-secrets.sh"

[[ -x "$HOOK" ]] || { echo "FAIL: $HOOK missing or not executable"; exit 1; }

sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT

git -C "$sandbox" init -q
git -C "$sandbox" config user.email hook-test@example.com
git -C "$sandbox" config user.name "Hook Fixture Test"
git -C "$sandbox" config core.hooksPath "$DIR"

# ─── Baseline: empty change must commit cleanly ───────────────────────────────
echo "baseline" > "$sandbox/README.md"
git -C "$sandbox" add README.md
if ! git -C "$sandbox" commit -qm "baseline"; then
  echo "FAIL: baseline commit was blocked by the hook (false positive)"
  exit 1
fi

# ─── Positive fixtures: each case must be reported (commit must fail) ─────────
cat > "$sandbox/positive-fixtures.md" <<'EOF'
CASE_BEARER: Authorization: Bearer AbCdEf1234567890AbCdEf1234567890AbCdEf12
CASE_MONGODB: mongodb://user:secret123@host.example.com:27017/db
CASE_POSTGRES: postgresql://user:secret123@host.example.com:5432/db
CASE_MYSQL: mysql://user:secret123@host.example.com:3306/db
CASE_REDIS: redis://user:secret123@host.example.com:6379/0
CASE_GITHUB: GHP_PLACEHOLDER
CASE_AWS: AKIAIOSFODNN7EXAMPLE
CASE_GLPAT: GLPAT_PLACEHOLDER
CASE_PAT_FORMAT: token=PATfakesecret1234567890.01.xxxxxxxx
CASE_FIGD: figd_AbCdEf1234567890AbCdEf
CASE_INFOMANIAK_NAME: INFOMANIAK_API_TOKEN=fakeexampletoken
CASE_PREPROD_NAME: INFOMANIAK_PREPROD_API_TOKEN=fakepreprodtoken123
CASE_FIGMA_NAME: FIGMA_TOKEN=fakefigmatoken123
CASE_GITLAB_NAME: GITLAB_TOKEN=PATfakesecret1234567890.01.xxxxxxxx
CASE_GOOGLE: GOOGLE_PLACEHOLDER
CASE_STRIPE: SKLIVE_PLACEHOLDER
CASE_OPENAI_BARE: sk-proj-AbCdEf1234567890AbCdEf123
CASE_ANTHROPIC_BARE: sk-ant-AbCdEf1234567890AbCdEf123
CASE_PK: pk.abc123.AbCdEf1234567890AbCdEf123456
CASE_JWT: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dGVzdF9zaWduYXR1cmVfZmFrZQ
CASE_PRIVATE_KEY: -----BEGIN RSA PRIVATE KEY-----
CASE_PASSWORD: password=hunter2secret
CASE_PASSWD: passwd=hunter2secret-bis
CASE_PWD: pwd=hunter2secret-ter
CASE_SLACK: xoxb-123456789012-AbCdEfGhIjKl
CASE_OPENAI_ENV: OPENAI_API_KEY=sk-fakekey1234567890
EOF

# Assemble four shapes at RUNTIME: this script must never contain a complete
# secret signature, or GitHub Push Protection blocks any push that carries one
# (lived incident 2026-10-09). Split prefix/body keep the local regex fixtures
# intact once assembled.
ghp_body="AbCdEf1234567890AbCdEf1234567890AbCd"
google_body="AbCdEf1234567890AbCdEf1234567890AbC"
glpat_body="AbCdEf1234567890AbCd"
sklive_body="AbCdEf1234567890AbCdEf1234"
sed -i.bak \
  -e "s|GHP_PLACEHOLDER|ghp_${ghp_body}|" \
  -e "s|GOOGLE_PLACEHOLDER|AIza${google_body}|" \
  -e "s|GLPAT_PLACEHOLDER|glpat-${glpat_body}|" \
  -e "s|SKLIVE_PLACEHOLDER|sk_live_${sklive_body}|" \
  "$sandbox/positive-fixtures.md"
rm -f "$sandbox/positive-fixtures.md.bak"

git -C "$sandbox" add positive-fixtures.md
# HOOK_SKIP_GITLEAKS=1: with gitleaks active, it blocks the commit first and
# the hook exits before the regex layer runs — the regex cases would be
# invisible. The gitleaks layer is validated by the dedicated cases below.
set +e
positive_output="$(HOOK_SKIP_GITLEAKS=1 git -C "$sandbox" commit -m "positive fixtures" 2>&1)"
positive_status=$?
set -e

if [[ $positive_status -eq 0 ]]; then
  echo "FAIL: hook did NOT block the positive fixtures"
  exit 1
fi

declare -a CASES=(
  CASE_BEARER CASE_MONGODB CASE_POSTGRES CASE_MYSQL CASE_REDIS CASE_GITHUB
  CASE_AWS CASE_GLPAT CASE_PAT_FORMAT CASE_FIGD CASE_INFOMANIAK_NAME
  CASE_PREPROD_NAME CASE_FIGMA_NAME CASE_GITLAB_NAME CASE_GOOGLE CASE_STRIPE
  CASE_OPENAI_BARE CASE_ANTHROPIC_BARE CASE_PK CASE_JWT CASE_PRIVATE_KEY
  CASE_PASSWORD CASE_PASSWD CASE_PWD CASE_SLACK CASE_OPENAI_ENV
)

missed=0
for id in "${CASES[@]}"; do
  if ! grep -q "$id" <<<"$positive_output"; then
    echo "FAIL: case $id NOT detected by the hook"
    missed=$((missed + 1))
  fi
done
if [[ $missed -gt 0 ]]; then
  echo "FAIL: $missed positive case(s) undetected"
  exit 1
fi

# ─── Negative fixtures: must commit cleanly (no false positives) ──────────────
# Reset the sandbox first: the expected-failure commit above left
# positive-fixtures.md staged, which would contaminate the negative commit.
git -C "$sandbox" restore --staged positive-fixtures.md
rm -f "$sandbox/positive-fixtures.md"

cat > "$sandbox/negative-fixtures.md" <<'EOF'
Docs and interpolations that must NOT trigger the hook:
- Set the INFOMANIAK_API_TOKEN variable in your ~/.config/opencode/.env
- The INFOMANIAK_PREPROD_API_TOKEN and GITLAB_TOKEN names are documented in config/.env.example
- Authorization: Bearer {env:OPENAI_API_KEY_INFOMANIAK}
- config uses {env:INFOMANIAK_API_TOKEN} and {env:GITLAB_TOKEN} interpolation
- Example MR URL: https://gitlab.example.com/acme-group/acme-app/-/merge_requests/123
- Example API: https://api.example.com/v4/projects/1234/repository/files
- Placeholder without value: password=<your-password-here>
- passwd=
- pwd=
EOF

git -C "$sandbox" add negative-fixtures.md
if ! negative_output="$(HOOK_SKIP_GITLEAKS=1 git -C "$sandbox" commit -m "negative fixtures" 2>&1)"; then
  echo "FAIL: hook blocked the negative fixtures (false positives):"
  echo "$negative_output" | sed 's/^/  /'
  exit 1
fi

# ─── Rename bypass: appended secret in a RENAMED file must be blocked ─────────
# Regression guard for the diff-filter: renamed files (status R) must be
# scanned too, otherwise `git mv` + append leaks without detection.
echo "original content" > "$sandbox/renamable.md"
git -C "$sandbox" add renamable.md
git -C "$sandbox" commit -qm "add renamable"
git -C "$sandbox" mv renamable.md renamed.md
echo "CASE_RENAME_SECRET: GITLAB_TOKEN=PATfakebypass9999.01.xxxxxxxx" >> "$sandbox/renamed.md"
git -C "$sandbox" add renamed.md
set +e
rename_output="$(git -C "$sandbox" commit -m "rename with appended secret" 2>&1)"
rename_status=$?
set -e

if [[ $rename_status -eq 0 ]]; then
  echo "FAIL: hook did NOT block a renamed file with an appended secret (diff-filter R bypass)"
  exit 1
fi
if ! grep -q "CASE_RENAME_SECRET" <<<"$rename_output"; then
  echo "FAIL: renamed-file secret not reported"
  exit 1
fi
# Cleanup: the blocked commit left renamed.md staged — unstage and remove it so
# later probe commits (index≠worktree, mutation) carry only their own file.
git -C "$sandbox" reset -q HEAD -- . 2>/dev/null || true
rm -f "$sandbox/renamed.md"

# ─── Index ≠ working tree: staged token hidden from the worktree must block ───
# The hook must scan the STAGED content (git diff --cached / gitleaks --staged),
# not the working tree: a token staged then removed from the file WITHOUT
# re-staging is what actually gets committed.
staged_file="$sandbox/index-vs-worktree.md"
git -C "$sandbox" checkout -q HEAD -- . 2>/dev/null || true
echo "CASE_INDEX_TOKEN: INFOMANIAK_API_TOKEN=fakeindextoken123" > "$staged_file"
git -C "$sandbox" add index-vs-worktree.md
echo "cleaned from worktree — never re-staged" > "$staged_file"
set +e
index_output="$(git -C "$sandbox" commit -m "staged token hidden from worktree" 2>&1)"
index_status=$?
set -e
if [[ $index_status -eq 0 ]]; then
  echo "FAIL: hook scanned the working tree instead of the index (staged-token bypass)"
  exit 1
fi
if ! grep -q "CASE_INDEX_TOKEN" <<<"$index_output"; then
  echo "FAIL: staged-token (index ≠ worktree) not reported"
  exit 1
fi
git -C "$sandbox" restore --staged index-vs-worktree.md 2>/dev/null || true
rm -f "$staged_file"

# ─── gitleaks absent → FAIL-CLOSED (commit must be blocked) ───────────────────
# PATH reduced to the system dirs so gitleaks (/usr/local/bin, brew) is hidden
# while git/grep/sed stay available. No HOOK_SKIP_GITLEAKS escape → must block.
echo "CASE_ABSENT_PROBE: nothing secret here" > "$sandbox/absent-probe.md"
git -C "$sandbox" add absent-probe.md
set +e
absent_output="$(env -i HOME="$HOME" PATH=/usr/bin:/bin git -C "$sandbox" commit -m "gitleaks absent probe" 2>&1)"
absent_status=$?
set -e
if [[ $absent_status -eq 0 ]]; then
  echo "FAIL: hook did NOT fail-closed when gitleaks is absent"
  exit 1
fi
if ! grep -qi "fail-closed" <<<"$absent_output"; then
  echo "FAIL: gitleaks-absent block message does not mention fail-closed"
  exit 1
fi
git -C "$sandbox" restore --staged absent-probe.md 2>/dev/null || true
rm -f "$sandbox/absent-probe.md"

# ─── gitleaks tool error → FAIL-CLOSED (commit must be blocked) ───────────────
# A fake gitleaks exiting 3 (not 0/1) simulates a broken tool/config: the hook
# must block instead of silently passing.
shim="$(mktemp -d)"
printf '#!/bin/sh\nexit 3\n' > "$shim/gitleaks"
chmod +x "$shim/gitleaks"
echo "CASE_ERROR_PROBE: nothing secret here" > "$sandbox/error-probe.md"
git -C "$sandbox" add error-probe.md
set +e
error_output="$(env -u HOOK_SKIP_GITLEAKS PATH="$shim:$PATH" git -C "$sandbox" commit -m "gitleaks error probe" 2>&1)"
error_status=$?
set -e
if [[ $error_status -eq 0 ]]; then
  echo "FAIL: hook did NOT fail-closed when gitleaks errored (exit 3)"
  exit 1
fi
if ! grep -qi "fail-closed" <<<"$error_output"; then
  echo "FAIL: gitleaks-error block message does not mention fail-closed"
  exit 1
fi
git -C "$sandbox" restore --staged error-probe.md 2>/dev/null || true
rm -f "$sandbox/error-probe.md" "$shim/gitleaks" && rmdir "$shim"

# ─── gitleaks-only detector (npm_ token): gitleaks layer proven on its own ────
# npm_ is NOT in the hook regex list: if this case is blocked, it can only be
# by gitleaks. Skipped with a notice when gitleaks is not installed.
if command -v gitleaks >/dev/null 2>&1; then
  echo "CASE_NPM_ONLY: token=npm_AbCdEf1234567890AbCdEf1234567890AbCd" > "$sandbox/npm-only.md"
  git -C "$sandbox" add npm-only.md
  set +e
  npm_output="$(env -u HOOK_SKIP_GITLEAKS git -C "$sandbox" commit -m "gitleaks-only detector" 2>&1)"
  npm_status=$?
  set -e
  if [[ $npm_status -eq 0 ]]; then
    echo "FAIL: gitleaks did NOT catch the npm_ token (gitleaks-only case)"
    exit 1
  fi
  git -C "$sandbox" restore --staged npm-only.md 2>/dev/null || true
  rm -f "$sandbox/npm-only.md"
  gitleaks_validated="gitleaks-only case blocked"
else
  gitleaks_validated="gitleaks-only case SKIPPED (gitleaks not installed)"
fi

# ─── Mutation test: the suite must detect a silenced pattern ──────────────────
# Copy the hook, delete the glpat pattern, run a glpat fixture through the
# mutated hook: it must NOT block. This proves the suite would catch a pattern
# regression (a silent detection loss) instead of green-lighting it.
mutated_dir="$(mktemp -d)"
sed '/glpat-\[A-Za-z0-9_-\]{20}/d' "$HOOK" > "$mutated_dir/pre-commit"
chmod +x "$mutated_dir/pre-commit"
glpat_mutated="glpat-MutAtEd1234567890Ab"
echo "CASE_MUTATION: token=$glpat_mutated" > "$sandbox/mutation-probe.md"
git -C "$sandbox" add mutation-probe.md
set +e
mutation_output="$(HOOK_SKIP_GITLEAKS=1 git -C "$sandbox" -c core.hooksPath="$mutated_dir" commit -m "mutation probe" 2>&1)"
mutation_status=$?
set -e
if [[ $mutation_status -ne 0 ]]; then
  echo "FAIL: mutation test inconclusive — mutated hook still blocked (suite insensitive to pattern removal?)"
  echo "$mutation_output" | sed 's/^/  /'
  exit 1
fi
git -C "$sandbox" restore --staged mutation-probe.md 2>/dev/null || true
rm -f "$sandbox/mutation-probe.md" "$mutated_dir/pre-commit" && rmdir "$mutated_dir"

echo "OK: pre-commit hook patterns validated (${#CASES[@]} positive cases blocked, negatives pass, rename bypass blocked, index≠worktree blocked, gitleaks fail-closed ×2, $gitleaks_validated, mutation detected)"
