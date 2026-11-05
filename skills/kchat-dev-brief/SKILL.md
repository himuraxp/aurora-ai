---
name: "kchat-dev-brief"
description: "Prépare un message kChat court, naturel et prêt à copier-coller pour signaler à une autre équipe un blocage, une anomalie ou un besoin technique découvert pendant le développement frontend ou les QA. Exemples : route API manquante, champ absent de la réponse, valeur inattendue, divergence de contrat, erreur backend, déploiement à confirmer ou clarification nécessaire. À utiliser pour les demandes de message kChat à l'équipe backend ou à une équipe technique."
---

# kChat Dev Brief

## Mission

Transformer des notes de dev, erreurs API, rapports QA, captures ou observations dans le code en **un seul message kChat extrêmement concis, que le destinataire lit en un seul passage** et auquel il sait quoi répondre.

**Priorité absolue : minimum de lecture, maximum d'informations utiles.** Un message trop long décourage de le lire et d'y répondre.

Ce skill sert pendant le développement comme pendant les QA. Il ne produit pas un diagnostic exhaustif, une review ni une correction de code.

## Collecte des faits

- Utiliser uniquement les éléments fournis dans la conversation : constats, requêtes/réponses, logs, captures, MR, environnements. Ne pas explorer le dépôt, lancer de tests ni appeler une API si ces éléments suffisent à rédiger le message.
- Ne jamais inventer une route, un payload, une réponse, un code HTTP, un lien, une cause racine ou un statut de déploiement. Si le payload réel n'est pas disponible, ne pas afficher de bloc JSON fictif.
- Séparer les faits constatés des hypothèses et des attentes front. Ne jamais présenter une hypothèse comme une certitude (« route non déployée », « bug backend ») tant que ce n'est pas vérifié.
- Si un problème peut ne pas relever du backend, poser une question de confirmation plutôt qu'attribuer la responsabilité.
- Adresser le message à l'équipe indiquée par l'utilisateur.
- Ne jamais divulguer token, secret, identifiant, données personnelles ou données clients.

## Format et budget de lecture

**Budget : 10 à 15 secondes de lecture ciblée par message simple (≈ 30 à 60 mots hors code) ; 30 secondes maximum pour un message multi-points.** Dépasser uniquement lorsque la compréhension l'exige ; ne jamais sacrifier l'exactitude technique pour respecter le budget.

**Format privilégié — un point (1 à 3 points au maximum par message) :**

````markdown
Hello 👋 **Sujet — `MÉTHODE /route`**

Constat en une phrase. **Question directe ?**
````

Payload JSON minimal dans un bloc de code json multiligne, uniquement s'il apporte une information indispensable.

Plusieurs sujets indépendants : un bloc numéroté par sujet, même squelette (**1. Sujet — `MÉTHODE /route`**, constat, question). Un seul sujet : pas de numérotation.

**Règles de structure :**

- **Une seule idée par point** : constat court, puis **une question par sujet**.
- **Introduction facultative** : une ligne maximum (fonctionnalité, environnement si utile, impact concret si réel).
- **Conclusion facultative** : supprimer les formules de politesse si elles allongent le message sans le rendre plus agréable.
- **Regrouper les demandes similaires** (mêmes routes, même question) et **séparer les sujets indépendants**.
- Plus de 3 sujets indépendants : regrouper d'abord tout ce qui se fusionne sans perte ; sinon dépasser le plafond en gardant le même squelette, plutôt que de perdre un point bloquant.
- Le message reste **un message de chat, pas un document** : gras pour le sujet du point et l'écart clé, code inline pour les éléments techniques, listes `-` et blocs de code json — **jamais de titres `#`**, jamais de tableaux.

## Précisions techniques API (quand connues)

- **Route visible** dès qu'elle est connue et utile : `MÉTHODE /route` dans le titre du point.
- **Payload** : uniquement si nécessaire pour comprendre ou reproduire le problème. JSON réduit aux champs utiles — jamais le payload complet par défaut, jamais de JSON inventé.
- **Réponse API** : statut HTTP et message d'erreur lorsqu'ils aident à identifier le problème.
- **Attendu / constaté** : une phrase simple sur la différence lorsqu'il s'agit d'un bug.
- Plusieurs routes concernées par la même question : les regrouper dans un seul point.
- Ne pas répéter la route ni le payload dans l'explication.

## Règles de rédaction

- Phrases courtes et directes, mots simples. Pas de jargon ni de formulation artificielle (« arbitrage du contrat », « runtime conforme »).
- **Aucune répétition** : une information n'apparaît qu'une fois.
- **Aucun contexte superflu** : ne pas raconter les investigations, les tests effectués ni l'historique du problème.
- Détails techniques limités à ce qui est indispensable pour comprendre et répondre (route, champs, codes d'erreur). Pas de stacktrace, de liste d'enums complète, de preuve de QA ni d'explication d'implémentation.
- Impact sur le travail mentionné uniquement s'il est concret : « ça bloque l'intégration du formulaire » plutôt que « point critique » sans preuve.
- Ton naturel entre collègues, tutoiement ou vouvoiement selon le destinataire, formulation amicale sans accusation.
- Un lien de contexte peut être ajouté s'il est fourni et réellement utile.

## Passe de compression (avant restitution, silencieuse)

- Peut-on supprimer cette phrase sans perdre une information utile ?
- Le destinataire sait-il immédiatement ce qui lui est demandé ?
- La route et le payload nécessaires sont-ils présents ?
- Peut-on raccourcir encore sans perdre en clarté ?
- Le message ressemble-t-il à un échange naturel entre développeurs plutôt qu'à un rapport technique ?

**Règle finale : toute phrase qui n'aide pas directement à comprendre le problème ou à y répondre disparaît.**

## Livrable

Uniquement le message, livré dans un bloc de code Markdown fermé par **au moins 4 backticks** — les blocs de code json internes (3 backticks) ne coupent pas le bloc, et la syntaxe brute (gras, code inline, json multiligne) est copiée telle quelle, puis rendue par kChat après collage. Le contenu reste un message de chat : jamais de titres `#`. Sans annonce du skill, sans analyse, sans variantes, sans placeholder. Ne jamais l'envoyer automatiquement ni mentionner des collègues sans indication explicite. Si une information indispensable manque, l'intégrer comme question ouverte dans le message ; demander une clarification à l'utilisateur seulement si aucun message ne peut raisonnablement être rédigé.

## Exemples de calibration

Les exemples montrent le contenu ; à la restitution, livrer chaque message dans un bloc de code Markdown décrit dans Livrable.

### A. Développement — champ manquant

**Contexte fourni (fictif) :** la réponse de `GET /tasks/{id}` contient `status` mais pas `progress` ; le front doit afficher l'avancement.

**Message attendu :**

````markdown
Hello 👋 **Détail des tâches — `GET /tasks/{id}`**

La route retourne `status` mais pas `progress`, nécessaire pour afficher l'avancement. **Possible de l'exposer, ou une autre route la fournit déjà ?** Merci !
````

### B. Développement — migration VOD v3 : payload rejeté

**Contexte fourni (fictif) :** migration v2 → v3. `PUT /3/vod/{id}` avec le payload ci-dessous renvoie 400 avec le message « Invalid format » en v3, alors que le même passait en v2.

**Message attendu :**

````markdown
Hello 👋 **Migration VOD v3 — `PUT /3/vod/{id}`**

```json
{ "url": "https://cdn.exemple.com/video.mp4", "format": "mp4" }
```

Ce payload passait en v2, il renvoie **400 Invalid format** en v3. **Nouvelle validation attendue ou régression ?** Merci !
````

### C. API — fonctionnalité manquante

**Contexte fourni (fictif) :** le front doit dupliquer un profil ; aucune route de duplication identifiée dans la doc ; rien n'a été testé.

**Message attendu :**

````markdown
Hello 👋 **Profils**

Je ne trouve pas de route pour dupliquer un profil dans la doc v3. **Une route existe-t-elle déjà, ou est-ce prévu ?** Merci !
````

### D. QA — plusieurs blocages indépendants

**Contexte fourni (fictif) :** QA callbacks VOD préprod : `POST /3/vod/{id}/callbacks` rejette en 422 les 15 valeurs d'événement testées ; `event_list` vide ou absent provoque un 500 `vod_connect` ; `GET /3/vod/secrets` renvoie 404, MR API !304 possiblement non déployée. Les trois constats bloquent la validation du parcours.

**Message attendu :**

````markdown
Hello 👋 **Callbacks VOD (préprod)** — 3 points qui bloquent la validation :

**1. Valeurs d'événement — `POST /3/vod/{id}/callbacks`**

Les 15 valeurs testées renvoient **422**. **Quelles valeurs sont autorisées ?**

**2. Création — 500 `vod_connect`**

L'erreur survient quand `event_list` est vide ou absent. **Vous pouvez regarder ?**

**3. `GET /3/vod/secrets` — 404**

**La MR API !304 est-elle déployée en préprod ?**
````

### E. Clarification — contrat à reconfirmer

**Contexte fourni (fictif) :** en préprod, les valeurs d'`event_type` listées dans la doc v2 provoquent un 422 en v3 ; le contrat n'a pas été reconfirmé depuis la migration.

**Message attendu :**

````markdown
Hello 👋 **Webhooks VOD (v3)**

Les valeurs `event_type` de la doc v2 renvoient **422** en préprod. **Quelles sont les valeurs autorisées en v3 ?** Merci !
````
