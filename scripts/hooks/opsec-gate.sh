#!/usr/bin/env bash
# opsec-gate.sh - OPSEC metadata gate: detects internal infrastructure
# identifiers (hosts, private package names, internal project paths, internal
# naming conventions) that gitleaks cannot see, because gitleaks only matches
# credentials.
#
# Background: the 2026-11-06 leak wave reached the public repository through
# documentation and a PR body, not through secrets (see
# docs/SECURITY-ACCEPTANCE.md). This gate covers the metadata channel.
#
# Usage:
#   opsec-gate.sh --staged            scan staged additions (pre-commit)
#   opsec-gate.sh --message FILE      scan a commit message (commit-msg)
#   opsec-gate.sh --files FILE...     scan full file contents (CI tree scan)
#   opsec-gate.sh --stdin             scan free text from stdin (PR body)
#
# Exit codes: 0 clean, 1 identifiers found. No external tools required
# (plain bash + grep), so there is no degraded mode: a match blocks.
#
# Patterns are ERE evaluated with `grep -E` (BSD-compatible: use
# [[:space:]] instead of \s, no BRE escapes like \+ or \{n\}).
set -euo pipefail

# Company/internal-identifier patterns live OUTSIDE this repo, in the private
# overlay (aurora-personal). This public gate ships the mechanism only: set
# AURORA_OPSEC_PATTERNS to a file with one ERE pattern per line (# = comment)
# to activate. Default: ~/dev/aurora-personal/config/opsec-patterns.txt
PATTERNS=()
COMPANY_PATTERNS_FILE="${AURORA_OPSEC_PATTERNS:-$HOME/dev/aurora-personal/config/opsec-patterns.txt}"
if [[ -f "$COMPANY_PATTERNS_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    PATTERNS+=("$line")
  done < "$COMPANY_PATTERNS_FILE"
fi

# Basenames never scanned. This gate's own sources contain the patterns by
# definition; SECURITY-ACCEPTANCE.md quotes historical identifiers in
# recorded decisions (same rationale as skipping .gitleaks.toml in the secret
# scanner, which remains the credential authority).
SKIP_FILES=(
  opsec-gate.sh
  test-opsec-gate.mjs
  opsec-scan.yml
  SECURITY-ACCEPTANCE.md
  test-pre-commit-patterns.sh
  opsec-patterns.txt
  secret-patterns.txt
)

if (( ${#PATTERNS[@]} == 0 )); then
  echo "OPSEC gate: no patterns file found (${COMPANY_PATTERNS_FILE}) — gate inactive"
  echo "  set AURORA_OPSEC_PATTERNS to a patterns file to activate"
  exit 0
fi

HITS=0

skip_file() {
  local base file
  base="$(basename "$1")"
  for file in "${SKIP_FILES[@]}"; do
    [[ "$base" == "$file" ]] && return 0
  done
  return 1
}

report_match() {
  printf 'OPSEC: %s\n' "$1"
  printf '%s\n' "$2" | head -3 | sed 's/^/  /'
  HITS=$((HITS + 1))
}

# Scan the full content of one file (line numbers included in the report).
scan_file() {
  local file="$1" p out
  for p in "${PATTERNS[@]}"; do
    out="$(grep -nE "$p" "$file" 2>/dev/null || true)"
    if [[ -n "$out" ]]; then
      report_match "$file matches pattern: $p" "$out"
    fi
  done
}

mode_staged() {
  local file p out
  while IFS= read -r -d '' file; do
    skip_file "$file" && continue
    for p in "${PATTERNS[@]}"; do
      out="$(git diff --cached -U0 -- "$file" 2>/dev/null | grep -E '^\+' | grep -Ev '^\+\+\+' | grep -Ee "$p" || true)"
      if [[ -n "$out" ]]; then
        report_match "staged change in $file matches pattern: $p" "$out"
      fi
    done
  done < <(git diff --cached --name-only --diff-filter=ACMR -z 2>/dev/null || true)
}

mode_message() {
  scan_file "$1"
}

mode_files() {
  local file
  for file in "$@"; do
    skip_file "$file" && continue
    [[ -f "$file" ]] || continue
    scan_file "$file"
  done
}

mode_stdin() {
  local stdin_data p out
  stdin_data="$(cat || true)"
  for p in "${PATTERNS[@]}"; do
    out="$(printf '%s\n' "$stdin_data" | grep -E "$p" || true)"
    if [[ -n "$out" ]]; then
      report_match "stdin matches pattern: $p" "$out"
    fi
  done
}

if (( $# < 1 )); then
  echo "usage: opsec-gate.sh --staged | --message FILE | --files FILE... | --stdin" >&2
  exit 2
fi

mode="$1"; shift
case "$mode" in
  --staged)
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
    mode_staged
    ;;
  --message)
    [[ -n "${1:-}" ]] || { echo "usage: opsec-gate.sh --message FILE" >&2; exit 2; }
    mode_message "$1"
    ;;
  --files)
    mode_files "$@"
    ;;
  --stdin)
    mode_stdin
    ;;
  *)
    echo "unknown mode: $mode" >&2
    exit 2
    ;;
esac

if (( HITS > 0 )); then
  echo ""
  echo "OPSEC gate: $HITS internal-identifier match(es)."
  echo "Remove the identifier or move it to private config. Intentional"
  echo "matches (this gate's own sources, the overlay patterns/acceptance files) are"
  echo "skipped; anything else needs a documented decision in the private"
  echo "overlay's SECURITY-ACCEPTANCE.md before using --no-verify."
  exit 1
fi

exit 0
