# Standard — Audit Read-Only

## Principe

Un audit est une analyse diagnostique. Il ne modifie aucun fichier source et ne corrige rien directement.

Utiliser ce standard quand l'utilisateur demande :

- un audit du projet ;
- un health-check ;
- une analyse de dette technique ;
- une priorisation de risques ;
- une revue large hors diff.

Pour une modification prête à livrer, utiliser `review-before-done.md`.

## Exception — audits SEO / AIO / Growth

Les audits SEO, AIO/GEO et Growth **ne relèvent pas** de ce standard. Ils sont délégués aux agents spécialistes de l'équipe Search & Growth :

- **Audit SEO** → Atlas (stratégie) + Crawler (technique)
- **Audit AIO** → Sage + Crawler
- **Audit SEO & AIO** → Atlas + Crawler + Sage
- **Audit Growth** → Pulse + Beacon

Aurora ne réalise **jamais** lui-même un audit SEO/AIO/Growth. Voir la section "Search & Growth Agents" du `AGENTS.md` et de `agents/aurora.md`.

## Axes d'audit

Choisir uniquement les axes pertinents au contexte :

| Axe | Questions à traiter |
|-----|---------------------|
| Qualité code | Lisibilité, duplication, complexité, conventions |
| Architecture | Couplage, frontières de modules, responsabilités |
| Sécurité | Secrets, validation d'entrée, auth, permissions, dépendances risquées |
| Dépendances | Paquets inutiles, obsolètes, incohérents, ajoutés sans justification |
| Performance | Requêtes coûteuses, rendu UI, boucles, I/O, bundle |
| Tests | Couverture des chemins critiques, assertions utiles, fragilité |
| UI / Accessibilité | États visibles, responsive, clavier, contrastes, textes |

## Procédure

1. Définir le périmètre : repo complet, dossier, feature, ou axe unique.
2. Lire d'abord `docs/ai/INDEX.md`, `WARNINGS.md`, puis les fichiers ciblés.
3. Limiter l'exploration selon `exploration-limits.md`.
4. Produire un rapport trié par sévérité.
5. Ne proposer des corrections que comme plan d'action séparé.

## Format de sortie

```md
## Verdict

Sain / À surveiller / À corriger / Bloquant

## Findings

| Sévérité | Axe | Fichier | Problème | Impact | Action recommandée |
|----------|-----|---------|----------|--------|--------------------|
| critique | sécurité | `path` | ... | ... | ... |

## Hors scope

- ...

## Vérifications recommandées

- ...
```

## Règles

- Ne pas transformer un audit en refactor.
- Ne pas signaler des préférences stylistiques comme risques.
- Chaque finding doit citer un fichier ou une preuve concrète.
- Si un risque est incertain, le marquer comme hypothèse et indiquer comment le confirmer.
