# AGENTS.md — Node.js API (exemple)

Ce fichier est la source de vérité pour les agents travaillant sur ce projet.

## Objectif du projet

API Node.js / Express exemple démontrant les conventions attendues.

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

Appliquer `frameworks/nodejs.md` :

- Séparation routes / services / repositories
- Validation des entrées
- Gestion d'erreurs centralisée
- Tests Jest (unitaires + intégration)
- Logs structurés
- Pas de `any`

## Workflow attendu

1. Lire le contexte existant (docs/ai/ puis INDEX.md).
2. Identifier les fichiers concernés.
3. Proposer un plan court (pour >2 fichiers).
4. Implémenter par petits changements.
5. Exécuter un review contradictoire si du code change.
6. Lancer ou indiquer les tests pertinents.
7. Résumer clairement les modifications.
