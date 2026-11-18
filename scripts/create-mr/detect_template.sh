#!/usr/bin/env bash
# detect_template.sh — Find and output the MR template for the current repository.
#
# Usage: detect_template.sh
#
# Searches known locations for MR templates. If found, outputs the template
# content to stdout. If not found, outputs nothing and exits 0.
#
# Known locations (in priority order):
#   1. .gitlab/merge_request_templates/*.md
#   2. .gitlab/merge_request_template.md
#   3. .gitlab/MERGE_REQUEST_TEMPLATE.md
#   4. ./MERGE_REQUEST_TEMPLATE.md
#   5. ./MR_TEMPLATE.md
#   6. ./PULL_REQUEST_TEMPLATE.md
#   7. .github/PULL_REQUEST_TEMPLATE.md
#
# Exits 1 only if not in a Git repository.

set -euo pipefail

# Ensure we are in a Git repository
if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "ERROR: Not in a Git repository." >&2
  exit 1
fi

TOPLEVEL="$(git rev-parse --show-toplevel)"
cd "$TOPLEVEL"

TEMPLATE_CONTENT=""

# 1. .gitlab/merge_request_templates/*.md (take the first one, alphabetically sorted)
if [ -d ".gitlab/merge_request_templates" ]; then
  FIRST_TEMPLATE=$(ls .gitlab/merge_request_templates/*.md 2>/dev/null | sort | head -1)
  if [ -n "$FIRST_TEMPLATE" ] && [ -f "$FIRST_TEMPLATE" ]; then
    TEMPLATE_CONTENT=$(cat "$FIRST_TEMPLATE")
  fi
fi

# 2. .gitlab/merge_request_template.md
if [ -z "$TEMPLATE_CONTENT" ] && [ -f ".gitlab/merge_request_template.md" ]; then
  TEMPLATE_CONTENT=$(cat ".gitlab/merge_request_template.md")
fi

# 3. .gitlab/MERGE_REQUEST_TEMPLATE.md
if [ -z "$TEMPLATE_CONTENT" ] && [ -f ".gitlab/MERGE_REQUEST_TEMPLATE.md" ]; then
  TEMPLATE_CONTENT=$(cat ".gitlab/MERGE_REQUEST_TEMPLATE.md")
fi

# 4. ./MERGE_REQUEST_TEMPLATE.md
if [ -z "$TEMPLATE_CONTENT" ] && [ -f "MERGE_REQUEST_TEMPLATE.md" ]; then
  TEMPLATE_CONTENT=$(cat "MERGE_REQUEST_TEMPLATE.md")
fi

# 5. ./MR_TEMPLATE.md
if [ -z "$TEMPLATE_CONTENT" ] && [ -f "MR_TEMPLATE.md" ]; then
  TEMPLATE_CONTENT=$(cat "MR_TEMPLATE.md")
fi

# 6. ./PULL_REQUEST_TEMPLATE.md
if [ -z "$TEMPLATE_CONTENT" ] && [ -f "PULL_REQUEST_TEMPLATE.md" ]; then
  TEMPLATE_CONTENT=$(cat "PULL_REQUEST_TEMPLATE.md")
fi

# 7. .github/PULL_REQUEST_TEMPLATE.md
if [ -z "$TEMPLATE_CONTENT" ] && [ -f ".github/PULL_REQUEST_TEMPLATE.md" ]; then
  TEMPLATE_CONTENT=$(cat ".github/PULL_REQUEST_TEMPLATE.md")
fi

# Output: template content or nothing
if [ -n "$TEMPLATE_CONTENT" ]; then
  printf '%s\n' "$TEMPLATE_CONTENT"
fi
