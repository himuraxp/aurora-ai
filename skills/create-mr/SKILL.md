---
name: create-mr
description: Create merge requests following Infomaniak conventions. Use when opening MRs, writing MR descriptions, or preparing changes for review. Follows Infomaniak's code review guidelines.
---

# Create Merge Request

Create merge requests following Infomaniak's engineering practices.

**Requires**: Gitlab CLI (`glab`) authenticated and available.

## Nature

Ce skill est **global**. Il est installé dans la configuration globale de
l'utilisateur OpenCode et n'est jamais copié dans les dépôts.

## Composants

| Composant | Chemin global | Rôle |
|-----------|---------------|------|
| Skill | `skills/create-mr/SKILL.md` | Règles métier et cycle de création |
| Scripts | `scripts/create-mr/*.sh` | Parties déterministes (détection, validation, upload) |
| Tests | `scripts/create-mr/tests/test_all.sh` | 57 cas de test |

## Règles fondamentales

### 1. Aucune interaction humaine

Le skill génère le titre, le contexte et la solution **automatiquement** depuis
l'analyse des commits et du diff. Pas de `read -r`, pas de prompt interactif,
pas de question dans le chat. L'agent analyse et crée la MR en autonomie.

### 2. Global uniquement

Ce skill ne doit **jamais** créer ou modifier `.opencode/` dans le dépôt
courant. Tous les composants sont dans la configuration globale.

### 3. glab exclusivement

Toutes les interactions GitLab passent par le CLI `glab`. Interdictions
absolues : `curl`, `wget`, SDK GitLab, bibliothèque HTTP, token écrit dans un
fichier, token affiché dans les logs.

Vérification au démarrage :

```bash
command -v glab
glab auth status
```

### 4. Scripts ne commitent jamais

Les scripts globaux ne contiennent ni n'exécutent `git commit`, `git push`,
`git push --force`, `git push --force-with-lease`. Le push est géré par
`push_branch.sh` (action explicite). La création de MR est gérée par
`create_mr.sh` (action explicite après validation du workspace).

### 5. Titre en anglais, description en français

**⚠️ STRICT LANGUAGE RULES:**

- **MR TITLE**: Must be in **ENGLISH** in Conventional Commit format
  - Format: `<type>(<scope>): <description>`
  - Examples: `feat(auth): Add OAuth2 login`, `fix(api): Handle null response`
- **MR DESCRIPTION**: Must be in **FRENCH**
  - All content must be written in French
  - Context, Solution, Resources → all in French

**Languages must not be mixed in the description.**

## Variables de configuration

| Variable | Défaut | Description |
|----------|--------|-------------|
| `CREATE_MR_DRY_RUN` | `false` | Mode lecture seule : affiche la MR sans la créer |
| `CREATE_MR_DEFAULT_SCOPE` | `""` | Scope par défaut si non détectable |

## Scripts globaux

| Script | Description |
|--------|-------------|
| `check_workspace.sh` | Vérifie workspace propre + branche feature (pas main/master) |
| `detect_target_branch.sh` | Détecte la branche cible (défaut via glab ou `--branch <name>`) |
| `detect_template.sh` | Cherche un template MR dans le dépôt (7 localisations connues) |
| `validate_title.sh` | Valide le format Conventional Commit du titre |
| `build_body.sh` | Assemble le body depuis template + variables ou format défaut |
| `upload_media.sh` | Upload fichiers média vers GitLab, retourne le Markdown |
| `ensure_glab_token.sh` | Préflight : re-source un `GITLAB_TOKEN` frais depuis le disque si le token du process est périmé (401). À SOURCER (`source ... || exit 1`) dans le même shell que l'appel glab |
| `push_branch.sh` | Push la branche courante si commits non pushés |
| `create_mr.sh` | Crée la MR via `glab mr create` (ou dry-run) |

Tous les scripts :
- utilisent des chemins absolus (résolus via `BASH_SOURCE`) ;
- refusent de fonctionner hors d'un dépôt Git ;
- n'effectuent jamais `git commit` ou `git push --force` ;
- utilisent `git rev-parse --show-toplevel`.

## Prérequis

Avant de créer une MR, tous les changements doivent être commités. Si des
changements non commités existent, invoquer d'abord le skill `commit`.

```bash
# Vérifier les changements non commités
git status --porcelain
```

Si le résultat montre des changements non commités, invoquer le skill `commit`
avant de continuer.

### Étape 0 — Fraîcheur du token GitLab (obligatoire)

Le process opencode hérite de son environnement au démarrage de la session et
ne le recharge **jamais** : si le token a été tourné sur disque pendant la
session (source canonique `~/.config/opencode/.env`), le process garde l'ancien
et chaque appel glab échoue en 401 "Token is expired" — même si un token frais
existe. Ne **jamais** conclure "token expiré, re-authentifie-toi" sans avoir
exécuté le préflight.

Le shell de l'agent est réinitialisé entre chaque commande : le script doit être
**sourcé** dans le même appel que la commande glab qui en dépend.

```bash
# À SOURCER (l'export doit vivre dans le shell courant) — même tool call que create_mr.sh
source "${SCRIPTS_DIR}/ensure_glab_token.sh" || exit 1
bash "${SCRIPTS_DIR}/create_mr.sh" ...
```

Le script : (1) valide le token de l'environnement ; (2) sinon re-source le
premier token valide trouvé dans `~/.config/opencode/.env` puis `~/.zshrc` ;
(3) échoue avec la procédure de rotation si toutes les sources sont périmées.
Il n'affiche jamais de secret.

## Cycle de création

### 0. Assurer la fraîcheur du token

```bash
source "${SCRIPTS_DIR}/ensure_glab_token.sh" || exit 1
```

### 1. Vérifier le workspace

```bash
bash "${SCRIPTS_DIR}/check_workspace.sh"
```

Vérifie :
- Le workspace est propre (pas de changements non commités)
- La branche courante n'est pas `main`/`master`/`develop`

### 2. Détecter la branche cible

```bash
# Détecter automatiquement la branche par défaut
TARGET_BRANCH=$(bash "${SCRIPTS_DIR}/detect_target_branch.sh")

# OU spécifier explicitement
TARGET_BRANCH=$(bash "${SCRIPTS_DIR}/detect_target_branch.sh" --branch staging)
```

L'agent analyse le prompt utilisateur pour détecter une branche cible explicite :

| Format | Exemple |
|--------|---------|
| French | `"vers staging"`, `"cible feat/new-feature"` |
| English | `"to main"`, `"target develop"` |
| CLI | `"--target-branch branch-name"`, `"-b main"` |

Si aucune branche détectée → branche par défaut du dépôt via `glab repo view`.

L'agent analyse aussi le prompt utilisateur pour détecter des **références d'issues** :

| Mention dans le prompt | Référence insérée dans la description |
|------------------------|----------------------------------------|
| `#426` | `Related to #426` |
| `Related to #426` | `Related to #426` (verbatim) |
| `fixes #426`, `closes #426`, `resolves #426` | `Closes #426` |
| `refs RM-1234` | `Refs RM-1234` |

Les références détectées sont passées à `--resources` lors de l'assemblage du
body (étape 7), donc affichées dans la section `Ressources` de la description.
Utiliser `Closes`/`Fixes` **uniquement** si l'utilisateur demande la fermeture
de l'issue au merge.

### 3. Analyser les changements

```bash
# Voir tous les commits qui seront dans la MR
git log "$TARGET_BRANCH..HEAD" --oneline

# Voir le diff complet
git diff "$TARGET_BRANCH...HEAD"
```

L'agent comprend le scope et le but de tous les changements avant d'écrire la
description.

### 4. Détecter le template MR

```bash
TEMPLATE_CONTENT=$(bash "${SCRIPTS_DIR}/detect_template.sh")
```

Localisations connues (par priorité) :
1. `.gitlab/merge_request_templates/*.md`
2. `.gitlab/merge_request_template.md`
3. `.gitlab/MERGE_REQUEST_TEMPLATE.md`
4. `./MERGE_REQUEST_TEMPLATE.md`
5. `./MR_TEMPLATE.md`
6. `./PULL_REQUEST_TEMPLATE.md`
7. `.github/PULL_REQUEST_TEMPLATE.md`

Si un template est trouvé, le stocker pour l'étape 6.
Sinon, utiliser le format par défaut.

### 5. Générer le titre (anglais, Conventional Commit)

L'agent génère le titre automatiquement depuis l'analyse des commits :

1. Analyser le type de changement (feat, fix, refactor, etc.)
2. Déterminer le scope si applicable
3. Écrire une description courte à l'impératif en anglais

**Types valides:**

| Type | Usage |
|------|-------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Refactoring (no behavior change) |
| `perf` | Performance improvement |
| `docs` | Documentation only |
| `test` | Test additions or corrections |
| `build` | Build system or dependencies |
| `ci` | CI configuration |
| `chore` | Maintenance tasks |
| `style` | Code formatting |
| `meta` | Repository metadata |
| `license` | License changes |

**Valider le titre:**

```bash
bash "${SCRIPTS_DIR}/validate_title.sh "$MR_TITLE"
```

### 6. Générer la description (français)

L'agent génère automatiquement depuis l'analyse du diff :

#### Contexte (en français)

- Quelle fonctionnalité/bug/fix cette MR adresse-t-elle ?
- Pourquoi ces changements sont-ils nécessaires ?
- Quel problème résolvent-ils ?

#### Solution (en français)

- Qu'a-t-on implémenté/modifié ?
- Comment cela fonctionne-t-il ?
- Décisions techniques clés

### 7. Assembler le body

```bash
# Si un template a été trouvé
bash "${SCRIPTS_DIR}/build_body.sh \
  --context "$CONTEXT" \
  --solution "$SOLUTION" \
  --resources "$RESOURCES" \
  --media "$MEDIA_MARKDOWN" \
  --template-file "$TEMPLATE_FILE" > "$BODY_FILE"

# Si pas de template (format par défaut)
bash "${SCRIPTS_DIR}/build_body.sh \
  --context "$CONTEXT" \
  --solution "$SOLUTION" \
  --resources "$RESOURCES" \
  --media "$MEDIA_MARKDOWN" > "$BODY_FILE"
```

Placeholders remplacés dans le template :
- `{{CONTEXT}}`, `{{SOLUTION}}`, `{{RESOURCES}}`, `{{MEDIA}}`
- `[]`, `Description de l'incrément ou du fix à insérer ici`
- `Description détaillée`, `Insérer les liens ici`, `Insérer les images ou vidéos ici`

Format par défaut si pas de template :

```markdown
## Contexte

${CONTEXT}

## Solution

${SOLUTION}

## Ressources

${RESOURCES}

## Media

${MEDIA}
```

### 8. Upload média (optionnel)

Si l'utilisateur a fourni des chemins de fichiers (images/vidéos) dans le prompt :

```bash
MEDIA_MARKDOWN=$(bash "${SCRIPTS_DIR}/upload_media.sh" "$FILE1" "$FILE2")
```

Chaque fichier est uploadé vers le projet GitLab et le Markdown retourné est
inséré dans la description.

### 9. Push la branche

```bash
bash "${SCRIPTS_DIR}/push_branch.sh"
```

Push les commits non pushés vers `origin/<current-branch>`. Ne fait rien si
déjà à jour.

### 10. Créer la MR

```bash
# Création réelle
bash "${SCRIPTS_DIR}/create_mr.sh \
  --target-branch "$TARGET_BRANCH" \
  --title "$MR_TITLE" \
  --body-file "$BODY_FILE"

# Mode dry-run (lecture seule)
bash "${SCRIPTS_DIR}/create_mr.sh \
  --target-branch "$TARGET_BRANCH" \
  --title "$MR_TITLE" \
  --body-file "$BODY_FILE" \
  --dry-run
```

La description est lue depuis un fichier pour éviter les problèmes d'échappement
shell avec les backticks, guillemets et caractères spéciaux.

### 11. Nettoyage

```bash
rm -f "$BODY_FILE"
```

## Conditions d'arrêt

- Workspace sale (changements non commités)
- Branche courante est `main`/`master`/`develop`
- Branche cible inexistante
- `glab` non disponible ou non authentifié (après préflight `ensure_glab_token.sh`)
- Titre invalide (Conventional Commit)
- Description trop courte (< 50 caractères)
- Push échoue
- `glab mr create` échoue

## Issue References

Reference issues in the MR body (French description):

| Syntax             | Effect                                  |
| ------------------ | --------------------------------------- |
| `Fixes #1234`      | Closes GitLab issue on merge            |
| `Closes #1234`     | Closes GitLab issue on merge            |
| `Resolves #1234`   | Closes GitLab issue on merge            |
| `Related to #1234` | Links issue without closing             |
| `Refs RM-1234`     | Link without closing                    |

## Editing Existing MRs

If you need to update an MR after creation:

```bash
# Update MR description (keep in French!)
# Write to temp file first to avoid JSON escaping issues
cat > ./mr-update.md << 'EOF'
New description in French here
EOF
glab mr update MR_NUMBER -d "$(cat ./mr-update.md)"
rm ./mr-update.md

# Update MR title (must remain in English!)
glab mr update MR_NUMBER -t 'feat(scope): updated description'

# Update both
cat > ./mr-update.md << 'EOF'
New description in French
EOF
glab mr update MR_NUMBER \
  -t 'feat(scope): new title' \
  -d "$(cat ./mr-update.md)"
rm ./mr-update.md
```

## Examples

### Example 1: Feature (Title in English, Description in French)

**Title (English):**

```
feat(notifications): add slack thread replies for alert updates
```

**Description (French):**

```markdown
## Contexte

Lorsqu'une alerte est mise à jour ou résolue, nous devons notifier les utilisateurs sans encombrer le canal Slack avec de nouveaux messages.

## Solution

Implémentation des réponses en thread Slack pour les mises à jour d'alertes. Au lieu de créer un nouveau message, nous postons une réponse dans le thread original de l'alerte. Cela regroupe les notifications liées et réduit le bruit dans le canal.

## Ressources

- https://trello.com/c/XXXXXX
```

### Example 2: Bug Fix

**Title (English):**

```
fix(api): handle null response in user endpoint
```

**Description (French):**

```markdown
## Contexte

L'endpoint utilisateur pouvait retourner null pour les comptes supprimés (soft-delete), provoquant des crashes dans le dashboard lors de l'accès aux propriétés utilisateur.

## Solution

Ajout d'une vérification null avant l'accès aux propriétés utilisateur. Retour d'une réponse 404 appropriée lorsque l'utilisateur n'existe pas.

## Ressources

- SENTRY-5678
```

## Guidelines

- **USE REPOSITORY TEMPLATE WHEN AVAILABLE** - Follow project conventions, fallback to default format if none
- **TITLE IN ENGLISH (Conventional Commit)** - Format: `<type>(<scope>): <description>`
- **DESCRIPTION IN FRENCH** - All content in French
- **One MR per feature/fix** - Do not mix unrelated changes
- **Reviewable MRs** - Small MRs get faster and better reviews
- **Explain the why** - Code shows what, the description explains why
- **Mark WIP early** - Use draft MRs for early feedback

## References

- [Sentry Code Review Guidelines](https://develop.sentry.dev/engineering-practices/code-review/)
- [Sentry Commit Messages](https://develop.sentry.dev/engineering-practices/commit-messages/)
- [Conventional Commits](https://www.conventionalcommits.org/)
