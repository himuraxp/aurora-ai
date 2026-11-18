# Standard — Error Correction

## Principe

Corriger un échec avec le même contexte pollué mène à une dégradation rapide. Après 2 corrections échouées sur le même problème, le contexte est saturé d'approches avortées et la qualité s'effondre. Aurora DOIT savoir quand faire un reset stratégique.

## Règle du "2-strikes"

### Définition

Un **Strike** = une tentative de correction ou de refactorisation d'un code considéré comme mauvais, d'une erreur de compilation, d'un test qui échoue ou d'un comportement buggy, où la modification proposée n'a **pas résolu le problème** (la même erreur ou un problème similaire persiste).

**Types spécifiques de strikes** :
- Correction d'un bug → le bug est toujours présent après la modification
- Correction d'une erreur de compilation → la compilation échoue encore (même erreur ou nouvelle)
- Correction d'un test qui échoue → le test échoue toujours après la modification
- Refactorisation d'un code → le nouveau code produit le même problème ou une nouvelle régression

**Ce qui n'est PAS un strike** :
- Correction typo ou formatage simple (pas de logique changée)
- Passage d'une étape de build/lint/test à une autre (compilation OK mais test échoue = nouveau problème, <= même strike si on corrige le premier problème)
- Gestion acceptée d'une décision d'évolution après discussion avec l'utilisateur

### Procédure

```
Strike 1 : erreur identifiée → correction proposée → ne fonctionne pas
Strike 2 : nouvelle correction proposée → ne fonctionne toujours pas
Strike 3 : → RESET OBLIGATOIRE
```

### Action de reset (strike 3)

1. **Constater** ouvertement : "2 corrections échouées, le contexte est pollué"
2. **Réinitialiser l'approche** : revenir à zéro sur ce sous-problème
3. **Réécrire l'invite** en incorporant les apprentissages :
   - Ce qui a été tenté et a échoué
   - La cause racine désormais identifiée
   - L'approche différente à essayer
4. ⚠️ **Ne JAMAIS** continuer à corriger dans la même session sans reset

## Cas spécifiques

### Corriger sans comprendre la cause racine

- ❌ "Erreur de compilation → je vais ajouter un type any pour passer"
- ✅ "Erreur de compilation → identifier pourquoi le type est mismatch → corriger la source du mismatch → vérifier que le build passe"

### Supprimer un test qui échoue

- ❌ Strike. **Jamais** supprimer un test sans justification explicite dans `STATUS.md` + `WARNINGS.md`.
- ✅ "Le test échoue car la logique a changé → mettre à jour le test pour refléter la nouvelle logique"

### Corriger en boucle sur le même fichier

Si un même fichier a été modifié > 3 fois pour le même problème :
- Lire le fichier actuel dans son **intégralité** (pas les morceaux)
- Se demander : "Le design de la solution est-il correct ?"
- Consulter `PLAN.md` — s'écarter du plan initial ? Discuter avec l'utilisateur.

## Contrôles de cohérence systématiques

Après chaque correction :
- [ ] La modification a-t-elle un effet de bord sur d'autres fichiers ?
- [ ] Les tests existants passent-ils toujours ?
- [ ] Le lint passe-t-il ?
- [ ] Si suppression de code : aucun autre fichier ne l'importe/utilise ?

## Anti-patterns

- ❌ 3+ tentatives sur le même problème sans reset
- ❌ Corriger sans comprendre la cause racine
- ❌ Supprimer un test, du lint ou du build check pour faire passer
- ❌ Modifier un fichier > 3 fois sans relecture globale du fichier
