# Standard — Escalation

## Si l'agent est bloqué

- **Arrêter l'exécution immédiatement.**
- Documenter le blocage dans `docs/ai/STATUS.md`.
- Ne pas essayer des dizaines de solutions aléatoires.
- Proposer une solution alternative si possible, mais marquer clairement comme hypothèse.

## Template de blocage

```md
## Bloqueur — YYYY-MM-DD

Tâche : [description de l'objectif]
Problème : [description précise]
Tenté : [actions déjà essayées et résultats]
Besoin : [ce qui manque pour débloquer : info, décision, accès, etc.]
```

## Blocages liés à la mémoire projet

- Si `docs/ai/WARNINGS.md` contient un warning critique actif concernant la zone de travail : **arrêter immédiatement** et demander clarification.
- En cas de contradiction entre `AGENTS.md` local et `docs/ai/DECISIONS.md` : **arrêter immédiatement** et demander à l'utilisateur quelle source prévaut.
- Documenter l'arrêt dans `STATUS.md` avec la raison (warning bloquant ou contradiction).

## Ce que l'agent ne doit JAMAIS faire

- Ne pas boucler sur des tentatives frénétiques (: retry x10).
- Ne pas proposer de contournement sécuritaire douteux.
- Ne pas inventer des données ou des comportements sans le signaler.
- Ne pas continuer une tâche en ignorant un échec critique.

## Ce que l'agent DOIT faire

- Informer l'utilisateur clairement.
- Documenter le contexte dans STATUS.md.
- Proposer la prochaine étape possible (même si c'est "besoin d'input humain").
