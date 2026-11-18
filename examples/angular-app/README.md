# Exemple Angular 20+

Exemple de structure projet Angular 20+ avec `AGENTS.md`, modes de travail et documentation IA.

À copier dans un projet Angular ou à générer via :

```bash
npm run init-project --prefix ~/.config/opencode-config
# ou: ~/.config/opencode-config/scripts/init-project.sh
```

## Structure de la documentation IA

Ce projet inclus la documentation de session complète :

- **AGENTS.md** : source de vérité du projet
- **docs/ai/PLAN.md** : plan technique courant
- **docs/ai/STATUS.md** : état d'avancement
- **docs/ai/DECISIONS.md** : décisions structurantes
- **docs/ai/CHANGELOG.md** : historique des agents
- **docs/ai/BUFFER.md** : mémoire tampon de session
- **docs/ai/INDEX.md** : cartographie du projet
- **docs/ai/WARNINGS.md** : alertes et dettes techniques

## Modes de travail

- **Mode EXECUTION** (par défaut) : modifier uniquement les fichiers dans le scope
- **Mode BRAINSTORM** : conception et planning uniquement, aucun code modifié
- **Mode AUDIT** : diagnostic read-only multi-axes, aucun code modifié

## Conventions

Standards Angular 20+ appliqués : standalone components, signals (`signal()`, `computed()`, `effect()`), `inject()`, `input()`/`output()`, blocs `@if`/`@for`, tests Jest.
