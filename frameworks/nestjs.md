---
description: Standard NestJS — architecture modulaire, DTOs typés, tests complets.
mode: subagent
---

# NestJS

> Les conventions TypeScript de base sont héritées de `frameworks/nodejs.md`. Ce framework ne documente que les spécificités NestJS.

## Objectif

Produire du code NestJS propre, modulaire, testé et maintenable.

## Architecture modulaire

- Un module = un domaine métier cohérent.
- Chaque module regroupe son controller, ses services, ses providers, ses DTOs.
- Limiter les modules globaux. Préférer l'import explicite.

```txt
users/
├── users.controller.ts
├── users.service.ts
├── users.module.ts
├── dto/
│   ├── create-user.dto.ts
│   └── update-user.dto.ts
└── tests/
    ├── users.service.spec.ts
    └── users.controller.spec.ts
```

## Controllers fins

- Uniquement parsing et délégation aux services.
- Pas de logique métier.
- Utiliser les décorators NestJS (Get, Post, Body, Param, Query) pour clean input.
- Retourner des DTOs/payloads typés, jamais de raw results.

## Services métier

- Logique métier pure, sans référence aux décorators ou HTTP.
- Injecter via le constructor (NestJS DI).
- Retourner des DTOs ou des erreurs explicites.
- Tester unitairement en mockant les repositories.

## DTOs typés

- `class-validator` ou équivalent projet pour la validation.
- Typage strict des DTOs.
- Ne pas utiliser `any` dans les champs de DTO.

## Guards

- Vérification d'authentification / autorisation.
- Uniquement, pas de logique métier.
- Réutiliser et déclarer explicitement par route.

## Interceptors

- Transformation de réponse, logging, ou timeout.
- Ni authorisation, ni logique métier.

## Pipes

- Validation et transformation des entrées.
- Préférer `ParseIntPipe`, `ValidationPipe`, `ParseArrayPipe` natifs.

## Filters d'erreurs

- Attraper les exceptions non gérées, formater proprement.
- Ne pas exposer les stacks internes en production.
- Logger les erreurs avec contexte.

## Modules par domaine métier

- Chaque module est un bounded context.
- Exposer uniquement ce qui doit être public.
- Mutually dependent modules = refacto nécessaire.

## Tests unitaires des services

- Tester les services en isolation.
- Mock scrupuleusement les repositories.
- Vérifier les effets de bord et les retours.

## Tests des controllers

- Tester les routes sans démarrer le serveur.
- Vérifier les statuts, les DTOs de réponse, les guards.
- Ne pas tester la logique métier (déjà testée dans les services).

## Tests E2E

- Tester les scénarios complets utilisateur.
- Monter un AppModule spécifique aux tests (clear DB, mocks).
- Vérifier le contrat pour chaque endpoint critique.

## Conventions de nommage

- Controller : `users.controller.ts`
- Service : `users.service.ts`
- DTO : `create-user.dto.ts`
- Module : `users.module.ts`
- Tests unitaires : `*.spec.ts`
- Tests e2e : `*.e2e-spec.ts`

## Anti-patterns NestJS

- ❌ Logique métier dans les controllers.
- ❌ `any` dans les DTOs ou les services.
- ❌ Accès direct à la base de données depuis les controllers.
- ❌ Modules monolithiques ou globaux sans besoin.
- ❌ guards avec logique métier.
- ❌ Pas de DTOs typés pour les entrées/sorties.
