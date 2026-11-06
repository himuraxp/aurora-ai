---
name: gitlab-feature-planner
description: Use when planning a large product feature from estimation sources (Excel/CSV/Markdown tables), Figma mockups and GitLab repositories — transforms raw task rows into a structured proposal of GitLab issues (1 issue = 1 page or coherent functional block; rows become checklist tasks; only shared/independent/complex components get their own issue) plus suggested MR groupings (suggestions only, never created), with mandatory human validation before any GitLab creation. Also supports auditing and syncing already-created issues (stable ID marker, acceptance criteria, relations). Trigger on "feature planner", "planifier la feature", "préparation de feature", "issues depuis le tableau", "découper le tableau en issues GitLab", "découpage produit", "planning produit", "suggestions de MR", "feature planner audit", "feature planner sync".
---

# GitLab Feature Planner

Transforme des sources de préparation produit (tableau d'estimation Excel/CSV/Markdown, maquettes Figma, repositories GitLab) en une proposition structurée d'issues GitLab — **sans créer une issue par ligne du tableau** — avec des **suggestions de regroupement en MR**.

**Requires** : `glab` (création des issues uniquement), `python3` (helper Excel, optionnel — sinon demander un export CSV).

## When to Use

- Préparer le développement d'une grosse feature (ex : Podcast) à partir d'un tableau d'estimation
- Regrouper des dizaines de tâches unitaires (composants, modales, drawers, actions) en un nombre raisonnable d'issues
- Construire des checklists d'issues depuis les lignes du tableau, prêtes à recevoir les MRs
- Proposer un découpage cohérent en MR (suggestions, jamais imposées)

## Philosophie — Granularité cible

> **1 issue GitLab = une page ou un bloc fonctionnel cohérent, à la granularité du tableau d'estimation.**
> Plusieurs MR peuvent être rattachées à cette issue.

Trois niveaux à ne pas confondre :

```text
Issue     = unité fonctionnelle de suivi (page ou bloc fonctionnel)
Task      = unité de travail issue du backlog (ligne du tableau)
MR group  = unité cohérente d'implémentation/review (suggestion)
```

Relation canonique :

```text
Issue     = page ou bloc fonctionnel
Checklist = tâches issues du tableau d'estimation
MR        = lot cohérent d'une ou plusieurs tâches
```

⚠ **Ne jamais modéliser « 1 tâche = 1 MR »** : une MR peut regrouper plusieurs tâches petites, proches fonctionnellement ou techniquement dépendantes. La granularité des issues est stable ; celle des MR reste flexible.

Les lignes du tableau deviennent principalement des **éléments de checklist** à l'intérieur des issues :

```markdown
## [Podcast] Dashboard

- [x] Store Podcast
- [x] Resolver Podcast
- [ ] Statistiques de la semaine — 1 j
- [ ] Distribution — 0.5 j
- [ ] Épisodes — 0.5 j
- [ ] Preview du dernier épisode — 2 j
- [ ] Dashboard vide — 0.125 j
- [ ] Header Podcast — 0.125 j
```

Une issue séparée pour un **composant** est créée UNIQUEMENT si au moins une condition :

| Condition | Signal dans le tableau | Exemple Podcast |
|-----------|------------------------|-----------------|
| **Partagé** entre ≥ 2 pages | Même composant cité sur plusieurs lignes/pages | Composants partagés Player |
| **Chantier technique indépendant** | Architecture, setup, store global, migration, infra | Setup Player |
| **Complexité suffisante** | Sous-tâches nombreuses, durée élevée, dépendances fortes | Lecteurs, Statistiques |

## Règles dures

1. **Aucune création sans validation humaine explicite** — et seules des **issues** sont créées ; les regroupements MR restent des suggestions, jamais créées automatiquement.
2. **Jamais 1 ligne du tableau = 1 issue.**
3. **Traçabilité** : chaque ligne source apparaît exactement UNE fois (dans la checklist d'une issue, ou comme tâche portée par une issue composant/infra). Les lignes non plaçables après clarification utilisateur vont dans `unmatched_rows` — jamais supprimées. Un orphelin rangé dans une issue (step 3) ne compte PAS comme unmatched.
4. **Justification obligatoire** : toute issue de type `component` ou `infra` porte une `rationale` explicite (une des 3 conditions du tableau ci-dessus).
5. **Suggestions de découpage MR toujours explicites** : présentées comme telles ; l'humain peut fusionner, séparer, déplacer une tâche ou ignorer.
6. **Pas de secrets** (tokens, .env, credentials) dans les issues.
7. Le repository local cible reste soumis à son `AGENTS.md`.

## Project resolution

La résolution d'un projet GitLab ne doit JAMAIS être devinée. Passer par le **registry** : `skills/gitlab-feature-planner/` + `resolve-project.py`.

**Distinguer** : nom humain (« Example Project », « Admin ») ≠ `gitlabPath` (`acme-group/example-project`) ≠ `projectId` (1001). Seul le couple path validé ↔ ID numérique est fiable.

**Registry — pattern private-config / public-engine** (repo public = template placeholder, config privée = données réelles, cf. deployment-changelog) :

| Fichier | Versionné ? | Contenu |
|---|---|---|
| `~/.config/opencode/gitlab-feature-planner-registry.private.json` | ❌ hors repo | Tes projets RÉELS validés (namespaces, IDs) — **jamais versionné** |
| `projects-registry.json` | ✅ versionné | Template placeholder (`acme-group/...`, IDs fictifs) |
| `projects-registry.example.json` | ✅ versionné | Template avec données d'exemple (identique au template ci-dessus) |

Le loader (`load_registry`) cherche dans l'ordre : **registre privé** (`~/.config/opencode/gitlab-feature-planner-registry.private.json`) → registry du repo → registry installé (`~/.config/opencode/skills/gitlab-feature-planner/`) → template example. `--record` écrit toujours dans le registre privé, jamais dans un fichier du repo public (les namespaces/IDs réels ne doivent pas fuiter dans le repo). Pour démarrer : copier `projects-registry.example.json` vers le chemin privé, puis le remplir via `--record`.

Stratégie, dans l'ordre :

```text
1. mapping explicite dans le project registry (alias / projectId / gitlabPath)
2. project path connu
3. project ID connu
4. recherche GitLab contrôlée (namespace + nom, jamais le premier résultat en aveugle)
5. ambiguïté → STOP, demander confirmation à l'utilisateur
```

- Un projet découvert et validé est **mémorisé** dans le registry (`resolve-project.py --record <alias> --path <p> --id <n>`, après confirmation humaine) — la prochaine feature ne repart pas de zéro.
- `resolve-project.py --validate` vérifie en live que chaque `projectId` répond avec le bon `path_with_namespace`.

**Pièges `glab` constatés en réel (issues d'une feature, 2026-09)** — `<ns>` = namespace, `<path>` = path du projet, `<id>` = ID numérique du registry :

| Appel | Résultat |
|-------|----------|
| `glab api "projects/<ns>%2F<path>"` (path URL-encodé) | ✅ fonctionne |
| `glab api "projects/<ns>/<path>"` (slashes bruts) | ❌ 404 — le router ne matche pas `projects/:id` |
| `glab repo view -R <ns>/<path>` | ❌ 404 malgré les droits (`project_access: 40`) |
| `glab api "projects/<id>"` (ID numérique) | ✅ toujours fiable |

→ Pour toute opération API : **ID numérique du registry** (référence primaire) ou path encodé `%2F` (fallback). Ne jamais passer un path brut à `glab api`.

**Recherche contrôlée d'un projet inconnu** (fallback) : `glab api "search?scope=projects&search=<nom>"` → vérifier `path_with_namespace` et les droits (`permissions.project_access`) → confirmer avec l'utilisateur → enregistrer via `resolve-project.py --record`.

## Issue routing

> **Une issue appartient au repository dans lequel son implémentation principale sera réalisée.**

```text
Issue = page / fonctionnalité cohérente + repository cible unique
```

Si une fonctionnalité touche plusieurs repositories : une **issue d'exécution par repo** (jamais une issue multi-repos) :

```text
Intégration univers Podcasts (fonctionnelle)
├── Manager Element → issue « Mise à jour du menu Univers »  (design system)
└── Admin4          → issue « Menu Univers, bloc et tab Podcasts »  (code Admin4)
```

Ne pas mettre une issue dans `example-project` si toutes ses MR seront faites dans `example-material`. Les issues jumelles se référent mutuellement (relation `relates_to` + mention dans les Notes). Chaque issue de l'IssueSpec porte un champ `project` = clé du registry.

## Pipeline

```text
Excel / CSV / Markdown (backlog)
        ↓ (1) normalisation
liste de tâches unifiée
        ↓ (2) analyse fonctionnelle
pages, composants, chantiers transverses
        ↓ (3) regroupement en issues + checklist
        ↓ (4) suggestions de regroupement MR
        ↓ (5) enrichissement (Figma + contexte repo + issues existantes)
        ↓ (6) IssueSpec
        ↓ (7) draft + preview
        ↓ (8) validation humaine   ← STOP obligatoire
        ↓ (9) création des issues (seulement)
```

### Step 1 — Normalisation

Convertir toutes les sources en une **liste de tâches unifiée** (une tâche = une ligne source nettoyée).

**Excel (.xlsx)** :

```bash
python3 ~/.config/opencode/skills/gitlab-feature-planner/xlsx-to-csv.py <tableau.xlsx> -o tableau.csv
# puis lire tableau.csv avec le tool Read
```

Le helper **expanse les cellules fusionnées** : la valeur de la cellule amont est propagée sur toute la plage fusionnée (cas typique — colonne Page fusionnée sur plusieurs lignes). Échec du helper → demander un export CSV (ne pas bloquer sur le format xlsx).

**Sources CSV/Markdown brutes** : si la colonne Page est vide alors qu'une valeur non vide précède (fusion perdue à l'export), propager la dernière valeur non vide (forward-fill) et signaler les lignes re-rattachées.

**Mapping des colonnes** (tolérer les variantes de nommage, demander si ambigu) :

| Colonne source | Champ unifié | Normalisation |
|----------------|--------------|---------------|
| Page | `page` | Trim ; vide après forward-fill → tâche transverse à classer (step 3) |
| Composant / Tâche | `task` | Trim ; supprimer formules Excel verbatim (`=SUM(...)`) et retours ligne |
| lien maquette | `figma` | URL valide ou `null` |
| Durée estimée | `estimate` | Conserver le format d'origine (`1 j`, `0.5 j`, `0.125 j` = 1 h) ; somme en jours au step 3 |
| Durée réalisée | `realized` | Non vide et > 0 → candidat `[x]` |
| Statut | `status` | « Fait / Terminé / Done / OK » → `[x]` |
| Assigné à | `assignee` | Username GitLab si identifiable, sinon `null` |

### Step 2 — Analyse fonctionnelle

Classer chaque tâche :

- **page** — une page / un écran identifié (Dashboard, Listing des épisodes, Paramètres…)
- **component** — un composant UI (store, resolver, header, drawer, modal…)
- **infra** — architecture / setup / intégration dans un existant (ex : Intégration dans l'univers Streaming)
- **feature** — un bloc fonctionnel non-page (API, backend, service, chantier métier transverse)
- **action** — une action métier (créer, éditer, supprimer, distribuer…)

Détecter les **signaux de partage** : même composant présent sur plusieurs pages, store/resolver global, utilitaires communs.

### Step 3 — Regroupement en issues + checklist

Table de décision :

| Tâche détectée | Devenir |
|----------------|---------|
| Page | 1 issue `type: page` |
| Bloc fonctionnel non-page (API, backend, métier) | 1 issue `type: feature` |
| Composant d'une seule page, simple | task dans la checklist de sa page |
| Composant partagé / chantier indépendant / complexe | 1 issue `type: component` (+ `rationale`) |
| Infra / setup / intégration | 1 issue `type: infra` (+ `rationale`) |
| Action métier d'une page | task dans la checklist de sa page |

Types d'issue (énumération fermée) : `page | feature | component | infra`.

- **Orphelins** (page absente ou ambiguë) : regrouper dans une issue `type: feature` « Setup & Architecture » ou « Divers » — jamais ignorés ; ces orphelins rattachés ne comptent pas comme `unmatched_rows`.
- **Agrégation** : somme des estimations par issue → `estimate_total` (en jours).

### Step 4 — Suggestions de regroupement MR

À l'intérieur de chaque issue, proposer un **découpage suggéré en MR** — jamais imposé, jamais créé.

**Priorité** (dans l'ordre) :

1. cohérence fonctionnelle ;
2. dépendances ;
3. proximité technique ;
4. taille raisonnable de MR ;
5. nombre de tâches (seulement en dernier recours).

**Regrouper quand** :

- tâches petites ;
- tâches fortement dépendantes ;
- même zone du code ;
- même composant / sous-système ;
- même comportement fonctionnel ;
- tâches difficiles à tester séparément ;
- changements qui ont du sens à reviewer ensemble.

**Éviter de regrouper** :

- plusieurs zones fonctionnelles sans rapport ;
- des tâches très grosses ;
- des changements qui rendent la MR difficile à reviewer ;
- des tâches pouvant avancer indépendamment si le regroupement crée un blocage.

**Heuristique de taille** : regrouper généralement **2 à 4 petites tâches** lorsqu'elles forment un lot cohérent — le nombre n'est pas le critère principal, la cohérence et la taille de la MR priment. Une tâche importante peut rester seule dans sa MR.

Chaque groupe porte un `reasoning` court et explicable (ex : « Même zone fonctionnelle », « Données et rendu étroitement liés »).

### Step 5 — Enrichissement

- **Issues existantes** : vérifier ce qui existe déjà avant de proposer (`glab issue list --search "<feature>" --output json`) et marquer/lier les doublons potentiels dans l'IssueSpec — ne jamais recréer une issue existante.
- **Figma** : rattacher les liens maquettes (colonne ou fournis par l'utilisateur) à chaque issue.
- **Contexte repo** : résoudre le ou les repositories via le **project registry** (section *Project resolution*) et l'issue routing ; ne jamais sélectionner arbitrairement un résultat de recherche. Si utile, déléguer une recherche à Explorer (stores existants, conventions, composants déjà en place) pour ancrer les checklists dans le code réel.
- **Dépendances** : ordonnancer — composants/infra avant les pages qui les utilisent → `depends_on`.

### Step 6 — IssueSpec

Format intermédiaire. Écrire `planning/<feature>/issuespec.json` :

```json
{
  "feature": "Podcast",
  "labels": ["feature::podcast"],
  "issues": [
    {
      "key": "dashboard",
      "title": "[Podcast] Dashboard",
      "type": "page",
      "figma": ["https://figma.com/file/..."],
      "tasks": [
        { "id": "store", "label": "Store Podcast", "estimate": null, "done": true, "figma": null, "assignee": null },
        { "id": "resolver", "label": "Resolver Podcast", "estimate": null, "done": true, "figma": null, "assignee": null },
        { "id": "statistics", "label": "Statistiques de la semaine", "estimate": "1 j", "done": false, "figma": "https://figma.com/file/...", "assignee": null },
        { "id": "distribution", "label": "Distribution", "estimate": "0.5 j", "done": false, "figma": null, "assignee": null },
        { "id": "episodes", "label": "Épisodes", "estimate": "0.5 j", "done": false, "figma": null, "assignee": null },
        { "id": "preview", "label": "Preview du dernier épisode", "estimate": "2 j", "done": false, "figma": null, "assignee": null },
        { "id": "empty-state", "label": "Dashboard vide", "estimate": "0.125 j", "done": false, "figma": null, "assignee": null },
        { "id": "header", "label": "Header Podcast", "estimate": "0.125 j", "done": false, "figma": null, "assignee": null }
      ],
      "estimate_total": "4.25 j",
      "mrGroups": [
        {
          "id": "structure",
          "title": "Structure et états de base",
          "taskIds": ["header", "empty-state"],
          "reasoning": ["Même zone fonctionnelle", "Petites tâches", "Reviewables ensemble"]
        },
        {
          "id": "analytics",
          "title": "Statistiques et distribution",
          "taskIds": ["statistics", "distribution"],
          "reasoning": ["Même section du dashboard", "Données et rendu étroitement liés"]
        },
        {
          "id": "episodes",
          "title": "Épisodes",
          "taskIds": ["episodes", "preview"],
          "reasoning": ["Même sous-système", "Preview dépend des épisodes"]
        }
      ],
      "depends_on": ["shared-player"],
      "rationale": null
    }
  ],
  "unmatched_rows": []
}
```

Invariants :

- union des `tasks` de toutes les issues + `unmatched_rows` = 100 % des lignes source ;
- `rationale != null` ⟺ `type ∈ {"component", "infra"}` ;
- chaque issue porte un champ `project` = **clé du project registry** (résolue en `gitlabPath` + `projectId`) ;
- champ optionnel `acceptanceCriteria` (3 à 6 critères dérivés des tâches/maquettes — jamais génériques) ;
- tout `taskId` référencé par un `mrGroups[].taskIds` existe dans les `tasks` de la même issue ;
- un `key` = un fichier draft ;
- un même `IssueSpec` régénère toujours les mêmes groupes (déterministe, aucun aléa).

### Step 7 — Draft GitLab (preview)

Écrire un fichier par issue : `planning/<feature>/draft/<key>.md`, plus un `index.md` de synthèse (titre, type, nb de tasks, estimé, dépendances, nb de MR suggérées).

Corps d'issue :

```markdown
## Objectif
<ce que couvre cette issue — la page ou le bloc fonctionnel>

## Checklist
- [ ] <tâche> — <durée estimée>

## Suggestion de découpage des MR

### MR — Structure et états de base
- Header Podcast
- Dashboard vide

### MR — Statistiques et distribution
- Statistiques de la semaine
- Distribution

## Maquettes
- <URL Figma>

## Dépendances
- <key / #123>

## Notes
<options, décisions, hors-périmètre>
```

Règles de rendu :

- **aucune section vide** : le renderer omet toute section sans contenu (`Notes`, `Dépendances`, `Points à clarifier`, `Notes techniques`, `Maquettes`, `Critères particuliers`, `Suggestion de découpage des MR`) — jamais de `## Notes` orphelin ni de placeholder du type « Pas de maquette spécifique » isolé dans une section ;
- **Critères d'acceptation** : section `## Critères d'acceptation` (3 à 6 **puces simples, jamais de checkbox**) insérée après le bloc « Total estimé », dérivée des tâches, de la page, des maquettes et du code existant — jamais des critères génériques copiés d'une issue à l'autre ; les zones d'ombre vont dans `## Points à clarifier`. Convention : `Checklist → éléments de progression GitLab` / `Critères d'acceptation → conditions de validation sans checkbox`. **Pourquoi** : les critères d'acceptation ne sont pas des tâches de développement et ne doivent donc pas fausser la progression native GitLab de l'issue — seul le travail issu du backlog compte dans « X of Y checklist items completed ».
- **Dépendances enrichies** : toujours `- #123 — [Podcast] Titre de l'issue liée` (numéro + titre), jamais un simple `- #123` ;
- la section `## Suggestion de découpage des MR` est **facultative** : l'omettre si le découpage est évident ou sans valeur ajoutée (KISS) ;
- items en **bulles simples** (pas de cases à cocher) — ce sont des suggestions, pas des tâches ;
- toujours présentées comme des **suggestions** : l'humain peut fusionner deux groupes, séparer un groupe, déplacer une tâche ou ne pas suivre.

**Sortie console attendue lors d'un `prepare`** :

```text
Issue proposée : [Podcast] Dashboard

8 tâches détectées (2 réalisées)

Suggestion de découpage :

MR 1 — Structure et états de base
- Header Podcast
- Dashboard vide

MR 2 — Statistiques et distribution
- Statistiques de la semaine
- Distribution

MR 3 — Épisodes
- Épisodes
- Preview du dernier épisode

Granularité :
- Issue : page
- Tasks : 8
- MR suggérées : 3
```

### Step 8 — Validation humaine (STOP)

Présenter le draft et attendre un feu vert explicite (« OK », « go », « crée »). Tant que la validation n'est pas explicite, **ne rien créer**.

Traitement des retours :

- fusion / scission d'issues → rejouer les steps 3–6 ;
- ajustement des regroupements MR (fusionner deux groupes, séparer un groupe, déplacer une tâche, ignorer la suggestion) → mettre à jour `mrGroups` et le draft ;
- renommages, durées, assignees, labels → mettre à jour l'IssueSpec et le draft.

### Step 9 — Création des issues (seulement)

Dans l'ordre des dépendances (composants/infra d'abord, puis pages). Le **corps du draft prime** : le skill `gitlab-issues` fournit uniquement les conventions CLI (flags, labels, cross-références) — ne pas lui emprunter son format de description (Summary/Details) au risque de mixer les styles.

**API** : préférer `glab api` avec l'**ID numérique** du project registry (`glab api "projects/1001/issues" -f title=... -f description=... -f labels=feature::podcast`) — voir *Project resolution* pour les pièges d'encodage des paths.

```bash
glab issue create \
  --title "[Podcast] Dashboard" \
  --description "$(cat planning/podcast/draft/dashboard.md)" \
  --label "feature::podcast"
```

- Après création des issues amont, remplacer les références `<key>` par les vrais numéros (`#123`) dans les descriptions via `glab issue update <n> --description ...` ; `group/project#123` pour le cross-repo.
- Optionnel : `/estimate <durée>` en commentaire pour l'estimate GitLab.
- Rattacher les MRs existantes le cas échéant (référence `!456` dans la description).
- **Ne jamais créer de MR** à partir des groupes suggérés : les MRs seront créées librement pendant l'implémentation.
- Terminer par le récap : URLs des issues créées. Persist le mapping `key → {iid, url, project}` dans `planning/<feature>/created.json` (base de l'audit/sync).
- **Relations structurées** : pour chaque dépendance réelle, créer un lien GitLab (`is_blocked_by` de l'aval vers l'amont) ; `relates_to` pour les issues jumelles cross-repo. Jamais de relation inventée parce que deux tâches « semblent proches ». Le lien s'ajoute à la dépendance Markdown (`- #N — [titre]`), il ne la remplace pas.
- **Estimation native GitLab** : V2 — ne pas la renseigner par défaut. Convention candidate (1 j = 8 h, déduite de « 0.125 j = 1 h » du tableau) à valider avec l'équipe ; le time tracking est inutilisé dans les projets concernés (constaté : `time_estimate = 0` sur toutes les issues).

## Idempotence — create / update / unchanged

Toute issue créée porte un **stable ID** en tête de description, invisible dans le rendu :

```markdown
<!-- aurora:planner <feature>/<key> -->
```

Correspondance : `IssueSpec stable ID` → issue GitLab existante (recherche par marqueur, sinon par titre exact + label) → diff → update uniquement si diff. Deux runs successifs sur une issue à jour → `unchanged`, zéro écriture. **Jamais** : IssueSpec → nouvelle issue quand l'issue existe déjà.

## Modes audit / sync

Après création (ou à tout moment), `sync_issues.py` audite et synchronise les issues d'une feature :

```bash
python3 ~/.config/opencode/skills/gitlab-feature-planner/sync_issues.py \
  --feature-dir ~/Desktop/planning/podcast --mode audit   # rapport, aucune écriture
python3 ~/.config/opencode/skills/gitlab-feature-planner/sync_issues.py \
  --feature-dir ~/Desktop/planning/podcast --mode sync    # applique descriptions + relations
```

- **audit** : issues trouvées, projets résolus via registry, diffs attendus (marqueur, critères, sections vides supprimées, dépendances enrichies, relations manquantes) — présenté sous forme de rapport `~ update / = unchanged / ! erreur` ;
- **sync** : applique les mises à jour de description et crée les liens `is_blocked_by` manquants (idempotent) ;
- une issue dans un projet incompatible avec son `IssueSpec` est signalée (`detect_wrong_project`) — déplacement manuel à arbitrer avec l'utilisateur, jamais un double-création silencieuse.

## Exemple Podcast — granularité attendue

**Issues pages / fonctionnalités** : Intégration dans l'univers Streaming, Univers Podcasts, Création d'un podcast, Dashboard, Listing des épisodes, Création/édition d'un épisode, Statistiques, Lecteurs, Distribution, Paramètres, Page publique Podcast, Page publique Épisode.

**Issues composants / infra** : Setup Player, Composants partagés Player.

**Tout le reste** (stores, resolvers, drawers, modales, actions unitaires) → checklists internes, avec suggestions de regroupement MR à l'intérieur de chaque issue.

## Anti-patterns

- ❌ 40 lignes Excel → 40 issues GitLab
- ❌ 1 tâche = 1 MR — ou l'inverse : une règle fixe « N tâches par MR »
- ❌ Créer des MR automatiquement à partir des suggestions de découpage
- ❌ Une issue fourre-tout « Misc » qui avale tout sans logique
- ❌ Regrouper dans une MR des zones fonctionnelles sans rapport
- ❌ Formules Excel verbatim (`=SUM(...)`) dans les titres de checklist
- ❌ Création directe dans GitLab sans draft ni validation
- ❌ Lignes de tableau perdues sans trace
- ❌ Redécouvrir un projet GitLab à chaque run (sans registry), ou passer un path brut à `glab api`
- ❌ Une issue multi-repos (ou une issue créée dans le mauvais repo)
- ❌ Section vide (`## Notes` sans contenu) ou placeholder isolé
- ❌ Dépendance nue `- #6` sans titre
- ❌ Critères d'acceptation génériques identiques d'une issue à l'autre
- ❌ Recréer une issue existante au lieu de la mettre à jour

## Tests

```bash
python3 -m unittest discover -s skills/gitlab-feature-planner/tests
```

Couverture : project resolution (alias / path / ID / displayName, ambiguïté, absence, mapping mémorisé), transformations du renderer (marqueur idempotent, critères, sections vides, dépendances enrichies, préservation Total estimé + MR suggestions), idempotence (2e run → unchanged), détection de mauvais projet. Compat : Python ≥ 3.9 (stdlib uniquement).
