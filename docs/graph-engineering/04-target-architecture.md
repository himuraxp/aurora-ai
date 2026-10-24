# Architecture cible — Execution Graph Core d'Aurora

> Carte Trello `DuTvF4fZ` · Itération 1 · 2026-10-24 · Livrable 4/5
> Issue du brainstorming Aurora ↔ ChatGPT : **APPROVED WITH CHANGES** (cf. `02-brainstorming-chatgpt-synthesis.md`). Document de conception — l'implémentation est explicitement gated (itération 2+, validation humaine).

## 1. Principe directeur

> « Transformer ce qui fonctionne déjà dans Aurora en une infrastructure d'orchestration commune, plutôt que construire un nouveau moteur qui reproduirait les capacités existantes. » (ChatGPT, tour 1)

Le problème n'est pas l'absence de Graph Engineering : **c'est la fragmentation des cinq contrats d'exécution** (task-workflow, deepwork, council, meeting, loop-engineering). La cible n'est donc **pas un 6ᵉ moteur** mais un **noyau commun** dont les skills existantes deviennent progressivement clientes.

```txt
                    ┌─────────────────────────────┐
                    │      Aurora Supervisor      │
                    │  planification conversationnelle,
                    │  coordination, arbitrage      │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    Execution Graph Core     │
                    │  TransitionEngine  (états légaux,  │
                    │    invalidations — logique tw_state)│
                    │  StateRepository   (persistance,    │
                    │    concurrence, leases, fencing)    │
                    │  EventLog          (journal atomique)│
                    │  EvidenceStore     (preuves, fraîcheur)│
                    │  GraphScheduler    (DAG, deps,      │
                    │    boucles bornées, budgets)        │
                    └──┬──────┬──────┬──────┬──────┬─┘
                       │      │      │      │      │
                 task-workflow deepwork council meeting loop-eng
                 (logique métier de chaque skill conservée)
```

**Frontières** (contraintes de la carte) :

- **KG ≠ EG** : l'Execution Graph Core partage *logiquement* rien avec le Knowledge Graph (aurora-memory). Séparation physique possible dans la même instance PostgreSQL via schémas et droits distincts — jamais de tables partagées.
- **Déterministe / LLM** : seuls les nœuds d'exécution et d'évaluation sont LLM ; toutes les **transitions** et **autorisations** sont déterministes.
- **Réutilisation** : TransitionEngine = la logique métier de `tw_state.py` (transitions, `evidence_guard`, invalidation, idempotence) ; StateRepository = nouveau backend derrière le même contrat.

## 2. Le contrat d'exécution à trois niveaux (Q3, validé)

| Niveau | Nature | Décide de | Exemples |
|---|---|---|---|
| **1. Preuve d'exécution technique** | déterministe | le processus a-t-il tourné correctement ? | exit code 0, timeout, format de sortie, artefacts produits, hashes, signatures |
| **2. Évaluation sémantique** | LLM encadré | le résultat est-il satisfaisant ? | review, council, cohérence avec les critères — verdict **structuré** : `{verdict, findings[{severity, criterionId, evidenceRef}], confidence}` — le moteur valide la **structure et les références**, jamais la vérité du jugement |
| **3. Autorisation de transition** | déterministe | le passage d'état est-il permis ? | preuves présentes **et fraîches** (codeSignature), budgets respectés, approbation humaine requise/présente (product-authority) |

**Quatre types d'échec, quatre budgets indépendants** :

| Échec | Traitement | Budget |
|---|---|---|
| technique transitoire (crash, timeout, format) | retry de l'exécution | `maxAttempts` + backoff |
| qualité (review insatisfaisante) | itération de correction | `maxIterations` |
| preuve invalide / périmée | transition bloquée (purge des preuves — logique `invalidate` existante) | — (jamais auto-résolu) |
| permission manquante | approbation humaine ou refus explicite | — (jamais auto-résolu) |

Plafonds transverses recommandés : coût tokens, durée cumulée, concurrence (`resourcePolicy`).

## 3. Contrats de données (issus du débat — extraits conceptuels, pas du code final)

### NodeDefinition — ce qui doit être exécuté

```txt
NodeDefinition {
  schemaVersion        // évolution des contrats sans casser les workflows actifs (P0)
  id, type             // type: agent | tool | human | gate
  deps[]               // DAG
  inputs, outputSchema // sorties typées
  permissions[]        // contrôlées au niveau du nœud (attestation product-authority)
  successCriteria[]    // critères machine-vérifiables quand possible
  evidencePolicy       // preuves attendues + leur fraîcheur (P0)
  retryPolicy{maxAttempts, backoff}
  timeoutSeconds
  resourcePolicy       // coût, tokens, concurrence, durée (P1)
  effectPolicy         // (P0) mode: read|write ; idempotencyKey? ; compensation? ;
                       //          onUncertainOutcome: reconcile|block
}
```

### NodeExecution — ce qui s'est réellement passé

```txt
NodeExecution {
  runId, nodeId, attempt
  status           // pending | running | blocked | completed | failed | cancelled
  executorId?, leaseToken?   // réservation exclusive + fencing
  startedAt?, completedAt?
  inputFingerprint           // réconciliation d'effets externes
  outputArtifactRefs[], evidenceRefs[]
  error?
}
```

### GraphDefinition

Identité propre + **version immuable au lancement** de chaque exécution. Les nœuds ne modifient pas librement la topologie en cours de route ; toute modification produit un **nouveau plan validé** avec lien de filiation vers le précédent.

### Responsabilités du noyau (séparation validée en Q2)

| Composant | Responsabilité | Backend itération pilote | Backend cible |
|---|---|---|---|
| TransitionEngine | états légaux, règles de passage, invalidations | logique `tw_state.py` réutilisée | idem |
| StateRepository | persistance, concurrence, réservation, leases | JSON + garde canonique + claim (mono-exécuteur) | PostgreSQL : réservation exclusive, lease + échéance + fencing, concurrence optimiste |
| EventLog | journal des transitions et incidents | `events.jsonl` append-only | journal **atomiquement lié** aux changements d'état (même transaction SQL) |
| EvidenceStore | preuves, fraîcheur, purge | `testResults/qaResults/...` + `codeSignature` | idem, FK vers runs |

### Trois couches (affinage tour 3 du débat)

```txt
Execution Graph Core    ordonnanceur, transitions, dépendances, preuves,
                        permissions, tentatives, reprise
        ▲
Workflow Adapters       logique métier propre à chacun des 5 protocoles
        ▲               (préserve le read-only de council, les garanties de meeting)
Executors               OpenCode (processus/sessions), CLI, MCP, outils locaux,
                        approbations humaines
```

Un nœud `gate` (ex. council) retourne un verdict **sans** devenir responsable des transitions globales du workflow.

### Ajustements P0 du débat (tour 3 — intégrés au contrat)

1. **Exclusion mutuelle réelle (P0.1)** : le claim actuel est une convention — le pilote exige un **verrou interprocessus atomique** couvrant les transitions, un seul ordonnanceur actif par `runId`, des écritures atomiques de l'état, la détection des exécutions interrompues.
2. **Taxonomie d'effets externes (P0.2)** : trois catégories — `safe` (rejeu sous préconditions vérifiées), `reconcile` (vérifier l'effet réel avant décision), `block` (intervention requise si incertain). Nuances : un `sessionID` OpenCode ne garantit pas l'absence de doublon à la recréation ; `git commit` n'est pas idempotent intrinsèquement ; GET-before-POST suppose que l'API permet d'identifier l'opération de façon fiable.
3. **`inputFingerprint` générique (P0.3)** : la signature git `sha1(HEAD + git status)` reste un **composant** de l'empreinte de fraîcheur, jamais la totalité — l'empreinte couvre les dépendances réellement pertinentes du nœud (config externe, versions d'outils, artefacts référencés).

Enrichissement du contrat de preuve attendu en RFC : `EvidenceRecord` et `EffectRecord` viennent s'ajouter à `GraphDefinition` / `NodeDefinition` / `NodeExecution` ; cas à traiter explicitement : un nœud techniquement réussi dont le **résultat devient invalide** avant l'exécution de ses descendants (invalidation transitive).

## 4. Effets externes — la règle de réconciliation (héritage ADR-017)

Scénario de référence (validé dans le débat) : effet externe confirmé par l'API, worker plante avant enregistrement du succès → **jamais de rejeu aveugle**. Au redémarrage : identifier l'opération (`idempotencyKey`), **réconcilier** (GET-before-POST — pattern déjà implémenté pour Trello dans `trello_comment.sh`, à généraliser à GitLab et aux écritures Infomaniak) ; si réconciliation impossible → `blocked` à résultat incertain. Classification actuelle des effets externes : cf. synthèse du brainstorming §3 (Q7) — **les écritures Infomaniak et la création de MR GitLab sont les zones sans idempotence à couvrir en priorité**.

## 5. Adoption progressive — stratégie de convergence (sans dénaturation)

| Étape | Action | Ce qui change / ne change pas |
|---|---|---|
| 1 | Extraire TransitionEngine du code de `tw_state.py` (même logique, importable) | `task-workflow` inchangé fonctionnellement |
| 2 | Implémenter StateRepository JSON + EventLog derrière l'interface | pilote mono-exécuteur |
| 3 | Définir GraphDefinition + scheduler DAG minimal (topo-sort, réservation) | — |
| 4 | **Pilote** : un workflow réel sur le noyau (proposition : analyse de MR avec implémentation → tests → review — cf. plan d'implémentation) | sans migration de task-workflow |
| 5 | brancher progressivement les skills : d'abord loop-engineering (le plus proche), puis meeting/council (gates → nœuds `gate`), deepwork en dernier | chaque skill garde sa logique métier |
| 6 | migration StateRepository → PostgreSQL au besoin DAG multi-worker (schéma EG distinct du KG) | pas de réécriture des données historiques task-workflow |

Chaque étape est **réversible** (aucune suppression du chemin existant avant validation de la suivante) — conforme à « plan d'implémentation incrémental et réversible » de la carte.

## 6. ADR draft — à valider en itération 2

```md
ADR-0XX — Noyau d'exécution en graphe (Execution Graph Core) pour Aurora
Statut : proposed (draft itération 1)
Contexte : cinq contrats de cycle de vie hétérogènes (task-workflow, deepwork,
council, meeting, loop-engineering) ; pas de DAG ni de dépendances inter-tâches ;
état d'exécution fragmenté ; observabilité éclatée ; permissions statiques par agent.
Décision :
  1. Noyau commun TransitionEngine/StateRepository/EventLog/EvidenceStore/GraphScheduler,
     clients progressifs (les 5 skills conservent leur logique métier).
  2. Contrats NodeDefinition / NodeExecution / GraphDefinition (versionnés, immuables
     à l'exécution, filiation des plans).
  3. Contrat d'exécution à 3 niveaux (technique déterministe / évaluation sémantique
     LLM encadrée / autorisation de transition déterministe) avec budgets indépendants.
  4. Effets externes : effectPolicy obligatoire, réconciliation avant rejeu
     (GET-before-POST généralisé), blocked à résultat incertain sinon (ADR-017).
  5. Backends : JSON + garde canonique pour le pilote mono-exécuteur ; PostgreSQL
     (schéma EG distinct du KG) requis avant DAG multi-worker durable.
Alternatives rejetées : LangGraph comme moteur central (coût d'intégration/duplication,
  état hors des structures Aurora ; facultatif pour sous-graphes cognitifs internes) ;
  Temporal pour l'itération 1 (coût opérationnel, absence de besoin de durabilité
  avancée démontré — le replay Temporal ne réexécute pas les appels LLM terminés,
  cf. brainstorming tour 1) ; 6e moteur autonome (dénaturerait l'existant).
Conséquences : un seul contrat de preuve transverse ; observabilité unifiée par
  exécution ; reprise inter-session réelle ; coût de refactoring progressif des 5 skills ;
  exigence de discipline schemaVersion dès le premier nœud.
```

*L'emplacement définitif de l'ADR (aurora-core/docs/adr/ vs aurora-ai) est tranché dans le plan d'implémentation — la décision porte sur le runtime (aurora-core), la MR documentaire courante vit dans aurora-ai.*
