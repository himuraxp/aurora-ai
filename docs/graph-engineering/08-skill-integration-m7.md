# 08 — Intégration des skills au Core (M7) : stratégie d'adaptateurs

- **Statut** : Accepted
- **Date** : 2026-10-24
- **Décideurs** : PO délégué (GO « adaptateurs des skills existants », NO-GO « écritures externes réelles »), Aurora (implémentation)
- **Prérequis** : ADR `07-adr-execution-graph-core.md` (décisions D1-D9, limites L1-L3), RFC `06-execution-graph-rfc.md` (§11 M7)

## 1. Principe : les skills restent la référence

Les skills existants (`task-workflow`, `commit`, `create-mr`, `mr-review`,
`meeting`, `council`, `loop-engineering`, `deepwork`, …) ne sont **jamais
modifiés** par M7. Le Core les orchestre **derrière des adaptateurs** :
`git diff` sur l'itération 6 prouve zéro modification hors
`skills/graph_core/` et `docs/graph-engineering/`. Le branchement est
**progressif et réversible** : le Core est un module additif, aucun point
d'entrée existant ne change, et la désactivation revient à ne plus
instancier l'adaptateur.

## 2. L'adaptateur shadow-read-first (`skills/graph_core/skill_adapter.py`)

L'adaptateur transforme une **spécification de tâches de skill** en
`GraphDefinition` conforme :

```python
specs = [
  {"id": "fetch", "kind": "process",
   "command": ["python3", "-c", "print('diff-ok')"]},
  {"id": "analyze", "kind": "analysis", "deps": ["fetch"]},
]
result = run_skill_graph("mon-workflow", specs, run_dir, lock_path)
```

Garanties fail-closed de l'adaptateur (en plus des contrats I9 du noyau) :

| Garantie | Mécanisme |
|---|---|
| Aucune écriture externe exprimable | tout `effectPolicy` est **refusé** (NO-GO PO 2026-10-24) |
| Permissions forcées en lecture | `permissions` imposé `read:fs, read:repo` — une permission `write:` déclarée par l'appelant est ignorée |
| `agent` jamais écrivain | kind `analysis` → nœud `agent` (I9 par contrats), kind `process` → nœud `tool` |
| Effets journalisés sans émission | `SandboxEffectDispatcher` obligatoire — `realEffectEmissions: 0` |
| Preuve technique par commande | exit code journalisé comme evidence (`exitCode == 0` requis par I2, artifactRef = stdout) |
| Commande faillible bornée | budget `technical` + timeout `subprocess` → échec terminal I8, descendants visiblement `pending` |

## 3. Démo réelle (preuve de branchement)

`skill-adapter-demo-metrics.json` : un graphe de 2 nœuds a exécuté, via le
Core, une **lecture réelle** de l'état du workflow actuel
(`tw-aurora-ai--8c7fb888-iter5.json` — read-only) suivie d'une analyse
statique : 2/2 complétés, successRate 1.0, 0 émission réelle, 0
intervention humaine, 0 problème journal. Le workflow actuel reste la
référence ; le Core l'a **lu**, jamais piloté.

## 4. Mapping des kinds et évolution

| kind M7 | Nœud | Executor | Écritures |
|---|---|---|---|
| `process` | `tool` | `subprocess` read-only déclaré par l'appelant | interdites (NO-GO) |
| `analysis` | `agent` | callable fourni (analyse statique/LLM-grade côté système actuel) | interdites (I9) |

Évolutions prévues **après** bascule validée (hors M7) : un kind
`dispatch` dont l'émission passerait par le protocole d'effets §7.2 avec un
dispatcher **réel** (getBeforePost, idempotencyKey, block par défaut) —
subordonné au GO PO explicite, à la QA avant/après (S1-S7 + métriques) et à
l'approbation humaine de la PR finale vers `main`.

## 5. Critère de non-régression (PO)

Avant chaque merge d'une itération de branchement :

1. `git diff <base>..HEAD` vide hors `skills/graph_core/` +
   `docs/graph-engineering/` ;
2. suites vertes : core (73) + pilote (16) + adaptateur (11) = 84 tests
   sous `-W error::ResourceWarning` ;
3. `tw_state.py validate` sur les états de workflow existants : `state
   valid` (coexistence M1, jamais modifié).

## 6. Limites connues de l'adaptateur (M7)

- Les executors `analysis` du M7 sont des **stubs** : l'analyse LLM-grade
  reste le travail du système actuel ; M7 mesure le squelette d'exécution
  (même posture que M5).
- Une commande `process` faussement déclarée « read-only » par son auteur
  ne peut pas être détectée par l'adaptateur — la discipline read-only est
  de la responsabilité de l'appelant ; l'adaptateur garantit uniquement
  l'absence d'**effet d'écriture journalisé** (NO-GO structural). Une
  extension sandbox filesystem (itération éventuelle M8) pourrait durcir
  cette garantie.
- Le couplage skill→Core inverse (un skill qui **invoque** le Core) reste
  réservé à une itération ultérieure : M7 est Core→skills, additif et
  réversible.
