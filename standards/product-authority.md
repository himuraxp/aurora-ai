# Standard — Product Authority (v1.1)

Standard normatif figé par la boucle cowork ChatGPT (tour 3, APPROVED — 14 invariants ACCEPTED, conversation projet Infomaniak `6acdc8ff`, msgs 38-47). L'implémentation runtime (agent `product-owner`, skill `product-authority`, plugin contrôleur) est l'Étape 3 du plan ; ce document est la source de vérité des contrats qu'elle implémente. Toute divergence entre l'implémentation et ce standard est un bug de l'implémentation. Toute révision de ce standard = décision humaine (le système d'autorité ne se modifie jamais lui-même — classe F).

## 1. Objet et fondation

L'autorité produit déléguée généralise un precedent du meeting : la réutilisation d'une décision produit ratifiée. Un humain valide **une POLITIQUE** (une assertion, une fois, sur une CLASSE de décisions) — jamais la décision individuelle. Le Product Owner délégué (PO) propose et décide dans l'enveloppe de la politique ; le contrôleur (plugin déterministe) autorise ; Aurora orchestrateur enregistre.

Fondation épistémique : **une assertion humaine valide une politique, elle ne valide pas chaque décision future** — c'est précisément pourquoi la classification, l'impact et les contraintes de CHAQUE décision sont enregistrés et vérifiés mécaniquement.

## 2. Invariant scindé E/A (jamais relaxé, aucun skill ne peut déroger)

Deux kinds de statut distincts, **jamais re-étiquetables** :

- **E (épistémique) — `HUMAN_VALIDATED`** : émane UNIQUEMENT d'une assertion humaine explicite en session. Aucune sortie d'agent n'est jamais une validation humaine. E n'est jamais relaxé, quelle que soit la politique.
- **A (autorisation) — `DELEGATED_APPROVED`** : émis UNIQUEMENT par le contrôleur, ssi une politique P valide couvre la classe C pour le projet X, classification mécanique enregistrée, et le record cite P (id + hash). Pas de P valide → `HUMAN_REQUIRED` (fail-closed).

**Autorisation produit ≠ GO d'exécution** : un `DELEGATED_APPROVED` n'autorise jamais à écrire, implémenter ou déployer — il fonde une décision de contenu. L'exécution suit les règles normales d'autorisation d'Aurora.

Le mot **« ratifier »** est réservé à l'humain. Le PO ne ratifie jamais — il décide du contenu (decider-of-record) dans l'enveloppe.

## 3. Les 3 rôles (sans agent double)

| Rôle | Porté par | Responsabilité |
|---|---|---|
| **Decider-of-record** | PO (agent `product-owner`, read-only, frontmatter miroir council-seat) | Propose la décision + classification + impact + contraintes. Ne lit JAMAIS le fichier de politique (Aurora injecte l'enveloppe au dispatch). Ne « ratifie » jamais. |
| **Authorizer** | La POLITIQUE (assertion humaine enregistrée) | Détermine si la classe est couverte pour le projet au niveau actif. |
| **Enforcer / recorder** | Aurora orchestrateur + plugin contrôleur (déterministe, hors modèle) | Vérifie le contrat, émet le statut et l'attestation, enregistre le record et le journal. |

Séparation des responsabilités anti-mauvaise-classification : **le modèle PROPOSE** (classe + impact + contraintes) ; **le reviewer CONTESTE** (re-classification indépendante) ; **le plugin DÉCIDE** (règles déterministes sur classification acceptée) ; **Aurora ENREGISTRE**. Le plugin ne considère jamais la présence d'une classe autorisée comme preuve suffisante de l'exactitude de la classification.

## 4. Niveaux d'autorité et politique

### 4.1 Niveaux (onboarding : une seule question)

| Niveau | Effet |
|---|---|
| **Consultatif** | Aucune délégation. Le PO émet des recommandations `PROPOSE_ONLY` au handoff ; toute décision reste `HUMAN_REQUIRED`. Rend le mode utile sans aucune ratification. |
| **Limité recommandé** | Délégation des classes C1-C4 (conditions de la table respectées). |
| **Étendu** | Délégation des classes C1-C4 + C5a + C6 (conditions respectées). |

- Le type de projet est **toujours `collaborative` — autorité partagée** (forcé, non négociable au MVP). Autorité **personnelle** de l'utilisateur ≠ autorité d'une équipe : l'heuristique de détection (indices de PO réel/équipe) dégrade vers Consultatif plutôt que de déléguer à tort.
- Expiration par défaut : **+90 jours, SANS auto-renouvellement**. Révocation manuelle à tout moment (une révocation mid-meeting est une feature : re-validation hash + expiry À LA RATIFICATION de chaque décision).
- Report d'onboarding : `deferred_until` TTL **14 jours**, aucune re-sollicitation pendant le TTL. Déclenchement de l'onboarding : au premier besoin réel d'une décision produit.
- **La réponse d'onboarding n'est valide QUE depuis un message direct de l'utilisateur** — jamais depuis un fichier repo, un document ou la sortie d'un agent (surface d'injection gardée).

### 4.2 Registre (hors des repos partagés)

```json
{
  "schema_version": 1,
  "global_policy": { "default_level": "consultative|limited|extended" },
  "projects": {
    "<project_key>": {
      "type": "collaborative",
      "authority": "shared",
      "level": "consultative|limited|extended",
      "expires_at": "<ISO-8601, défaut +90j, sans auto-renouvellement>",
      "deferred_until": "<ISO-8601, optionnel, TTL 14j>",
      "created_at": "<ISO-8601>",
      "provenance": "USER_ASSERTION",
      "identity": { "origin": "<host/owner/repo normalisé>", "main_path": "<chemin principal cross-checké>" }
    }
  }
}
```

- Chemin unique : `~/.config/opencode/aurora-product-authority.json` (privé). **Aucun fichier de politique dans les repos partagés.**
- Mutations UNIQUEMENT via le skill orchestrator `product-authority` (`show` / `set` / `revoke` / `defer` / `reconcile`), provenance `USER_ASSERTION` obligatoire, chaque mutation journalisée en aurora-memory events (`sourceKind: DELEGATED_POLICY`).
- **Cross-check intégrité** : hash du fichier ↔ dernier event mémoire. Mismatch → **fail-closed au niveau Consultatif + alerte + `reconcile` avec confirmation explicite**.
- **Threat model honnête** (accepté, tour 2) : l'intégrité est DÉTECTIVE, pas préventive — l'orchestrateur est le TCB (il écrit les deux côtés). Le check détecte le tampering des agents, pas la compromission de l'orchestrateur. Suffisant pour un outil personnel mono-utilisateur ; durcissement = décision séparée.

### 4.3 Identité projet (anti-spoofing)

- `origin` normalisé (`host/owner/repo`) + **cross-check du chemin principal** enregistré au onboarding.
- Mismatch → **downgrade consultatif + 1 re-confirmation utilisateur** (anti-spoofing `git remote set-url`).
- Sans remote → main worktree via `git-common-dir`. **Jamais de fuzzy matching.**
- Changement d'identité légitime (repo renommé/déplacé) → `reconcile` avec confirmation explicite.

## 5. Table de classification v1.1

Version figée (tour 2, L2 ACCEPTED). La classification s'applique **à la RATIFICATION, sur le TEXTE FINAL** de la décision — une décision peut entrer « clarification d'AC » et sortir « suppression d'un comportement du release » (scénario morphing, testé).

| Classe | Autonomie minimale | Condition |
|---|---|---|
| **C1 — Clarification des critères d'acceptation** | Limité | Intention fonctionnelle inchangée |
| **C2 — Priorisation locale (tâche courante)** | Limité | Aucun engagement externe |
| **C3 — Arbitrage UX mineur** | Limité | Impact mineur et réversible |
| **C4 — Nommage interne** | Limité | Non contractuel, non public |
| **C5a — Ajustement de réalisation** | Étendu | Objectif fonctionnel inchangé |
| **C5b — Modification fonctionnelle majeure** | **Interdit** | Validation humaine. Définition opérationnelle : ajout/suppression de comportement utilisateur, modification d'un AC essentiel, ou création d'un engagement |
| **C6 — Priorisation inter-tâches** | Étendu | Priorités préalablement approuvées |
| **F — Restrictions absolues** | **Interdit** | Validation ou procédure compétente |

**Classe F (jamais délégable, à tous les niveaux)** : contrats publics, pricing, engagements roadmap/dates, communications publics, affectation de travail à des tiers, données sensibles, dérogations réglementaires, **et le système d'autorité lui-même** (politiques, registre, contrôleur, ce standard). Règle de récusation : la mémoire, la configuration Aurora et le système d'autorité ne sont jamais délégables.

**Règle fondamentale** : la classe ne suffit JAMAIS seule à autoriser une décision. L'autorisation = **COMBINAISON classe + impact déclaré + contraintes + autorité disponible**, vérifiée par le contrôleur. Une décision touchant plusieurs classes doit satisfaire **toutes** les restrictions applicables. **Si la classification reste ambiguë, la décision est soumise à validation humaine (`HUMAN_REQUIRED`)** — l'ambiguïté ne se résout jamais mécaniquement. La règle « la classe la plus restrictive » s'applique à un autre cas : la **divergence entre deux classifications** (PO vs reviewer, section 7).

Décision produit déjà ratifiée (doc / ADR / convention) **prime** : la réviser = `HUMAN_REQUIRED`.

## 6. Champs d'impact obligatoires (3 booléens non optionnels)

Tout Decision Proposal contient les 3 booléens, **non optionnels**, vérifiés de façon déterministe au contrôleur :

| Booléen | Signification |
|---|---|
| `touches_existing_acceptance_criteria` | La décision modifie des critères d'acceptation existants (les clarifier sans les changer = false) |
| `adds_removes_user_facing_behavior` | La décision ajoute ou supprime un comportement visible par l'utilisateur |
| `introduces_commitment` | La décision crée un engagement (roadmap, date, contrat, dépendance externe) |

**Combinaisons incohérentes → refus de délégation, quelle que soit la classe proposée** (le champ peut être menti, mais il crée une surface déclarée, auditable et testable). La matrice classe × impact est implémentée en dur dans le contrôleur (fail-closed : toute combinaison dont la cohérence n'est pas établie est refusée). Exemples de refus déterministes :

- `C1` + `adds_removes_user_facing_behavior=true` → incohérent (une clarification ne change pas le comportement utilisateur).
- `C1` + `introduces_commitment=true` → incohérent.
- `C2` + `introduces_commitment=true` → incohérent (condition « aucun engagement externe »).
- Toute classe délégable dont les impacts déclarés correspondent à la définition opérationnelle de C5b ou F (section 5) → incohérent → re-classification ou `HUMAN_REQUIRED`.

Cas limite fixé : `C5a` + `touches_existing_acceptance_criteria=true` reste délégable au niveau Étendu **si** l'objectif fonctionnel est inchangé — l'essentialité de l'AC (un AC essentiel = C5b) est un jugement **sémantique** : il est arbitré par la re-classification indépendante du reviewer (section 7), pas par le contrôleur ; toute incertitude persistante → `HUMAN_REQUIRED`.

Le morphing C1→C5b (démarrer en clarification, finir en suppression de comportement) est le scénario e2e complet de ces couches.

## 7. Anti-mauvaise-classification : 3 couches proportionnées

Un contrôle déterministe sur une classification mensongère serait mécaniquement correct et matériellement faux (« Clarifier les AC en supprimant les anciens formats » présenté C1). Réponse validée, 3 couches :

1. **Champs d'impact déclaratifs obligatoires** (section 6) — vérification déterministe au contrôleur ; surface auditable ; un mensonge crée une incohérence détectable.
2. **Re-classification indépendante** (ciblée, pas un second meeting) : TOUTE décision candidate à la délégation (`DELEGATED_APPROVED`) est soumise AUSSI au product-analyst (agent `reviewer` existant, non décisionnel — 1 dispatch ciblé par décision candidate). Le reviewer reclassifie **à l'aveugle** : il reçoit le **texte final complet, les critères d'acceptation existants et le périmètre approuvé** — JAMAIS la classe proposée par le PO ni son argumentaire. Il **réévalue aussi les 3 booléens d'impact** (pas seulement la classe). La re-classification s'applique aussi quand l'impact déclaré a changé depuis la classification initiale ou quand un participant a contesté la portée.
   - Divergence PO/reviewer → **la classe la plus restrictive**, ou `HUMAN_REQUIRED` si le désaccord porte sur une classe interdite.
   - **Limite documentée (improvement 5, verdict tour 3)** : deux modèles peuvent commettre la même erreur de classification. La solution **réduit** le risque, elle ne le supprime pas mathématiquement.
3. **Fail-closed** : incertitude persistante après les 2 couches → `PROPOSE_ONLY` puis `HUMAN_REQUIRED`.

**Séquençage** : la re-classification indépendante est effectuée **avant** la décision du contrôleur — le plugin n'émet jamais `DELEGATED_APPROVED` sur une classification non confirmée (ou convergente) ; le contrôleur applique ensuite les règles déterministes à la classification acceptée.

## 8. Formats de données

### 8.1 Decision Proposal (produit par le PO, consommé par le contrôleur)

```json
{
  "decision_id": "PD-014",
  "title": "<résumé court>",
  "final_text": "<texte final complet de la décision — objet de la classification>",
  "classification": { "class": "C1|C2|C3|C4|C5a|C6", "rationale": "<argumentaire PO — jamais transmis au reviewer>" },
  "impact": {
    "touches_existing_acceptance_criteria": false,
    "adds_removes_user_facing_behavior": false,
    "introduces_commitment": false
  },
  "constraints": ["<contraintes déclarées>"],
  "project_key": "<host/owner/repo>",
  "classified_at": "<ISO-8601>"
}
```

### 8.2 Decision Record (produit par Aurora, append-only, traçable)

```json
{
  "decision_id": "PD-014",
  "final_text": "<texte final>",
  "classification": { "class": "C3", "reclassified_by": "po|product-analyst", "reviewer_class": "C3", "reviewer_impact": { "touches_existing_acceptance_criteria": false, "adds_removes_user_facing_behavior": false, "introduces_commitment": false }, "convergent": true },
  "impact": { "touches_existing_acceptance_criteria": false, "adds_removes_user_facing_behavior": false, "introduces_commitment": false },
  "constraints": ["..."],
  "project_key": "...",
  "status": "PROPOSE_ONLY|DELEGATED_APPROVED|HUMAN_REQUIRED|REFUSED",
  "refused_reason": "<obligatoire si REFUSED — ex. incoherent_impact_combination>",
  "policy_ref": { "policy_id": "PA-003", "policy_hash": "..." },
  "authorization": { "...": "attestation — section 8.3, présente ssi DELEGATED_APPROVED" },
  "recorded_at": "<ISO-8601>"
}
```

Les décisions déléguées sont **traçables** : le record cite la politique (id + hash) et porte l'attestation. Les records historiques sont append-only — **une révocation ne réécrit jamais l'histoire**, elle bloque les nouvelles fondations. Un refus (`REFUSED`) est tracé avec sa raison (section 9.1) — traçabilité complète.

### 8.3 Authorization Attestation (émise UNIQUEMENT par le contrôleur)

```yaml
authorization:
  issuer: product-authority-controller
  authorization_id: AUTH-031
  policy_id: PA-003
  policy_hash: "<hash de la politique au moment de la ratification>"
  decision_digest: "<hash canonique : contenu final + classe + impact (3 booléens) + contraintes + identité projet>"
  authorized_at: "<ISO-8601>"
```

- **L'attestation ne vit QUE côté contrôleur** (journal append-only). Elle n'est jamais produite par un texte d'agent.
- `decision_digest` lie l'autorisation au contenu exact : **toute modification ultérieure de la décision invalide l'attestation**.
- Pas de PKI ni de signature cryptographique au MVP — un point de contrôle unique + re-vérification live (gain disproportionné).

### 8.4 DecisionUsageContext (contexte courant, obligatoire à la consommation)

```json
{
  "project_key": "<host/owner/repo du projet où la décision est consommée>",
  "task_scope": "<périmètre actuel de la tâche>",
  "applicable_constraints": ["<contraintes applicables au moment de l'usage>"],
  "known_conflicts": ["<décisions plus récentes potentiellement incompatibles, si connues>"]
}
```

Si les informations nécessaires ne sont pas vérifiables, le contrôleur ne doit **pas** affirmer l'applicabilité (section 9.2).

### 8.5 Reclassification (produite par le product-analyst, entrée du contrôleur)

```json
{
  "decision_id": "PD-014",
  "reviewer_class": "C1|C2|C3|C4|C5a|C5b|C6|F",
  "reviewer_impact": {
    "touches_existing_acceptance_criteria": false,
    "adds_removes_user_facing_behavior": false,
    "introduces_commitment": false
  },
  "notes": "<observations — sans accès à la classe ni à l'argumentaire du PO>"
}
```

Classification proposée indépendamment du texte final + réévaluation des 3 booléens d'impact. Le product-analyst ne reçoit JAMAIS la classification ni l'argumentaire du PO (section 7).

## 9. Contrats du contrôleur (déterministes, hors modèle)

### 9.1 authorizeProductDecision

```ts
authorizeProductDecision(policy, decision: DecisionProposal, context): AuthorizationResult
```

Vérifications déterministes : identité projet (origin + cross-check), expiry, révocation, hash de la politique, classes du niveau actif, classe F et récusation, cohérence classe × impact (section 6), contraintes explicitement représentées, version des contrats, plafond (~3 décisions déléguées par Meeting, disjoncteur expérimental). **Proposal malformé (booléen manquant, classe hors enum, champ obligatoire absent) → fail-closed explicite : `REFUSED` avec `reason: malformed_proposal`** — jamais d'interprétation tolérante.

Réponses possibles :

| Statut | Condition |
|---|---|
| `DELEGATED_APPROVED` (+ attestation) | Toutes les vérifications passent, y compris re-classification indépendante convergente (le séquençage section 7 est respecté) |
| `HUMAN_REQUIRED` | Politique absente/expirée/révoquée ; classe C5b ou F ; classification ambiguë (section 5) ; divergence sur classe interdite ; informations insuffisantes (`insufficient_information` — jamais d'exigence métier inventée) ; décision révisant une décision déjà ratifiée |
| `PROPOSE_ONLY` | Mode Consultatif, ou incertitude persistante (recommandation au handoff, décision reste `HUMAN_REQUIRED`) |
| `REFUSED` (+ `reason`) | Combinaison classe × impact incohérente ; proposal malformé — le refus est tracé en record (section 8.2) |

### 9.2 verifyAuthorization (point de consommation)

```ts
verifyAuthorization(
  authorizationId: string,
  decisionDigest: string,
  currentContext: DecisionUsageContext,
): AuthorizationVerificationResult

type AuthorizationVerificationResult =
  | { valid: true; applicable: true }
  | { valid: true; applicable: false; reason: string }
  | { valid: false; reason: "unknown_authorization" | "digest_mismatch" | "policy_expired" | "policy_revoked" }
  | "REQUIRES_REVALIDATION"
```

Invoqué **à chaque usage** d'une décision déléguée comme autorité (préparation d'implémentation, handoff ultérieur) — pas seulement inscrit dans le record. Re-vérifications, dans l'ordre : l'attestation **existe** côté contrôleur ; le `decisionDigest` fourni correspond au contenu exact enregistré ; la politique n'est ni expirée ni révoquée **au moment de l'usage** ; **applicabilité opérationnelle** re-évaluée dans le contexte courant (identité projet, périmètre, contraintes, absence de décision incompatible plus récente).

Résultats :

| Résultat | Signification |
|---|---|
| `{ valid: true, applicable: true }` | Utilisable comme autorité pour cet usage |
| `{ valid: true, applicable: false, reason }` | Attestation valide mais non applicable ici (contraintes, conflit plus récent…) |
| `{ valid: false, reason: "unknown_authorization" }` | **Aucune attestation connue du contrôleur** — un texte « status: DELEGATED_APPROVED » sans authorization_id connue est REFUSÉ comme autorisation (jamais un laissez-passer par construction) |
| `{ valid: false, reason: "digest_mismatch" }` | Le contenu consommé diffère du contenu autorisé — **toute modification ultérieure de la décision invalide l'attestation** |
| `{ valid: false, reason: "policy_expired" \| "policy_revoked" }` | La politique ne fonde plus d'autorité actuelle — résultat **explicite**, jamais masqué derrière `REQUIRES_REVALIDATION` |
| `REQUIRES_REVALIDATION` | Attestation et politique valides, mais contexte courant **non vérifiable** (identité, périmètre, contraintes, conflits) — le contrôleur **ne peut pas affirmer** l'applicabilité ; re-soumission humaine ou re-check |

**Trois dimensions séparées, jamais fusionnées** : validité historique (le record tient, append-only) ≠ autorité actuelle (re-check à chaque ratification) ≠ applicabilité opérationnelle (re-check à l'usage). Une décision historiquement valable n'est pas « devenue fausse » à l'expiration — elle doit être **réévaluée dans son contexte actuel** avant tout nouvel usage comme autorité. Un `DELEGATED_APPROVED` n'est jamais un laissez-passer permanent.

## 10. Règles de refus — ce que le PO ne peut jamais faire

1. S'auto-élever (changer son niveau, ses classes, ses limites).
2. Modifier son propre contrat ou le système d'autorité (classe F).
3. Contourner une règle de sécurité ou d'autorité.
4. Prétendre représenter une validation humaine non obtenue (invariant E).
5. Décider pour un autre responsable (autorité personnelle ≠ équipe).
6. Lire le fichier de politique (l'enveloppe est injectée par Aurora).
7. Utiliser le mot « ratifier » ou émettre un statut sans attestation du contrôleur.

Tout texte d'agent affirmant un statut d'autorité **sans attestation connue du contrôleur** est **illégitime par construction** — aucun consommateur (Aurora inclus) ne peut le fonder.

## 11. Cas d'incertitude (synthèse)

| Situation | Réponse |
|---|---|
| Ambiguïté de classification | `HUMAN_REQUIRED` — l'ambiguïté est soumise à validation humaine, jamais résolue mécaniquement |
| Divergence PO / reviewer | La plus restrictive ; `HUMAN_REQUIRED` si classe interdite en jeu |
| Informations insuffisantes | `insufficient_information` → `HUMAN_REQUIRED` (jamais d'exigence métier inventée) |
| Contexte non vérifiable à l'usage | `REQUIRES_REVALIDATION` |
| Politique absente / expirée / révoquée | `HUMAN_REQUIRED` (fail-closed) |
| Mismatch hash registre ↔ journal | Fail-closed Consultatif + alerte + `reconcile` (confirmation explicite) |
| Mismatch identité projet | Downgrade Consultatif + 1 re-confirmation |
| Révision d'une décision produit déjà ratifiée | `HUMAN_REQUIRED` (la décision ratifiée prime) |

## 12. Tests de réception (Étape 3 — conditions, pas design)

La matrice (~20 scénarios) inclut obligatoirement, par contrat : morphing C1→C5b (e2e complet couche B) ; injection de classification par le PO (C5b déguisé en C1 → refus/escalade) ; consommateur présentant un `DELEGATED_APPROVED` sans attestation valide → `{ valid: false, reason: "unknown_authorization" }` ; décision modifiée après autorisation → digest mismatch → attestation invalide ; reprise `sessionID` → restrictions actives ; révocation mid-meeting → re-validation à la ratification suivante ; mismatch hash → fail-closed Consultatif ; mismatch identité → downgrade + re-confirmation. Extensions de la review (fidélité aux zones ambiguës) : proposal malformé (booléen manquant / classe hors enum) → fail-closed `REFUSED` traçable ; `verifyAuthorization` sur politique expirée/révoquée → résultat explicite `{ valid: false }` (jamais `REQUIRES_REVALIDATION` par défaut) ; ambiguïté entre deux classes délégables → `HUMAN_REQUIRED` (règle section 5) ; `C5a + touches_existing_acceptance_criteria=true` → verdict défini (arbitrage sémantique reviewer, section 6). L'e2e de bout en bout : **Meeting → question produit → décision PO → classification indépendante → autorisation contrôleur → handoff → vérification d'applicabilité** ; le même scénario hors délégation → `HUMAN_REQUIRED`.

## 13. Garde-fous du MVP (assumés, non cachés)

- Plafond ~3 décisions déléguées par Meeting (disjoncteur expérimental).
- Stockage privé, atomique, journalisé (P1-9 ACCEPTED).
- Intégrité détective (orchestrateur TCB) — section 4.2.
- Pas de crypto/PKI — attestation + re-check live (section 8.3).
- Deux modèles peuvent se tromper — réduction du risque, pas élimination (section 7).
