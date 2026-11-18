---
name: create-staging
description: "Provision a staging environment on a web-based staging tool (tool URL, project catalog, naming, bundles and variables live in a PRIVATE config, never in this repo) from a branch name or a merge-request link — resolve the MR to its source branch, derive a collision-free staging name, create the staging through the tool UI with explicit clicks (never Enter), reconcile the tool-prefilled variables against the team's template with a SHA-256 digest gate, verify on 3 levels (config digest, deployment, HTTP access URLs in the final report), and attach twin branches later when sibling tasks ship. Use when the user says 'create-staging', 'crée un staging', 'monte un staging', 'staging pour cette MR', 'staging depuis cette branche', wants a staging environment for a feature branch or MR, or asks to attach a twin branch to an existing staging."
---

# Create Staging — provisionnement d'un environnement de staging piloté UI

Crée un staging **complet** (projets, branches, variables d'environnement) sur un
outil de staging web à partir d'un nom de branche ou d'un lien de merge request.
La ressource est ensuite **suivie** (manifeste privé) pour la reprise, la
réconciliation et l'**attach tardif** des branches jumelles.

Leçon terrain (pilot réel 2026-11-12) : l'outil pré-remplit ~30 variables par
défaut à la création — l'injection n'est **jamais** une saisie ex nihilo, c'est
une **réconciliation par diff** (no-op sur conforme, update sur divergent, add
sur absent), prouvée par digest SHA-256. Le champ Name tronque silencieusement
au-delà de sa longueur maximale : c'est le compilateur qui tronque, pas le
formulaire. Et une feature multi-repos a des branches jumelles qui **n'existent
pas encore** au provisionnement initial : le staging est une ressource
évolutive, l'attach tardif fait partie du contrat.

## Frontière repo public / config privée (OPSEC)

- **Ce skill est générique** : aucune URL interne, aucun domaine, aucun nom de
  projet réel, aucune valeur de variable — tout vit dans la **config privée**.
- **Config privée** : `~/.config/opencode/staging/config.json` (0600) —
  baseUrl de l'outil, adapter, naming, mapping repos → projets, bundles,
  variables fixed/derived/empty, access patterns, paramètres de vérification.
  Le schéma public est `config.schema.json` ; l'exemple fictif testé est
  `config.example.json`.
- **État privé** : `~/.local/state/aurora/staging/<ressource>/` — `plan.json`
  (manifeste de reprise + machine d'état) et `journal.jsonl` (preuves datées).
- Toute évolution du schéma passe par le schéma public + l'exemple fictif
  testé — jamais par un fixture contenant des données réelles.

## CLI

```
/create-staging <branche | URL-MR> [--name X] [--dry-run]
/create-staging --attach <repo>:<branche> --staging <name>
/create-staging --resume <plan-id>
```

- `--name X` : override du nom dérivé (fail-closed sur collision, aucun
  suffixe automatique).
- `--dry-run` : résolution + plan + compilation + collision check, aucune
  écriture.
- `--attach` : monter une branche sur un projet du staging existant (la tâche
  jumelle a été développée après la création).

## Machine d'état

```
PLANNED → CREATED → CONFIGURING → CONFIGURED → VERIFYING → READY
                                                      ↘ CONFIGURED_NOT_READY
                       toute étape ↘ BLOCKED / FAILED (preuve + point de reprise)
```

Un timeout ne produit **jamais** un READY. Le manifeste `plan.json` porte
l'état, les preuves par niveau et le digest des variables.

## Procédure

1. **Config** — lire la config privée ; résoudre l'adapter (navigateur debug).
2. **Résolution de l'entrée** — branche seule = repo courant ; URL MR = API
   GitLab (`source_branch`, `target_branch`, état opened) via preflight token.
   Vérifier : MR non ambiguë, branche source exacte, repo identifié.
3. **Nommage** — slug de la branche (strip des préfixes `feat/`, `fix/`, …),
   **tronquer côté compilateur** à `maxLength` sur frontière de tiret, override
   explicite prioritaire. Garde : la valeur du champ après saisie DOIT égaler
   le nom attendu (le champ tronque silencieusement).
4. **Collision** — scan du listing de l'outil ; présence = BLOCKED (fail-closed,
   aucun suffixe automatique). Vérifier le **préfixage idempotent** : la
   ressource infra = display name préfixé par `resourcePrefix` **si absent**.
5. **Bundle** — repo résolu → projet cible (`branchPolicy: source`) + projets
   associés (défaut). Le Core verrouillé vient avec ses branches défaut.
6. **Compilation des variables** — `compile_variables.py` (fonction pure) :
   nom + config → paires triées + digest SHA-256 canonicalisé. Aucun accès
   navigateur requis ; le test self-testé doit passer.
7. **Inspection distante read-only** — listing des stagings, résolution de
   collision, détection d'état partiel d'une ressource revendiquée.
8. **Plan d'exécution** — présenter projets, branches, nom, compte de
   variables, créations/updates prévus. La création et toute modification
   sensible exigent un GO explicite de l'opérateur.
9. **Création** — formulaire Create : saisie du Name, toggles des projets,
   branche source via le combobox du projet concerné. Bouton Create désactivé
   tant que le formulaire est incomplet. Prochain état : CREATED.
10. **Attente du provisionnement initial** — statut de l'outil ; l'édition des
    variables est verrouillée jusqu'à l'état prêt de la ressource. Timeout =
    BLOCKED (jamais READY).
11. **Réconciliation des variables** — l'outil pré-remplit un jeu par défaut ;
    calculer le diff contre le plan : conforme = no-op, divergent = update,
    absent = add. **Gate pré-submit** : digest SHA-256 canonicalisé du
    formulaire === digest du plan. Un seul clic Update (une transaction).
    Post-update : re-provisionnement transitoire de l'outil, jamais interprété
    comme une panne.
12. **Vérification 3 niveaux + rapport** — L1 config (relecture intégrale des
    paires depuis la page de détail, digest = plan) ; L2 déploiement (état
    prêt de la ressource + workloads en bonne santé) ; L3 fonctionnement
    (résolution DNS + HTTP sur les URLs dérivées, idéalement comparées
    endpoint-par-endpoint à un staging de référence). **Le rapport final DOIT
    inclure les URLs d'accès** (pattern `access.homePattern` de la config,
    `{customerId}` = paramètre d'usage de l'opérateur) — c'est le livrable que
    l'opérateur consomme.

## Invariants P0

- **JAMAIS de press_key Enter** dans les formulaires Create/Edit de l'outil :
  Enter = submit + redirection. Clics explicites uniquement.
- **Un seul clic Update par transaction d'injection** — le bouton Update
  soumet le formulaire ENTIÈR (branches incluses) : vérifier l'état pré-submit
  avant Update.
- **Aucune écriture sans plan résolu et GO opérateur** ; staging non
  revendiqué (aucun manifeste local) = jamais modifié, adoption = décision
  opérateur.
- **Aucun succès sans relecture distante** des variables ; aucun READY sans
  config + disponibilité validées.
- **Zéro donnée interne dans le repo public** — la moindre donnée réelle
  (URL, domaine, IP/CIDR, nom de projet, valeur de variable) va dans la
  config privée, jamais dans un fichier versionné.
- **Reprise idempotente** : re-run = diff état attendu vs observé ; verrou
  local par nom ; re-vérification distante immédiate avant écriture ; pas de
  rollback destructif.
- **Adaptateur API absent** : piloter l'UI ; la découverte d'endpoints backend
  est interdite sans contrat validé et autorisé explicitement en interne.

## Patterns de pilotage UI (fragiles, éprouvés)

- Dropdowns/menus : le clic DOM émulé déclenche le listener click-outside et
  referme instantanément → **clic natif** (tool browser-debug) uniquement.
- Options des dialogs de sélection de branche : absentes du snapshot
  d'accessibilité → localiser par texte dans le dialog puis clic DOM natif sur
  l'élément option.
- Après chaque ajout de paire de variables : re-snapshot (les identifiants
  changent).
- Vérification système : re-lire `input.value` du champ Name après saisie ;
  re-snapshot pré-submit et digest avant Update.
- Timeout MCP navigateur : jamais de pause > 25 s par appel côté page ;
  les boucles d'attente se coupent par appels courts.

## Attach tardif de branches jumelles

Une feature multi-repos a souvent des branches jumelles qui **n'existent pas
encore** au provisionnement initial. Le cycle : détecter les candidates
(recherche GitLab du slug / du préfixe produit dans les repos du bundle) →
**proposer** à l'opérateur (jamais d'application auto : des branches
homonymes non liées existent) → monter la branche sur le projet du staging
existant via le formulaire Edit (même transaction UI) → Update → vérification
3 niveaux → journal. Le manifeste `plan.json` du staging porte les projets et
leurs politiques de branche : l'attach = réconciliation d'un champ de plus.

## Config (schéma public, valeurs privées)

Voir `config.schema.json` (contrat) et `config.example.json` (exemple fictif
testé par le compilateur). Sections : `tool` (baseUrl, adapter),
`naming` (resourcePrefix, stripBranchPrefixes, maxLength), `repositories`
(mapping repo → projet du catalogue), `bundles` (projets + branchPolicy),
`environment` (defaultDomainPattern, managedKeys, fixed, derived, empty),
`access` (homePattern avec `{customerId}`), `verification` (intervalle +
timeout).
