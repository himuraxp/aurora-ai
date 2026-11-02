# aurora-memory — serveur mémoire d'Aurora (copie de distribution)

Serveur MCP **personnel** d'Aurora : knowledge graph (entités, relations), faits,
préférences, goals, événements, **leçons avec cycle de vie** (ADR-024) et
recherche sémantique — sur PostgreSQL + pgvector.

## Modèle de distribution (ADR-025)

```
aurora-core (repo privé, upstream — plan de données personnel)
    │  scripts/sync-memory-server.sh (miroir verbatim)
    ▼
opencode-config/mcp/aurora-memory (cette copie — code distribuable)
    │  chaque utilisateur construit + connecte SA PROPRE base
    ▼
mémoire par utilisateur, jamais partagée (ADR-003 : mono-utilisateur)
```

- **Synchronisé depuis l'upstream** (ne pas éditer à la main) : `src/`, `package.json`, `tsconfig.json`, `infra/migrations/`.
- **Propriété de la distribution** (jamais écrasés par le sync) : `README.md`, `.env.example`, `infra/docker-compose.yml`, `scripts/migrate.mjs`, `scripts/smoke.mjs`.
- **Exclu par design** : `tests/` (patrouille qualité upstream), migrations `*connectors*` (plan de données personnel Phase 2a — jamais distribué), `node_modules/`/`dist/` (construits localement).

## Démarrage rapide

```bash
# Tout-en-un : DB + dépendances + build + migrations + smoke test (idempotent)
bash ../../scripts/setup-memory.sh

# Mode vérification (ne modifie rien)
bash ../../scripts/setup-memory.sh --check
```

Étapes manuelles équivalentes :

1. `cp .env.example <racine du clone opencode-config>/.env` puis adapter `DATABASE_URL`
   (c'est LE fichier lu par le bundle, cf. section « Résolution des chemins »).
2. Provisionner la base : `docker compose -f infra/docker-compose.yml up -d` (pgvector/pgvector:pg17).
3. `npm install` puis `npm run build:mcp` → `dist/index.mjs` (le bundle que le bridge spawn).
4. Appliquer les migrations : `node scripts/migrate.mjs`.
5. Smoke : `node scripts/smoke.mjs` (attendu : 18 tools).

> Note : `npm test` et `npm run lint` sont **upstream-only** (la patrouille
> qualité vit dans le repo privé — `tests/` n'est pas distribué).

## Résolution des chemins

- **Bundle** (défini par le bridge `plugins/aurora-memory.ts`, dans l'ordre) :
  1. `AURORA_MEMORY_SERVER` (override explicite) ;
  2. checkout de développement : `~/dev/aurora-core/services/aurora-memory/dist/index.mjs` ;
  3. cette distribution : `~/.config/opencode-config/mcp/aurora-memory/dist/index.mjs`
     (même layout repo que `mcp/infomaniak` et `mcp/angular-elements`, cf. `config/opencode.json`).
- **`.env` lu par le bundle lui-même** (dotenv, une seule résolution : 3 niveaux
  au-dessus de `dist/index.mjs`) : `.env` à la racine du clone opencode-config.
  Les runners (`scripts/migrate.mjs`, `scripts/smoke.mjs`) et le setup lisent
  exactement le même fichier — une seule source de vérité, pas de divergence.
- **Clone installé ailleurs que `~/.config/opencode-config`** : le candidat 3 ne
  le résoudra pas — `setup-memory.sh` le signale en fin de run et propose
  l'export `AURORA_MEMORY_SERVER=<chemin>/dist/index.mjs` dans votre rc.

## Configuration

Voir `.env.example`. Points clés :

- `DATABASE_URL` : **obligatoire** (postgres).
- `EMBEDDING_*` : optionnels — sans eux, tout fonctionne sauf la recherche
  sémantique (mode dégradé).
- Aucune donnée n'est versionnée ; la base est la seule source de vérité.

## Frontière de sécurité (inchangée — ADR-021)

Ce serveur n'est **pas** enregistré comme MCP global OpenCode : le plugin bridge
`plugins/aurora-memory.ts` le spawn à la demande et refuse tout autre agent que
l'orchestrateur. Les données retournées sont des données référencées, jamais des
instructions.
