#!/usr/bin/env bash
# check_workspace.sh — Verify workspace is clean and on a feature branch.
#
# Usage: check_workspace.sh
#
# Exits 0 if workspace is clean and not on main/master.
# Exits 1 with error message on stderr otherwise.
#
# This script does NOT commit, push, or modify any files.

set -euo pipefail

# Resolve script directory (support BASH_SOURCE)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure we are in a Git repository
if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "ERROR: Not in a Git repository." >&2
  exit 1
fi

TOPLEVEL="$(git rev-parse --show-toplevel)"
cd "$TOPLEVEL"

# Check for uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: Workspace is dirty. Commit or stash changes first." >&2
  echo "" >&2
  git status --short >&2
  exit 1
fi

# Check current branch
CURRENT_BRANCH="$(git branch --show-current)"

if [ -z "$CURRENT_BRANCH" ]; then
  echo "ERROR: Detached HEAD state. Checkout a branch first." >&2
  exit 1
fi

# Refuse to create MR from main/master
case "$CURRENT_BRANCH" in
  main|master|develop)
    echo "ERROR: Cannot create MR from '$CURRENT_BRANCH'. Create a feature branch first." >&2
    echo "  git checkout -b feat/your-feature" >&2
    exit 1
    ;;
esac

echo "OK: workspace clean, branch '$CURRENT_BRANCH'"
