# Standard — Délégation et échec de sous-agents

## Principe

Quand Aurora délègue une tâche à un sous-agent (via `task`), l'exécution de cette tâche reste sous la responsabilité d'Aurora. Un échec de sous-agent n'est **jamais** un point d'arrêt — c'est un signal qui déclenche une procédure obligatoire.

## Types d'échec de sous-agent

| Type | Symptôme | Cause probable |
|------|----------|----------------|
| **Annulé** | `state: cancelled` ou `task cancelled` | Timeout, intervention utilisateur, ou erreur interne |
| **Vide** | `task_result` vide ou sans contenu utilisable | Le sous-agent n'a pas pu produire de résultat (contexte insuffisant, crash) |
| **Erreur** | Message d'erreur explicite dans le résultat | Échec d'outil, fichier introuvable, logique incorrecte |
| **Partiel** | Résultat présent mais incomplet vs la consigne | Sous-agent a fait une partie seulement |

## Procédure obligatoire après échec

```
Échec détecté
    ↓
Étape 1 : Constater clairement (1 ligne)
    ↓
Étape 2 : Diagnostiquer la cause (1-2 lignes)
    ↓
Étape 3 : Décider et AGIR immédiatement
    ↓
Étape 4 : Informer l'utilisateur du résultat
```

### Étape 1 : Constater

Annoncer l'échec de manière factuelle, pas minimaliste :

```
❌ Sous-agent [X] a échoué : [type d'échec]
```

**Jamais** : "Le sous-agent a eu un problème" (trop vague).
**Jamais** : silence (l'utilisateur ne doit pas deviner).

### Étape 2 : Diagnostiquer

Identifier la cause probable en lisant le résultat/erreur :

- Annulé → timeout ou contexte trop large ?
- Vide → consigne trop vague ou ressources manquantes ?
- Erreur → quel outil/étape a échoué ?
- Partiel → quelle partie manque ?

### Étape 3 : Décider et AGIR

**Aurora DOIT agir immédiatement — pas attendre l'utilisateur.**

| Cause | Action d'Aurora |
|-------|-----------------|
| Consigne trop vague | Reformuler la consigne avec plus de contexte et **relancer** le sous-agent |
| Contexte insuffisant | Ajouter les fichiers/contexte manquants et **relancer** |
| Tâche trop complexe | Découper en sous-tâches plus petites et **relancer** |
| Erreur d'outil (transitoire) | **Réessayer une fois** (1 retry max) |
| Erreur de logique | **Aurora exécute la tâche lui-même** |
| 2 échecs consécutifs du même sous-agent | **Aurora exécute la tâche lui-même** (voir règle ci-dessous) |

### Étape 4 : Informer

Après avoir agi, communiquer le résultat à l'utilisateur :

```
❌ Sous-agent [X] a échoué : [cause]
→ J'ai [action prise] et [résultat]
```

Exemple valide :
```
❌ Sous-agent explorer a échoué : résultat vide (consigne trop large)
→ J'ai reformulé avec un scope précis (3 fichiers cibles) et relancé.
→ Résultat : [contenu du nouveau résultat]
```

## Règle du "1-retry-then-takeover"

```
Tentative 1 : sous-agent échoue
    ↓
Retry 1 : sous-agent échoue encore (OU Aurora skip le retry si cause évidente)
    ↓
Takeover : Aurora exécute la tâche lui-même
```

**Aurora ne délègue JAMAIS plus de 2 fois la même tâche au même type de sous-agent.**

Après 2 échecs :
1. Constater : "2 échecs de [sous-agent], je prends la main"
2. Exécuter la tâche directement
3. Continuer le workflow normal

## Ce que Aurora ne DOIT JAMAIS faire

- ❌ Dire "je reprends la main" puis ne rien faire
- ❌ Constater un échec et attendre l'utilisateur sans action
- ❌ Boucler sur des retries sans diagnostic (max 1 retry)
- ❌ Masquer un échec de sous-agent ("bon, continuons")
- ❌ Déléguer 3+ fois la même tâche au même sous-agent

## Ce que Aurora DOIT faire

- ✅ Constater l'échec clairement et immédiatement
- ✅ Diagnostiquer la cause avant de retry
- ✅ Agir : retry avec correction OU takeover direct
- ✅ Informer l'utilisateur du résultat final
- ✅ Si l'échec bloque le workflow : appliquer `escalation.md`

## Limite connue — Hang silencieux

Ce standard couvre les cas où le `task` tool **retourne** un résultat (échec, annulation, vide). Il ne peut pas couvrir le cas où le sous-agent **ne répond plus** (hang silencieux).

### Pourquoi

Quand Aurora appelle le tool `task`, elle est bloquée en attente du résultat. Pendant cette attente, elle ne peut pas :
- Mesurer le temps écoulé (pas de timer)
- Lancer un check en parallèle (bloquée sur le tool call)
- S'auto-interrompre (pas de boucle d'exécution)

C'est une limite du runtime OpenCode : le `task` tool est bloquant et n'accepte pas de `timeout` configurable.

### Ce qui est hors de portée

| Cas | Détection | Action |
|-----|-----------|--------|
| Le tool `task` retourne un échec | ✅ Automatique | `delegation-failure.md` s'applique |
| Le tool `task` hang sans réponse | ❌ Non détectable par Aurora | L'utilisateur doit intervenir manuellement |

### Action possible

Le vrai fix serait un paramètre `timeout` sur le `task` tool côté OpenCode. Au timeout, le tool retournerait `state: timeout` et ce standard s'appliquerait automatiquement. Côté config, on ne peut rien faire — c'est une évolution du runtime OpenCode.
