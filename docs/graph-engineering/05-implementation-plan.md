# Plan d'implémentation — Graph Engineering pour Aurora

> Carte Trello `DuTvF4fZ` · Itération 1 · 2026-10-24 · Livrable 5/5
> Issue du brainstorming : **GO itération 2 = conception des contrats et stratégie de convergence. NO-GO migration générale / multi-worker avant validation des invariants.** Ce document découpe le chemin complet, avec des points d'arrêt explicites.

## Rappel des garde-fous (issus de la carte et du débat)

1. Aucune modification structurelle sans validation explicite (contrainte carte + gates PO à chaque itération).
2. Réutilisation > réécriture ; compatibilité des skills existants préservée à chaque étape.
3. KG ≠ EG — jamais de tables partagées.
4. Frontière déterministe/LLM — les 3 niveaux du contrat d'exécution (cf. `04-target-architecture.md` §2).
5. Chaque étape est réversible ; un échec de validation d'invariant = retour à l'étape précédente, pas un contournement.

## Itération 2 — RFC d'architecture (prochaine session, GO obtenu)

**Livrable attendu (débat tour 3) : une RFC, pas du code de production.** Contenu obligatoire :

1. **Contrats complets** : `GraphDefinition`, `NodeDefinition`, `NodeExecution`, `EvidenceRecord`, `EffectRecord` — schémas formels + validations.
2. **Invariants de transition** — y compris le traitement des cas où un nœud termine techniquement avec succès mais dont le résultat devient **invalide avant l'exécution de ses descendants** (invalidation transitive).
3. **Comportement de reprise** — reprise sans réexécution des nœuds à preuves valides.
4. **Matrice des responsabilités** entre le noyau (Core) et les cinq protocoles (Workflow Adapters), par invariant.
5. **Scénarios de validation du prototype** — les **6 propriétés mesurables** convenues : (1) DAG ≥ 2 branches indépendantes + convergence ; (2) reprise sans réexécution des nœuds valides ; (3) invalidation transitive des descendants ; (4) boucle de correction bornée après review défavorable ; (5) interruption sûre avant effet externe incertain ; (6) exclusion mutuelle effective entre deux sessions reprenant le même workflow.
6. **Intégration des 3 P0** : verrou interprocessus atomique (P0.1), taxonomie safe/reconcile/block des effets (P0.2), `inputFingerprint` générique (P0.3).
7. **Stratégie de migration progressive** — adoption par skill, shadow-run, rollback par étape.

**Arrêt obligatoire** : la RFC est soumise à ChatGPT (boucle coworking) puis validation humaine avant itération 3. 

**Garde-fous itération 2** : pilote en écritures externes **locales maîtrisées** uniquement ; workflow pilote = analyse → implémentation → review.

## Itération 3 — Noyau minimal + pilote (après validation itération 2)

| Étape | Contenu | Preuve attendue | Rollback |
|---|---|---|---|
| 3.1 | Extraire `TransitionEngine` du code de `tw_state.py` (même logique, module importable) + tests unitaires de transition portés | tests verts équivalents à la suite existante | les 2 fichiers coexistent |
| 3.2 | `StateRepository` JSON (garde canonique, claim) + `EventLog` derrière interface | suite + e2e sur dépôt temporaire (motif des tests `tw_state.py`) | interface pointe sur l'ancien code |
| 3.3 | `GraphScheduler` minimal : topological sort, réservation, exécution séquentielle (mono-worker) | tests scheduler + dry-run du pilote | module isolé |
| 3.4 | Implémenter les contrats NodeDefinition/NodeExecution (schemaVersion dès le premier nœud) | validation de schéma testée | — |
| 3.5 | **Pilote** : workflow d'analyse de MR sur le noyau, en parallèle du système actuel (shadow) | comparaison mesurée (métriques ci-dessous) | pilote désactivable par flag |
| 3.6 | ADR définitif (emplacement : **aurora-core/docs/adr/** — décision d'exécution appartient au runtime) + documentation | ADR validé humain | — |

**Gate** : comparaison pilote vs système actuel présentée à ChatGPT + GO humain avant toute généralisation.

## Itération 4 — Généralisation progressive (gate itération 3 franchie)

1. Brancher `loop-engineering` sur le noyau (le plus proche : callbacks → nœuds, compteur d'essais → budget `maxAttempts`).
2. Brancher `meeting` (gate → nœud `gate`, verdict READY/CONDITIONAL/BLOCKED → conditions de transition).
3. Brancher `council` (délégation au noyau : dépendances, tentatives, permissions, preuves — les 3 sièges et l'arbitrage restent la logique métier du skill).
4. Fusionner la trajectoire de `deepwork` (dernier, le plus éloigné du contrat).
5. `task-workflow` migre son StateRepository vers PostgreSQL **seulement si** le besoin multi-worker est avéré (sinon le JSON reste, conformément à la décision Q2).
6. Retirer les doublons de preuve issus de l'ancien parcours (après validation de non-régression).

## Métriques du pilote (comparaison avant généralisation)

Définies dès l'itération 1 par ChatGPT, confirmées dans le débat :

- taux de réussite des workflows ;
- durée de bout en bout ;
- coût en tokens par exécution ;
- nombre de reprises (retries) et d'itérations de correction ;
- nombre d'interventions humaines ;
- (ajout débat) : incidents d'effet externe détectés/réconciliés — indicateur direct de la qualité de `effectPolicy`.

Source de mesure : EventLog du noyau (première valeur de l'observabilité unifiée — l'audit a montré l'absence de métriques agrégées aujourd'hui).

## Risques et parades

| Risque | Parade |
|---|---|
| Régression d'un des 5 skills lors du branchement | adoption par skill avec shadow-run ; la logique métier ne bouge pas |
| Boucles coûteuses (tokens) | budgets indépendants + plafonds `resourcePolicy` + règle des 2 corrections conservée |
| Double effet externe au rejeu | `effectPolicy` + réconciliation GET-before-POST + `blocked` à incertain (ADR-017) |
| Dérive vers un 6ᵉ moteur | le noyau réutilise la logique de `tw_state.py` ; adoption progressive obligatoire ; gate PO par itération |
| Contrats instables | `schemaVersion` P0 dès le premier nœud ; GraphDefinition immuable à l'exécution, filiation des plans |

## Position de la présente MR dans ce plan

Cette MR (**itération 1**) livre les 5 documents d'architecture — **aucun code**. Les itérations 2+ démarrent après revue humaine de cette MR et consolidation du débat ChatGPT en cours.
