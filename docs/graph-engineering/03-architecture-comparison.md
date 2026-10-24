# Comparatif des architectures d'exécution pour Aurora

> Carte Trello `DuTvF4fZ` · Itération 1 · 2026-10-24 · Livrable 3/5
> Version 1 — à challenger dans le brainstorming Aurora ↔ ChatGPT avant consolidation.

## Candidats évalués

| # | Candidat | Nature |
|---|----------|--------|
| A | Supervisor / Workers (étendu) | évolution du modèle actuel d'Aurora |
| B | DAG / Parallel Workers | graphe acyclique à dépendances explicites |
| C | Evaluator / Optimizer (boucle) | boucle travail → évaluation → correction |
| D | Moteur natif maison (nœuds + transitions, persistance PostgreSQL) | base commune A/B/C |
| E | LangGraph (framework externe) | library Python/JS de graphes d'agents |
| F | Temporal (orchestration durable) | moteur de workflows durable, déjà présent dans l'environnement de dev |

## Critères (issus des contraintes de la carte)

1. **Réutilisation > réécriture** — capitaliser sur `tw_state.py`, goals PostgreSQL, council/meeting, ADRs 012-017.
2. **Complexité non justifiée interdite** — la solution la plus simple qui couvre les besoins réels.
3. **Compatibilité skills/workflows existants** — `task-workflow`, `deepwork`, `council`, `meeting`, `ai-cowork` continuent de fonctionner.
4. **KG ≠ EG** — pas de fusion mémoire sémantique / état d'exécution.
5. **Frontière déterministe / LLM** — les transitions et validations sont déterministes ; seuls les nœuds d'exécution sont LLM.
6. **Pas de modification structurelle sans validation explicite** — évolution incrémentale réversible.

## Analyse

### A. Supervisor / Workers (étendu)

Ce que fait déjà Aurora : l'orchestrateur délègue (`task`), consolide (`agent-output.v1`), arbitre.

- **+** : zéro migration conceptuelle ; le pattern est éprouvé ; s'adapte au graphe en devenant « planification en nœuds ».
- **−** : le superviseur reste la mémoire de l'exécution (contexte conversationnel) — reprise inter-session faible ; pas de dépendances inter-tâches ; observabilité non résolue.
- **Verdict** : **conserver comme mode de coordination**, insuffisant seul comme moteur.

### B. DAG / Parallel Workers

Dépendances explicites entre nœuds, exécution parallèle des tâches indépendantes, convergence vers validation.

- **+** : répond à la limitation n°2 de l'audit (pas de fork/join de tâches) ; modélise naturellement les audits multi-agents et les pipelines build→test→review ; le PARALLEL GATE en est déjà un cas particulier.
- **−** : acyclique — les boucles (retry, correction) doivent être modélisées à part (versions successives du graphe ou boucles Evaluator/Optimizer imbriquées).
- **Verdict** : **retenu comme structure de dépendances**, à compléter par C pour les boucles.

### C. Evaluator / Optimizer

Un nœud exécute, un nœud évalue, correction jusqu'aux critères — dans des bornes.

- **+** : correspond au PARALLEL GATE et à la règle des 2 corrections ; formalisable en boucle bornée (max iterations, critères de sortie) — déjà le modèle du council et de l'ai-cowork (verdict APPROVED).
- **−** : sans bornes strictes, boucle infinie possible (coût tokens) ; nécessite des critères d'acceptation machine-vérifiables (les preuves `exitCode: 0` de `tw_state.py` existent déjà).
- **Verdict** : **retenu comme primitive de boucle bornée**, réutilisant la garde de preuve existante.

### D. Moteur natif maison

Contrat de nœud (id, dépendances, entrées/sorties, permissions, critères de réussite) + moteur de transitions (pending/running/completed/failed/blocked) + persistance PostgreSQL séparée du KG + journal.

- **+** : **réutilise directement** `tw_state.py` (transitions fermées, codeSignature, invalidation, idempotence, journal), les goals PostgreSQL (transitions fermées), les ADRs 012/014/015/017 ; emplacement `workflows/` réservé ; contrôle total de la frontière déterministe/LLM ; pas de dépendance nouvelle ; évolution incrémentale par branche de graphe.
- **−** : tout est à construire hors noyau de transitions (scheduling, réhydratation, UI de suivi) ; risque NIH si les besoins dépassent le périmètre ; maintenance d'un moteur maison.
- **Verdict** : **base recommandée** — le noyau de transitions existe, testé ; le périmètre des besoins (documenté dans l'audit) reste couvert par une extension native.

### E. LangGraph

- **+** : primitives de graphe matures (nodes, edges, state, checkpointing, human-in-the-loop) ; communauté active ; accélère un prototype.
- **−** : **incompatibilité d'architecture profonde** — Aurora orchestre des processus OpenCode (CLI, MCP, sessions, skills) pas des fonctions Python in-process ; le bridging LangGraph→processus OpenCode réintroduit tout le travail que le moteur natif ferait, avec une dépendance lourde ; le state LangGraph vit dans son runtime, pas dans les structures Aurora (tw_state/PostgreSQL) ; conflit avec la contrainte « compatibilité skills existants » et « réutilisation plutôt que réécriture ».
- **Verdict** : **rejeté pour le cœur** ; source d'inspiration pour les primitives (interrupt, checkpointer).

### F. Temporal

- **+** : durabilité réelle (reprise après crash, retry policy, timers, signaux = interruptions humaines), déjà présent dans l'environnement de développement ; observable par construction. **Précision issue du débat (tour 1)** : le replay de Temporal ne réexécute pas les appels LLM terminés — leurs résultats sont enregistrés dans l'historique des Activities ; c'est le code d'orchestration déterministe qui est rejoué. Le non-déterminisme LLM n'est donc **pas** un argument de rejet.
- **−** : les Activities interrompues (résultat non enregistré) peuvent être réessayées avec un nouveau coût LLM ou un effet externe répété — l'encapsulation idempotente des effets reste nécessaire ; dépendance d'infrastructure (service Temporal à opérer) ; le pont vers l'orchestrateur conversationnel (OpenCode, pas un worker) reste à construire ; complexité significative vs besoin actuel (itération 1 = documents).
- **Verdict** : **rejeté pour l'itération 1 — pour des raisons de coût opérationnel et d'absence de besoin démontré de durabilité avancée** (justification corrigée suite au brainstorming, cf. `02-brainstorming-chatgpt-synthesis.md` §2). Candidat à réévaluer si ces besoins deviennent réels ; la frontière nœud LLM / Activity déterministe devra alors être documentée dans l'ADR.

## Synthèse comparative

| Critère | A Superv/Workers | B DAG | C Evaluator/Opt | D Natif | E LangGraph | F Temporal |
|---|---|---|---|---|---|---|
| Réutilisation de l'existant | ●●● | ●● | ●●● | ●●● | ● | ● |
| Complexité ajoutée | ●●● (faible) | ●● | ●●● (faible) | ●● | ● | ● (élevée) |
| Compatibilité skills | ●●● | ●●● | ●●● | ●●● | ● | ●● |
| Dépendances inter-tâches | ● | ●●● | ● | ●●● | ●●● | ●●● |
| Boucles bornées | ●● | ● (cyclique interdit) | ●●● | ●●● | ●●● | ●● |
| Reprise / durabilité | ● | ●● | ●● | ●●● | ●● | ●●● |
| Frontière déterministe/LLM | ●● | ●●● | ●●● | ●●● | ●● | ●● (rejeu coûteux) |
| Dépendance externe nouvelle | ●●● | ●●● | ●●● | ●●● | ● (lourde) | ● (serveur) |
| Observabilité unifiée | ● | ●● | ●● | ●●● | ●● | ●●● |

## Recommandation (pré-brainstorming)

**Hybride D + A + B + C** : un **moteur de transitions natif** (base D, construit sur `tw_state.py` + PostgreSQL, séparé du KG) qui exécute des **graphes DAG bornés** (B) avec des **boucles Evaluator/Optimizer** (C) comme primitives de correction, le tout coordonné par le **Supervisor** actuel (A) qui reste l'interface conversationnelle. LangGraph et Temporal sont écartés pour le cœur, réévaluables ponctuellement.

*Ce comparatif est une position de départ à challenger dans la conversation de référence (Phase 2 de la carte) — voir `02-brainstorming-chatgpt-synthesis.md` pour le débat réel et ses conclusions.*
