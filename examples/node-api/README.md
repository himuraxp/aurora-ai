# Exemple Node.js API

Exemple de projet Node.js / Express montrant les conventions attendues pour un projet API.

Initialisé via :

```bash
npm run init-project --prefix ~/.config/opencode-config
# ou: ~/.config/opencode-config/scripts/init-project.sh
```

## Structure cible après initialisation

```txt
node-api/
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
  src/               → sources Node.js
```

Ce dossier ne contient volontairement que le README d'exemple. Pour créer la structure complète dans un vrai projet, lancer `init-project.sh`, puis référencer `frameworks/nodejs.md` dans le `AGENTS.md` local.

## Standards appliqués

Ce projet suit les conventions du framework `nodejs.md` :

- Séparation routes / services / repositories
- Validation des entrées
- Gestion d'erreurs centralisée
- Tests Jest (unitaires + intégration)
- Logs structurés
- Pas de `any`
