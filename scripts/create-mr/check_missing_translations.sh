#!/usr/bin/env bash
# check_missing_translations.sh — Detect transloco literals added by the
# branch that are missing from the project's translation reference file.
#
# Usage: check_missing_translations.sh \
#   --target-branch <name> \
#   [--translations-file <path>] \
#   [--max-examples <n>]
#
# Pure local check: git only, never any network call, never writes to the
# workspace.
# Exit 0 on a completed check (including an empty result), 1 on an
# environment error (not a repo, unknown branch, missing python3).
#
# Output (stdout, single JSON object):
#   action: "label" (missing strings → pass --label to create_mr.sh)
#         | "none" (check ran clean)
#         | "skipped-no-translations-file"
#         | "skipped-no-changed-files"
#   missing / missingCount / missingTruncated / extractedCount /
#   checkedFiles / translationsFile

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET_BRANCH=""
TRANSLATIONS_FILE=""
MAX_EXAMPLES="20"

while [ $# -gt 0 ]; do
  case "$1" in
    --target-branch)
      [ $# -ge 2 ] || { echo "ERROR: Missing value for --target-branch" >&2; exit 1; }
      TARGET_BRANCH="$2"
      shift 2
      ;;
    --translations-file)
      [ $# -ge 2 ] || { echo "ERROR: Missing value for --translations-file" >&2; exit 1; }
      TRANSLATIONS_FILE="$2"
      shift 2
      ;;
    --max-examples)
      [ $# -ge 2 ] || { echo "ERROR: Missing value for --max-examples" >&2; exit 1; }
      MAX_EXAMPLES="$2"
      shift 2
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "$TARGET_BRANCH" ]; then
  echo "ERROR: --target-branch is required." >&2
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found." >&2
  exit 1
fi

if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "ERROR: Not in a Git repository." >&2
  exit 1
fi
TOPLEVEL="$(git rev-parse --show-toplevel)"
cd "$TOPLEVEL"

BASE_REF=""
if git rev-parse --verify --quiet "refs/heads/$TARGET_BRANCH" &>/dev/null; then
  BASE_REF="$TARGET_BRANCH"
elif git rev-parse --verify --quiet "refs/remotes/origin/$TARGET_BRANCH" &>/dev/null; then
  BASE_REF="origin/$TARGET_BRANCH"
else
  echo "ERROR: Base branch '$TARGET_BRANCH' not found locally or on origin. Run 'git fetch' first." >&2
  exit 1
fi

if [ -n "$TRANSLATIONS_FILE" ]; then
  if [ ! -f "$TRANSLATIONS_FILE" ]; then
    echo "ERROR: --translations-file '$TRANSLATIONS_FILE' does not exist." >&2
    exit 1
  fi
else
  for candidate in \
    "src/translations/fr_FR.json" \
    "src/assets/i18n/fr.json" \
    "src/assets/i18n/fr-FR.json" \
    "src/locales/fr.json" \
    "public/locales/fr.json"; do
    if [ -f "$candidate" ]; then
      TRANSLATIONS_FILE="$candidate"
      break
    fi
  done
  if [ -z "$TRANSLATIONS_FILE" ]; then
    for dir in src/translations src/assets/i18n src/locales public/locales; do
      if [ -d "$dir" ]; then
        candidate="$(ls "$dir"/fr*.json 2>/dev/null | head -1 || true)"
        if [ -n "$candidate" ]; then
          TRANSLATIONS_FILE="$candidate"
          break
        fi
      fi
    done
  fi
fi

if [ -z "$TRANSLATIONS_FILE" ]; then
  TRANS_DIR=""
else
  # Normalize and resolve relative paths from the repo root.
  TRANSLATIONS_FILE="${TRANSLATIONS_FILE#./}"
  TRANS_DIR="$(dirname "$TRANSLATIONS_FILE")"
fi

if [ -z "$TRANSLATIONS_FILE" ]; then
  echo '{"action":"skipped-no-translations-file","missing":[],"missingCount":0,"missingTruncated":false,"extractedCount":0,"checkedFiles":0,"translationsFile":null}'
  exit 0
fi

case "$MAX_EXAMPLES" in
  '' | *[!0-9]*)
    echo "ERROR: --max-examples must be a positive integer." >&2
    exit 1
    ;;
esac

PATHSPECS=('*.ts' '*.html' ':!*.spec.ts')
if [ "$TRANS_DIR" != "." ]; then
  PATHSPECS+=(":!${TRANS_DIR}/**")
fi
CHANGED_FILES="$(git diff --name-only "$BASE_REF...HEAD" -- "${PATHSPECS[@]}" | wc -l | tr -d ' ')"

ADDED_FILE="$(mktemp)"
trap 'rm -f "$ADDED_FILE"' EXIT
# Keep ADDED lines only: drop the +++ header, then print only lines starting
# with '+' (removed lines '-' and --- headers never match).
git diff -U0 --no-color "$BASE_REF...HEAD" -- "${PATHSPECS[@]}" |
  sed -e '/^+++ /d' -n -e 's/^+//p' >"$ADDED_FILE"

if [ "$CHANGED_FILES" -eq 0 ]; then
  python3 "$SCRIPT_DIR/check_missing_translations.py" \
    --added-file "$ADDED_FILE" \
    --translations-file "$TRANSLATIONS_FILE" \
    --checked-files 0 \
    --max-examples "$MAX_EXAMPLES" \
    --action skipped-no-changed-files
  exit 0
fi

python3 "$SCRIPT_DIR/check_missing_translations.py" \
  --added-file "$ADDED_FILE" \
  --translations-file "$TRANSLATIONS_FILE" \
  --checked-files "$CHANGED_FILES" \
  --max-examples "$MAX_EXAMPLES"
