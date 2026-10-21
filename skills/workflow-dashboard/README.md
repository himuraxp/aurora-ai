# Workflow Dashboard — Universal Progress Core (J1→J4)

Contrat de progression universel pour OpenCode : **tout** ce qui avance (skills,
plans, tâches ad hoc) publie son état dans un format unique, et le dashboard
l'affiche. Livraisons : J1 cœur (contrat + persistance + CLI + adaptateur
task-workflow), J2 renderer terminal, J3 intégration pane Orca, J4 relais
todowrite (plugin).

## Fichiers

| Fichier | Rôle |
|---|---|
| `wd_core.py` | Contrat `ProgressTopic` v1 : validation, store atomique, verrous, dérivation d'affichage |
| `wd_taskworkflow.py` | Adaptateur NATIF : traduit à la volée les états `task-workflow` (lecture seule, jamais écrit) |
| `wd_publish.py` | CLI de publication (garantie DÉCLARATIVE) : create / step / add-step / set-steps / close / show / list |
| `wd_dashboard.py` | Renderer terminal (LECTURE SEULE STRICTE) : 3 catégories, `--watch`, `--verbose` |
| `wd_orca.py` | Intégration pane Orca (idempotent) : ensure / close / status |
| `wd_relay.py` | Relais todowrite (RELAIS NATIF) : `reconcile <sessionID> <todos|->` |
| `tests/` | 147 tests (contrat, verrous, concurrence multi-process, atomicité, adaptateur, renderer, Orca, relais, CLI e2e) |

## Contrat ProgressTopic v1

```jsonc
{
  "schemaVersion": 1,
  "topicId": "uuid",               // v4 au create CLI ; v5 déterministe pour les sources natives
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
  mélangent jamais. Abréviations en faible largeur : `[tw] [tr] [oc]`.

## Les 3 niveaux de garantie

1. **NATIF** — `wd_taskworkflow.py` : lecture directe de
   `~/.config/opencode/task-workflows/*.json` (le skill reste inchangé, aucun
   miroir `progress/`). Normalisation d'affichage : `PASSED→DONE`,
   `WAITING_APPROVAL→BLOCKED` (+ detail préservant l'original).
2. **RELAIS NATIF** — `wd_relay.py` + plugin `config/plugins/wd-relay.ts` :
   hook `tool.execute.after` sur `todowrite`, mapping déterministe 1:1 du
   payload (`pending→PENDING`, `in_progress→RUNNING`, `completed→DONE` ;
   inconnu → `PENDING` + trace). **topicId = UUID v5** dérivé de la session
   (`todowrite:<sessionID>`) : association session→topic stable **sans état**,
   réconciliation complète à chaque event (le payload gagne sur tout, y
   compris l'effacement des traces obsolètes).
3. **DÉCLARATIF** — `wd_publish.py` ; couverture partielle assumée, c'est la
   discipline de l'orchestrateur.

## Stockage & fiabilité

- Layout : `~/.config/opencode/progress/<scope-key>/<topicId>.json`
  - scope-key : `global` · `worktree-<sha1_12(realpath)>` · `session-<sanitized>`
- Écriture **CLI-only** (jamais d'édition manuelle) : `tmp + os.replace`
  atomique, `revision++` par écriture.
- **Verrou par fichier** (`<topicId>.json.lock`) : `O_CREAT|O_EXCL` + retry ;
  takeover stale **uniquement** si âge dépassé **ET** pid mort — jamais le
  verrou d'un writer actif. Non réentrant intra-process (writers = process
  séparés) ; `ensure`/`close` du pane utilisent un FileLock sur leur état.
- **Lecture tolérante** : fichier corrompu => entrée signalée (`list
  --include-errors`, compteur renderer), jamais un crash.
- État des panes Orca : `~/.config/opencode/workflow-dashboard-panes.json`
  (hors du répertoire `progress/`, RMW sous `FileLock`).

## CLI

```bash
python3 wd_publish.py create --title "Migration X" --kind plan \
  --source orchestrator-cli --scope worktree --worktree-path /path \
  --step "s1=Analyse" --step "s2=Code"

python3 wd_publish.py step <topicId> s2 RUNNING --detail "en cours"
python3 wd_publish.py close <topicId> --status SKIPPED --detail "abandon assumé"
python3 wd_publish.py list --include-errors
python3 wd_publish.py list --source task-workflow  # topics natifs (non stockés)
python3 wd_publish.py show <topicId>               # topic + progression dérivée
```

Sorties JSON garanties (même en erreur de verrou/OS) ; exit `0` ok · `1`
erreur (contrat/introuvable/verrou) · `2` usage. `show` ne couvre que les
topics **stockés** — les topics natifs task-workflow ne passent que par
`list --source task-workflow` (adaptateur, lecture seule).

```bash
# Renderer (lecture seule, vue hiérarchique : étapes ouvertes sous chaque
# sujet actif, cap 3 + « +N ») :
python3 wd_dashboard.py [--watch 0.5] [--verbose] [--width N] [--session-id S]

# Pane Orca (idempotent — SPLIT du terminal OpenCode du worktree, JAMAIS un
# nouvel onglet ; ORCA_TERMINAL_HANDLE prioritaire, sinon découverte via
# `orca terminal list` filtrée agentIdentity=opencode + worktree courant) :
python3 wd_orca.py ensure --worktree-path /path [--session-id S] [--watch 0.5]
python3 wd_orca.py close --worktree-path /path && python3 wd_orca.py status
# re-lance un pane : close puis ensure (nouveau handle, sans duplication)

# Relais todowrite (appelé par le plugin ; utilisable manuellement) :
python3 wd_relay.py reconcile <sessionID> '[{"content":"A","status":"in_progress"}]'
python3 wd_relay.py reconcile <sessionID> -         # payload par stdin
```

Le relais : exit `0` ok · `1` erreur (JSON sur stdout) · `2` usage (texte
stderr, pattern `wd_publish`). Overrides d'environnement : `WD_PROGRESS_DIR`,
`WD_TASKWORKFLOW_DIR`, `WD_SESSION_ID` (priorité session renderer),
`WD_PANES_STATE_FILE`, `WD_ORCA_BIN`, `WD_RELAY_SCRIPT` (plugin).

## Plugin wd-relay (J4)

`config/plugins/wd-relay.ts` — hook `tool.execute.after` filtré sur
`todowrite` : payload par **stdin** vers `wd_relay.py` (argv-array + stdin :
aucune injection, pas de limite ARG_MAX), try/catch **total** sur le handler —
aucun crash du relais n'interrompt jamais le workflow. Skip loggué sans
payload exploitable ni `sessionID` : jamais de donnée fictive. Déployé par
`install.sh` vers `~/.config/opencode/plugins/` (auto-load) ; le script
`wd_relay.py` vers `~/.config/opencode/skills/workflow-dashboard/`.

**Preuve E2E du hook (sonde 2026-10-21, opencode v2.1.2)** : le hook
`tool.execute.after` ne fire qu'en **format V1** (fonction plugin retournant
l'objet Hooks) ; l'API v2 `ctx.tool.hook("execute.after")` s'enregistre
**sans fire** (seul `execute.before` est routé). Shape runtime réelle :
`input = {tool, sessionID, agent, messageID, id, input, status, result}` —
`sessionID` présent, args du tool dans `input`. Le test d'intégration
`tests/test_plugin_relay.py` rejoue ce chemin complet (payload → hook →
`wd_relay.py` → store) à chaque suite.

**Caveat v2.1.2** : le tool natif `todowrite` n'est plus exposé dans le
catalogue des agents de cette version (le renderer TUI le connaît pour
rétrocompat). Le relais reste câblé, testé, et s'activera sur toute
version/fork exposant `todowrite` — aucune donnée fictive entre-temps.

**Smoke E2E du relais** (critère E2E #2 — à exécuter après déploiement) :
1. Ouvrir une session OpenCode, demander un plan (`todowrite` se déclenche).
2. Vérifier `~/.config/opencode/progress/session-*/<topicId>.json` — topicId
   = `uuid5(todowrite:<sessionID>)`, source `todowrite-relay`.
3. Avancer le plan, re-vérifier : mêmes topicId, statuts réconciliés
   (payload gagne), log `[wd-relay]` sans erreur.

## Invariants

- Le dashboard est un **lecteur strict** : il n'écrit jamais.
- Les skills restent inchangés ; task-workflow = adaptateur direct (une seule
  source d'autorité par exécution, pas de miroir).
- Zéro dépendance npm/Python tierce (stdlib uniquement).
- Sans relais (plugin absent) : pas de topic todowrite — jamais de donnée
  fictive.
- Terminés archivés visuellement (fenêtre 48h + compteur `+N`), jamais
  supprimés ; sources illisibles signalées (jamais muettes).

## Tests

```bash
python3 -m unittest discover -s skills/workflow-dashboard/tests   # 146 tests
```
