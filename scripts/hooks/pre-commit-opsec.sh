#!/usr/bin/env bash
# pre-commit-opsec.sh - pre-commit gate for internal infrastructure metadata
# (hosts, private package names, internal paths, internal naming).
# Complements the secret scanner: gitleaks sees credentials, this gate sees
# identifiers. Standalone installation:
#   cp scripts/hooks/pre-commit-opsec.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#   git config core.hooksPath scripts/hooks
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/opsec-gate.sh" --staged
