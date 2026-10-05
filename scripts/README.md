# scripts/

Scripts d'installation, maintenance et automatisation pour opencode-config.

## Scripts

| Script | Usage | Description |
|--------|-------|-------------|
| `setup.sh` | `./scripts/setup.sh [--force] [--no-animation]` | Première installation sur une machine. Interactif : installe opencode-ai, rtk, MCP servers, copie la config, collecte les secrets |
| `install.sh` | `./scripts/install.sh [--prune] [--no-config] [--dry-run]` | Mise à jour. Copie uniquement les fichiers modifiés vers `~/.config/opencode/` |
| `init-project.sh` | `./scripts/init-project.sh [--dry-run]` | Initialise un projet : copie `AGENTS.md`, détecte la stack, ajoute le framework |
| `sync-project.sh` | `./scripts/sync-project.sh [--dry-run]` | Synchronise les templates d'un projet (crée `.new` si conflit) |
| `health-check.sh` | `./scripts/health-check.sh [--installed] [--quiet]` | Vérifie la cohérence : JSON valides, agents, modèles, orphelins |
| `permissions-matrix.sh` | `./scripts/permissions-matrix.sh [--output FILE]` | Génère un tableau markdown des permissions de tous les agents |
| `validate-memory.sh` | `./scripts/validate-memory.sh [PROJECT_DIR]` | Vérifie que `docs/ai/` est bien formé (fichiers requis, sections) |
| `ui.sh` | `source scripts/ui.sh` | Bibliothèque UI partagée (couleurs, animations, barres de progression) |

## Sous-dossiers

| Dossier | Description |
|---------|-------------|
| `create-mr/` | Scripts de création de merge requests (voir `create-mr/README.md`) |
| `hooks/` | Hooks Git (voir `hooks/README.md`) |

## Installation

### Première installation (nouvelle machine)

```bash
git clone https://github.com/himuraxp/aurora-ai.git ~/.config/opencode-config
cd ~/.config/opencode-config
npm run setup
# ou: ./scripts/setup.sh
```

### Mise à jour

```bash
cd ~/.config/opencode-config && git pull && npm run update
# ou: ./scripts/install.sh
```

### Initialiser un projet

```bash
cd /path/to/project
~/.config/opencode-config/scripts/init-project.sh
# ou depuis le repo: npm run init-project
```

### Commandes npm disponibles

| Commande | Script bash équivalent | Description |
|---------|------------------------|-------------|
| `npm run setup` | `scripts/setup.sh` | Installation complète interactive |
| `npm run update` | `scripts/install.sh` | Mise à jour des fichiers de config |
| `npm run prune` | `scripts/install.sh --prune` | Mise à jour + suppression des orphelins |
| `npm run dry-run` | `scripts/install.sh --dry-run` | Prévisualiser les changements |
| `npm run init-project` | `scripts/init-project.sh` | Initialiser un projet |
| `npm run sync` | `scripts/sync-project.sh` | Synchroniser les templates |
| `npm run health-check` | `scripts/health-check.sh` | Vérifier la cohérence |
| `npm run permissions` | `scripts/permissions-matrix.sh` | Générer la matrice de permissions |
| `npm run validate-memory` | `scripts/validate-memory.sh` | Valider docs/ai/ d'un projet |

> Les flags supplémentaires peuvent être passés via `--` : `npm run setup -- --force`

## Dépendances

- **Node.js** >= 18 (pour opencode-ai et MCP servers)
- **npm** (pour opencode-ai et plugins)
- **rtk** (optional, installé par setup.sh — économise des tokens via rewrite)
- **glab** (optional, pour les skills GitLab)
- **ImageMagick** (optional, pour le skill image-transparent-background)
- **idb-companion** + **fb-idb** (optional, macOS, pour iOS Simulator MCP)

## ui.sh — Bibliothèque UI partagée

Utilisée par `setup.sh` et `install.sh` pour les animations et couleurs. 100% bash, zéro dépendance externe. Compatible macOS (bash 3.2+) et Linux (bash 4+).

```bash
source "$(dirname "${BASH_SOURCE[0]}")/ui.sh"
ui_logo
ui_section "System Check"
ui_info "Checking prerequisites..."
ui_run "Installing opencode-ai" npm install -g opencode-ai
ui_ok "Done"
```
