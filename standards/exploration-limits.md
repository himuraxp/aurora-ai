# Standard — Exploration Limits

## Principe

L'exploration de code consomme massivement le contexte. Sans garde-fous, une session de "comprehension" remplit la fenêtre de contexte et dégrade les performances. Aurora DOIT délimiter strictement les investigations.

## Règles de délimitation

### 1. Limite de profondeur

- **Niveau 1** (scope connu) : < 5 fichiers — pas besoin de plan
- **Niveau 2** (scope partiellement connu) : 5-15 fichiers — plan court obligatoire
- **Niveau 3** (scope inconnu) : > 15 fichiers — investigation via subagent obligatoire

### 2. Subagent obligatoire pour l'investigation lourde

Quand une investigation touche plus de 15 fichiers potentiels, **toujours** utiliser un subagent `explore` ou `general` :

```text
Use an explore subagent to investigate how [X] works.
Return ONLY :
- Files read (with line ranges if relevant)
- Key findings (max 10 bullet points)
- Files that need to be modified for task [Y]
```

Le subagent explore dans son propre contexte. L'agent principal conserve son contexte propre pour l'implémentation.

### 3. Découpage des investigations

Une investigation ne doit jamais être : "expliquer le projet" ou "comprendre tout le code".

Chaque investigation DOIT avoir :
- **Un objectif précis** : ex. "trouver où les tokens d'authentification sont rafraîchis"
- **Une portée délimitée** : ex. "dans src/auth/ uniquement"
- **Un résultat attendu** : ex. "liste des fichiers + flux de rafraîchissement"

### 4. Limite de tokens

Si l'investigation a lu plus de 100 lignes de code sans trouver la réponse, **stopper**.
- Noter dans `BUFFER.md` que la recherche est incomplète
- Demander à l'utilisateur des indices sur l'emplacement, ou
- Affiner la recherche avec des motifs plus spécifiques (`Grep` sur des mots-clés précis)

### 5. Pas de lecture globale inutile

- ❌ `find src -name "*.ts" | xargs cat` → massacre de contexte
- ✅ `Grep "AuthService"` puis `Read` du fichier trouvé
- ✅ `Grep "@Injectable.*Auth"` pour trouver le provider

## Informations à collecter pour l'INDEX.md

Après une investigation réussie, mettre à jour `docs/ai/INDEX.md` avec les fichiers découverts pour éviter de refaire la recherche :

```text
## Découverte — 2026-06-08
- `src/auth/token.service.ts` : Rafraîchissement des tokens
- `src/auth/guard.ts` : Protection des routes
```

## Anti-patterns

- ❌ "Explorer le code pour comprendre" sans objectif précis
- ❌ Lire l'intégralité d'un fichier de > 200 lignes si grep suffit
- ❌ Faire une investigation de > 15 fichiers sans subagent
- ❌ Stocker les résultats d'investigation uniquement dans la conversation — toujours persister dans `docs/ai/INDEX.md`
