#!/usr/bin/env bash
# Sync the aurora-memory MCP server from its upstream (aurora-core, private) into
# the public distribution copy (mcp/aurora-memory/) — ADR-025.
#
# Model (ADR-002/025): aurora-core = upstream source of truth (development, personal
# data plane) — opencode-config/mcp/aurora-memory = distribution snapshot that any
# self-hosted install can build and run with its OWN database (per-user memory).
#
# Synced verbatim : src/, package.json, tsconfig.json, infra/migrations (minus connectors).
# Distribution-owned (never overwritten) : infra/docker-compose.yml, .env.example, README.md.
#
# Excluded from distribution by design:
#   - node_modules/, dist/  (built on install — npm ci && npm run build:mcp)
#   - tests/                (upstream quality gate; require the private repo layout)
#   - *connectors* migrations (personal data plane, Phase 2a J1 — never distributed)
set -euo pipefail
shopt -s nullglob   # un dossier migrations vide/erroné ne doit jamais produire de glob littéral ni de rm massif

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UPSTREAM="${AURORA_MEMORY_UPSTREAM:-$HOME/dev/aurora-core/services/aurora-memory}"
UPSTREAM_INFRA="${AURORA_MEMORY_UPSTREAM_INFRA:-$HOME/dev/aurora-core/infra}"
DIST="$REPO_ROOT/mcp/aurora-memory"

if [[ ! -d "$UPSTREAM/src" ]]; then
  echo "✗ upstream introuvable: $UPSTREAM" >&2
  echo "  (surcharger avec AURORA_MEMORY_UPSTREAM=/chemin/services/aurora-memory)" >&2
  exit 1
fi
if [[ ! -d "$UPSTREAM_INFRA/migrations" ]]; then
  echo "✗ migrations upstream introuvables: $UPSTREAM_INFRA/migrations" >&2
  echo "  (surcharger avec AURORA_MEMORY_UPSTREAM_INFRA=/chemin/infra)" >&2
  exit 1
fi

mkdir -p "$DIST/infra/migrations"

# 1. Mirror verbatim blocks (delete + copy = exact mirror, anti-drift).
rsync -a --delete "$UPSTREAM/src/" "$DIST/src/"
cp "$UPSTREAM/package.json" "$DIST/package.json"
cp "$UPSTREAM/tsconfig.json" "$DIST/tsconfig.json"

# 2. Migrations — everything upstream has EXCEPT the connectors schema (ADR-025).
for f in "$UPSTREAM_INFRA"/migrations/*.sql; do
  base="$(basename "$f")"
  if [[ "$base" == *connectors* ]]; then
    echo "- $base (exclue : schéma connectors — plan de données personnel, jamais distribué)"
  else
    cp "$f" "$DIST/infra/migrations/$base"
  fi
done
# Guard: remove distribution migrations that no longer exist upstream (anti-drift).
for f in "$DIST"/infra/migrations/*.sql; do
  base="$(basename "$f")"
  if [[ ! -f "$UPSTREAM_INFRA/migrations/$base" ]]; then
    rm -f "$f"
    echo "- $base (retirée : absente de l'upstream)"
  fi
done

echo "✓ distribution synchronisée : $DIST"
echo "  upstream = $UPSTREAM"
