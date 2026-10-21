#!/usr/bin/env bash
# create_mr.sh — Create the MR via glab.
#
# Usage: create_mr.sh \
#   --target-branch <name> \
#   --title "<title>" \
#   --body-file <path>       # path to file containing the MR description
#   [--dry-run]
#
# Creates the MR using glab mr create. The description is read from a file
# to avoid shell escaping issues with backticks, quotes, and special chars.
#
# In --dry-run mode, outputs what would be done but does not create the MR.

set -euo pipefail

TARGET_BRANCH=""
TITLE=""
BODY_FILE=""
DRY_RUN=false

while [ $# -gt 0 ]; do
  case "$1" in
    --target-branch)
      TARGET_BRANCH="$2"
      shift 2
      ;;
    --title)
      TITLE="$2"
      shift 2
      ;;
    --body-file)
      BODY_FILE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# Validate required arguments
if [ -z "$TARGET_BRANCH" ]; then
  echo "ERROR: --target-branch is required." >&2
  exit 1
fi

if [ -z "$TITLE" ]; then
  echo "ERROR: --title is required." >&2
  exit 1
fi

if [ -z "$BODY_FILE" ] || [ ! -f "$BODY_FILE" ]; then
  echo "ERROR: --body-file is required and must exist." >&2
  exit 1
fi

# Ensure we are in a Git repository
if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "ERROR: Not in a Git repository." >&2
  exit 1
fi

TOPLEVEL="$(git rev-parse --show-toplevel)"
cd "$TOPLEVEL"

if [ "$DRY_RUN" = true ]; then
  # Dry-run never invokes glab: the check below must stay AFTER this branch
  # so --dry-run works on machines without glab (CI test suite requirement).
  echo "=== DRY RUN ==="
  echo "Target branch: $TARGET_BRANCH"
  echo "Title: $TITLE"
  echo "Body file: $BODY_FILE"
  echo ""
  echo "--- Body preview (first 500 chars) ---"
  head -c 500 "$BODY_FILE"
  echo ""
  echo "--- End preview ---"
  echo ""
  echo "Would run: glab mr create -b \"$TARGET_BRANCH\" -t \"$TITLE\" -d \"\$(cat $BODY_FILE)\" -y"
  exit 0
fi

# Ensure glab is available (real run only — dry-run above exits before this)
if ! command -v glab &>/dev/null; then
  echo "ERROR: glab CLI not found." >&2
  exit 1
fi

# Create the MR
if ! glab mr create \
  -b "$TARGET_BRANCH" \
  -t "$TITLE" \
  -d "$(cat "$BODY_FILE")" \
  -y; then
  echo "ERROR: glab mr create failed." >&2
  exit 1
fi

echo "OK: MR created"
