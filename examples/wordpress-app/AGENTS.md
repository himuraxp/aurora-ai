# AGENTS.md — WordPress (exemple)

Ce fichier est la source de vérité pour les agents travaillant sur ce projet.

## Objectif du projet

Site WordPress avec **thème custom** et **plugins maison** — démonstration des
conventions attendues (sécurité, hooks, i18n, performances).

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

Appliquer `frameworks/wordpress.md` :

- **Sécurité (bloquant)** : toute sortie échappée (`esc_html`, `esc_attr`, `wp_kses_post`), toute entrée sanitizée, nonce sur toute action non idempotente, `current_user_can()` avant action sensible, `defined('ABSPATH') || exit;` en tête de chaque fichier PHP, `$wpdb->prepare()` dès qu'une variable entre dans du SQL.
- **Hooks & architecture** : extension par hooks uniquement (jamais le core ni un plugin tiers), préfixe unique global (`monplugin_`, `montheme_`), bootstrap plugin sur `plugins_loaded`, modules par responsabilité dans `inc/`.
- **Assets** : tout via `wp_enqueue_*` (rien en dur dans les templates), handles préfixés et versionnés, données JS via `wp_localize_script()`.
- **Données** : `WP_Query`/`get_posts()` plutôt que SQL brut, transients pour les traitements coûteux, options via la Settings API.
- **i18n** : toutes les chaînes via `__()`/`_e()` avec un text domain unique.
- **Qualité** : PHPCS WordPress Coding Standards (`wp-coding-standards/wpcs`) — zéro erreur `WordPress.Security.*` ; PHPUnit sur la logique métier.

## Workflow attendu

1. Lire le contexte existant (docs/ai/ puis INDEX.md).
2. Identifier les fichiers concernés.
3. Proposer un plan court (pour >2 fichiers).
4. Implémenter par petits changements.
5. Exécuter un review contradictoire si du code change.
6. Lancer ou indiquer les tests pertinents.
7. Résumer clairement les modifications.

## Zones sensibles

- `functions.php` du thème : setup uniquement, pas de logique métier.
- Hooks d'activation/désactivation des plugins : migrations d'options
  testées en priorité (données de production en jeu).
- Toute modification de requête SQL ou de traitement de `$_POST` :
  relecture sécurité obligatoire.
