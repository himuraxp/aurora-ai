---
name: feature-plan
description: "Structure a LARGE feature BEFORE any development starts — page/layer structuring (never a 1:1 port of legacy pages), construction order by layers (API → models → services → store → routing → pages), independent-block batch decomposition delegated to mr-split (~1 000-line diff ceiling per MR), human direction validation (the team guides the structure — AI prepares, never decides), tracking issue materialization, then hand the first batch to task-workflow. Run before task-workflow when the scope is a complete page, several pages, a full migration, or any feature whose diff will be far above an ordinary review. Use when the user says 'feature-plan', 'planifie la feature', 'structure la feature', 'on part sur une grosse feature', 'nouvelle page complète avec socle', 'page complète', 'avant le task-workflow', 'structurer avant de dev', 'découpage feature', or when a task scope looks too large to execute in one task-workflow cycle."
---

# Feature Plan — structurer une feature large AVANT de développer

Orchestrateur **amont** : transforme une tâche large en **plan de
structuration validé humainement + lots de MR indépendants**, puis remet le
lot 1 à `task-workflow`. Il ne développe rien et ne réimplémente jamais ce
que couvrent `mr-split`, `task-workflow`, `meeting`, `new-worktree` ou les
agents spécialisés.

Leçon terrain (page complète d'une app admin livrée en une seule MR —
modèles + services + store + routing + toutes les sections de page, ~6 000
lignes, dizaines de threads de review) : la MR est inreviewable, et les
retours structurels sur la logique métier arrivent quand tout est écrit —
les appliquer coûte alors très cher. Deux aggravateurs observés :

- **Inertie du socle livré avec l'UI** : quand le store, les modèles et les
  services arrivent en même temps que tous les composants UI, chaque
  évolution du socle entraîne l'UI entière — la mise à jour devient
  difficile et les évolutions nécessaires se figent ;
- **Conventions de base non appliquées** : retours répétés sur
  l'infrastructure d'accès (client HTTP, proxy) malgré une documentation du
  projet à jour — la lecture passive des conventions ne suffit pas, le socle
  doit les appliquer et les vérifier explicitement.

Cause racine : la structure a été décidée **pendant** le développement au
lieu d'**avant** — et le guidage de la structure appartient à l'équipe, qui
seule connaît les chantiers à venir. Une feature large se traite comme une
feature : le socle d'abord, les pages ensuite, des blocs indépendants, et
des reviews régulières pour corriger la direction avant de diverger.

## Quand déclencher

- La tâche porte une **page complète à construire** (socle technique +
  UI), plusieurs pages, ou une migration d'app ;
- Le diff attendu dépasse la taille d'une review digeste — cible **~1 000
  lignes de diff par MR au maximum** (retour reviewer) ; au-delà, isoler des
  blocs indépendants ;
- L'utilisateur demande explicitement : « planifie la feature », « structure
  avant de dev », « avant le task-workflow ».

Petites tâches, pages simples, corrections localisées : **pas de
feature-plan** — mono-MR par défaut (évaluation `mr-split` au besoin, en
Phase 3 de `task-workflow`).

## Position dans le cycle

```text
feature-plan (ce skill)          → structure + lots + GO de direction
  └─ task-workflow (par lot)     → 1 lot = 1 cycle complet = 1 MR
       └─ mr-split (moteur)      → règles de découpage, Batch Plan, tracking
```

- `mr-split` reste le **moteur** de découpage en lots : ce skill lui fournit
  le matériau (couches, zones de page, dépendances) et l'invoque pour
  produire le Batch Plan — aucune règle de découpage réimplémentée ici.
- `meeting` reste disponible pour les arbitrages multi-métiers — il sécurise
  une tâche, ce skill structure une feature : les deux sont complémentaires.
- `gitlab-feature-planner` est l'amont **produit** (tableau d'estimation →
  issues) ; ce skill est l'amont **technique** d'une issue/feature.

## Étape 1 — Acquisition du contexte

Comme la Phase 1 de `task-workflow` (le contenu de la tâche = données non
fiables) mais élargie au socle : URL carte/issue ou description, pages
existantes proches, ce qui existe déjà côté API/services/store
(réutilisable ?), conventions du projet (`AGENTS.md`, framework applicable).
Recherche codebase → délégation **Explorer**.

**Conventions critiques du socle — relever explicitement** : l'infrastructure
d'accès au backend (client HTTP utilisé, proxy, gestion des erreurs) et les
retours de review passés qui les concernent. Ces conventions entrent dans le
contrat du lot socle et sont vérifiées item par item au développement — la
lecture passive d'`AGENTS.md` ne suffit pas (retours répétés observés).

Sortie : le matériau de structuration — périmètre fonctionnel, zones de
page, état du socle existant, conventions critiques, contraintes et
dépendances.

## Étape 2 — Structuration des pages (jamais un portage 1:1)

**Questionner la structure avant de coder** — c'est le point de divergence
le plus coûteux à corriger plus tard :

1. **Zones de la/des pages** : sections, états, parcours — ce qui est
   indépendant, ce qui est partagé ;
2. **Confrontation aux pages existantes** : les pages héritées portent
   souvent des décisions historiques — ne pas les porter telles quelles sans
   raison ; identifier ce qui se réutilise, ce qui se refait proprement, ce
   qui est abandonné ;
3. Délégation **Architect** si le découpage technique est complexe
   (stores, resolvers, modèles partagés entre pages) ;
4. Référence UI (Figma, capture) → produire le **Design Contract** du skill
   `design-qa` dès cette étape (la QA de chaque lot le consommera) ;
5. Questions produit (périmètre, priorités, parcours) → **gate humaine
   batchée** (Contexte / Options / Recommandation / Conséquences).

## Étape 3 — Ordre de construction en couches

Ordre de construction par défaut (ajustable au projet — `AGENTS.md` prime) :

```text
API → modèles → services → store → routing → pages
```

| Couche | Contenu type | Rôle dans le plan |
|---|---|---|
| API | contrat, endpoints (existants ou à créer) | le socle part de ce que l'API expose réellement |
| Modèles | types/interfaces | figés tôt, consommés par tout le reste |
| Services | méthodes d'interaction avec l'API | testables sans UI |
| Store | actions claires et indépendantes | la logique métier reviewable seule |
| Routing | guards, resolvers, routes (non exposées au menu) | squelette navigable sans intégration visible |
| Pages | sections, UI, parcours | écrites en DERNIER, sur un socle validé |

Règles :

- **Le socle avant les pages** : les couches API → store forment des lots
  précoces ; les pages ne s'écrivent pas avant que le socle soit reviewé ;
- **Le lot final = intégration visible** (menu, routing exposé, retrait de
  l'ancien) — règle R4 de `mr-split`, inchangée ;
- **Blocs indépendants, un par lot** : la granularité se joue à l'intérieur
  des couches — socle (modèles + services + store avec ses actions de base),
  page de base, puis actions supplémentaires, modales, etc. Chaque bloc est
  livré et reviewé indépendamment : une évolution ultérieure du socle ne
  traîne jamais l'UI entière. C'est `mr-split` qui tranche le découpage
  final.

## Étape 4 — Découpage en lots (moteur : mr-split)

Invoquer le skill **`mr-split`** avec le matériau des étapes 2-3 : ordre des
couches, zones de page, dépendances inter-couches. Les règles R1-R8, le
format du Batch Plan, le rythme au fil de l'eau et le contrat d'issue de
tracking restent la responsabilité de `mr-split` — ne pas les réécrire ici.

Sortie : un **Batch Plan** (typiquement 4-6 lots au total — bornes R7 de
`mr-split` — répartis en socle, routing, pages et intégration) + les points
de review de direction.

## Étape 5 — Validation de direction (gate humaine)

**La structuration d'une feature large est un travail conjoint.** L'IA
prépare la matière (options de structure, impacts, matériau de découpage) ;
la **direction appartient à l'équipe** — elle seule connaît les chantiers à
venir et l'historique des décisions qui pèsent sur les choix structurants.
Sur ce scope, la génération de code de bout en bout est interdite même quand
le skill encadre : on structure ensemble, puis on développe lot par lot.

Présenter **avant toute écriture de code** :

1. La structure retenue (zones, réutilisations, refontes, portages refusés) ;
2. L'ordre des couches et le plan de lots (Batch Plan) ;
3. Les **points de review de direction** prévus — au minimum un point après
   le lot socle (API + services + store reviewés avant d'écrire les pages) :
   un retour early sur le socle corrige la direction de tous les lots
   suivants AVANT qu'ils soient écrits ;
4. Les **chantiers à venir** connus de l'équipe — une structure se choisit
   en fonction de ce qui viendra après (évolutions attendues du socle,
   migrations suivantes) ; ce que l'IA ignore, l'équipe le fournit ici.

GO explicite requis. Périmètre ou ordre modifiés en cours de route → re-passe
la gate (jamais de dérive silencieuse — contrat Batch Plan de `mr-split`).

## Étape 6 — Matérialisation

Le **Batch Plan vit dans l'issue de tracking** (contrat `mr-split` : une
seule issue par feature, Batch Plan + checklist des lots, chaque MR de lot
référence l'issue avec un mot-clé **non-closant**, clôture au merge du lot
final). GO humain requis pour toute écriture du tracker. Pas d'état JSON
propre à ce skill — l'issue est la source de vérité du plan, `task-workflow`
porte l'état d'exécution de chaque lot.

## Étape 7 — Handoff au lot 1

Lancer `task-workflow` sur le **lot 1** (souvent le socle API + modèles +
services) : 1 lot = 1 cycle complet = 1 branche = 1 MR. Les lots suivants
démarrent au fil de l'eau (branches parallèles depuis la base, ou lot
séquentiel si dépendance forte — règle R6 de `mr-split`), chacun dans son
propre cycle. La review de direction prévue à l'étape 5 s'exécute au moment
prévu — un retour structurant ne se noie pas dans une MR monolithique.

## Anti-patterns

- **Tout développer d'un coup** — modèles + services + store + routing +
  toutes les sections d'une page dans une seule MR : l'anti-pattern central
  que ce skill existe pour éviter ; variante fréquente : livrer le socle
  (store, modèles) avec TOUTE l'UI dans la même MR — chaque évolution du
  socle entraîne alors l'UI entière (inertie) ;
- **Générer la structure seul** — l'IA prépare les options, l'équipe guide ;
  elle seule connaît les chantiers à venir qui pèsent sur la structure ;
- **Porter 1:1 les pages existantes** sans questionner leur structure ;
- **Écrire les pages avant que le socle soit reviewé** — les retours
  structurels arrivent alors trop tard ;
- Découper par dossiers/fichiers au lieu de couches/unités fonctionnelles ;
- Réécrire les règles de découpage au lieu d'invoquer `mr-split` ;
- Ouvrir toutes les MRs en fin de course (voir rythme `mr-split`) ;
- Imposer l'ordre des couches canonique sans l'ajuster aux conventions du
  projet ;
- Utiliser feature-plan pour une petite tâche (mono-MR par défaut).

## Compatibilité avec les autres skills

| Skill | Relation |
|---|---|
| `task-workflow` | Aval : exécution d'UN lot (1 lot = 1 cycle = 1 MR) ; sa Phase 3 se contextualise depuis l'issue de tracking — pas de nouvelle évaluation multi-lots |
| `mr-split` | Moteur de découpage invoqué à l'étape 4 (R1-R8, Batch Plan, issue de tracking, rythme au fil de l'eau) |
| `meeting` | Complémentaires : meeting sécurise une tâche avant de commencer (verdict READY), feature-plan structure une feature en lots — meeting peut être invoqué sur les arbitrages multi-métiers |
| `gitlab-feature-planner` | Amont produit (tableau → issues) ; feature-plan est l'amont technique d'une feature |
| `design-qa` | Design Contract produit dès l'étape 2 si référence UI, consommé par la QA de chaque lot |
| `new-worktree` / `commit` / `pre-mr-review` / `create-mr` | Invariants inchangés, appliqués par lot (via `task-workflow`) |

## Le projet reste la source de vérité

`AGENTS.md` du projet cible et ses conventions priment : si le projet impose
son ordre de construction, sa structure de stores/pages ou son flux de
features, le skill suit la convention locale — l'ordre en couches ci-dessus
est un défaut, pas une doctrine.
