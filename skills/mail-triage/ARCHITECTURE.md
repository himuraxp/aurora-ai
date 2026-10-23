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
2. Rien ne quitte l'Inbox silencieusement : inconnu/sensible restent en Inbox ; un déplacement n'implique jamais de marquage lu ; jamais de déplacement vers Corbeille/Spam ; jamais de suppression.
3. Règles déterministes avant toute classification ; confiance élevée du modèle ≠ autorisation.
4. Périmètre IMAP strict : compte + source **pinée `INBOX`** (fail-closed au chargement) ; pas d'extension à d'autres boîtes ; pas de SMTP ; pas de pièces jointes en V1.
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
- Un seul compte, une seule boîte source (`INBOX`).
