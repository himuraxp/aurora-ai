#!/usr/bin/env bash
# detect_target_branch.sh — Detect the target branch for the MR.
#
# Usage: detect_target_branch.sh [--branch <name>]
#
# If --branch is provided, validates it exists and outputs it.
# Otherwise, detects the repository default branch via glab and outputs it.
#
# Output (stdout): the target branch name
# Errors go to stderr; exit 1 on failure.

set -euo pipefail

# Resolve script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure we are in a Git repository
if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "ERROR: Not in a Git repository." >&2
  exit 1
fi

TOPLEVEL="$(git rev-parse --show-toplevel)"
cd "$TOPLEVEL"

# Parse arguments
TARGET_BRANCH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --branch)
      TARGET_BRANCH="$2"
      shift 2
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# If a branch was specified, validate it exists
if [ -n "$TARGET_BRANCH" ]; then
  if git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH" 2>/dev/null; then
    echo "$TARGET_BRANCH"
    exit 0
  fi

  git fetch --all --prune --quiet 2>/dev/null || true

  if git show-ref --verify --quiet "refs/remotes/origin/$TARGET_BRANCH" 2>/dev/null; then
    echo "$TARGET_BRANCH"
    exit 0
  fi

  echo "ERROR: Target branch '$TARGET_BRANCH' not found." >&2
  echo "" >&2
  echo "Available branches:" >&2
  git branch -r 2>/dev/null | sed 's/origin\///' | sort -u | head -20 >&2
  exit 1
fi

# No branch specified: detect default branch via glab
if ! command -v glab &>/dev/null; then
  echo "ERROR: glab CLI not found. Install it or specify --branch." >&2
  exit 1
fi

DEFAULT_BRANCH=""
RAW_JSON=""
if ! RAW_JSON=$(glab repo view --output json 2>/dev/null); then
  echo "ERROR: glab repo view failed. Check authentication." >&2
  exit 1
fi

# Validate JSON before parsing
if ! echo "$RAW_JSON" | jq empty 2>/dev/null; then
  echo "ERROR: glab returned invalid JSON." >&2
  exit 1
fi

DEFAULT_BRANCH=$(echo "$RAW_JSON" | jq -r '.default_branch // empty' 2>/dev/null)

if [ -z "$DEFAULT_BRANCH" ]; then
  echo "ERROR: glab returned empty default_branch." >&2
  exit 1
fi

echo "$DEFAULT_BRANCH"
