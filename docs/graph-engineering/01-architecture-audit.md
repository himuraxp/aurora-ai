# Audit technique de l'architecture Aurora — orchestration multi-agents

> Carte Trello : [Aurora] Graph Engineering — Audit architectural & orchestration multi-agents (`DuTvF4fZ`) · Itération 1 · 2026-10-24
> Livrable 1/5. Tous les constats sont sourcés (chemins précis). Ce document est purement descriptif : aucune proposition ici — voir `04-target-architecture.md`.

## Périmètre et méthode

Analyse factuelle du fonctionnement réel du système, sans modification de code. Sources : dépôts `aurora-ai` (config agents/skills/standards/scripts, branche `main` @ `e80ddbb`) et `aurora-core` (runtime : services, connecteurs, ADRs). Axe par axe, puis synthèse forces / limitations / redondances / composants réutilisables.

---

## A1 — Orchestrateur principal et délégation

**Composants** : `agents/aurora.md` (orchestrateur principal), `agents/aurora-heavy.md` (raisonnement avancé), plugin `oh-my-opencode-slim` (11 agents : `atlas, crawler, sage, scribe, pulse, echo, beacon, designer, mobile, security, cybersec` — `config/oh-my-opencode-slim.json`), 16 agents fichiers (`agents/*.md` : architect, reviewer, tester, spark, vision, explorer/fixer/librarian/oracle via plugin, council-*, meeting-*, product-owner).

**Fonctionnement réel** :

- Cycle de travail fixe : `Explorer → Planifier → Implémenter → [PARALLEL GATE] → Committer` (`agents/aurora.md`, section « Cycle de travail »).
- Délégation **par triggers de mots-clés** : tables déclaratives (Engineering & Design, Search & Growth) mappant domaine → agent(s). Multi-agents en parallèle possible (task en un seul message), consolidation par Aurora (`standards/agent-output.md` : retour JSON obligatoire `agent-output.v1`).
- Sous-agents invoqués via `task` : `background` (retour immédiat, notification à complétion) ou `foreground`. Sessions ré adressables par `sessionID` (resume).
- Résolution des modèles **par rôles, pas par modèles** (`config/model-roles.json`, `scripts/configure-models.sh` → `~/.config/opencode/aurora-models.json`), avec chaînes de fallback (expert → Kimi-K2.6 → Nemotron-3-Nano).
- Hiérarchie d'autorité documentée (system → standards → agents → frameworks → AGENTS.md projet → docs/ai/).

**Constat structurant** : la « planification » est une pratique conversationnelle (le plan vit dans le contexte de session et dans `docs/ai/PLAN.md` du projet), pas un objet d'état pilotable par un moteur. Les dépendances entre tâches orchestrées ne sont pas modélisées hors de `task-workflow` (voir A2).

## A2 — Cycle de vie des tâches

**Composants** : `skills/task-workflow/` (orchestrateur Trello/GitLab complet), `skills/deepwork/SKILL.md` (efforts multi-phase haut risque), `skills/council/` (délibération), `skills/meeting/` (gate pré-implémentation), `skills/loop-engineering/` (runtime Grill + Monitor).

**`task-workflow` — le cycle de vie le plus abouti** (`skills/task-workflow/SKILL.md`, `tw_state.py`) :

- **9 phases** : Contexte → Worktree → Analyse → Code → QA → Review → MR → Finalisation (+ rapport).
- **Machine à états fermée** : `PENDING/RUNNING/WAITING_APPROVAL/BLOCKED/FAILED/PASSED/SKIPPED` + `STALE` dérivé ; transitions légales codées (`TRANSITIONS` dans `tw_state.py`, ex. `PENDING → {RUNNING, SKIPPED, BLOCKED}`, `PASSED` est absorbant — seule `invalidate` en sort).
- **Preuves fail-closed** : `testResults[]/qaResults[]/reviewResults[]/mrResults[]` avec `{phase, name, status, exitCode}` — un `pass` **exige** `exitCode: 0` ; un contrôle ignoré n'existe qu'avec une `reason` non vide ; les phases 4-7 partagent une `codeSignature` (sha1 de HEAD + `git status --porcelain` du worktree) — une preuve ne survit pas au code qu'elle prouvait (`invalidate` purge).
- **Persistance hors dépôt** : `~/.config/opencode/task-workflows/<workflowId>.json` (garde canonique — écriture hors dossier refusée), `workflowId` = hash de l'identité normalisée de la tâche (toutes les formes d'URL → même id, idempotence).
- **Journal chronique** : `events.jsonl` append-only (transitions journalisées par `mark`, incidents et reprises via `log`), divergence état/journal détectée (`JOURNAL-WARNING`) sans bloquer.
- **Reprise** : `resume` calcule un plan déterministe (phases PASSED à signature courante = sautées ; signature obsolète = invalidées ; BLOCKED ré-évaluées).
- **Gates humaines** : gate PO batchée (`WAITING_APPROVAL`), questions format Contexte/Options/Recommandation/Conséquences ; option product-authority (attestations vérifiées à l'usage).
- **Handoff** : bascule vers Orca (`tw_orca.py handoff`, verdicts `pending/skipped/failed/uncertain` enregistrés, anti double prise).

**`deepwork`** : phases dépendantes + review gates, fichier de progression local `.slim/deepwork/` — un second modèle de cycle, non aligné sur `tw_state.py`.

**`council`** : 3 sièges read-only indépendants (`council-architect/council-skeptic/council-guardian`) + synthétiseur sans outils + arbitrage Aurora ; verdict `DECIDED/CONDITIONAL/INVESTIGATE/ESCALATE`. **Pattern Evaluator/Optimizer complet, déjà opérationnel.**

**`meeting`** : gate pré-implémentation multi-métiers, Meeting Record + `meeting-handoff.v1`, verdict `READY/CONDITIONAL/BLOCKED` (incomplete ≠ READY). **Pattern de nœud de validation humaine et multi-perspectives.**

**`loop-engineering`** : runtime Grill (interview) + Monitor (callbacks, compteur d'essais, `cancel(loopID)`) — embryon de boucle conditionnelle pilotée.

**Constat structurant** : `task-workflow` est déjà un **graphe linéaire strict à 9 nœuds** avec transitions fermées, preuves invalidantes, reprise et idempotence — mais linéaire : pas de branches, pas de fork/join, pas de dépendances inter-nœuds hors séquence. Les autres skills (deepwork, meeting, council) réimplémentent chacune leur propre modèle de cycle avec des contrats hétérogènes.

## A3 — Goals, états, sessions, dépendances

**Composants** : `services/aurora-memory` (outil `goals` : `goal_create, goal_list, goal_update_status`), mémoire de session par projet (`docs/ai/` — 7 fichiers : STATUS, PLAN, CHANGELOG, BUFFER, INDEX, WARNINGS, DECISIONS ; `standards/memory-session-flow.md`, `standards/memory-auto-update.md`), skills de session OpenCode (sessions persistées, resume, renommage, worktrees).

**Fonctionnement réel** :

- Goals : état persistant en PostgreSQL, **transitions fermées** (le serveur refuse un changement de statut hors transitions légales — contrat « §F » du plan Aurora OS). Les goals ne portent pas de graphe de dépendances (pas de relation goal→goal).
- `docs/ai/` : état de session **par projet**, tenu par les agents, projection additive depuis la mémoire (`projection_generate`, ADR-013/018). Idempotent, gitignoré.
- Sessions OpenCode : persistance disque, resume multi-sessions, move/rename/worktrees — l'état conversationnel est réadressable mais pas un objet de graphe.

**Constat structurant** : trois niveaux d'état coexistent (goal PostgreSQL, workflow JSON hors dépôt, session docs/ai) sans modélisation commune ni références croisées. Les dépendances ne sont exprimées nulle part de façon machine-exploitable.

## A4 — Mémoire persistante / Knowledge Graph

**Composants** : `services/aurora-memory` (`~/dev/aurora-core`) — MCP stdio, 15 outils (`entity_upsert, entity_search, relation_upsert, relation_query, fact_insert, fact_query, preference_set/query, goal_*, event_append/list, memory_search, projection_generate`), PostgreSQL + pgvector, embeddings Qwen3-8B 4096d (ADR-022, migration 003).

**Fonctionnement réel** :

- KG : `entities`, `relations`, `facts`, `events`, `preferences`, `documents`, `embeddings` (+ `identities`, `accounts`, `credentials`, `connector_bindings` — migrations 001-004 appliquées).
- Accès **orchestrator-only** : le bridge local plugin n'exécute que pour l'orchestrateur (ADR-021, B3 v1) ; 4 agents en profil READ minimal (`architect, reviewer, designer, mobile` — ADR-020) ; les agents retournent des `memory_observations`, l'orchestrateur seul persiste.
- Provenance obligatoire (USER_ASSERTION/EXPLICIT_CORRECTION pour le dur), contenu mémoire = donnée non fiable (jamais des instructions), secrets interdits (ADR-016).
- Projection : KG → `docs/ai/projection/` additif (ADR-013), chemin épinglé (`AURORA_PROJECTION_ROOT`).

**Constat structurant** : le KG est la mémoire **sémantique** (« ce qu'Aurora sait »). Il n'y a **aucun état d'exécution persisté côté KG** — la distinction Knowledge Graph / Execution Graph est déjà structurelle dans le code (la carte impose de la préserver).

## A5 — Connecteurs, outils, permissions, validation

**Composants** : `services/connectors` (frontière read-only — ADR-023), bridges orchestrator-scoped (`config/plugins/infomaniak-bridge.ts` : écritures API derrière une décision explicite ; `aurora-memory.ts` : accès mémoire), registre product-authority (`~/.config/opencode/aurora-product-authority.json` — privé, niveau consultative/limited/extended, attestations re-vérifiées à chaque usage, blind re-classification), `standards/escalation.md`, `standards/error-correction.md` (règle des 2 corrections échouées → stop & reset), permission model OpenCode (denies/allows par agent dans `config/opencode.json` + `agents/*.md`).

**Fonctionnement réel** : les écritures à fort impact passent systématiquement par un pont orchestrator-scoped + preuve d'autorisation (le pattern DELEGATED_APPROVED n'autorise que le contenu, jamais l'exécution). Le deny global est banni (inopérant pour les file-agents — invariant empirique documenté dans `AGENTS.md`).

**Constat structurant** : le contrôle de permission est **par agent et par tool** (statique), pas par **étape d'exécution**. Un graphe qui porte ses permissions sur ses nœuds trouverait ici un point d'extension naturel (le pattern d'attestation product-authority est déjà transversal).

## A6 — Exécution parallèle, erreurs, retries, observabilité

**Composants** : background tasks (job board : `task_result/task_status/task_cancel/task_message`), PARALLEL GATE (`standards/review-before-done.md`, `standards/workflow.md`), `skills/council` (délibération parallèle), logs OpenCode (`~/.local/share/opencode/log/`), journal `events.jsonl` (task-workflow), events KG.

**Fonctionnement réel** :

- Parallélisme réel : plusieurs `task` en un message ; consolidation orchestrator (tri sévérité/effort, rapport unifié). Fork/join limité au PARALLEL GATE (review ∥ vérification) et aux audits multi-agents.
- Erreurs : règle des 2 corrections (`error-correction.md`), anti-patterns (`anti-patterns.md`), échec de délégation traité (`delegation-failure.md` : constater → diagnostiquer → agir), escalade (`escalation.md`).
- Observabilité : **trois systèmes séparés** — logs runtime OpenCode (opérational), `events.jsonl` (chronique workflow, append-only, gaps détectés), events KG (mémoire sémantique). Aucune vue unifiée ; pas de métriques de coût/tokens/reprises agrégées.

**Constat structurant** : les mécanismes de résilience existent (reprise, invalidation, retries bornés) mais sont **locaux à chaque skill** — aucune reprise transversale d'une exécution multi-skills.

## A7 — Inventaire ADRs (aurora-core/docs/adr/)

| ADR | Titre | Statut | Pertinence Execution Graph |
|---|---|---|---|
| 012 | Contrat de Capability Packs (déclaratif, runtime-indépendant, versionné) | accepté | **Élevée** — contrats de nœuds déclaratifs |
| 013 | docs/ai projection | accepté | Moyenne — restitution |
| 014 | Audit append-only | accepté | **Élevée** — journal d'exécution |
| 015 | Executor sandbox (Docker) | accepté | Élevée — exécution isolée des nœuds |
| 016 | Credential broker | accepté | Élevée — secrets hors nœuds |
| 017 | Idempotence + compensations | accepté | **Critique** — retries/reprise |
| 018 | Service aurora-memory | accepté | Contexte KG |
| 019 | OpenCode wiring activation | accepté | Contexte intégration |
| 020 | Memory access governance | accepté | Contexte permissions |
| 021 | Memory orchestrator-scoped adapter | accepté | Contexte permissions |
| 022 | Embeddings Qwen3-8B | accepté | Faible |
| 023 | Phase 2a email/calendar read-only | accepté | Faible |

Le dossier `workflows/` d'aurora-core est **vide** (emplacement réservé par le plan `docs/AURORA-OS-PLAN.md`) — de même `apps/` et `packages/`.

---

## Synthèse

### Forces (réutilisables telles quelles)

1. **`tw_state.py`** : machine à états fermée, transitions validées, preuves fail-closed avec `codeSignature`, invalidation, reprise déterministe, idempotence, journal append-only — **le noyau d'un moteur de transitions existe déjà, testé** (suite `python3 -m unittest`).
2. **Patterns de validation** : council (Evaluator/Optimizer), meeting (gate multi-perspectives), PARALLEL GATE (fork/join), gate PO (interruption humaine `WAITING_APPROVAL`), product-authority (attestations transversales).
3. **Contrats d'échange standardisés** : `agent-output.v1` (retour de nœuds agents), meeting-handoff.v1, capability packs déclaratifs (ADR-012).
4. **Persistance éprouvée** : PostgreSQL (goals à transitions fermées, KG), JSON d'état hors dépôt avec garde canonique, journal JSONL.
5. **Délégation déclarative** : tables agents/triggers, résolution par rôles + fallback, sessions ré adressables.
6. **Emplacements réservés** : `workflows/` vide dans aurora-core — structure anticipée.

### Limitations

1. **Pas de moteur de graphe générique** : chaque skill (task-workflow, deepwork, meeting, council, loop-engineering) porte son propre modèle de cycle — 5 contrats hétérogènes pour des besoins convergents (phases, transitions, preuves, gates).
2. **`task-workflow` = graphe linéaire strict** : pas de branches conditionnelles, pas de fork/join de tâches, pas de dépendances inter-nœuds hors séquence.
3. **Pas de dépendances inter-tâches** : les goals et les workflows ne se référencent pas ; une exécution multi-tâches n'a pas d'état partagé machine-exploitable.
4. **État d'exécution fragmenté** : JSON hors dépôt / `.slim/deepwork/` / contextes de session / `docs/ai/` — aucune vue unifiée, aucune reprise transversale.
5. **Observabilité éclatée** : logs runtime, events.jsonl, events KG — pas de métriques agrégées (durée, coût, reprises, interventions humaines) par exécution.
6. **Permissions statiques par agent** : pas de contrôle d'autorisation par étape d'exécution (le portage au niveau nœud n'existe pas).

### Redondances observées

- Deux modèles de workflow documentaires concurrents (task-workflow vs deepwork) pour le même besoin de phases + gates.
- Trois systèmes de journalisation (logs, events.jsonl, events KG) sans contrat commun.
- Gates humaines réimplémentées par skill (question batchée, WAITING_APPROVAL, verdicts meeting/council) avec sémantiques voisines mais incompatibles.

### Composants réutilisables pour un Execution Graph

| Besoin du graphe | Composant existant à réutiliser |
|---|---|
| Transitions d'état fermées | `tw_state.py` (`TRANSITIONS`, `evidence_guard`, `invalidate`) |
| Identité/idempotence d'exécution | `new_workflow_id` (hash d'identité normalisée) |
| Journal d'exécution | `events.jsonl` + `append_event` (ADR-014) |
| Contrats de nœuds | Capability Packs (ADR-012) + `agent-output.v1` |
| État persistant | PostgreSQL (modèle goals à transitions fermées) |
| Checkpoints/reprise | `resume` + `codeSignature` + `invalidate` |
| Nœuds de validation | council / meeting / gate PO / product-authority |
| Permissions par nœud | product-authority (attestation) + bridge gating (ADR-021) |
| Exécution sandbox | ADR-015 (executor Docker) |
| Compensations | ADR-017 (idempotence + compensations) |

---

*Méthode de lecture de cet audit : chaque constat est vérifiable par le chemin cité. Toute imprécision constatée en revue est une anomalie de document, pas une interprétation.*
