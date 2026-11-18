#!/usr/bin/env bash
set -euo pipefail

# permissions-matrix.sh — Generate a markdown table of all agent permissions.
#
# Parses every agents/*.md frontmatter and outputs a table:
#   | Agent | Mode | Model | Edit | Bash default | Webfetch | Skill |
#
# Usage: ./scripts/permissions-matrix.sh [--output FILE]
#   --output FILE  Write to FILE instead of stdout

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      shift
      OUTPUT_FILE="${1:-}"
      [[ -z "$OUTPUT_FILE" ]] && { echo "Missing output file" >&2; exit 1; }
      ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--output FILE]"
      exit 0
      ;;
    *) ;;
  esac
  shift
done

# Extract a top-level frontmatter field (field: value)
get_field() {
  local file="$1"
  local field="$2"
  awk "/^---$/{n++; next} n==1 && /^${field}:[[:space:]]/ {sub(/^${field}:[[:space:]]*/, \"\"); print; exit}" "$file"
}

# Extract a field nested under "permission:" block
get_perm_field() {
  local file="$1"
  local field="$2"
  awk "/^---$/{n++; next} n==1 && /^permission:/{found=1; next} found && /^  ${field}:[[:space:]]/ {sub(/^  ${field}:[[:space:]]*/, \"\"); print; exit} found && /^[^ ]/{exit}" "$file"
}

# Extract bash permission: either a scalar (bash: deny) or the "*" entry in a block
get_bash_default() {
  local file="$1"
  # First check if bash is a scalar (e.g. "bash: deny" or "bash: false")
  scalar=$(awk '/^---$/{n++; next} n==1 && /^  bash:[[:space:]]*[a-z]/{sub(/^  bash:[[:space:]]*/, ""); print; exit}' "$file")
  if [[ -n "$scalar" ]]; then
    echo "$scalar"
    return
  fi
  # Otherwise look for the "*": entry in the bash block
  awk '/^---$/{n++; next} n==1 && /^  bash:/{found=1; next} found && /^    "\*":/ {gsub(/[" ]/, "", $1); gsub(/[" ]/, "", $2); print $2; exit} found && /^  [a-z]/ && !/^  bash:/{exit}' "$file"
}

generate() {
  echo "| Agent | Mode | Model | Edit | Bash | Webfetch | Skill |"
  echo "|-------|------|-------|------|------|----------|-------|"

  for agent_file in "$ROOT_DIR"/agents/*.md; do
    [[ -f "$agent_file" ]] || continue
    name="$(basename "$agent_file" .md)"
    [[ "$name" == "README" ]] && continue

    mode=$(get_field "$agent_file" "mode")
    model=$(get_field "$agent_file" "model")
    edit=$(get_perm_field "$agent_file" "edit")
    webfetch=$(get_perm_field "$agent_file" "webfetch")
    skill=$(get_perm_field "$agent_file" "skill")
    bash_perm=$(get_bash_default "$agent_file")

    # Clean up
    [[ -z "$mode" ]] && mode="-"
    [[ -z "$model" ]] && model="-"
    [[ -z "$edit" ]] && edit="-"
    [[ -z "$webfetch" ]] && webfetch="-"
    [[ -z "$skill" ]] && skill="-"
    [[ -z "$bash_perm" ]] && bash_perm="-"

    # Shorten model name
    if [[ "$model" != "-" ]]; then
      model="${model##*/}"
    fi

    echo "| $name | $mode | $model | $edit | $bash_perm | $webfetch | $skill |"
  done
}

if [[ -n "$OUTPUT_FILE" ]]; then
  generate > "$OUTPUT_FILE"
  echo "Permissions matrix written to $OUTPUT_FILE"
else
  generate
fi
