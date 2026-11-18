# Standard — Anti-Patterns

## 5 patterns d'échec à reconnaître et corriger immédiatement

### 1. La session fourre-tout (The everything session)

**Symptôme** : Vous commencez par une tâche, puis demandez autre chose, puis revenez à la première. Le contexte est plein d'informations non pertinentes.

**Conséquence** : La fenêtre de contexte est saturée de sujets sans lien, l'agent fait des erreurs ou mélange les commandes de tâches distinctes.

**Correction** : 
- Une tâche = une session. Si un nouveau sujet surgit, noter dans `BUFFER.md` et traiter séparément.
- Si le sujet principal est terminé et qu'un sujet connexe apparaît : finir le sujet principal, persister la mémoire, puis aborder le connexe.

---

### 2. Corrige encore et encore (The correction spiral)

**Symptôme** : L'agent fait quelque chose de mal, vous le corrigez, c'est toujours mal, vous corrigez à nouveau. Après 2-3 essais, la session est polluée par des approches échouées.

**Conséquence** : La qualité s'effondre, les corrections deviennent de plus en plus bizarres (hack sur hack).

**Correction** : 
- Voir `error-correction.md` (règle 2-strikes).
- Après 2 échecs de correction : reset, réécrire l'invite, repartir avec un contexte propre.

---

### 3. L'AGENTS.md sur-spécifié (The over-specified config)

**Symptôme** : Le `AGENTS.md` local fait 500 lignes, contient des règles évidentes, du code fichier par fichier, des tutoriels.

**Conséquence** : L'agent ignore la moitié des règles car elles se perdent dans le bruit. Les règles importantes ne sont pas appliquées.

**Correction** : 
- Règle : Si supprimer une ligne ne causerait pas d'erreur, la supprimer.
- Inclure uniquement : commandes bash, règles de style qui diffèrent des conventions, décisions architecturales, pièges.
- Exclure : documentation API détaillée (lien vers la doc), conventions standard du langage, descriptions fichier par fichier.

---

### 4. L'écart confiance-puis-vérification (Trust-then-verify gap)

**Symptôme** : L'agent produit une implémentation plausible, vous lui faites confiance, vous ne vérifiez pas (ou il ne vérifie pas).

**Conséquence** : Cas limites non gérés, régressions silencieuses, bugs en production.

**Correction** :
- **Toujours** fournir une vérification que l'agent peut exécuter : tests, compilation, script de comparaison.
- Voir `verification.md` et `review-before-done.md`.
- Si vous ne pouvez pas vérifier le résultat, ne pas le déployer.

---

### 5. L'exploration infinie (The infinite exploration)

**Symptôme** : Vous demandez "investiguer" sans délimiter. L'agent lit des centaines de fichiers, explore 10 modules sans lien, remplit le contexte.

**Conséquence** : La session devient une exploration sans objectif, aucune modification utile n'est faite, le contexte est saturé.

**Correction** :
- Voir `exploration-limits.md`.
- Chaque investigation DOIT avoir : objectif précis, portée délimitée, résultat attendu.
- Si > 15 fichiers : utiliser un subagent explore.

## Règle générale

> Si vous reconnaissez un anti-pattern en cours, **stoppez immédiatement** et appliquez la correction, même si cela signifie perdre le travail de la dernière étape. Un reset propre est moins coûteux qu'une session polluée.
