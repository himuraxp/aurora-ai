# AGENTS.md — Monorepo (exemple)

Ce fichier est la source de vérité pour les agents travaillant sur ce projet.

## Objectif du projet

Monorepo exemple montrant la structure cible avec gestion multi-packages.

## Règles générales

- Respecter le style existant.
- Garder les changements ciblés.
- Ne pas faire de refactoring massif non demandé.
- Ne pas ajouter de dépendance sans justification claire.
- Préserver les comportements existants.
- Ajouter ou adapter les tests quand la logique change.
- Toujours privilégier une solution simple, maintenable et lisible.
- **Exécuter un examen contradictoire (review adversarial) avant de déclarer une tâche terminée**.
- **Stopper et reset après 2 corrections échouées** sur le même problème.

## Framework / Stack

Selon les packages, référencer le framework correspondant :

- `frameworks/nodejs.md` — packages API
- `frameworks/nestjs.md` — packages NestJS
- `frameworks/angular-20.md` — packages frontend Angular
- `frameworks/astro.md` — packages Astro

Documenter chaque package dans `docs/ai/INDEX.md`.

## Workflow attendu

1. Lire le contexte existant (docs/ai/ puis INDEX.md).
2. Identifier les fichiers concernés.
3. Proposer un plan court (pour >2 fichiers).
4. Implémenter par petits changements.
5. Exécuter un review contradictoire si du code change.
6. Lancer ou indiquer les tests pertinents.
7. Résumer clairement les modifications.
