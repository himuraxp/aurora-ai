# Exemple Monorepo

Exemple de monorepo montrant la structure cible avec `AGENTS.md` et documentation IA.

Initialisé via :

```bash
npm run init-project --prefix ~/.config/opencode-config
# ou: ~/.config/opencode-config/scripts/init-project.sh
```

## Structure cible après initialisation

```txt
monorepo/
  AGENTS.md          → conventions du projet
  docs/
    ai/
      PLAN.md        → plan technique courant
      STATUS.md      → état d'avancement
      DECISIONS.md   → décisions structurantes
      CHANGELOG.md   → historique des agents
      BUFFER.md      → mémoire tampon de session
      INDEX.md       → cartographie du projet
      WARNINGS.md    → alertes et dettes techniques
  packages/          → packages du monorepo
```

Ce dossier ne contient volontairement que le README d'exemple. Pour créer la structure complète dans un vrai monorepo, lancer `init-project.sh`, puis documenter les packages dans `docs/ai/INDEX.md`.

## Standards appliqués

Ce monorepo peut suivre plusieurs frameworks selon ses packages. Documenter chaque package dans `docs/ai/INDEX.md`.

- Séparation des concerns
- Tests par package
- Scripts build/lint/test au niveau root
