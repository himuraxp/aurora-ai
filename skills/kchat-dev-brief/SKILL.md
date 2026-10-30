---
name: "kchat-dev-brief"
description: "Prépare un message kChat court, naturel et prêt à copier-coller pour signaler à une autre équipe un blocage, une anomalie ou un besoin technique découvert pendant le développement frontend ou les QA. Exemples : route API manquante, champ absent de la réponse, valeur inattendue, divergence de contrat, erreur backend, déploiement à confirmer ou clarification nécessaire. À utiliser pour les demandes de message kChat à l'équipe backend ou à une équipe technique."
---

# kChat Dev Brief

## Mission

Transformer des notes de développement, échanges techniques, rapports QA, captures, erreurs API ou observations dans le code en **un seul message kChat concis, compréhensible et actionnable**.

**But :** que l'équipe destinataire comprenne immédiatement **le contexte, le constat et ce qui est attendu d'elle**, sans devoir parcourir un rapport complet.

Ce skill sert **pendant le développement comme pendant les QA**. Il ne sert pas à faire un diagnostic exhaustif, une review ni à corriger du code.

## Situations couvertes

- Endpoint absent ou non disponible (`404`, route non déployée, méthode non prévue).
- Champ manquant ou valeur absente dans la réponse API.
- Format, type, enum, valeur, pagination ou comportement API différent du besoin frontend ou du contrat convenu.
- Erreur serveur ou validation inattendue (`422`, `500`, etc.).
- Fonctionnalité backend manquante pour poursuivre l'intégration frontend.
- Clarification attendue : contrat API, valeurs autorisées, responsabilité, disponibilité en préprod/prod, calendrier de déploiement.
- Blocages identifiés lors d'une QA, d'un test E2E ou d'une phase de développement.

## Sources et comportement

- Utiliser uniquement les éléments déjà fournis ou clairement disponibles dans la conversation : constats, requêtes/réponses, logs, extraits de code, captures, MR, environnements.
- Ne pas inventer de route, de champ, de valeur attendue, de code HTTP, de lien, de cause racine ou de statut de déploiement.
- Ne pas explorer le dépôt, lancer de tests ni appeler une API si les éléments transmis suffisent à rédiger le message.
- Séparer les **faits constatés** des **attentes frontend**, des **hypothèses** et des **questions à confirmer**.
- Ne jamais présenter « il manque un champ », « bug backend » ou « route non déployée » comme une certitude si le contrat ou le déploiement n'a pas été vérifié.
- Adresser le message à l'équipe indiquée par l'utilisateur ; ne pas supposer systématiquement que le backend est fautif.

## Méthode

1. **Identifier la demande** : s'agit-il de corriger un problème, d'ajouter une donnée, de confirmer un contrat ou de vérifier un déploiement ?
2. **Garder seulement l'utile** : fonctionnalité, environnement si pertinent, endpoint/champ précis, comportement observé, comportement nécessaire au front, action/question attendue.
3. **Regrouper** les constats connexes et classer les points bloquants en premier. Ignorer les tests PASS, le bruit de console et les explications d'implémentation non nécessaires.
4. **Formuler une demande par point** : « Est-ce prévu ? », « Vous pouvez ajouter `x` ? », « Pouvez-vous confirmer les valeurs possibles ? », « La route est-elle disponible en préprod ? ».
5. **Produire uniquement le message kChat**, sans annoncer que le skill a été exécuté, sans analyse ou variantes après le texte.

## Règles de rédaction

- **Par défaut 50 à 90 mots ; maximum 120 mots**, sauf demande explicite de l'utilisateur.
- **1 à 3 points au maximum**. Pour un seul sujet, préférer **un paragraphe de 2 à 4 phrases** plutôt qu'une liste artificielle.
- Ton **naturel, direct, cordial, entre collègues**. Une accroche simple (« Hello 👋 ») suffit.
- **Écrire le message en Markdown que kChat rend** (le style doit rester après le copier-coller) : gras `**…**` pour le sujet du point et l'écart clé, code inline pour les éléments techniques, listes `-` pour plusieurs points.
- **Gras parcimonieux** : le sujet de chaque point et 1 à 2 éléments clés au total — jamais une phrase longue entière, jamais le message entier.
- Formuler les demandes sans accusation : « Je constate… », « J'aurais besoin de… », « Vous pouvez confirmer… ? ».
- Conserver les éléments techniques qui permettent d'agir (`GET /route`, `field_name`, `404`, MR), mais **pas de payload complet**, stacktrace, longue liste d'enums ou chronologie.
- Éviter les titres de rapport, les tableaux, les longs blocs Markdown et les conclusions bureaucratiques.
- Mentionner l'impact sur le développement uniquement s'il est concret : « ça bloque l'intégration du formulaire » plutôt que « point critique » sans preuve.
- Un lien de contexte peut être ajouté s'il est fourni et réellement utile.
- Ne jamais divulguer token, identifiant secret, mot de passe, credentials, données privées ou données clients.
- **Ne pas envoyer le message automatiquement**, ni mentionner des collègues sans indication explicite. L'utilisateur le copie-colle.
- Si une information indispensable manque, formuler une question ouverte dans le message si cela reste utile ; demander une clarification à l'utilisateur seulement si aucun message exact ne peut raisonnablement être rédigé.

## Adaptation du format

**Un besoin unique :**

> Hello 👋 **[Fonctionnalité]** : [fait observé] sur `[endpoint]`. **Il me faudrait [besoin frontend]**. Vous pouvez me confirmer si c'est prévu / possible ? Merci !

**Plusieurs sujets indépendants :**

> Hello 👋 **[Fonctionnalité] (en [environnement])**, j'ai quelques points à voir avec vous :
>
> - **[Sujet]** : [fait]. [besoin ou question].
> - **[Sujet]** : [fait]. [besoin ou question].
>
> [Impact concret si utile.] Merci !

Ne jamais laisser les placeholders dans la réponse finale. Ne pas ajouter artificiellement un environnement ou une liste s'ils ne sont pas utiles. Livrer le message en texte Markdown brut — pas dans un bloc de code.

## Exemples de calibration

### A. Pendant le développement : champ manquant

**Contexte fourni (fictif) :** Sur l'écran des tâches, la réponse de `GET /tasks/{id}` contient `status` mais pas `progress`. Le front doit afficher la progression. Le besoin de ce champ n'a pas encore été validé avec le backend.

**Message attendu :**

Hello 👋 **Détail des tâches** : `GET /tasks/{id}` retourne bien `status`, mais **pas de valeur `progress`** — on en aurait besoin pour afficher l'avancement côté front. Vous pensez pouvoir l'exposer, ou il existe déjà un autre champ/endpoint prévu ? Merci !

### B. Pendant le développement : route à confirmer

**Contexte fourni (fictif) :** Le front doit dupliquer un profil. Aucune route de duplication n'a été identifiée dans la documentation disponible ; aucune réponse API n'a été testée.

**Message attendu :**

Hello 👋 **Duplication des profils** : je n'ai pas trouvé de route prévue pour cette action dans la doc API. Est-ce qu'un endpoint existe déjà ou faut-il en prévoir un ? Merci !

### C. Pendant la QA : plusieurs blocages confirmés

**Contexte fourni :** QA callbacks VOD préprod : 15 valeurs d'événement testées rejetées en 422 ; `event_list` vide/absent provoque un 500 `vod_connect` ; `GET /secrets` renvoie 404 ; déploiement MR API !304 incertain.

**Message attendu :**

Hello 👋 **Callbacks VOD (préprod)**, j'ai 3 points à vérifier avec vous :

- **Événements (422)** : les 15 valeurs testées sont rejetées. Vous pouvez confirmer les valeurs autorisées ?
- **Création (500)** : erreur `vod_connect` avec `event_list` vide ou absent. À vérifier côté API.
- **Secrets (404)** : `GET /secrets` est indisponible. La MR API `!304` est-elle déjà déployée en préprod ?

Ça bloque la validation complète du parcours. Merci !

## Vérification finale silencieuse

- Le message correspond au **besoin réel** (développement, QA, demande d'évolution ou clarification), sans forcer un cadrage « QA ».
- Chaque constat est étayé ; aucune hypothèse n'est transformée en certitude.
- Chaque point contient une action ou une question compréhensible.
- Le message est court, lisible d'un coup d'œil et **prêt à copier-coller**.
- Le Markdown employé est rendu par kChat (gras, code inline, listes) et le message reste lisible en texte brut.
- Aucune explication d'agent n'entoure le message.
