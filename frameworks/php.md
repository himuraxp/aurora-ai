---
description: Standard PHP / Laravel 12 — API backend Infomaniak, architecture, tests PHPUnit, CI GitLab.
mode: subagent
---

# PHP / Laravel

## Objectif

Produire des API PHP/Laravel modernes, testées et sécurisées, conformes à la
base technique backend Infomaniak : **Laravel 12 sur PHP 8.4–8.5** avec la
couche API maison `infomaniak/*`. Le socle de référence est Laravel 12 /
PHP 8.5 (floor 8.4 pour le legacy récent) ; ne pas référencer Laravel 10/11.

Ces règles s'ajoutent aux standards globaux ; elles ne les remplacent pas.
En cas de conflit, les conventions du `AGENTS.md` du repo cible l'emportent
(les repos backend Infomaniak sont agent-ready et documentent leur propre
workflow devenv : `fmt` → `lint` → `audit` → `tests`).

**Garde de périmètre** : le déclencheur de détection (`composer.json`) couvre
tout projet PHP. Si le `composer.json` ne requiert ni `laravel/framework` ni
de packages `infomaniak/*` (outil CLI, librairie, API hors périmètre),
n'appliquer que les sections génériques (structure, style, tests) et suivre
les choix du repo — les interdits maison (guards, normalizers, templates CI)
ne s'appliquent pas.

## Structure de projet

```txt
app/
├── Http/
│   ├── Controllers/        # Controllers minces, final, par version (V1/V2)
│   ├── FormRequests/       # Une classe par endpoint
│   ├── Middleware/
│   ├── Resources/          # Normalizers maison (BaseNormalizer)
│   └── ...
├── Services/               # Logique métier injectée readonly dans les controllers
├── Actions/                # Cas d'usage isolés
├── Repositories/           # Requêtes métier (collections), scopes dans les modèles
├── DTOs/                   # Objets de transport immuables
├── Enums/                  # Enums backées string/int
├── Policies/
└── Jobs/
routes/
├── api.php                 # Routes par audience (public / _staff / _private / _internal)
└── v1/ ... v2/             # Arborescence alignée sur les namespaces app/**/V1|V2
tests/
├── Unit/
├── Feature/
└── docker-compose.yml      # Exécution via test-local.sh, jamais artisan test direct
```

## Architecture

- **Controllers minces** : `final class`, injection de services
  `private readonly` par promotion de constructeur, aucune requête métier.
- **FormRequest par endpoint** : la méthode de rules suit la convention
  maison `<method>Rules()` (ex : `queryRules()`) quand le repo l'exige.
- **Normalizers maison** au lieu des API Resources standard : classes
  `final` `extends BaseNormalizer` (`Infomaniak\ApiNormalization`), avec
  variantes Unit/Meta si nécessaire.
- **Repositories** isolent les requêtes Eloquent complexes ; scopes de
  modèle préfixés `scope` + attribut `#[Scope]` + PHPDoc `@method`.
- **DTOs et Enums dédiés** : pas d'arrays magiques entre couches ; enums
  backées (`: string` / `: int`).
- **Versionnement** : namespaces `App\Http\Controllers\V2\...` alignés sur
  `routes/v2/...` ; filet de routes par audience (`api.php`,
  `api_staff.php`, `api_private.php`, `api_internal_no_auth.php`).

## Couche API Infomaniak

La couche API standard est constituée de packages maison, superposés à
Laravel — ne pas substituer les briques communautaires :

- `infomaniak/api-normalization` — normalizers de requêtes/réponses
- `infomaniak/site-api-laravel-core` + `api-core-tests` — socle applicatif et TestCase (`CreatesApplication`)
- `infomaniak/api-doc` — génération de la documentation API (`artisan api:doc:generate`)
- `infomaniak/laravel-oauth2` + guards `infomaniak` / `infomaniak-token` — authentification (pas de Sanctum/Passport)
- `infomaniak/lib-laravel-audit-api` — audit des endpoints (attributs sur les FormRequests)

Erreurs centralisées : `Handler::render()` délègue au renderer API maison ;
les exceptions métier sont des classes dédiées (ex : `RateLimitExceededException`),
jamais des `HttpException` génériques. Ne pas exposer les stacks au client.

## Contrat API & documentation

- Toute modification de contrat passe par les annotations `@api_path_required`,
  `@api_return`, `@category` et régénère la documentation.
- Le CI exécute `laravel-api-doc-diff` : une MR avec un contrat modifié et
  une doc non régénérée **échoue**.

## Style de code

- `declare(strict_types=1)` sur **tout nouveau fichier** ; pas de rétrofit
  massif de fichiers legacy (migration progressive via rector si demandé).
- `final` + `readonly` par défaut sur les classes de service, DTOs et
  normalizers.
- Formatter/linter **mago** (PER-CS, print-width 120, tab 4 espaces,
  baseline lint) sur les repos modernes ; variants connus : `laravel/pint`
  preset laravel, `php-cs-fixer` + `slevomat` sur le legacy. Ne jamais mixer
  deux formatters sur un même repo.
- Analyse statique : `larastan/larastan` (PHPStan niveau repo), `phpmd` ;
  upgrades assistés par rector (`LARAVEL_120`, `DeclareStrictTypesRector`).

## Tests

- **PHPUnit** (jamais Pest), hiérarchie `Unit` / `Feature`.
- Privilégier les tests **Feature de bout en bout API** (contrat : statut,
  body, erreurs) — ils dominent numériquement dans les repos de référence.
- TestCase de base sur `Infomaniak\ApiCoreTests\CreatesApplication` ;
  exécution via `tests/test-local.sh` (docker-compose), pas `artisan test` direct.
- Mockery + Faker disponibles ; ne pas tester les détails d'implémentation.

## CI/CD GitLab

- Stages : `.pre` / build / test / deploy / scan.
- Réutiliser les **templates maison** : includes
  `docker-public/gitlab-ci-dev-scripts` (php-composer, php-unit-test,
  php-code-style, php-composer-audit, laravel-audit-api, sonarqube) et
  composants `devops/ci` (`laravel-api-doc`, `laravel-api-doc-diff`, SBOM).
- Pas de jobs raw dupliquant ces templates ; pipelines déclenchés sur
  merge_request_event, branches cibles develop/master.

## Workflow agent

- Lire le `AGENTS.md` du repo cible **avant** de coder : il définit la
  commande `tests`, le bouclier `audit` (JSON smells, boucle jusqu'à zéro)
  et les spécificités locales.
- `laravel/boost` est configuré sur les repos (`boost.json`, agents opencode) :
  s'appuyer sur ses guidelines comme source Laravel à jour.
- Commits conventionnels ; changelog/releases générés par
  `infomaniak/lib-conventional-changelog` (scripts composer `changelog`,
  `release` + notification kChat) — jamais de changelog manuel.

## Anti-patterns

- ❌ Logique métier dans les controllers (requêtes Eloquent inline).
- ❌ API Resources standard là où la norme repo est `BaseNormalizer`.
- ❌ Sanctum/Passport là où les guards `infomaniak` sont configurés.
- ❌ Pest sur un repo PHPUnit ; `artisan test` hors docker-compose.
- ❌ Job CI PHP raw dupliquant un template `gitlab-ci-dev-scripts`.
- ❌ MR modifiant un contrat API sans régénérer la doc.
- ❌ Réinstaller des briques communauté que la couche maison couvre déjà.

## Checklist avant validation

En plus des vérifications obligatoires de `verification.md`, vérifier :

- [ ] `fmt` / `lint` (mago ou outil du repo) passent sans baseline ajoutée.
- [ ] Analyse statique (larastan/phpstan) sans nouvelle erreur.
- [ ] `tests` (suite docker-compose du repo) passent.
- [ ] Contrat API inchangé, ou doc régénérée (`api:doc:generate`).
- [ ] Nouveau code : `strict_types`, `final`, `readonly`, FormRequest dédié.
- [ ] Aucune exception métier rendue générique (renderer maison utilisé).
