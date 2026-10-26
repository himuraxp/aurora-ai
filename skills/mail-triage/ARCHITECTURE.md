# ARCHITECTURE — mail-triage

ADR v1 — validée en boucle de revue Aurora ↔ ChatGPT (3 tours + tour d'exécution, 2026-10-23).
Décision « B+ hybride » : moteur IMAP autonome générique, configuration et règles strictement privées, skill OpenCode comme interface.

## 1. Décision

- Le skill n'est **pas le moteur** : il est l'interface conversationnelle vers un moteur indépendant, capable de fonctionner sans OpenCode (déclenchement scheduler).
- Moteur = scripts Python **stdlib uniquement** (`imaplib`, `email`, `sqlite3`, `urllib`, `json`, `hashlib`) — zéro dépendance npm/pip.
- Code générique dans le dépôt public ; **tout ce qui est personnel vit hors du dépôt** (`~/.config/opencode/mail-triage/` + secrets dans `.env`).
- JSON (pas YAML) : la stdlib Python n'a pas de parseur YAML ; les scripts Python du dépôt consomment tous du JSON.

## 2. Composants

```text
skills/mail-triage/
  SKILL.md            # interface conversationnelle (procédure, jamais auto-exécutive)
  ARCHITECTURE.md     # ce document
  scripts/
    triage.py         # CLI : scan | plan | apply | status | reconcile | digest
    config.py         # chargement + validation du config.json privé (fail-closed)
    policy.py         # règles déterministes, niveaux de risque, invariants, pseudonymisation
    imap_client.py    # wrapper imaplib : TLS, capabilities, fetch en-têtes, UID MOVE
    state.py          # SQLite privé : processed, plans, authorizations, digests + verrous
    digest.py         # fenêtre temporelle + rendu markdown du résumé
    kchat.py          # client kChat minimal (urllib) : DM + posts, idempotent
  templates/          # exemples génériques (jamais de valeurs réelles)
  tests/
```

```text
~/.config/opencode/          # PRIVÉ — jamais dans un dépôt
  .env                       # MAIL_TRIAGE_IMAP_LOGIN, MAIL_TRIAGE_IMAP_PASSWORD,
                             # MAIL_TRIAGE_KCHAT_TOKEN, MAIL_TRIAGE_KCHAT_DM_USERNAME
  mail-triage/
    config.json              # compte, allowlist dossiers, kill switches, options digest
    rules.json               # règles déterministes (id, priorité, match, folder, mode)
    state.sqlite             # UID traités, plans, autorisations, digests
    audit.jsonl              # décisions (rotation courte, pseudonymisé)
```

## 3. Contrat CLI

| Commande | Effet | Écriture |
|---|---|---|
| `scan` | lecture seule : inventaire dossiers, en-têtes récents (plafond 200 UIDs, fenêtre déduite de l'état), évaluation règles — inspection volontaire, sortie lisible **non journalisée** | aucune (lit l'état pour la fenêtre) |
| `plan` | dry-run : construit le plan de déplacements, l'enregistre (SHA-256 d'intégrité, expiration) | state |
| `apply --plan <id> --confirm-apply` | exécute un plan : intégrité (SHA-256) + autorisation + revalidation des préconditions avant CHAQUE déplacement | IMAP + state |
| `status` | état du moteur (config, dernier scan/plan/apply/digest, kill switches) | aucune |
| `workflow [--sync]` | **J4bis** : état read-only des dossiers workflow (« A lire »/« A traiter »/INBOX) + refs non lus ; `--sync` maintient l'état persistant (new→ref `#wN` 48 h, absents→resolved — zéro re-proposition, D6) | state (avec `--sync`) |
| `reconcile [--plan <id>] [--digest]` | réparation après interruption : réconciliation des déplacements incertains et des publications kChat | IMAP + state |
| `digest [--send]` | construit (et envoie si `--send`) le résumé kChat du matin | kChat + state |

Sorties JSON garanties, exit 0/1/2 (0 OK, 1 erreur métier, 2 usage/config). Toute sortie CLI est **pseudonymisée** : jamais de corps de message, jamais d'adresse complète, expéditeur = hash tronqué.

## 4. Séparation intégrité / autorisation / exécution

1. **Intégrité** : empreinte SHA-256 canonique du plan (preuve que le plan n'a pas changé).
2. **Autorisation (V1 — réel)** : le gate d'exécution est la combinaison `--confirm-apply` + vérification de l'empreinte SHA-256 + contrôle d'expiration du plan. **Chaque `apply` exige une confirmation humaine de l'invocation courante** : aucune règle ne s'exécute seule en V1. La table `authorizations` (autorisation liée à l'empreinte, à usage unique — `batch_approved` / `rule_auto_approved`) est **réservée pour V2** (persistance inter-invocations) et non câblée dans le CLI V1.
3. **Exécution** : revalidation des préconditions avant chaque déplacement (compte, UIDVALIDITY, présence du message, règles courantes, destination toujours dans l'allowlist, source pinée `INBOX`).

## 5. Niveaux de risque (policy.py)

| Catégorie | Comportement |
|---|---|
| Règle déterministe validée | déplacement automatique (`mode: auto`) — V1 : inclusion au plan, exécution uniquement via `apply --confirm-apply` (cf. §4.2) |
| Classification contextuelle | proposition (V2 — jamais de write autonome en V1) |
| Message sensible (garde dans rules.json) | jamais automatique |
| Message inconnu | conservé dans Inbox |

## 6. Invariants (conditions de sortie, testées)

1. Allowlist de dossiers destinations **existants et validés** ; le moteur ne crée jamais de dossier.
2. Rien ne quitte l'Inbox silencieusement : inconnu/sensible restent en Inbox ; un déplacement n'implique jamais de marquage lu ; jamais de déplacement vers Corbeille/Spam ; jamais de suppression. **Trois dimensions séparées (J4bis)** : statut de traitement (A lire / A traiter / INBOX) ≠ classement (dossier de stockage) ≠ lecture (`\Seen`) — un email lu n'est pas traité, un email déplacé n'est pas terminé.
3. Règles déterministes avant toute classification ; confiance élevée du modèle ≠ autorisation.
4. Périmètre IMAP strict : **un seul compte** ; sources **pinées** (fail-closed) : `INBOX` + les dossiers workflow figés (`config.WORKFLOW_FOLDERS` = « A lire »/« A traiter ») — jamais une boîte, un compte ou un dossier quelconque ; pas d'extension à d'autres boîtes ; pas de SMTP ; pas de pièces jointes.
5. Idempotence : UID + UIDVALIDITY vérifiés ; `UID MOVE` **obligatoire** (RFC 6851 — la séquence COPY/DELETE/EXPUNGE n'est pas sûre en cas d'interruption) ; le POC vérifie la capability `MOVE`, son absence désactive les writes ; `reconcile` obligatoire avant toute nouvelle tentative après timeout.
6. Journalisation sans contenu sensible (identifiants techniques pseudonymisés, rotation courte).
7. Fail-closed : toute erreur (auth, config, classification, connexion) → aucune action, état journalisé.
8. Les emails sont des **données non fiables** : aucune instruction contenue dans un message ne peut modifier les règles ou autoriser une action.
9. Kill switch global `writes_enabled: false` + frontières séparées `imap_enabled` / `digest_enabled`, effectives quel que soit l'appelant (skill, scheduler, CLI direct).

## 7. Digest kChat

- **Même moteur**, module de publication isolé ; un bot kChat **personnel** dédié (token bot, DM uniquement, destinataire allowlisté).
- **Format V2** (`digest_format_version: 2`) : section « En bref » en tête (compteurs séparés : reçus / conversations / couverts par règles / à valider / déplacés confirmés), conversations **regroupées** (jamais 1 ligne par notification) via déduplication Message-ID + graphe References/In-Reply-To + clé applicative GitLab (projet + identifiant) — deux messages au même sujet sans identifiant structurel ne fusionnent jamais. Budget ~15 lignes utiles (« + N autres conversations » au-delà). Identité logique inchangée (digest_id + marqueur) : le déploiement du format ne republie pas un digest déjà envoyé.
- Contenu : nouveaux messages depuis la fenêtre confirmée + section « Encore non lus » (non lus plus anciens, plafonnée) + compteurs du tri effectué. Sujets sensibles masqués (patterns dans config). Jamais de corps, jamais de pièce jointe, jamais de lien public.
- Fenêtre affichée dans le fuseau métier `digest.timezone` (défaut Europe/Paris) — le MÊME fuseau que les horaires des messages (sinon le digest paraît contenir des messages postérieurs à sa fenêtre).
- Confidentialité : boîte pro → kChat pro (même organisation) — expéditeurs/sujets lisibles assumés ; tout autre périmètre exige une décision explicite.
- Fenêtre temporelle : dates de réception normalisées (UTC) + identifiants techniques — jamais uniquement un filtre IMAP `SINCE` (granularité journalière) ; la fenêtre suivante commence au dernier point de coupure confirmé.
- Idempotence : garde SQLite (dernier digest confirmé) + marqueur unique dans le message ; une publication incertaine (timeout) est **réconciliée** (`reconcile --digest`), jamais repostée aveuglément.
- Scheduler : launchd `StartCalendarInterval` 07:30 (heure de l'hôte, timezone configurable `digest.timezone`, défaut `Europe/Paris`) + `RunAtLoad` + garde SQLite — un horaire manqué (Mac endormi) n'est rattrapé qu'au chargement du job (limite documentée).

## 8. Jalons

| Jalon | Livrable | Critère de sortie |
|---|---|---|
| J1 | ADR, contrats CLI, squelette | architecture + schémas figés |
| J2 | IMAP read-only, règles, policy, tests | scan déterministe testable sans compte réel |
| J3 | app password + POC IMAP réel | lecture réelle, capabilities + dossiers vérifiés |
| J4 | digest kChat + tests | premier digest réel en DM, sans mutation IMAP |
| J5 | UID MOVE, apply, reconcile | déplacements sur dossier test, sans doublon |
| J6 | launchd, revue, PR | tests de reprise et de confidentialité validés |

## 9. Limites documentées (V1)

- Classification IA absente (V2, mode proposition uniquement).
- Catch-up au réveil limité à `RunAtLoad` (un Mac endormi qui se réveille sans reboot ne déclenche pas le digest).
- Fenêtre de scan plafonnée à **200 en-têtes récents** (`fetch_recent_headers`, cap volontaire).
- Noms de dossiers non-ASCII (ex. mUTF-7) hors périmètre : allowlist ASCII imprimable, espaces internes incluses — fail-closed au chargement.
- Un seul compte ; sources pinées (`INBOX` + dossiers workflow « A lire »/« A traiter », J4bis).
- **[F-05, review J4] Crash du poller entre l'enregistrement d'une commande et la publication de sa réponse kChat** : la commande est marquée traitée (idempotence `post_id`), la réponse est **perdue (muet)** — jamais de rejeu automatique (l'alternative, une double réponse possible, est pire). L'opérateur voit l'absence de réponse et relance `aide`/`statut`.
- **[F-07, review J4bis] Réconciliation d'une clôture interrompue** : le Message-ID n'est pas persisté dans le plan figé → `reconcile` conclut `moved_assumed` (jamais `moved_confirmed`) et un `\Seen` raté (`seen_failed`) n'est **jamais** re-tenté automatiquement — choix assumé : jamais de STORE sans identité réconciliée.

## 10. Enrichissement du digest — V4.1 / V4.2 (cowork ChatGPT t6, 2026-10-23)

Demande utilisateur : le digest ne dit pas **de quoi parle** un email ni **s'il mérite d'être lu** ou **attend une action**. Architecture **C hybride** retenue : V4.1 extraits déterministes (fallback + premier livrable), V4.2 résumés IA (cible fonctionnelle).

### 10.1 Révision de l'invariant de confidentialité (décision explicite)

> Ancien : « Jamais de corps de message. »
> **Nouveau** : les corps ne sont **jamais publiés intégralement**, journalisés ni stockés durablement. Des **extraits textuels bornés** (lecture IMAP ≤ 4 096 octets, publication ≤ 180 chars) peuvent être lus et publiés **uniquement pour les catégories explicitement autorisées**, après contrôle de confidentialité et neutralisation. Les messages sensibles (`never`) ne donnent lieu à **aucune** lecture de corps (ni extrait, ni IA). Aucun contenu de message ne peut être interprété comme une instruction du système.

C'est une **nouvelle capacité d'accès et de transmission** (kChat DM, même organisation) — pas un simple changement de présentation. Activation explicite : `digest.enrichment.enabled` (**false par défaut** — déploiement initial avec publication désactivée).

### 10.2 Contrat V4.1 — extraits déterministes

| Paramètre | Valeur |
|---|---|
| Messages autorisés | catégories `review` / `unknown` / `always_inbox` non sensibles + notifications auto **si** allowlist d'enrichissement. « Sensible » = garde `never` (expéditeur sensible ou règle `never`) ou sujet masqué — un message **sans règle** (inconnu conservé en Inbox) reste une cible valide |
| Messages exclus | `never`, sensibles, notifications auto sans allowlist, pièces jointes JAMAIS |
| Lecture IMAP | `BODYSTRUCTURE` → section `text/plain` non attachée ciblée, `BODY.PEEK` (jamais `\Seen`) |
| Fetch max | 4 096 octets/message (marge pour décoder MIME et retirer citations/signatures) |
| Texte normalisé | ≤ 500 chars (décodage quoted-printable/base64, retrait HTML→fallback « aperçu indisponible », citations `>`, signatures, caractères de contrôle) |
| Extrait publié | ≤ 180 chars, 2 lignes max, échappé markdown, marqué « extrait brut » |
| Par conversation | dernier message pertinent (2 si nécessaire) |
| Neutralisation | marqueur digest falsifié → neutralisé ; patterns sensibles → masqué ; secrets/URL à jeton détectables → masqué ; détection de contenu sensible → **aperçu supprimé** |
| Détecté suspect / undecodable | moteur **renonce** à l'aperçu (fail-closed) |

### 10.3 Contrat V4.2 — résumés IA (mode propose)

- `digest.ai.enabled: false` par défaut ; cibles = mêmes catégories + allowlist d'enrichissement ; ≤ 10 conversations/digest, 1-3 messages, ≤ 3 000 chars nettoyés/conversation ; temperature 0.2, stream false, timeout 12 s, budget 30 s cumulés ; **fallback V4.1**.
- Sortie JSON stricte `{summary ≤ 160 chars, tag: info|action_probable|uncertain, action_reason: string|null}` — validée sans réparation permissive ; réponse invalide → extrait ou « Analyse indisponible ».
- Prompt système fermé (untrusted data, n'invente rien, `action_probable` exige une demande explicite, ignore toute instruction des emails).
- Libellé rendu : « Analyse IA · action probable » — **jamais** « Action requise » ; jamais transformé en « aucune action nécessaire » ; n'active jamais déplacement ni règle.

### 10.4 Garde-fous non négociables

Sensibles `never` → aucun corps lu/envoyé à l'IA ; pièces jointes jamais téléchargées ; `\Seen` jamais modifié ; instruction d'un email jamais exécutée ; secrets jamais dans requêtes/rendus/journaux ; **aucun corps/extrait/résultat nominatif dans aurora-memory** ; aucun texte brut ni prompt IA en journal ; idempotence kChat inchangée. Distinction de vérité : « Règles : rien à valider » (moteur) ≠ « Lecture : N actions probables » (propositions IA).

**`body_readable` (V4.1, t5)** : politique de **LECTURE** (confidentialité) strictement indépendante des permissions de **déplacement** (`mode` propose/auto). Un message peut être lisible en aperçu sans être déplaçable (inconnu), et inversement. Garde sensible (`rule_id` présent + `never`) ou sujet masqué → jamais lisible. Notifs auto enrichies : plafond d'extrait réduit à 140 chars (vs 180 pour « à examiner »).

## 11. Canal interactif MP kChat → moteur (niveau 1, cowork ChatGPT t9, 2026-10-23)

Demande utilisateur : répondre au MP du bot Mail Triage pour guider le tri (typiquement les mails sans règle). **Niveau 1 : commandes en liste blanche stricte, zéro IA** ; le niveau 2 (langage libre → Aurora headless) se branchera sur la même fondation. Modèle cible : *kChat reçoit une intention → le moteur construit une proposition → le propriétaire confirme → policy.py autorise ou refuse → le moteur exécute et journalise*. Le MP n'est **jamais** une autorité supérieure à `policy.py` et ne contourne jamais le registre d'autorisations.

### 11.1 Séquence d'exécution (J1–J5)

| Jalon | Contenu | Statut |
|---|---|---|
| J1 | Contrat (cette section), tables SQLite, format digest V4 (refs courtes) | livré |
| J2 | Poller read-only (`listen --once`) : pagination exhaustive, aide/statut | livré, **APPROVED t10** (validé en prod : « aide » traité + idempotence) |
| J3 | Propositions (grammaire complète, résolution refs/dossiers, non exécutables par défaut) | GO t10 — 3 P0 à intégrer |
| J4 | Confirmations + règles (réutilisation plan/apply/reconcile, tests adversariaux de concurrence) | **livré (2026-10-26)** — consommation atomique, exécution figée, 9 tests de sortie passés |
| J5 | Production contrôlée (launchd StartInterval 300, reprises crash, activation writes séparée) | à venir |

### 11.2 Permissions séparées (P0, t9)

Quatre gates indépendants : **lecture interactive** (`interactive.enabled` — aide/statut, read-only) ≠ **création de propositions** ≠ **écriture de règles** (`writes.interactive_rules`, J4) ≠ **déplacement IMAP** (`writes.imap_enabled`, existant). Le poller read-only fonctionne même quand les mutations sont désactivées. Toute mutation interactive exige `writes.enabled` ET le gate dédié.

### 11.3 Collecte des commandes (P0, t9)

Curseur **create_at seul interdit**. Algorithme : FileLock exclusif partagé → collecte **paginée exhaustive** (`before` chain, chevauchement de sécurité, cap MAX_PAGES) → tri `(create_at, post_id)` → filtre expéditeur `== recipient_id` exact + canal DM bot–propriétaire exact + post non édité (`edit_at == 0`) et non supprimé → **registre SQLite `post_id` PRIMARY KEY** (idempotence, rejeu impossible) → traitement ordonné → publication de la réponse → **checkpoint avancé seulement après traitement complet de la fenêtre** (pagination incomplète = checkpoint gelé, jamais d'avance sur un trou). Premier run = baseline sans traitement des messages antérieurs. Posts édités/supprimés : jamais porteurs d'autorisation ; une confirmation supprimée après exécution n'est pas une révocation rétroactive. Aucune pièce jointe ni réaction emoji interprétée comme commande. Audit : verbe + statut + post_id, jamais le texte intégral du MP.

### 11.4 Autorisations à usage unique (P0, t9)

Le `ok #p1` du propriétaire est une **autorisation distante validée** (pas un simple texte) : `proposal_id` opaque unique non réutilisé, `owner_user_id` exact, `channel_id` DM autorisé, `action` structurée et **figée**, `target` (UID ou règle), `target_version` (empreinte des préconditions — changement de règles entre proposition et confirmation → refus), `created_at`/`expires_at` (**30 min** déplacement ponctuel, **24 h** règle), `status` (pending/executing/applied/rejected/uncertain/expired), `source_post_id`, `confirmation_post_id`. La confirmation ne couvre **jamais** une opération plus large que la proposition. Réutilisation du même moteur d'autorisation que la CLI (`plans` + `authorizations` + `policy.py`) : le MP produit une autorisation traçable, jamais un apply direct.

### 11.5 Références courtes (P0, t9 + **correction t10**)

Format digest **V4** : chaque conversation « À examiner » → `#a1…`, « En attente » → `#n1…`, « Encore non lus » → `#l1…`. Une référence = **un seul message** (le dernier de la conversation — jamais un thread entier), liée à `(digest_id, mailbox, uidvalidity, uid, expéditeur, sujet)`, immuable, non réassignée, **expire 48 h** après publication. `#a1 → dossier` = déplacement **ponctuel** du message désigné ≠ `expediteur X → dossier` = création de **règle future** — jamais confondus, jamais de règle implicite déduite d'une réponse à une référence.

**Correction t10 (P0)** : la résolution « digest le plus récent non expiré gagne » est **révoquée** — risque de déplacer le mauvais message (l'utilisateur répond à la notification de lundi, le moteur résout #n1 vers le digest de mardi). Contrat J3 : références **globalement non ambiguës** pendant leur durée de validité (compteur monotone à la construction, jamais réutilisées tant qu'une ref identique est active — et jamais réutilisées immédiatement après expiration si un message retardé peut encore arriver). **Une commande ambiguë est REFUSÉE, jamais résolue arbitrairement.**

### 11.6 Grammaire niveau 1 + destinations (P1, t9)

Verbes : `aide`, `statut`, `#ref → dossier`, `expediteur <addr> → dossier`, `domaine <domaine> → dossier`, `ok #p1`, `annule #p1` — regex ancrées, ≤ 256 chars, tout le reste → réponse générique (jamais d'exécution de texte libre). Un message `#ref <texte libre>` (sans flèche, ex. `#a1 : quand…`) reçoit une **aide au format** éducative — le texte n'est jamais exécuté. Destinations : **alias stricts** résolus depuis la config (`corbeille` → chemin IMAP validé), allowlist imposée, dossier interdit → **refus immédiat sans proposition** (une confirmation humaine ne légitime jamais une destination interdite), jamais de chemin arbitraire ni de création de dossier implicite (la création de dossier ne se fait pas via le MP). Règles interactives : toujours **mode propose**, pas de promotion auto depuis le MP ; domaine = plus puissant que l'expéditeur exact (priorité expéditeur 150 > domaine 155, portée du domaine confirmée explicitement). **Sémantique des matchs (F-03, figée J4 2026-10-26)** : les règles interactives « expediteur » utilisent le match **ADRESSE EXACTE dédié `from_exact`** (jamais la sous-chaîne de `from_any`) — « bob@x.com » n'attrape ni « bob@x.com.evil.tld » ni « a+bob@x.com@attacker.io » ; `config.py` rejette toute valeur `from_exact` sans `@` ou avec espace. `from_any`/`from_domain_any` restent des correspondances par sous-chaîne pour les règles manuelles existantes. Limites (configurables, bornées moteur) : 5 règles interactives/jour, 10 propositions **actives** simultanées (les expirées libèrent le budget, F-01), 30 commandes/5 min, 256 chars/commande ; le quota quotidien de règles compte les annulées (anti-boucle annule/recrée).

### 11.7 Écriture des règles (P1, t9) + non-propriétaires — **livré (J4, `rules_writer.py`)**

Service **unique** de mutation `rules.json` (`scripts/rules_writer.py`) : verrou dédié `rules.lock` → charger l'état courant → **idempotence `operation_id`** (règle identique déjà présente = `already_applied` réconcilié, contenu divergent = `conflict` jamais écrasé) → revérifier l'empreinte **SHA-256 globale** de rules.json SOUS verrou (= `target_version` de la proposition, divergence = refus sans write) → validation schéma complète (`validate_rules_doc`) → plafond (100 règles) → tmp 0600 + fsync + `os.replace` → backup de la dernière version valide (0600, même répertoire privé) → recharger et revalider (échec = rollback vers la version précédente). Traçabilité `operation_id` dans `rule_operations` (SQLite) : réconciliation sans ambiguïté après une coupure suivant le remplacement, jamais de doublon. **Non-propriétaires : ignore total** — aucune réponse, aucune proposition, aucun détail des commandes ; compteur technique d'événements ignorés sans contenu.

### 11.8 Conditions t10 pour l'activation des mutations (J3-J5, 2026-10-26)

Verdict t10 : **APPROVED — GO J3-J5** sans nouvelle revue d'architecture ; l'**activation** des mutations est conditionnée aux P0 suivants :

- **[P0-J3] Références non ambiguës** (§11.5 corrigé) — jamais « dernier digest gagne ».
- **[P0-J4] `ok #p1` atomique et lié** : UPDATE conditionnel (pending→executing) = réservation atomique correcte mais ne garantit pas l'exécution exactly-once de l'effet externe IMAP — séquence : confirmation (owner+DM+post_id) → executing (txn validée) → **revalidation** policy+plan+cible (SHA-256 **global** de rules.json, compte, source, UID/UIDVALIDITY, chemin canonique figé) → apply → applied/uncertain (réconciliable, jamais deux fois).
- **[P0-J4] Idempotence mutations + réponses kChat après crash** (crash entre publication réponse et checkpoint : garanti par le registre post_id + publication APRÈS avancement ; à démontrer par test avant J5).
- **[P1-J3] La proposition affiche le chemin IMAP canonique résolu** (« Déplacement proposé : #n1 → INBOX/Auto/News ») ; l'allowlist ne neutralise **jamais** les exclusions absolues (Trash/Spam/Drafts/Sent, y compris noms localisés).
- **[P1-J5] Verrou dédié couvrant toute l'exécution de `listen --once`** (poller > 300 s = pas de seconde exécution concurrente) + verrou de mutation distinct ; verrou périmé = âge dépassé ET propriétaire absent (protection réutilisation PID).

**Tests de sortie exigés (9)** : ref d'ancien digest non déplaçable après réutilisation de #n1 ; alias interdit/supprimé entre proposition et confirmation = aucun write ; règles modifiées = confirmation refusée ; deux confirmations concurrentes = une seule transition executing ; crash avant/après UID MOVE = aucune répétition aveugle ; crash après os.replace(rules.json) = règle reconnue sans duplication ; réponse kChat publiée puis timeout = aucune réexécution ; poller > 300 s = pas de concurrence ; kill switch désactivé entre proposition et confirmation = aucun write.

**Statut J4 (2026-10-26)** : les 9 tests de sortie sont **implémentés et verts** (`tests/test_confirmations.py`, FakeConn IMAP zéro réseau) — suite complète **238/238 sur Python 3.14 (dev) ET 3.9.6 (LIVE)**. Implémentation : `_handle_ok` (cross-check owner+DM+pending → **réservation atomique** `reserve_proposal` (UPDATE conditionnel pending→executing, usage unique) → gates (§11.2 : `writes.enabled` + `imap_enabled` pour move / `interactive_rules` pour règle) → **revalidations** (SHA-256 global rules.json = `target_version`, allowlist, invariants absolus) → exécution du contenu **FIGÉ** dans `proposals.action` (plan `interactive-{pid}` construit depuis l'action, jamais re-résolu depuis les digest_refs) → applied/partial/uncertain/rejected. Sweep `timeout_stale_executing` (executing > 26 h → uncertain, jamais re-consommable). Réutilisation du cœur CLI : `run_plan_apply`/`_run_plan_checked` (triage.py) — mêmes verrous apply.lock, mêmes revalidations, même chemin reconcile.

## 12. Workflow « A lire » / « A traiter » (J4bis — cowork ChatGPT APPROVED, 2026-10-26)

Mandat : réorganiser la consommation de la boîte par **statut de traitement** (« je lis ce qui attend ») sans fusionner ni migrer les 20 dossiers historiques. Boucle cowork 3 tours → **APPROVED** (thread `6adb268a…`, décisions D1–D7 figées).

### 12.1 Schéma cible (D1, D2)

- **INBOX** = réception / classification / filet de sécurité (jamais obligatoirement vide) ; inconnus et sensibles y restent sans autorisation explicite (D5).
- **« A lire »** = informations à consulter, sans action identifiée. **« A traiter »** = décision/validation/réponse attendue. Dossiers IMAP réels créés **manuellement** par l'opérateur (jamais par le moteur) ; noms ASCII (gate mUTF-7, §9) ; aliases kChat `lire`/`traiter`.
- Les 20 dossiers historiques = **stockage final** — aucune fusion, aucune migration massive, jamais de marquage lu en masse des ~18 k / 40 k existants.

### 12.2 Trois dimensions séparées + sémantique des modes (D3)

**Statut de traitement** (A lire / A traiter / INBOX) ≠ **classement** (dossier de stockage) ≠ **lecture** (`\Seen`). Modes auto/propose/never **inchangés** ; nouvelle clé de règle optionnelle **`workflow_target`** (`policy.py`/`config.py`, fail-closed : valeur hors `WORKFLOW_FOLDERS` = PolicyError/ConfigError) :

- Règle avec `workflow_target` : le **déplacement initial** vise le dossier workflow (le message **attend**) ; `folder` (optionnel) = stockage final appliqué à la clôture « traité » — `folder` seul = comportement historique inchangé (déplacement direct au stockage).
- **[F-06, review J4bis]** `final_folder` dans la sortie de `policy.evaluate` est **informatif** : il n'est jamais consommé automatiquement. La clôture exige une destination de stockage **explicite dans la commande** (`traite #ref → alias`) qui **prime** — une règle avec `folder` ne préjuge pas de la destination de clôture (l'opérateur décide au moment T, pas la règle au moment de sa création).
- Règles nouvelles = **futurs messages seulement** (jamais de re-scan rétroactif) ; sans règle : INBOX.

### 12.3 Politique `\Seen` (D4)

Le classement **préserve `\Seen`** (aucun STORE au déplacement). La **seule** voie vers « lu » est la clôture explicite « traité » : déplacement stockage + `STORE +FLAGS \Seen` **sous autorisation** (proposition confirmée / apply CLI) et **réconciliation de l'identité** du message dans la destination (SEARCH `HEADER Message-ID` — l'UID change au MOVE) **avant** tout STORE ; cible introuvable = uncertain, jamais de `\Seen` aveugle. Jamais de marquage lu en masse.

### 12.4 Séparation scan / état workflow (D7, D6) — **livré (J4bis, 2026-10-26)**- `scan` : comportement actuel (INBOX → plan, sources pinées étendues aux dossiers workflow).
- `workflow` (read-only, `--sync`) : état de « A lire » / « A traiter » / INBOX — comptages + refs `(mailbox, uidvalidity, uid)`, **zéro reclassification**, jamais de re-scan des 20 dossiers historiques. `--sync` maintient `workflow_items` (SQLite) : new→ref `#wN` active (48 h, compteur partagé, jamais de doublon), absents du dossier→resolved (`uncertain` reste uncertain — réconciliation opérateur), réapparition d'un résolu → **jamais réintroduit**.
- Plans/refs liés au **dossier source** (`mailbox + uidvalidity + uid` partout : payload, digest_refs, `_revalidate_preconditions` sur `move["from_folder"]`) — les dossiers workflow sont suivis, jamais re-scanés en boucle.
- Digest workflow : section « En attente de traitement » (items new/pending **avec ref active** uniquement — cap 5, total affiché ; activation progressive : section absente si vide) ; resolved/uncertain jamais listés.
- Clôture « traité » : **livrée** — grammaire `traite #ref → alias` (destination explicite, sans flèche = aide), proposition `treat` (budget/TTL déplacement ponctuel, item→pending), exécution = move + fetch Message-ID source **avant** move + STORE `+FLAGS \Seen` sur la destination **après** réconciliation identité (cible absente/ambiguë = uncertain `seen_failed`, jamais de `\Seen` aveugle) — idempotente (usage unique), réconciliable (chemin reconcile existant). **Limite F-07 (§9)** : le Message-ID n'étant pas persisté dans le plan, une clôture interrompue se réconcilie en `moved_assumed` et le `\Seen` raté n'est jamais re-tenté.
- `workflow_target` (D3) : validé fail-closed (`config.WORKFLOW_FOLDERS`), destination du déplacement initial, `folder` = stockage final de la clôture.

### 12.5 Dispatch auto des lus dans « A lire » (décision utilisateur, 2026-10-26)

Demande explicite du propriétaire : quand un email du dossier « A lire » est **lu** (`\Seen` posé par la lecture humaine dans le client mail), il est **dispatché automatiquement** vers son stockage final — complément de la clôture explicite « traité » (qui reste disponible). Sémantique : la lecture humaine devient un **signal de clôture autorisé** (le moteur n'écrit toujours JAMAIS `\Seen`).

- **Destination jamais implicite** : elle vient de la **règle courante** réévaluée sur l'en-tête au moment du dispatch (`policy.evaluate` → `final_folder` = `folder` de la règle) ; aucune règle déterminée, ou `folder` absent de la règle → le message **reste** dans « A lire » (fail-safe).
- **« A traiter » n'est pas concerné** : la lecture n'y suffit pas (une action est attendue) — dispatch limité à `WORKFLOW_FOLDERS[0]`.
- **Garde-fous** : items `pending`/`uncertain` jamais dispatchés (une clôture est peut-être en vol) ; allowlist + existence serveur revalidées (PolicyError → skip) ; erreur IMAP → item `uncertain` réconciliable, **jamais re-dispatché automatiquement** ; items hors cap de scan attendent ; journal + `mark_processed` + état `resolved`.
- **Déclencheur** : `workflow --sync` (`_dispatch_read_items`) — tout move est révocable, jamais de suppression ; `\Seen` préservé au move (déjà posé par l'humain).
