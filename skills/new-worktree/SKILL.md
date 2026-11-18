---
name: new-worktree
description: Create a Git branch and its worktree in one step from a simple intent like "feat podcast Gestion des formulaires et config dynamique", "feat trello-EX12345" or "fix rm-1234". Translates the description to English, composes the branch name (<type>/<context>--<description>), detects the base branch automatically (no hardcoding), reuses existing branch/worktree instead of duplicating. Orca native mode (default): creates the worktree via `orca worktree create --agent` so a new chat linked to the worktree opens in Orca; Git fallback (<repo>.worktrees/) when Orca is unavailable. Never destructive. Trigger on "new-worktree", "worktree", "nouveau worktree", "créer une branche", "branche + worktree", "create branch and worktree", "environnement isolé", "isolate work in a worktree".
---

# New Worktree — branche + worktree en une intention

Transforme une intention minimale (`feat podcast Gestion des formulaires...`) en
**branche Git nommée selon convention + worktree prêt à travailler**, sans
que l'utilisateur ait à fournir le nom complet, la traduction, le nom ou le
chemin du worktree.

**Mode Orca natif (défaut)** : quand le runtime Orca est joignable, le worktree
est créé via `orca worktree create --agent` — un **nouveau chat lié au worktree**
apparaît dans Orca (sidebar), prêt à recevoir la tâche. **Fallback Git** (layout
`<repo>.worktrees/`) quand Orca est absent, fermé ou en échec : le skill ne
dépend jamais d'Orca pour réussir.

**Requires** : `git`, `python3` (stdlib uniquement — aucune dépendance). Orca
facultatif (détection automatique).

## Nature

Skill **global** (comme `create-mr`) : installé dans la configuration globale
OpenCode, jamais copié dans les dépôts. Le script détermine tout lui-même
(repo, remote, base, chemins) depuis le répertoire courant.

## Invocation utilisateur

```text
<skill> new-worktree feat podcast Gestion des formulaires et config dynamique
<skill> new-worktree feat trello-EX12345
<skill> new-worktree fix rm-1234
<skill> new-worktree fix rm-1234 Corriger le chargement infini des playlists
```

Format : `<type> <contexte> [description]` — c'est tout. L'agent fait le reste.

## Procédure

### 1. Parser l'intention

| Token | Rôle | Exemples |
|-------|------|----------|
| 1er token | type de branche | `feat`, `fix`, `refactor`, `chore`, `docs`, `test`... |
| 2e token | contexte principal ou identifiant — **conservé tel quel** (casse incluse) | `podcast`, `trello-EX12345`, `rm-1234` |
| reste | description fonctionnelle — à traduire en anglais | `Gestion des formulaires et config dynamique` |

Si l'utilisateur fournit directement un nom de branche complet (contient `/`),
passer en mode `--branch` (passthrough).

### 2. Traduire la description (si nécessaire)

Règles de génération de la description anglaise :

1. **FR → EN** si français ; **si déjà en anglais : ne pas retraduire**, passer tel quel.
2. **Naturelle et concise** — formulation qu'un dev anglais écrirait, pas une
   traduction littérale : « chargement infini des playlists » →
   `infinite playlist loading` (PAS `loading infinity of playlists`).
3. Garder le **sens fonctionnel**, supprimer les mots inutiles (articles,
   verbes génériques type « gérer/permets »).
4. Pas d'accents, d'apostrophes ni de ponctuation dans le résultat final.
5. Le script slugifie déjà (accents, apostrophes, ponctuation → `-`, lowercase)
   — l'agent fournit des mots, pas du kebab.

Exemples validés :

| Description fournie | Description anglaise retenue |
|---------------------|------------------------------|
| `Gestion des formulaires et config dynamique` | `dynamic form and config management` |
| `Corriger le chargement infini des playlists` | `fix infinite playlist loading` |
| `Dynamic configuration management` | `dynamic configuration management` (inchangé) |
| `Ajouter l'export CSV des épisodes` | `add csv export for episodes` |

### 3. Appeler le script (partie déterministe)

Le chemin du script : `<skill_dir>/new_worktree.py`.

```bash
# contexte + description (description DÉJÀ traduite en anglais par l'agent)
python3 "<skill_dir>/new_worktree.py" --type feat --context podcast \
  --desc "dynamic form and config management"

# identifiant seul (pas de description -> pas de « -- »)
python3 "<skill_dir>/new_worktree.py" --type feat --context trello-EX12345

# identifiant + description
python3 "<skill_dir>/new_worktree.py" --type fix --context rm-1234 \
  --desc "fix infinite playlist loading"

# nom de branche complet (passthrough)
python3 "<skill_dir>/new_worktree.py" --branch "feat/podcast--dynamic-form-and-config-management"

# aperçu sans création (aucune mutation)
python3 "<skill_dir>/new_worktree.py" --type feat --context podcast --desc "..." --dry-run
```

Options utiles : `--base <name>` (forcer la branche de base), `--remote <name>`
(multi-remotes), `--repo <path>` (défaut : cwd — fonctionne depuis un
sous-dossier), `--list` (lister les worktrees du dépôt), `--prompt <brief>`
(brief initial du chat lié — mode Orca), `--orca-agent <id>` (défaut
`opencode`, surchargeable par `NW_ORCA_AGENT`), `--no-orca` (forcer le mode
Git). Variables d'environnement : `NW_ORCA_BIN` (binaire orca, tests).

### 4. Afficher le résultat

Le script produit un bloc compact — l'afficher tel quel à l'utilisateur :

```text
Branch: feat/podcast--dynamic-form-and-config-management
Base: develop
Worktree: /Users/example/orca/workspaces/example-project/feat-podcast--dynamic-form-and-config-management
Chat: structured chat (opened as chat)
Status: created
```

En `--dry-run`, une ligne `Orca:` s'ajoute (`actif` ou `ignoré` + cause) :
elle annonce le mode que la création réelle utilisera.

`Chat` n'apparaît qu'en mode Orca : `kind` de l'agent lancé (chat structuré ou
terminal en fallback) + détail du receipt. En fallback Git, le bloc est celui
décrit plus bas (`Worktree` sous `<repo>.worktrees/`, pas de ligne `Chat`).

`Status` : `created` (branche + worktree créés) · `branch reused` (branche
existante, worktree créé) · `existing worktree reused` (rien créé, chemin
retourné) · `dry-run` (aperçu). La ligne `Base` n'est affichée que quand la
branche de base est pertinente (création, dry-run) ; un dry-run sur une
branche/worktree existants renvoie `existing worktree reused`.

Suggérer ensuite, selon le mode :
- **Orca natif** : *« Le worktree et son chat sont ouverts dans Orca (sidebar) —
  le chat ne prend pas le focus automatiquement. »*
- **Fallback Git** : *« Ouvre ce chemin dans Orca (nouveau panneau de terminal). »*

### 5. Composer le brief du chat lié (mode Orca, tâche immédiate)

Quand le worktree est créé **pour démarrer une tâche tout de suite** (issue,
carte, demande utilisateur), l'agent compose un brief autonome et le passe via
`--prompt` : le nouveau chat reçoit le travail initial. Le brief doit être
auto-suffisant — le chat ne voit PAS la conversation courante : objectif,
contexte du projet, contraintes, critères de succès. Si le worktree est créé
« à vide » (préparation), omettre `--prompt` : le chat s'ouvre vide, lié au
worktree, et attend les instructions.

## Convention de nommage des branches

```text
<type>/<contexte>                # identifiant seul, casse conservée
<type>/<contexte>--<description> # avec description en kebab-case anglais
```

- séparateur type/contexte : `/` — séparateur contexte/description : `--`
- identifiants (`trello-EX12345`, `rm-1234`) : **casse préservée**, jamais reformattés
- description : kebab-case lowercase, sans accents/apostrophes/ponctuation
- le script slugifie tout ce qui est non-alphanumérique (le `/` d'un contexte
  multi-mots devient `-`, jamais une arborescence involontaire)
- branche > 100 chars : description tronquée + suffixe digest 8 chars (unicité)

## Branche de base — jamais hardcodée

Ordre de détection (chaque candidat est **validé** avant d'être retenu) :

1. `--base` explicite si fourni
2. symref locale `refs/remotes/<remote>/HEAD` (origin/HEAD — instantané, réseau non requis)
3. `git ls-remote --symref <remote> HEAD` (réseau, universel GitLab/GitHub)
4. `glab repo view --output json` → `default_branch` (GitLab, même logique que `create-mr`)
5. fallback local dans cet ordre : `develop` → `main` → `master` (convention
   organisation : `develop` = branche d'intégration)
6. en dernier recours : HEAD courant

Cela évite de créer une branche depuis une feature branch qui serait checkout
au moment de l'exécution. `git fetch <remote> --prune` est exécuté avant les
vérifications ; **un remote inaccessible n'est pas bloquant** (warning +
références locales).

## Convention des worktrees — deux layouts

### Mode Orca natif (défaut, runtime joignable)

```text
~/orca/workspaces/<repo>/<branche-avec-/-remplacé-par-->   # chemin géré par Orca
```

Création déléguée à `orca worktree create --repo name:<repo> --name <slug>
--branch <branche> --agent <agent> [--base-branch <base>] [--prompt <brief>]
--json` — Orca place le worktree, lance l'agent **sous forme de chat lié au
worktree** (selon le choix Chat | CLI de l'utilisateur pour cet agent) et le
receipt dit lequel (`launch.outcome.kind`). La branche de base détectée par le
skill est transmise via `--base-branch` (jamais de base hardcodée par Orca) —
seule exception : quand aucune base n'est détectable (`HEAD`), `--base-branch`
est omis et Orca applique sa base par défaut.

### Mode Git (fallback : `--no-orca`, orca absent, runtime fermé, échec orca)

```text
<parent-du-repo>/<repo>.worktrees/<branche-avec-/-remplacé-par-->
```

Exemple — repo `/Users/example/dev/example-project`, branche
`fix/rm-1234--fix-infinite-playlist-loading` :

```text
/Users/example/dev/example-project.worktrees/fix-rm-1234--fix-infinite-playlist-loading
```

Pourquoi ce choix :

- **projet identifiable** : le dossier `*.worktrees` est sibling du repo, préfixé du même nom
- **branche identifiable** : mapping déterministe branche → dossier (`/` → `-`)
- **hors du repo** : aucun `.gitignore` à modifier, aucune imbrication de dépôt,
  pas de confusion pour les outils qui scannent `~/dev`
- **Orca-compatible** : Orca identifie ses worktrees par ID interne
  (`ORCA_WORKTREE_ID` par terminal), pas par convention de chemin — tout
  dossier git s'ouvre comme workspace et est découvert/indexé par Orca
- distinct du skill OMO `worktrees` (lanes d'agents sous `.slim/worktrees/`,
  usage orchestrator — ne pas mélanger les deux conventions)

Les deux layouts produisent des worktrees Git ordinaires : la réutilisation
(`worktree_for_branch`) et le listage (`--list`) les voient tous les deux.

## Robustesse (cas gérés par le script)

| Cas | Comportement |
|-----|--------------|
| invocation depuis un sous-dossier | repo résolu via `git rev-parse` |
| invocation depuis un worktree existant | repo **principal** résolu (`.git-common-dir`) |
| plusieurs remotes | `origin` prioritaire, sinon premier remote ; `--remote` pour forcer |
| aucun remote | fetch sauté, base détectée en local |
| remote inaccessible | warning, poursuite avec les refs locales |
| branche déjà en local | branche réutilisée (`branch reused`), jamais recréée |
| branche uniquement sur remote | branche locale créée par DWIM depuis `origin/<branche>` |
| worktree déjà présent | statut `existing worktree reused` + chemin retourné |
| dépôt dirty (modifs non commitées) | sans effet sur `git worktree add` — pas de stash/reset/clean |
| nom trop long | troncature + digest (unicité garantie) |
| accents/apostrophes/ponctuation | slugify NFKD (é → e, `'` → supprimé, ponctuation → `-`) |
| majuscules dans identifiants | conservées |
| description déjà en anglais | pas de retraduction (responsabilité agent, étape 2) |
| chemin du worktree déjà pris (non-worktree) | erreur propre — jamais de suppression |
| branche checkout dans un autre worktree | ce worktree est réutilisé (jamais de conflit) |
| dossier du worktree supprimé manuellement (sans prune) | erreur Git `already used by worktree` — résolution manuelle uniquement : recréer le dossier ou demander à l'utilisateur un `git worktree prune` explicite |
| orca CLI absent (`NW_ORCA_BIN` introuvable) | warning + création Git classique (jamais bloquant) |
| runtime Orca fermé (`orca status` injoignable) | warning + création Git classique |
| `orca worktree create` en échec (sélecteur, repo non indexé...) | warning avec la cause lisible + création Git classique |
| `orca worktree create` en timeout (180 s) | warning « résultat incertain » + bascule Git : la branche créée entre-temps est réutilisée (jamais de doublon) |
| réponse orca illisible (JSON attendu, `ok`, chemin manquant) | warning + création Git classique |
| `--prompt` fourni mais bascule Git | warning `--prompt ignoré` (pas de chat lié en Git) |
| worktree déjà créé par Orca (même branche) | détecté par `git worktree list` → `existing worktree reused` |
| dépôt bare | supporté — worktree sous `<parent>/<nom-sans-.git>.worktrees/` |
| dépôt sans aucun commit | erreur claire — créer un commit initial d'abord |
| submodule / `--separate-git-dir` | repo principal résolu via `--git-dir` vs `--git-common-dir` |

## Règles de sécurité (règles dures)

- **Jamais** : `git reset`, `git clean`, `git stash`, `git branch -D`,
  `git worktree remove`, `git worktree prune`, `git checkout` dans le repo
  principal, force-push.
- Le script ne fait que : fetch, lectures de refs, `git worktree add`, création
  de dossiers — et réutilise tout ce qui existe déjà.
- En cas de conflit (chemin pris, état inattendu) : erreur propre + action
  manuelle suggérée à l'utilisateur, jamais de résolution automatique
  destructive.

## Anti-patterns

- Passer une description française au script (la traduction est l'étape 2 de l'agent).
- Passer du kebab-case dans `--desc` (donner des mots, le script slugifie).
- Hardcoder `main`/`master`/`develop` au lieu de laisser la détection agir.
- Oublier `--prompt` quand le worktree est créé pour démarrer une tâche
  immédiatement (le chat lié s'ouvrirait vide).
- Utiliser ce skill pour des lanes d'agents parallèles → skill OMO `worktrees`.
- Créer un worktree manuellement avec `git worktree add` au lieu du script
  (perte de la convention de chemin, du chat lié et des vérifications).
- Court-circuiter le fallback : si Orca échoue, la création Git est le
  comportement attendu, pas une erreur.

## Tests

```bash
python3 -m unittest discover -s skills/new-worktree/tests -v
```

Couverture : les 5 scénarios de nommage canoniques + slugify (accents,
apostrophes, ponctuation, casse, longueur) + e2e git sur dépôts temporaires
(création, réutilisations, remote-only, sans remote, sous-dossier, dépôt dirty,
collision de chemin, dry-run) + e2e orca via fixture `fake_orca.sh` (création +
chat lié, flags transmis, fallbacks runtime/échec/réponse, `--no-orca`,
réutilisation prioritaire sans appel orca, dry-run).

Herméticité : `GitFixture` épingle `NW_ORCA_BIN` sur un binaire inexistant —
aucun test ne touche un Orca réel ; la classe `OrcaFixture` branche la fixture.
