# ADR 07 — Execution Graph Core : décisions définitives et limites connues

- **Statut** : Accepted
- **Date** : 2026-10-24
- **Décideurs** : Product Owner délégué (ChatGPT, verdict « OUI AVEC RÉSERVES »), Aurora (orchestrateur, implémentation), Reviewer (revues adversariales tours 1-2 par itération)
- **Spécification contraignante** : `06-execution-graph-rfc.md` (RFC, PR #48). L'ADR documente les décisions prises pendant l'implémentation ; toute divergence implémentation/RFC reste un bug.

## Contexte

Le milestone M5 (pilote analyse-MR en shadow-run, PR #50) a démontré le noyau
d'exécution en graphe sur un workflow réel : 5/5 nœuds complétés, successRate
1.0, effets journalisés en simulation pure (`realEffectEmissions: 0`), 0
intervention humaine, 0 problème journal
(`shadow-run-pr49-metrics.json`). Trois limites de forme, assumées par le
pilote, ont été identifiées par la revue adversariale puis validées par le PO
délégué avant la bascule. Cet ADR fige les décisions structurantes (M1-M5) et
ces limites, avec leurs déclencheurs de réévaluation.

## Décisions

### D1 — Emplacement et périmètre du noyau

Le noyau vit dans le paquet `skills/graph_core/` (Python 3.9+, stdlib only),
copie conforme de l'implémentation pilote documentée, en coexistence avec
`tw_state.py` (jamais modifié). Mono-exécuteur, pas de PostgreSQL, moteurs
natifs — NO-GO ratifiés non re-challengeables. Le couplage skill→Core est
réservé à M7+.

### D2 — Le journal transactionnel est la source de vérité (I3)

`journal.jsonl` (JSONL, checksum par record, fsync fichier + répertoire) est
l'unique source de vérité. Le snapshot (`snapshot.json`) est une projection
rebuildable, jamais autoritative. Une queue de journal incomplète (écriture
torn) est ignorée ; un checksum invalide n'est jamais confirmé. La projection
est fidèle : `evidenceIds`, `inputFingerprint`, statuts d'arrivée par
descendant affecté, `attempt` par record (re-review R-01).

### D3 — La chaîne de générations vit dans le lockfile (F-01)

`knownGenerations` est append-only dans le **lockfile** (événements
`acquire`), jamais dans la projection rebuildable seule. Conséquence
vérifiée par test : la perte du snapshot ne perd pas le run (S2c) — le
journal + le lockfile suffisent à reconstruire.

### D4 — Fencing par ordinalité positionnelle

Le writer doit détenir le **dernier** `acquire` du lockfile, vérifié dans la
même section critique que l'écriture (`_critical`). Le token est un UUIDv4
(unique, pas ordonné lexicalement) : l'ordinalité est **positionnelle** — un
token acquis après une purge de queue est appendu en position strictement
postérieure à toute ligne durablement confirmée. Une ligne lockfile valide
syntaxiquement mais sans `generationToken` exploitable produit un mismatch →
`StaleGeneration` → refus fail-closed. Réserve PO « token strictement
nouveau et postérieur à toute génération durable » : satisfaite par
construction (cf. L3).

### D5 — Machine d'états et staleness par révisions de journal

Transitions légales selon la table §3.1 (`completed`/`cancelled` terminaux) ;
invalidation par opération dédiée I5 (portée transitive, preuves marquées
jamais supprimées). La staleness d'une complétion (I5/F3) est évaluée par
**révisions de journal monotones**, pas par horloges : deux records dans la
même seconde murale restent ordonnés (T-01). Les nœuds `running` orphelins
sont re-épinglés à la reprise (§5.3, journalisés `kind=invalidation`) sauf
effet non conclu → `blocked` (réconciliation d'abord).

### D6 — Garde I2 AVANT émission d'effet, protocole §7.2

Le garde I2 (preuves conformes à `evidencePolicy`) s'applique **avant** le
protocole d'effet : une preuve non conforme ne permet **jamais** l'émission
(bug d'ordre attrapé par les tests pilote, itération 4). Le protocole
d'effet est journalisé (`prepared → dispatched → confirmed/uncertain`,
séquence condensée pour `safe`), avec `EffectDispatcher` injectable et
classification `block` jamais dispatchée sans approbation humaine
(`human-intervention` journalisé avec acteur/motif).

### D7 — Ordre de reprise §5, identité adoptée depuis le journal

`acquire_lock → identité run-id → plan (I6/F09) → rebuild → markers →
re-pin orphans → freshness (I7)`. Un fichier `run-id` perdu, vide (torn) ou
partiellement déchiré n'entraîne **jamais** un redémarrage à froid d'un run
peuplé : l'identité est adoptée du journal (reprise implicite) ou le
redémarrage est refusé (`PlanMismatch`, reprise explicite) — croisement
systématique fichier/journal (R4-01/R4-01b). Un échec du protocole de
reprise libère toujours le verrou (R4-08).

### D8 — Invariant I9 à deux niveaux

Au niveau **contrats** : un nœud `agent` ne porte jamais `write:` ; une
permission `write:` sans `effectPolicy.mode=write` est refusée (règle
réciproque, R4-02). Au niveau **runtime** : le moteur refuse l'exécution
d'un effet d'écriture sans permission correspondante. Aucune écriture
externe directement depuis un nœud agent — incontournable, rappelé par le PO
pour M7.

### D9 — Heartbeat par décision de scheduling, detection-only

Un heartbeat (pid + session + token) est appendu au lockfile par décision de
scheduling. Il mesure la **progression de l'ordonnanceur**, pas la vitalité
continue du processus — cf. L2.

## Known limitations / Revisit triggers

Limites de forme assumées au M5, validées par le PO délégué le 2026-10-24
(verdict « OUI AVEC RÉSERVES »). Chaque limite porte son déclencheur de
réévaluation.

### L1 — I2-avant-émission : la preuve métier post-émission est inexprimable

**Verdict PO : ACCEPTÉ.** Le garde I2 précède l'émission : une tentative
dont l'effet n'a pas abouti ne produit **jamais** de preuve métier persistée
(volontaire, fail-closed — l'ADR M6 note l'exclut explicitement). La RFC
§7.2 permettrait formellement d'exprimer une preuve post-émission ; la forme
actuelle ne l'exprime pas.

**Nuance PO intégrée (traçabilité)** : une preuve de réussite est soumise
aux gardes I2 (jamais produite artificiellement après un échec), mais un
**événement d'exécution ou d'échec** reste journalisable indépendamment des
preuves — vérifié dans l'implémentation : un refus I2 journalise une
transition `blocked` (`failureClass: invalidEvidence`, compteur de budget),
un effet non conclu journalise `effect uncertain` (payload erreur). Aucune
tentative échouée n'est invisible ; seule la preuve métier ne persiste pas.

**Revisit trigger** : un cas réel exigeant une preuve métier post-émission →
évolution de la RFC (jamais un contournement du moteur).

### L2 — Heartbeat par décision : progression ≠ vitalité

**Verdict PO : ACCEPTÉ.** Le heartbeat représente la progression de
l'ordonnanceur et ne constitue ni une preuve de vitalité continue ni une
autorisation de reprise concurrente. **Une absence de heartbeat ne permet
jamais de reprendre le verrou ni de déclarer automatiquement l'ancien
propriétaire mort** — l'escalade documentée (RFC §4.2) est HUMAINE. L'exclusion
mutuelle reste garantie par le flock noyau, jamais par le heartbeat.

**Revisit trigger** (PO) : introduction de workers concurrents, d'exécutions
longues ou d'une récupération automatique → réévaluation de la cadence et de
la sémantique.

### L3 — Queue déchirée du lockfile : tolérance bornée

**Verdict PO : ACCEPTÉ SOUS RÉSERVE.** Les trois invariants PO et leur
implémentation :

1. *Seule une dernière ligne réellement incomplète peut être ignorée* —
   `_critical` ignore une ligne imparsable uniquement en **dernière**
   position (miroir I3) ; une ligne imparsable **médiane** est traitée comme
   un mismatch → refus.
2. *Corruption au milieu → refus fail-closed* — couvert par (1) ; une ligne
   syntaxiquement **valide mais incorrecte** (ex. `acquire` sans
   `generationToken` exploitable) produit également un mismatch →
   `StaleGeneration` → refus.
3. *Token postérieur à toute génération durable, jamais de réutilisation
   silencieuse* — la reprise acquiert un token **nouveau** (UUIDv4, D4),
   appendu en position strictement postérieure à toute ligne durablement
   confirmée ; le fencing exige que ce soit le **dernier** acquire. Aucun
   token antérieur n'est jamais réutilisé.

**Revisit trigger** : si le lockfile devient un protocole de récupération
automatique (au-delà de la détection), la sémantique de purge/récupération
devra être redéfinie explicitement.

## Décisions d'avancement PO (2026-10-24)

- **GO** rédiger et intégrer l'ADR M6 (le présent document).
- **GO** préparer M7 et développer les adaptateurs des skills existants
  (`loop-engineering`, `meeting`, `council`, `deepwork`) derrière des
  adaptateurs — l'activation des écritures externes reste encadrée par les
  politiques d'effets et les permissions existantes (D8).
- **NO-GO** généraliser automatiquement les écritures externes réelles sur
  la seule base du shadow-run.
- **Maintien** de la compatibilité des skills et des mécanismes existants
  (permissions, preuves, approbations).
- Critère de succès M7 : **non-régression des skills existants**, avec un
  branchement **progressif et réversible** sur le noyau.

## Conséquences

- Le noyau M1-M5 est **gelé fonctionnellement** à l'état validé : les
  évolutions passent par la RFC, pas par des contournements.
- Les trois limites sont des contraintes connues, documentées et
  traçables — pas des dettes cachées.
- La bascule (écritures externes réelles) reste subordonnée à un GO PO
  explicite avec QA complète avant/après (S1-S7 + métriques) et approbation
  humaine pour la PR finale vers `main`.

## Références

- RFC : `06-execution-graph-rfc.md` (PR #48, mergée)
- M1-M4 : PR #49 (mergée) — TransitionEngine, persistance, scheduler, contrats
- M5 : PR #50 (mergée) — pilote shadow-run + métriques
- Shadow-run : `shadow-run-pr49-metrics.json`
- Verdicts PO : canal ChatGPT (browser-debug), 2026-10-24 — itérations 3-5
