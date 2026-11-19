---
name: feature-plan
description: "Structure a LARGE feature BEFORE any development starts — page/layer structuring (never a 1:1 port of legacy pages; one business object = one model/store entry, view variations never duplicate the model), construction order by layers (API → models → services → store → routing → pages), independent-block batch decomposition delegated to mr-split (batches grouped by functional coherence, never by folder; ~1 000-line diff ceiling per MR), human direction validation (the team guides the structure — AI prepares, never decides), tracking issue materialization, then hand the first batch to task-workflow. Also re-structures an already-built oversized batch from its real diff (per-component stats, review feedback reintegrated per zone). Run before task-workflow when the scope is a complete page, several pages, a full migration, or any feature whose diff will be far above an ordinary review. Use when the user says 'feature-plan', 'planifie la feature', 'structure la feature', 'on part sur une grosse feature', 'nouvelle page complète avec socle', 'page complète', 'avant le task-workflow', 'structurer avant de dev', 'découpage feature', or when a task scope looks too large to execute in one task-workflow cycle."
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
  l'infrastructure d'accès (client HTTP, proxy, types de retour des
  services) malgré une documentation du projet à jour — la lecture passive
  des conventions ne suffit pas, le socle doit les appliquer et les
  vérifier explicitement. Ce sont des défauts systématiques que la review
  humaine attrape mais qu'une lecture automatique laisse passer — et ils
  se répètent d'une migration à l'autre tant qu'ils ne sont pas dans le
  contrat du socle ;
- **Concepts métier dupliqués pour des variations de vue** : deux vues du
  même objet métier modélisées comme deux modèles, deux ensembles d'actions
  et deux champs de store distincts — dizaines de threads pour refusionner,
  logique dupliquée partout ; les vues UI ne décident pas de la structure
  du modèle.

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
  avant de dev », « avant le task-workflow » ;
- Un **lot déjà développé** doit être re-découpé (MR ouverte, souvent déjà
  reviewée) → mode re-structuration (étape 1 : diff réel, retours de review
  réintégrés par zone).

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
Chaque retour de review récurrent sur des migrations passées devient une
**règle du contrat socle** — pas un espoir de vigilance.

**Contrat de l'API — lire avant de structurer** : ce que l'API fait déjà
(tri, valeurs par défaut, comportement sur ressource manquante) n'est ni
réimplémenté ni compensé côté front — connaître le contrat évite d'écrire
de la logique défensive redondante et des vérifications que l'API garantit
déjà.

**Mode re-structuration — le lot existe déjà** : quand la structuration
arrive APRÈS le développement (MR ouverte, souvent déjà reviewée),
acquérir le **diff réel** de la MR existante — stats par zone/composant
(tailles réelles par fichier, pas les estimations de la carte) et
découpage calibré sur ces zones. Confronter carte/issue ↔ contenu réel :
tout écart (bloc annoncé, absent du diff) est une **open question** portée
à la gate, jamais une hypothèse. Les retours de review passés se
réintègrent dans **le sous-lot de leur zone** — chaque sous-MR embarque
les correctifs de son périmètre, le reviewer ne revoit pas tout.

Sortie : le matériau de structuration — périmètre fonctionnel, zones de
page, état du socle existant, conventions critiques, contrat API, contraintes
et dépendances.

## Étape 2 — Structuration des pages (jamais un portage 1:1)

**Questionner la structure avant de coder** — c'est le point de divergence
le plus coûteux à corriger plus tard :

1. **Zones de la/des pages** : sections, états, parcours — ce qui est
   indépendant, ce qui est partagé ;
2. **Confrontation aux pages existantes** : les pages héritées portent
   souvent des décisions historiques — ne pas les porter telles quelles sans
   raison ; identifier ce qui se réutilise, ce qui se refait proprement, ce
   qui est abandonné ;
3. **Fusion des concepts métier** : plusieurs vues du même objet métier
   (formulaire, réglages, mode d'affichage…) = **un** modèle, **une**
   entrée de store, **un** ensemble d'actions — les vues se partagent
   l'objet et se différencient au rendu ; dupliquer le modèle ou le store
   par vue duplique toute la logique et coûte cher à refusionner ;
4. Délégation **Architect** si le découpage technique est complexe
   (stores, resolvers, modèles partagés entre pages) ;
5. Référence UI (Figma, capture) → produire le **Design Contract** du skill
   `design-qa` dès cette étape (la QA de chaque lot le consommera) ;
6. Questions produit (périmètre, priorités, parcours) → **gate humaine
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
- **Routing : initialisation par resolver, guards fail-closed** — le
  chargement initial des données se déclenche au **resolver**, pas dans un
  effect de composant ; les guards réutilisent les **selectors existants**
  (un id se lit d'un seul endroit dans toute l'app, même clé de param pour
  le même objet) et **refusent l'accès** quand un paramètre requis manque ;
  leur fallback de redirection n'est **jamais la page qu'ils gardent**
  (risque de boucle) ;
- **Blocs indépendants, un par lot** : la granularité se joue à l'intérieur
  des couches — socle (modèles + services + store avec ses actions de base),
  puis les blocs de la page, puis la page elle-même. Règles de granularité :
  - chaque **bloc/composant d'une page est une unité de découpage
    candidate** — il a sa valeur propre : testable isolément, réutilisable
    par une autre MR ;
  - le regroupement se fait **par cohérence fonctionnelle, jamais par
    dossier** — un lot porte un thème de valeur (le cadre de page, la
    chaîne vignette, les réglages du partage), jamais « les fichiers du
    dossier X » ; un paquet de composants dans une seule MR est la MR
    monolithique en petit ;
  - la page finale ne fait qu'**assembler** des blocs déjà reviewés — sa
    review porte sur le parcours, pas sur les composants ;
  - garde-fou anti-micro (esprit R7 — pas de découpage excessif) : pas de
    sous-lot isolé sous ~300 lignes quand il peut fusionner avec un
    sous-lot voisin de même cohérence fonctionnelle.

  Chaque bloc est livré et reviewé indépendamment : une évolution ultérieure
  du socle ne traîne jamais l'UI entière. C'est `mr-split` qui tranche le
  découpage final.

**Contrat du lot socle** — règles génériques à adapter au projet (extraites
de retours de review récurrents sur des migrations comparables) :

- *Infrastructure d'accès* : les services métier passent des **routes
  métier** au client HTTP de l'app, qui gère seul le routage/proxy —
  jamais de construction d'URL proxy dans un service ; les types de retour
  respectent les génériques du client (un désaccord de type = signal d'un
  code non vérifié contre le vrai contrat) ;
- *Actions du store* : nommage sans ambiguïté (une action d'appel API ≠ un
  patch d'état local — renommer si le nom prête à confusion) ; une action
  de mise à jour accepte un **objet partiel** (pas de mise à jour clé par
  clé) ; les notifications d'erreur/succès se gèrent **dans le store**
  (une seule fois), pas dans chaque composant appelant ; pas d'état
  redondant (une valeur déjà stockée n'est pas dupliquée dans un champ
  séparé) ; l'id d'un objet créé se propage via l'action (objet complet
  mis à jour), pas via un snapshot de store ;
- *Modèles* : un concept métier = un modèle (cf. étape 2) ; réutiliser les
  patterns utilitaires existants du repo plutôt que d'en réinventer des
  parallèles ; zéro nombre magique — constantes métier nommées, valeurs
  par défaut explicites ; vérifier l'existence d'un identifiant **avant**
  de déclencher une action (jamais de valeur par défaut silencieuse) ;
- *Fonctions* : une fonction appartient au service de son **domaine**, pas
  au service qui l'utilise en premier ; une sélection sur grande liste
  paginée est un composant autonome réutilisable, pas un chargement de
  store.

## Étape 4 — Découpage en lots (moteur : mr-split)

Invoquer le skill **`mr-split`** avec le matériau des étapes 2-3 : ordre des
couches, zones de page, dépendances inter-couches. Les règles R1-R8, le
format du Batch Plan, le rythme au fil de l'eau et le contrat d'issue de
tracking restent la responsabilité de `mr-split` — ne pas les réécrire ici.

Sortie : un **Batch Plan** (typiquement 3-6 lots au total — bornes R7 de
`mr-split` — répartis en socle, routing, pages et intégration) + les points
de review de direction.

## Étape 5 — Validation de direction (gate humaine)

**La structuration d'une feature large est un travail conjoint.** L'IA
prépare la matière (options de structure, impacts, matériau de découpage) ;
la **direction appartient à l'équipe** — elle seule connaît les chantiers à
venir et l'historique des décisions qui pèsent sur les choix structurants.
Sur ce scope, la génération de code de bout en bout est interdite même quand
le skill encadre : on structure ensemble, puis on développe lot par lot.

Présenter **avant toute écriture de code** — ou, en mode re-structuration,
avant le re-découpage en sous-MRs :

1. La structure retenue (zones, réutilisations, refontes, portages refusés) ;
2. L'ordre des couches et le plan de lots (Batch Plan) ;
3. Les **points de review de direction** prévus — au minimum un point après
   le lot socle (API + services + store reviewés avant d'écrire les pages) :
   un retour early sur le socle corrige la direction de tous les lots
   suivants AVANT qu'ils soient écrits. Cette review socle se fait
   **humainement, ligne par ligne**, ciblée sur services, modèles et store —
   le cœur de la logique métier, et le type de défaut de contrat
   (infrastructure, typage) qu'une lecture automatique laisse passer ;
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
- **Découper/empiler par dossiers** — choisir les lots par fichiers/dossiers
  (« les fichiers du dossier X ») ou empiler les blocs indépendants d'une
  page dans une seule MR parce qu'ils vivent au même endroit ; les lots se
  choisissent par **cohérence fonctionnelle** (couches et unités
  fonctionnelles, un thème de valeur par lot) et la page finale n'assemble
  que des blocs déjà reviewés ;
- **Porter 1:1 les pages existantes** sans questionner leur structure ;
- **Dupliquer modèle/store pour des variations de vue** d'un même concept
  métier — refusionner coûte ensuite des dizaines de threads ;
- **Construire une URL proxy dans un service métier** — le client HTTP de
  l'app gère le routage ; un désaccord de types de retour avec le client =
  signal d'un socle non vérifié contre le vrai contrat ;
- **Initialiser les données dans un effect de composant** — c'est le rôle
  du resolver ; et un guard qui autorise l'accès sans son paramètre requis
  ou qui redirige vers la page qu'il garde ;
- **Écrire les pages avant que le socle soit reviewé** — les retours
  structurels arrivent alors trop tard ;
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
