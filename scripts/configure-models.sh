#!/usr/bin/env bash
# configure-models.sh — Aurora model configuration (standalone, re-runnable).
#
# Resolves config/model-roles.json (versioned role policy) against models
# actually usable with the user's API keys (discovery + real probes), then
# generates the LIVE OpenCode config (opencode.json, agents/*.md frontmatters,
# aurora-models.json). Never modifies the repository. Always backs up before
# writing. Designed to be non-breaking: existing verified selections are kept.
#
# Usage:
#   scripts/configure-models.sh [--yes] [--dry-run] [--providers a,b] [--force] [--quiet]
#
# This script is invoked by setup.sh and can be run standalone at any time
# (key changed, provider added, model rotated).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OPENCODE_DIR="${OPENCODE_DIR:-$HOME/.config/opencode}"

# Secrets (never printed): source the live .env so probes can use the keys.
# shellcheck disable=SC1091
[ -f "$OPENCODE_DIR/.env" ] && set -a && source "$OPENCODE_DIR/.env" && set +a

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PYTHON_BIN="$c"; break; fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "error: python3 not found (required for the model configuration engine)" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/lib/configure_models.py" "$@"
