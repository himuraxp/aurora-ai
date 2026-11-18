# Standard — Commits

## Format

```txt
type(scope): résumé
```

Le résumé est impératif, en minuscules, concis (≤ 50 caractères idéalement, maximum 72).

## Types

| Type | Usage |
|------|-------|
| `feat` | Nouvelle fonctionnalité |
| `fix` | Correction de bug |
| `refactor` | Refactoring sans changement de comportement |
| `test` | Ajout ou correction de tests |
| `docs` | Documentation uniquement |
| `chore` | Maintenance, montée de version, etc. |

## Règles

- **Un changement logique par commit**.
- **Jamais de commit avec build cassé**.
- **Jamais de commit avec tests cassés**.
- La portée (scope) est optionnelle mais recommandée.
- Un corps de message peut détailler la motivation si nécessaire.

## Anti-patterns

- ❌ Commit WIP, fix, final, encore, vraiment la bonne.
- ❌ Commit mélangeant une feature et un fix dans le même changeset.
- ❌ Commit avec tests échouants masqués.
- ❌ Message trop long et pas impératif.
