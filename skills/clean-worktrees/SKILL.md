---
name: clean-worktrees
description: "Clean up Git worktrees and branches left on the machine that are already merged or no longer exist on origin (squash-merge / deleted MR branch cases). Scans all worktrees of the repository, classifies each entry (merged, gone-on-origin, dirty, active, locked, protected…), shows a plan by default and deletes only on explicit --apply after user GO. Trigger on \"clean-worktrees\", \"clean worktrees\", \"worktree cleanup\", \"nettoyer les worktrees\", \"supprimer les branches mergées\", \"branches plus sur origin\", \"cleanup orca worktrees\", \"prune branches\"."
---

# Clean Worktrees — cleanup des worktrees mergés ou absents d'origin

Une commande pour nettoyer les worktrees (et leurs branches) restés sur la
machine après la fin d'un travail : branche **déjà mergée** dans la branche
d'intégration, ou **plus présente sur origin** (MR mergée avec suppression de
la branche source, merge squash inclus). Pensé pour les espaces Orca : les
worktrees créés par `new-worktree` / `task-workflow` s'accumulent une fois la
MR mergée.

**Requires** : `git`, `python3` (stdlib uniquement — aucune dépendance).

## Nature

Skill **global** (comme `new-worktree`) : installé dans la configuration
globale OpenCode, jamais copié dans les dépôts. Le script détermine tout
lui-même (repo, remote, base, chemins) depuis le répertoire courant.

## Invocation utilisateur

```text
<skill> clean-worktrees
<skill> clean-worktrees --repo /Users/me/dev/podcast-player
<skill> clean-worktrees nettoie les worktrees du projet X
```

L'agent fait tourner le script en mode plan (défaut), présente le résultat,
demande le GO, puis applique avec `--apply`. **Jamais de `--apply` sans
confirmation explicite de l'utilisateur.**

## Procédure

### 1. Lancer le plan (dry-run, aucune mutation)

```bash
python3 "<skill_dir>/clean_worktrees.py" --repo <repo-root>
```

Options utiles : `--remote <name>` (multi-remotes), `--base <name>` (forcer la
branche d'intégration), `--ignore-untracked` (les fichiers non suivis —
`node_modules`, artefacts de build — ne marquent pas le worktree dirty ;
⚠️ ils sont détruits avec le worktree, ne pas utiliser s'ils sont précieux),
`--include-local-only` (voir Classification), `--prune` (nettoie aussi les
entrées stale, avec `--apply`).

### 2. Présenter le plan et demander le GO

Afficher le bloc du script tel quel (sections DELETE / KEEP + summary).
Préciser à l'utilisateur :

- **merged** / **gone-on-origin** = suppression prouvée (aucun commit perdu) ;
- **unverified-origin** = ref distante disparue mais preuve incomplète →
  gardée : suggérer à l'utilisateur de pousser/vérifier manuellement ;
- **dirty** = modifs non commitées → c'est à l'utilisateur de stash/commit
  manuellement, le script ne touchera jamais ce worktree ;
- **local-only** = branche jamais poussée → WIP potentiel, demandé
  explicitement si l'utilisateur veut l'inclure (`--include-local-only`).

Rappeler de fermer les panneaux/terminaux Orca pointant sur les worktrees
DELETE avant d'appliquer (Orca garde ses propres références de panneau).

### 3. Appliquer (après GO uniquement)

```bash
python3 "<skill_dir>/clean_worktrees.py" --repo <repo-root> --apply
```

Ordre garanti : `git worktree remove <path>` puis suppression de la branche.
La sortie liste APPLIED / FAILED + résumé. Un échec (`worktree remove` refusé,
branche checkout ailleurs…) est rapporté, jamais forcé : corriger manuellement
puis relancer.

## Classification

| Statut | Signification | Action |
|--------|---------------|--------|
| `merged` | branche ancêtre de la base (`merge-base --is-ancestor` contre `origin/<base>` ou `<base>` locale) | **DELETE** |
| `gone-on-origin` | upstream configuré + ref distante **observée disparue par le fetch du script** + tip pré-fetch == tip local (tout poussé — voir preuve stricte) | **DELETE** |
| `unverified-origin` | ref distante disparue mais preuve incomplète (état pré-fetch non observé, tip local ≠ tip pré-fetch, fetch en échec) → des commits non poussés ne peuvent être exclus | **keep dur** — jamais supprimé, même avec `--include-local-only` |
| `on-other-remote` | la branche existe sous un autre remote (fork) non sélectionné | skip — gérer via `--remote` |
| `local-only` | jamais poussée, non mergée → WIP potentiel | skip (DELETE avec `--include-local-only`) |
| `active-on-origin` | la branche existe toujours sur origin et n'est pas mergée | skip |
| `dirty` | modifs non commitées (ou non suivies, sans `--ignore-untracked`) | skip |
| `protected` | branche protégée : `main`/`master`/`develop`, la base détectée, ou la branche du worktree principal | skip |
| `current` | le script tourne depuis ce worktree (cwd, y compris sous-dossier) | skip |
| `locked` | worktree verrouillé (`git worktree lock`) | skip |
| `detached` | aucun branch attaché | skip |
| `stale` | dossier absent du disque (ou entrée prunable) | skip — nettoyé par `--apply --prune` |
| `error` | lecture du worktree impossible (`git status` en échec) | skip — investiguer manuellement |
| `main` | worktree principal du repo | jamais touché |

## Détection de la base (jamais hardcodée)

1. `--base` explicite si fourni
2. symref `refs/remotes/<remote>/HEAD` (origin/HEAD)
3. locale dans cet ordre : `develop` → `main` → `master` (convention
   Infomaniak : `develop` = branche d'intégration)
4. en dernier recours : HEAD courant

La ref de comparaison : `origin/<base>` si elle existe (fresque), sinon
`<base>` locale. `git fetch <remote> --prune` est exécuté avant la
classification (best-effort : un remote inaccessible n'est pas bloquant —
warning + état local, direction fail-safe).

## La preuve `gone-on-origin` (stricte)

GitLab/GitHub suppriment la branche source à la merge. Avec un **merge
squash**, la branche locale n'est *pas* ancêtre de la base (le commit squash
est un nouveau commit) : `git branch --merged` ne la voit pas mergée alors
que le travail est intégré.

Supprimer sans risque exige de prouver que **tout** a été poussé. Le script
exige les trois conditions suivantes :

1. la ref de tracking `refs/remotes/<remote>/<branche>` **existait avant le
   `fetch --prune`** du run, à exactement le SHA du tip local (aucun commit
   non poussé) ;
2. le fetch a **réussi** et la ref a disparu après prune (la suppression est
   observée par ce run) ;
3. juste avant le delete, le tip local est **re-vérifié** (aucun commit
   concurrent entre la classification et l'application).

La preuve est persistée entre le run plan et le run apply
(`.git/clean-worktrees-state.json`, TTL 1 h) : le fetch du run plan pruné la
ref, le run apply recharge l'observation. Un fichier absent, périmé ou non
concordant = `unverified-origin` = keep (fail-safe). Idem si un `push
--delete` local a déjà pruné la ref de tracking : la preuve n'est plus
observable, la branche est gardée — l'utilisateur qui sait qu'il a tout
poussé supprime manuellement.

## Codes de sortie

| Code | Sens |
|------|------|
| `0` | plan, ou `--apply` sans échec |
| `1` | `--apply` terminé avec des échecs partiels (section FAILED) |
| `2` | erreur fatale (pas un repo, base introuvable, sortie porcelain malformée…) |

## Robustesse (cas gérés par le script)

| Cas | Comportement |
|-----|--------------|
| invocation depuis un sous-dossier ou un worktree | repo + worktree principal résolus via git |
| plusieurs remotes | `origin` prioritaire, sinon premier remote ; `--remote` pour forcer ; branche poussée vers un autre remote = `on-other-remote` (keep) |
| aucun remote | fetch sauté ; seules les branches mergées localement sont éligibles |
| remote inaccessible | warning + refs distantes restées en l'état (pas de prune) → aucune suppression côté origin (fail-safe) |
| worktree contenant le cwd | jamais supprimé (statut `current`) |
| fichiers non suivis (build, node_modules) | marquent dirty par défaut ; `--ignore-untracked` les ignore à la classification — **mais ils sont détruits avec le worktree** (le remove git efface le dossier), à ne pas utiliser s'ils sont précieux |
| `git worktree remove` refusé par git | FAILED — sauf avec `--ignore-untracked` : retry `--force` uniquement si les fichiers **trackés** sont re-vérifiés propres à l'instant (jamais de force à l'aveugle) |
| branche checkout dans le worktree supprimé | ordre garanti : remove worktree → delete branch, tip re-vérifié entre les deux |
| entrées prunable / dossier supprimé à la main | statut `stale` ; `git worktree prune` uniquement via `--apply --prune` |
| merge squash / MR avec suppression de branche | couvert par le statut `gone-on-origin` (preuve stricte ci-dessous) |
| plan → apply = 2 runs | la preuve `gone-on-origin` survit au premier fetch via `.git/clean-worktrees-state.json` (TTL 1 h) |

## Règles de sécurité (règles dures)

- **Le plan précède toujours l'application** : mode dry-run par défaut ;
  `--apply` n'est jamais passé sans le GO explicite de l'utilisateur, après
  présentation du plan.
- Le worktree principal n'est jamais supprimé. Les branches `main`, `master`,
  `develop`, la base détectée et la branche du worktree principal ne sont
  jamais touchées.
- `git worktree remove --force` n'est jamais passé sans `--ignore-untracked` ET
  une re-vérification à l'instant que les fichiers trackés sont propres. Le
  remove (forcé ou non) détruit aussi les fichiers **non suivis** du dossier :
  ne jamais utiliser `--ignore-untracked` sur un worktree pouvant contenir des
  fichiers non suivis précieux (`.env`, config locale…).
- `git branch -D` ne tourne que sur des branches prouvées : ancêtre d'une ref
  de base, ou preuve `gone-on-origin` stricte (état pré-fetch == tip local +
  suppression observée par le fetch du script + tip re-vérifié) — le `-d` de
  git est plus faible (relatif au HEAD courant) et refuserait des suppressions
  valides (squash, origin/base en avance du local).
- Le script n'écrit jamais sur le remote : lecture seule (fetch --prune).
  Jamais de push, force-push, reset, stash, clean.
- Une branche jamais poussée (potentiel WIP) est sautée par défaut —
  `--include-local-only` exige d'avoir demandé à l'utilisateur.

## Anti-patterns

- Lancer `--apply` sans avoir montré le plan ni obtenu le GO.
- Passer `--include-local-only` sans avoir explicitement signalé le risque WIP
  à l'utilisateur.
- Supprimer manuellement `git worktree remove --force` / `git branch -D` en
  dehors du script (perte de la classification et des gardes).
- Confondre avec le skill OMO `worktrees` (lanes d'agents sous
  `.slim/worktrees/` — son protocole de cleanup à lui s'applique aux lanes, ce
  skill aux worktrees convention `new-worktree`).
- Exécuter le script depuis l'intérieur d'un worktree à supprimer : il se
  protège seul (statut `current`), ne pas contourner.

## Tests

```bash
python3 -m unittest discover -s skills/clean-worktrees/tests -v
```

Couverture (23 tests e2e) : classification sur dépôts temporaires avec remote
(merged, gone-on-origin après suppression serveur, gone-on-origin bloquée par
un commit non poussé, fail-safe offline fetch en échec, ref prunée + offline,
local-only, active-on-origin, dirty, untracked, protected, current, locked,
detached, stale, sans remote, multi-remotes on-other-remote) + garanties
(plan sans mutation, branche du worktree principal préservée, précédences
protected/locked > merged, détection de base chemins 3-4, current en
sous-dossier) + suppression effective en `--apply`.
