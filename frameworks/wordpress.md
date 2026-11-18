---
description: Standard WordPress — thèmes custom et plugins, sécurisation, hooks, performances.
mode: subagent
---

# WordPress

## Objectif

Règles de développement pour les projets WordPress : **thèmes custom** et
**plugins**. Périmètre : PHP (thèmes/plugins), JavaScript et CSS de front.
Hors périmètre : WordPress headless, page builders et générateurs de code.

Ces règles s'ajoutent aux standards globaux (sécurité, accessibilité, qualité) ;
elles ne les remplacent pas. En cas de conflit, le plus spécifique l'emporte.

## Sécurité (bloquant)

- Échapper **toute** sortie : `esc_html()`, `esc_attr()`, `esc_url()`,
  `esc_textarea()`, `wp_kses_post()` pour le HTML riche. Une interpolation
  non échappée est une vulnérabilité XSS.
- Valider/sanitiser **toute** entrée : `sanitize_text_field()`, `sanitize_key()`,
  `absint()`, `wp_unslash()` sur `$_GET`/`$_POST`/`$_REQUEST`/`$_COOKIE`.
- Nonce sur toute action non idempotente : `wp_nonce_field()` +
  `wp_verify_nonce()` (front) ou `check_admin_referer()` (admin).
- Vérifier les capacités avant toute action sensible :
  `current_user_can('manage_options')`.
- Chaque fichier PHP exécutable commence par `defined('ABSPATH') || exit;` —
  aucun accès direct possible.
- Requêtes SQL : `$wpdb->prepare()` obligatoire dès qu'une variable intervient.
  Privilégier l'API (`WP_Query`, `get_posts()`, `get_option()`) au SQL brut.

## Hooks & architecture

- Étendre par **hooks** (actions/filtres) — ne jamais modifier le core ou un
  plugin tiers. Priorités et nombre d'arguments explicites sur les
  `add_action`/`add_filter` non standard.
- Préfixe unique pour tout élément global : fonctions, hooks, options,
  transients, shortcodes (`monplugin_`, `montheme_`). Une collision avec le
  core ou un plugin tiers = bug silencieux.
- Thème : `functions.php` = setup (`after_setup_theme`, `add_theme_support`,
  `register_nav_menus`) — pas de logique métier ; modules dans `inc/`.
- Plugin : bootstrap sur `plugins_loaded`, modules par responsabilité dans
  `inc/`, activation/désactivation séparées (`register_activation_hook`,
  `register_deactivation_hook`).
- Options d'admin via la Settings API (`register_setting`,
  `add_settings_field`) — jamais de `$_POST` traité à la main.

## Assets & enqueues

- Aucun `<script>`/`<link>` en dur dans les templates :
  `wp_enqueue_script()`/`wp_enqueue_style()` via `wp_enqueue_scripts` (front),
  `admin_enqueue_scripts` (admin), `enqueue_block_editor_assets` (éditeur).
- Handles préfixés et versionnés (`montheme-main`, version = version du
  thème/plugin), dépendances déclarées.
- Données vers le JS : `wp_localize_script()` ou `wp_add_inline_script()` —
  jamais d'URL ni de clé en dur dans un fichier JS.

## Base de données & données

- `WP_Query`/`get_posts()` plutôt que SQL ; `wp_reset_postdata()` après toute
  boucle custom.
- Cache des traitements coûteux : transients (`get_transient`/`set_transient`),
  `wp_cache_*` pour les accès répétés dans une exécution.
- Pas d'appel HTTP dans le rendu de page : `wp_remote_get()` + transient avec
  TTL explicite et gestion d'erreur.
- Configuration : `get_option`/`update_option` — pas de constantes définies à
  la volée, pas d'options écrites à chaque requête front.

## Thèmes

- Hiérarchie de templates respectée (`index.php`, `single.php`,
  `archive.php`…) ; `get_header()`/`get_footer()`/`get_sidebar()` — jamais
  d'`include` manuel de template.
- `wp_head()` et `wp_footer()` présents et non conditionnés.
- `theme.json` (block themes, styles d'éditeur inclus) et `block.json`
  (blocs custom) versionnés ; `add_editor_style()` pour les thèmes classiques.
- Support child theme : `get_template_directory()` (parent) vs
  `get_stylesheet_directory()` (child) — choisir consciemment selon l'usage.

## i18n

- Toutes les chaînes traduisibles : `__()`, `_e()`, `esc_html__()`, `_x()`
  avec un text domain unique (`montheme` / `monplugin`).
- Text domain chargé dans le bootstrap, hooké sur `after_setup_theme`/`init` :
  `load_theme_textdomain()` (thème), `load_child_theme_textdomain()` (child
  theme), `load_plugin_textdomain()` (plugin).
- Pas de HTML concaténé dans les chaînes : placeholders + `sprintf()`.

## Qualité & tests

- PHP compatible avec la version minimale annoncée (header plugin/readme) —
  pas de syntaxe supérieure dans le code livré.
- PHPCS WordPress Coding Standards (`wp-coding-standards/wpcs`) : zéro erreur
  `WordPress.Security.*` — échappements et nonces sont bloquants.
- Pas de `@` ni de `error_reporting(0)` masquant les erreurs ; `WP_DEBUG`
  propre en développement.
- Tests PHPUnit (PHP + mock WP ou installation de test) pour la logique
  métier ; hooks critiques (activation, migration d'options) testés en
  priorité.

## Performance

- Pas de requête dans une boucle (N+1) : préchargement des méta/terms via les
  flags `update_post_meta_cache`/`update_post_term_cache` de `WP_Query`.
- Déqueue des assets inutiles (`wp_dequeue_script()`/`wp_dequeue_style()`)
  plutôt que leur masquage en CSS.
- Images : tailles déclarées (`add_image_size`), `srcset` natif, lazy
  loading natif.

## Accessibilité

- Navigation au clavier et focus visible sur menus et blocs interactifs.
- Formulaires : `<label>` explicites, erreurs associées via
  `aria-describedby`.
- `wp_nav_menu()` : conteneur sémantique, `aria-current` sur la page active.
