#!/usr/bin/env bash
# create_mr.sh — Create the MR via glab.
#
# Usage: create_mr.sh \
#   --target-branch <name> \
#   --title "<title>" \
#   --body-file <path>       # path to file containing the MR description
#   [--label "<name>"]       # optional label; existence is verified against
#                            # the project before creation — skipped (with a
#                            # WARN) if absent or if the API is unreachable
#   [--dry-run]
#
# Creates the MR using glab mr create. The description is read from a file
# to avoid shell escaping issues with backticks, quotes, and special chars.
#
# In --dry-run mode, outputs what would be done but does not create the MR
# (and never calls glab).

set -euo pipefail

TARGET_BRANCH=""
TITLE=""
BODY_FILE=""
LABEL=""
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
    --label)
      [ $# -ge 2 ] || { echo "ERROR: Missing value for --label" >&2; exit 1; }
      LABEL="$2"
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
  if [ -n "$LABEL" ]; then
    echo "Label: $LABEL (existence verified against the project before creation)"
  fi
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

# Optional label: verify it exists on the project before passing it to
# glab mr create (an unknown label would fail the whole creation).
# Python exit codes: 0 = found, 1 = label absent, 2 = API error body
# (e.g. {"message":"401 …"}) or unreachable API — the MR is created without
# the label in every non-zero case (WARN, never blocking).
LABEL_ARGS=()
LABEL_RESULT="none"
if [ -n "$LABEL" ]; then
  SEARCH_PREFIX="${LABEL%%::*}"
  SEARCH_PREFIX_ENC="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$SEARCH_PREFIX")"
  LABELS_FILE="$(mktemp)"
  LABEL_VERIFY=api-error
  if glab api "projects/:fullpath/labels?per_page=100&search=${SEARCH_PREFIX_ENC}" >"$LABELS_FILE" 2>/dev/null &&
    [ -s "$LABELS_FILE" ]; then
    if python3 -c '
import json
import sys

label, path = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as fh:
        labels = json.load(fh)
except Exception:
    sys.exit(2)
if isinstance(labels, dict):
    if "data" in labels:
        labels = labels["data"] or []
    else:
        sys.exit(2)
sys.exit(0 if any(isinstance(item, dict) and item.get("name") == label for item in labels) else 1)
' "$LABEL" "$LABELS_FILE"; then
      LABEL_VERIFY=found
    else
      LABEL_VERIFY="$?"
    fi
  fi
  rm -f "$LABELS_FILE"
  case "$LABEL_VERIFY" in
    found)
      LABEL_ARGS=(-l "$LABEL")
      LABEL_RESULT="applied"
      ;;
    1)
      LABEL_RESULT="skipped-label-not-found"
      echo "WARN: label '$LABEL' does not exist on this project — creating MR without it." >&2
      ;;
    *)
      LABEL_RESULT="skipped-api-error"
      echo "WARN: could not verify label '$LABEL' on the project (API error) — creating MR without it." >&2
      ;;
  esac
fi

# Create the MR
if ! glab mr create \
  -b "$TARGET_BRANCH" \
  -t "$TITLE" \
  -d "$(cat "$BODY_FILE")" \
  ${LABEL_ARGS[@]+"${LABEL_ARGS[@]}"} \
  -y; then
  echo "ERROR: glab mr create failed." >&2
  exit 1
fi

echo "OK: MR created"
echo "LABEL: $LABEL_RESULT"
