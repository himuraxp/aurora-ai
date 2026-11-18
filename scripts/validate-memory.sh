#!/usr/bin/env bash
set -euo pipefail

# validate-memory.sh — Verify that docs/ai/ is well-formed.
#
# Checks:
#   1. Required files exist (STATUS, PLAN, DECISIONS, CHANGELOG, BUFFER, INDEX, WARNINGS)
#   2. STATUS.md has the 4 required sections
#   3. PLAN.md has a status frontmatter
#   4. BUFFER.md has a snapshot reprise
#   5. No .new files lingering
#
# Usage: ./scripts/validate-memory.sh [PROJECT_DIR]
#   PROJECT_DIR defaults to current directory

PROJECT_DIR="${1:-$(pwd)}"
AI_DIR="$PROJECT_DIR/docs/ai"

ERRORS=0
WARNINGS=0

ok()   { echo "  OK   $1"; }
warn() { echo "  WARN $1"; WARNINGS=$((WARNINGS + 1)); }
fail() { echo "  FAIL $1"; ERRORS=$((ERRORS + 1)); }

echo "=== Memory Validation ==="
echo "Target: $AI_DIR"
echo ""

if [[ ! -d "$AI_DIR" ]]; then
  echo "docs/ai/ not found — nothing to validate."
  exit 0
fi

# ─── 1. Required files ──────────────────────────────────────────────────────

echo "--- Required files ---"

required_files=(STATUS.md PLAN.md DECISIONS.md CHANGELOG.md BUFFER.md INDEX.md WARNINGS.md)
for f in "${required_files[@]}"; do
  if [[ -f "$AI_DIR/$f" ]]; then
    ok "$f"
  else
    fail "$f — missing"
  fi
done

# ─── 2. STATUS.md sections ──────────────────────────────────────────────────

echo ""
echo "--- STATUS.md sections ---"

if [[ -f "$AI_DIR/STATUS.md" ]]; then
  for section in "## En cours" "## Fait" "## Bloqué" "## Prochaine action"; do
    if grep -qF "$section" "$AI_DIR/STATUS.md" 2>/dev/null; then
      ok "$section"
    else
      fail "STATUS.md — missing section '$section'"
    fi
  done
fi

# ─── 3. PLAN.md frontmatter ────────────────────────────────────────────────

echo ""
echo "--- PLAN.md frontmatter ---"

if [[ -f "$AI_DIR/PLAN.md" ]]; then
  if head -1 "$AI_DIR/PLAN.md" | grep -q "^---$"; then
    if grep -q "^status:" "$AI_DIR/PLAN.md" 2>/dev/null; then
      status_val=$(grep "^status:" "$AI_DIR/PLAN.md" | head -1 | sed 's/^status:[[:space:]]*//')
      ok "status: $status_val"
      case "$status_val" in
        pending|in-progress|implemented|reviewed|blocked) ;;
        *) warn "PLAN.md — unexpected status value '$status_val'" ;;
      esac
    else
      warn "PLAN.md — no 'status' field in frontmatter"
    fi
  else
    warn "PLAN.md — no frontmatter (status field recommended)"
  fi
fi

# ─── 4. BUFFER.md snapshot ─────────────────────────────────────────────────

echo ""
echo "--- BUFFER.md snapshot ---"

if [[ -f "$AI_DIR/BUFFER.md" ]]; then
  if grep -qiE '^##.*snapshot|^##.*reprise' "$AI_DIR/BUFFER.md" 2>/dev/null; then
    ok "Snapshot reprise found"
  else
    warn "BUFFER.md — no snapshot reprise section"
  fi

  # Check size (warn if > 100 lines)
  lines=$(wc -l < "$AI_DIR/BUFFER.md")
  if [[ $lines -gt 100 ]]; then
    warn "BUFFER.md — $lines lines (consider archiving old snapshots)"
  else
    ok "BUFFER.md — $lines lines"
  fi
fi

# ─── 5. No .new files ───────────────────────────────────────────────────────

echo ""
echo "--- Lingering .new files ---"

new_count=$(find "$AI_DIR" -name "*.new" -type f 2>/dev/null | wc -l | tr -d ' ')
if [[ $new_count -eq 0 ]]; then
  ok "No .new files"
else
  warn "$new_count .new file(s) found — merge or remove them"
  find "$AI_DIR" -name "*.new" -type f 2>/dev/null | while read -r f; do
    echo "       $f"
  done
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "=== Summary ==="
if [[ $ERRORS -eq 0 && $WARNINGS -eq 0 ]]; then
  echo "Memory is well-formed."
elif [[ $ERRORS -eq 0 ]]; then
  echo "Memory is valid with $WARNINGS warning(s)."
else
  echo "$ERRORS error(s), $WARNINGS warning(s)."
fi

exit $((ERRORS > 0 ? 1 : 0))
