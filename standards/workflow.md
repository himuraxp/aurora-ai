# Standard — Workflow

## Cycle universel de travail

Toute tâche suit impérativement ce cycle :

```txt
Explorer → Planifier → Implémenter → [PARALLEL GATE] → Committer
                                      ├── Review (adversarial)
                                      └── Vérifier (build + lint + test)
```

### 0. Visibilité de l'avancement

Toute tâche à étapes multiples (3+ actions distinctes) DOIT utiliser `todowrite` pour rendre l'avancement visible en temps réel :

- Créer la liste des todos dès la phase d'exploration ou de planification.
- Marquer un todo `in_progress` au moment de le commencer (un seul à la fois).
- Marquer `completed` dès que le travail est fait — pas en batch à la fin.
- Pour les délégations à un sous-agent : un todo par sous-agent, marqué `in_progress` pendant l'attente, `completed` ou `cancelled` au retour.
- L'utilisateur ne doit jamais avoir à deviner où en est l'agent.

### 1. Explorer

- Toujours lire le code existant avant toute modification.
- Identifier les fichiers concernés, les conventions en vigueur, les patterns existants.
- Ne jamais implémenter directement sans comprendre le contexte.
- Si `docs/ai/` existe dans le projet courant, charger automatiquement la mémoire projet **en parallèle** (4 Read dans un seul message) :
  1. `STATUS.md` — état, bloqueurs, prochaine étape
  2. `PLAN.md` — plan en cours
  3. `WARNINGS.md` — alertes actives et zones à risque
  4. `INDEX.md` — cartographie du projet
  5. `BUFFER.md` — uniquement si reprise interrompue ou blocage signalé (5e Read séparé)
- **Si l'exploration touche > 15 fichiers potentiels** : utiliser un subagent `explore` pour l'investigation (voir `exploration-limits.md`).

### 2. Planifier

- Pour toute modification touchant plus de 2 fichiers : plan obligatoire.
- Le plan doit contenir : objectif, fichiers concernés, étapes, risques, tests.
- Le plan doit suivre un statut explicite : `pending`, `in-progress`, `implemented`, `reviewed` ou `blocked`.
- `implemented` ne signifie pas terminé : seul le passage review + vérification permet de passer à `reviewed`.
- Stocker le plan dans `docs/ai/PLAN.md`.
- Si la tâche comporte 3+ actions distinctes, créer également un `todowrite` pour la visibilité temps réel (voir étape 0).

### 3. Implémenter

- Travailler de manière incrémentale.
- Un changement logique à la fois.
- Ne jamais casser le build volontairement.
- Préserver les comportements existants.

### 4. Parallel Gate (Review + Vérifier)

Le Review (examen contradictoire) et la Vérification (build + lint + test) sont **indépendants** et DOIVENT être lancés en parallèle dans un seul message de tool calls.

- Lancer le subagent `reviewer` (ou skill `code-review`) ET la commande de build/lint/test dans le même tool call message.
- Si les deux réussissent → passer à Committer.
- Si l'un échoue → corriger en 1 seule itération, puis relancer uniquement celui qui a échoué.
- Si les deux échouent → corriger les deux en 1 seule itération, puis relancer les deux en parallèle.
- **Max 1 itération de correction** après le Parallel Gate. Cette règle est **plus stricte** que `error-correction.md` (2-strikes) : après échec de l'unique itération, reset direct.

Voir `review-before-done.md` et `verification.md` pour les procédures détaillées de chaque branche.

### Audit read-only

Si l'utilisateur demande un audit, un health-check ou une analyse de dette technique, appliquer `audit.md` au lieu du cycle d'implémentation. L'audit est diagnostique : il ne modifie pas le code et produit un rapport priorisé.

### 5. Committer

- Un changement logique par commit.
- Jamais de commit avec build cassé.
- Jamais de commit avec tests cassés.
- Format : `type(scope): résumé`
- Persister la mémoire projet selon `memory-auto-update.md` et vérifier via `memory-checklist.md`.

## Règles absolues

- Ne jamais implémenter sans exploration préalable.
- Ne jamais merger sans vérification NI sans review adversarial.
- Ne jamais masquer une erreur.
- Après 2 corrections échouées sur le même problème : reset obligatoire (voir `error-correction.md`).
- Jamais de correction en boucle sans comprendre la cause profonde (voir `error-correction.md`).
