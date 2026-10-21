#!/usr/bin/env bash
# build_comparison_table.sh — Build the Before/After comparison Markdown table.
#
# Usage: build_comparison_table.sh \
#   --before "<upload Markdown of the BEFORE screenshot>" \
#   --after  "<upload Markdown of the AFTER screenshot>" \
#   [--caption "<component or feature name>"] \
#   [--before-label "<label>"] \
#   [--after-label "<label>"]
#
# Inputs are the Markdown snippets returned by upload_media.sh (one per
# image). This script performs NO network calls and never touches GitLab:
# upload first with upload_media.sh, then pass the returned snippets here.
#
# Output (stdout): an optional bold caption line followed by a two-column
# Markdown table, ready to be appended to the Solution section of the MR
# description.
#
# Fail-closed: missing/empty snippet, a snippet that does not look like an
# upload link, or a caption/label containing a pipe (would break the table)
# exits 1 with an error on stderr. An upload failure must never silently
# produce a broken table.
#
# This script does NOT commit, push, or modify any tracked files.

set -euo pipefail

BEFORE=""
AFTER=""
CAPTION=""
BEFORE_LABEL="Avant"
AFTER_LABEL="Après"

usage() {
  echo "Usage: build_comparison_table.sh --before <md> --after <md> [--caption <text>] [--before-label <text>] [--after-label <text>]" >&2
}

missing_value() {
  echo "ERROR: Missing value for option: $1" >&2
  usage
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --before)
      [ $# -ge 2 ] || missing_value "$1"
      BEFORE="$2"
      shift 2
      ;;
    --after)
      [ $# -ge 2 ] || missing_value "$1"
      AFTER="$2"
      shift 2
      ;;
    --caption)
      [ $# -ge 2 ] || missing_value "$1"
      CAPTION="$2"
      shift 2
      ;;
    --before-label)
      [ $# -ge 2 ] || missing_value "$1"
      BEFORE_LABEL="$2"
      shift 2
      ;;
    --after-label)
      [ $# -ge 2 ] || missing_value "$1"
      AFTER_LABEL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

# Fail-closed: both sides are required — without one there is no comparison.
if [ -z "$BEFORE" ] || [ -z "$AFTER" ]; then
  echo "ERROR: --before and --after are both required (non-empty upload Markdown from upload_media.sh)." >&2
  usage
  exit 1
fi

# Fail-closed: snippets must look like a GitLab upload image link returned by
# upload_media.sh (e.g. ![name](/uploads/<secret>/name.png)) — a local path
# or an external URL would render as a broken image in the MR.
looks_like_upload_md() {
  echo "$1" | grep -qE '!\[[^]]*\]\([^)]*/uploads/[^)]+\)'
}

if ! looks_like_upload_md "$BEFORE"; then
  echo "ERROR: --before does not look like a GitLab upload Markdown snippet (expected ![...](/uploads/...))." >&2
  exit 1
fi

if ! looks_like_upload_md "$AFTER"; then
  echo "ERROR: --after does not look like a GitLab upload Markdown snippet (expected ![...](/uploads/...))." >&2
  exit 1
fi

# Fail-closed: a pipe or a newline inside any table cell/caption would break
# the Markdown table (the GitLab upload alt-text derives from the file name,
# so e.g. "avant|apres.png" is a real case). Snippets are single-line by
# contract (one Markdown per line from upload_media.sh).
contains_table_breaker() {
  case "$1" in
    *"|"*|*"
"*) return 0 ;;
    *) return 1 ;;
  esac
}

for value in "$BEFORE" "$AFTER" "$CAPTION" "$BEFORE_LABEL" "$AFTER_LABEL"; do
  if contains_table_breaker "$value"; then
    echo "ERROR: caption, labels and snippets must not contain a pipe or a newline character (would break the Markdown table)." >&2
    exit 1
  fi
done

if [ -n "$CAPTION" ]; then
  echo "**${CAPTION} :**"
  echo ""
fi

echo "| ${BEFORE_LABEL} | ${AFTER_LABEL} |"
echo "| ------ | ------ |"
echo "| ${BEFORE} | ${AFTER} |"
