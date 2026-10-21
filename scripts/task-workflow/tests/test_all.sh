#!/usr/bin/env bash
# test_all.sh — Tests for task-workflow scripts (trello_comment.sh).
#
# Usage: bash test_all.sh
#
# Zero network: curl is stubbed on PATH and reads the curl config that the
# script passes via stdin (-K -). All assertions are local.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SCRIPT="$SCRIPTS_DIR/trello_comment.sh"

PASS=0
FAIL=0
TOTAL_ASSERTIONS=0
FAILED_ASSERTIONS=0

TMP_BASE="/tmp/task-workflow-tests-$$"
mkdir -p "$TMP_BASE/stub"
trap 'rm -rf "$TMP_BASE"' EXIT

# ─── Helpers (same contract as scripts/create-mr/tests/test_all.sh) ──────────

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
  if [ "$expected" = "$actual" ]; then
    PASS=$((PASS + 1)); echo "  PASS: $desc"
  else
    FAIL=$((FAIL + 1)); FAILED_ASSERTIONS=$((FAILED_ASSERTIONS + 1))
    echo "  FAIL: $desc"
    echo "    expected: '$expected'"
    echo "    actual:   '$actual'"
  fi
}

assert_contains() {
  # grep -qF -- : needles starting with "-" are values, not options (PR #38 fix)
  local desc="$1" needle="$2" haystack="$3"
  TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
  if echo "$haystack" | grep -qF -- "$needle"; then
    PASS=$((PASS + 1)); echo "  PASS: $desc"
  else
    FAIL=$((FAIL + 1)); FAILED_ASSERTIONS=$((FAILED_ASSERTIONS + 1))
    echo "  FAIL: $desc — needle not found: '$needle'"
  fi
}

assert_not_contains() {
  local desc="$1" needle="$2" haystack="$3"
  TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
  if echo "$haystack" | grep -qF -- "$needle"; then
    FAIL=$((FAIL + 1)); FAILED_ASSERTIONS=$((FAILED_ASSERTIONS + 1))
    echo "  FAIL: $desc — needle found but must be absent: '$needle'"
  else
    PASS=$((PASS + 1)); echo "  PASS: $desc"
  fi
}

# ─── curl stub: no real network, driven by env vars ──────────────────────────
# CURL_STUB_GET:  with-mr | clean | http500 | network-error
# CURL_STUB_POST: ok | http500
# The stub records argv (secrets-in-argv assertion) and the full stdin config
# (body/URL assertions) into files under the per-test TMP dir.

mkdir -p "$TMP_BASE/stub"
cat > "$TMP_BASE/stub/curl" <<'STUB'
#!/usr/bin/env bash
set -uo pipefail
echo "ARGV: $*" >> "${CURL_STUB_LOG:?}"
out_file=""; fmt=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out_file="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
  esac
  shift
done
config="$(cat)"
printf '%s\n' "$config" >> "${CURL_STUB_CONFIG_LOG:?}"
# Route fidelity (post-mortem F-01): GET /actions/comments is UNROUTED (404
# "Cannot GET" live probe) while POST /actions/comments IS the real comment
# creation route — the 404 simulation applies to GET configs only.
is_post="$(printf '%s' "$config" | grep -c 'request = "POST"' || true)"
if [[ "$is_post" -eq 0 ]] && printf '%s' "$config" | grep -q 'actions/comments'; then
  printf '{"error":"Cannot GET /1/cards/xxx/actions/comments"}' > "$out_file"
  printf '404'
  exit 0
fi
# Resolve data-urlencode text@file references so tests can assert on the body
body_ref="$(printf '%s\n' "$config" | sed -n 's/^data-urlencode = "text@\(.*\)"/\1/p')"
if [[ -n "$body_ref" && -f "$body_ref" ]]; then
  printf 'BODY: ' >> "${CURL_STUB_CONFIG_LOG:?}"
  cat "$body_ref" >> "${CURL_STUB_CONFIG_LOG:?}"
  printf '\n' >> "${CURL_STUB_CONFIG_LOG:?}"
fi
if printf '%s' "$config" | grep -q 'request = "POST"'; then
  case "${CURL_STUB_POST:-ok}" in
    # Realistic action payload: memberCreator.id (24-hex) comes AFTER the
    # action id — the commentId extraction must survive it (review F-03).
    ok)      printf '{"id":"68f0a1b2c3d4e5f6a7b8c9d0","data":{"text":"x"},"memberCreator":{"id":"99ff88ee77dd66cc55bb44aa"}}' > "$out_file"; printf '200' ;;
    http500) printf '{"error":"server exploded"}' > "$out_file"; printf '500' ;;
  esac
  exit 0
fi
case "${CURL_STUB_GET:-clean}" in
  with-mr)       printf '[{"id":"111122223333444455556666","data":{"text":"🔗 Merge request liée : https://gitlab.infomaniak.ch/g/p/-/merge_requests/602"}}]' > "$out_file"; printf '200' ;;
  # longer-mr: MR 6030 already commented — a MR 603 lookup must NOT see "already"
  longer-mr)     printf '[{"id":"111122223333444455556666","data":{"text":"🔗 Merge request liée : https://gitlab.infomaniak.ch/g/p/-/merge_requests/6030"}}]' > "$out_file"; printf '200' ;;
  clean)         printf '[{"id":"111122223333444455556666","data":{"text":"ancien commentaire sans MR"}}]' > "$out_file"; printf '200' ;;
  http500)       printf '{"error":"boom"}' > "$out_file"; printf '500' ;;
  network-error) exit 7 ;;
esac
STUB
chmod +x "$TMP_BASE/stub/curl"

# Run the script in an isolated env: stubbed PATH, no real secrets, tmp .env.
run_script() {
  local tmpdir="$1"; shift
  env -i \
    PATH="$TMP_BASE/stub:/usr/bin:/bin" \
    HOME="$TMP_BASE/home" \
    TRELLO_ENV_FILE="$tmpdir/env" \
    TRELLO_API_KEY="test-key-abc" \
    TRELLO_TOKEN="test-token-xyz" \
    CURL_STUB_LOG="$tmpdir/curl-argv.log" \
    CURL_STUB_CONFIG_LOG="$tmpdir/curl-config.log" \
    CURL_STUB_GET="${CURL_STUB_GET:-clean}" \
    CURL_STUB_POST="${CURL_STUB_POST:-ok}" \
    bash "$SCRIPT" "$@" 2>&1
}

new_case() {
  CASE_N=$((CASE_N + 1))
  CASE_DIR="$TMP_BASE/case-$CASE_N-$RANDOM"
  mkdir -p "$CASE_DIR"
  : > "$CASE_DIR/curl-argv.log"
  : > "$CASE_DIR/curl-config.log"
}
CASE_N=0

JSON_OUTCOME() { printf '%s' "$1" | sed -n 's/.*"outcome":"\([a-z-]*\)".*/\1/p'; }

# ─── 1. Usage / argument validation ──────────────────────────────────────────
echo "── argument validation ──"
set +e
out="$(bash "$SCRIPT" 2>&1)"; code=$?
set -e
assert_eq "no args → usage error exit 2" "2" "$code"
assert_contains "no args prints usage" "usage: trello_comment.sh" "$out"

set +e
out="$(bash "$SCRIPT" --card-url "not-a-trello-url" --mr-url "https://x/mr/1" 2>&1)"; code=$?
set -e
assert_eq "invalid card url → exit 2" "2" "$code"

set +e
out="$(bash "$SCRIPT" --card-url "https://trello.com/c/abc12345" --mr-url "relative/url" 2>&1)"; code=$?
set -e
assert_eq "relative mr-url → exit 2" "2" "$code"

set +e
out="$(bash "$SCRIPT" --card-url "https://trello.com/c/abc1234" --mr-url "https://x/mr/1" 2>&1)"; code=$?
set -e
assert_eq "shortLink with 7 chars → exit 2" "2" "$code"

# ─── 2. no-token → exit 3 (browser-debug fallback signal) ────────────────────
echo "── no-token fallback signal ──"
new_case
set +e
out="$(env -i PATH="$TMP_BASE/stub:/usr/bin:/bin" HOME="$TMP_BASE/home" \
  TRELLO_ENV_FILE="$CASE_DIR/env" \
  CURL_STUB_LOG="$CASE_DIR/curl-argv.log" CURL_STUB_CONFIG_LOG="$CASE_DIR/curl-config.log" \
  bash "$SCRIPT" --card-url "https://trello.com/c/abc12345" --mr-url "https://gitlab.example/mr/1" 2>&1)"; code=$?
set -e
assert_eq "no secrets anywhere → exit 3" "3" "$code"
assert_eq "outcome no-token" "no-token" "$(JSON_OUTCOME "$out")"
assert_contains "no-token reason documents the one-shot setup" "trello.com/appkey" "$out"
assert_eq "no-token makes no network call" "" "$(cat "$CASE_DIR/curl-argv.log")"

# .env file resolution (no env vars, values only in the env file)
new_case
printf 'TRELLO_API_KEY="file-key-123"\nTRELLO_TOKEN=file-token-456\n' > "$CASE_DIR/env"
set +e
out="$(env -i PATH="$TMP_BASE/stub:/usr/bin:/bin" HOME="$TMP_BASE/home" \
  TRELLO_ENV_FILE="$CASE_DIR/env" \
  CURL_STUB_LOG="$CASE_DIR/curl-argv.log" CURL_STUB_CONFIG_LOG="$CASE_DIR/curl-config.log" \
  CURL_STUB_GET=clean CURL_STUB_POST=ok \
  bash "$SCRIPT" --card-url "https://trello.com/c/abc12345" --mr-url "https://gitlab.example/mr/2" 2>&1)"; code=$?
set -e
assert_eq "secrets from .env file → posted (exit 0)" "0" "$code"
assert_eq "outcome posted" "posted" "$(JSON_OUTCOME "$out")"

# ─── 3. dry-run: body printed, zero network ──────────────────────────────────
echo "── dry-run ──"
new_case
set +e
out="$(run_script "$CASE_DIR" --card-url "https://trello.com/c/abc12345/projet-xyz" \
  --mr-url "https://gitlab.infomaniak.ch/g/p/-/merge_requests/602" \
  --mr-title "feat: select multi-extension" --branch "feat/trello-w2v1zNEG" --dry-run)"; code=$?
set -e
assert_eq "dry-run → exit 0" "0" "$code"
assert_eq "outcome dry-run" "dry-run" "$(JSON_OUTCOME "$out")"
assert_contains "dry-run shows the MR url" "https://gitlab.infomaniak.ch/g/p/-/merge_requests/602" "$out"
assert_contains "dry-run shows the title" "feat: select multi-extension" "$out"
assert_contains "dry-run shows the review-humanity footer" "jamais de merge automatique" "$out"
assert_eq "dry-run makes no network call" "" "$(cat "$CASE_DIR/curl-argv.log")"

# ─── 4. Idempotence: GET-before-POST ─────────────────────────────────────────
echo "── idempotence ──"
new_case
set +e
out="$(CURL_STUB_GET=with-mr run_script "$CASE_DIR" \
  --card-url "https://trello.com/c/abc12345" \
  --mr-url "https://gitlab.infomaniak.ch/g/p/-/merge_requests/602")"; code=$?
set -e
assert_eq "MR already in comments → already (exit 0)" "0" "$code"
assert_eq "outcome already" "already" "$(JSON_OUTCOME "$out")"
assert_eq "already = exactly one call (GET only)" "1" "$(grep -c 'ARGV' "$CASE_DIR/curl-argv.log")"

new_case
set +e
out="$(CURL_STUB_GET=clean CURL_STUB_POST=ok run_script "$CASE_DIR" \
  --card-url "https://trello.com/c/abc12345" \
  --mr-url "https://gitlab.infomaniak.ch/g/p/-/merge_requests/603" \
  --branch "feat/trello-w2v1zNEG")"; code=$?
set -e
assert_eq "clean card → posted (exit 0)" "0" "$code"
assert_eq "outcome posted" "posted" "$(JSON_OUTCOME "$out")"
assert_contains "posted carries the comment id" '"commentId":"68f0a1b2c3d4e5f6a7b8c9d0"' "$out"
assert_not_contains "commentId is the ACTION id, not memberCreator.id" "99ff88ee77dd66cc55bb44aa" "$out"
assert_eq "clean card = two calls (GET then POST)" "2" "$(grep -c 'ARGV' "$CASE_DIR/curl-argv.log")"
config_log="$(cat "$CASE_DIR/curl-config.log")"
assert_contains "POST body carries the MR url" "merge_requests/603" "$config_log"
assert_contains "POST body carries the branch" "feat/trello-w2v1zNEG" "$config_log"
assert_contains "POST targets the right card (shortLink, /c/ prefix stripped)" "cards/abc12345/actions/comments" "$config_log"
# Route fidelity (review F-01): the dedupe GET must hit the real route
assert_contains "GET uses the real Trello route (actions?filter=commentCard)" "actions?key=" "$config_log"
assert_contains "GET sets filter=commentCard" "filter=commentCard" "$config_log"
assert_contains "GET pins the dedupe window (limit=1000)" "limit=1000" "$config_log"
get_lines="$(grep 'url = ' "$CASE_DIR/curl-config.log" | head -1)"
assert_not_contains "GET never calls the unrouted /actions/comments" "actions/comments" "$get_lines"

# Boundary match (review F-02): MR 6030 already commented must not satisfy MR 603
new_case
set +e
out="$(CURL_STUB_GET=longer-mr CURL_STUB_POST=ok run_script "$CASE_DIR" \
  --card-url "https://trello.com/c/abc12345" \
  --mr-url "https://gitlab.infomaniak.ch/g/p/-/merge_requests/603")"; code=$?
set -e
assert_eq "longer MR number is not a false already → posted (exit 0)" "0" "$code"
assert_eq "outcome posted (not already)" "posted" "$(JSON_OUTCOME "$out")"

# ─── 5. Failures are honest ──────────────────────────────────────────────────
echo "── failure paths ──"
new_case
set +e
out="$(CURL_STUB_GET=http500 run_script "$CASE_DIR" \
  --card-url "https://trello.com/c/abc12345" --mr-url "https://gitlab.example/mr/9")"; code=$?
set -e
assert_eq "GET HTTP 500 → failed (exit 1)" "1" "$code"
assert_eq "outcome failed" "failed" "$(JSON_OUTCOME "$out")"
assert_contains "failure reason carries the HTTP code" "HTTP 500" "$out"

new_case
set +e
out="$(CURL_STUB_GET=network-error run_script "$CASE_DIR" \
  --card-url "https://trello.com/c/abc12345" --mr-url "https://gitlab.example/mr/9")"; code=$?
set -e
assert_eq "network error → failed (exit 1)" "1" "$code"

new_case
set +e
out="$(CURL_STUB_GET=clean CURL_STUB_POST=http500 run_script "$CASE_DIR" \
  --card-url "https://trello.com/c/abc12345" --mr-url "https://gitlab.example/mr/9")"; code=$?
set -e
assert_eq "POST HTTP 500 → failed (exit 1)" "1" "$code"
assert_contains "POST failure reason carries the HTTP code" "POST comment returned HTTP 500" "$out"

# ─── 6. Secrets never appear in argv ─────────────────────────────────────────
echo "── secrets hygiene ──"
argv_log="$(cat "$CASE_DIR/curl-argv.log")"
assert_not_contains "API key never in argv" "test-key-abc" "$argv_log"
assert_not_contains "token never in argv" "test-token-xyz" "$argv_log"
new_case
printf 'TRELLO_API_KEY="file-key-123"\nTRELLO_TOKEN=file-token-456\n' > "$CASE_DIR/env"
: > "$CASE_DIR/curl-argv2.log"
: > "$CASE_DIR/curl-config2.log"
set +e
out_secret_probe="$(env -i PATH="$TMP_BASE/stub:/usr/bin:/bin" HOME="$TMP_BASE/home" \
  TRELLO_ENV_FILE="$CASE_DIR/env" \
  CURL_STUB_LOG="$CASE_DIR/curl-argv2.log" CURL_STUB_CONFIG_LOG="$CASE_DIR/curl-config2.log" \
  CURL_STUB_GET=clean CURL_STUB_POST=ok \
  bash "$SCRIPT" --card-url "https://trello.com/c/abc12345" --mr-url "https://gitlab.example/mr/10" 2>&1)"; probe_code=$?
set -e
assert_eq "secrets from .env file → real POST (probe exit 0)" "0" "$probe_code"
argv2="$(cat "$CASE_DIR/curl-argv2.log")"
assert_not_contains "file-sourced key never in argv" "file-key-123" "$argv2"
assert_not_contains "file-sourced token never in argv" "file-token-456" "$argv2"
# Secrets DO travel in the curl stdin config (body/query) — that is by design,
# argv is the exposure surface (`ps`) that must stay clean.
assert_contains "file-sourced key reaches curl via stdin config" "file-key-123" "$(cat "$CASE_DIR/curl-config2.log")"

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Summary: $PASS/$TOTAL_ASSERTIONS assertions passed ($FAILED_ASSERTIONS failed) ==="
[ "$FAILED_ASSERTIONS" -eq 0 ]
