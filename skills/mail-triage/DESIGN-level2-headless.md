# Design niveau 2 — Canal MP en langage libre → runner headless

**Statut : PROPOSITION (conception, revue sécurité intégrée) — STOP : toute implémentation exige un GO humain.**
Date : 2026-11-05 · Fondation : ARCHITECTURE §11 (niveau 1 J1-J4 livrés) et §12 (workflow J4bis).
Principe directeur : le niveau 2 se branche sur la fondation §11 — il n'ajoute **aucune** voie d'exécution nouvelle, il ajoute un **générateur de propositions** supplémentaire (au même rang que la grammaire N1).
Revue : sécurité défensive 2026-11-05 (9 findings intégrés — F-01 isolement runner, F-02 rendu actif, F-03 précédence routage, F-04 runner pur, F-05 scoping moteur, F-06 traces, F-07/F-08/F-09).

---

## 1. Mandat

Répondre aux MPs du propriétaire écrits en **langage libre** (ex. « résume ce qui attend de moi ce matin », « prépare un tri des newsletters de la semaine ») — cas que la grammaire N1 (§11.6, regex ancrées) refuse aujourd'hui par une réponse générique. Le niveau 2 route ces MPs vers un **runner headless dédié** qui analyse et produit des **propositions** au format N1, confirmables par `ok #p1` via le chemin d'autorisation existant (§11.4).

Hors périmètre de ce design : implémentation, activation, intégration launchd (J5).

## 2. Principes non négociables

1. **Le niveau 2 n'est jamais un exécutant.** Le runner headless produit une proposition (déplacement ponctuel, synthèse) — il ne déplace rien, n'écrit aucune règle, ne touche jamais `rules.json`, l'IMAP, kChat ni l'état SQLite de production. Toute action matérielle reste : proposition → confirmation humaine `ok #p1` → policy.py → moteur N1.
2. **Le MP libre est une donnée non fiable** (même doctrine que V4.2 §10.4 et niveau 1 §11.3) : jamais une instruction. Un contenu demandant « supprime tout le dossier X » reçoit la même infrastructure de refus (exclusions absolues, allowlist, policy) qu'une commande N1 — une formulation plus polie n'élargit jamais le périmètre.
3. **Aucune élévation par contenu** : un contenu lu par le runner (MP, inventaire d'état, réponse d'outil) ne peut ni activer une gate, ni modifier le périmètre, ni « descendre » une proposition en exécution directe.
4. **Sous-ensemble strict du niveau 1** : ce que le niveau 2 propose doit être expressible en verbes N1 existants (`#ref → dossier`, `traite #ref → alias`, synthèse). Pas de capacité nouvelle cachée derrière le langage libre.
5. **Le niveau 2 peut être coupé à tout instant** sans dégrader N1 (les 4 gates N1 restent indépendantes).
6. **Isolement du runner = contrat OS/processus, jamais un deny de permissions.** Le runner est une **pure fonction** : entrée JSON (sérialisée par le moteur) → sortie JSON, **zéro outil, zéro accès fichiers, zéro réseau, zéro secret dans l'environnement** (jamais les `MAIL_TRIAGE_*` — il n'en a jamais besoin ; l'appel modèle si nécessaire est fait par le moteur, pas le runner). Les denies de permissions client-side sont prouvés inopérants pour les agents opencode à accès fichiers (doctrine ADR-021 du repo aurora-core) : s'ils existent, ils ne sont que best-effort — la seule frontière de confiance est la validation moteur de la sortie. Si une session opencode était retenue comme runner (option non recommandée), l'isolation OS (utilisateur dédié / sandbox / conteneur, aucun accès à `~/.config/opencode/mail-triage/` et `.env`) devient obligatoire. Test J2 : un runner hostile (induit par injection) ne peut ni écrire, ni lire le répertoire privé, ni atteindre un secret.

## 3. Architecture (flux)

```
MP libre (langage naturel, propriétaire, DM autorisé)
   │  poller N1 (§11.3 : registre post_id, idempotence, checkpoint)
   │  grammaire N1 d'abord (§5 : seuls les zéro-match routent)
   │  → 5e gate → bornes MP (§7) → budgets (§7)
   ▼
Runner headless = PURE FONCTION (principe §2.6)
   │  entrée : enveloppe JSON sérialisée par le moteur
   │           { texte MP (quoted, non interprété), inventaire minimal
   │             pseudonymisé : refs actives ≤ 30, aliases allowlist, quotas }
   │  sortie : JSON strict { kind, verb?, target?, display_summary }
   │           — validé par le MOTEUR (schéma + allowlist verbes/kind
   │             par étape + bornes) ; non conforme → refus statique
   ▼
Proposition N1 standard (§11.4) — proposal_id opaque, figée, TTL 30 min,
   target_version, source_post_id, marquée `origin: headless`
   (tous les champs d'autorité fixés par le moteur, jamais par le runner)
   ▼
Proposition affichée au propriétaire (kChat) — chemin IMAP canonique
   résolu (P1-J3) + mention « générée par assistant » ; le texte rendu
   (display_summary / clarify / synthèse) est NEUTRALISÉ (§4 A10)
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
| A3 | Fuite de contenu vers les journaux / stockages | Traces du runner, stockage de session, logs | Contrat de traces au niveau RUNNER (F-06) : le runner n'a zéro outil de logging ; stockage de session purgé immédiatement après traitement (compteur + statut sans contenu) ; journal N1 inchangé (verbe + statut + post_id + proposal_id, jamais le texte libre) ; **zéro secret dans l'environnement du runner** |
| A4 | Contournement des 4 gates N1 | Le runner tente d'appeler le moteur en écriture | Structurel par le principe §2.6 : pure fonction sans capability face au moteur (ni lecture ni écriture) ; sa seule sortie est le JSON revalidé par le poller N1, qui crée une proposition *pending*, jamais *executing* |
| A5 | Proposition « plus large » que l'intention | Langage libre ambigu (« range ce dossier ») | Proposition figée à un verbe+cible précis ; ambiguïté → réponse de clarification (jamais de résolution arbitraire, cohérent §11.5) ; destinations = alias strict → chemin canonique, jamais chemin arbitraire |
| A6 | DoS / coût | Boucle MPs↔sessions, coût IA | Budgets §7 (10 sessions/j, 1 tour, 60 s, ≤5 actives, verrou poller P1-J5 qui sérialise tout) ; MP hors quota ou hors borne → réponse statique sans session |
| A7 | Élévation de rôle de l'agent | Injection « tu es maintenant autorisé à… » | La capacité est bornée par le **contrat du runner** (pure fonction, §2.6), pas par son prompt : aucune instruction ne peut lui conférer une capacité absente du runtime |
| A8 | Réutilisation/rejeu | Le même MP retraité, réponse rejouée | Fondation §11.3 (registre post_id, idempotence) ; 1 session = 1 tour = au plus 1 proposition ; `target_version` + TTL 30 min N1 inchangés |
| A9 | Confidentialité du rendu | La synthèse recopie du contenu sensible dans kChat | Le runner reçoit l'état *pseudonymisé du digest* (sujets masqués, pas de corps) — jamais les emails bruts ; sensibles : aucune ligne ; même frontière que le digest V4.1 |
| A10 | Injection de rendu actif du texte agent (F-02) | `display_summary` / clarify / synthèse étape 1 : texte dérivé de données non fiables rendu dans le DM à côté d'une proposition (lien phishing, pixel, marqueur falsifié, faux « ok #p1 ») | Contrat obligatoire : TOUT texte agent destiné au rendu passe la primitive V4.2 (`_sanitize_ai_text`) avant publication — markdown actif désamorcé, URLs masquées, marqueur neutralisé, lignes aplaties, **borne appliquée après neutralisation** ; formes de commande (`ok #pN`, `#ref →`) neutralisées dans le texte rendu (anti-conditionnement à confirmer) ; échec → « résumé indisponible », jamais de rendu brut ; tests adversariaux J2/J3 |

## 5. Gates, précédence de routage & activation

- **5e gate dédiée** `interactive.headless.enabled` (défaut **false**, booléen strict — même discipline que `digest.ai.enabled` V4.2 : « true » string ne passe pas). Indépendante des 4 gates §11.2.
- **Précédence de routage (F-03)** : la grammaire N1 s'applique **intégralement et d'abord**. Seuls les MPs à **zéro regex-match** (statut unknown du parser `parse_command`) routent vers le niveau 2. Toute classe de refus de la grammaire (ref-typo éducatif, alias inconnu, destination interdite, ref expiré) est **N1-finale** : le MP reçoit exactement la même réponse avec la gate N2 ON ou OFF — jamais de re-adjudication d'un refus délibéré (un « #a1 → corbeille » refusé sans proposition par N1 ne peut pas recevoir une destination alternative en N2). Un carve-out ultérieur (router les ref-typo vers N2) serait un changement de contrat explicite, décidé à la ratification — jamais les classes à portée de policy. Le changement du contrat §11.6 (« tout le reste → réponse générique » devient « réponse générique ou session N2 selon gate, sur zéro-match seulement ») est documenté dans le design ratifié.
- **Chain gate + timing (F-08)** : publier une proposition headless exige les gates de sa cible au moment de la CONFIRMATION ; la 5e gate est **re-vérifiée au moment de la création** de la proposition (gate coupée en vol → aucune création, réponse statique — une session terminée en vol ne mine rien) ; `ok #p1` refusé si coupée entre proposition et confirmation (extension du test N1 §11.8).
- **Prérequis** : niveau 1 J4-J5 actifs ; `interactive.enabled` off → poller à l'arrêt → aucun routage du tout.

## 6. Permissions du runner (agent dédié, pure fonction)

| Capacité | Niveau 2 |
|---|---|
| Lecture emails bruts / IMAP / SQLite écriture | ❌ jamais (inventaire pseudonymisé seulement, sérialisé dans l'enveloppe) |
| Écriture fichiers (config, rules.json, état, mémoires) | ❌ jamais |
| Appel réseau | ❌ jamais (l'appel modèle si nécessaire est fait par le MOTEUR — le runner n'est pas en mesure de contourner ni de fuir ; zéro secret dans son environnement) |
| Publication kChat | ❌ direct ; la publication passe par le service N1 existant (le JSON est rendu par le moteur) |
| Lecture/écriture de l'état moteur hors enveloppe | ❌ aucune interface : l'agent ne possède **zéro capability** face au moteur (F-04) — l'inventaire est borné et pseudonymisé côté moteur avant transmission |
| Exécution shell / outils d'écriture | ❌ jamais |

Format d'échange figé : entrée = `{ texte MP (quoted, non interprété, ≤ borne §7), inventaire minimal (refs actives ≤ 30, aliases allowlist, quotas restants) }` ; sortie = JSON strict `{ kind: proposal | clarify | refusal, verb?, target?, display_summary ≤ 300 chars, expires_hint }` — **validé par le moteur** (schéma strict + allowlist verbes/kind **par étape** F-05 + bornes) avant tout traitement ; non conforme → refus + réponse statique. `expires_hint` est strictement informatif (le TTL 30 min est fixé par le moteur) ; tout champ d'autorité (`proposal_id`, `status`, `origin`, TTL) est **absent du schéma de sortie et ignoré par le validateur** s'il apparaît.

## 7. Budgets & quotas (constantes de conception, bornées moteur)

- ≤ **10** sessions headless / jour (compteur partagé avec le quota N1 anti-boucle ; quota de règles = N1 inchangé : 5/jour).
- 1 session = 1 tour = 1 proposition au plus (pas de boucle multi-tours ; « relancer » = nouveau MP = nouveau budget).
- Durée max de session : **60 s** wall-clock (timeout → réponse statique « indisponible », jamais de proposition partielle).
- ≤ **5 propositions actives** d'origine headless simultanées (la borne globale N1 10 actives reste).
- Propositions headless : TTL **30 min**, jamais de règle (§8 : les règles restent N1-only dans ce niveau initial).
- **Borne de longueur du MP libre (F-07)** : ≤ 1 500 chars appliquée côté moteur **avant** routage ; MP excédentaire → réponse statique éducative, jamais de session, aucune consommation de budget (la grammaire N1 borne ses commandes à 256 chars ; le libre ne doit pas devenir une fenêtre d'injection illimitée).

## 8. Découpage progressif (quoi activer, dans quel ordre)

Étape 1 : **synthèse seule** — le MP libre produit une *réponse informative* (résumé de l'état, aide à la décision) SANS proposition exécutable. Risque conditionnel : quasi nul **SI** le rendu est neutralisé (A10), le scoping moteur appliqué (tout `kind: proposal` émis à l'étape 1 → refus sans retraitement) et la purge des traces implémentés — ce sont les **tests de sortie J2 explicites**, pas des jugements qualitatifs (F-09).
Étape 2 : propositions **déplacement ponctuel** (`#ref → alias` seul verbe accepté — allowlist moteur par étape : une sortie émettant un verbe de règle ou toute autre action est refusée quelle que soit sa formulation) — usage unique, TTL court, révocable, effets limités à un message.
Étape 3 (décision séparée, pas dans ce design) : propositions de **règles** en langage libre — exigera une re-conception (impact durable sur la boîte).

L'allowlist verbes/kind **par étape est une constante moteur** (F-05) : le scoping n'est jamais documentaire — une sortie hors périmètre de l'étape active reçoit un refus moteur, sans proposition créée, quel que soit le prompt du runner.

## 9. Plan de livraison (J1-J4) — GO humain requis avant J1

| Jalon | Contenu | Tests de sortie |
|---|---|---|
| **J1** | Contrat (ce document ratifié), 5e gate + re-check à la création, validation de sortie JSON strict + allowlist verbes/kind par étape, précédence de routage (zéro-match seulement, refus N1 finaux), borne MP, routage vers le runner, réponse statique de refus | gate off → comportement N1 identique octet pour octet ; MP reconnu-refusé → même réponse gate ON/OFF ; sortie non conforme → refus ; MP > borne → statique sans session ; quotas appliqués |
| **J2** | Étape 1 du §8 : synthèse read-only (rendu borné, pseudonymisé, neutralisé A10) | **Test runner hostile (F-01)** : zéro écriture ET zéro lecture du répertoire privé, zéro secret en environnement, prouvés sur un runner induit par injection ; tests adversariaux : MP hostile, contenu hostile dans l'inventaire, sorties adversariales (JSON invalide, markdown actif, URL, marqueur, formes `ok #pN`/`#ref →` dans le rendu) toutes neutralisées/refusées ; purge des traces effective |
| **J3** | Étape 2 : propositions déplacement via chemin N1 (§11.4 intégral : figée, TTL, revalidations) | proposition hors verbes N1 rejetée ; kill switch coupé entre proposition et confirmation = aucun write (extension du test N1) ; TTL 30 min ; quotas ; idempotence post_id étendue ; gate re-checkée à la création |
| **J4** | Observabilité + durcissement final : journal verbe/statut sans contenu, purge stockage runner (spot-check), revue sécurité post-implémentation sur code réel, activation conditionnée (GO séparé de l'opérateur) | audit complet des écritures (aucune hors moteur N1) ; matrice de gates en vol à chaque transition (routing / session / création / confirmation) ; audit journal (MPs routés = statut + compteurs, jamais de texte libre) |

**Condition de démarrage J1** : ratification de ce design par l'opérateur + budget de revue sécurité sur l'implémentation (revue re-passée à J4 sur code réel).

## 10. Décisions ouvertes (à trancher par l'opérateur)

1. **Runner** : l'option recommandée (F-01) est le **runner pure-fonction** (stdin JSON → stdout JSON, zéro outil, zéro fichiers, zéro réseau, zéro secret env — l'appel modèle est fait par le moteur) ; l'option session opencode n'est retenue qu'avec isolation OS obligatoire (les denies runtime restent best-effort, ADR-021).
2. Étape 3 (règles en langage libre) : dans le périmètre d'un design futur, pas celui-ci.
3. **Traces & tiers (F-06)** : purge immédiate du stockage runner après traitement (compteur + statut sans contenu) ; périmètre de transmission tiers nommé et assumé (texte MP + sujets masqués → API modèle, rétention côté provider non contrôlable — même posture assumée que V4.2 §10.3.1 pour le sujet).

---

*Ce document ne modifie aucun comportement existant. Il ne crée aucune capacité tant que la 5e gate est absente (défaut false) et que J1-J4 ne sont pas implémentés et revus.*
