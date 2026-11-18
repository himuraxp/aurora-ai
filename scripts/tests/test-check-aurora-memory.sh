#!/usr/bin/env bash
set -euo pipefail

# test-check-aurora-memory.sh — classification harness for check-aurora-memory.mjs.
#
# Injects fake MCP (newline-delimited JSON) servers via AURORA_MEMORY_SERVER to
# pin every classification of the real checker WITHOUT docker, PostgreSQL or
# aurora-core — CI-runnable, node stdlib only, < 2 s.
#
# Pinned shapes (each maps to one real failure mode of the bridge server):
#   1. healthy           → PASS C1 + PASS C2 (JSON payload), rc 0
#   2. silent-error      → FAIL C2 "EMPTY message" (the observed 8-day shape), rc 1
#   3. crash-after-init  → FAIL C1 "exited code N" (close-based classification), rc 1
#   4. exit0-no-answer   → FAIL C1 "exited cleanly (code 0) without answering", rc 1
#   5. dsn-in-stderr     → FAIL C1 + credential redacted (***@, never user:pass), rc 1
#   6. bad-payload       → FAIL C2 "not JSON" (isError:false degraded shape), rc 1
#
# Usage: bash scripts/tests/test-check-aurora-memory.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECK="$ROOT_DIR/scripts/check-aurora-memory.mjs"

if ! command -v node >/dev/null 2>&1; then
  echo "SKIP node absent"
  exit 0
fi

PASS_COUNT=0
FAIL_COUNT=0

ok()   { echo "  OK   $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  FAIL $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A fake MCP server speaking newline-delimited JSON (same transport as the
# real aurora-memory bundle). $1 = filename, stdin = handler body.
write_fake() {
  cat > "$TMP/$1" <<EOF
const seen = new Set();
process.stdin.on("data", (d) => {
  for (const raw of d.toString().split("\n")) {
    if (!raw.trim()) continue;
    let msg;
    try { msg = JSON.parse(raw); } catch { continue; }
    fakeHandle(msg);
  }
});
$2
EOF
}

# run_check <fake-file> → sets OUT and RC
run_check() {
  OUT=$(AURORA_MEMORY_SERVER="$TMP/$1" AURORA_MEMORY_PG_CONTAINER=aurora-memory-check-nope \
    node "$CHECK" 2>&1) && RC=0 || RC=$?
}

assert_rc() {
  if [[ "$RC" == "$1" ]]; then ok "$2 (rc=$RC)"; else fail "$2 — expected rc $1, got $RC"; fi
}

assert_contains() {
  if printf '%s' "$OUT" | grep -qF -- "$1"; then ok "$2"; else fail "$2 — '$1' not found in: $(printf '%s' "$OUT" | head -c 300)"; fi
}

assert_not_contains() {
  if printf '%s' "$OUT" | grep -qF -- "$1"; then fail "$2 — '$1' must not appear"; else ok "$2"; fi
}

# ─── 1. healthy ──────────────────────────────────────────────────────────────
write_fake "healthy.mjs" 'function fakeHandle(msg) {
  if (msg.id === 1 && !seen.has(1)) { seen.add(1);
    process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:1,result:{protocolVersion:"2024-11-05",capabilities:{tools:{}},serverInfo:{name:"fake",version:"0"}}})+"\n"); }
  else if (msg.id === 2 && !seen.has(2)) { seen.add(2);
    process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:2,result:{content:[{type:"text",text:"[]"}]}})+"\n"); }
}'
run_check "healthy.mjs"
assert_rc 0 "healthy server accepted"
assert_contains "PASS C1" "healthy: C1 pass"
assert_contains "PASS C2" "healthy: C2 pass"

# ─── 2. silent-error (the observed 8-day degradation shape) ─────────────────
write_fake "silent-error.mjs" 'function fakeHandle(msg) {
  if (msg.id === 1 && !seen.has(1)) { seen.add(1);
    process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:1,result:{protocolVersion:"2024-11-05",capabilities:{tools:{}},serverInfo:{name:"fake",version:"0"}}})+"\n"); }
  else if (msg.id === 2 && !seen.has(2)) { seen.add(2);
    process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:2,result:{content:[{type:"text",text:""}],isError:true}})+"\n"); }
}'
run_check "silent-error.mjs"
assert_rc 1 "silent error detected"
assert_contains "FAIL C2 goal_list" "silent-error: C2 fails"
assert_contains "EMPTY message" "silent-error: empty-message shape named"

# ─── 3. crash after init (close-based classification, non-zero) ─────────────
write_fake "crash-after-init.mjs" 'function fakeHandle(msg) {
  if (msg.id === 1 && !seen.has(1)) { seen.add(1);
    process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:1,result:{protocolVersion:"2024-11-05",capabilities:{tools:{}},serverInfo:{name:"fake",version:"0"}}})+"\n");
    process.exit(3); }
}'
run_check "crash-after-init.mjs"
assert_rc 1 "crash after init detected"
assert_contains "exited code 3" "crash-after-init: exit code classified"

# ─── 4. exit 0 without answering tools/call ─────────────────────────────────
write_fake "exit0-no-answer.mjs" 'function fakeHandle(msg) {
  if (msg.id === 1 && !seen.has(1)) { seen.add(1);
    process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:1,result:{protocolVersion:"2024-11-05",capabilities:{tools:{}},serverInfo:{name:"fake",version:"0"}}})+"\n");
    process.exit(0); }
}'
run_check "exit0-no-answer.mjs"
assert_rc 1 "silent exit-0 detected"
assert_contains "exited cleanly (code 0) without answering" "exit0-no-answer: clean-exit classified"

# ─── 5. DSN in stderr must be redacted ──────────────────────────────────────
cat > "$TMP/dsn-crash.mjs" <<'EOF'
console.error("connect ECONNREFUSED for postgres://aurora:supersecret@localhost:5433/aurora");
process.exit(1);
EOF
run_check "dsn-crash.mjs"
assert_rc 1 "dsn crash detected"
assert_contains "***@" "dsn-crash: credentials redacted"
assert_not_contains "supersecret" "dsn-crash: no raw password in output"
assert_not_contains "aurora:supersecret" "dsn-crash: no raw DSN in output"

# ─── 6. isError:false with non-JSON payload (new degradation shape) ─────────
write_fake "bad-payload.mjs" 'function fakeHandle(msg) {
  if (msg.id === 1 && !seen.has(1)) { seen.add(1);
    process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:1,result:{protocolVersion:"2024-11-05",capabilities:{tools:{}},serverInfo:{name:"fake",version:"0"}}})+"\n"); }
  else if (msg.id === 2 && !seen.has(2)) { seen.add(2);
    process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:2,result:{content:[{type:"text",text:"internal error, not json"}]}})+"\n"); }
}'
run_check "bad-payload.mjs"
assert_rc 1 "non-JSON payload rejected"
assert_contains "FAIL C2 goal_list" "bad-payload: C2 fails"
assert_contains "not JSON" "bad-payload: payload-shape violation named"

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Summary ==="
if [[ $FAIL_COUNT -eq 0 ]]; then
  echo "check-aurora-memory classification harness: $PASS_COUNT assertion(s) passed."
else
  echo "check-aurora-memory classification harness: $FAIL_COUNT failure(s)."
fi
exit $((FAIL_COUNT > 0 ? 1 : 0))
