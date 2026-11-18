# AGENTS.md — Projet

Ce fichier est la source de vérité pour les agents travaillant sur ce projet.

## Rôle de ce fichier

Aurora charge automatiquement les standards globaux et découvre `docs/ai/` sans configuration supplémentaire.
Ce fichier n'a **pas** besoin de dupliquer la logique mémoire (ordre de lecture, rôles des documents...).

Concentrez-vous ici sur :

- **Contexte métier** : produit, utilisateurs, contraintes.
- **Règles spécifiques** : conventions non couvertes par les standards globaux.
- **Conventions locales** : architecture, nommage, patterns préférés.
- **Exceptions projet** : dérogations temporaires ou zones à risque propres à ce projet.

## Objectif du projet

Décrire ici le produit, le contexte métier et les contraintes principales.

## Règles générales

- Respecter le style existant.
- Garder les changements ciblés.
- Ne pas faire de refactoring massif non demandé.
- Ne pas ajouter de dépendance sans justification claire.
- Préserver les comportements existants.
- Ajouter ou adapter les tests quand la logique change.
- Toujours privilégier une solution simple, maintenable et lisible.
- Ne jamais lire globalement des fichiers énormes si une recherche ciblée suffit.
- Utiliser `INDEX.md` pour comprendre où chercher avant de scanner le projet.
- Ne pas polluer `DECISIONS.md` avec des micro-décisions temporaires.
- **Exécuter un examen contradictoire (review adversarial) avant de déclarer une tâche terminée**.
- **Stopper et reset après 2 corrections échouées** sur le même problème.
- **Reconnaître les anti-patterns** (session fourre-tout, over-specified config, exploration infinie, etc.) et appliquer la correction immédiatement.

## Standards globaux

Les standards suivants sont chargés automatiquement par l'agent principal (Aurora) :

- **workflow** : cycle Explorer → Planifier → Implémenter → [PARALLEL GATE] → Committer (Review + Vérifier en parallèle)
- **verification** : vérifications build/lint/test obligatoires avant de considérer une tâche terminée
- **communication** : directivité, ownership, pushback constructif
- **escalation** : gestion des blocages et arrêt propre
- **commits** : format et règles de commit
- **review-before-done** : examen contradictoire obligatoire avant déclaration de fin
- **audit** : audit read-only multi-axes pour health-checks et dette technique
- **exploration-limits** : délimiter les investigations, utiliser subagents pour exploration lourde
- **error-correction** : reset après 2 corrections échouées, ne jamais corriger sans cause profonde
- **anti-patterns** : reconnaitre et stopper les 5 patterns d'échec courants
- **artifact-authoring** : création homogène de standards, agents, frameworks et templates
- **delegation-failure** : procédure obligatoire après échec de sous-agent
- **agent-output** : format de retour JSON structuré pour les sous-agents

Ces standards sont stockés dans `~/.config/opencode/standards/` par l'installation globale.

## Modes de travail

### Mode EXECUTION (par défaut)

Objectif : appliquer le plan existant.

Règles :
- Modifier uniquement les fichiers dans le scope.
- Vérifier build/lint/test après chaque changement logique.
- Documenter les écarts dans `BUFFER.md`.
- Stopper immédiatement si contradiction avec `DECISIONS.md` ou `WARNINGS.md`.
- Consulter `INDEX.md` avant de toucher un fichier inconnu du projet.
- **Exécuter un examen contradictoire (review adversarial) avant de considérer terminé** via subagent ou skill `code-review`.
- **Stopper et reset après 2 corrections échouées** sur le même problème (voir standards globaux `error-correction.md`).

### Mode BRAINSTORM

Objectif : concevoir, planifier, architecturer.

Règles :
- Aucune modification de code source.
- Documentation, architecture et planification uniquement.
- Autorisé à modifier : `PLAN.md`, `DECISIONS.md`, `INDEX.md`.
- Sortie du mode quand le plan est validé et clair.

### Mode AUDIT

Objectif : diagnostiquer sans modifier.

Règles :
- Lire `INDEX.md` et `WARNINGS.md` avant d'explorer.
- Choisir les axes pertinents : qualité, architecture, sécurité, dépendances, performance, tests, UI/accessibilité.
- Produire un rapport priorisé avec preuves.
- Ne pas corriger pendant l'audit ; proposer un plan d'action séparé.
- **Exception** : les audits SEO/AIO/Growth sont délégués aux agents spécialistes (Atlas, Crawler, Sage, Pulse, Beacon) — voir `AGENTS.md` global section "Search & Growth Agents".

## Documentation IA

Aurora détecte `docs/ai/` au démarrage et applique l'ordre de lecture défini dans les standards globaux (`~/.config/opencode/standards/memory-session-flow.md`). L'ordre de mise à jour (persistance) est défini dans `memory-auto-update.md` et la vérification dans `memory-checklist.md`.
L'AGENTS.md local n'a **pas** besoin de répéter ces règles.

## Angular 20 — Conventions

### Templates HTML

- Utiliser `@if` / `@else`.
- Utiliser `@for (...; track ...)`.
- Ne pas utiliser `*ngIf`, `*ngFor`, `ngSwitch`.
- Ne pas utiliser `let` dans `@for`.
- Les blocs `@if` et `@for` doivent entourer des balises HTML complètes.
- Ne jamais utiliser `@if` ou `@for` comme attribut.
- Éviter les expressions complexes dans le HTML.

### TypeScript

- Composants standalone uniquement.
- Pas de NgModule manuel.
- Injection via `inject()` uniquement.
- Variables privées avec `#variable`.
- Éviter `private`.
- Inputs avec `input()` / `input.required()`.
- Outputs avec `output()`.
- Ne pas utiliser `@Input()` / `@Output()`.
- Utiliser `signal()`, `computed()`, `effect()`.
- RxJS uniquement dans les services métier, sauf contrainte existante.
- Éviter `null`, préférer `undefined`.
- Ne pas utiliser `any`.

### Tests

- Utiliser Jest.
- Pour les inputs standalone, utiliser `fixture.componentRef.setInput()`.
- Tester les comportements visibles.
- Ajouter les tests nécessaires pour toute logique modifiée.

### SCSS

- Éviter la duplication.
- Ne pas ajouter de style global sans nécessité.
- Respecter la structure SCSS existante.
- Préserver le responsive.

### Accessibilité

- Libellé ou `aria-label` sur tous les boutons.
- Actions critiques explicites.
- Préserver les états loading, empty, error.

## Workflow attendu

Pour une tâche complexe :

1. Lire le contexte existant (docs/ai/ puis INDEX.md).
2. Identifier les fichiers concernés.
3. Proposer un plan court (pour >2 fichiers).
4. Implémenter par petits changements.
5. Exécuter un review contradictoire si du code ou des règles changent.
6. Lancer ou indiquer les tests pertinents.
7. Résumer clairement les modifications.
