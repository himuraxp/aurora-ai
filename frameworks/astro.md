---
description: Standard Astro — architecture de site statique moderne, SEO, performances, i18n.
mode: subagent
---

# Astro

## Objectif

Produire des sites Astro performants, accessibles, SEO-ready et maintenables avec gestion multilingue.

## Architecture de projet

```txt
src/
├── content/            # Collections de contenu (blog, docs, pages)
├── components/         # Composants Astro (.astro), React (.jsx/.tsx), Vue (.vue)
├── layouts/            # Layouts partagés
├── pages/              # Routes du site
├── styles/             # SCSS/CSS globaux
├── utils/              # Fonctions réutilisables
├── i18n/               # Fichiers de traduction et logique de routing i18n
├── config/             # Astro.config.mjs, tailwind, intégrations
└── plugins/            # Intégrations custom si nécessaire
```

### Séparation des responsabilités

- `pages/` : uniquement routing, chargement des données, layout.
- `components/` : logique UI, props, slots.
- `content/` : Markdown/MDX processing, collections typées via `contentLayer`.
- `utils/` : fonctions pures, helpers, formatage.

## Collections de contenu

- Toujours typer via `contentLayer` :

```ts
import { defineCollection } from 'astrojs';

const blog = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    published: z.date(),
    tags: z.array(z.string()),
  }),
});
```

- Valider au build. Ne pas laisser de contenu non validé.
- Utiliser les métadonnées pour le SEO (title, description, date, permalink).

## Internationalisation (i18n)

- Configurer `i18n` avec `defaultLocale` et `locales` dans `astro.config.mjs`.
- Utiliser un helper pour générer les liens traduits (préfixe par locale).
- Ne pas dupliquer le layout par langue. Passer la locale en contexte.
- Traduire le frontmatter ou réutiliser les chaînes depuis des fichiers `.json`.
- Carousel/Gallery : gestion des alt et aria-label traduits.

## SEO

### Titre / description / og

- Titre unique par page avec suffixe de marque constante.
- Description entre 150-160 caractères.
- Open Graph : title, description, image à la une en 1200x630.

### JSON-LD

- Générer automatiquement les données structurées pour article, page, FAQ.
- Valide avec le Rich Results Test.
- Placer dans `<head>` du `head.astro` ou dans un `Seo.astro` dédié.

### Sitemap

- Vérifier que toutes les URLs publiques sont présentes.
- Exclure les URLs canoniques dynamiques redondantes.
- Prioriser les langues par nombre de requêtes dans les crawlers (hreflang alternatif).

### Robots.txt

- Bloquer les routes authentifiées, admin, staging.
- Vérifier que le fichier existe et est déployé.

## Performance

- Précharger uniquement les polices/CSS/JS nécessaires à l'interactivité.
- Assets : compresser et lazy-load les composants si possible.
- Lighthouse minimum : 95 performance, 100 accessibilité.
- Ne pas embarquer de framework lourd (React/Vue) si l'interactivité concerne 1 ou 2 composants.
- Utiliser les composants Server si possible.

## Images optimisées

- Utiliser `astro-imagetools` ou `@astrojs/image` pour compresser et générer srcsets.
- Avif par défaut, webp fallback.
- Dimensions explicites pour éviter le CLS.
- Lighthouse captera les images sans dimensions.

## Accessibilité

- Lighthouse a11y minimum 95.
- boutons : aria-label explicite si icône seule.
- Interactions via clavier possibles.
- Focus visible, skip to content.
- Formulaires : labels et aria-required.
- Couleurs : ratio minimum 4.5:1 pour le texte normal (3:1 pour grands textes).
- Pas de `aria-hidden` sur les éléments focusables.

## Composants réutilisables

- Chaque composant doit être testable en isolation (props, id, variant).
- Eviter la duplication de logique.
- Utiliser des modules de composants UI (Design System) si le projet est moyen/grand.
- Transformer les composants réutilisables en `islands` si l'interactivité côté client est nécessaire.

## Pages .astro

- Chaque page ne doit contenir que du routing, du chargement de données (content ou fetch), et du layout.
- Ne pas mettre de logique métier lourde dans un composant `.astro` : extraire en util.
- Utiliser `Astro.props` pour passer des données aux layouts.
- Construire des types d'URL correspondants strictement au routing.

## Frontmatter conventions

```md
---
title: string
slug: string  // correspond au chemin pour i18n
published: date
description: string
tags: string[]
image: string  // OG image
---
```

- Utiliser un Zod schema pour toutes les collections.
- Pas de champ optionnel non justifié.
- Dashboard d'édition : Pas de frontmatter libre. Utiliser des types.

## Markdown / MDX

- Markdown pur dans la collection. Composants de présentation MDX propres.
- Utiliser les rehype/remark pour échapper automatiquement.
- Ne pas autoriser d'HTML brut dans `content/`.

## Tracking analytics

- Ne pas bloquer le blocking de script via async/defer.
- Respecter le GDPR (bannière de consentement et contrôle).
- Utiliser les routes côté serveur par les analytics si possible.
- Charger le script uniquement après consentement explicite (sauf analytics anonymisé et local).

## Pages statiques multilingues

- Output en dossiers séparés : `/en/page`, `/fr/page`.
- Utiliser `astro-i18n-utils` ou `astrojs: i18n` pour routing.
- Générer automatiquement les `hreflang` pour les pages traduites en `head`.
- Lors du préchargement des liens, prévoir le préchargement des traductions pour améliorer la navigation.

## Anti-patterns Astro

- ❌ Logique métier lourde dans les composants `.astro`.
- ❌ Duplication de code par locale au lieu d'abstraction.
- ❌ Ignorer les dimensions d'images ( CLS élevé ).
- ❌ Mettre `async` sur les scripts analytics avant le body.
- ❌ Embarquer des composants React/Vue inutilement.
- ❌ Frontmatter non validé.
- ❌ Contenu non sécurisé (HTML brut).

## Checklist publication

En plus des vérifications obligatoires de `verification.md`, vérifier :

- [ ] Pour chaque page : title, description unique, Open Graph approprié
- [ ] JSON-LD valide pour les types de contenus (Article, Product, FAQ, HowTo)
- [ ] Sitemap et robots.txt distinct (pas de route Spam potential ou admin exposure)
- [ ] Icones et images : pas d'erreur CLS, dimensions avif/webp
- [ ] Accessibilité : lighthouse >=95 a11y
- [ ] Internationalisation : routing par locale, hreflang
- [ ] Analytics chargé en mode consent / non-blocking
- [ ] RSS / Atom feed configuré si nécessaire
- [ ] Contenu des collections validé au build
- [ ] Aucune route en staging ou environnement non prod n'est accessible au public
