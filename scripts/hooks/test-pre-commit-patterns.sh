#!/usr/bin/env bash
set -euo pipefail

# hooks/test-pre-commit-patterns.sh — end-to-end validation of pre-commit-secrets.sh.
#
# Builds a sandbox git repo (core.hooksPath pointed at this folder), stages
# positive fixtures (each must be BLOCKED and reported by case id) and negative
# fixtures (must commit cleanly), then runs REAL commits — a hook is only
# proven by a real commit, never by manual execution.
#
# The suite runs the hook with HOOK_SKIP_GITLEAKS=1 so results stay
# deterministic whether or not gitleaks is installed (gitleaks coverage is a
# separate concern; this suite validates the regex layer).
#
# Positive fixtures necessarily contain sample secret SHAPES — this file is
# excluded from its own scan (see SKIP_FILES in pre-commit-secrets.sh).

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
CASE_GITHUB: ghp_AbCdEf1234567890AbCdEf1234567890AbCd
CASE_AWS: AKIAIOSFODNN7EXAMPLE
CASE_GLPAT: GLPAT_PLACEHOLDER
CASE_PAT_FORMAT: token=PATfakesecret1234567890.01.xxxxxxxx
CASE_FIGD: figd_AbCdEf1234567890AbCdEf
CASE_INFOMANIAK_NAME: INFOMANIAK_API_TOKEN=fakeexampletoken
CASE_PREPROD_NAME: INFOMANIAK_PREPROD_API_TOKEN=fakepreprodtoken123
CASE_FIGMA_NAME: FIGMA_TOKEN=fakefigmatoken123
CASE_GITLAB_NAME: GITLAB_TOKEN=PATfakesecret1234567890.01.xxxxxxxx
CASE_GOOGLE: AIzaAbCdEf1234567890AbCdEf1234567890AbC
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

# Assemble two shapes at RUNTIME: this script must never contain a complete
# secret signature, or GitHub push protection blocks any push that carries it.
# Split prefix/body keep the local regex fixtures intact once assembled.
glpat_body="AbCdEf1234567890AbCd"
sklive_body="AbCdEf1234567890AbCdEf1234"
sed -i.bak \
  -e "s|GLPAT_PLACEHOLDER|glpat-${glpat_body}|" \
  -e "s|SKLIVE_PLACEHOLDER|sk_live_${sklive_body}|" \
  "$sandbox/positive-fixtures.md"
rm -f "$sandbox/positive-fixtures.md.bak"

git -C "$sandbox" add positive-fixtures.md
set +e
positive_output="$(git -C "$sandbox" commit -m "positive fixtures" 2>&1)"
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
if ! negative_output="$(git -C "$sandbox" commit -m "negative fixtures" 2>&1)"; then
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

echo "OK: pre-commit hook patterns validated (${#CASES[@]} positive cases blocked, negatives pass, rename bypass blocked)"
