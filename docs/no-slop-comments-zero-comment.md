---
name: no-slop-comments
description: "Zero-comment default for AI coding agents: code must be self-explanatory — no comments in written code, the only exceptions being mathematical reasoning and complex logic. Also detects and strips AI-slop comments when editing existing code. Use when writing or editing code, comments, JSDoc, docstrings, or TODOs."
allowed-tools: Read Write Edit Glob Grep
---
<!--
Fichier autonome et portable — aucune dépendance au projet Aurora.
Double usage : (1) ce document explique le concept, (2) ce MÊME fichier est le skill.
Installation (1 étape) : copier ce fichier tel quel dans
  ~/.config/opencode/skills/no-slop-comments/SKILL.md
puis redémarrer OpenCode. C'est tout.
-->
# no-slop-comments — zéro commentaire par défaut

> Système portable d'hygiène des commentaires de code pour agents de codage IA (OpenCode, Claude Code, Cursor, Copilot Workspace…). Le code écrit par un agent ne doit contenir **aucun commentaire**, sauf deux exceptions fermées : le raisonnement mathématique et l'intent de logique complexe.

## 1. Le problème

Les modèles de langage génèrent des commentaires par habitude d'entraînement : ils narrent le code au lieu de l'expliquer. Ces commentaires sont du bruit :

- ils **doublent la charge de lecture** sans rien apporter (le code dit déjà la même chose) ;
- ils **pourrissent** — le code évolue, le commentaire reste faux ;
- ils **trahissent la génération IA** (bannières décoratives, narration en étapes, vocabulaire par défaut ✅🚀) ;
- ils **masquent les rares commentaires utiles** : quand tout est commenté, rien ne l'est.

## 2. Le concept en 4 principes

1. **Zéro par défaut.** Le code est présumé auto-explicite : noms, types, structure, tests. Si un lecteur a besoin d'un commentaire pour comprendre une ligne, la réponse est d'abord un meilleur nom, une extraction de fonction, un type plus précis ou un test — jamais un commentaire.
2. **Un commentaire est une exception à justifier.** La whitelist est fermée : raisonnement mathématique ou intent de logique complexe. Tout le reste est interdit dans le code écrit.
3. **Le « pourquoi » vit hors du code.** Message de commit, description de PR/MR, documentation projet. L'information est déplacée, jamais détruite — un commentaire supprimé dont le fait migre vers le commit n'a rien perdu.
4. **Les conventions locales gagnent.** Un projet qui exige des docstrings, des headers de licence ou des marqueurs generated-code garde ses règles — la règle zéro commentaire ne passe jamais devant l'AGENTS.md / les conventions du projet. Où les repérer : `AGENTS.md` ou `CONTRIBUTING`, la configuration des linters (eslint-plugin-jsdoc, pydocstyle…), la densité de docstrings du module édité — en cas de doute, demander.

## 3. Le contrat de l'agent

Quand l'agent écrit ou édite du code :

- générer **zéro nouveau commentaire** par défaut ;
- tout commentaire en dehors des 2 exceptions est **supprimé à la même occasion** (lors de l'édition de la ligne ou du bloc concerné) ;
- une exception fait **1 ligne, 2 seulement si la seconde porte un fait nouveau** — jamais 3, sauf dérivation mathématique (§4.1) limitée au strict nécessaire ;
- expliquer le **pourquoi, jamais le quoi** ;
- **zéro TODO en commentaire** — une TODO est une tâche, elle va au tracker d'issues ;
- **zéro echo de signature** (JSDoc/docstring qui répète `@param price The price.`) — la documentation de contrat API vit dans la doc projet ;
- ne jamais purger les commentaires du code non touché (pas de refactoring déguisé en nettoyage) ;
- jamais de commentaire pour compenser du code confus — **restructurer le code** à la place.

### Le test en deux questions

Avant d'écrire un commentaire :

1. **C'est du raisonnement mathématique ou de l'intent de logique complexe ?** Non → ne pas écrire.
2. **Un nom, un type, une petite extraction porteraient ça — ou c'est un pourquoi ponctuel pour un commit ou une PR ?** Oui → ne pas écrire. Un fait permanent, lui, vit à côté du code : c'est l'exception §4.2.

Dans le doute → ne pas écrire.

## 4. Les deux exceptions (seuls commentaires autorisés)

### 4.1 Raisonnement mathématique

Dérivation d'une formule, source d'une constante magique, subtilité d'unité ou de précision, borne de complexité — tout ce que la formule cache.

```ts
// 0.2126 / 0.7152 / 0.0722 : poids de luminance linéaire Rec. 709 (ITU-R BT.709).
const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
```

### 4.2 Intent de logique complexe

Invariant non évident, hypothèse d'algorithme, piège comportemental que le code ne peut pas exprimer — un fait qui empêche un vrai bug si le lecteur « simplifie » le code.

```js
// Stripe may retry webhook deliveries for up to three days; duplicates are legal.
```

## 5. Où va le « pourquoi »

| Contenu | Destination |
|---|---|
| Pourquoi ce changement existe | Message de commit |
| Contexte métier, décision d'architecture, alternatives rejetées | Description de PR/MR |
| Décisions durables, contrats | Documentation projet (`docs/`, ADR, `DECISIONS.md`) |
| Constante, seuil, configuration (sauf source mathématique d'une valeur — cf. §4.1) | Une constante **nommée** dans le code (`STRIPE_RETRY_WINDOW_DAYS = 3`) |

## 6. Les patterns interdits (jamais écrire, toujours retirer quand touché)

| Pattern | Exemple | Action |
|---|---|---|
| Séparateur décoratif | `// ===== Auth =====` | Supprimer |
| Répéter le code | `// Initialise la variable` au-dessus de `let count = 0` | Supprimer |
| Narration de workflow | `// Étape 1 : valider`, `// Ensuite…`, `// Enfin…` | Supprimer — si le flux est confus, restructurer le code |
| Label vide | `// Logique métier`, `// Helper`, `// Point d'entrée` | Supprimer |
| TODO vague ou TODO en code | `// TODO: améliorer` | Tracker d'issues |
| Echo de signature | JSDoc `@param price The price.` | Supprimer |
| Emoji décoratif | `// ✅ Validation` | Supprimer |
| Marqueur de fin | `} // end if` | Supprimer |
| Sur-explication | Paragraphe de 4 lignes pour un fait d'une ligne | Réduire au fait seul (1 ligne) ou supprimer |
| Narration ligne à ligne | Un commentaire par instruction | Supprimer tout |
| Ton formel / criard | « Cette fonction est responsable de valider… » | Supprimer |

## 7. Checklist de vérification

À vérifier sur chaque livraison. Toutes les réponses doivent être **oui** :

- [ ] Zéro nouveau commentaire hors exceptions (§4.1/§4.2) écrit ?
- [ ] Tout commentaire restant est-il du raisonnement mathématique ou de l'intent de logique complexe ?
- [ ] Chaque commentaire a-t-il passé le test en deux questions ?
- [ ] 1 ligne (2 max — dérivation mathématique §4.1 : au strict nécessaire), court, naturel ?
- [ ] Chaque « pourquoi » supprimé a-t-il migré vers un endroit durable (commit, PR, doc) ?
- [ ] Zéro TODO en commentaire ?
- [ ] Conventions locales respectées (docstrings exigées, headers de licence, marqueurs generated) ?
- [ ] Aucun commentaire du code non touché purgé ?
- [ ] Le code se suffit à lui-même : noms, types, structure, tests ?

## 8. Installation dans votre OpenCode

**1 étape :**

```bash
mkdir -p ~/.config/opencode/skills/no-slop-comments
cp no-slop-comments-zero-comment.md ~/.config/opencode/skills/no-slop-comments/SKILL.md
```

Redémarrer OpenCode. Rien d'autre : le frontmatter du fichier porte les déclencheurs — OpenCode charge le skill automatiquement quand une tâche écrit ou édite du code, des commentaires, de la JSDoc, des docstrings ou des TODOs (matching sémantique sur la description).

**Câblage renforcé (optionnel)** : si votre setup orchestre des sous-agents (Fixer, commit…), ajoutez l'attente dans votre AGENTS.md ou le prompt d'orchestrateur pour qu'elle voyage dans les briefs :

> Zéro commentaire par défaut dans le code généré — le code doit se suffire à lui-même (noms, types, structure, tests) ; seuls survivent les commentaires de raisonnement mathématique ou de logique complexe (1-2 lignes max ; dérivation mathématique §4.1 : au strict nécessaire). Le « pourquoi » va dans le message de commit, la description de PR ou la doc — jamais en commentaire de code.

## 9. FAQ rapide

- **« Et la documentation d'API ? »** — Elle vit dans la doc projet (README, docs/, générateur de doc). Un docstring qui répète la signature est interdit ; un docstring exigé par les conventions du projet reste suivi (principe 4).
- **« Et les tags JSDoc fonctionnels — @deprecated, @throws, @internal ? »** — Ce sont des métadonnées machine consommées par les outils (IDE, linters, générateurs de doc), pas des commentaires au sens du skill : ils restent sur le symbole.
- **« Un commentaire temporaire pendant le debug ? »** — De même que TODO : jamais commité. Le commentaire de travail se transforme en issue ou disparaît.
- **« Mon collègue écrit encore du code commenté ? »** — La règle lie le code écrit/édité par l'agent. Pour le style humain, la checklist (§7) sert de convention de revue.
- **« D'où vient ce système ? »** — Adapté du projet open-source [anti-slop](https://github.com/miqdadbadjuber/anti-slop) (skills "Code Comments"), durci en default-deny par l'opérateur : la version upstream gardait une whitelist large (« Not a Ban ») qui laissait revenir les commentaires ; l'inversion du défaut est la seule posture qui tient.
