---
name: session-finalize
description: Certificat de clôture de session — validateur déterministe, lecture seule, idempotent et non éditorial de la mémoire projet docs/ai/ et de l'état git au moment T. Émet un certificat JSON (invariants mécaniques, empreintes SHA-256, verdict par précédence) que l'agent reporte dans son message de rendu. Ne décide JAMAIS du statut de mission, ne bloque JAMAIS la fin de session, n'écrit JAMAIS. Trigger on "session-finalize", "certificat de clôture", "certificat mémoire", "valider la mémoire avant de rendre la main", "closure certificate".
---

# Session Finalize — certificat de clôture de session

Un validateur **déterministe, lecture seule, idempotent, non éditorial** qui
produit un **certificat de clôture** : un instantané vérifiable de l'état
mécanique de la mémoire projet (`docs/ai/`) et du working tree au moment T.

```text
python3 skills/session-finalize/finalize.py --project /chemin/du/projet
python3 finalize.py --project . --mission "chantier A" --max-age-hours 168 --strict
```

**Non-objets (contrat)** : n'édite jamais un fichier, n'écrit jamais dans le
repo, ne décide jamais du statut d'une mission, ne bloque jamais la fin de
session. Le certificat est une **preuve, pas un verrou**. La règle « un échec
n'efface jamais le travail » est procédurale : l'agent DOIT reporter le
verdict dans son message de fin (câblé dans `standards/memory-checklist.md`),
jamais mécanique.

**Frontière de confiance** (comme design-qa) : le validateur certifie la
présence, la fraîcheur et la cohérence mécanique — il ne prouve JAMAIS que le
contenu est vrai. Un STATUS à jour mais faux passe.

## Contrat d'entrée / sortie

- **Entrée** : `--project` (défaut : cwd), `--max-age-hours` (opt-in, **sans
  valeur par défaut** — absent = aucune contrainte d'âge), `--strict`
  (opt-in), `--mission` (libre, embarqué dans le certificat).
- **Sortie** : certificat JSON garanti sur stdout, **zéro écriture**.
  `stderr` + exit 2 uniquement pour une erreur environnementale.

## Invariants (v1.1 — 6 vérifications mécaniques)

| Check | Certifie | fail si | warning si | unknown si |
|---|---|---|---|---|
| `memory_presence` | les 7 fichiers canoniques existent | un fichier manque | — | présent mais refusé en lecture (symlink sortant, illisible, répertoire) |
| `memory_initialized` | fichier non vide, non identique au squelette canonique | vide ou squelette | — | refusé en lecture, ou contenu non interprétable |
| `memory_recency` | STATUS + CHANGELOG portent une entrée datée (heading YYYY-MM-DD, formats mixtes acceptés) | — | entrée datée la plus **récente** d'âge > `--max-age-hours` (si fourni) | aucune date parseable, date future au-delà d'une tolérance de +24 h (dérive d'horloge) |
| `memory_versioned` | docs/ai tracké propre | — | fichiers trackés modifiés non commités | erreur git en cours d'exécution |
| `worktree_snapshot` | branch, HEAD, `git_status_signature` (état git, JAMAIS le contenu) | — | WIP non commité hors docs/ai | erreur git en cours d'exécution |
| `plan_status_enum` | clé simple `status:` de PLAN dans l'enum standard | valeur hors enum | — | forme non interprétable |

**Résultats par check** : `pass` / `fail` / `warning` / `unknown` /
`not_applicable` (+ `unknown_reason`). `not_applicable` (projet non-git,
mémoire non trackée, contrôle hors domaine) ne compte dans **aucune**
catégorie — une observation non applicable n'est pas une preuve manquante.

## Verdict par précédence (déterministe)

1. ≥ 1 `fail` → **fail**
2. `docs/ai/` entièrement absent → **no_docs** (état légitime déclaré)
3. ≥ 1 `unknown` → **incomplete** (preuve insuffisante, jamais un échec métier)
4. ≥ 1 `warning` → **warning**
5. sinon → **pass**

**Exit codes** :

| Verdict | normal | `--strict` |
|---|---|---|
| pass | 0 | 0 |
| warning | 0 | 1 |
| incomplete | 0 | **0** — `--strict` ne transforme jamais un manque de preuve en échec métier |
| no_docs | 0 | 0 |
| fail | 1 | 1 |
| erreur environnementale | 2 | 2 |

## Certificat

```json
{
  "schema_version": 1,
  "tool_version": "1.1.0",
  "mission": "chantier A",
  "snapshot": {
    "project_root": "/chemin/du/projet",
    "branch": "feat/session-finalize",
    "head_sha": "07b2801f67c2…",
    "git_status_signature": "1b4eb4b526c2f5a6…",
    "memory_fingerprint": "sha256:9f86d081884c7d65…",
    "generated_at": "2026-11-05T14:30:00.000000+00:00",
    "checks": [{ "id": "memory_presence", "result": "pass", "detail": { } }]
  },
  "summary": { "verdict": "pass", "counts": { } }
}
```

- **`git_status_signature`** = `sha1(head + "\n" + porcelain_brut)` — la
  sérialisation est **octet pour octet** celle du `codeSignature` de
  task-workflow (`tw_state.compute_code_signature`), compatibilité
  inter-outils exacte. Garantie **strictement limitée** : signature d'état git
  (quels chemins diffèrent de HEAD), pas une empreinte de contenu du working
  tree — un `git status` ne liste pas le contenu, et deux versions d'un même
  fichier modifié peuvent produire la même signature. La validité du contenu
  de `docs/ai/` est attestée **uniquement** par `memory_fingerprint`.
- **`memory_fingerprint`** = SHA-256 en encodage longueur-préfixé canonique
  sur les 7 fichiers en ordre alphabétique fixe, distinction explicite
  PRESENT/ABSENT (un fichier absent ≠ un fichier vide). Un ancien certificat
  ne peut pas être présenté comme valide après une modification locale. Un
  hash n'est pas une signature cryptographique d'authenticité.
- **Idempotence** : même état observé + même instant d'évaluation → mêmes
  résultats, à l'exception de `generated_at`. Quand `--max-age-hours` est
  activé, le verdict de récence **dépend de l'instant d'évaluation** — un
  contrôle peut passer de `pass` à `warning` avec le temps, à fichiers
  identiques. Documenté, pas un défaut.

## Read-only effectif (pas juste « aucune écriture »)

- Sous-commandes git **whitelistées** : `rev-parse`, `status`, `ls-files` —
  toute autre est refusée par construction (`ValueError`).
- L'environnement `GIT_*` hérité est **purgé** (aucune redirection par
  `GIT_DIR`/`GIT_WORK_TREE` de l'appelant) et `core.fsmonitor` est épinglé à
  `false` (aucun daemon fsmonitor, rien n'est écrit dans `.git/`) ; git est
  exécuté avec `GIT_OPTIONAL_LOCKS=0` : jamais de rafraîchissement d'index ni
  de création de `index.lock`.
- Aucun shell, timeout 30 s sur chaque commande.
- Lectures de fichiers **confinées** : le realpath **complet** (chaque
  composant de chemin est résolu) doit rester sous la racine du projet — un
  symlink de fichier ou de répertoire (y compris `docs/ai` lui-même) qui
  sortirait du périmètre → `unknown` (pas de lecture), jamais de suivi hors
  périmètre.
- Les **tests vérifient la non-mutation** : octets de `.git/index`
  (`git rev-parse --git-path index`, SHA-256 avant/après — y compris dans un
  worktree), `git status` avant/après, contenus mémoire avant/après.

## Compatibilité projets sans git

Un projet non-git est un état déclaré : `worktree_snapshot` et
`memory_versioned` retournent `not_applicable` (jamais `unknown` — ce n'est
pas une preuve manquante, le domaine ne s'applique pas). Les autres checks
s'appliquent normalement. La même sémantique s'applique au binaire git absent
(état déclaré) ; un échec en cours d'exécution sur un repo utilisable
(timeout, erreur I/O) est une preuve manquante → `unknown`.

## Tests

```text
python3 skills/session-finalize/tests/test_finalize.py        # unittest, offline
```

Couverture : projets sans mémoire, fichiers manquants, formats de dates
mixtes, frontmatter valide/illégale/non interprétable/absent, dépôts non-git,
mémoire git-ignorée, états WIP, squelettes canoniques, récence opt-in,
idempotence, compatibilité octet-pour-octet avec task-workflow, non-mutation
(index, porcelain, contenus — y compris dans un worktree).

## Fin de session (usage recommandé)

Voir `standards/memory-checklist.md` → section « Certificat de clôture
(recommandé) » : lancer le validateur après avoir mis la mémoire à jour, puis
reporter `verdict` + `memory_fingerprint` (tronqué) + `git_status_signature`
(tronqué) dans le message de rendu. Un échec environnemental (exit 2) est
signalé, jamais silencieux. Recommandé, jamais bloquant en v1.
