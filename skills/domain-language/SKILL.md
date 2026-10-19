---
name: domain-language
description: "Génère et maintient le référentiel du langage métier partagé d'un projet (Ubiquitous Language, DDD) — scanne le dépôt, propose un glossaire docs/ai/domain-language.md avec statuts VALIDATED/CANDIDATE/AMBIGUOUS. L'extraction du code est une PROPOSITION, jamais la vérité métier ; la validation des définitions est humaine. Utiliser quand l'utilisateur dit 'domain-language', 'langage métier', 'glossaire métier', 'ubiquitous language', 'vocabulaire du projet', 'harmoniser la terminologie', ou avant la clarification d'un besoin complexe (meeting / task-workflow)."
---

# Domain Language — référentiel du langage métier partagé

Les agents doivent parler **le langage du projet**, jamais inventer leurs
propres concepts. Ce skill construit et maintient un glossaire métier partagé
(Ubiquitous Language, DDD) qui sert à la clarification des besoins
(`meeting`), à la planification (`task-workflow` Phase 3) et aux briefs de
délégation — **par sélection ciblée, jamais par injection systématique**.

## Règle dure — l'extraction est une PROPOSITION

Un terme extrait du code décrit **ce que le code fait aujourd'hui**, pas ce
qu'il doit faire. L'extraction est une **proposition** ; seule la
**confirmation humaine** crée une définition validée. Un agent ne fait JAMAIS
passer une définition en `VALIDATED` de sa propre autorité.

## Statuts des définitions

| Statut | Signification | Qui peut le poser |
|---|---|---|
| `VALIDATED` | Définition confirmée par un humain | **Jamais un agent** — confirmation explicite de l'utilisateur (message direct), tracée |
| `CANDIDATE` | Terme extrait du code, définition proposée, à confirmer | Agent (extraction) |
| `AMBIGUOUS` | Usages contradictoires détectés (même terme, sens différents) — conflit à arbitrer | Agent (détection) |

Rétrogradation d'un `VALIDATED` : uniquement sur **trace humaine**
(`invalidatedBy: HUMAN` + raison — pattern `design-qa`), jamais silencieusement
par une nouvelle extraction. Une extraction qui contredit un `VALIDATED`
signale le conflit dans le rapport et passe le terme en `AMBIGUOUS`.

## Fichier de sortie

`docs/ai/domain-language.md` dans le dépôt cible (mémoire projet, git-ignorée
comme les autres fichiers `docs/ai/`) — un référentiel par projet, jamais
global :

```markdown
# Domain Language — <projet>

<!-- génération : skill domain-language, <date> — extraction = proposition -->

## VALIDATED
### <Terme>
- Définition : <définition confirmée humain>
- Source : <file:line de l'usage de référence>
- Validé le : <date — par qui>

## CANDIDATE
### <Terme>
- Définition proposée : <extraction>
- Sources : <file:line> (<n> usages)
- À confirmer : oui

## AMBIGUOUS
### <Terme>
- Sens A : <usage + file:line>
- Sens B : <usage + file:line>
- Conflit : <ce qui diverge> → arbitrage humain requis
```

## Procédure

1. **Scan du dépôt** (délégation **Explorer**, périmètre ciblé) : termes du
   domaine — noms de modèles/entités/services/types/tables, vocabulaire des
   tests et des critères d'acceptation, `AGENTS.md`, README, discussions de
   tickets. Le scan lit ; il ne modifie rien.
2. **Rapprochement** : regrouper synonymes et variantes (ex. `Workflow` vs
   `Pipeline`), compter les usages, détecter les conflits de sens (même terme,
   2 définitions incompatibles → `AMBIGUOUS`).
3. **Proposition** : générer/mettre à jour `docs/ai/domain-language.md`
   (statuts `CANDIDATE`/`AMBIGUOUS` uniquement — un agent ne pose jamais
   `VALIDATED`) ; mise à jour **idempotente** (re-scan = mêmes entrées,
   nouvelles découvertes ajoutées, rien d'écrasé sans trace).
4. **Validation humaine** : présenter les `CANDIDATE` prioritaires (usages
   fréquents, termes des critères d'acceptation) ; l'utilisateur confirme →
   `VALIDATED` (date + par qui). L'utilisateur peut corriger une définition
   proposée — la correction l'emporte sur l'extraction.
5. **Arbitrage des `AMBIGUOUS`** : présenter les conflits détectés avec leurs
   deux sens sourcés ; l'arbitrage est humain (ou PO) — jamais tranché par
   l'agent.

## Consommation ciblée (jamais systématique)

Le glossaire est consulté **par sélection pertinente à la tâche**, jamais
injecté en entier dans un contexte :

| Consommateur | Usage |
|---|---|
| `meeting` (mode clarification HIGH) | Un terme ambigu du besoin → question de clarification alimentée par les définitions et conflits sourcés |
| `task-workflow` Phase 3 | Le contrat d'implémentation (et ses critères d'acceptation/invariants) utilise les définitions `VALIDATED` — un terme absent du glossaire suit l'extraction standard |
| Briefs de délégation | Les définitions `VALIDATED` **pertinentes au périmètre** de la sous-tâche (2-5 termes), pas le glossaire complet |

Cohérence documentaire : si une définition contredit le `AGENTS.md` du projet,
le conflit est **signalé** (jamais résolu silencieusement) — `AGENTS.md`
prime ; la définition passe en `AMBIGUOUS` jusqu'à arbitrage humain.

## Anti-patterns

- ❌ Présenter une extraction comme la vérité métier — c'est une proposition.
- ❌ Poser un `VALIDATED` sans confirmation humaine explicite.
- ❌ Rétrograder ou réécrire un `VALIDATED` sans trace humaine (date, qui, raison).
- ❌ Injecter le glossaire entier dans chaque contexte — sélection ciblée.
- ❌ Trancher un `AMBIGUOUS` soi-même — l'arbitrage est humain.
- ❌ Résoudre silencieusement un conflit définition ↔ `AGENTS.md` — signaler.
- ❌ Créer un second référentiel terminologique ailleurs (templates, skills
  dédiés) — `docs/ai/domain-language.md` est le référentiel unique par projet.

## Tests

```bash
bash scripts/health-check.sh   # section domain-language (invariants doc)
```

Le skill est documentaire (génération + maintenance de glossaire) : pas de
suite unitaire — les invariants sont vérifiés par le health-check (règles
dures présentes) et les pilotes réels (1er scan = proposition, validation
humaine, consommation ciblée).

## Skills et outils réutilisés

| Besoin | Mécanisme réutilisé |
|---|---|
| Scan du dépôt | agent **Explorer** (lecture seule) |
| Clarification des termes ambigus | skill `meeting` (mode clarification, Question Ledger) |
| Contrat d'implémentation | skill `task-workflow` (Phase 3 — les AC/invariants utilisent les définitions `VALIDATED`) |
| Trace humaine de rétrogradation | pattern `design-qa` (`invalidatedBy: HUMAN` + raison) |
| Conflit documentaire | règle globale `AGENTS.md` prime — signalé, jamais silencieux |
