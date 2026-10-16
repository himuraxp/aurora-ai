# CHANGELOG

## 2026-10-09

- Hook pre-commit secrets : patterns ERE morts réparés (échap. BRE `\+`/`\{n\}` = littéraux en ERE), ajout des assignments `GITLAB_TOKEN=`/`INFOMANIAK_PREPROD_API_TOKEN=` (ancrés, préfixe de valeur), format PAT GitLab interne `PAT….01.…`, scan des fichiers renommés (`--diff-filter=ACMR`)
- Nouvelle suite e2e `scripts/hooks/test-pre-commit-patterns.sh` (sandbox : 26 cas positifs bloqués, négatifs passent, bypass par renommage couvert) branchée dans `scripts/health-check.sh`
- gitleaks intégré au pre-commit (deep scan) + `.gitleaks.toml` (allowlist de la suite de fixtures)
- MCP angular-elements : endpoints GitLab internes + project id déplacés vers la configuration `ANGULAR_ELEMENTS_*` (plus aucune valeur interne en dur dans le repo public) ; `ANGULAR_ELEMENTS_REF` optionnel
- Skills : exemples GitLab internes anonymisés (deployment-changelog, mr-review)

## 2026-09-09

- Migration du stockage de la clé API Infomaniak : OpenCode ne charge pas les `.env` → la clé vit désormais dans le shell rc de l'utilisateur (`~/.zshrc`, bloc managé idempotent par `setup.sh`), lue via `{env:OPENAI_API_KEY_INFOMANIAK}` (correction 401 sur installation fraîche)
- `scripts/setup.sh` : bloc managé idempotent (markers `# >>> opencode-config (managed by setup.sh) >>>`), dédoublonnage des exports libres de `OPENAI_API_KEY_INFOMANIAK`/`IDB_UDID`/`IDB_PATH` (déplacement, jamais de duplication), re-émission verbatim des valeurs rc (pas de double-échappement %q), rewrite atomique (tmp + `mv` unique), permissions préservées, backup + syntax-check du rc avec restauration, seed clé `shell rc > secret legacy > .env > prompt`, seed `IDB_*` depuis rc, lectures secrets masquées (`read -rs`)
- `config/opencode.json` : provider Infomaniak en `Bearer {env:...}`, baseURLs en dur (standard + B300), deny-list `secrets/*` préventive
- `IDB_UDID`/`IDB_PATH` quittent le `.env` pour le shell rc (MCP ios-simulator sans fallback `.env`)
- `scripts/install.sh` : migration automatique non bloquante + warn si clé absente du shell rc
- `scripts/migrate-secrets.sh` + `scripts/test-migrate-secrets.sh` : supprimés (approche V1 abandonnée avant commit)
- `scripts/hooks/pre-commit-secrets.sh` : pattern `OPENAI_API_KEY[A-Za-z_]*=` (couvre la nouvelle variable)
- Docs alignées : `README.md`, `AGENTS.md`, `config/README.md`, `config/.env.example`

## 2026-08-12

- Audit read-only + correction de 10 findings (3 high, 4 medium, 2 low, 1 info)
- `config/oh-my-opencode-slim.json` : preset `opencode-go` supprimé (provider non disponible)
- `config/.env.example` : documentation B300 sans Authorization (endpoint interne) + différences euria-code entre providers
- `agents/spark.md` : modèle → Ministral-3 (alignement doc), `cat *` restreint à `./mr-*.md` + `./*.md`
- `agents/aurora.md` : référence Spark mise à jour (Ministral-3)
- `agents/{atlas,crawler,scribe,pulse,echo,sage,beacon}.md` : `cat *` → `deny` (sécurité sous-agents, tool `read` suffit)
- `agents/aurora-heavy.md` : `cat *` → `ask` (agent primary interactif)
- `docs/ai/WARNINGS.md` : warnings stale archivés (aurora-heavy, cat *, opencode-go), risques permissions documentés
- `docs/ai/BUFFER.md` : nettoyage (5 snapshots → 1 récent)
- `docs/ai/STATUS.md` : allégement (263 → 30 lignes, historique archivé dans CHANGELOG)
- `examples/node-api/AGENTS.md` : créé (template + référence `frameworks/nodejs.md`)
- `examples/monorepo/AGENTS.md` : créé (template + références multi-frameworks)
- `docs/testing.md` : mis à jour (Angular-only → multi-stack avec sections Node.js/NestJS)
- `docs/ai/INDEX.md` : mis à jour (15 agents, 16 standards, config, conventions, commande recherche)
- `docs/ai/DECISIONS.md` : 3 décisions ajoutées (cat * durcissement, opencode-go suppression, Spark Ministral-3)
- `docs/workflow.md` : référence à `agent-output.md` ajoutée (section délégation)
- `examples/angular-app/AGENTS.md` : synchronisé avec `templates/AGENTS.md` (rôle, standards, modes, doc IA)
- `scripts/health-check.sh` : nouveau script de vérification de cohérence (JSON, frontmatter, modèles, orphelins, références)
- `scripts/permissions-matrix.sh` : nouveau script générant un tableau markdown des permissions agents
- `scripts/validate-memory.sh` : nouveau script validant la structure `docs/ai/` d'un projet
- `scripts/hooks/pre-commit-secrets.sh` : nouveau hook git anti-fuite de secrets (API keys, private keys, passwords, connection strings)
- `scripts/init-project.sh` : auto-détection de stack (angular.json, nest-cli.json, astro.config.*, package.json)
- `README.md` : clarification stubs examples + suppression mention opencode-go + section scripts étendue
- Config active synchronisée (`install.sh --prune` : memory.md orphelin supprimé, 12 agents mis à jour)

## 2026-08-11

- Nouveau standard `agent-output.md` : format de retour JSON structuré pour les sous-agents (schéma v1, 12 catégories, 5 sévérités, consolidation multi-agents)
- 13 agents mis à jour avec section "Format de retour JSON" (atlas, crawler, sage, scribe, pulse, echo, beacon, reviewer, security, architect, tester, spark, vision) — aucune exception
- `aurora.md` et `AGENTS.md` : référence au standard dans les règles de délégation et comportement attendu

## 2026-08-10

- Audit complet read-only du repo (55 findings sur 4 zones via subagents Reviewer parallèles)
- Correction du routing Search & Growth : délégation automatique + mots-clés déclencheurs + routing multi-agents
- Équipe Search & Growth : 7 nouveaux agents (atlas, crawler, sage, scribe, pulse, echo, beacon)
- `standards/audit.md` : exception SEO/AIO/Growth déléguée aux agents spécialistes
- `templates/AGENTS.md` : exception SEO/AIO/Growth dans le Mode AUDIT

## 2026-08-09

- Portabilité complète du repo : `git clone + setup.sh` reproduit toute la config
- `config/` créé : `opencode.json` (secrets → `{env:...}`), `oh-my-opencode-slim.json`, `package.json`, `plugins/rtk.ts`, `.env.example`
- `scripts/setup.sh` : installation interactive (prérequis, opencode-ai, rtk, MCP, secrets, vérification)
- `scripts/install.sh` : tracking `new/updated/unchanged`, `--no-config`, `--prune`, `--dry-run`
- `standards/delegation-failure.md` : procédure obligatoire après échec de sous-agent
- Optimisation modèles par agent (oracle → Qwen 397B, explorer/librarian → Ministral-3, etc.)
- `aurora-heavy.md` ajouté au repo

## 2026-08-06

- Délégation sous-agents : Spark (commit/MR, `mode: all`) + Vision (multimodal)
- `agents/aurora.md` : section "Délégation aux sous-agents" (Spark par défaut + fallback, Vision obligatoire pour images)
- `agents/spark.md` : permissions bash complétées pour `create-mr` + `skill: allow`

## 2026-06-28

- Correction des 7 findings de l'audit read-only (install.sh --prune, sync-project.sh .new horodatés, template générique, etc.)
- Analyse et intégration adaptée des recommandations AIDD (audit read-only, artifact-authoring, review en axes, lifecycle PLAN.md, capacités prouvées INDEX.md)
- Ajout des fichiers `docs/ai/` manquants : `PLAN.md`, `INDEX.md`, `WARNINGS.md`, `DECISIONS.md`

## 2026-06-09

- Intégration Claude Code best practices : 4 nouveaux standards (review-before-done, exploration-limits, error-correction, anti-patterns)
- Workflow enrichi : ajout étape REVIEW (6 étapes)
- AGENTS.md (global + template) : 4 nouvelles obligations de comportement
- Renommage `memory.md` → `memory-session-flow.md` pour lever l'ambiguïté

## 2026-06-05

- Restructuration complète du repository.
- Création des dossiers `agents/`, `templates/`, `examples/`, `scripts/`, `docs/`.
- Renommage des agents : `angular-20-infomaniak.md`, `reviewer.md`, `tester.md`, `architect.md`.
- Ajout de l'agent `security.md` pour les revues de code sécurité.
- Ajout de la documentation `docs/` (angular-20, code-review, testing, architecture).
- Ajout des exemples `angular-app`, `node-api`, `monorepo`.
- Installation multi-couches documentée dans le README.
- Scripts `install.sh`, `init-project.sh`, `sync-project.sh` adaptés à la nouvelle structure.
