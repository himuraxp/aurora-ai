# Create MR — Skill global OpenCode

Création automatique de merge requests GitLab suivant les conventions
Infomaniak. Zéro interaction humaine : l'agent génère le titre et la
description depuis l'analyse des commits et du diff.

## Installation

Ce skill est installé globalement dans la configuration OpenCode de
l'utilisateur :

```bash
OPENCODE_GLOBAL_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
```

Vérifier le chemin global réellement chargé :

```bash
ls -la "${OPENCODE_GLOBAL_DIR}/skills/create-mr/SKILL.md"
ls -la "${OPENCODE_GLOBAL_DIR}/scripts/create-mr/"*.sh
```

## Prérequis

### glab

```bash
# Installation (macOS)
brew install glab

# Authentification (hostname = votre instance GitLab, ex. gitlab.example.com)
glab auth login --hostname <votre-host-gitlab>

# Vérification
glab auth status
```

## Composants

| Composant | Chemin |
|-----------|--------|
| Skill | `skills/create-mr/SKILL.md` |
| Scripts | `scripts/create-mr/*.sh` |
| Tests | `scripts/create-mr/tests/test_all.sh` |

## Scripts

| Script | Description |
|--------|-------------|
| `check_workspace.sh` | Vérifie workspace propre + branche feature |
| `detect_target_branch.sh` | Détecte la branche cible (`--branch <name>` ou auto) |
| `detect_template.sh` | Cherche un template MR dans le dépôt |
| `validate_title.sh` | Valide le format Conventional Commit |
| `build_body.sh` | Assemble le body depuis template ou format défaut |
| `upload_media.sh` | Upload fichiers média vers GitLab |
| `push_branch.sh` | Push la branche si commits non pushés |
| `create_mr.sh` | Crée la MR via `glab mr create` (`--dry-run` supporté) |

## Variables de configuration

| Variable | Défaut | Description |
|----------|--------|-------------|
| `CREATE_MR_DRY_RUN` | `false` | Mode lecture seule |
| `CREATE_MR_DEFAULT_SCOPE` | `""` | Scope par défaut |

## Cycle de création

1. `check_workspace.sh` → workspace propre + branche feature
2. `detect_target_branch.sh` → branche cible détectée
3. Analyser commits + diff → comprendre le scope
4. `detect_template.sh` → template trouvé ?
5. Générer titre (EN, Conventional Commit) depuis l'analyse
6. Générer description (FR) depuis l'analyse
7. `build_body.sh` → assemblage final
8. `validate_title.sh` → format valide ?
9. `upload_media.sh` → upload média (optionnel)
10. `push_branch.sh` → push si nécessaire
11. `create_mr.sh` → création de la MR
12. Nettoyage

## Dry-run

```bash
# Mode lecture seule : affiche la MR sans la créer
CREATE_MR_DRY_RUN=true
```

Ou passer `--dry-run` à `create_mr.sh` directement.

## Sécurité

- Aucun commit automatique (les commits sont gérés par le skill `commit`).
- Aucun push forcé.
- Les scripts ne contiennent jamais `git commit` ou `git push --force`.
- La description est lue depuis un fichier pour éviter les problèmes d'échappement.
- Le titre est validé en format Conventional Commit avant création.

## Tests

```bash
bash "${OPENCODE_GLOBAL_DIR}/scripts/create-mr/tests/test_all.sh"
```

57 cas de test. N'appelle jamais un vrai projet GitLab.

## Règles de langue

| Élément | Langue | Format |
|---------|--------|--------|
| Titre MR | Anglais | Conventional Commit : `<type>(<scope>): <description>` |
| Description MR | Français | Template du projet ou format par défaut |

## Mise à jour

Les fichiers globaux peuvent être mis à jour sans impacter le dépôt courant.

```bash
# Vérifier l'installation
ls -la "${OPENCODE_GLOBAL_DIR}/skills/create-mr/SKILL.md"
ls -la "${OPENCODE_GLOBAL_DIR}/scripts/create-mr/"*.sh

# Lancer les tests
bash "${OPENCODE_GLOBAL_DIR}/scripts/create-mr/tests/test_all.sh"
```
