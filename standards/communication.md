# Standard — Communication

## Principes de communication

- **Pas de flatterie artificielle** : ne pas valoriser une solution faible par politesse.
- **Pas de sycophantie** : ne pas dire oui à une mauvaise idée.
- **Ownership des erreurs** : si l'agent commet une erreur, la reconnaître immédiatement et proposer une correction.
- **Pushback constructif** : contredire une demande lorsqu'elle est inefficace, dangereuse, ou violerait les conventions. Expliquer pourquoi.
- **Langue de l'utilisateur** : répondre dans la langue utilisée par l'utilisateur (français si l'utilisateur parle français, anglais si anglais).
- **Solution, pas catalogue** : privilégier la meilleure solution plutôt qu'une liste de solutions équivalentes. Justifier le choix.
- **Maximum une question de clarification** : lorsque l'intention est déductible, proposer la meilleure interprétation et demander confirmation. Eviter de bombarder l'utilisateur de questions.

## Format de sortie markdown

Le markdown produit par l'agent doit être **validement structuré et rendu correctement** par tout parser markdown. Une réponse techniquement correcte mais mal formatée est inutilisable.

### Règles obligatoires

#### Headings

- Respecter la hiérarchie stricte : `#` → `##` → `###` → `####`. Ne **jamais sauter un niveau** (ex: `##` → `####` sans `###`).
- Un seul `#` (H1) par document, en haut. Les sections commencent à `##`.
- Pas de heading vide (`## ` sans texte).
- Pas de `#` en fin de ligne après le texte (`## Titre #` → `## Titre`).
- Préférer les headings ATX (`## Titre`) aux setext (`Titre\n===` ou `Titre\n---`). Les setext entrent en conflit avec les séparateurs `---`.

#### Code blocks

- **Ligne vide obligatoire** avant et après chaque bloc de code (triple backticks).
- Indiquer le langage du bloc : ` ```nginx `, ` ```ts `, ` ```bash `, etc.
- Le code inline (un mot, un identifiant, une valeur) utilise des backticks simples : `` `variable` ``.
- Le code multi-lignes utilise un code block.
- Si le code contient des triple backticks, utiliser des délimiteurs à 4+ backticks : ` ``` ` ` ` ` pour le wrapper.
- Ne **jamais** imbriquer un code block dans un autre sans escalade des délimiteurs.

#### Tableaux

- Un tableau doit **toujours** contenir au moins une ligne de données. Jamais de tableau avec uniquement les headers.
- Aligner les colonnes avec `|` pour la lisibilité du source.
- Garder les tableaux compacts : si une cellule contient une phrase complète, envisager une liste à la place.
- Pour les sauts de ligne dans une cellule, utiliser `<br>` (uniquement dans ce contexte de tableau).
- Pas de tableau dans une cellule de tableau (non supporté par le markdown standard).

#### Listes

- Préférer les listes numérotées (`1.`) pour les étapes ordonnées et les flux de données.
- Préférer les listes à puces (`-`) pour les énumérations non ordonnées.
- **Préférer les listes structurées** aux diagrammes ASCII art (sauf si le diagramme est complexe et apporte une vraie valeur).
- Indentation des sous-listes : **2 espaces** par niveau. Ne jamais mixer espaces et tabulations.
- Une ligne vide n'est pas obligatoire entre items d'une même liste, mais l'est entre une liste et un autre élément block-level.

#### Liens et images

- Liens : format `[texte](url)`. Ne **jamais** laisser une URL brute cliquable si elle peut être un lien.
- Pas de lien sans texte de substitution : `[](url)` est interdit.
- Images : `![texte alternatif](url)` — le alt text est **obligatoire**. Pas de `![](url)`.
- Si l'image est décorative, utiliser `![](url)` avec alt vide est acceptable uniquement dans du contenu HTML, pas en markdown pur.

#### Emphasis

- **Cohérence** : choisir `*` ou `_` pour l'italique/gras dans tout le document. Ne pas mixer.
- Gras : `**texte**`. Italique : `*texte*`.
- Ne pas imbriquer emphasis identiques (`**gras **et italique**` → cassé). Utiliser `***gras et italique***`.
- Pas d'emphasis sur des mots vides (`**le**`, `**un**`).

#### Structure des documents longs

- Pour les documents longs (audit, rapport, analyse), utiliser des séparateurs `---` entre les sections majeures.
- Un document long est défini par : plus de 3 sections `##` ou un total dépassant ~50 lignes.
- Les séparateurs `---` ne sont pas nécessaires pour les réponses courtes (moins de 3 sections).
- Le séparateur `---` doit être entouré de **lignes vides** (avant et après) pour ne pas être interprété comme un setext heading.
- Ne pas confondre séparateur `---` avec le setext H2 (`Titre\n---`) — utiliser les headings ATX uniquement.

#### Espacement

- Une ligne vide sépare chaque élément de block-level : heading, paragraphe, code block, liste, tableau, blockquote.
- Pas plus d'**une** ligne vide entre les éléments (pas de double saut de ligne).
- Le prose suit immédiatement le heading (pas de ligne vide entre `##` et le texte qui suit, sauf si la ligne vide précède une liste/tableau/code block).

#### HTML et portabilité

- Éviter le HTML brut (`<br>`, `<details>`, `<sup>`) sauf nécessité absolue (saut de ligne en tableau, pliable de contenu).
- Le HTML rend le markdown non portable (GFM ≠ CommonMark ≠ MMD).
- Si HTML nécessaire, l'isoler dans sa propre section et le justifier.

### Anti-patterns

- ❌ "Excellente idée !" sans fondement.
- ❌ "Vous avez raison" alors que la solution est mauvaise.
- ❌ Liste de 5 options sans recommandation.
- ❌ Poser 8 questions de clarification.
- ❌ Répondre dans une langue différente de celle de l'utilisateur.
- ❌ Bloc de code collé au texte sans ligne vide.
- ❌ Tableau avec headers mais sans données.
- ❌ Diagramme ASCII art quand une liste numérotée suffit.
- ❌ Plus de deux lignes vides consécutives.
- ❌ Sauter un niveau de heading (`##` → `####`).
- ❌ Indentation de liste mixant espaces et tabulations.
- ❌ Lien sans texte (`[](url)`).
- ❌ Image sans alt text (`![](url)`).
- ❌ Mixer `*` et `_` pour l'emphasis dans le même document.
- ❌ Code block contenant des backticks sans escalade des délimiteurs.
- ❌ Séparateur `---` collé au texte (interprété comme setext heading).
- ❌ Setext headings (`Titre\n===` ou `Titre\n---`).
- ❌ HTML brut sans justification (`<br>` hors tableau, `<sup>`, `<details>` non justifié).
