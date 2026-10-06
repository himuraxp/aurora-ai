#!/usr/bin/env bash
# memory-access-check.sh — Conformity check of the memory surface (ADR-021).
#
# Model since ADR-021 ("closed surface"): aurora-memory is NEVER a global OpenCode MCP.
# Aurora accesses memory only through the orchestrator-scoped adapter (B3, pending);
# capability agents get memory context injected by aurora and return memory_observations.
#
# Verified invariants:
#   1. mcp."aurora-memory".enabled == false in repo and live (surface closed).
#   2. No aurora-memory_* permission key in the config (global or per-agent) — old
#      per-tool denies are removed (they were cosmetic, ADR-021).
#   3. agent.plan is minimal (no tools/permission field that would block MCP spawn).
#   4. Plugin is pinned (oh-my-opencode-slim@<version>) — cache version skew.
#   5. agents/*.md: no aurora-memory_* frontmatter permission except aurora.md (15 allows,
#      documentation of intent); READ agents carry the "broker via aurora" section.
#   6. Live matches repo (mcp entry, aurora.md, agents frontmatters).
#
# Usage: scripts/memory-access-check.sh [--no-live]
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$ROOT/config/opencode.json"
AGENTS_DIR="$ROOT/agents"
CHECK_LIVE=true
if [[ "${1:-}" == "--no-live" ]]; then CHECK_LIVE=false; fi

FAIL=0
fail() { echo "  ✗ $1"; FAIL=1; }
pass() { echo "  ✓ $1"; }

command -v jq >/dev/null || { echo "jq required"; exit 2; }
[[ -f "$CFG" ]] || { echo "config not found: $CFG"; exit 2; }

check_config() {
  local cfg="$1" label="$2"
  echo "== $label =="

  # 1. Surface closed
  EN=$(jq -r '.mcp["aurora-memory"].enabled == false' "$cfg")
  if [[ "$EN" == "true" ]]; then pass "mcp.aurora-memory.enabled = false"
  else fail "mcp.aurora-memory.enabled must be exactly false while B3 is not shipped (got: $(jq -r '.mcp["aurora-memory"].enabled | type' "$cfg"))"; fi

  # 2. No memory permission keys anywhere in config
  G=$(jq -r '[.permission // {} | keys[] | select(startswith("aurora-memory_"))] | length' "$cfg")
  A=$(jq -r '[.agent // {} | to_entries[] | .value.permission // {} | keys[] | select(startswith("aurora-memory_"))] | length' "$cfg")
  if [[ "$G" == "0" && "$A" == "0" ]]; then pass "0 aurora-memory_* permission key (global + agents)"
  else fail "aurora-memory_* permission keys present (global=$G agents=$A) — remove, they are cosmetic (ADR-021)"; fi

  # 3. agent.plan minimal (blocks local MCP spawn otherwise)
  PT=$(jq -r '.agent.plan | has("tools")' "$cfg" 2>/dev/null || echo "noagent")
  PP=$(jq -r '.agent.plan | has("permission")' "$cfg" 2>/dev/null || echo "noagent")
  if [[ "$PT" == "noagent" ]]; then fail "agent.plan missing"
  elif [[ "$PT" == "false" && "$PP" == "false" ]]; then pass "agent.plan minimal (no tools/permission)"
  else fail "agent.plan has tools/permission fields — must stay minimal (blocks MCP spawn, ADR-021)"; fi

  # 4. Plugin pinned
  PL=$(jq -r '[.plugin // [] | .[] | select(startswith("oh-my-opencode-slim"))] | .[0] // ""' "$cfg")
  if [[ "$PL" == oh-my-opencode-slim@* ]]; then pass "plugin pinned: $PL"
  else fail "plugin not pinned (got '$PL') — non-deterministic cache version skew"; fi
}

check_config "$CFG" "1. Repo config (surface closed)"

# 5. Agent frontmatters
echo "== 2. Agent frontmatters =="
BAD=$(grep -l "aurora-memory_" "$AGENTS_DIR"/*.md 2>/dev/null | grep -v "/aurora\.md$" || true)
if [[ -z "$BAD" ]]; then pass "no aurora-memory_* frontmatter outside aurora.md"; else fail "memory keys in: $(echo "$BAD" | xargs -n1 basename | tr '\n' ' ')"; fi
AA=$(grep -c "aurora-memory_" "$AGENTS_DIR/aurora.md" || true)
if [[ "$AA" == "15" ]]; then pass "aurora.md keeps 15 intent allows"; else fail "aurora.md: $AA/15 memory allows"; fi
BROKER=$(grep -l "Mémoire personnelle (broker via aurora)" "$AGENTS_DIR"/{architect,reviewer,designer,mobile}.md 2>/dev/null | wc -l | tr -d ' ')
if [[ "$BROKER" == "4" ]]; then pass "4 READ agents carry the broker contract"; else fail "broker contract missing in $BROKER/4 READ agents"; fi

if [[ "$CHECK_LIVE" == true ]]; then
  echo "== 3. Live consistency (~/.config/opencode) =="
  LIVE_CFG="${HOME}/.config/opencode/opencode.json"
  LIVE_AGENTS="${HOME}/.config/opencode/agents"
  if [[ ! -f "$LIVE_CFG" ]]; then
    fail "live config missing: $LIVE_CFG"
  else
    check_config "$LIVE_CFG" "3a. Live config (surface closed)"
    for f in "$AGENTS_DIR"/*.md; do
      b=$(basename "$f")
      [[ -f "$LIVE_AGENTS/$b" ]] || { fail "live agents/$b missing"; continue; }
      diff -q "$f" "$LIVE_AGENTS/$b" >/dev/null 2>&1 || fail "live agents/$b differs — redeploy"
    done
    [[ $FAIL -eq 0 ]] && pass "live agent files identical to repo"
  fi
fi

echo ""
if [[ $FAIL -eq 0 ]]; then echo "MEMORY SURFACE CHECK: OK (ADR-021 closed surface)"; else echo "MEMORY SURFACE CHECK: FAILED"; exit 1; fi
