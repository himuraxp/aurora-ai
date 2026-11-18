#!/usr/bin/env bash
# validate_title.sh — Validate that a title follows Conventional Commit format.
#
# Usage: validate_title.sh "<title>"
#
# Valid format: <type>(<scope>): <description>
#   type: feat|fix|refactor|perf|docs|test|build|ci|chore|style|meta|license
#   scope: optional, in parentheses
#   description: mandatory
#
# Exits 0 if valid, 1 if invalid. Error messages on stderr.

set -euo pipefail

if [ $# -lt 1 ] || [ -z "$1" ]; then
  echo "ERROR: No title provided." >&2
  echo "Usage: validate_title.sh \"<title>\"" >&2
  exit 1
fi

TITLE="$1"

# Conventional Commit regex
# Type: required, from the allowed list
# Scope: optional, in parentheses
# Breaking change: optional (!)
# Separator: colon + space
# Description: required
VALID_TYPES='feat|fix|refactor|perf|docs|test|build|ci|chore|style|meta|license'

if ! echo "$TITLE" | grep -qE "^(${VALID_TYPES})(\([^)]+\))?!?: .+"; then
  echo "ERROR: Title does not respect Conventional Commit format." >&2
  echo "" >&2
  echo "Expected: <type>(<scope>): <description>" >&2
  echo "Valid types: ${VALID_TYPES//|/, }" >&2
  echo "Examples:" >&2
  echo "  feat(auth): add OAuth2 login" >&2
  echo "  fix(api): handle null response" >&2
  echo "  refactor: extract validation logic" >&2
  exit 1
fi

# Check title length (max 100 chars)
if [ ${#TITLE} -gt 100 ]; then
  echo "ERROR: Title is too long (${#TITLE} chars, max 100)." >&2
  exit 1
fi

# Check no trailing period
if echo "$TITLE" | grep -qE '\.$'; then
  echo "WARN: Title should not end with a period." >&2
fi

echo "OK"
