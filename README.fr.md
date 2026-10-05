<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/aurora-logo-without-name-dark.png">
    <img src=".github/assets/aurora-logo-without-name.png" width="300" alt="Logo Aurora">
  </picture>

  <h1>Aurora</h1>

  [![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE) [![Last Commit](https://img.shields.io/github/last-commit/himuraxp/aurora-ai.svg)](https://github.com/himuraxp/aurora-ai/commits/main) [![OpenCode Compatible](https://img.shields.io/badge/OpenCode-Compatible-brightgreen.svg)](https://opencode.ai)

  > **Un setup OpenCode prêt pour la production, multi-agents — Angular, Node.js, NestJS, Astro.**

  Forkable. Extensible. Prête à l'emploi.

  [English](README.md) · **Français**
</div>

> Si Aurora vous est utile, pensez à laisser une star au dépôt ⭐ — cela aide d'autres développeurs à le trouver.

---

## Pourquoi Aurora ?

Les agents IA (OpenCode, Cursor, Claude...) ne savent pas quel standard utiliser à moins que vous le leur disiez — et ils peuvent perdre le contexte du projet entre deux sessions. **Aurora** transforme OpenCode en équipe d'ingénierie orchestrée et auto-documentée.

**Ce que vous obtenez :**

- **18 agents spécialisés + 4 agents plugin** — rôles ingénierie (reviewer, tester, security, architect, designer...) et équipe Search & Growth
- **16 standards universels + 33 skills** — review adversariale, vérification, commits, et la suite accessibilité de 17 sous-skills
- **Mémoire projet persistante** — 7 documents `docs/ai/` lus automatiquement en début de session : les agents gardent le contexte entre les sessions
- **14 modèles avec fallback automatique** — contexte 250k → 1M, assignation des agents par coût
- **Cohérent entre machines** — même setup et même comportement partout, avec des exemples prêts à l'emploi (Angular, API Node.js, monorepo)

→ [Quick Start](#quick-start) — opérationnel en quelques minutes.

## Quick Start

### 1. Installer (première fois)

```bash
git clone https://github.com/himuraxp/aurora-ai.git ~/.config/opencode-config
cd ~/.config/opencode-config
npm run setup
```

> Équivalent bash : `~/.config/opencode-config/scripts/setup.sh`

`setup.sh` est interactif : vérifie les prérequis (Node.js 18+, npm), installe ou met à jour `opencode-ai` (npm global) et `rtk` (Homebrew sur macOS), propose les MCP servers, copie agents, standards, frameworks et fichiers de config, et demande interactivement les variables d'environnement (clé API, endpoints).

> Les secrets vivent dans `~/.config/opencode/.env` (permissions 600, jamais versionné) et dans un **bloc managé** idempotent de votre shell rc — la clé API n'existe jamais en deux copies. Détails dans [Configuration](#configuration).

Si `.env` existe déjà avec les variables requises, l'étape de configuration est ignorée. Pour reconfigurer : `npm run setup -- --force`.

### 2. Mettre à jour (modifications ultérieures)

```bash
cd ~/.config/opencode-config
git pull
npm run update
```

> Équivalent bash : `./scripts/install.sh`

`install.sh` affiche pour chaque fichier s'il est `new`, `updated` ou `unchanged` et ne réécrit que les fichiers modifiés. Options :

```bash
npm run setup             # mise à jour complète (config + dépendances + vérifications)
npm run prune             # nettoyer les fichiers orphelins après renommages/suppressions
npm run update -- --no-config   # mettre à jour sans toucher à opencode.json / plugins
```

### 3. Initialiser un projet

```bash
cd mon-projet
~/.config/opencode-config/scripts/init-project.sh
# prévisualiser sans rien modifier : ajouter --dry-run
```

Résultat :

```txt
mon-projet/
├── AGENTS.md
└── docs/
    └── ai/
        ├── PLAN.md       → plan technique courant
        ├── STATUS.md     → état d'avancement
        ├── DECISIONS.md  → décisions structurantes
        ├── CHANGELOG.md  → historique des sessions
        ├── BUFFER.md     → mémoire tampon de session
        ├── INDEX.md      → cartographie du projet
        └── WARNINGS.md   → alertes et dettes techniques
```

### 4. Synchroniser les templates d'un projet existant

```bash
~/.config/opencode-config/scripts/sync-project.sh
# prévisualiser sans rien modifier : ajouter --dry-run
```

N'écrase jamais les fichiers existants : il crée des fichiers `.new` (ou horodatés) à fusionner manuellement.

**Opérationnel en quelques minutes.**

## Sommaire

- [Pourquoi Aurora ?](#pourquoi-aurora-)
- [Quick Start](#quick-start)
- [Agent State Layer](#agent-state-layer)
- [Configuration](#configuration)
- [Modèles et Fallback](#modèles-et-fallback)
- [Mémoire projet](#mémoire-projet)
- [Architecture](#architecture)
- [Comment l'utiliser ?](#comment-lutiliser-)
- [Comment personnaliser ?](#comment-personnaliser-)
- [Documentation](#documentation)
- [FAQ](#faq)
- [Structure du repo](#structure-du-repo)
- [Principe de priorité](#principe-de-priorité)

---

## Agent State Layer

Les agents IA perdent le contexte à chaque nouvelle session. Ce repository résout ce problème avec une couche de mémoire persistante :

| Document | Problème résolu |
|----------|----------------|
| **BUFFER.md** | Interruptions de session — snapshot de reprise |
| **INDEX.md** | Lectures inutiles — cartographie du projet en un coup d'œil |
| **WARNINGS.md** | Régressions — alertes actives avant tout changement |
| **STATUS.md** | Continuité — état d'avancement entre sessions |
| **PLAN.md** | Direction — plan technique courant |
| **DECISIONS.md** | Traçabilité — décisions structurantes justifiées |

Cycle de session (mis à jour avec l'étape REVIEW) :

```txt
EXPLORER → PLANIFIER → IMPLÉMENTER → [REVIEW] → VÉRIFIER → COMMITTER
```

Avec l'étape **REVIEW** (examen contradictoire) obligatoire avant de considérer une tâche comme terminée.

---

## Configuration

### Variables d'environnement

OpenCode ne charge **pas** les fichiers `.env` : les références `{env:...}` de
`opencode.json` lisent uniquement l'environnement du shell. D'où deux emplacements :

- **Shell rc (bloc managé par `setup.sh`)** : la clé API Infomaniak AI (**seule
  copie**) et les valeurs `IDB_*` du MCP iOS, qui ne lit que son environnement
  process (pas de fallback `.env`). Le bloc est idempotent : les exports
  préexistants de ces variables sont déplacés dans le bloc, jamais dupliqués.
- **`~/.config/opencode/.env`** : les variables lues directement par les MCP
  servers et les outils (fallback interne dans leur code).

| Variable | Emplacement | Usage | Requis |
|----------|-------------|-------|--------|
| `OPENAI_API_KEY_INFOMANIAK` | shell rc (bloc managé) | Clé API Infomaniak AI | Oui |
| `IDB_UDID` | shell rc (bloc managé) | UDID simulateur iOS (MCP ios-simulator) | Non |
| `IDB_PATH` | shell rc (bloc managé) | Chemin binaires idb (MCP ios-simulator) | Non |
| `INFOMANIAK_API_TOKEN` | `.env` | Token API Infomaniak (MCP infomaniak — fallback `.env`) | Non |
| `GITLAB_TOKEN` | shell rc ou `.env` | Token GitLab (MCP angular-elements — fallback `.env`) | Non |
| `FIGMA_TOKEN` | `.env` | Token API Figma (skill `figma-ds-sync` — sync design system) | Non |

`setup.sh` demande ces valeurs interactivement. Pour les variables du `.env`
(`INFOMANIAK_API_TOKEN`, `FIGMA_TOKEN`, ...), éditez `~/.config/opencode/.env`
directement. Pour la clé et les valeurs `IDB_*`, utilisez `setup.sh --force`
(Enter pour garder, nouvelle valeur pour remplacer) — ou éditez le bloc managé
du shell rc.

### MCP Servers

La configuration inclut six MCP servers dans `opencode.json` :

| MCP Server | Rôle | Installation |
|------------|------|-------------|
| `chrome-devtools` | Navigation, screenshots, audit Lighthouse, debug Chrome (navigateur headless isolé) | Auto-installé via `npx` au premier lancement |
| `browser-debug` | Se connecte à un navigateur en mode debug (`http://127.0.0.1:9222`) — utilisé par le skill `ai-cowork` (Aurora ↔ ChatGPT) | Auto-installé via `npx` ; nécessite un navigateur lancé en mode debug (voir ci-dessous) |
| `ios-simulator` | Interaction avec le simulateur iOS (tap, swipe, screenshots, UI tree) | Optionnel — nécessite `idb-companion` + `fb-idb` |
| `context7` | Documentation à jour des librairies et frameworks | Auto-installé via `npx` |
| `infomaniak` | API Infomaniak — radio, VOD, newsletter, DNS, events, AI | Local (voir `mcp/infomaniak/README.md`) |
| `angular-elements` | Design system Angular Elements — composants, API, stories | Local (voir `mcp/angular-elements/README.md`) |

#### chrome-devtools-mcp

Aucune installation manuelle nécessaire. Le package `chrome-devtools-mcp` est téléchargé automatiquement par `npx` au premier appel.

Deux instances coexistent (tools préfixés par le nom du serveur) :
- `chrome-devtools_*` — headless isolé (Designer, audits)
- `browser-debug_*` — connecté à `http://127.0.0.1:9222` (skill `ai-cowork`)

Pour le mode debug (session navigateur persistante, login ChatGPT conservé) :

```bash
"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/opencode/brave-debug-profile"
```

> Le `--user-data-dir` dédié est **obligatoire** (Chromium ≥136 ignore `--remote-debugging-port` sur le profil par défaut).

#### ios-simulator-mcp (macOS uniquement)

Ce MCP nécessite 3 dépendances externes :

| Dépendance | Installation |
|------------|-------------|
| Xcode | App Store (nécessaire pour `xcrun simctl`) |
| `idb-companion` | `brew tap facebook/fb && brew install idb-companion` |
| `fb-idb` | `python3 -m venv ~/.local/idb-venv && ~/.local/idb-venv/bin/pip install fb-idb` |

`setup.sh` propose d'installer ces dépendances automatiquement. Si vous refusez ou si vous êtes sur Linux, le MCP reste configuré dans `opencode.json` mais plantera au runtime — vous pouvez le désactiver en passant `"enabled": false`.

Variables d'environnement associées (shell rc, bloc managé par `setup.sh` — le
MCP ios-simulator ne lit pas `.env`) :

| Variable | Usage |
|----------|-------|
| `IDB_UDID` | UDID du simulateur iOS cible (auto-détecté par `setup.sh`) |
| `IDB_PATH` | Chemin vers les binaires `idb` (défaut: `~/.local/idb-venv/bin:...`) |

### Ce qui est installé

```txt
~/.config/opencode/
├── agents/                    # Personnalités IA
├── standards/                 # Comportements universels
├── frameworks/                # Règles par stack technique
├── opencode.json              # Config principale (providers, models, permissions, MCP)
├── oh-my-opencode-slim.json   # Presets sous-agents
├── package.json               # Dépendances plugins
├── plugins/
│   └── rtk.ts                 # Plugin RTK (token savings)
├── .env                       # Secrets (jamais versionné)
└── .env.example               # Template des variables d'environnement
```

---

## Modèles et Fallback

### 14 modèles configurés

La configuration utilise **14 modèles** répartis en 6 catégories :

| Catégorie | Modèles | Context max | Coût (input/output) | Usage |
|-----------|---------|-------------|---------------------|-------|
| **Expert** | euria-code (GLM-5.2) | 250k | $0.60 / $3.00 | Raisonnement complexe, architecture, sécurité, review, code |
| | euria-code-tiny | 200k | $0.30 / $0.40 | Version légère d'euria-code, multimodal (image) |
| **Intermédiaire** | Mistral-Small-4 (119B) | 256k | $0.20 / $0.75 | Commits, skills CLI, SEO technique, content |
| | Kimi-K2.6 | 256k | $0.60 / $3.00 | Fallback gros contextes |
| | Qwen3.5-397B | 204k | $0.80 / $3.60 | Multimodal natif (image+video), disponible sur demande |
| | Qwen3.5-122B | 200k | $0.40 / $3.20 | Intermédiaire Qwen, output 100k |
| **Léger** | Ministral-3 (14B) | 80k | $0.30 / $0.40 | Modèle léger — réservé aux agents plugin `explorer`/`librarian` |
| | Gemma-4-31B | 100k | $0.20 / $0.40 | Tâches générales |
| | Apertus-70B | 100k | $0.70 / $2.50 | Tâches générales |
| **Ultra-léger** | **Nemotron-3-Nano (30B)** | **1M** | **$0.05 / $0.20** | **Fallback ultime, gros contextes** |
| **Embedding** | Qwen3-Embedding-8B | 32k | $0.01 / $0 | Vectorisation (recommandé) |
| | bge_multilingual_gemma2 | 8k | $0.01 / $0 | Multilingue FR/EN |
| | mini_lm_l12_v2 | 512 | $0.005 / $0 | Petits textes |
| **Transcription** | whisper | 448k | $0.006 / $0 | Audio → texte |

### Fallback automatique

Quand un prompt dépasse la limite de contexte d'un modèle, OpenCode bascule **automatiquement** vers un modèle avec plus de contexte. Chaînes notables :

```
Ministral-3 (80k)      → Mistral-Small-4 (256k) → Kimi-K2.6 → Nemotron-3-Nano (1M)
euria-code (250k)      → Kimi-K2.6 (256k)       → Nemotron-3-Nano (1M)
Gemma-4 (100k)         → Mistral-Small-4 (256k) → Kimi-K2.6 → Nemotron-3-Nano (1M)
Qwen3.5-397B (204k)    → Kimi-K2.6 (256k)       → Nemotron-3-Nano (1M)
```

> **Avantage** : Le fallback ultime (Nemotron-3-Nano) est le modèle **le moins cher** ($0.05/1M tokens). Les très gros contextes coûtent en fait *moins* cher.

### Assignation des agents

| Agent | Modèle | Pourquoi |
|-------|--------|----------|
| `aurora`, `architect`, `security`, `cybersec`, `reviewer`, `atlas`, `sage`, `mobile`, `tester`, `beacon`, `crawler`, `build`, `plan` | euria-code (GLM-5.2) | Raisonnement expert, code, sécurité, long-context 1M natif |
| `aurora-heavy`, `designer`, `vision` | Qwen3.5-397B | Multimodal natif (image+video), analyse de screenshots et mockups |
| `echo`, `scribe`, `pulse` | Mistral-Small-4 (119B) | Bon équilibre coût/performance/créativité |
| `spark` | Mistral-Small-4 (119B) | Commits, skills CLI — 256k contexte évite la boucle de compaction |
| `oracle` (plugin) | euria-code (variant high) | Conseil stratégique, review adversariale |
| `fixer` (plugin) | Qwen3.5-122B | Exécution rapide de spec |
| `explorer`, `librarian` (plugin) | Ministral-3 (14B) | Recherche rapide codebase / docs externes |

---

## Mémoire projet

Aurora détecte automatiquement le dossier `docs/ai/` à la racine du projet dès le début de chaque session.

### Lecture automatique au bootstrap

Si `docs/ai/` existe, Aurora charge immédiatement :

1. `STATUS.md` — état actuel, bloqueurs, prochaine étape
2. `PLAN.md` — plan technique en cours
3. `WARNINGS.md` — alertes actives et zones à risque
4. `INDEX.md` — cartographie du projet

### Lecture conditionnelle

- **BUFFER.md** : chargé uniquement en cas de reprise de session interrompue, de blocage signalé dans `STATUS.md`, ou si l'utilisateur demande explicitement de reprendre une tâche.
- **DECISIONS.md** : consulté en JIT (Just-In-Time) si une décision structurante, une contradiction ou une refonte d'architecture est détectée.
- **CHANGELOG.md** : consulté en JIT si une régression est suspectée ou si l'utilisateur demande l'historique.

### Pourquoi les fichiers `.new` ne sont pas lus

Lors d'une synchronisation (`sync-project.sh`), les fichiers existants ne sont pas écrasés. Le script génère des fichiers `.new` comme propositions de mise à jour, ou `.new.YYYYMMDD-HHMMSS` si une proposition existe déjà.
**OpenCode ne lit jamais les fichiers `.new` automatiquement.** Ils doivent être fusionnés manuellement dans les fichiers officiels.

### Checklist d'adoption sur un projet existant

Pour adopter la mémoire projet sur un projet existant possédant déjà `docs/ai/` :

1. Lancer `init-project.sh` dans le projet existant.
2. Vérifier les fichiers créés dans `docs/ai/`.
3. Comparer les éventuels fichiers `.new` générés.
4. Fusionner manuellement les sections utiles.
5. Supprimer les `.new` une fois traités.
6. Lancer OpenCode avec Aurora.
7. Vérifier qu'Aurora annonce la mémoire projet détectée.

---

## Architecture

```txt
Global Configuration
        ↓
     Standards    (workflow, memory-session-flow, memory-auto-update, memory-checklist, verification, communication, escalation, commits, review-before-done, audit, exploration-limits, error-correction, anti-patterns, artifact-authoring, delegation-failure, agent-output)
        ↓
          Agents       (aurora, aurora-heavy, reviewer, tester, security, cybersec, architect, spark, vision, atlas, crawler, sage, scribe, pulse, echo, beacon, designer, mobile) + plugin (explorer, fixer, librarian, oracle)
        ↓
    Frameworks     (angular-20, nodejs, nestjs, astro...)
        ↓
 Project AGENTS.md (source de vérité locale)
        ↓
   Project Docs    (PLAN, STATUS, DECISIONS, CHANGELOG, BUFFER, INDEX, WARNINGS)
```

**Standards** : comportements universels applicables à tout projet.
**Agents** : personnalités spécialisées pour des tâches spécifiques.
**Frameworks** : règles techniques par stack (Angular, Node.js, NestJS, Astro).
**Project AGENTS.md** : source de vérité ultime, le local l'emporte toujours.
**Project Docs** : mémoire persistante de session entre les conversations IA.

---

## Comment l'utiliser ?

Après installation, l'agent Aurora (principal) charge automatiquement :

```txt
1. Standards globaux (workflow, communication, verification...)
2. Agents globaux (aurora, aurora-heavy, reviewer, tester, security, cybersec, architect, spark, vision, atlas, crawler, sage, scribe, pulse, echo, beacon, designer, mobile) + agents du plugin (explorer, fixer, librarian, oracle)
3. Framework ciblé (Angular 20+, Node.js, etc.)
4. Standards entreprise (si configurés)
5. AGENTS.md local + docs/ai/
```

La règle d'or : **le local l'emporte toujours**. `AGENTS.md` à la racine du projet est la source de vérité ultime.

---

## Comment personnaliser ?

### Personnaliser les agents

Modifiez les fichiers dans le repo cloné, puis relancez `npm run update` (ou `./scripts/install.sh`).

Les agents disponibles sont dans `agents/` :

| Agent | Rôle |
|-------|------|
| `aurora.md` | Agent principal — chargement et coordination |
| `aurora-heavy.md` | Agent pour tâches complexes (euria-code) |
| `reviewer.md` | Code review stricte |
| `tester.md` | Tests qualité |
| `security.md` | Cybersécurité défensive — AppSec, threat modeling, secure code review, DevSecOps, hardening |
| `cybersec.md` | Cybersécurité offensive — pentest, Red Team, exploitation, recon, bypass, privesc |
| `architect.md` | Découpage technique |
| `spark.md` | Sous-agent léger (commit, MR) |
| `vision.md` | Sous-agent multimodal (images, screenshots) |
| `atlas.md` | SEO Strategy — stratégie, keyword research, content gaps |
| `crawler.md` | Technical SEO — audit et correction SEO technique |
| `sage.md` | AIO / GEO — optimisation pour moteurs de recherche génératifs |
| `scribe.md` | SEO Content — production et optimisation éditoriale |
| `pulse.md` | Growth Marketing — acquisition, conversion, funnel |
| `echo.md` | Social Distribution — distribution multi-canal |
| `beacon.md` | Analytics — mesure SEO et marketing |
| `designer.md` | UX/UI Designer — conception d'interfaces, DA, design system, accessibilité (2 modes : autonome / DS Infomaniak) |
| `mobile.md` | Mobile Engineer — iOS, Android, React Native, Flutter |

> Agents **fournis par le plugin** `oh-my-opencode-slim` (config `config/oh-my-opencode-slim.json`) : `explorer` (recherche codebase), `fixer` (exécution rapide de spec), `librarian` (recherche docs externes), `oracle` (conseil technique stratégique, review adversariale).

### Ajouter un framework

Créez un fichier `frameworks/<mon-framework>.md` dans le repo :

```txt
frameworks/
├── angular-20.md   # Angular 20+ stand-alone
├── nodejs.md       # API Node.js / Express
├── nestjs.md       # Architecture modulaire NestJS
└── astro.md        # Sites statiques Astro, SEO, i18n
```

Le nom du fichier sera le nom du framework. Relancez `npm run update` (ou `./scripts/install.sh`) pour le déployer.

### Créer une nouvelle règle

1. Dans le repo `~/.config/opencode-config`
2. Créez un fichier dans `standards/` (universel) ou `agents/` (rôle spécialisé)
3. Relancez `npm run update` (ou `./scripts/install.sh`)
4. Référencez-le dans le `AGENTS.md` du projet concerné

### Personnaliser le workflow de session

Modifiez `standards/workflow.md` et `standards/memory-session-flow.md` pour adapter le cycle de travail et la gestion de la mémoire de session.

### Adapter la stack d'un projet

Le template `AGENTS.md` est volontairement générique. Ajoutez dans le `AGENTS.md` local les conventions de stack utiles, ou référencez un framework global :

- `frameworks/angular-20.md`
- `frameworks/nodejs.md`
- `frameworks/nestjs.md`
- `frameworks/astro.md`

---

## Documentation

| Guide | Contenu |
|-------|---------|
| [Workflow](docs/workflow.md) | Comment fonctionne le cycle de travail, étape par étape |
| [Customization](docs/customization.md) | Comment personnaliser et étendre (agents, standards, frameworks) |
| [Architecture](docs/architecture.md) | Comment s'articulent les couches de configuration |
| [Angular 20](docs/angular-20.md) | Règles Angular 20+ détaillées |
| [Code review](docs/code-review.md) | Guide de revue de code |
| [Testing](docs/testing.md) | Guide de tests |
| [Examples](examples/) | Projets prêts à l'emploi : app Angular, API Node, monorepo |

---

## FAQ

<details>
<summary><strong>Est-ce macOS uniquement ?</strong></summary>

La configuration est développée sur **macOS**. Le cœur (OpenCode, agents, standards, frameworks) est multi-plateforme (Node.js 18+). Deux parties spécifiques à macOS : `rtk` s'installe via Homebrew (installation manuelle sur Linux) et le MCP `ios-simulator` nécessite Xcode — passez `"enabled": false` pour ce MCP sous Linux.

</details>

<details>
<summary><strong>Où vont mes clés API et mes secrets ?</strong></summary>

Dans `~/.config/opencode/.env` (permissions 600, jamais versionné) pour les outils MCP, et dans le **bloc managé** de votre shell rc pour la clé API Infomaniak AI — jamais dans `opencode.json` et jamais commités. Voir [Configuration](#configuration).

</details>

<details>
<summary><strong>Comment vérifier mon installation ?</strong></summary>

```bash
npm run health-check     # cohérence de la config (JSON, agents, modèles)
npm run permissions      # matrice des permissions agents
npm run validate-memory  # structure docs/ai/ d'un projet
```

</details>

<details>
<summary><strong>Est-ce que ça marche avec Cursor ou Claude Code ?</strong></summary>

La mémoire projet (`docs/ai/`, `AGENTS.md`) et les conventions (standards, frameworks) sont agnostiques de l'agent et lisibles par n'importe quel outil IA. Les agents et skills eux-mêmes sont au format OpenCode.

</details>

<details>
<summary><strong>Le git push échoue avec `RPC failed, HTTP 400` sur des fichiers volumineux ?</strong></summary>

GitHub refuse les pushs avec un payload supérieur à 1 MiB (défaut `http.postBuffer`). Fix : `git config http.postBuffer 157286400`, puis re-push. Vérifiez toujours avec `git ls-remote origin main` — un message trompeur « Everything up-to-date » peut suivre un push échoué.

</details>

---

## Structure du repo

<details>
<summary><strong>Arborescence</strong></summary>

```txt
aurora-ai/
│
├── README.md
├── LICENSE
├── CHANGELOG.md
│
├── config/                     Config OpenCode (versionnée, sans secrets)
│   ├── opencode.json             Providers, models, permissions, MCP servers
│   ├── oh-my-opencode-slim.json  Presets sous-agents (euria-code)
│   ├── package.json              Dépendance @opencode-ai/plugin
│   ├── .env.example              Template des variables d'environnement
│   └── plugins/
│       └── rtk.ts                Plugin RTK (token savings via rtk rewrite)
│
├── standards/               Comportements universels
│   ├── workflow.md            Cycle Explorer→Planifier→Implémenter→[PARALLEL GATE]→Committer
│   ├── error-correction.md    Arrêt après 2 échecs pour éviter la spirale
│   ├── anti-patterns.md       Stopper les 5 patterns de session types
│   ├── artifact-authoring.md  Créer standards/agents/frameworks sans doublons
│   ├── delegation-failure.md  Procédure obligatoire après échec de sous-agent
│   ├── agent-output.md        Format de retour JSON structuré pour les sous-agents
│   ├── audit.md               Audit read-only multi-axes
│   ├── review-before-done.md  Examen contradictoire avant déclaration de fin
│   ├── exploration-limits.md  Exploration ciblée et subagents
│   ├── memory-session-flow.md     Ordre de lecture automatique des docs/ai/ en début de session
│   ├── memory-checklist.md        Checklist mémoire en fin de session
│   ├── memory-auto-update.md      Standard de persistance mémoire
│   ├── verification.md            Vérifications build/lint/test obligatoires
│   ├── communication.md           Franchise, ownership, pushback
│   ├── escalation.md              Gestion des blocages
│   └── commits.md                 Format et règles de commit
│
├── agents/                  18 définitions d'agents — voir Comment personnaliser
│
├── frameworks/                Règles par stack technique
│   ├── angular-20.md          Conventions Angular 20+ stand-alone
│   ├── nodejs.md              Conventions Node.js API
│   ├── nestjs.md              Conventions NestJS
│   └── astro.md               Conventions Astro
│
├── templates/                 Ce que chaque projet reçoit
│   ├── AGENTS.md              Template racine pour chaque projet
│   ├── PLAN.md                Plan technique courant
│   ├── STATUS.md              État d'avancement
│   ├── DECISIONS.md           Décisions structurantes
│   ├── CHANGELOG.md           Journal des agents
│   └── project-docs/
│       ├── BUFFER.md          Mémoire tampon de session
│       ├── INDEX.md           Cartographie du projet
│       └── WARNINGS.md        Alertes et dettes techniques
│
├── examples/                  Exemples prêts à l'emploi
│   ├── angular-app/           Projet Angular 20+ complet (AGENTS.md + docs/ai/)
│   ├── node-api/              Projet API Node.js (AGENTS.md + README)
│   └── monorepo/              Monorepo multi-packages (AGENTS.md + README)
│
├── mcp/                       MCP servers locaux
│   ├── infomaniak/            API Infomaniak (radio, VOD, newsletter, DNS, events, AI)
│   └── angular-elements/      Design system Angular Elements (composants, API, stories)
│
├── tools/                     CLIs d'infrastructure (repo, pas installés comme agents)
│   └── figma-ds/              CLI de sync du design system Figma Infomaniak
│       ├── src/               TypeScript strict (check / sync / diff / mapping)
│       ├── tests/             Suite node:test (53 tests)
│       └── *-reference.json   Références manuelles (familles Figma, composants ik-*)
│
├── skills/                    Skills réutilisables
│   ├── accessibility/         Suite accessibilité (17 sous-skills orchestrés : aria, contraste, focus, clavier, formulaires…)
│   ├── ai-cowork/             Co-working Aurora ↔ ChatGPT (boucle de review autonome via browser-debug)
│   ├── allow-command/         Pré-approuver des commandes shell dans opencode.json
│   ├── clonedeps/             Cloner les sources des dépendances pour inspecter les internals des librairies
│   ├── code-review/           Review adversariale de code
│   ├── codemap/               Cartes de code hiérarchiques pour repos inconnus
│   ├── commit/                Messages de commit (conventions Infomaniak)
│   ├── create-mr/             Création de merge requests (scripts + tests)
│   ├── deepwork/              Workflow orchestré multi-phases avec gates de review (chantiers lourds)
│   ├── deployment-changelog/  Changelog de déploiement
│   ├── figma-ds-sync/         Sync du design system Figma Infomaniak (check/sync/diff/mapping)
│   ├── gitlab-ci/             Interaction GitLab CI/CD (glab)
│   ├── gitlab-feature-planner/  Issues GitLab depuis un tableau d'estimation + suggestions de regroupement MR
│   ├── gitlab-issues/         Gestion des issues GitLab (glab)
│   ├── gitlab-summary/        Résumé d'activité GitLab
│   ├── image-transparent-background/  Suppression de fond blanc (ImageMagick)
│   ├── laravel-cruddy-by-design/  Contrôleurs/routes Laravel RESTful stricts (max 7 méthodes)
│   ├── loop-engineering/      Runtime Grill + Monitor pour boucles d'ingénierie
│   ├── mr-review/             Review de MR avec commentaires inline
│   ├── mr-review-feedback/    Application des retours de review MR
│   ├── new-worktree/          Branche + worktree en une intention (jamais destructif)
│   ├── oh-my-opencode-slim/   Configuration et tuning du plugin oh-my-opencode-slim
│   ├── pre-mr-review/         Revue qualité pré-MR
│   ├── radio-tag-genres/      Tagging de genres musicaux pour playlists radio
│   ├── readme/                 Génération de README
│   ├── reflect/               Analyse des sessions passées → skills/config réutilisables
│   ├── release-smoke-test/    Validation de release oh-my-opencode-slim
│   ├── review-gap-analyzer/   Retours de revue → amélioration des règles AGENTS.md/pre-mr-review
│   ├── simplify/              Simplification de code sans changement de comportement
│   ├── translate-doc/         Traduction de documentation
│   ├── user-stories/          Rédaction de user stories
│   ├── verification-planning/ Plan de vérification avant changement de code non trivial
│   └── worktrees/             Worktrees Git comme lanes isolées (protocole OMO)
│
├── scripts/                   Automatisation
│   ├── setup.sh                Installation complète (première fois, interactive)
│   ├── install.sh              Installer/mettre à jour la config globale
│   ├── init-project.sh         Initialiser un nouveau projet (auto-détection stack)
│   ├── sync-project.sh         Synchroniser les templates
│   ├── health-check.sh         Vérifier la cohérence de la config (JSON, agents, modèles)
│   ├── permissions-matrix.sh   Générer un tableau des permissions agents
│   ├── validate-memory.sh     Valider la structure docs/ai/ d'un projet
│   ├── create-mr/              Scripts de création de MR (build_body, check_workspace, detect_target_branch, detect_template, push_branch, tests, upload_media, validate_title)
│   └── hooks/
│       └── pre-commit-secrets.sh  Hook git anti-fuite de secrets
│
└── docs/                      Guides utilisateur
    ├── ai/                   Mémoire projet du repo (PLAN, STATUS, DECISIONS, CHANGELOG, BUFFER, INDEX, WARNINGS)
    ├── workflow.md            Comment fonctionne le cycle de travail
    ├── customization.md        Comment personnaliser et étendre
    ├── angular-20.md          Règles Angular 20+ détaillées
    ├── code-review.md         Guide de revue de code
    ├── testing.md             Guide de tests
    └── architecture.md        Guide architectural
```

</details>

---

## Principe de priorité

L'agent reçoit et applique dans cet ordre (du plus général au plus spécifique, le plus spécifique l'emporte) :

1. **Standards** globaux `~/.config/opencode/standards/` (workflow, memory-session-flow, memory-auto-update, memory-checklist, verification, communication, escalation, commits, review-before-done, audit, exploration-limits, error-correction, anti-patterns, artifact-authoring, delegation-failure, agent-output).
2. **Agents** globaux `~/.config/opencode/agents/` (aurora, aurora-heavy, reviewer, tester, security, cybersec, architect, spark, vision, atlas, crawler, sage, scribe, pulse, echo, beacon, designer, mobile) + agents du plugin oh-my-opencode-slim (explorer, fixer, librarian, oracle).
3. **Frameworks** globaux `~/.config/opencode/frameworks/` (angular-20, nodejs, nestjs, astro).
4. Standards entreprise (si configurés).
5. **`AGENTS.md`** local du projet.
6. Instructions explicites de la tâche en cours.

---

## Licence

MIT
