# Standard — Verification

## Parallel Gate

La Vérification s'exécute **en parallèle** du Review (examen contradictoire) dans le cadre du Parallel Gate du workflow (voir `workflow.md` étape 4). Les deux branches sont lancées dans un seul message de tool calls :

```
Implémenter terminé
    ├── Review (review-before-done.md)   ─┐
    └── Vérifier (ce standard)            ─┤── Aurora consolide
                                           └── Corriger si nécessaire → Committer
```

## Qualité avant déclaration de fin

Une tâche n'est **jamais** considérée comme terminée tant que les vérifications suivantes ne passent pas :

```bash
build
lint
test
```

## Obligations de l'agent

- Lancer les vérifications adaptées au projet (npm run build, npm run lint, npm test, etc.).
- Montrer les résultats réels dans la session.
- Ne jamais affirmer qu'un changement fonctionne sans preuve exécutable.

## En cas d'échec

- Corriger la cause racine.
- Ne jamais masquer une erreur avec un ignore, un skip, ou une suppression de test.
- Documenter dans `docs/ai/STATUS.md` si un blocage nécessite une décision humaine.

## Anti-patterns

- ❌ "Cela devrait fonctionner" sans preuve.
- ❌ Supprimer un test pour faire passer le build.
- ❌ Ignorer un lint sans justification explicite et temporaire.
- ❌ Déclarer une tâche terminée sans exécuter les vérifications.
