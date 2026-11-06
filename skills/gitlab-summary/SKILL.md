---
name: gitlab-summary
description: Generate a daily GitLab activity summary report. Use when user asks for a quick recap of their GitLab work, daily standup report, or activity overview. Formats output as markdown grouped by project name following Infomaniak conventions.
---

## Version: 1.1.0

# GitLab Daily Summary

Génère un résumé journalier de l'activité GitLab au format markdown plat, concis, compatible Slack.

## Format de sortie

**FORMAT PLAT OBLIGATOIRE** — compatible Slack/Markdown, aucune indentation, aucun sous-niveau :

```markdown
## Résumé GitLab - YYYY-MM-DD

project1:
- Action concise 1
- Action concise 2

project2:
- Action concise 1
- Action concise 2
```

## Règles de formatage

- Format `.md` obligatoire
- **1 bullet = 1 ligne autonome** — pas d'indentation, pas de sous-niveau
- **5 à 10 mots maximum par bullet** — concision absolue
- Regrouper par [nom du projet] - chaque projet apparaît UNE SEULE FOIS suivi de ":"
- Sous chaque projet, lister avec bullets "-"
- 4 à 5 bullets maximum par projet
- Aucun contexte, aucune explication, aucun futur
- Pas de répétition de scope dans les bullets
- **Pas de détail d'implémentation** (signatures de fonction, noms de variables internes) — les noms de feature/produit courts sont autorisés s'ils identifient la fonctionnalité

## Synthèse des actions

- Fusionner commits/MR similaires sous une action concise
- Privilégier les verbes d'action : **merge, push, fix, refactor** (exclure approve, review, open)
- **SUPPRIMER** : IDs, numéros de MR, branches, auteurs
- Conserver uniquement l'intention technique ou produit

## Projets

**Tous les projets GitLab sont automatiquement pris en charge.**

Le skill utilise **directement le nom du projet GitLab** comme titre dans le résumé. Chaque projet apparaît avec son nom réel, sans transformation ni regroupement.

### Exemple de sortie

```
Manager:
- Nouveau: AirPlay support player
- Fix: tag folders media management

Handbook:
- update documentation activités
- restructuration projets

example-project-material:
- Fix: composants material design
```

**Règle simple** : Utiliser le nom du projet tel que défini dans GitLab (`project.name`).

## Processus

### Étape 1 : Récupérer les événements

```bash
# Récupérer les événements du jour via glab API
TODAY=$(date +%Y-%m-%d)
EVENTS=$(glab api "events?after=${TODAY}&before=${TODAY}&per_page=100")
```

### Étape 2 : Grouper par projet

Pour chaque événement, identifier:
- `action_name` : pushed to, pushed new, commented on, merged, opened, approved, accepted, etc.
- `target_type` : MergeRequest, DiffNote, Issue, etc.
- `project_id` : ID du projet
- `target_title` : titre de la MR/issue

Grouper tous les événements par `project_id`.

### Étape 3 : Récupérer le nom du projet

**Règle** : Utiliser directement le nom du projet tel que défini dans GitLab.

```bash
# Récupérer les infos du projet via glab API
PROJECT_INFO=$(glab api "projects/$PROJECT_ID")
PROJECT_NAME=$(echo "$PROJECT_INFO" | jq -r '.name')

# Utiliser le nom du projet comme identifiant dans le résumé
SCOPE="$PROJECT_NAME"
```

**Exemple** :
- Projet avec `name: "Manager"` → Section "Manager" dans le résumé
- Projet avec `name: "Handbook"` → Section "Handbook" dans le résumé
- Projet avec `name: "example-project-material"` → Section "example-project-material" dans le résumé

**Résultat** : Chaque projet apparaît dans le résumé avec son nom exact GitLab, sans transformation.

### Étape 4 : Récupérer et analyser les commits

**Pour chaque événement "pushed to" ou "pushed new":**

1. Récupérer les commits avec leur message complet via glab API:
   ```bash
   glab api "projects/$PROJECT_ID/repository/commits?since=$DATE_START&until=$DATE_END&author=$USER_EMAIL"
   ```

2. Parser chaque message de commit:
   - Extraire la première ligne
   - Identifier le préfixe Conventional Commit (feat:, fix:, refactor:, chore:, test:, etc.)
   - Extraire le sujet principal après le préfixe

3. Grouper par catégorie et compter:
   - feat → Nouveau (X)
   - fix → Fix (X)
   - refactor → Refacto (X)
   - perf → Perf (X)
   - chore → Chore (sans préfixe à l'affichage)
   - test → Test (X)
   - docs → Doc (X)
   - Sans préfixe → Update (X)

### Étape 5 : Filtrer les Actions et Gérer les Merges

**Règles de filtrage:**

**Ne JAMAIS inclure dans le résumé:**
- **Delete branches**: suppression de branches (ex: "Delete branches: feat/trello-XYZ")
- **Open MR**: création de nouvelles MR (ex: "open MR feature X")
- **Pushed new/delete**: création ou suppression de branches
- **Commits de merge internes**: merges entre branches de feature (format: "Merge branch 'X' into 'Y'")

**Gestion spéciale des merges:**

| Type de merge | Affichage | Condition |
|---------------|-----------|-----------|
| Merge vers feature/develop | Ne PAS afficher | Branche cible ≠ master/main |
| Merge vers master/main | Afficher "MEP: sujet" | Branche cible = master/main |

**Format MEP** : `MEP: <sujet court>` — toujours accompagné d'un descriptif concis du contenu déployé.

**Détection du merge master/main:**

```bash
# Vérifier si le push concerne master ou main
if [[ "$REF" == "master" || "$REF" == "main" ]]; then
  # C'est une MEP
  echo "MEP: <sujet>"
else
  # Merge interne, ne pas afficher
  :
fi
```

**SEULES actions à synthétiser:**

| Actions brutes | Action synthétisée |
|----------------|-------------------|
| "accepted" avec ref=master/main | MEP: <sujet> |
| Push de commits | Nouveau, Fix, Refacto, etc. |

**Actions à EXCLURE (ne PAS afficher):**

| Actions brutes | Raison |
|----------------|--------|
| "approved" | Approve MR - pas d'impact sur le code réel |
| "commented on" | Review code avec commentaires - pas de changement de code |
| "commented on" DiffNote/DiscussionNote | Review code - feedback uniquement |

**Context**: Seuls les merges vers master/main sont informatifs (déploiement en production). Les merges entre branches de développement sont des étapes intermédiaires sans valeur pour le résumé.

### Règle critique — enrichissement des push

- Ne jamais afficher uniquement un volume de commits (ex: "push 34 commits")
- Extraire les thématiques fonctionnelles depuis `target_title`, nom de branche, title de la MR ou nom de commit
- Regrouper les commits par feature ou sous-système
- **Transformer en catégories de changements via les préfixes de commits**
- Transformer en actions métier compréhensibles

Format attendu:
- <feature1>
- <feature2>
- <feature3>

### Catégorisation des commits (Conventional Commits)

**Récupérer les messages de commits**

Pour chaque événement `pushed to` ou `pushed new`, extraire les commits avec leur message:

```bash
# Pour un événement push avec project_id et commit_from/commit_to
glab api "projects/$PROJECT_ID/repository/commits?since=YYYY-MM-DDT00:00:00Z&until=YYYY-MM-DDT23:59:59Z&author=$USER_ID&per_page=100"
```

**Analyser les types de changements**

Parser la première ligne de chaque message de commit et extraire le préfixe:

| Préfixe | Catégorie | Verbe à utiliser | Description |
|---------|-----------|------------------|-------------|
| `feat:` | **Nouveau** (Nouvelles fonctionnalités) | Nouveau | Ajout de nouvelles fonctionnalités |
| `fix:` | **Fix** (Corrections) | Fix | Correction de bugs |
| `refactor:` | **Refacto** (Refactoring) | Refacto | Restructuration du code sans changement de comportement |
| `perf:` | **Perf** (Performance) | Optimise | Améliorations de performance |
| `chore:` | **Chore** (Maintenance) | *(sans préfixe)* | Taches de maintenance, scripts, dépendances |
| `test:` | **Test** (Tests) | Ajoute | Ajout ou modification de tests |
| `docs:` | **Doc** (Documentation) | Documente | Documentation et commentaires |
| `ci:` | **CI/CD** (Pipeline) | Configure | Configuration CI/CD |
| Pas de préfixe | **Update** (Autre) | Update | Autres modifications |

**Règles de formatage par catégorie**

1. **Grouper les commits par scope et par catégorie**
2. **Synthétiser le contenu** en extrayant le sujet après le préfixe:
   - "feat: add media converter configuration" → "Nouveau: configuration media converter"
   - "fix: encoding bug in manager" → "Fix: bug d'encoding dans manager"
   - "refactor: dashboard components" → "Refacto: composants dashboard"
3. **Exception pour les commits de type chore** — ne pas afficher la catégorie, uniquement le sujet:
   - "chore: update dependencies" → "update dependencies" (sans "Chore:")
   Tous les autres types gardent leur préfixe (Nouveau, Fix, Refacto, etc.)
4. **Lister les sujets** sur une même ligne, séparés par des virgules

### Regroupement par feature/thème — FORMAT PLAT

**Principe** : Regrouper les commits qui concernent le même sujet/fonctionnalité sur une seule ligne plate par catégorie. **Aucune indentation, aucun sous-niveau.**

**Étape 1 : Identifier le thème**

Extraire les mots-clés significatifs après avoir retiré :
- Les préfixes conventionnels (feat:, fix:, refactor:)
- Les mots d'action vides (add, implement, move, extract, update, correct, resolve, remove)
- Les articles et prépositions

**Étape 2 : Regrouper par similarité**

```
feat: add driveId parameter for kDrive
fix: correct parameter name from displayMode
feat: add selectedDriveId and displayMode support
```
→ **Identifié** : "displayMode" et "driveId" sont liés (kDrive pre-selection)

**Étape 3 : Fusionner par catégorie — 1 bullet plat par catégorie**

Quand plusieurs commits touchent le même sujet, les regrouper par catégorie. Chaque catégorie = 1 bullet plat autonome.

**Priorité d'affichage** : Nouveau > Fix > Refacto > autres

**Format de sortie PLAT unifié**

```
Manager:
- Nouveau: pré-sélection kDrive – paramètre driveId, support selectedDriveId et displayMode
- Fix: correction du nom du paramètre displayMode
- Refacto: extraction du type de mode d'affichage

Player:
- Fix: chargement du plugin DASH – chemin dynamique depuis public
- suppression des console.log de debug
```

**Note** : Les commits `chore` s'affichent sans préfixe de catégorie, uniquement le sujet (voir règle ligne 232).

**Règles de regroupement — FORMAT PLAT**

1. **Extraire le sujet principal** :
   - "add driveId parameter for kDrive" → "kDrive pre-selection"
   - "Load DASH plugin dynamically" → "DASH plugin loading"
   - "extract display mode type" → "display mode type"

2. **Identifier les relations** :
   - Mêmes termes techniques (driveId, displayMode, DASH plugin)
   - Même sous-système ou composant
   - Actions complémentaires sur une même feature

3. **Format final — 1 bullet par catégorie, plat** :
   ```
   - Nouveau: [Sujet] – action1, action2
   - Fix: [Sujet] – action1
   - Refacto: [Sujet] – action1
   ```

**Exemple complet avec regroupement plat**

Entrée :
```
feat: add driveId parameter for kDrive pre-selection
feat: add selectedDriveId and displayMode support
fix: correct parameter name from displayMode to displayModeId
refactor: extract display mode type into TDisplayMode alias
feat: Load DASH plugin dynamically from public folder
fix: Use PUBLIC_URL for DASH plugin path
chore: Remove debug console.log statement
```

Sortie :
```
Manager:
- Nouveau: pré-sélection kDrive – paramètre driveId, support selectedDriveId et displayMode
- Fix: correction du nom du paramètre displayMode
- Refacto: extraction du type de mode d'affichage

Player:
- Fix: chargement du plugin DASH – chemin dynamique depuis public
- suppression des console.log de debug
```

**Extraction intelligente des sujets**

- Retirer les préfixes (feat:, fix:, refactor:)
- Retirer les mots d'action vides (add, implement, move, extract, update, correct, resolve, remove)
- Identifier les noms communs (displayMode, driveId, DASH, plugin, etc.)
- Regrouper par similarité sémantique
- Limiter à 2-3 mots par sujet
- Utiliser le verbe français approprié selon la catégorie
- **Pas de détail d'implémentation** (signatures de fonction, noms de variables internes obscurs) — les noms de feature/produit courts (DASH, localStorage, driveId) sont autorisés s'ils identifient clairement la fonctionnalité


### Étape 6 : Formater la sortie

```markdown
## Résumé GitLab - $(date +%Y-%m-%d)

scope1:
- action1
- action2

scope2:
- action1
- action2
```

## Exemples

### Exemple 1 — Conventional Commits avec regroupement plat

**Entrée (commits bruts avec messages)**:
```
example-project (proj 1001):
- feat: add media converter encoding configuration panel
- feat: implement source validation for converter inputs
- feat: create dashboard for media converter management
- fix: resolve encoding race condition bug
- fix: correct source config validation error
- refactor: extract converter logic into dedicated service
- refactor: simplify dashboard component structure
- chore: update media-converter dependencies

Player (proj 5685):
- feat: persist subtitle text track settings in localStorage
- test: add unit tests for subtitle persistence
- chore: bump player version
```

**Sortie formatée plate**:
```markdown
## Résumé GitLab - 2026-03-23

Manager:
- Nouveau: media converter – panel de config, validation des sources, dashboard
- Fix: condition de concurrence encodage, erreur de validation config
- Refacto: extraction du service converter, simplification dashboard
- dépendances du converter

Player:
- Nouveau: persistance des sous-titres via localStorage
- Test: tests unitaires persistance sous-titres
- bump version player
```

### Exemple 2 — Fusion de catégories en format plat

```markdown
## Résumé GitLab - 2026-03-26

Manager:
- Nouveau: pré-sélection kDrive – paramètre driveId, support selectedDriveId et displayMode
- Fix: correction du nom du paramètre displayMode
- Refacto: extraction du type de mode d'affichage

Player:
- Fix: chargement du plugin DASH – chemin dynamique depuis public
- suppression des console.log de debug
```

**Principe appliqué** :
- Les commits sur "displayMode" et "driveId" sont regroupés sous "kDrive pre-selection"
- Les commits sur "DASH plugin" sont regroupés
- Chaque catégorie = 1 bullet plat, sans indentation

### Exemple 3 — MEP avec contexte

```markdown
## Résumé GitLab - 2026-07-29

Manager:
- Nouveau: overlay media converter – activation sur vidéo complète
- Nouveau: task-steps-status – tooltip interactif scrollable
- Fix: overlay helper, upload image 1.5MB
- Refacto: config formulaire overlay

Player:
- MEP: XSS share plugin – échappement HTML
- codeowners approbations groupe + guardrails sécurité
```

## Commande pour exécuter

```bash
# Le skill est invoqué automatiquement quand l'utilisateur demande : 
# - "résumé gitlab"
# - "daily summary"
# - "activité gitlab"
# - "standup report"
# - etc.
```

## Notes

- Toujours utiliser la date du jour (queried date)
- Limite de 50 événements par défaut
- Seuls les événements de la journée sont inclus
- Le français est utilisé pour toutes les descriptions
- **Format plat obligatoire** : chaque bullet est autonome, sans indentation ni sous-niveau
- **Concision** : 5-10 mots par bullet maximum, pas de détail technique
