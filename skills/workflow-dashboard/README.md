# Workflow Dashboard — Universal Progress Core (J1)

Contrat de progression universel pour OpenCode : **tout** ce qui avance (skills,
plans, tâches ad hoc) publie son état dans un format unique, et le dashboard
l'affiche. Ce jalon livre le cœur (contrat + persistance + CLI + adaptateur
task-workflow) — sans rendu (J2) ni intégration Orca (J3) ni relais todowrite
(J4).

## Fichiers

| Fichier | Rôle |
|---|---|
| `wd_core.py` | Contrat `ProgressTopic` v1 : validation, store atomique, verrous, dérivation d'affichage |
| `wd_taskworkflow.py` | Adaptateur NATIF : traduit à la volée les états `task-workflow` (lecture seule, jamais écrit) |
| `wd_publish.py` | CLI de publication (garantie DÉCLARATIVE) : create / step / add-step / set-steps / close / show / list |
| `tests/` | 67 tests (contrat, verrous, concurrence multi-process, atomicité, adaptateur, CLI e2e) |

## Contrat ProgressTopic v1

```jsonc
{
  "schemaVersion": 1,
  "topicId": "uuid-v4",            // identité d'exécution (UUID v5 déterministe pour task-workflow)
  "title": "Objectif lisible",
  "kind": "skill | plan | custom",
  "source": "task-workflow | todowrite-relay | orchestrator-cli",
  "scope": "global | worktree | session",
  "sessionId": "…",                 // requis si scope=session
  "worktreePath": "…",              // requis si scope=worktree
  "parentTopicId": "…",             // optionnel
  "steps": [                        // PLATS + parentId (pas de double comptage)
    { "id": "s1", "label": "…", "status": "DONE", "detail": "…", "updatedAt": "…" }
  ],
  "createdAt": "ISO-8601", "updatedAt": "ISO-8601", "revision": 7
}
```

- **Statuts** : `PENDING | RUNNING | DONE | FAILED | BLOCKED | SKIPPED` —
  terminaux = `DONE/FAILED/SKIPPED`, `BLOCKED` n'est **pas** terminal.
- **Le statut global n'est PAS éditable** : il est dérivé à l'affichage
  (`derive_status`) — le dashboard interprète les transitions publiées, il ne
  décide jamais qu'une tâche est terminée.
- **La source est toujours affichée** : les 3 niveaux de garantie ne se
  mélangent jamais.

## Les 3 niveaux de garantie

1. **NATIF** — `wd_taskworkflow.py` : lecture directe de
   `~/.config/opencode/task-workflows/*.json` (le skill reste inchangé, aucun
   miroir `progress/`). Normalisation d'affichage : `PASSED→DONE`,
   `WAITING_APPROVAL→BLOCKED` (+ detail préservant l'original).
2. **RELAIS NATIF** (J4) — hook `todowrite` = mapping déterministe 1:1 du
   payload, jamais d'inférence.
3. **DÉCLARATIF** — cette CLI ; couverture partielle assumée, c'est la
   discipline de l'orchestrateur.

## Stockage & fiabilité

- Layout : `~/.config/opencode/progress/<scope-key>/<topicId>.json`
  - scope-key : `global` · `worktree-<sha1_12(realpath)>` · `session-<sanitized>`
- Écriture **CLI-only** (jamais d'édition manuelle) : `tmp + os.replace`
  atomique, `revision++` par écriture.
- **Verrou par fichier** (`<topicId>.json.lock`) : `O_CREAT|O_EXCL` + retry ;
  takeover stale **uniquement** si âge dépassé **ET** pid mort — jamais le
  verrou d'un writer actif.
- **Lecture tolérante** : fichier corrompu => entrée signalée (`list --include-errors`),
  jamais un crash (un état réel corrompu a été observé en production).

## CLI

```bash
python3 wd_publish.py create --title "Migration X" --kind plan \
  --source orchestrator-cli --scope worktree --worktree-path /path \
  --step "s1=Analyse" --step "s2=Code"

python3 wd_publish.py step <topicId> s2 RUNNING --detail "en cours"
python3 wd_publish.py close <topicId> --status SKIPPED --detail "abandon assumé"
python3 wd_publish.py list --include-errors
python3 wd_publish.py list --source task-workflow  # topics natifs (non stockés)
python3 wd_publish.py show <topicId>              # topic + progression dérivée
```

Sorties JSON garanties (même en erreur de verrou/OS) ; exit `0` ok · `1`
erreur (contrat/introuvable/verrou) · `2` usage. `show` ne couvre que les
topics **stockés** — les topics natifs task-workflow ne passent que par
`list --source task-workflow` (adaptateur, lecture seule). Overrides
d'environnement (tests/pilotes) : `WD_PROGRESS_DIR`, `WD_TASKWORKFLOW_DIR`.

## Invariants

- Le dashboard est un **lecteur strict** : il n'écrit jamais.
- Les skills restent inchangés ; task-workflow = adaptateur direct (une seule
  source d'autorité par exécution, pas de miroir).
- Zéro dépendance npm/Python tierce (stdlib uniquement).
- Sans relais (J4 absent) : pas de topic todowrite — jamais de donnée fictive.
- Terminés archivés visuellement, jamais supprimés (J2).

## Tests

```bash
python3 -m unittest discover -s skills/workflow-dashboard/tests
```
