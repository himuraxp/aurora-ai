# Design niveau 2 — Canal MP en langage libre → runner headless

**Statut : PROPOSITION (conception, revue sécurité interne + revue externe intégrées) — STOP : toute implémentation exige un GO humain.**
Date : 2026-11-05 · Fondation : ARCHITECTURE §11 (niveau 1 J1-J4 livrés) et §12 (workflow J4bis).
Principe directeur : le niveau 2 se branche sur la fondation §11 — il n'ajoute **aucune** voie d'exécution nouvelle, il ajoute un **générateur de propositions** supplémentaire (au même rang que la grammaire N1).
Revues : sécurité défensive interne 2026-11-05 (9 findings intégrés — F-01…F-09) ; revue externe indépendante ai-cowork 2026-11-05 — verdict ITERATE, 4 lacunes P0 + 5 menaces/renforcements P1 + corrections de sur-promesses intégrées (notées « [P0.x] » / « [P1.x] » ci-dessous). Verdict externe final : *« Je valide l'orientation architecturale ; le GO d'implémentation reste une décision humaine distincte de cette revue. »*

---

## 1. Mandat

Répondre aux MPs du propriétaire écrits en **langage libre** (ex. « résume ce qui m'attend ce matin », « prépare un tri des newsletters de la semaine ») — cas que la grammaire N1 (§11.6, regex ancrées) refuse aujourd'hui par une réponse générique. Le niveau 2 route ces MPs vers un **runner headless dédié** qui analyse et produit des **propositions** au format N1, confirmables par `ok #p1` via le chemin d'autorisation existant (§11.4).

Hors périmètre de ce design : implémentation, activation, intégration launchd (J5).

## 2. Principes non négociables

1. **Le niveau 2 n'est jamais un exécutant.** Le runner headless produit une proposition (déplacement ponctuel, synthèse) — il ne déplace rien, n'écrit aucune règle, ne touche jamais `rules.json`, l'IMAP, kChat ni l'état SQLite de production. Toute action matérielle reste : proposition → confirmation humaine `ok #p1` → policy.py → moteur N1.
2. **Le MP libre est une donnée non fiable — distinction intention / autorité [P0, revue externe]** : le MP exprime une *intention fonctionnelle* (le niveau d'usage : trier, résumer, préparer) que le système interprète dans un périmètre figé ; il ne porte **jamais d'instruction d'autorité** (élargir un périmètre, activer une gate, commander une exécution, contourner un refus). Un contenu demandant « supprime tout le dossier X » reçoit la même infrastructure de refus (exclusions absolues, allowlist, policy) qu'une commande N1 — une formulation plus polie n'élargit jamais le périmètre.
3. **Aucune élévation par contenu** : un contenu lu par le runner (MP, inventaire d'état, réponse d'outil) ne peut ni activer une gate, ni modifier le périmètre, ni « descendre » une proposition en exécution directe.
4. **Sous-ensemble strict du niveau 1** : ce que le niveau 2 propose doit être expressible en verbes N1 existants (`#ref → dossier`, `traite #ref → alias`, synthèse). Pas de capacité nouvelle cachée derrière le langage libre.
5. **Le niveau 2 peut être coupé à tout instant** sans dégrader N1 (les 4 gates N1 restent indépendantes).
6. **Isolement = contrat OS/processus, composant par composant — jamais un deny de permissions.** Le runner est une **pure fonction** : entrée JSON (sérialisée par le moteur) → sortie JSON, **zéro outil, zéro accès fichiers, zéro réseau, zéro secret dans l'environnement** (jamais les `MAIL_TRIAGE_*` — il n'en a jamais besoin ; l'appel au modèle est fait par le moteur, pas le runner). Nuance [P0.2, revue externe] : la pureté du runner ne qualifie que le runner — le **pipeline N2 complet** dépend d'un appel modèle, d'un état et de ressources externes : l'isolation est donc spécifiée **par composant privilégié** (construction du contexte, client modèle, validation de la sortie, création de la proposition — chacun avec des capacités explicitement limitées, cf. §6bis), et le modèle/runner ne peut influencer ni les paramètres d'appel fournisseur, ni les chemins du moteur, ni la sélection des gates, ni la politique d'autorisation. « Zéro secret en env » ne garantit pas l'absence de descripteurs hérités ni d'accès à des services locaux : le test hostile J2 vérifie **les propriétés du processus réellement lancé** (descripteurs hérités, env effectif, capacités réseau, arrêt forcé, descendants) — jamais une configuration déclarative. Les denies de permissions client-side restent best-effort (doctrine ADR-021) : la seule frontière de confiance est la validation moteur de la sortie. Si une session opencode était retenue comme runner (option non recommandée), l'isolation OS (utilisateur dédié / sandbox / conteneur, aucun accès à `~/.config/opencode/mail-triage/` et `.env`) devient obligatoire.
7. **Une sortie valide du modèle ne constitue jamais une autorisation d'exécuter** — invariant central validé par la revue externe (aligné OWASP GenAI : séparation proposition / approbation / exécution).

## 3. Architecture (flux)

```
MP libre (langage naturel, propriétaire, DM autorisé)
   │  poller N1 (§11.3 : registre post_id, idempotence, checkpoint)
   │  grammaire N1 d'abord (§5 : seuls les zéro-match routent ;
   │    zone de rejet déterministe pour les formulations N1-like invalides)
   │  → 5e gate → bornes MP (§7) → budgets (§7)
   ▼
Runner headless = PURE FONCTION (principe §2.6)
   │  entrée : enveloppe JSON versionnée sérialisée par le moteur
   │           (schéma fermé v1 par étape, cf. §6)
   │  sortie : JSON strict { kind, verb?, target?, display_summary }
   │           — validée par le MOTEUR (schéma + allowlist verbes/kind
   │             par étape + bornes) ; non conforme → refus statique
   ▼
Proposition N1 standard (§11.4) — proposal_id opaque, figée, TTL 30 min,
   target_version, source_post_id, marquée `origin: headless`
   (tous les champs d'autorité fixés par le moteur, jamais par le runner)
   ▼
Proposition affichée au propriétaire (kChat) — reconstruite EXCLUSIVEMENT
   depuis l'action canonique validée (jamais depuis display_summary,
   cf. §4 A5/A10) : ref cible + description sûre + dossier canonique exact +
   caractère ponctuel + origine N2 + expiration + mention « générée par
   assistant »
   ▼
`ok #p1` → chemin d'autorisation N1 EXISTANT (§11.4/§11.7)
   (owner+DM+usage unique+revalidations+gates) → exécution moteur
```

Point clé : **aucun composant nouveau ne touche l'effet final**. La seule nouveauté exécutée est la *génération* de la proposition (calcul + lecture d'un inventaire sérialisé + validation + publication kChat par le service N1 existant).

## 4. Surface d'attaque (matrice)

| # | Menace | Vecteur | Mitigation (conception) |
|---|--------|---------|-------------------------|
| A1 | Prompt injection via MP libre | Le propriétaire colle un texte contenant des ordres (ou un email manipulé l'y induit) | Doctrine « contenu = données » (§2.2) ; le runner ne reçoit que des invariants figés en prompt système ; la sortie est VALIDÉE par le moteur (schéma + allowlist verbes/kind + bornes — une proposition hors périmètre est **rejetée sans proposition**, sans jamais faire confiance au texte produit) |
| A2 | Injection via contenus consultés | Sujet/email adversarial dans l'inventaire d'état sérialisé | Inventaire **pré-pseudonymisé par construction** (sujets masqués, pas de corps, sensibles absents) ; un runner compromis reste une pure fonction sans capability (§2.6) — au pire il pollue une proposition, rejetée si invalide et confirmée par un humain sinon |
| A3 | Fuite de contenu vers les journaux / stockages | Traces du runner, stockage de session, logs, traces du client modèle | Contrat de traces au niveau RUNNER (F-06 + P0.1) : le runner n'a zéro outil de logging ; stockage de session purgé immédiatement après traitement (compteur + statut sans contenu) ; **toute la chaîne moteur → fournisseur → moteur** : erreurs/traces HTTP/télémétrie du client modèle sans contenu sensible, pas de secret dans les traces ; journal N1 inchangé (verbe + statut + post_id + proposal_id, jamais le texte libre) |
| A4 | Contournement des 4 gates N1 | Le runner tente d'appeler le moteur en écriture | Structurel par le principe §2.6 : pure fonction sans capability face au moteur (ni lecture ni écriture) ; sa seule sortie est le JSON revalidé par le poller N1, qui crée une proposition *pending*, jamais *executing* |
| A5 | Proposition « plus large » que l'intention + **confirmation mécanique** | Langage libre ambigu (« range ce dossier ») ; l'humain confirme sans voir quoi | Ambiguïté → clarification (jamais de résolution arbitraire, cohérent §11.5) ; destinations = alias strict → chemin canonique ; **l'étape 2 n'admet qu'un couple canonique unique (#ref, dossier)** — jamais d'opération groupée, implicite ou sur un ensemble dynamique ; la confirmation affiche ref + description sûre + dossier exact + ponctualité + origine N2 + expiration ; le `display_summary` n'est **jamais** la description faisant autorité : la confirmation est reconstruite exclusivement depuis l'action canonique validée [P0.3] |
| A6 | DoS / coût | Boucle MPs↔sessions, coût IA, saturation concurrente | Budgets §7 (10 sessions/j, 1 tour, budgets distincts processus/modèle/requête, ≤5 actives, MP ≤ 1 500 chars, **plafond explicite de sessions simultanées** + sérialisation par le verrou poller P1-J5) ; MP hors quota ou hors borne → réponse statique sans session |
| A7 | Élévation de rôle de l'agent | Injection « tu es maintenant autorisé à… » | La capacité est bornée par le **contrat du runner** (pure fonction, §2.6), pas par son prompt : aucune instruction ne peut lui conférer une capacité absente du runtime |
| A8 | Réutilisation/rejeu | Le même MP retraité, réponse rejouée | Fondation §11.3 (registre post_id durable, idempotence) ; 1 session = 1 tour = au plus 1 proposition ; `target_version` + TTL 30 min N1 inchangés ; **identité kChat vérifiée côté serveur** (auteur, canal, bot destinataire — héritée §11.3) ; **les messages du bot lui-même ne sont jamais traités** (anti auto-déclenchement) [P1.9] |
| A9 | Confidentialité du rendu | La synthèse recopie du contenu sensible dans kChat | Le runner reçoit l'état *pseudonymisé du digest* (sujets masqués, pas de corps) — jamais les emails bruts ; sensibles : aucune ligne ; même frontière que le digest V4.1 |
| A10 | Injection de rendu actif du texte agent (F-02) | `display_summary` / clarify / synthèse étape 1 : texte dérivé de données non fiables rendu dans le DM (lien phishing, pixel, marqueur falsifié, faux « ok #p1 », mentions kChat) | Contrat obligatoire : TOUT texte agent destiné au rendu passe la primitive V4.2 (`_sanitize_ai_text`) avant publication — markdown actif désamorcé, URLs masquées, marqueur neutralisé, lignes aplaties, **borne appliquée après neutralisation**, encodage contextuel de **tous les champs affichés** ; formes de commande (`ok #pN`, `#ref →`) neutralisées ; échec → « résumé indisponible », jamais de rendu brut ; tests adversariaux J2/J3 |
| A11 | Confusion de partition grammaire N1 / langage libre (P1) | Une commande N1 malformée tombe dans N2 | **Zone de rejet déterministe** : les formulations portant des formes de commande N1 invalides (regex manquées, ref expiré, alias inconnu, destination interdite) → réponse statique N1, JAMAIS de routage N2 ; tests de partition exhaustifs — la zone de rejet est déterministe côté moteur, jamais une interprétation probabiliste du modèle |
| A12 | Substitution de cible (P1) | Le modèle invente une référence ou un dossier | Résolution EXCLUSIVEMENT depuis l'inventaire canonique borné sérialisé dans l'enveloppe (refs actives, aliases allowlist) ; une ref/dossier absent de l'inventaire = refus structurel ; revalidation IMAP de l'identité (UIDVALIDITY/UID/Message-ID) avant tout MOVE |
| A13 | Dérive de synthèse (P1) | Résumé plausible mais factuellement faux | Synthèse fondée sur des **faits structurés** de l'inventaire (comptages, refs, statuts), sans extrapolation sur le contenu des emails ; bornes d'affichage ; mention explicite de la source (état du tri, pas de promesse d'exhaustivité) |
| A14 | Entrées/sorties malformées (P1) | JSON dupliqué, Unicode trompeur, sortie excessive | Parser strict (UTF-8 valide, budget octets/chars sur l'entrée ET la sortie, pas de dupes), refus → réponse statique ; tests adversariaux |

## 5. Gates, précédence de routage & activation

- **5e gate dédiée** `interactive.headless.enabled` (défaut **false**, booléen strict — même discipline que `digest.ai.enabled` V4.2 : « true » string ne passe pas). Indépendante des 4 gates §11.2.
- **Précédence de routage (F-03 + P1.5)** : la grammaire N1 s'applique **intégralement et d'abord** — partition déterministe couvrant : matches exacts, commandes malformées (formes N1-like invalides), refs expirées, alias inconnus, destinations interdites, refus explicites. **Seuls les MPs à zéro regex-match ET hors zone de rejet déterministe** routent vers le niveau 2. Toute classe de refus de la grammaire est **N1-finale** : le MP reçoit exactement la même réponse avec la gate N2 ON ou OFF — jamais de re-adjudication d'un refus délibéré. Un carve-out ultérieur serait un changement de contrat explicite, décidé à la ratification. Le changement du contrat §11.6 (« tout le reste → réponse générique » devient « réponse générique ou session N2 selon gate, sur zéro-match hors zone de rejet ») est documenté dans le design ratifié.
- **Chain gate + timing + point de non-retour (F-08 + P0.4)** : la 5e gate est évaluée **avant la création d'une session** ; sa désactivation **interdit immédiatement** toute nouvelle proposition N2 ET toute confirmation N2 non encore autorisée (kill switch entre proposition et confirmation → `ok #p1` refusé — extension du test N1 §11.8) ; les **gates N1 d'écriture sont re-évaluées immédiatement avant l'effet IMAP** ; les transitions d'état des propositions restent **atomiques et persistantes** (réservation conditionnelle pending→executing N1 — une confirmation concurrente ne peut acquérir deux fois la même proposition) ; une opération **déjà engagée dans IMAP** n'est jamais promise annulable ; toute issue IMAP incertaine → état **uncertain** réconciliable (jamais de relance automatique qui doublerait l'effet — cohérent N1 `uncertain`).
- **Prérequis** : niveau 1 J4-J5 actifs ; `interactive.enabled` off → poller à l'arrêt → aucun routage du tout.

## 6. Contrat d'entrée/sortie (schéma fermé, versionné)

Format d'échange figé [P0.1] — **schéma d'entrée minimal, versionné et fermé, distinct par étape** :

- Entrée v1 (étape 1 — synthèse) : `{ schema_version: 1, stage: 1, mp_text (quoted, non interprété, ≤ borne §7), inventory: { refs_actives ≤ 30 (ref, statut, date), aliases_allowlist, quotas_restants } }` — **faits structurés seulement** (A13) ; pseudonymisation vérifiable par construction du schéma (aucun champ n'est un contenu brut).
- Entrée v1 (étape 2 — déplacement) : les mêmes + la ref ciblée et ses attributs canoniques (expéditeur pseudonymisé, dossier source, date) sélectionnés par le MOTEUR.
- Sortie : JSON strict `{ kind: proposal | clarify | refusal, verb?, target?, display_summary ≤ 300 chars, expires_hint }` — validée par le moteur (schéma strict + allowlist verbes/kind **par étape** F-05 + bornes) avant tout traitement ; non conforme → refus + réponse statique. `expires_hint` strictement informatif (le TTL 30 min est fixé par le moteur) ; tout champ d'autorité (`proposal_id`, `status`, `origin`, TTL) est **absent du schéma de sortie et ignoré par le validateur** s'il apparaît.
- **Confidentialité du chemin modèle (P0.1)** : les champs exacts transmis au fournisseur sont exactement ces champs (décision assumée, même posture que V4.2 §10.3.1 pour le sujet — rétention provider non contrôlable, nommée) ; le client modèle (côté moteur) : timeout, budget octets (réponse plafonnée), pas de télémétrie contentuelle, erreurs → raisons machine ; modèle indisponible → réponse statique « indisponible » (jamais de proposition partielle).

## 6bis. Capacités par composant du pipeline N2 (isolation par étage, P0.2)

| Composant | Capacités | Interdits |
|---|---|---|
| Construction de l'enveloppe (moteur) | lecture de l'état moteur (lecture seule), sérialisation pseudonymisée | jamais de contenu brut d'email, jamais de secret dans l'enveloppe |
| Client modèle (moteur) | appel HTTP sortant, budget, timeout | jamais d'injection de contenu produit par le runner dans l'appel, jamais de paramètre dicté par la sortie du runner |
| Validation de sortie (moteur) | parsing strict, allowlist par étape, bornes | jamais de confiance au texte produit ; jamais de résolution de cible hors inventaire |
| Création de proposition (moteur) | INSERT proposition pending (service N1 existant) | jamais de transition directe vers executing ; jamais de bypass des gates N1 |
| Runner | traitement du texte de l'enveloppe | zéro outil, zéro fichiers, zéro réseau, zéro secret, zéro logging |

Le runner ne peut influencer aucun de ces étages : sa seule sortie est le JSON validé.

## 7. Budgets & quotas (constantes de conception, bornées moteur)

- ≤ **10** sessions headless / jour (compteur partagé avec le quota N1 anti-boucle ; quota de règles = N1 inchangé : 5/jour) ; **plafond explicite de sessions simultanées** (la sérialisation du verrou poller P1-J5 la garantit de fait — le plafond est documenté et testé).
- 1 session = 1 tour = 1 proposition au plus ; le client modèle n'active **ni reprise automatique, ni appel d'outil, ni session persistante implicite** [revue externe] ; « relancer » = nouveau MP = nouveau budget.
- **Budgets distincts** [P0.4, revue externe] : durée du processus runner (60 s wall-clock), délai du client modèle (≤ timeout moteur), budget de la requête globale — un appel modèle terminé **après** expiration est ignoré (sa sortie n'est jamais consommée après coup) ; l'arrêt du runner traite ses descendants (pgrp) — test hostile.
- ≤ **5 propositions actives** d'origine headless simultanées (borne globale N1 10 actives reste).
- Propositions headless : TTL **30 min**, jamais de règle (§8).
- **Borne de longueur du MP libre (F-07)** : ≤ 1 500 chars appliquée côté moteur **avant** routage ; MP excédentaire → réponse statique éducative, jamais de session, aucune consommation de budget.

## 8. Découpage progressif (quoi activer, dans quel ordre)

Étape 1 : **synthèse seule** — le MP libre produit une *réponse informative* (résumé de l'état, aide à la décision) SANS proposition exécutable. Le validateur **rejette structurellement tout `kind: proposal` à l'étape 1** (réponse statique, sans retraitement) — indépendamment du prompt [P1.6] ; la synthèse est fondée sur l'inventaire structuré borné, **sans prétendre à une exhaustivité non démontrée** (mention de la source) [A13]. Risque conditionnel : quasi nul **SI** le rendu est neutralisé (A10), le scoping moteur appliqué et la purge des traces implémentés — tests de sortie J2 explicites.
Étape 2 : propositions **déplacement ponctuel** — seul verbe accepté : `#ref → alias` (allowlist moteur par étape : toute sortie émettant un verbe de règle ou toute autre action est refusée quelle que soit sa formulation) ; **ciblage exact d'un seul message et d'un seul dossier canonique** ; revalidation IMAP de l'identité et de la validité de la référence (UIDVALIDITY/UID/Message-ID) avant déplacement [P1.7/P0.3] ; usage unique, TTL court, révocable, effets limités à un message.
Étape 3 (décision séparée, pas dans ce design) : propositions de **règles** en langage libre — exigera une re-conception (impact durable sur la boîte).

L'allowlist verbes/kind **par étape est une constante moteur** (F-05) : le scoping n'est jamais documentaire — une sortie hors périmètre de l'étape active reçoit un refus moteur, sans proposition créée, quel que soit le prompt du runner.

## 9. Plan de livraison (J1-J4) — GO humain requis avant J1

| Jalon | Contenu | Tests de sortie |
|---|---|---|
| **J1** | Contrat (ce document ratifié), 5e gate + re-check à la création, validation de sortie JSON strict + allowlist verbes/kind par étape, précédence de routage (zéro-match hors zone de rejet déterministe, refus N1 finaux), borne MP, routage vers le runner, réponse statique de refus ; **frontières de confiance par composant spécifiées (§6bis)**, schémas d'entrée versionnés par étape, transitions d'état atomiques | gate off → comportement N1 identique octet pour octet ; MP reconnu-refusé ET commande N1 malformée → même réponse gate ON/OFF ; sortie non conforme → refus ; MP > borne → statique sans session ; quotas + plafond simultané appliqués ; **partition N1/N2 exhaustive testée** |
| **J2** | Étape 1 du §8 : synthèse read-only (rendu borné, pseudonymisé, neutralisé A10) | **Test runner hostile (F-01/P0.2)** : zéro écriture ET zéro lecture du répertoire privé, zéro secret en env **et zéro descripteur hérité sensible**, vérifiés sur le processus réellement lancé (pas déclaratif) ; tests adversariaux : MP hostile, contenu hostile dans l'inventaire, sorties malformées (JSON dupliqué, Unicode, sortie excessive, markdown actif, URL, marqueur, formes `ok #pN`/`#ref →` dans le rendu) toutes neutralisées/refusées ; purge des traces effective ; **audit des données réellement envoyées au fournisseur** ; zéro chemin de création de proposition exécutable |
| **J3** | Étape 2 : propositions déplacement via chemin N1 intégral (figée, TTL, revalidations) | couple canonique unique (#ref, dossier) uniquement ; confirmation reconstruite depuis l'action figée (jamais display_summary) ; revalidation IMAP identité avant MOVE ; courses/expiration/kill switch/issues IMAP incertaines testés ; gate coupée en vol à chaque transition (routage/session/création/confirmation) |
| **J4** | Observabilité + durcissement final : journal verbe/statut sans contenu, purge stockage runner (spot-check), **processus descendants, timeouts, cancellation, redémarrage après crash testés** [P1.8], revue sécurité post-implémentation sur code réel, activation conditionnée (GO séparé de l'opérateur) | audit complet des écritures (aucune hors moteur N1) ; matrice de gates en vol ; audit journal (MPs routés = statut + compteurs, jamais de texte libre) ; identité kChat serveur-side vérifiée ; registre anti-rejeu durable |

**Condition de démarrage J1** : ratification de ce design par l'opérateur + budget de revue sécurité sur l'implémentation (revue re-passée à J4 sur code réel).

**Points de vigilance d'implémentation (revue externe APPROVED, à traiter comme tests d'acceptation — pas de refonte)** :
- **A. Précédence N1 (livrable J1)** : critère d'acceptation de la zone de rejet — une commande N1 invalide ou délibérément refusée ne peut **jamais** devenir admissible en passant par N2.
- **B. Réconciliation IMAP (J3/J4)** : distinguer l'incertitude résoluble par vérification d'état de celle exigeant une résolution humaine — le système ne convertit **jamais** automatiquement une incertitude en autorisation de recommencer le MOVE.
- **C. Identité & concurrence (J3/J4)** : Message-ID seul n'est pas une preuve d'identité unique — l'identité canonique enregistrée et les invariants IMAP disponibles font foi ; la réservation atomique doit rester effective après crash et redémarrage.

## 10. Décisions ouvertes (à trancher par l'opérateur)

1. **Runner** : l'option recommandée (F-01 + revue externe) est le **runner pure-fonction** (stdin JSON → stdout JSON, zéro outil, zéro fichiers, zéro réseau, zéro secret env — l'appel modèle est fait par le moteur) ; l'option session opencode n'est retenue qu'avec isolation OS obligatoire (les denies runtime restent best-effort, ADR-021).
2. Étape 3 (règles en langage libre) : dans le périmètre d'un design futur, pas celui-ci.
3. **Traces & tiers (F-06 + P0.1)** : purge immédiate du stockage runner après traitement (compteur + statut sans contenu) ; périmètre de transmission tiers nommé et assumé (texte MP + inventaire pseudonymisé → API modèle, rétention côté provider non contrôlable — même posture assumée que V4.2 §10.3.1) ; politique du client modèle : pas de télémétrie contentuelle, erreurs en raisons machine.
4. Zone de rejet déterministe (P1.5) : la définition précise des formes N1-like invalides (l'heuristique déterministe exacte) sera proposée à J1 et validée par tests de partition — la ratification du principe suffit ici.

---

*Ce document ne modifie aucun comportement existant. Il ne crée aucune capacité tant que la 5e gate est absente (défaut false) et que J1-J4 ne sont pas implémentés et revus.*
