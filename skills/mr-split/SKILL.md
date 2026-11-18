---
name: mr-split
description: "Decide whether a task ships as ONE merge request or SPLITS into several reviewable batches (lots), and produce the batch plan — size evaluation, functional-unit boundaries (tabs, page, reusable component), dependency ordering, final integration batch last (menu, routing, feature switch, legacy removal), incremental publication rhythm (open each MR when its batch is ready, never all at once). Use when a task scope looks heavy for a reviewer, when a migration spans several pages or components, when the user says 'split en plusieurs MR', 'découper en lots', 'plusieurs MRs', 'grosse tâche', 'splite cette MR', 'lots de review', 'découpe en plusieurs merge requests', or during task-workflow Phase 3 to evaluate multi-MR delivery."
---

# MR Split — découpage d'une tâche en lots de MRs reviewables

Tranche **avant le développement** : une tâche part en **une MR** ou en
**plusieurs lots** (une MR par lot), avec un plan de lots validé humainement.

Leçon terrain (migration de pages d'une ancienne admin vers une app cible) :
une MR unique a livré 2 pages complètes + une modale partagée en un seul
diff — le reviewer a demandé « un sacré morceau » à couper en lots (chaque
tab = un lot, la modale = un lot à part, la mise à jour du menu = tout à la
fin au moment du retrait de l'ancienne page). Le code était prêt, mais
l'accumulation a fait perdre le bénéfice principal du split : la review
**au fil de l'eau**, au rythme de l'avancement, sur plusieurs jours.

Ce skill est **procédural** : il ne crée rien automatiquement (ni issue, ni
branche, ni MR) — il produit une évaluation et un plan, et encadre la
séquence d'exécution.

## Quand évaluer

- **task-workflow Phase 3** (intégration principale) : au moment du plan,
  avant Phase 4 ;
- **À la demande** : « split en plusieurs MR », « découpe en lots » ;
- **MR déjà ouverte trop grosse** : arbitrage humain (fermer/recréer en lots
  vs laisser telle quelle) — le skill est surtout **préventif** ; un split
  post-hoc coûte le temps de review déjà investi.

## Évaluation — une MR ou plusieurs lots ?

Signaux **pour** le split (≥ 2 = évaluer sérieusement) :

| Signal | Exemple |
|---|---|
| ≥ 2 unités fonctionnelles **indépendantes** dans la tâche | 2 tabs d'une page, 2 pages, une modale réutilisable + ses consommateurs |
| Composant/infrastructure partagée créée **avec** les pages qui la consomment | modale de sélection de user créée en même temps que la page qui l'utilise |
| Diff attendu nettement au-dessus d'une review ordinaire | migration multi-pages, ~ > 400-600 lignes (indicateur, pas une règle mécanique) |
| Effort > 1-2 jours de développement | l'estimation du plan de la tâche |
| L'intégration visible peut être **différée** | page migrée accessible par URL directe, menu mis à jour plus tard |

**Mono-MR par défaut** : changement localisé, cohésion forte (tout change
ensemble), < ~ 400 lignes — ne pas forcer le split. Un découpage excessif
coûte plus qu'il ne rapporte (contexte à reconstruire à chaque MR).

Doute ou arbitrage produit (périmètre des lots, ordre) → **question humaine
batchée** (gate PO de task-workflow : Contexte / Options / Recommandation /
Conséquences). Jamais un découpage imposé sans GO explicite du périmètre.

## Règles de découpage (invariants)

1. **R1 — Un lot = une unité de review digeste.** Cible indicative : une
   review de l'ordre de 30-45 minutes ; au-delà, découper. Indicateur, pas
   une règle mécanique — la question est « le reviewer tient le diff en tête
   ? ».
2. **R2 — Un lot = une valeur fonctionnelle identifiable**, jamais « des
   fichiers ». « Tab Épisodes de la page Podcast » est un lot ; « les
   fichiers .ts du dossier X » n'en est pas un.
3. **R3 — Composant/infrastructure partagée = lot AVANT ses consommateurs.**
   Une modale, un store, un resolver créés pour plusieurs lots sortent dans
   un lot propre, livré en premier.
4. **R4 — Le lot FINAL = intégration visible + retrait de l'ancien.** Menu,
   navigation, routing, feature switch, suppression de la page héritée : en
   dernier, une seule fois. Avant ce lot, le nouveau doit exister sans être
   exposé aux utilisateurs (migration : page accessible par URL directe,
   menu inchangé jusqu'au retrait).
5. **R5 — Chaque lot compile, passe les tests et ne casse pas l'existant.**
   Si un lot ne tient pas debout seul, la frontière est fausse.
6. **R6 — Tracer les dépendances inter-lots.** Par défaut : lots
   indépendants (branches parallèles depuis la base). Une dépendance forte
   (ex. lot 4 consommant le store/API livré par le lot 3) → lot séquentiel :
   démarrer après le merge du lot dont il dépend (ou rebase temporaire si le
   projet le pratique — arbitrage explicite).
7. **R7 — Pas de découpage excessif.** 3-6 lots est le régime typique ; 2
   petites modifications cohérentes ne font pas 2 MRs — un découpage en 2
   lots reste légitime pour une tâche grosse qui se laisse mal découper en
   davantage d'unités.
8. **R8 — Périmètre in/out par lot, sans chevauchement.** Chaque
   fonctionnalité de la tâche apparaît exactement une fois dans le plan.

## Plan de lots (Batch Plan)

Format (en français — c'est le périmètre présenté à la validation humaine) :

```markdown
## Lot 1 — <titre fonctionnel>
- Périmètre : <ce qui est livré> / Hors périmètre : <ce qui ne l'est pas>
- Fichiers/zones : <zones attendues>
- Dépendances : aucune
- Critère de complétude : <comment on sait que le lot est prêt>
- MR : <lien ajouté au fil de l'eau>

## Lot N (final) — Intégration et retrait
- Périmètre : mise à jour du menu/routing, retrait de la page héritée
- Dépendances : lots 1..N-1 mergés
```

- **Matérialisation — défaut : l'issue de suivi GitLab.** Si la tâche porte
  déjà une issue (issue GitLab source, ou entrée task-workflow) : l'enrichir
  du Batch Plan (description ou commentaire) — **GO humain explicite** requis
  pour toute écriture du tracker. Si la tâche n'a **aucune** issue (carte
  Trello, demande directe) : créer au GO une **issue de tracking** (conventions
  `gitlab-issues`) — titre = tâche globale, corps = source (URL carte ou
  issue), Batch Plan et **checklist des lots** (`- [ ] Lot N — titre`) ;
  **une seule** issue de tracking par tâche — les issues de lot individuelles
  restent un opt-in lié à la tracking, jamais automatiques.
- **Liaison des MRs en relation** : chaque MR de lot mentionne l'issue de
  suivi dans sa description avec un mot-clé **non-closant** (`Related to
  #id`) — **jamais `Closes` sur les lots 1..N-1** : une fermeture prématurée
  tuerait le tracking → GitLab attache la MR à l'issue, l'issue centralise
  les MRs en relation, la case du lot est cochée au merge.
- **Clôture** : au merge du **lot final** — fermeture explicite humaine, ou
  mot-clé de fermeture porté par le lot final seul (si la convention du
  projet l'accepte).
- Variante de matérialisation : section du plan task-workflow — se limiter
  aux étapes du lot courant de CET état (le plan d'un état ne porte jamais
  les étapes des lots exécutés dans d'autres états) et référencer l'issue
  comme source de vérité du plan complet.
- Le GO initial couvre la matérialisation du plan **et ses mises à jour
  mécaniques** (lien de MR ajouté au fil de l'eau, case cochée au merge) ;
  toute modification de **périmètre ou d'ordre** d'un lot re-passe la gate
  PO batchée — jamais de dérive de périmètre silencieuse.

## Rythme de publication (la leçon centrale)

- **Un lot fini = MR ouverte immédiatement** (dev → tests → pre-mr-review →
  create-mr), puis le lot suivant démarre. La review se déroule au fil de
  l'eau, en parallèle du travail sur les lots suivants.
- **JAMAIS toutes les MRs ouvertes en fin de course** : « je finis tout puis
  j'ouvre 4 MRs d'un coup » annule exactement ce que le split apporte — le
  reviewer reçoit la même masse, étalée sur 4 onglets.
- Bénéfice secondaire : un retour de review early sur le lot 1 corrige la
  direction des lots suivants AVANT qu'ils soient écrits.

## Exécution d'un lot

Chaque lot suit le cycle standard, sans mécanisme nouveau :

| Étape | Mécanisme |
|---|---|
| Branche + worktree | skill `new-worktree` (`--base` = cible de MR explicite) |
| Développement | conventions du projet (AGENTS.md), skill `commit` |
| Tests / QA | selon le projet ; QA navigateur si UI exposée par le lot |
| Review pré-MR | skill `pre-mr-review` |
| MR | skill `create-mr` (`--target-branch` explicite, template du projet) |
| Suivi | checklist des lots dans l'issue (un lot mergé = case cochée) |

**Via task-workflow** : recommandé **1 entrée de suivi par lot** (issue liée
à l'issue mère) → 1 cycle complet par lot avec son propre état (l'état
task-workflow porte 1 branche = 1 MR ; ne jamais réutiliser le même état
pour 2 branches). Hors task-workflow, le même cycle s'applique via les
skills ligne à ligne.

## Anti-patterns

- Découper par dossier/fichier au lieu d'unité fonctionnelle (R2).
- Mettre la mise à jour du menu dans le lot 1 — l'utilisateur voit une page
  à moitié migrée (R4).
- Ouvrir toutes les MRs d'un coup en fin de course (voir Rythme).
- 2 MRs qui ne compilent pas séparément (R5).
- Créer issues/branches/MRs sans GO humain sur le plan de lots.
- Modifier le périmètre d'un lot en cours sans mettre le plan à jour
  (Batch Plan — dérive de périmètre).
- Fermer l'issue de tracking prématurément — `Closes` porté par un lot
  intermédiaire ferme le suivi avant le lot final (voir Clôture).
- Splitter une MR déjà en review sans arbitrage humain (coût > bénéfice).

## Compatibilité avec les autres skills

| Skill | Relation |
|---|---|
| `task-workflow` | Integration principale : évaluation en Phase 3, 1 lot = 1 cycle (1 entrée de suivi par lot) |
| `gitlab-feature-planner` | Amont produit (tableau d'estimation → issues) ; mr-split découpe **une tâche en lots de MR**. Si l'issue porte déjà les suggestions mrGroups du planner, elles servent d'**entrée** à l'évaluation (affinées : ordre, dépendances, lot final d'intégration, rythme) — au GO, le plan de lots mr-split prévaut, les mrGroups restent indicatifs |
| `new-worktree` / `commit` / `pre-mr-review` / `create-mr` | Invariants inchangés, appliqués par lot |
| Gate PO (tool `question`) | Le périmètre des lots = décision produit → validation humaine batchée, jamais silencieuse |

## Le projet reste la source de vérité

`AGENTS.md` du projet cible et ses conventions de review priment : si le
projet impose une taille de MR, un type de découpage ou un flux spécifique,
le skill suit la convention locale.
