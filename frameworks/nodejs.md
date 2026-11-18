---
description: Standard Node.js / TypeScript — API moderne, tests, sécurité.
mode: subagent
---

# Node.js

## Objectif

Produire du code Node.js TypeScript moderne, maintenable, testé et sécurisé.

## Structure de projet

```txt
src/
├── routes/         # Définition des endpoints
├── services/       # Logique métier sans state
├── repositories/   # Accès données
├── models/         # Types, interfaces, DTOs
├── middleware/     # Express/Koa/Fastify middlewares
├── utils/          # Fonctions pures réutilisables
└── config/         # Variables d'environnement centralisées
```

## Conventions TypeScript

- Ne pas utiliser `any`.
- Utiliser des interfaces explicites pour les DTOs.
- Privilégier `undefined` à `null`.
- Typer les retours de fonctions critiques.
- Éviter le typage implicite.

## Séparation des couches

### Routes / controllers

- Uniquement parsing des paramètres, appel des services, renvoi des réponses.
- Pas de logique métier.
- Valider toutes les entrées avant d'appeler les services.

### Services

- Logique métier pure, sans dépendance framework.
- Retourner `undefined` au lieu de `null`.
- Jeter des erreurs typées (BusinessError, ValidationError, etc.).

### Repositories

- Isoler tout accès à la base de données ou aux services externes.
- Mapper les résultats bruts en modèles métier.
- Ne pas exposer les raw results au controller.

## Variables d'environnement

- Centraliser dans `config/`.
- Valider au démarrage avec un schéma explicite.
- Ne jamais utiliser `process.env.*` directement hors de `config/`.
- Exécuter `dotenv` uniquement dans le script d'entrypoint.

## Validation des entrées

- Valider systématiquement les body / params / query avant toute logique.
- Utiliser un validateur typé (Zod, io-ts, ou class-validator).
- Ne jamais faire confiance aux données entrantes.

## Gestion d'erreurs

- Utiliser des classes d'erreurs typées.
- Ne pas avaler les erreurs silencieusement.
- Propager avec contexte (message, code, cause).
- Erreurs 500 : logger, pas exposer au client (sauf en dev).

```ts
class ValidationError extends Error {
  readonly code = 'VALIDATION_ERROR';
}
```

## Logs structurés

- Utiliser un logger structuré (Pino, Winston avec format JSON).
- Logger les erreurs avec stack, context, request_id.
- Ne jamais logger de donnée sensible (mot de passe, token, PII).
- Corréler les logs par request ID.

## Scripts obligatoires

```json
{
  "build": "tsc",
  "lint": "eslint src/",
  "test": "jest --coverage"
}
```

Tous doivent passer avant considérer une tâche terminée.

## Tests unitaires (Jest)

- Tester les services métier en isolation.
- Mocker les repositories, les dépendances externes.
- Nommer explicitement : `should return undefined when user not found`.
- Ne pas tester les détails d'implémentation (framework, ORM).

## Tests d'intégration API

- Tester les routes avec un serveur de test réel (supertest).
- Valider le contrat : statut, body, erreurs.
- Initialiser et nettoyer la base de données entre les suites.

## Sécurité API

- Helmet / HSTS / CORS configurés.
- Rate limiting sur les endpoints sensibles.
- Ne jamais exposer les stacks d'erreurs au client en production.
- Validation et sanitization des entrées.
- Pas de secrets dans le code source (utiliser des env vars).

## Anti-patterns

- ❌ Logique métier dans les routes/controllers.
- ❌ `process.env.VAR` éparpillé dans le code.
- ❌ `any` ou typing non strict.
- ❌ Erreurs avalées silencieusement.
- ❌ Logging de tokens ou de PII.
- ❌ Fonctions de 300 lignes.

## Checklist avant validation

En plus des vérifications obligatoires de `verification.md`, vérifier :

- [ ] `build` passe.
- [ ] `lint` passe.
- [ ] `test` passe (coverage non nul).
- [ ] Aucun `any` quand le type est connu.
- [ ] Les erreurs sont propagées et non avalées.
- [ ] Les secrets sont bien dans env vars (pas dans le code).
