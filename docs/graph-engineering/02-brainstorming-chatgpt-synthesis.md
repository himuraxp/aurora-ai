# Synthèse du brainstorming Aurora ↔ ChatGPT

> Carte Trello `DuTvF4fZ` · Itération 1 · 2026-10-24 · Livrable 2/5
> Conversation de référence : https://chatgpt.com/c/6adb9882-d0ac-83ed-a0a6-64eb14998189 — débat réel mené par Aurora via browser-debug (boucle ai-cowork).

## 1. Contexte pré-existant (avant la carte)

La conversation contient le brief théorique initial rédigé par ChatGPT à la demande de l'utilisateur :

- Évolution `Prompt → Context → Harness → Loop → Graph Engineering` — approches **complémentaires**, non générations successives.
- Composants d'un graphe : **Nodes / Edges / Shared State** ; capacités : exécution parallèle, routage conditionnel, reprise contrôlée, checkpoints, interruptions humaines.
- Architectures candidates : Supervisor/Workers, DAG/Parallel Workers, Evaluator/Optimizer.
- Introduction progressive recommandée : contrat de nœud → moteur de transitions minimal → persistance PostgreSQL séparée du KG → premier workflow réel (analyse de MR) → mesure.
- Distinction posée dès le départ : **Knowledge Graph (ce qu'Aurora sait) ≠ Execution Graph (ce qu'elle doit faire)**.
- Note de ChatGPT à l'utilisateur : prévoir un **arrêt obligatoire après l'audit** (constats présentés dans la conversation, débat, GO avant implémentation) — respecté par ce workflow (MR documentaire, gate PO).

## 2. Tour 1 — Audit présenté, position initiale challengée

**Ce qu'Aurora a publié** : synthèse de l'audit (`01-architecture-audit.md`) — task-workflow déjà graphe linéaire à 9 nœuds (machine à états fermée, preuves fail-closed, codeSignature, invalidation, reprise déterministe, idempotence, journal append-only) ; 5 contrats de cycle hétérogènes ; pas de DAG ni dépendances inter-tâches ; état fragmenté ; observabilité éclatée ; KG≠EG déjà structurel ; `workflows/` réservé ; ADRs 012/014/015/017 pertinents.

**Position initiale d'Aurora** : hybride — moteur de transitions natif (tw_state.py + PostgreSQL) exécutant des DAG bornés avec boucles Evaluator/Optimizer bornées, Supervisor conservé. LangGraph rejeté (incompatibilité processus vs in-process). Temporal rejeté (non-déterminisme LLM vs event sourcing).

**Verdict ChatGPT : `APPROVED WITH CHANGES`** avec 4 arbitrages :

| Question | Verdict | Décision |
|---|---|---|
| Q1 — LangGraph | Accord (justification affinée) | Pas dans le cœur. Le vrai problème n'est pas l'incompatibilité mais le **coût d'intégration et la duplication des responsabilités**. Cas d'usage retenu : **sous-graphes cognitifs** (LangGraph comme moteur interne d'un nœud, jamais l'orchestrateur global). Pas pour l'itération 1. |
| Q2 — JSON vs PostgreSQL | À ajuster | **Séparer TransitionEngine** (logique métier — réutiliser `tw_state.py`) **/ StateRepository** (persistance + concurrence) **/ EventLog** (journal atomiquement lié aux transitions). JSON acceptable pour un prototype isolé ; **PostgreSQL requis avant un DAG multi-worker durable** (réservation exclusive de nœud, lease avec échéance, fencing anti-worker-périmé). KG séparé **logiquement** — une seule instance PostgreSQL peut suffire (schémas + droits distincts). Pas de réécriture des données historiques task-workflow. |
| Q3 — Déterminisme/LLM | À renforcer | Séparation en **3 niveaux** : (1) preuve d'exécution technique — déterministe (exit code, timeout, artefacts, hashes) ; (2) évaluation sémantique — LLM encadré produisant un **verdict structuré** (`{verdict, findings[{severity, criterionId, evidenceRef}], confidence}`) dont le moteur valide la **structure** sans prétendre prouver le jugement ; (3) autorisation de transition — déterministe (preuves présentes et fraîches, budgets, approbation humaine). Quatre types d'échec distincts avec **budgets indépendants** : échec technique transitoire (retry), échec de qualité (itération de correction), preuve invalide (bloqué), permission manquante (approbation/refus explicite). |
| Q4 — Contrat de nœud | À compléter | Deux objets séparés : **NodeDefinition** (ce qui doit être exécuté : + `schemaVersion`, `idempotencyKey`, `effectPolicy{mode, idempotencyKey?, compensation?, onUncertainOutcome}`, `evidencePolicy`, `resourcePolicy`) et **NodeExecution** (ce qui s'est passé : `runId`, `attempt`, `leaseToken`, `inputFingerprint`, `outputArtifactRefs`, `evidenceRefs`). Graphe **versionné immuable** au lancement ; toute modification de topologie = nouveau plan avec filiation. |

**Reframing majeur de ChatGPT** : « Le véritable problème n'est pas l'absence de Graph Engineering, mais **la fragmentation des contrats d'exécution**. » Déconseil explicite de créer un 6ᵉ moteur à côté des 5 existants → **noyau commun progressivement adopté** : *Aurora Supervisor* (planification conversationnelle) au-dessus d'un *Execution Graph Core* (transitions, dépendances, evidence & gates, retries & recovery, permissions, events & state) dont les 5 skills (task-workflow, deepwork, council, meeting, loop-engineering) deviennent clients en conservant leur logique métier (ex. council garde ses 3 sièges et délègue dépendances/tentatives/permissions/preuves au noyau).

**Scénario critique soulevé (effets externes)** : worker qui plante après un effet externe confirmé mais avant l'enregistrement du succès → rejeu = double effet. La solution n'est pas le DAG persisté seul mais l'**identité de l'opération + preuves d'effet + réconciliation avant rejeu** ; si irréconciliable → `blocked` à résultat incertain. « Cela correspond directement à l'esprit de ton ADR-017. »

**Correction factuelle apportée par ChatGPT (acceptée par Aurora)** : Temporal **ne réexécute pas** les appels LLM terminés lors du replay — leurs résultats sont enregistrés dans l'historique des Activities ; c'est le code d'orchestration déterministe qui est rejoué. Le non-déterminisme LLM ne justifie donc pas à lui seul le rejet de Temporal. Le rejet est maintenu pour l'itération 1 (coût opérationnel, absence de besoin de durabilité avancée démontré) mais l'ADR devra porter la justification correcte. *(Le comparatif `03-architecture-comparison.md` a été corrigé en conséquence.)*

## 3. Tour 2 — Réponses factuelles d'Aurora aux 3 questions renvoyées

ChatGPT a renvoyé 3 questions « plus importantes, à ce stade, que le choix définitif d'un framework ». Réponses d'Aurora (sourcées de l'audit) :

**Q5 — Nature des 5 contrats** : seul **task-workflow** est une vraie machine à états persistée (transitions fermées codées et appliquées fail-closed, preuves structurées avec exitCode, reprise déterministe). Les 4 autres sont des **protocoles** d'exécution ou de validation : deepwork (progression markdown descriptive), council (verdict unique, read-only), meeting (gate avec invariant interne incomplete→jamais READY), loop-engineering (état mémoire + callbacks). → Candidats naturels à l'adoption progressive du noyau.

**Q6 — Concurrence réelle** : plusieurs sessions OpenCode peuvent tourner simultanément sur le même projet (constaté), mais chaque orchestrateur conversationnel est séquentiel. Primitives existantes : garde de dossier canonique + claim du handoff (refus d'un second preneur) + journal séquentiel par workflow ; transitions goals fermées côté PostgreSQL (atomique SQL). **Pas de verrouillage interprocessus générique ni de versioning d'état.** → Le backend JSON + garde canonique suffit pour un **pilote mono-exécuteur** ; PostgreSQL (réservation + lease + fencing) requis dès le DAG multi-worker durable — les deux positions convergent.

**Q7 — Effets externes** : OpenCode (task spawn/cancel : idempotent par sessionID, réconciliable via task_status), Git (commit/push/worktree réessayables ; jamais de force-push par convention), Trello (GET-before-POST **déjà implémenté** dans `trello_comment.sh`), GitLab (création de MR non idempotente — GET-before-POST à généraliser), **Infomaniak API (écritures sans aucune idempotence — zone critique**, confirmation orchestrator obligatoire par le bridge ADR-021, réconciliation par GET avant rejeu requise), filesystem (idempotent à contenu déterministe). → `effectPolicy{onUncertainOutcome: reconcile|block}` obligatoire sur les nœuds d'écriture.

## 4. Tour 3 — Verdict final après réponses factuelles

**Réponses d'Aurora publiées** (matrice Q5, concurrence Q6, effets externes Q7 — cf. §3). **Verdict ChatGPT : `APPROVED` — « Passage à la conception détaillée autorisé. »**

**Décisions architecturales consolidées** (table finale du débat) : moteur natif basé sur les invariants de `tw_state.py` · stockage pilote JSON mono-exécuteur avec **verrouillage exclusif** · stockage cible PostgreSQL logiquement indépendant du KG · DAG **statique et versionné** · Supervisor conservé · exécution = processus OpenCode/CLI/MCP/outils · gates = council/meeting/review · corrections bornées sans cycles arbitraires dans le DAG · permissions par nœud + politique d'effets externes · observabilité structurée corrélée par `runId`.

**Trois ajustements P0 avant toute implémentation** :

| # | Ajustement | Exigence |
|---|---|---|
| P0.1 | Le claim existant ne garantit pas l'exclusion mutuelle (deux processus peuvent claim au même instant) | verrou interprocessus **atomique** couvrant les transitions (pas une convention entre agents), un seul ordonnanceur actif par `runId`, écritures atomiques de l'état, détection des exécutions interrompues |
| P0.2 | Nuance Q7 : un `sessionID` OpenCode permet de retrouver une exécution sans garantir l'absence de doublon à la recréation ; deux `git commit` successifs ne sont pas intrinsèquement idempotents | trois catégories explicites d'effets : **safe** (rejeu sous préconditions vérifiées) / **reconcile** (vérifier l'effet réel avant toute décision) / **block** (intervention requise si incertain) ; GET-before-POST suffit uniquement si l'API permet d'identifier l'opération de façon fiable |
| P0.3 | La signature git ne doit pas être la seule preuve de fraîcheur (fichiers ignorés, config externe, réponses API obsolètes, version d'outil changée) | `inputFingerprint` générique construit sur les dépendances réellement pertinentes de chaque nœud ; la signature git `sha1(HEAD+status)` reste un **composant** de l'empreinte |

**Architecture cible affinée en 3 couches** : Execution Graph Core (ordonnanceur, transitions, dépendances, preuves, permissions, tentatives, reprise) / **Workflow Adapters** (logique propre aux 5 protocoles — préserve le read-only de council et les garanties de meeting) / **Executors** (OpenCode, CLI, MCP, outils locaux, approbations humaines). Un gate council retourne un verdict sans devenir responsable des transitions globales.

**Périmètre du premier prototype** : workflow analyse → implémentation → review ; écritures externes limitées aux opérations locales maîtrisées ; **6 propriétés mesurables** : (1) DAG ≥ 2 branches indépendantes + convergence, (2) reprise sans réexécution des nœuds à preuves valides, (3) invalidation **transitive** des descendants quand une preuve amont devient obsolète, (4) boucle de correction bornée après review défavorable, (5) interruption sûre avant un effet externe à résultat incertain, (6) exclusion mutuelle effective entre deux sessions reprenant le même workflow.

**Prochaine livraison attendue : une RFC d'architecture** (pas de code de production) contenant : `GraphDefinition`, `NodeDefinition`, `NodeExecution`, `EvidenceRecord`, `EffectRecord`, les invariants de transition, le comportement de reprise, la matrice de responsabilités noyau/5 protocoles, et le traitement des cas où un nœud réussit techniquement mais dont le résultat devient invalide avant l'exécution des descendants.

**GO** : finaliser la RFC, les scénarios de validation, la stratégie de migration progressive. **NO-GO** : migration PostgreSQL globale, intégration LangGraph ou Temporal, remplacement immédiat des cinq contrats.

> « Le premier succès du projet ne sera pas d'exécuter un graphe complexe. Ce sera de prouver qu'Aurora peut interrompre, reprendre et valider un workflow multi-étapes sans perdre son état, dupliquer un effet externe ou accepter une preuve périmée. » (ChatGPT, tour 3 — fondement proposé pour la suite du coworking)

## 5. Issue du débat (consolidée)

- **Itération 1 : APPROVED WITH CHANGES → APPROVED** après réponses factuelles Q5/Q6/Q7 — architecture hybride native confirmée comme hypothèse de référence, affinée (3 couches, 3 P0).
- **GO itération 2** : RFC d'architecture (contrats complets + scénarios de validation + stratégie de migration).
- **NO-GO** persistants : migration PostgreSQL globale, LangGraph/Temporal dans le cœur, remplacement immédiat des cinq contrats.
