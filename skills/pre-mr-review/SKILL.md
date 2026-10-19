---
name: pre-mr-review
description: Effectuer une revue de qualité pré-MR complète. Analyse le périmètre modifié pour identifier le code mort, les duplications, les simplifications possibles et les refactorings à faible risque. Mode avancé disponible pour les merges sur develop/master vérifiant conventions, complexité, typage, performances, accessibilité et sécurité.
---

# Revue de Qualité Pré-MR

Effectue une revue complète des modifications avant ouverture de la Merge Request afin d'améliorer la qualité du code sans modifier le comportement fonctionnel.

## Mode standard (par défaut)

Utilisé pour toute revue pré-MR standard.

### Analyse préalable

Avant toute modification :

#### Détermination de la branche de référence

Si l'utilisateur a explicitement spécifié une branche de comparaison (ex: "compare avec develop", "par rapport à origin/main"), utiliser **impérativement** cette branche sans tenter de détecter automatiquement.

Sinon, détecter automatiquement la **branche parent réelle** (celle depuis laquelle la branche courante a été créée) et calculer le merge-base.

#### Algorithme de détection de la branche parent

Le problème : la branche de tracking (`@{u}`) pointe souvent vers `origin/develop` ou la remote de la branche elle-même, et non vers la branche parent réelle. Le fallback `main`/`master`/`develop` inclut alors tous les commits de la branche parent dans le diff.

Exemple : `feat/trello-V6hDEYiv` créée depuis `feat/media-converter`. Si on compare contre `origin/develop`, le diff contient les commits de `feat/media-converter` ET ceux de `feat/trello-V6hDEYiv`. Il faut comparer contre `feat/media-converter`.

**Méthode** : parmi toutes les branches (locales et distantes), trouver celle dont le `merge-base` avec HEAD est le **plus récent** (commit timestamp le plus élevé). C'est la branche qui a divergé le plus récemment de HEAD = la branche parent. On filtre les branches où HEAD n'a aucun commit d'avance (ce seraient des branches enfants, pas parent).

```bash
# Détecter la branche courante
CURRENT_BRANCH=$(git branch --show-current)

# Trouver la branche parent réelle (la branche depuis laquelle la branche courante a été créée)
# Méthode : parmi toutes les branches, trouver celle dont le merge-base avec HEAD est
# le plus récent (divergence la plus proche = branche parent la plus probable).
# On exclut la branche courante et sa remote tracking (comparer contre soi-même = inutile).
# On filtre les branches où HEAD n'a aucun commit d'avance (branches enfants, pas parent).

BEST_BRANCH=""
BEST_MB_TIMESTAMP=0
BEST_BEHIND=999999

for REF in $(git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/origin/ 2>/dev/null \
             | grep -v "^${CURRENT_BRANCH}$" \
             | grep -v "^origin/${CURRENT_BRANCH}$" \
             | grep -v 'HEAD$'); do
    MB=$(git merge-base HEAD "$REF" 2>/dev/null || echo "")
    if [ -n "$MB" ]; then
        # HEAD doit avoir des commits que cette branche n'a pas (sinon c'est une branche enfant)
        AHEAD=$(git rev-list --count "$REF..HEAD" 2>/dev/null || echo 0)
        if [ "$AHEAD" -gt 0 ]; then
            BEHIND=$(git rev-list --count "HEAD..$REF" 2>/dev/null || echo 0)
            MB_TS=$(git log -1 --format=%ct "$MB" 2>/dev/null || echo 0)
            # Préférer le merge-base le plus récent ; en cas d'égalité de timestamp,
            # la branche la moins divergente (BEHIND le plus petit) = la branche parent directe
            if [ "$MB_TS" -gt "$BEST_MB_TIMESTAMP" ] || \
               ([ "$MB_TS" -eq "$BEST_MB_TIMESTAMP" ] && [ "$BEHIND" -lt "$BEST_BEHIND" ]); then
                BEST_MB_TIMESTAMP=$MB_TS
                BEST_BRANCH="$REF"
                BEST_BEHIND=$BEHIND
            fi
        fi
    fi
done

if [ -n "$BEST_BRANCH" ]; then
    UPSTREAM="$BEST_BRANCH"
else
    # Fallback 1 : branche de tracking configurée
    UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "")
    # Fallback 2 : branches distantes communes
    if [ -z "$UPSTREAM" ]; then
        UPSTREAM=$(git branch -r | grep -E 'origin/(main|master|develop)' | sort | head -1 | xargs || echo "origin/main")
    fi
fi

# Calculer le commit de création (merge-base)
BASE_COMMIT=$(git merge-base HEAD "$UPSTREAM")

# Afficher la branche parent détectée pour vérification
echo "Branche parent détectée : $UPSTREAM (merge-base: $(git rev-parse --short "$BASE_COMMIT"))"

# Afficher le diff exact des changements de cette branche
git diff "$BASE_COMMIT..HEAD"
```

Enregistrer la branche utilisée pour le diff dans le contexte de la session. **Si la branche détectée ne correspond pas à la branche parent attendue, demander à l'utilisateur de confirmer ou de spécifier explicitement la branche de comparaison.**

#### Chargement des conventions du projet (AGENTS.md)

**OBLIGATOIRE** — Avant de commencer la revue, vérifier la présence du fichier `AGENTS.md` à la racine du projet :

- Si `AGENTS.md` existe : **le consulter impérativement** et extraire toutes les conventions, règles de nommage, patterns d'architecture, directives de style et autres règles projet spécifiques. Ces conventions doivent être **intégrées à toutes les vérifications** et prendre la priorité sur les règles génériques.
- Si `AGENTS.md` n'existe pas : utiliser les défauts, mais noter dans le récapitulatif final l'absence de conventions explicites. Les règles génériques s'appliquent alors.
- Si `AGENTS.md` contient des 🚫 (STOP) ou des warnings critiques : **ne pas procéder** à des modifications dans les zones concernées et signaler le blocage dans le récapitulatif.
- Si `AGENTS.md` contient des contradictions avec `docs/ai/DECISIONS.md` : **STOPPER immédiatement** et demander clarification à l'utilisateur.

### Vérifications

#### 0. Conformité AGENTS.md — vérifications bloquantes (TOUJOURS)

**Cette section est PRIORITAIRE sur toutes les autres.**

Le fichier `AGENTS.md` contient des règles CRITICAL numérotées. Il faut les extraire et les vérifier **systématiquement** sur chaque ligne du diff, sans exception. Les checks suivants sont des vérifications **bloquantes** : si elles échouent, le récapitulatif final doit les signaler comme **BLOCKERS** et l'agent doit corriger avant de proposer la MR.

**Patterns interdits à détecter dans le diff :**

| Règle AGENTS.md | Pattern à scanner | Décrit dans le diff |
|---|---|---|
| Rule 22 — Non-null assertion (`!`) | `\w+!\.\w+` (générique : tout identifiant suivi de `!.`), `\)!\.\w+` ou tout `!` après une expression optionnelle | L'expression précédée de `?` suivie immédiatement de `!` |
| Rule 23 — Manual cast (`as`) | `\b\w+\s+as\s+\w+` (incluant `as never`, `as unknown as`) | Tout cast `as Type` dans le code nouveau (tests compris) |
| Rule 25 — Speculative infrastructure | Fonction dont le corps ne fait que `return constante_array;` après un guard `UNSPECIFIED` | Fonction mappée `getXForY` retournant toujours la même constante |
| Rule 26 — Tautological test | `it.each` ou `it` où chaque cas d'entrée produit le même résultat attendu, et le résultat est une constante hardcodée dans le test | Test avec `toEqual(expectedConstant)` où `expectedConstant` est identique pour toutes les entrées |
| Rule 27 — Dead code branch | `if` dont la condition ne peut être vraie qu'avec une valeur impossible du domaine (ex: `PROFILE_UNSPECIFIED` dans un select qui n'exclut jamais cette valeur) | Branche `if` conditionnée sur une valeur que le UI ne peut pas produire |
| Rule 28 — CSS semantic dishonesty | `whitespace-pre-line` ou `pre-wrap` appliqué à une interpolation de chaîne ne pouvant contenir de `\n` | Classe `whitespace-pre-line` dans le template HTML |
| Rule 14 — Empty catch | `catchError\(\(error\)\s*=>\s*\{\s*return` ou `error:\s*\(\)\s*=>\s*\{\s*\}` | Callback `catchError` ou `error` sans corps |
| Rule 16 — `Record<string, unknown>` | `Record<string, unknown>` | Type trop vague quand une structure est connue |
| Rule 30 — Directive internal API access | `\.trigger\.(stopOpenOnMouseOver\|openOnClick\|close)\|overlay\?\.element` | Accès à `.trigger`, `.overlay`, `.close()` depuis un composant |
| Rule 31 — `::ng-deep` | `::ng-deep` | Usage de `::ng-deep` dans les styles SCSS/CSS |
| Rule 32 — `localeCompare` on ISO dates | `\.localeCompare\(` | Tri de dates ISO 8601 avec `localeCompare` |
| Rule 33 — `NO_ERRORS_SCHEMA` | `NO_ERRORS_SCHEMA` | Utilisation de `NO_ERRORS_SCHEMA` dans les tests |
| Rule 34 — Helper logic in component | Fonction pure/métier privée `#` ou `private readonly` dans un `.component.ts` | Logique de groupement, d'agrégation ou de formatage pure dans un composant |
| Rule 35 — Widened `string` for domain literals | Paramètre `status: string` dans une méthode qui reçoit un union type connu | Perte de l'exhaustivité du `switch` par élargissement à `string` |
| Rule 36 — Missing component under test | `TestBed.configureTestingModule` contenant des imports mais PAS le composant cible | Le composant testé n'est pas dans le tableau `imports` |
| Rule 37 — Method calls from template | `[class.*]="[^"]*\w+\([^"]*\)`, `{{ \w+\(` ou `\(click\)="\w+\(` dans `.html` | Méthode du composant appelée dans un binding template avec arguments (computed interdit) |
| Rule 38 — Redundant `input(undefined)` | `input<[^>]+>\(\s*undefined\s*\)` | Optional signal input avec initialisation `undefined` explicite |
| Rule 39 — Manual `undefined` checks instead of `isNullish` | `!==\s*undefined\b|\B===\s*undefined\b|!==\s*null\s*&&\s*!==\s*undefined|===\s*null\s*\|\|\s*===\s*undefined` ou `value &&` utilisé pour détecter null/undefined | Vérification manuelle `null/undefined` ou truthiness check au lieu de `isNullish()` / `!isNullish()` |
| Rule 40 — String union type alias | `export\s+type\s+\w+\s*=\s*('[^']+'\s*\|)` | `export type` string union qui doit être un `enum` dans `.model.ts` |
| Rule 19 extension — Types/enums in `.helper.ts` | `export\s+(type|enum|interface)` dans un fichier `.helper.ts` du diff | Type/enum/interface exporté depuis un fichier `.helper.ts` au lieu de `.model.ts` |
| Rule 41 — Error swallowing `of(undefined)` in NGXS | `of(undefined)\.pipe\(\s*tap` ou `of(undefined)` dans un fichier `.state.ts` suivi de `dispatch\(new NotifyError` dans le même bloc | Erreur dispatchée dans `tap` puis `of(undefined)` → action marquée réussie + double toast |
| Rule 42 — Dead `??` after non-nullish expression | `\.split\([^)]*\)\[0\]\s*\?\?` ou `\.match\([^)]*\)\?\.\[0\]\s*\?\?` | Fallback `??` après une expression toujours définie (ex: `split('?')[0] ?? path`) |
| Rule 43 — `as never` / double cast in tests | `\bas\s+never\b` ou `\bas\s+unknown\s+as\s+` | Cast bypassant TypeScript, même dans les tests |
| Rule 44 — Production crippled by test env | `JSON\.parse\(JSON\.stringify\(` dans un fichier `.ts` non `.spec.ts`, ou `eslint-disable.*structuredClone` | Code de production contraint par limitation de l'environnement de test |
| Rule 18 — User-facing string without transloco | `\[(ikTooltip\|attr\.aria-label\|label\|placeholder)\]="[^"]*"` sans `\| transloco` dans `.html`, ou `{{ '[^']*' }}` / `{{ "[^"]*" }}` sans `\| transloco` | Attribut user-facing ou interpolation texte non pipé via `transloco` |
| Rule 49 — Magic string domain literal | `!== '[A-Z][A-Za-z]+'` ou `=== '[A-Z][A-Za-z]+'` dans un `.component.ts` ou `.helper.ts` | Littéral chaîne représentant une valeur du domaine comparé directement |
| Rule §2 — Interface with `T` prefix | `interface\s+T[A-Z]` dans un fichier `.ts` | Interface déclarée avec préfixe `T` au lieu de `I` |
| Rule 50 — Anonymous inline object type in signature | `:\s*\{[^}]+\}\[\]` ou `:\s*\{[^}]+\}\s*$` dans une `export function` | Type objet anonyme inline dans une signature de fonction exportée |
| Rule 3 — Subscription without `takeUntilDestroyed` | `\.subscribe\(` non précédé de `takeUntilDestroyed` dans la même chaîne de pipe | Subscription sans `takeUntilDestroyed` dans le diff |
| Rule 49 extended — Magic string domain literal (lowercase) | `\?\?\s*'[a-z][a-z-]+'` ou `===\s*'[a-z][a-z-]+'` dans un `.ts` | Fallback ou comparaison avec une string lowercase représentant une valeur du domaine (ex: `'hls'`) |
| Redundant `Validators.minLength(1)` with `required` | `Validators\.minLength\(1\)` en présence de `Validators\.required` | `minLength(1)` redondant avec `required` — `required` rejette déjà les strings vides |
| Lesson 42 — `.model.ts` outside `models/` directory | Fichier `.model.ts` dont le chemin ne contient pas `/models/` | Fichier `.model.ts` co-localisé avec un composant au lieu d'être dans le répertoire `models/` centralisé |
| Rule 53 — Confusing spread order (explicit before spread) | `\{\s*\w+:\s*[^,}]+,\s*\.\.\.\w+` | Propriétés explicites avant un spread dans un objet littéral (écrasement silencieux) |

**Action obligatoire si un pattern BLOCKER est détecté :**

1. Lister l'occurrence exacte (fichier + ligne).
2. Proposer la correction directement conforme à l'exemple ✅ de `AGENTS.md`.
3. **Ne jamais valider une MR si un BLOCKER persiste.**

**Commandes de scan rapide sur le diff :**

```bash
# Scanner le diff pour les patterns critiques
# NOTE : $UPSTREAM et $BASE_COMMIT sont déjà déterminés par l'algorithme de
# détection de la branche parent ci-dessus. Ne pas recalculer ici.
# Si l'agent arrive directement à cette section sans avoir exécuté la détection,
# il DOIT remonter à la section "Détermination de la branche de référence" d'abord.
BASE_COMMIT=${BASE_COMMIT:-$(git merge-base HEAD "${UPSTREAM:-origin/main}")}

# Non-null assertion (! sur valeur optionnelle) — scan générique
# Capture tout identifiant suivi de "!." (ex: result!.settings, form!.value, user!.name)
# ainsi que les patterns spécifiques (.get()!, )!., et "?...!")
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '\w+!\.|\)!\.|\?\.!\.' || true

# Manual cast (as Type) — generic detection of ANY type assertion in added lines.
# Flags: `as unknown`, `as unknown as` (double cast), `as string|number|boolean`,
# `as <PascalCase>`, `as never`, and casts after form accessors (.getRawValue() as, .value as).
# Excludes legitimate `as const` and import aliasing (`import { X as Y }`).
git diff "$BASE_COMMIT..HEAD" -- '*.ts' \
  | grep -nE '^\+.*\bas\s+(unknown(\s+as)?|never|string|number|boolean|[A-Z][A-Za-z0-9_]*)\b' \
  | grep -vE '^\+.*(\{ .* as |as const)' || true

# whitespace-pre-line in HTML when data has no newlines
git diff "$BASE_COMMIT..HEAD" -- '*.html' | grep -nE 'whitespace-pre-line|whitespace-pre-wrap' || true

# Empty catch/error callbacks
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'catchError\(\(error\)\s*=>\s*\{\s*return|error:\s*\(\)\s*=>\s*\{\s*\}' || true

# Record<string, unknown>
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'Record<string, unknown>' || true

# Speculative placeholder comments
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -niE 'refine here|placeholder|future|backend|TODO.*refine|FIXME.*per.*codec' || true

# Directive internal API access (trigger, overlay manipulation)
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '\.trigger\.(stopOpenOnMouseOver|openOnClick|close)|overlay\?\.element|\.element\)\.contains' || true

# ::ng-deep in styles
git diff "$BASE_COMMIT..HEAD" -- '*.scss' '*.css' | grep -nE '::ng-deep' || true

# localeCompare on date fields (heuristic: property name contains date/time)
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '\.(scheduled_at|created_at|updated_at|started_at|ended_at|timestamp|date).*\.localeCompare' || true

# NO_ERRORS_SCHEMA in test files
git diff "$BASE_COMMIT..HEAD" -- '*.spec.ts' | grep -nE 'NO_ERRORS_SCHEMA' || true

# Pure helper logic embedded in component (business functions inside .component.ts)
git diff "$BASE_COMMIT..HEAD" -- '*.component.ts' | grep -nE '(private|#)(group|aggregate|format|determine|compute|map|parse|transform)\w*\(' || true

# Widened string parameter that should be a union type
# Heuristic: method named get*Label/status or switch with string param
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'status:\s*string\b|\bget\w*Label\(.*:\s*string\b' || true

# Component under test missing from imports in spec files
git diff "$BASE_COMMIT..HEAD" -- '*.spec.ts' | grep -nE 'TestBed\.(overrideTestingModule|configureTestingModule)(\s|\n)*\{' -A 10 | grep -nE 'imports:\s*\[' -A 5 || true

# Import order violations — check each MODIFIED .ts file (more reliable than raw-diff grep).
# Detects internal-alias imports (@app/@products/@shared/@environments) appearing
# BEFORE third-party (@angular/@infomaniak/@jsverse/@ngrx/@rxjs) without a blank-line
# group separator. Ranks: angular=1, third-party=2, internal=3, relative=4.
# Also detects false blank-line separations WITHIN the same group (Rule §1).
git diff --name-only "$BASE_COMMIT..HEAD" -- '*.ts' | while read -r FILE; do
  [ -f "$FILE" ] || continue
  awk '
    function grp(l) {
      if (l ~ /from .@angular\//) return 1
      if (l ~ /from .@(ngxs|ngrx|rxjs|infomaniak|jsverse)\//) return 2
      if (l ~ /from .@(app|products|shared|environments)\//) return 3
      if (l ~ /from .[.][.][\/]/) return 4
      return 0
    }
    /^import / && !/^import type / {
      g = grp($0)
      if (g > 0 && prevg > 0 && g < prevg) {
        printf "%s:%d: IMPORT ORDER — group %d appears after group %d\n", FILENAME, NR, g, prevg
      }
      if (g > 0 && blank_after > 0 && g == blank_after) {
        printf "%s:%d: FALSE GROUP SEPARATION — blank line within group %d\n", FILENAME, NR, g
      }
      if (g > 0) { prevg = g; blank_after = 0 }
    }
    /^\s*$/ { blank_after = prevg; prevg = 0 }
  ' "$FILE"
done || true

# Relative imports where workspace alias exists (heuristic: ./ and ../ inside src/app/)
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'from\s+[\'\"\'\'](\.\/|\.\.\/)' | grep -v '\.spec\.ts' || true

# Rule 37 — Method calls from template with arguments (heuristic: function call syntax inside binding)
git diff "$BASE_COMMIT..HEAD" -- '*.html' | grep -nE '\[class[^"]*\w+\(|\[\w+\][^"]*\w+\(|\{\{[^}]*\w+\(' || true

# Rule 38 — Redundant explicit undefined in optional input signals
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'input<[^>]+>\(\s*undefined\s*\)' || true

# Rule 39 — Manual null/undefined checks and truthiness checks instead of isNullish
# Flags === undefined, !== undefined, === null || === undefined, and truthiness
# checks (value &&) used to detect null/undefined — should use isNullish()/!isNullish()
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '!==\s*undefined\b|===\s*undefined\b|!==\s*null\s*&&\s*!==\s*undefined' || true
# Truthiness check for null/undefined detection: pattern like "value &&" or "value && value !== ''"
# Heuristic: identifier && same identifier !== '' (common anti-pattern for null/empty check)
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '\b(\w+)\s*&&\s*\1\s*!==\s*'"'"''"'"'' || true

# Rule 40 — String-literal union type alias that should be an enum
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE "export\s+type\s+\w+\s*=\s*('[^']+'\s*\|)" || true

# Types/enums/interfaces exported from .helper.ts (should go to .model.ts)
git diff "$BASE_COMMIT..HEAD" -- '*.helper.ts' | grep -nE '^\+export\s+(type|enum|interface)\s+' || true

# Rule 41 — Error swallowing in NGXS: of(undefined) + tap(NotifyError)
# Detects of(undefined)/EMPTY followed by tap with NotifyError dispatch in .state.ts
git diff "$BASE_COMMIT..HEAD" -- '*.state.ts' | grep -nE 'of\(undefined\)|return EMPTY' -A5 | grep -nE 'NotifyError' || true

# Rule 42 — Dead ?? fallback after always-defined expressions
# split()[0] always returns a string; match()?.[0] already guarded by ?.
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE "\.split\([^)]*\)\[0\]\s*\?\?|\.match\([^)]*\)\?\.\[0\]\s*\?\?" || true

# Rule 43 — as never / as unknown as (double cast) — even in tests
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '\bas\s+never\b|\bas\s+unknown\s+as\s+' || true

# Rule 44 — Production code crippled by test environment limitations
# Flags JSON.parse(JSON.stringify()) in non-spec files and eslint-disable of structuredClone
git diff "$BASE_COMMIT..HEAD" -- '*.ts' ':!*.spec.ts' | grep -nE 'JSON\.parse\(JSON\.stringify\(' || true
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'eslint-disable.*structuredClone|structuredClone.*not.*available.*jsdom' || true

# Rule 18 — User-facing string attributes and interpolations without transloco pipe
# Flags [ikTooltip], [attr.aria-label], label=, placeholder= bindings without | transloco
# Also flags {{ 'text' }} and {{ "text" }} interpolations without | transloco
git diff "$BASE_COMMIT..HEAD" -- '*.html' | grep -nE '\[(ikTooltip|attr\.aria-label|label|placeholder)\]="[^"]*"' | grep -v 'transloco' || true
git diff "$BASE_COMMIT..HEAD" -- '*.html' | grep -nE "\{\{[^}]+'[^']*'[^}]*\}\}|\{\{[^}]+\"[^\"]*\"[^}]*\}\}" | grep -v 'transloco' || true

# Rule 49 — Magic string domain literal compared directly in logic
# Flags === 'PascalCase' or !== 'PascalCase' comparisons in .ts files (heuristic: capitalized literal)
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '===\s*'"'"'[A-Z][A-Za-z]+'"'"'|!==\s*'"'"'[A-Z][A-Za-z]+'"'"'' || true

# Rule §2 — Interface declared with T prefix instead of I
# Flags interface TName in .ts files
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'interface\s+T[A-Z]' || true

# Rule 50 — Anonymous inline object type in exported function signature
# Flags { key: T; ... }[] or { key: T; ... } as return/param type in export function
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'export\s+function\s+\w+\s*\([^)]*\):\s*\{[^}]+\}\s*(\[\]|$)' || true
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'export\s+function\s+\w+\s*\([^)]*:\s*\{[^}]+\}' || true

# Rule 3 — Subscription without takeUntilDestroyed
# Detects .subscribe() calls in the diff that are not preceded by takeUntilDestroyed
# in the same pipe chain. Flags the file + line for manual verification.
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '^\+.*\.subscribe\(' | grep -v 'takeUntilDestroyed' || true

# Rule 49 extended — Magic string domain literal (lowercase fallbacks)
# Catches 'hls', 'hls-chain', etc. used as ?? fallback or === comparison values
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE "\?\?\s*'[a-z][a-z-]+'|===\s*'[a-z][a-z-]+'" || true

# Redundant Validators.minLength(1) alongside Validators.required
# required already rejects empty strings; minLength(1) is noise
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE 'Validators\.minLength\(1\)' || true

# Lesson 42 — .model.ts file outside the centralized models/ directory
# Model files should be in a models/ directory, not co-located with components
git diff --name-only "$BASE_COMMIT..HEAD" | grep -E '\.model\.ts$' | grep -v '/models/' || true

# Rule 53 — Confusing spread order (explicit properties before spread)
# Detects { key: value, ...obj } which silently overrides the explicit properties
git diff "$BASE_COMMIT..HEAD" -- '*.ts' | grep -nE '\{\s*\w+:\s*[^,}]+,\s*\.\.\.\w+' || true
```

**Lint & format automatique (OBLIGATOIRE — prévient les retours triviaux de revue)**

Avant toute analyse sémantique, exécuter les commandes de lint et format du projet pour détecter les violations d'ordre d'import, d'indentation et de style qui seraient autrement signalées par un reviewer humain :

```bash
# 1. Lint — détecte les violations d'ordre d'import, les casts, les règles TypeScript
yarn lint 2>&1 | tee /tmp/pre-mr-lint.log

# 2. Format check — détecte les incohérences d'indentation et de style
yarn format:check 2>&1 | tee /tmp/pre-mr-format.log
```

**Action si lint ou format:check signalent des erreurs :**

1. Exécuter `yarn lint:fix` et `yarn format:write` sur les fichiers du diff.
2. Relancer `yarn lint` et `yarn format:check` pour confirmer.
3. Toute erreur résiduelle est un **BLOCKER** signalé dans le récapitulatif.

**Note :** Le bot de revue ne fait pas de raisonnement sémantique sur l'ordre des imports — il compare les groupes déclarés dans `AGENTS.md` (Angular → Third-party → Internal → Relative). La règle ESLint `import/order` du projet (`config/eslint/import-order.mjs`) couvre déjà ces groupes. Toute violation d'ordre d'import remontée par un reviewer indique que `yarn lint` n'a pas été exécuté avant le commit.

#### 1. Code mort

- variables inutilisées ;
- imports inutilisés ;
- fonctions, méthodes ou composants non utilisés ;
- conditions devenues inutiles ;
- branches de code inaccessibles ;
- commentaires obsolètes ;
- imports relatifs (`./` ou `../`) dans un fichier `.ts` quand un alias de workspace existe pour le même import ;
- violation de l'ordre d'import (mix entre paquets Angular, third-party, alias internes, ou relatifs sans séparation par ligne vide).

#### 2. Duplication

- logique dupliquée ;
- conditions répétées ;
- transformations identiques ;
- composants ou helpers pouvant être mutualisés ;
- constantes pouvant être réutilisées.

#### 3. Simplification

Identifier les endroits où le code peut être rendu plus simple sans diminuer sa lisibilité :

- conditions simplifiables ;
- imbrications inutiles ;
- variables intermédiaires superflues ;
- retours anticipés (`early return`) lorsque cela améliore la lecture ;
- expressions pouvant être rendues plus explicites ;
- suppression de code inutile.

#### 4. Refactoring (faible risque uniquement)

Proposer uniquement des refactorings à faible risque :

- améliorer la lisibilité ;
- améliorer le nommage lorsque nécessaire ;
- extraire uniquement les fonctions réellement réutilisables ;
- supprimer les duplications ;
- réduire la complexité cyclomatique ;
- conserver les conventions existantes.

Ne pas introduire de nouvelles abstractions si elles n'apportent pas un bénéfice clair.

### Contraintes

- Ne pas modifier le comportement fonctionnel.
- Ne pas modifier l'API publique des composants sans nécessité.
- Réutiliser les helpers, services et composants existants.
- Éviter toute nouvelle dépendance.
- Limiter les changements au périmètre concerné.
- Ne jamais faire de refactoring "par principe" : chaque modification doit apporter un gain réel de lisibilité, de simplicité ou de maintenabilité.

### Résultat attendu

Appliquer directement les améliorations pertinentes.

À la fin, fournir un récapitulatif indiquant :

- **les BLOCKERS `AGENTS.md` détectés et corrigés** (liste explicite avec fichier + ligne pour chaque `!`, `as`, `as never`, `as unknown as`, `whitespace-pre-line`, `Record<string, unknown>`, test tautologique, infrastructure spéculative, accès interne directive, `::ng-deep`, `localeCompare` ISO, `NO_ERRORS_SCHEMA`, logique pure dans composant, `string` élargi, imports test manquants, **appel méthode template**, **`input(undefined)` redondant**, **`isNullish` manquant ou truthiness check (`value &&`)**, **types/enums dans `.helper.ts`**, **string union type au lieu d'enum**, **error swallowing `of(undefined)` dans NGXS**, **dead `??` fallback**, **`JSON.parse(JSON.stringify())` contraint par env de test**, **attribut ou interpolation user-facing sans `transloco`**, **magic string domain literal comparé directement**, **fausse séparation de groupe d'imports**, **interface avec préfixe `T` au lieu de `I`**, **type objet anonyme inline dans une signature de fonction exportée**, **subscription sans `takeUntilDestroyed`**, **magic string domain literal en lowercase (`?? 'hls'`)**, **`Validators.minLength(1)` redondant avec `required`**, **fichier `.model.ts` hors du répertoire `models/` centralisé**, **spread order trompeur (propriétés explicites avant spread)**, **duplication de logique de parsing/splitting existant dans un helper**, etc.) ;
- le code mort supprimé ;
- les duplications supprimées ;
- les simplifications réalisées ;
- les refactorings effectués ;
- les éventuels points qui mériteraient une discussion avant la Merge Request.

**Si un BLOCKER `AGENTS.md` persiste après la revue, la conclusion doit être `"MR NON PRÊTE — BLOCKERS AGENTS.md NON RÉSOLUS"` et lister les violations restantes.**

## Mode avancé (merges critiques)

Activé explicitement par l'utilisateur via "mode avancé" ou "review complète".

À utiliser systématiquement avant un merge sur `develop` ou `master`.

En plus des vérifications du mode standard, effectuer les contrôles suivants :

### 5. Conventions du projet

- cohérence avec les conventions de nommage établies ;
- **respect strict des CRITICAL RULES de `AGENTS.md`** (si elles sont listées numériquement) — chaque violation doit être traitée comme un BLOCKER ;
- absence d'infrastructure spéculative (wrapper `getXForY` retournant toujours la même constante sans divergence réelle) — `AGENTS.md` Rule 25 ;
- absence de tests tautologiques (tester que `f(x) === C` quand `f` est littéralement `return C`) — `AGENTS.md` Rule 26 ;
- **absence d'appels à des APIs internes de directives** (`.trigger`, `.overlay`, manipulation impérative) — `AGENTS.md` Rule 30 ;
- **pas de `::ng-deep`** dans les styles — `AGENTS.md` Rule 31 ;
- **pas de `localeCompare` pour trier des dates ISO** — `AGENTS.md` Rule 32 ;
- **pas de `NO_ERRORS_SCHEMA`** — `AGENTS.md` Rule 33 ;
- **logique métier/pure extraite des composants** dans des `.helper.ts` — `AGENTS.md` Rule 34 ;
- **types union concrets** utilisés au lieu de `string` pour des valeurs de domaine figées — `AGENTS.md` Rule 35 ;
- **composant sous-test présent dans `imports`** — `AGENTS.md` Rule 36 ;
- **pas d'appel de méthodes du composant depuis le template avec arguments** (state dérivé via `computed()` uniquement) — `AGENTS.md` Rule 37 ;
- **pas de `input<T | undefined>(undefined)` redondant** — `AGENTS.md` Rule 38 ;
- **utilisation systématique de `isNullish()` / `!isNullish()`** au lieu de `=== undefined` / `!== undefined` manuels ou truthiness checks (`value &&`) — `AGENTS.md` Rule 39 ;
- **pas de `export type` string-literal union** pour un ensemble fini de constantes (doit être un `enum` dans `.model.ts`) — `AGENTS.md` Rule 40 ;
- **pas d'error swallowing déguisé `of(undefined)` + `tap(NotifyError)` dans les actions NGXS** (doit produire un `throwError`) — `AGENTS.md` Rule 41 ;
- **pas de `?? fallback` après une expression toujours définie** (ex: `split('?')[0] ?? path`) — `AGENTS.md` Rule 42 ;
- **pas de `as never` ni `as unknown as T` (double cast)**, même dans les tests — `AGENTS.md` Rule 43 ;
- **pas de code de production contraint par l'environnement de test** (ex: `JSON.parse(JSON.stringify())` au lieu de `structuredClone` à cause d'un claim jsdom) — `AGENTS.md` Rule 44 ;
- **pas d'attribut user-facing sans `transloco`** (`[ikTooltip]`, `[attr.aria-label]`, `label=`, `placeholder=` non pipés via `transloco`) — `AGENTS.md` Rule 18 ;
- **pas de magic string domain literal comparé directement** (ex: `label !== 'ValidateProto'` — extraire en constante nommée ou `enum`) — `AGENTS.md` Rule 49 ;
- **pas de fausse séparation de groupe d'imports** (ligne vide entre deux imports du même groupe) — `AGENTS.md` Section 1 ;
- **interfaces toujours préfixées `I`** (jamais `T`) — `AGENTS.md` §2 Naming Conventions ;
- **pas de type objet anonyme inline dans une signature de fonction exportée** (extraire en `interface` dans `.model.ts`) — `AGENTS.md` Rule 50 ;
- **pas de logique de parsing/splitting dupliquée** — avant d'écrire `lastIndexOf('.') + slice` ou `split(sep)[index]` inline, chercher un helper existant et le réutiliser — `AGENTS.md` Rule 51 ;
- **pas d'utilisation de helpers orientés fichier (`getBasename`, `getExtension`) sur des noms de dossiers** — ces helpers traitent les points comme des séparateurs d'extension — `AGENTS.md` Rule 52 ;
- **pas de propriétés explicites avant un spread dans un objet littéral** — toujours utiliser l'ordre spread-first : `{ ...obj, key: value }` — `AGENTS.md` Rule 53 ;
- **fichiers `.model.ts` placés dans le répertoire `models/` centralisé** — ne jamais co-localiser un `.model.ts` avec un composant UI — `AGENTS.md` Rule 54 ;
- **types, interfaces et enums jamais exportés depuis un `.helper.ts`** — `AGENTS.md` Rule 19 ;
- **imports relatifs évité quand un alias de workspace est disponible** — `AGENTS.md` Section 1 ;
- **ordre d'import respecté** : Angular → Third-party → Internal alias → Relative, avec ligne vide de séparation — `AGENTS.md` Section 1 ;
- respect des patterns et architectures du projet ;
- cohérence avec le code environnant.

### 6. Complexité

- fonctions ou méthodes trop longues ;
- complexité cyclomatique élevée ;
- nesting excessif ;
- responsabilités multiples dans une même fonction ;
- code difficile à tester.

### 6bis. Deep Modules (complexité d'interface)

Pour chaque module touché par le diff, poser la question : « **L'interface de
ce module expose-t-elle une complexité disproportionnée par rapport aux
comportements qu'elle encapsule ?** »

Examiner : dépendances visibles depuis l'extérieur, stabilité du contrat (API
consommées ailleurs), cohésion des responsabilités, testabilité aux frontières.

Jugement qualitatif — **pas de seuil universel**, **pas de refonte
automatique** : un constat produit un commentaire argumenté
(`suggestion:` ou `thought:`, interface alternative proposée en option),
jamais une exigence de réécriture. Une interface large mais justifiée par ce
qu'elle masque est correcte.

### 7. Gestion des erreurs

- cas limites non gérés ;
- erreurs silencieuses ;
- messages d'erreur peu explicites ;
- absence de fallback ou de recovery ;
- promises sans catch / observables sans gestion d'erreur.

### 8. Typage TypeScript

- utilisation de `any` non justifiée ;
- **assertions de type (`as`) manuelles** — vérifier systematically `AGENTS.md` Rule 23 : ne jamais caster avec `as` quand un type propre existe. Si un `as` est détecté dans le diff, c'est un **BLOCKER**. Exception : cast de type discriminant dans un `switch` avec narrowing explicite et type désambiguïsé.
- **non-null assertion (`!`)** — vérifier `AGENTS.md` Rule 22 : chaque `!` sur une valeur optionnelle doit être remplacée par un guard `if` explicite ou du optional chaining (`?.`). Si un `!` est détecté, c'est un **BLOCKER**.
- nullability mal gérée ;
- types implicites qui devraient être explicites ;
- interfaces/types dupliqués ;
- **`Record<string, unknown>`** — vérifier `AGENTS.md` Rule 16 : préférer un `interface` ou `type` concret. Si détecté, **BLOCKER**.

### 9. Performances

- re-renders inutiles (Angular/React/Vue) ;
- calculs répétés pouvant être mis en cache ;
- signaux/computed mal utilisés ;
- **appels de méthodes depuis le template qui recalculent un state dérivé à chaque cycle de détection** (doit être un `computed()` signal) — `AGENTS.md` Rule 37 ;
- allocations mémoire inutiles ;
- requêtes redondantes ;
- listes sans virtualisation si volumineuses.

### 9bis. Typage TypeScript — spécifique au diff

En plus des règles générales :
- **`export type X = 'a' | 'b' | 'c'`** détecté dans le diff → vérifier s'il ne doit pas être un `enum` dans un fichier `.model.ts` — `AGENTS.md` Rule 40 ;
- **`!== undefined` ou `=== undefined` sans `null`** détecté à des endroits où une valeur peut être `null` ou `undefined` → proposer `!isNullish()` / `isNullish()` — `AGENTS.md` Rule 39 ;
- **truthiness check `value &&` ou `value && value !== ''`** pour détecter null/undefined → utiliser `!isNullish(value)` à la place — `AGENTS.md` Rule 39 ;
- tout nouveau fichier `.helper.ts` du diff exportant `interface`, `type` ou `enum` doit être signalé comme incohérent avec la séparation `.model.ts` / `.helper.ts` — `AGENTS.md` Rule 19 ;
- **`of(undefined)` ou `return EMPTY` suivi de `tap(dispatch(NotifyError))` dans un fichier `.state.ts`** → error swallowing déguisé, doit produire un `throwError` — `AGENTS.md` Rule 41 ;
- **`split(...)[0] ?? ...` ou `match(...)?.[0] ?? ...`** dans le diff → le `??` est un dead fallback, à supprimer — `AGENTS.md` Rule 42 ;
- **`as never` ou `as unknown as T`** dans le diff (tests compris) → double cast interdit, construire un `Partial<T>` typé — `AGENTS.md` Rule 43 ;
- **`JSON.parse(JSON.stringify(...))` dans un fichier non-`.spec.ts`** ou `eslint-disable` justifié par jsdom → code de production contraint par l'env de test, BLOCKER — `AGENTS.md` Rule 44.
- **`[ikTooltip]`, `[attr.aria-label]`, `label=`, `placeholder=` non pipés via `transloco`** dans un `.html` du diff → attribut user-facing sans i18n, BLOCKER — `AGENTS.md` Rule 18 ;
- **`=== 'PascalCase'` ou `!== 'PascalCase'`** dans un `.ts` du diff → magic string domain literal, extraire en constante nommée ou `enum` — `AGENTS.md` Rule 49 ;
- **ligne vide entre deux imports du même groupe** (ex: deux imports relatifs séparés par une ligne vide) → fausse séparation de groupe, BLOCKER — `AGENTS.md` Section 1.
- **`interface TName` au lieu de `interface IName`** dans un `.ts` du diff → interface avec préfixe `T` au lieu de `I`, renommer — `AGENTS.md` §2.
- **`{{ 'texte' }}` ou `{{ "texte" }}` sans `| transloco`** dans un `.html` du diff → interpolation user-facing sans i18n, BLOCKER — `AGENTS.md` Rule 18.
- **`export function fn(...): { key: T; ... }[]`** dans un `.ts` du diff → type objet anonyme inline en signature, extraire en `interface` dans `.model.ts` — `AGENTS.md` Rule 50.
- **`.subscribe(` non précédé de `takeUntilDestroyed`** dans un `.ts` du diff → subscription sans gestion du lifecycle, BLOCKER — `AGENTS.md` Rule 3.
- **`?? 'lowercase-string'` ou `=== 'lowercase-string'`** dans un `.ts` du diff → magic string domain literal en lowercase, extraire en constante nommée — `AGENTS.md` Rule 49 (extended).
- **`Validators.minLength(1)`** dans un `.ts` du diff → redondant avec `Validators.required`, supprimer — simplification.
- **fichier `.model.ts` hors d'un répertoire `models/`** → co-localisation avec composant, déplacer dans le `models/` centralisé — `AGENTS.md` Rule 54.
- **`{ key: value, ...obj }`** dans un `.ts` du diff → spread order trompeur, inverser en `{ ...obj, key: value }` — `AGENTS.md` Rule 53.
- **`lastIndexOf('.') + slice` ou `split(sep)[index]` inline** dans un `.ts` du diff → duplique potentiellement un helper existant, chercher et réutiliser — `AGENTS.md` Rule 51.

### 10. Risques de régression

- modifications pouvant impacter d'autres parties du code ;
- suppression de code qui semble mort mais pourrait être utilisé dynamiquement ;
- changements de comportement non intentionnels ;
- absence de tests couvrant le périmètre modifié ;
- **changement de contrat sur un helper/utilitaire partagé** (ex: `@shared/helpers/*`) — pour tout diff modifiant un fichier sous `src/app/shared/`, énumérer tous les importateurs via `rg "from.*<helper-path>"` et vérifier qu'aucun consommateur ne repose sur le comportement modifié. Si la modification change une condition, une valeur de retour, ou le branchement d'un `return` (ex: ajout d'un `if (disabled) return null` dans un validator), l'inscrire comme point de discussion MR et vérifier les tests des consommateurs.

### 11. Cohérence des noms

- noms de variables/fonctions/classes non explicites ;
- incohérence entre le nom et la responsabilité ;
- termes métier incorrectement utilisés.

### 12. Accessibilité (composants UI uniquement)

- attributs ARIA manquants ou incorrects ;
- navigation au clavier non fonctionnelle ;
- contraste insuffisant ;
- structures HTML non sémantiques ;
- messages de statut non annoncés aux lecteurs d'écran.

### 13. Sécurité

- injections possibles (XSS, SQL, etc.) ;
- validation des entrées utilisateur insuffisante ;
- données sensibles exposées ;
- permissions ou authentification mal gérées ;
- utilisation de fonctions dangereuses (`eval`, `innerHTML`, etc.).

### 14. Code temporaire

- TODO/FIXME oubliés ;
- code commenté non supprimé ;
- débogage (`console.log`, `debugger`) laissé en place.

### 15. Réutilisation et séparation des responsabilités

- opportunités d'utiliser des helpers/services existants ;
- **logique de parsing/splitting dupliquée** — avant d'écrire `lastIndexOf('.') + slice` ou `split(sep)[index]` inline, chercher un helper existant (`getBasename`, `getExtension`, `formatBytes`) et le réutiliser — `AGENTS.md` Rule 51 ;
- **helpers orientés fichier utilisés sur des noms de dossiers** — `getBasename`, `getExtension`, `stripExtension` traitent les points comme des séparateurs d'extension ; ne pas les utiliser sur des noms de dossiers — `AGENTS.md` Rule 52 ;
- logique pouvant être déplacée dans un utilitaire partagé ;
- duplication avec du code déjà présent dans une autre partie du projet ;
- fonctions **pures et stateless** (formatage, groupement, agrégation, mapping) encore logées dans des `.component.ts` — doivent être extraites dans un `.helper.ts` dédié ;
- interfaces/types/enum définis dans des fichiers `.service.ts` ou `.component.ts` au lieu de `.model.ts` ;
- **fichiers `.model.ts` co-localisés avec des composants** au lieu d'être dans le répertoire `models/` centralisé — `AGENTS.md` Rule 54.

## Commandes d'utilisation

```
"faire une revue pré-MR"
"review de qualité avant merge"
"pré-review des changements"
"revue pré-MR mode avancé"
"review complète avant merge sur master/develop"
"qualité du code avant MR"

# Avec branche de référence explicite
"pré-review par rapport à origin/develop"
"revue pré-MR compare avec main"
"review qualité avant merge, branche de base: origin/staging"
```

## Processus d'exécution

1. Détecter le mode (standard par défaut, avancé si demandé explicitement).
2. **Déterminer la branche de référence** : utiliser celle spécifiée par l'utilisateur s'il en a indiqué une, sinon détecter automatiquement la **branche parent réelle** via l'algorithme de merge-base le plus récent (voir section "Détermination de la branche de référence"). Cet algorithme parcourt toutes les branches locales et distantes, trouve celle dont le merge-base avec HEAD est le plus récent tout en garantissant que HEAD a des commits d'avance (pour exclure les branches enfants). Générer le diff exact avec `git diff <merge-base>..HEAD`. **Si la branche détectée ne correspond pas à la branche parent attendue, demander à l'utilisateur de confirmer.**
3. **Scan de conformité `AGENTS.md`** : exécuter impérativement les commandes de scan rapide des patterns critiques (non-null assertions `!`, casts `as` (incluant `as never` et `as unknown as`), `whitespace-pre-line`, empty catch, `Record<string, unknown>`, speculative infrastructure, directive internal APIs, `::ng-deep`, `localeCompare` sur dates, `NO_ERRORS_SCHEMA`, logique métier dans composants, `string` élargi pour des unions, composant testé manquant, **appels de méthodes depuis le template**, **`input(undefined)` redondant**, **`isNullish` manquant ou truthiness check (`value &&`)**, **types/enums dans `.helper.ts`**, **string union type au lieu d'enum**, **error swallowing `of(undefined)` dans NGXS**, **dead `??` fallback**, **`JSON.parse(JSON.stringify())` contraint par env de test**, **attribut ou interpolation user-facing sans `transloco`**, **magic string domain literal**, **fausse séparation de groupe d'imports**, **interface avec préfixe `T`**, **type objet anonyme inline en signature**, **subscription sans `takeUntilDestroyed`**, **magic string domain literal en lowercase**, **`Validators.minLength(1)` redondant**, **fichier `.model.ts` hors `models/`**, **spread order trompeur**) sur le diff généré en 2. **Bloquer immédiatement** si un BLOCKER est détecté : l'agent doit corriger avant toute autre vérification.
4. Inspecter les fichiers ajoutés, modifiés et supprimés.
5. Pour chaque fichier, appliquer les vérifications appropriées au mode actif.
6. Proposer et appliquer directement les améliorations pertinentes (avec confirmation si changement risqué).
7. Générer le récapitulatif final incluant :
   - la branche de référence utilisée,
   - le statut de conformité AGENTS.md (BLOCKERS éventuels et corrections appliquées).

## Notes

- Toujours préserver le comportement fonctionnel existant.
- En cas de doute sur une suppression ou modification, demander confirmation.
- Le mode avancé peut être long sur de gros périmètres ; privilégier une analyse incrémentale si nécessaire.
- Les deux modes doivent vérifier la présence de tests et suggérer leur ajout si le périmètre modifié n'en a pas.
