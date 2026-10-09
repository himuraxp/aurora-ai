---
name: deployment-changelog
description: Génère un changelog de déploiement au format spécifié pour les commits sur master depuis 00:01 ce matin jusqu'à maintenant.
---

## Version: 1.1.0

# Deployment Changelog Generator

Génère un changelog de déploiement au format spécifié pour les commits sur master depuis 00:01 ce matin jusqu'à maintenant.

## Format de sortie

Format obligatoire:
```markdown
[Acme App] Deploying updates - 1.6.51

---

#### [1.6.51](https://gitlab.example.com/acme-group/acme-app/-/compare/1.6.50...1.6.51) (2026-03-31)

#### Features

* Added a separate AirPlay player option for player configuration and playback management ([fa1ce01](https://gitlab.example.com/acme-group/acme-app/-/commit/fa1ce01))

#### Bug Fixes

* Updated generated translations to reflect the latest player and interface changes ([cafe012](https://gitlab.example.com/acme-group/acme-app/-/commit/cafe012))
```

## Processus

### Étape 1: Détecter le projet

**Récupérer le nom du projet depuis le repo local:**

```bash
# Détecter le remote git, en déduire le host GitLab et le chemin du projet
# (le host du remote EST la source de vérité pour les MR/compare links)
GIT_REMOTE=$(git remote get-url origin 2>/dev/null || git config --get remote.origin.url)
GITLAB_HOST=$(echo "$GIT_REMOTE" | sed -E 's#^(ssh://)?(git@|https?://)##; s#[/:].*##')
PROJECT_PATH=$(echo "$GIT_REMOTE" | sed "s#.*$GITLAB_HOST/##" | sed 's/\.git$//')
echo "Projet: $PROJECT_PATH (host: $GITLAB_HOST)"
```

### Étape 2: Récupérer les tags de version

**Trouver le dernier tag et l'avant-dernier:**

```bash
# Récupérer le dernier tag
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")

if [[ -z "$LATEST_TAG" ]]; then
  # Pas de tags - utiliser la date du jour comme version
  echo "Aucun tag trouvé, utilisation de la date du jour comme version"
  HAS_TAGS=false
  PREVIOUS_TAG=""
  VERSION=$(date +%Y-%m-%d)
  LATEST_TAG="HEAD"
else
  # Tags disponibles
  HAS_TAGS=true
  PREVIOUS_TAG=$(git describe --tags --abbrev=0 --exclude="$LATEST_TAG" 2>/dev/null || echo "")
  VERSION="${LATEST_TAG#v}"
fi

echo "Version actuelle: $VERSION"
[[ "$HAS_TAGS" == true ]] && echo "Version précédente: ${PREVIOUS_TAG:-'aucune'}"
```

### Étape 3: Définir la plage de temps

**Période: 00:01 aujourd'hui jusqu'à maintenant:**

```bash
# Date de début: 00:01 aujourd'hui
START_DATE=$(date +%Y-%m-%d)T00:01:00
START_TIMESTAMP=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$START_DATE" +%s 2>/dev/null || date -d "$START_DATE" +%s)

# Date de fin: maintenant
END_TIMESTAMP=$(date +%s)

# Formater pour l'affichage
RELEASE_DATE=$(date +%Y-%m-%d)
```

### Étape 4: Récupérer les commits via glab API

**Récupérer les commits entre les dates sur la branche master:**

```bash
# Encoder le chemin du projet pour l'URL
ENCODED_PROJECT=$(echo "$PROJECT_PATH" | sed 's/\//%2F/g')

# Récupérer les commits via l'API GitLab
START_ISO=$(date -r "$START_TIMESTAMP" -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d @"$START_TIMESTAMP" +%Y-%m-%dT%H:%M:%SZ)
END_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)

COMMITS=$(glab api "projects/$ENCODED_PROJECT/repository/commits?ref_name=master&since=$START_ISO&until=$END_ISO&per_page=100")

# Vérifier si des commits ont été trouvés
if [[ -z "$COMMITS" ]] || [[ "$COMMITS" == "[]" ]]; then
  echo "Aucun commit trouvé sur master entre $START_ISO et $END_ISO"
  exit 0
fi
```

### Étape 5: Analyser et catégoriser les commits

**Parser les commits et catégoriser par type:**

```bash
# Extraire les commits avec leurs messages et IDs
# Format attendu du JSON: [{"id": "hash", "title": "message", "message": "full message", ...}]

# Catégoriser les commits
FEATURES=$(echo "$COMMITS" | jq -r '.[] | select(.title | test("^(feat|feature):"; "i")) | @base64')
FIXES=$(echo "$COMMITS" | jq -r '.[] | select(.title | test("^fix:"; "i")) | @base64')
OTHERS=$(echo "$COMMITS" | jq -r '.[] | select(.title | test("^(feat|feature|fix):"; "i") | not) | @base64')

echo "Features trouvées: $(echo "$FEATURES" | grep -c "^" || echo 0)"
echo "Fixes trouvés: $(echo "$FIXES" | grep -c "^" || echo 0)"
```

### Étape 6: Formater le changelog

**Générer le format attendu:**

```bash
PROJECT_NAME=$(echo "$PROJECT_PATH" | sed 's/.*\///')

# Titre
echo "[$PROJECT_NAME] Deploying updates - $VERSION"
echo ""
echo "---"
echo ""

# Header avec ou sans comparaison
if [[ "$HAS_TAGS" == true && -n "$PREVIOUS_TAG" ]]; then
  # Avec tags - lien de comparaison
  echo "#### [$VERSION](https://$GITLAB_HOST/$PROJECT_PATH/-/compare/${PREVIOUS_TAG}...${LATEST_TAG}) ($RELEASE_DATE)"
else
  # Sans tags - titre simple avec la date
  echo "#### Deployment du $RELEASE_DATE"
fi
echo ""

# Section Features
if [[ -n "$FEATURES" ]]; then
  echo "#### Features"
  echo ""
  echo "$COMMITS" | jq -r '.[] | select(.title | test("^(feat|feature):"; "i")) | "* " + (.title | sub("^[a-z]+: ?"; ""; "i")) + ([" + (.id | .[:8]) + "](https://'$GITLAB_HOST'/'$PROJECT_PATH'/-/commit/" + .id + "))"'
  echo ""
fi

# Section Bug Fixes
if [[ -n "$FIXES" ]]; then
  echo "#### Bug Fixes"
  echo ""
  echo "$COMMITS" | jq -r '.[] | select(.title | test("^fix:"; "i")) | "* " + (.title | sub("^fix: ?"; ""; "i")) + ([" + (.id | .[:8]) + "](https://'$GITLAB_HOST'/'$PROJECT_PATH'/-/commit/" + .id + "))"'
  echo ""
fi

# Section Others (si nécessaire)
if [[ -n "$OTHERS" ]]; then
  echo "#### Other Changes"
  echo ""
  
  # Traiter chaque commit "other" individuellement pour enrichir les merge commits
  echo "$COMMITS" | jq -c '.[] | select(.title | test("^(feat|feature|fix):"; "i") | not)' | while read -r commit; do
    commit_id=$(echo "$commit" | jq -r '.id')
    commit_title=$(echo "$commit" | jq -r '.title')
    short_hash=$(echo "$commit_id" | cut -c1-8)
    
    # Vérifier si c'est un commit de merge (merge local manuel)
    if echo "$commit_title" | grep -qiE "merge branch|merge pull request"; then
      # Essayer de récupérer la MR associée à ce commit
      merge_request=$(glab api "projects/$ENCODED_PROJECT/merge_requests?source_branch=$commit_title&state=all&per_page=5" 2>/dev/null | jq -r '.[0] // empty')
      
      if [[ -n "$merge_request" ]]; then
        mr_title=$(echo "$merge_request" | jq -r '.title')
        echo "* $mr_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
      else
        # Fallback: essayer de trouver la MR via la branche source dans le message de merge
        branch_name=$(echo "$commit_title" | sed -n "s/.*['\"]\([^'\"]*\)['\"].*/\1/p" | grep -v "^$" | head -1)
        
        if [[ -n "$branch_name" ]]; then
          merge_request=$(glab api "projects/$ENCODED_PROJECT/merge_requests?source_branch=$branch_name&state=all&per_page=1" 2>/dev/null | jq -r '.[0] // empty')
          
          if [[ -n "$merge_request" ]]; then
            mr_title=$(echo "$merge_request" | jq -r '.title')
            echo "* $mr_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
          else
            # Aucune MR trouvée, afficher le message original
            echo "* $commit_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
          fi
        else
          echo "* $commit_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
        fi
      fi
    else
      # Pas un merge commit, afficher normalement
      echo "* $commit_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
    fi
  done
  
  echo ""
fi
```

### Étape 7: Validation et création d'événement

**Afficher le changelog généré et demander validation:**

```bash
# Stocker le changelog complet
CHANGELOG_TITLE="[$PROJECT_NAME] Deploying updates - $VERSION"

# Générer le contenu Other avec enrichissement des merge commits
OTHER_CONTENT=""
if [[ -n "$OTHERS" ]]; then
  OTHER_CONTENT="#### Other Changes

"
  while IFS= read -r commit; do
    commit_id=$(echo "$commit" | jq -r '.id')
    commit_title=$(echo "$commit" | jq -r '.title')
    short_hash=$(echo "$commit_id" | cut -c1-8)
    
    # Vérifier si c'est un commit de merge (merge local manuel)
    if echo "$commit_title" | grep -qiE "merge branch|merge pull request"; then
      # Essayer de récupérer la MR associée
      merge_request=$(glab api "projects/$ENCODED_PROJECT/merge_requests?source_branch=$commit_title&state=all&per_page=5" 2>/dev/null | jq -r '.[0] // empty')
      
      if [[ -n "$merge_request" ]]; then
        mr_title=$(echo "$merge_request" | jq -r '.title')
        OTHER_CONTENT="${OTHER_CONTENT}* $mr_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
      else
        # Fallback: essayer de trouver la MR via la branche source dans le message de merge
        branch_name=$(echo "$commit_title" | sed -n "s/.*['\"]\([^'\"]*\)['\"].*/\1/p" | grep -v "^$" | head -1)
        
        if [[ -n "$branch_name" ]]; then
          merge_request=$(glab api "projects/$ENCODED_PROJECT/merge_requests?source_branch=$branch_name&state=all&per_page=1" 2>/dev/null | jq -r '.[0] // empty')
          
          if [[ -n "$merge_request" ]]; then
            mr_title=$(echo "$merge_request" | jq -r '.title')
            OTHER_CONTENT="${OTHER_CONTENT}* $mr_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
          else
            OTHER_CONTENT="${OTHER_CONTENT}* $commit_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
          fi
        else
          OTHER_CONTENT="${OTHER_CONTENT}* $commit_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
        fi
      fi
    else
      OTHER_CONTENT="${OTHER_CONTENT}* $commit_title ([$short_hash](https://$GITLAB_HOST/$PROJECT_PATH/-/commit/$commit_id))"
    fi
    OTHER_CONTENT="${OTHER_CONTENT}
"
  done < <(echo "$COMMITS" | jq -c '.[] | select(.title | test("^(feat|feature|fix):"; "i") | not)')
  OTHER_CONTENT="${OTHER_CONTENT}
"
fi

CHANGELOG_CONTENT=$(cat <<EOF
#### $(if [[ "$HAS_TAGS" == true && -n "$PREVIOUS_TAG" ]]; then echo "[$VERSION](https://$GITLAB_HOST/$PROJECT_PATH/-/compare/${PREVIOUS_TAG}...${LATEST_TAG}) ($RELEASE_DATE)"; else echo "Deployment du $RELEASE_DATE"; fi)

$(if [[ -n "$FEATURES" ]]; then echo "#### Features"; echo ""; echo "$COMMITS" | jq -r '.[] | select(.title | test("^(feat|feature):"; "i")) | "* " + (.title | sub("^[a-z]+: ?"; ""; "i")) + " ([" + (.id | .[:8]) + "](https://'$GITLAB_HOST'/'$PROJECT_PATH'/-/commit/" + .id + "))"'; echo ""; fi)

$(if [[ -n "$FIXES" ]]; then echo "#### Bug Fixes"; echo ""; echo "$COMMITS" | jq -r '.[] | select(.title | test("^fix:"; "i")) | "* " + (.title | sub("^fix: ?"; ""; "i")) + " ([" + (.id | .[:8]) + "](https://'$GITLAB_HOST'/'$PROJECT_PATH'/-/commit/" + .id + "))"'; echo ""; fi)

$OTHER_CONTENT
EOF
)

echo "========================================"
echo "📋 CHANGELOG GÉNÉRÉ"
echo "========================================"
echo ""
echo "**Titre:**"
echo "$CHANGELOG_TITLE"
echo ""
echo "**Description:**"
echo "$CHANGELOG_CONTENT"
echo ""
echo "========================================"
```

**Demander validation à l'utilisateur:**

```bash
read -p "Ce changelog vous convient-il ? (oui/non) : " CONFIRMATION

if [[ "$CONFIRMATION" =~ ^[Oo][Uu][Ii]$ ]]; then
  echo "✅ Création de l'événement en cours..."
else
  echo "❌ Création annulée."
  exit 0
fi
```

### Étape 8: Créer l'événement via l'API Infomaniak

**Récupérer le token Bearer:**

```bash
# Récupérer depuis la variable d'environnement
BEARER_TOKEN="${BEARER_EVENT:-}"

# Si pas de token, demander à l'utilisateur
if [[ -z "$BEARER_TOKEN" ]]; then
  echo "Variable BEARER_EVENT non définie."
  read -sp "Veuillez entrer le token Bearer: " BEARER_TOKEN
  echo ""
fi

# Vérifier que le token est présent
if [[ -z "$BEARER_TOKEN" ]]; then
  echo "❌ Token Bearer requis pour créer l'événement."
  exit 1
fi
```

**Préparer et envoyer la requête API:**

```bash
# Préparer les timestamps
START_DATETIME=$(date +"%Y-%m-%d %H:%M:%S")

# IMPORTANT : payload aligné sur le formulaire internal.infomaniak.com
# - ended_at reste null à la création : c'est autoclose + estimated_time (min) qui terminent l'événement
# - Pour poser une date de fin explicite après création : PUT /2/events/private/{id} avec {"ended_at": "Y-m-d H:i:s"}
PAYLOAD=$(jq -n \
  --arg started_at "$START_DATETIME" \
  --arg title "$CHANGELOG_TITLE" \
  --arg description "$CHANGELOG_CONTENT" \
  '{
    type: "maintenance",
    status: "inprogress",
    description: { title: $title, body: $description },
    started_at: $started_at,
    ended_at: null,
    event_type: "internal",
    visibility: "internal",
    estimated_time: 5,
    autoclose: true,
    business_units: ["media"],
    groups: ["dev-central", "unix-central"],
    disable_notify: false,
    confidentiality_impact: false,
    integrity_impact: false,
    availability_impact: false,
    risk_score: 1,
    perimeter_score: 1,
    business_score: 2,
    intervention_score: 2,
    global_score: 4,
    deploy_slug: "default_team",
    is_cyberattack: false
  }')

API_ENDPOINT="https://api.infomaniak.com/2/events/private"

echo "📤 Envoi de la requête à l'API Infomaniak..."

# Envoyer la requête
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_ENDPOINT" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "$PAYLOAD")

# Extraire le code HTTP et le body
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

# Vérifier la réponse
if [[ "$HTTP_CODE" == "201" ]] || [[ "$HTTP_CODE" == "200" ]]; then
  echo "✅ Événement créé avec succès !"
  echo "Réponse: $BODY"
else
  echo "❌ Erreur lors de la création de l'événement (HTTP $HTTP_CODE)"
  echo "Réponse: $BODY"
  exit 1
fi
```

## Commande d'utilisation

```
Le skill est invoqué quand l'utilisateur demande :
- "générer le changelog de déploiement"
- "créer le changelog pour le déploiement"
- "deployment changelog"
- "changelog de déploiement"
- "changelog matin"
```

## Prérequis

- Être dans un répertoire git avec remote GitLab
- Avoir `glab` configuré et authentifié
- Avoir `jq` installé pour le parsing JSON
- Avoir `curl` installé pour les appels API
- **Variable d'environnement** : `BEARER_EVENT` doit être définie avec le token API Infomaniak (sinon sera demandé interactivement)

## Notes

- Analyse uniquement la branche master
- Période: 00:01 du jour courant jusqu'à maintenant
- **Comportement avec tags** : Détecte automatiquement le dernier et l'avant-dernier tag, génère un lien de comparaison entre versions
- **Comportement sans tags** : Utilise la date du jour comme version (YYYY-MM-DD), pas de lien de comparaison
- Affiche les commits avec leur hash court et lien vers GitLab
- Groupe automatiquement en Features/Bug Fixes/Other
- **Nouvelle fonctionnalité** : Après génération, le changelog est affiché pour validation avant création automatique de l'événement Infomaniak
- L'événement est créé avec les paramètres : type=maintenance, business_units=["media"], event_type=internal, visibility=internal, groups=["dev-central","unix-central"], deploy_slug=default_team
- **Fin d'événement** : `ended_at` reste `null` à la création ; `autoclose: true` + `estimated_time: 5` (minutes) terminent l'événement automatiquement. Payload aligné sur le formulaire internal.infomaniak.com
- **Date de fin explicite** (optionnel) : après création, `PUT /2/events/private/{id}` avec `{"ended_at": "Y-m-d H:i:s"}` (format obligatoire `Y-m-d H:i:s`, PATCH n'existe pas). La durée est auto-calculée par l'API et le status passe à `terminated` une fois la date passée
- Si la variable `BEARER_EVENT` n'est pas définie, le token sera demandé interactivement
- **Amélioration des merge commits** : Pour les commits "Merge branch..." (fait via merge local manuel), le skill tente automatiquement de récupérer le titre de la MR associée via l'API GitLab et l'affiche à la place du message de merge technique
