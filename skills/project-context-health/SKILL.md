---
name: project-context-health
description: Préflight mémoire projet — validateur déterministe 2 niveaux (L1 léger à chaque ouverture, L2 --deep réconciliation ciblée) de docs/ai/ et de l'état git en OUVERTURE de session/tâche. Journal JSONL append-only par worktree (--record = baseline mécanique), états fresh/stale/unknown non exclusifs, jamais de faux fresh, jamais de fallback silencieux. Lecture seule hors --record. Complément d'ouverture de session-finalize (clôture en FIN). Trigger on "project-context-health", "préflight mémoire", "préflight session", "context health", "vérifier la mémoire projet avant de travailler".
---

# Project Context Health — préflight mémoire d'ouverture

Un validateur **déterministe, lecture seule hors `--record`, idempotent, non
éditorial** qui répond à UNE question en ouverture de session ou de tâche :
« docs/ai/ est-il utilisable et frais AVANT de commencer ? » — le complément
d'ouverture de `session-finalize` (qui certifie la clôture, en fin).

```text
python3 skills/project-context-health/context_health.py --project /chemin/du/projet
python3 context_health.py --project . --deep --history
python3 context_health.py --project . --record --mission "chantier X"
python3 context_health.py --project . --strict --max-age-hours 168
```

**Frontière de confiance** (identique à session-finalize) : conformité
mécanique uniquement. `fresh` signifie « les 7 fichiers sont identiques
octet-pour-octet à la baseline enregistrée ET la référence git n'a pas bougé »
— jamais une affirmation sur la validité sémantique ou la fraîcheur globale du
contenu. Un baseline stale signifie « quelque chose a changé », jamais « la
mémoire est fausse ».

## Niveaux de préflight (contrat)

- **L1 (défaut)** : lecture bornée des 7 fichiers + état git + DERNIER
  enregistrement du journal. Pas de scan exhaustif, pas de parsing complet.
  Suffisant pour les 3 axes en < 1 s sur un projet sain.
- **L2 (`--deep`)** : réconciliation ciblée uniquement — diff par fichier
  contre la baseline, diagnostics git bornés, parsing diagnostique de la
  queue du journal avec `--history`. Les diagnostics L2 ont toujours
  `coverage: partial` ; ils n'élèvent JAMAIS une conclusion L1.

## Axes non exclusifs

Un rapport peut porter à la fois `initialized`, `stale` et « pas de baseline »
— un axe ne masque pas l'autre.

| Axe | Certifie | fail | unknown | warning | not_applicable |
|---|---|---|---|---|---|
| `initialization` | les 7 fichiers canoniques existent et sont lisibles | un fichier manquant ou vide | refus de lecture (symlink sortant, illisible) | — | — |
| `last_validation` | une baseline mécanique enregistrée existe | — | évidence corrompue (journal tronqué, illisible, schéma incompatible) | — | absente (premier run : état légitime normal) |
| `freshness` | stabilité mécanique depuis la baseline (fingerprint + référence git) | — | aucun baseline, journal tronqué/corrupte/incompatible (zéro fallback silencieux), baseline datée dans le futur au-delà de 24 h | référence git déplacée (stale, conservateur) ; contenu modifié ; standard_version différente | — |

**Règle unifiée de la queue du journal** : dernière ligne tronquée →
`journal-tail-truncated` ; JSON invalide → `journal-tail-corrupt` ; schéma
incompatible → `schema-incompatible`. Dans tous les cas freshness = `unknown`
et **JAMAIS** de retombée sur un enregistrement antérieur. Le scan arrière
n'existe qu'en diagnostic `--deep --history`, jamais comme preuve L1.

## Journal par worktree

`$(git rev-parse --absolute-git-dir)/project-context-health/journal.jsonl`.

- **Append-only** : un enregistrement n'est jamais réécrit ni tronqué ;
  l'historique est préservé sans perte.
- **Isolation par worktree** : un worktree lié possède son propre git-dir
  (`.git/worktrees/<nom>`), donc deux worktrees du même repo ne peuvent
  JAMAIS se partager des baselines. Filtrage défensif en profondeur :
  un enregistrement dont `project_root` (realpath) ne correspond pas est
  ignoré et compté, jamais comparé.
- **`--record` = baseline mécanique** : une observation figée à l'instant T,
  jamais une certification de vérité documentaire. Normalement produit après
  une clôture vérifiée (certificat session-finalize) — l'enregistrement n'est
  pas la preuve de cette vérification.
- **Refus d'enregistrer un état cassé** : si l'axe initialization est `fail`
  ou `unknown`, `--record` refuse (exit 2) et laisse le journal intact.
- **Verrouillage** : append sous verrou exclusif plateforme (flock POSIX) +
  contrôle d'écriture (re-lecture et re-parsing de la queue). La promesse est
  la **détection** des enregistrements incomplets, pas l'atomicité absolue.
  Risque résiduel accepté par contrat : la re-lecture garantit la cohérence
  logique, pas la durabilité disque après une coupure système (pas de fsync
  forcé) — acceptable pour un journal de baseline non critique. Côté lecteur,
  une queue partiellement écrite pendant un append concurrent est couverte
  par la règle unifiée (→ `unknown`, conservateur).
- **Trois versions découplées** par enregistrement : `record_schema_version`
  (parseabilité), `standard_version` (différente → stale, raison
  `standard-changed`), `tool_version` (une montée seule n'invalide JAMAIS).

## Pin cross-tool

`memory_fingerprint` et `git_status_signature` sont octet-pour-octet
identiques à `session-finalize` (les tests live importent `finalize` avec
skipTest si absent). Ne jamais changer ces sérialisations sans changer les
deux outils ensemble.

## Verdict par précédence (déterministe, identique à session-finalize)

1. ≥ 1 `fail` → **fail** (exit 1)
2. `docs/ai/` entièrement absent → **no_docs** (état légitime, exit 0)
3. ≥ 1 `unknown` → **incomplete** (preuve insuffisante, exit 0)
4. ≥ 1 `warning` → **warning** (exit 0)
5. sinon → **pass** (exit 0)

`--strict` transforme `warning` (et `stale`) en exit 1 mais ne transforme
JAMAIS un manque de preuve (`unknown`) en échec métier.

**Exit codes** : 0 verdict rendu ; 1 échec (ou strict-warn) ; 2 erreur
environnementale. Sur exit 2, deux formes : un **refus explicite** de
`--record` (état cassé, `docs/ai/` absent, git indisponible) émet un JSON
explicite `{recorded: false, refused: true, reason: …}` sur stdout ; une
**erreur inattendue** (échec d'écriture, IO) est rapportée sur stderr avec
stdout vide. Dans les deux cas : zéro écriture partielle.

## Non-objets (contrat)

N'édite jamais un fichier, n'écrit JAMAIS hors `--record` (et jamais dans le
working tree ni docs/ai), ne répare jamais la mémoire, ne décide jamais de la
validité du contenu, ne bloque JAMAIS une session (le verdict est une preuve
pour l'agent, pas un verrou).
