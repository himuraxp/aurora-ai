#!/usr/bin/env bash
# setup-memory.sh — onboarding de la mémoire personnelle d'Aurora (ADR-025).
#
# Provisionne, vérifie et démarre le serveur mémoire (mcp/aurora-memory/) sur
# UNE base PostgreSQL+pgvector PAR UTILISATEUR — la mémoire n'est jamais
# partagée (ADR-003). Idempotent : chaque étape est sautée si déjà satisfaite.
# Non destructif : jamais de down/delete de volume, jamais d'écrasement de .env.
#
# Usage :
#   bash setup-memory.sh           # applique les étapes manquantes
#   bash setup-memory.sh --check   # vérifie sans rien modifier
#
# Codes de sortie : 0 = prêt · 1 = échec · 2 = configuration incomplète (.env)
set -euo pipefail

CHECK=0
case "${1:-}" in
  "") ;;
  --check) CHECK=1 ;;
  *) printf 'usage: setup-memory.sh [--check]\n' >&2; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_ROOT="$REPO_ROOT/mcp/aurora-memory"
LOG_PREFIX="?"

# Fichier .env lu par le bundle lui-même (dotenv, heuristique 3-niveaux
# au-dessus de dist/index.mjs) — source UNIQUE, en cohérence avec les runners
# (migrate.mjs, smoke.mjs) et avec ce script. Une DATABASE_URL déjà exportée
# dans l'environnement reste prioritaire.
ENV_FILE="$REPO_ROOT/.env"
DEFAULT_DATABASE_URL="postgresql://aurora:aurora@127.0.0.1:5433/aurora"

log()  { printf '%s %s\n' "$1" "$2"; }
ok()   { log "✓" "$1"; }
skip() { log "=" "$1"; }
fail() { log "✗" "$1" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# Charge DATABASE_URL depuis l'environnement puis depuis ENV_FILE.
# Parsing SANS eval (le .env est un fichier externe : jamais évalué comme du shell),
# guillemets d'encadrement retirés, format validé. La valeur n'est jamais affichée.
load_database_url() {
  DATABASE_URL="${DATABASE_URL:-}"
  if [[ -z "$DATABASE_URL" && -f "$ENV_FILE" ]] && grep -q '^DATABASE_URL=' "$ENV_FILE"; then
    DATABASE_URL="$(grep '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | sed 's/^"\(.*\)"$/\1/')"
  fi
  [[ -n "$DATABASE_URL" && "$DATABASE_URL" == postgres* ]]
}

# Sonde read-only de la base (SELECT 1) via le module pg du serveur.
probe_db() {
  (cd "$SERVER_ROOT" && node -e "
    const pg = require('pg');
    const c = new pg.Client({ connectionString: process.env.DATABASE_URL, connectionTimeoutMillis: 5000 });
    c.connect()
      .then(() => c.query('SELECT 1'))
      .then(() => { console.log('DB_OK'); return c.end(); })
      .catch((e) => { console.error(e.message); process.exit(1); });
  " >/dev/null 2>&1)
}

step_prereqs() {
  have node || fail "node absent (requis ≥ 22, cf. mcp/aurora-memory/package.json engines) — https://nodejs.org"
  have npm  || fail "npm absent (fourni avec node)"
  ok "prérequis node/npm présents"
}

# .env : si ENV_FILE est absent ET qu'aucune DATABASE_URL n'est exportée, le
# script (hors --check) le crée depuis .env.example. Un fichier EXISTANT n'est
# JAMAIS touché (pas d'écrasement, pas d'append) — on demande l'ajout manuel.
step_env() {
  if [[ -n "${DATABASE_URL:-}" ]]; then
    ok "DATABASE_URL fournie par l'environnement"
    return 0
  fi
  if [[ -f "$ENV_FILE" ]]; then
    if grep -q '^DATABASE_URL=' "$ENV_FILE"; then
      ok "config .env trouvée : $ENV_FILE"
    else
      log "✗" "$ENV_FILE existe mais ne définit pas DATABASE_URL — ajoutez-y la ligne DATABASE_URL=postgresql://… puis relancez"
      exit 2
    fi
  elif [[ $CHECK -eq 1 ]]; then
    log "✗" "aucune DATABASE_URL configurée — relancez sans --check pour créer $ENV_FILE depuis l'exemple"
    exit 2
  else
    cp "$SERVER_ROOT/.env.example" "$ENV_FILE"
    ok "config créée : $ENV_FILE (adaptez DATABASE_URL au besoin)"
  fi
}

step_db() {
  if load_database_url && probe_db; then
    skip "base mémoire joignable (SELECT 1)"
    return 0
  fi
  if [[ $CHECK -eq 1 ]]; then
    log "✗" "base mémoire injoignable et docker non invoqué (--check)"
    exit 2
  fi
  have docker || fail "docker absent et base injoignable — installez Docker ou renseignez DATABASE_URL"
  log "?" "provisionnement PostgreSQL+pgvector (compose : $SERVER_ROOT/infra/docker-compose.yml)"
  docker compose -f "$SERVER_ROOT/infra/docker-compose.yml" up -d postgres \
    || fail "échec docker compose up — vérifiez Docker"
  log "?" "attente de la base (60 s max, DATABASE_URL par défaut du compose)…"
  local i
  for i in $(seq 1 60); do
    DATABASE_URL="$DEFAULT_DATABASE_URL" probe_db && break
    sleep 1
    [[ $i -eq 60 ]] && fail "base non prête après 60 s — vérifiez 'docker compose -f $SERVER_ROOT/infra/docker-compose.yml logs'"
  done
  ok "base PostgreSQL+pgvector prête (défaut : 127.0.0.1:5433 — adaptez DATABASE_URL si vous personnalisez)"
}

step_deps() {
  if [[ -d "$SERVER_ROOT/node_modules/@modelcontextprotocol" ]]; then
    skip "dépendances npm installées"
  else
    [[ $CHECK -eq 1 ]] && { log "✗" "dépendances npm manquantes (--check)"; exit 2; }
    log "?" "npm install (mcp/aurora-memory)…"
    (cd "$SERVER_ROOT" && npm install --no-audit --no-fund) || fail "npm install"
    ok "dépendances installées"
  fi
}

step_build() {
  if [[ -f "$SERVER_ROOT/dist/index.mjs" ]] \
     && [[ -z "$(find "$SERVER_ROOT/src" -newer "$SERVER_ROOT/dist/index.mjs" -print -quit 2>/dev/null)" ]]; then
    skip "bundle dist/index.mjs à jour"
  else
    [[ $CHECK -eq 1 ]] && { log "✗" "bundle absent ou périmé (--check)"; exit 2; }
    log "?" "build du bundle (npm run build:mcp)…"
    (cd "$SERVER_ROOT" && npm run build:mcp) || fail "build:mcp"
    ok "bundle construit : $SERVER_ROOT/dist/index.mjs"
  fi
}

step_migrate() {
  if [[ $CHECK -eq 1 ]]; then
    log "=" "migrations (sautées en --check — idempotentes hors check)"
  else
    log "?" "application des migrations (idempotent)…"
    (cd "$SERVER_ROOT" && load_database_url && DATABASE_URL="$DATABASE_URL" node scripts/migrate.mjs) \
      || fail "migrations — vérifiez DATABASE_URL"
    ok "migrations appliquées (état schema_migrations)"
  fi
}

step_smoke() {
  (cd "$SERVER_ROOT" && DATABASE_URL="${DATABASE_URL:-$DEFAULT_DATABASE_URL}" node scripts/smoke.mjs) \
    || fail "smoke test — bundle invalide"
}

step_prereqs
[[ -d "$SERVER_ROOT" ]] || fail "copie de distribution absente : $SERVER_ROOT"
step_env
step_deps    # avant step_db : la sonde DB utilise le module pg du package
step_db
step_build
step_migrate
step_smoke

printf '\n%s\n' "Mémoire personnelle prête (par-utilisateur — jamais partagée, ADR-003/025)."
[[ $CHECK -eq 1 ]] || printf '%s\n' "Optionnel : recherche sémantique → renseignez EMBEDDING_* dans votre .env (sinon mode dégradé)."
CANONICAL_ROOT="$HOME/.config/opencode-config"
if [[ "$REPO_ROOT" != "$CANONICAL_ROOT" ]]; then
  printf '\n%s\n' "Clone non canonique ($REPO_ROOT ≠ $CANONICAL_ROOT) : le bridge ne résoudra pas ce bundle automatiquement."
  printf '%s\n' "  → exportez dans votre rc :  export AURORA_MEMORY_SERVER=\"$SERVER_ROOT/dist/index.mjs\""
fi
