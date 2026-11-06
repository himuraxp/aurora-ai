#!/usr/bin/env bash
# commit-msg-opsec.sh - commit-msg gate: the message text itself is a leak
# channel. The 2026-11-06 wave documented an internal investigation in a
# commit message and a PR body, channels that survive any later code fix.
# Standalone installation:
#   cp scripts/hooks/commit-msg-opsec.sh .git/hooks/commit-msg
#   chmod +x .git/hooks/commit-msg
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/opsec-gate.sh" --message "$1"
