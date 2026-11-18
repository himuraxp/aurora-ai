# Exemple WordPress

Exemple de projet WordPress (thème custom + plugins maison) montrant les
conventions attendues : sécurisation, hooks, i18n, performances.

Initialisé via :

```bash
npm run init-project --prefix ~/.config/opencode-config
# ou: ~/.config/opencode-config/scripts/init-project.sh
```

## Structure cible après initialisation

```txt
wordpress-app/
  AGENTS.md                    → conventions du projet
  docs/
    ai/
      PLAN.md                  → plan technique courant
      STATUS.md                → état d'avancement
      DECISIONS.md             → décisions structurantes
      CHANGELOG.md             → historique des agents
      BUFFER.md                → mémoire tampon de session
      INDEX.md                 → cartographie du projet
      WARNINGS.md              → alertes et dettes techniques
  wp-content/
    themes/montheme/           → thème custom (functions.php = setup, inc/ = modules)
    plugins/monplugin/         → plugin maison (bootstrap plugins_loaded, inc/)
```

Ce dossier contient volontairement le minimum (README + AGENTS.md). Pour créer
la structure complète dans un vrai projet, lancer `init-project.sh`, puis
référencer `frameworks/wordpress.md` dans le `AGENTS.md` local.

## Standards appliqués

Ce projet suit les conventions du framework `wordpress.md` :

- Sécurité bloquante : échappement systématique en sortie, sanitisation en
  entrée, nonces sur les actions non idempotentes, `ABSPATH` en tête de
  chaque fichier PHP, `$wpdb->prepare()` pour tout SQL paramétré
- Extension par hooks (jamais de modification du core ou d'un plugin tiers),
  préfixe unique pour tout élément global
- Assets via `wp_enqueue_*` uniquement, i18n avec text domain unique
- `WP_Query` plutôt que SQL brut, transients pour les traitements coûteux
- PHPCS WordPress Coding Standards (`wp-coding-standards/wpcs`) — zéro
  erreur `WordPress.Security.*` ; PHPUnit sur la logique métier
