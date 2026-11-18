# 09 — Rapport de QA finale : Graph Engineering avant la PR vers `main`

- **Date** : 2026-10-24
- **Périmètre** : branche d'intégration `feat/graph-engineering` (merge des PR #48, #49, #50, #51, #52) vs l'état initial du dépôt (avant le projet)
- **Gates exécutés** : voir §2 (preuves d'exécution sur le code mergé)
- **Décision attendue** : approbation **humaine** pour la PR finale `feat/graph-engineering` → `main` (le merge main n'est **jamais** automatique — USER_ASSERTION 2026-10-24)

## 1. Comparaison avant / après

| Axe | AVANT (système actuel, référence) | APRÈS (Core intégré, en shadow) |
|---|---|---|
| Machine d'états | Ad hoc, par skill, sans table légale | Table §3.1 (I1), `completed`/`cancelled` terminaux, 84/84 tests |
| Journal d'exécution | Chronique `events.jsonl` append-only (seq, transitions/incidents), mais **sans checksum, sans fsync, non transactionnelle** | JSONL transactionnel checksumé (I3), fsync fichier + répertoire, queue torn ignorée, checksum invalide jamais confirmé |
| Reprise après crash | Protocole `claim`/`resume` scripté (phases validées non rejouées, recovery journalisée via `claim --force`), **sans garantie crash-safe** | Projection rebuildable + chaîne de générations dans le lockfile (S2/S2b/S2c) : 0 re-exécution de nœud frais, 0 perte de run, re-pin des orphelins, réconciliation d'effets |
| Invalidation | `invalidate_phase` par phase avec garde STALE fail-closed, **sans transitivité, sans marquage de preuves, grain phase** | Transitive au grain nœud (I5), preuves **marquées jamais supprimées**, staleness par révisions de journal (valable dans la même seconde) |
| Effets d'écriture | Non encadrés | Protocole §7.2 (prepared→dispatched→confirmed/uncertain), double-fenêtre P0.3 fermée, séquence condensée `safe`, `block` jamais dispatché sans approbation humaine journalisée |
| Exclusion mutuelle | Refus de claim concurrent + gardes handoff (convention applicative), **sans verrou noyau ni fencing** | flock noyau + fencing positionnel dans la même section critique que l'écriture (StaleGeneration fail-closed) |
| Budgets d'échec | Aucun | Per-classe (I8) : technical terminal à épuisement, quality/invalidEvidence/permission jamais auto-résolus → `blocked` |
| Écritures externes réelles | n/a (le système actuel EST la référence) | **0** sur tout le projet (sandbox + NO-GO structurel M7) — la bascule reste subordonnée à un GO PO + GO humain |
| Métriques d'exécution | Chronique d'événements sans métriques agrégées standardisées | `collect_metrics` : successRate par graphe, durées ms par dernière tentative, wallClock, retries, effets par phase, interventions humaines |
| Couplage | — | Additif et réversible : 0 modification des skills existants et de `tw_state.py` (scellé par `git diff` à chaque itération) |

## 2. Preuves d'exécution (gates de la QA finale, code mergé)

| Gate | Commande | Résultat |
|---|---|---|
| Suite complète | `python3 -W error::ResourceWarning -m unittest discover -s skills/graph_core/tests` | **84/84 OK** (57 core + 16 pilote + 11 adaptateur) — artefact : `final-qa-tests-artifact.txt` |
| Coexistence | `python3 skills/task-workflow/tw_state.py validate ~/.config/opencode/task-workflows/tw-aurora-ai--8c7fb888-iter6.json` | `state valid` — 0 régression sur le workflow actuel |
| Shadow-run final | `run_skill_graph` sur la PR #52 (gh pr view réel + grep réel + analyse, 3 nœuds — specs journalisées dans l'artefact) | **3/3 complétés, successRate 1.0, wallClock 0.542 s, `realEffectEmissions: 0`, 0 intervention humaine, 0 problème journal** (`final-qa-shadow-metrics.json`) |
| Scellement non-régression | `git diff origin/main..origin/feat/graph-engineering --stat -- . ':(exclude)skills/graph_core' ':(exclude)docs/graph-engineering'` | vide (collé dans la description de la PR finale) |

## 3. Couverture des scénarios RFC §10 (S1-S7)

| Scénario | Statut | Preuve (tests automatisés) |
|---|---|---|
| S1 — convergence après toutes les deps | ✅ automatisé | `test_s1_convergence_after_all_deps` (ordre journal I4) |
| S2 — reprise sans re-exécution des nœuds frais | ✅ automatisé | `test_s2_resume_skips_fresh_completed` + `s2b` (crash pendant nœud → re-pin §5.3) + `s2c` (perte snapshot → 0 perte) + `s2d` (plan muté → PlanMismatch) |
| S3 — invalidation transitive, preuves marquées | ✅ automatisé | `test_s3_transitive_invalidation_marks_never_deletes` (b intact, journal complet) |
| S4 — reprise après intervention humaine | ✅ par composition | nœud `blocked` jamais auto-résolu (I8, testé) + `human-intervention` journalisé avec acteur/motif (`test_s5_s7_reconcile_effect_crash_blocks_without_rejeu` → `scheduler.record_human_intervention`) + reprise S2 |
| S5 — crash entre `dispatched` et l'émission | ✅ automatisé | `test_s5_s7_reconcile_effect_crash_blocks_without_rejeu` (fake dispatcher) : `uncertain → blocked`, 0 re-dispatch |
| S6 — exclusion mutuelle + fencing | ✅ automatisé | `test_s6_mutual_exclusion_and_fencing` + `s6b` (chaîne de générations) |
| S7 — séquence d'effets §7.1 | ✅ automatisé | `test_s7_safe_effect_uses_condensed_sequence` + `test_s7_block_effect_never_reaches_dispatcher` |

## 4. Historique des revues adversariales (toutes appliquées)

| Itération | PR | Findings | Traitement |
|---|---|---|---|
| 3 (M1-M4 core) | #49 | 20 (+3 axes tests) | tous corrigés, re-review **CONFORME**, 7 bugs réels attrapés par les tests |
| 4 (M5 pilote) | #50 | 10 | tous corrigés, re-review **CONFORME** + résiduelles R4-01b |
| 5 (M6 ADR) | #51 | 4 (doc) | tous appliqués |
| 6 (M7 adaptateur) | #52 | 9 (0 bloquant) | 4 appliqués pré-merge, backlog pré-flip tracé (§6 doc 08) |

Total : **43 findings traités, 0 régression I1-I9 constatée sur aucune re-review**.

## 5. Validations PO déléguées (ChatGPT, canal dédié)

| Décision | Verdict |
|---|---|
| RFC M2 (itération 2) | validée → PR #48 mergée |
| Clôtures itérations 3-4 | notifiées, pas de gate demandé |
| ADR M6 (3 limites de forme) | **OUI AVEC RÉSERVES** — réserves vérifiées contre l'implémentation et consignées (ADR L1-L3) |
| Avancement M7 | **GO adaptateurs / NO-GO écritures externes réelles** — respecté |

## 6. Chemin de bascule (après merge main, hors périmètre actuel)

1. **Rien ne change** au merge : le Core est additif, les skills restent la référence exécutive.
2. Toute écriture externe réelle passera par un dispatcher **réel** (protocole §7.2, `getBeforePost`, idempotencyKey, `block` par défaut) — prérequis : reviewable (grep du diff), GO PO explicite, QA avant/après ciblée, approbation humaine.
3. Le backlog pré-flip (doc 08 §6) et les revisit triggers (ADR L1-L3) encadrent les évolutions.

## 7. Limites assumées (rappel)

- M7 `analysis` = stubs (l'analyse LLM-grade reste le travail du système actuel).
- Le NO-GO est structurel (protocole d'effet), pas un sandbox filesystem.
- Les 3 limites ADR L1-L3 avec leurs revisit triggers.
- Backlog pré-flip doc 08 §6 (non bloquant, tracé).
