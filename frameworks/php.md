---
description: Standard PHP / Laravel 12 — API backend, architecture en couches, tests PHPUnit, CI GitLab.
mode: subagent
---

# PHP / Laravel

## Objectif

Produire des API PHP/Laravel modernes, testées et sécurisées. Baseline de
référence : **Laravel 12 sur PHP 8.4+**.

Ces règles s'ajoutent aux standards globaux ; elles ne les remplacent pas.
En cas de conflit, les conventions du `AGENTS.md` du repo cible l'emportent :
s'il documente un workflow devenv (`fmt` → `lint` → `audit` → `tests`),
suivre ses commandes et ses outils.

**Garde de périmètre** : le déclencheur de détection (`composer.json`) couvre
tout projet PHP. Si le `composer.json` ne requiert ni `laravel/framework` ni
de couche API maison (registre composer privé), n'appliquer que les sections
génériques (structure, style, tests) et suivre les choix du repo — les
prescriptions ci-dessous liées à une couche maison ne s'appliquent pas.

## Structure de projet

```txt
app/
├── Http/
│   ├── Controllers/        # Controllers minces, final, par version (V1/V2)
│   ├── FormRequests/       # Une classe de validation par endpoint
│   ├── Middleware/
│   ├── Resources/          # Sérialisation (normalizers ou API Resources)
│   └── ...
├── Services/               # Logique métier injectée readonly dans les controllers
├── Actions/                # Cas d'usage isolés
├── Repositories/           # Requêtes métier (collections), scopes dans les modèles
├── DTOs/                   # Objets de transport immuables
├── Enums/                  # Enums backées string/int
├── Policies/
└── Jobs/
routes/
├── api.php                 # Filet de routes par audience (public / staff / privé)
└── v1/ ... v2/             # Arborescence alignée sur les namespaces app/**/V1|V2
tests/
├── Unit/
├── Feature/
└── docker-compose.yml      # Suite d'exécution intégrée si le repo en fournit une
```

## Architecture

- **Controllers minces** : `final class`, injection de services
  `private readonly` par promotion de constructeur, aucune requête métier.
- **FormRequest par endpoint** : la convention de nommage des méthodes de
  rules (standard `rules()` ou convention dédiée) est fixée par la couche
  maison du repo — la suivre telle quelle.
- **Sérialisation** : si le repo cible fournit une couche maison, utiliser
  ses normalizers ; sinon les API Resources standard de Laravel.
- **Repositories** isolent les requêtes Eloquent complexes ; scopes de
  modèle préfixés `scope` + attribut dédié + PHPDoc `@method` si le repo
  les documente ainsi.
- **DTOs et Enums dédiés** : pas d'arrays magiques entre couches ; enums
  backées (`: string` / `: int`).
- **Versionnement** : namespaces `App\Http\Controllers\V2\...` alignés sur
  `routes/v2/...` ; un filet de routes par audience d'endpoint
  (public, staff, privé, interne) avec des frontières d'authentification
  explicites par fichier.

## Couche API maison

Quand l'organisation maintient une couche API dédiée (packages composer sur
registre privé, superposés à Laravel), elle constitue le socle standard —
ne pas substituer les briques communautaires tant que la couche existe :

- normalizers de requêtes/réponses dédiés
- socle applicatif et TestCase partagé (base de `CreatesApplication`)
- génération de la documentation API (commande artisan dédiée)
- authentification par guards OAuth2 maison — ne pas installer Sanctum ou
  Passport en parallèle d'une couche auth existante
- audit des endpoints (attributs posés sur les FormRequests)

Erreurs centralisées : `Handler::render()` délègue au renderer API ; les
exceptions métier sont des classes dédiées (ex : `RateLimitExceededException`),
jamais des `HttpException` génériques. Ne pas exposer les stacks au client.

## Contrat API & documentation

- Toute modification de contrat passe par les annotations dédiées du
  générateur de doc (`@api_*`) et régénère la documentation.
- Le CI exécute le diff de documentation : une MR avec un contrat modifié et
  une doc non régénérée **échoue**.

## Style de code

- `declare(strict_types=1)` sur **tout nouveau fichier** ; pas de rétrofit
  massif de fichiers legacy (migration progressive via rector si demandé).
- `final` + `readonly` par défaut sur les classes de service, DTOs et
  normalizers.
- Formatter/linter : **mago** (PER-CS, print-width 120, tab 4 espaces,
  baseline lint) sur les repos modernes ; variants courants : `laravel/pint`
  preset laravel, `php-cs-fixer` (+ `slevomat` sur le legacy). Ne jamais
  mixer deux formatters sur un même repo.
- Analyse statique : `larastan/larastan` (PHPStan niveau repo), `phpmd` ;
  upgrades assistés par rector (sets `LARAVEL_120`, `DeclareStrictTypesRector`).

## Tests

- **PHPUnit** (jamais Pest sur les repos qui imposent PHPUnit), hiérarchie
  `Unit` / `Feature`.
- Privilégier les tests **Feature de bout en bout API** (contrat : statut,
  body, erreurs) — ils dominent numériquement dans les backends éprouvés.
- TestCase de base fourni par la couche maison si présente, sinon
  `CreatesApplication` du framework ; exécution via la suite docker-compose
  du repo quand elle existe, pas d'appel artisan direct.
- Mockery + Faker disponibles ; ne pas tester les détails d'implémentation.

## CI/CD GitLab

- Stages : `.pre` / build / test / deploy / scan.
- Réutiliser les **templates CI maison de l'organisation** quand ils existent
  (installation composer, exécution PHPUnit, style, audit composer, analyse
  statique, SBOM) plutôt que définir des jobs raw.
- Pipelines déclenchés sur merge_request_event, branches cibles de release.

## Workflow agent

- Lire le `AGENTS.md` du repo cible **avant** de coder : il définit les
  commandes devenv (`tests`, `fmt`, `lint`, `audit`), le bouclier audit
  (boucle jusqu'à zéro smell) et les spécificités locales.
- `laravel/boost` (configuré via `boost.json` quand présent) : s'appuyer sur
  ses guidelines comme source Laravel à jour.
- Commits conventionnels ; changelog/releases générés par l'outillage maison
  de l'organisation s'il existe — jamais de changelog manuel.

## Anti-patterns

- ❌ Logique métier dans les controllers (requêtes Eloquent inline).
- ❌ Substituer une brique communautaire à la couche maison existante
  (normalizers, guards, générateur de doc).
- ❌ Pest sur un repo PHPUnit ; artisan test hors de la suite docker-compose.
- ❌ Job CI PHP raw dupliquant un template maison.
- ❌ MR modifiant un contrat API sans régénérer la doc.
- ❌ Exception métier rendue générique (renderer maison contourné).

## Checklist avant validation

En plus des vérifications obligatoires de `verification.md`, vérifier :

- [ ] `fmt` / `lint` (mago ou outil du repo) passent sans baseline ajoutée.
- [ ] Analyse statique (larastan/phpstan) sans nouvelle erreur.
- [ ] `tests` (suite du repo) passent.
- [ ] Contrat API inchangé, ou doc régénérée.
- [ ] Nouveau code : `strict_types`, `final`, `readonly`, FormRequest dédié.
- [ ] Aucune exception métier rendue générique (renderer maison utilisé).
