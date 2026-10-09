---
name: mr-review
description: Review a GitLab MR and post inline conventional comments on code lines. Use when the user gives a GitLab MR URL or asks to review an MR. Analyzes the diff, delegates to Oracle for adversarial review, and posts structured inline comments using Conventional Comments format (issue:, suggestion:, nitpick:, question:, thought:, praise:).
---

# MR Review — Inline Conventional Comments

Review a GitLab merge request and post inline comments directly on the code lines
using the Conventional Comments convention.

**Requires**: GitLab CLI (`glab`) authenticated and available.

## Nature

Ce skill est **global**. Il est installé dans la configuration globale de
l'utilisateur OpenCode et n'est jamais copié dans les dépôts.

## Prerequisites

```bash
command -v glab
glab auth status
```

If `glab` is not authenticated, stop and ask the user to run `glab auth login`.

## Process

### Step 1: Parse the MR URL and extract metadata

The user provides a GitLab MR URL or an MR number. Extract:

- **Project**: `acme-group/acme-app` (or from URL)
- **MR IID**: from URL or argument

```bash
# If URL: https://gitlab.example.com/acme-group/acme-app/-/merge_requests/123
# Extract project and IID
```

Fetch MR metadata:

```bash
glab api "projects/${PROJECT_ENCODED}/merge_requests/${MR_IID}" \
  | jq '{source_branch: .source_branch, sha: .sha, base_sha: .diff_refs.base_sha, head_sha: .diff_refs.head_sha, start_sha: .diff_refs.start_sha}'
```

### Step 2: Fetch the MR diff

```bash
glab mr diff ${MR_IID} --repo ${PROJECT_PATH}
```

### Step 3: Read AGENTS.md and detect tooling-enforced rules

If the target project contains an `AGENTS.md`, read it to extract the coding
rules that apply to the review. This is critical — the review must be based on
the project's actual conventions, not generic best practices.

**Tooling detection** (critical to avoid false positives): Before applying
AGENTS.md rules, check the project for tooling that already enforces them
automatically. Rules already enforced by tooling must NOT be flagged in review.

Check for:
- **ESLint**: `.eslintrc.*`, `eslint.config.*` — import ordering, naming
  conventions, type safety rules
- **Prettier**: `.prettierrc*` — formatting rules
- **Stylelint**: `.stylelintrc*` — CSS/SCSS linting rules
- **EditorConfig**: `.editorconfig` — indentation, line endings
- **Angular CLI schematics**: `angular.json` — prefix enforcement, file naming

If a rule from AGENTS.md is already enforced by ESLint/Prettier or another
linter, exclude it from the review scope. Commenting on something that the
tooling already handles wastes the author's time and generates noise.

### Step 4: Delegate to Oracle for adversarial review

Delegate the diff analysis to the `oracle` subagent with:
- The full diff text
- A summary of the AGENTS.md rules to check against
- Instruction to return a structured list of findings

The Oracle prompt must:
- Ask for findings with: file path, line number, severity (issue/suggestion/nitpick),
  description, recommendation, and AGENTS.md rule reference if applicable.
- Enforce the Conventional Comments prefixes: `issue:`, `suggestion:`, `nitpick:`,
  `question:`, `thought:`, `praise:`.
- NOT rubber-stamp. Find real problems.
- Justify every comment (explain the "why").
- Propose concrete solutions or alternatives.
- Tous les commentaires DOIVENT être rédigés en français. Les préfixes Conventional Comments
  (`issue:`, `suggestion:`, `nitpick:`, `question:`, `thought:`, `praise:`) restent en anglais,
  mais tout le texte descriptif, les explications, les justifications et les solutions proposées
  doivent être en français.

The Oracle prompt MUST include the following anti-patterns as hard filters.
Oracle DOIT appliquer ces filtres pendant l'analyse et ne pas inclure les
findings correspondants dans sa réponse. L'orchestrateur DOIT également
vérifier chaque finding restant avant publication.

#### Anti-patterns to avoid (false positive filters)

**AP1 — Tooling déjà en place** (filet de sécurité — l'orchestrateur filtre
déjà ces règles dans Step 3, mais si un finding tooling-related passe malgré
tout, le supprimer)
Si une règle AGENTS.md est déjà enforced par un linter (ESLint, Prettier,
Stylelint, etc.), ne pas la vérifier. Exemple: l'ordre des imports est géré par
ESLint → ne pas commenter l'ordre des imports.

**AP2 — Scope export vs interne**
Une règle sur les interfaces/types/fichiers `.model.ts` (Angular) ou équivalent
ne s'applique que si l'élément est **exporté**. Un type interne non exporté,
utilisé uniquement dans le fichier où il est défini, peut rester colocalisé.
Exemple (Angular) : une interface dans un `.model.ts` non exportée.
Exemple (générique) : une interface locale à un fichier, non exportée, utilisée
uniquement dans ce fichier. Ne pas flagger un type interne pour violation de
règle de placement de fichier.

**AP3 — Terminologie métier**
Ne pas appliquer aveuglément une règle de traduction ou de naming à un terme
qui est utilisé tel quel dans le vocabulaire métier du domaine. Les termes
techniques métier (ex: "player", "playback" en VOD) peuvent être conservés en
anglais même si une règle générale exige le français. Vérifier le contexte
domaine avant de flagger.

**AP4 — Théorie des types vs contexte runtime**
Ne pas flagger un issue de type basé sur une signature TypeScript large si le
contexte d'usage garantit un type plus précis. Critères vérifiables
statiquement : (a) le type est narrowing par un type guard ou assertion
function visible dans le diff, (b) la signature de l'API/framework appelée
garantit le type (ex: Chart.js garantit `number` pour `context.parsed` quand
`type: 'pie'`), ou (c) un literal type union qui exclut les autres cas.
Exemple: Chart.js type `context.parsed` comme `number | number[] | null |
undefined`, mais pour un chart type `pie` le runtime garantit `number`.

**AP5 — Visibilité codebase (validation gérée ailleurs)**
Avant de flagger une validation, cohérence ou garde manquante, vérifier si elle
n'est pas déjà gérée ailleurs dans le codebase (autre composant, service, guard,
intercepteur, resolver). Si la validation est déléguée à un autre endroit du
flux, ne pas flagger son absence locale.

Ce filtre est appliqué par l'**orchestrateur** (pas Oracle) : après réception
des findings d'Oracle, l'orchestrateur exécute `grep` sur le codebase pour
vérifier si la validation existe ailleurs. Si oui, le finding est supprimé
avant publication.

Exemple : validation d'email déjà gérée par un guard Angular → ne pas flagger
l'absence de validation dans le composant qui reçoit la data. Contre-exemple :
aucune validation d'email nulle part → flagger normalement.

### Step 5: Map findings to exact line numbers

For each finding from Oracle, fetch the file content at the MR head SHA to get
the exact line number:

```bash
glab api "projects/${PROJECT_ENCODED}/repository/files/${FILE_PATH_ENCODED}/raw?ref=${HEAD_SHA}"
```

Use `cat -n` or manual counting to find the exact line. The line must exist in
the diff (new_line) for the inline comment to anchor correctly.

### Step 6: Post inline comments via GitLab API

Post each comment as a discussion thread with a `position` object so it anchors
to the code line in the diff view.

**Critical**: `glab api -f` does not serialize nested objects correctly. Use
`--input` with a JSON payload file.

```bash
cat > /tmp/comment_payload.json << 'ENDJSON'
{
  "body": "issue: description du problème en français.\n\nExplanation...\n\n```typescript\n// code example\n```",
  "position": {
    "base_sha": "${BASE_SHA}",
    "head_sha": "${HEAD_SHA}",
    "start_sha": "${START_SHA}",
    "position_type": "text",
    "new_path": "${FILE_PATH}",
    "new_line": ${LINE_NUMBER}
  }
}
ENDJSON

glab api --method POST \
  "projects/${PROJECT_ENCODED}/merge_requests/${MR_IID}/discussions" \
  --input /tmp/comment_payload.json \
  -H "Content-Type: application/json"
```

### Step 7: Verify all comments are inline

After posting, verify each discussion has a `position` set:

```bash
glab api "projects/${PROJECT_ENCODED}/merge_requests/${MR_IID}/discussions" \
  | jq '[.[] | .notes[0] | {has_position: (.position != null), file: .position.new_path, line: .position.new_line}]'
```

If a comment was posted without a position (fallback to plain note), delete it
and retry with the JSON payload method.

### Step 8: Report to the user

Display a summary table:

```
| # | Préfixe | Fichier | Ligne |
|---|---------|--------|-------|
| 1 | issue: | path/to/file.ts | 42 |
| 2 | suggestion: | path/to/other.ts | 15 |
```

## Conventional Comments Format

All comments MUST use one of these prefixes:

| Prefix | When to use |
|--------|-------------|
| `issue:` | Problem, bug, or error that must be fixed |
| `suggestion:` | Improvement or alternative, non-blocking |
| `nitpick:` | Minor detail or personal preference |
| `question:` | Question about code intent or behavior |
| `thought:` | Reflection or idea related to the code |
| `praise:` | Positive aspect, good practice |

### Comment structure

```
{prefix}: {description concise du problème en français}.

{explication du pourquoi c'est un problème, avec le contexte, en français}

{solution concrète ou alternative, avec exemple de code si pertinent, en français}
```

### Rules

- Formuler des commentaires clairs, concis et précis.
- Adopter un ton respectueux et constructif. Privilégier les suggestions et les
  questions aux affirmations catégoriques.
- Justifier chaque commentaire. Expliquer le "pourquoi".
- Proposer des solutions alternatives concrètes.
- Every comment must be an inline comment anchored to a code line, not a
  general note on the MR.
- Langue : Les préfixes restent en anglais (convention Conventional Comments).
  Tout le reste du commentaire (description, explication, solution, référence
  à la règle) doit être rédigé en français.
- **Anti-patterns** : Appliquer systématiquement les filtres AP1–AP5 décrits
  dans le Step 4. Tout finding correspondant à un anti-pattern doit être
  supprimé avant publication. L'objectif est la qualité sur le signal, pas la
  quantité.

## Error handling

- If `glab api --input` fails (returns non-zero), retry once.
- If a file is not in the diff, the inline comment cannot be anchored — skip it
  and report it as a plain note instead.
- If the diff is empty, report "No changes to review".
- If Oracle returns no findings, report "No issues found" and post a `praise:`
  comment if warranted.
