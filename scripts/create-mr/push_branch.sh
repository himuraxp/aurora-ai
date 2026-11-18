#!/usr/bin/env bash
# push_branch.sh — Push the current branch to remote if it has unpushed commits.
#
# Usage: push_branch.sh
#
# Pushes the current branch to origin if there are unpushed commits.
# If already up to date, does nothing.
#
# This script DOES push (it is the explicit push action, not a commit).
# It does NOT commit, merge, rebase, or force-push.

set -euo pipefail

# Ensure we are in a Git repository
if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "ERROR: Not in a Git repository." >&2
  exit 1
fi

TOPLEVEL="$(git rev-parse --show-toplevel)"
cd "$TOPLEVEL"

CURRENT_BRANCH="$(git branch --show-current)"

if [ -z "$CURRENT_BRANCH" ]; then
  echo "ERROR: Detached HEAD state." >&2
  exit 1
fi

# Check for unpushed commits
UNPUSHED_COUNT=0
if git rev-parse --verify "origin/$CURRENT_BRANCH" &>/dev/null; then
  # Branch exists on remote: count commits ahead
  UNPUSHED_COUNT=$(git rev-list --count "HEAD" "^origin/$CURRENT_BRANCH" 2>/dev/null || echo "0")
else
  # Branch doesn't exist on remote yet: count commits since the default branch
  # Find the base branch (try main, then master, then develop)
  BASE_BRANCH=""
  for candidate in main master develop; do
    if git rev-parse --verify "origin/$candidate" &>/dev/null 2>&1 || git rev-parse --verify "$candidate" &>/dev/null 2>&1; then
      BASE_BRANCH="$candidate"
      break
    fi
  done

  if [ -n "$BASE_BRANCH" ]; then
    UNPUSHED_COUNT=$(git rev-list --count "HEAD" "^$BASE_BRANCH" 2>/dev/null || echo "0")
  else
    # No base branch found: count all commits (rare edge case)
    UNPUSHED_COUNT=$(git rev-list --count HEAD 2>/dev/null || echo "0")
  fi
fi

if [ "$UNPUSHED_COUNT" -eq 0 ]; then
  echo "OK: branch '$CURRENT_BRANCH' is up to date"
  exit 0
fi

echo "Pushing $UNPUSHED_COUNT commit(s) to origin/$CURRENT_BRANCH..."
if ! git push origin "$CURRENT_BRANCH"; then
  echo "ERROR: git push failed." >&2
  exit 1
fi

echo "OK: pushed $UNPUSHED_COUNT commit(s)"
