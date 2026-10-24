# RFC — Execution Graph Core pour Aurora

> Carte Trello `DuTvF4fZ` · Itération 2 · 2026-10-24 · Livrable unique
> Statut : **proposed** — en review PO (ChatGPT, product-authority) puis GO humain avant itération 3 (implémentation).
> Prérequis : itération 1 validée (`01-05`, PR #47) ; issue du débat Aurora ↔ ChatGPT (3 tours, APPROVED) et de la review PO de la PR #47 (APPROVED WITH CHANGES, corrections appliquées `5d79232`).

## 0. Objectifs et non-objectifs

**Objectifs de cette RFC** : définir les contrats formels, les invariants de transition, les garanties de concurrence/reprise/effets externes et la stratégie de migration d'un noyau d'exécution en graphe (**Execution Graph Core**), dont les cinq protocoles existants (task-workflow, deepwork, council, meeting, loop-engineering) deviennent progressivement clients **sans dénaturation de leur logique métier**.

**Critère de succès** (débat tour 3) : *« prouver qu'Aurora peut interrompre, reprendre et valider un workflow multi-étapes sans perdre son état, dupliquer un effet externe ou accepter une preuve périmée. »*

**Non-objectifs (NO-GO ratifiés)** : migration PostgreSQL générale, intégration LangGraph/Temporal dans le cœur, remplacement immédiat des cinq contrats, orchestration multi-worker dans le pilote.

**Périmètre du pilote** : workflow *analyse → implémentation → review* sur écritures externes locales maîtrisées ; backend **JSON mono-exécuteur** avec verrouillage exclusif ; PostgreSQL est la **cible conditionnelle** (avant tout DAG multi-worker durable).

---

## 1. Vue d'ensemble

```txt
                    ┌─────────────────────────────┐
                    │      Aurora Supervisor      │
                    │ planification conversationnelle,
                    │ coordination, arbitrage       │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    Execution Graph Core     │
                    │  GraphScheduler | TransitionEngine │
                    │  StateRepository | EventLog | EvidenceStore │
                    └──┬──────┬──────┬──────┬──────┬─┘
                       │      │      │      │      │
                 task-workflow deepwork council meeting loop-eng
                     (Workflow Adapters — logique métier préservée)
                                   │
                    ┌──────────────▼──────────────┐
                    │         Executors           │
                    │ OpenCode (processus/sessions), CLI, │
                    │ MCP, outils locaux, approbations humaines │
                    └─────────────────────────────┘
```

**Frontières invariables** : le Knowledge Graph (aurora-memory, PostgreSQL) et l'Execution Graph Core ne partagent **aucune table** (séparation logique au minimum, schémas + droits distincts si cohabitation dans une instance) ; les transitions et autorisations sont **déterministes**, seuls les nœuds d'exécution et d'évaluation sont LLM.

---

## 2. Contrats formels

Schémas en pseudo-TypeScript (contrat conceptuel, pas du code final). Toute évolution passe par `schemaVersion` — un nœud ou un graphe non conforme au schéma n'est jamais instancié.

### 2.1 GraphDefinition — le plan versionné

```ts
interface GraphDefinition {
  schemaVersion: number;          // évolution du contrat sans casser les runs actifs
                                  // compat moteur : {N, N-1} ; toute rupture de champ = bump
                                  // majeur ; les GraphDefinition persistées portent leur
                                  // version et sont revalidées à la reprise (review technique F18)
  graphId: string;                // identité du graphe (ex. "mr-analysis-v1")
  version: string;                // version du plan, immuable une fois le run lancé
  nodes: NodeDefinition[];
  initialNodes: string[];         // racines du DAG (≥ 1 — S1 exige 2 branches indépendantes
                                  // donc plusieurs racines sans deps ; review technique F7)
  sharedStateSchema?: object;     // schéma de l'état partagé typé (optionnel, validateur JSON Schema)
  filiation?: {                   // CHAMP RÉSERVÉ M7+ (review technique F15 — non exercé
    parentGraphId: string;        // par S1-S7 ni M1-M4 au pilote, documenté pour la cible)
    parentVersion: string;
    reason: string;               // motif documenté de la dérivation
  };
}
```

**Règles** : le graphe lancé est **immuable pour la durée du run** (`runId` → `(graphId, version)` figés à la création) ; les nœuds ne modifient jamais la topologie en cours de route — toute modification produit un **nouveau plan validé** avec lien de filiation. `deps[]` des nœuds forment un **DAG** (acyclique, vérifié à la validation du plan : cycle = rejet).

### 2.2 NodeDefinition — ce qui doit être exécuté

```ts
interface NodeDefinition {
  schemaVersion: number;
  id: string;
  type: "agent" | "tool" | "human" | "gate";
  deps: string[];                 // ids des nœuds prérequis (DAG)
  inputs: object;                 // références aux sorties attendues / état partagé
  outputSchema: object;           // schéma de la sortie (validation déterministe)
  permissions: string[];          // autorisations requises, TYPÉES (review technique F4/I9) :
                                  // "read:<domaine>" | "write:<domaine>" — un nœud agent ne
                                  // porte JAMAIS de permission write (invariant I9) ; une
                                  // écriture externe exige un nœud tool avec effectPolicy
  successCriteria: string[];      // critères machine-vérifiables quand possible
  evidencePolicy: {               // preuves attendues + leur fraîcheur (P0.3)
    required: ("exitCode" | "artifact" | "structuredVerdict" | "humanApproval")[];
    // "artifact" = preuve kind technical portant artifactRef {path, hash} (review F17)
    freshness: { inputFingerprint: boolean };
  };
  failureBudgets: {               // (review technique F8) — 4 compteurs indépendants (I8)
    technical: number;            // retries d'échec technique transitoire
    quality: number;              // itérations de correction (Evaluator/Optimizer borné)
    // invalidEvidence et permission n'ont PAS de budget : jamais auto-résolus (blocked)
  };
  retryPolicy: { maxAttempts: number; backoff: "none" | "fixed" | "exponential" };
  timeoutSeconds: number;
  resourcePolicy?: {              // budgets transverses (P1)
    maxTokens?: number;
    maxWallTimeSeconds?: number;
    concurrencyKey?: string;      // CHAMP RÉSERVÉ M7+ (review technique F15 — le pilote
                                  // s'exécute séquentiellement en topo-order, cf. §11 M3)
  };
  effectPolicy: {                 // (P0.2) — obligatoire sur tout nœud d'écriture
    mode: "read" | "write";
    idempotencyKey?: string;      // identité stable de l'opération externe
    reconciliation?: "getBeforePost" | "contentHash" | "none";
    onUncertainOutcome: "reconcile" | "block";
    compensation?: string;        // DOCUMENTATION-ONLY au pilote (review technique F16 :
                                  // pas de protocole d'exécution défini — champ descriptif
                                  // référencé par ADR-017, aucun déclencheur automatique)
  };
}
```

### 2.3 NodeExecution — ce qui s'est réellement passé

```ts
interface NodeExecution {
  runId: string;                  // identité du run (unique, immuable)
  nodeId: string;
  attempt: number;                // 1-based
  status: "pending" | "running" | "blocked" | "completed" | "failed" | "cancelled";
  executorId?: string;            // qui exécute (session/agent)
  generationToken?: string;       // génération du détenteur du verrou (fencing §4 —
                                  // vérifiée à CHAQUE écriture d'état, pas seulement stockée)
  startedAt?: string;
  completedAt?: string;
  inputFingerprint: string;       // (P0.3) fraîcheur des entrées — cf. §6.3
  outputArtifactRefs: string[];   // artefacts persistés hors état (chemins + hash)
  evidenceRefs: string[];         // références vers les EvidenceRecords
  failureCounts: {                // (review technique F8/I8) — compteurs par classe d'échec,
    technical: number;            // incrémentés indépendamment, jamais fusionnés ; comparés
    quality: number;              // aux failureBudgets du NodeDefinition à chaque retry
    invalidEvidence: number;      // (jamais auto-résolu → blocked)
    permission: number;           // (jamais auto-résolu → blocked)
  };
  error?: string;
}
```

### 2.4 EvidenceRecord — la preuve structurée

```ts
interface EvidenceRecord {
  evidenceId: string;
  runId: string;
  nodeId: string;
  attempt: number;
  kind: "technical" | "semantic" | "authorization";   // 3 niveaux du contrat d'exécution
  exitCode?: number;              // kind: technical — un pass exige 0
  structuredVerdict?: {           // kind: semantic — LLM encadré, structure validée par le moteur
    verdict: "pass" | "fail" | "inconclusive";
    findings: { severity: string; criterionId: string; evidenceRef: string }[];
    confidence?: number;
  };
  approvalRef?: string;           // kind: authorization — attestation product-authority / approbation humaine
  artifactRef?: { path: string; hash: string };  // (review technique F17) — forme "artifact"
                                  // d'une preuve kind: technical : référence de l'artefact
                                  // persisté (chemin + hash) ; satisfait
                                  // evidencePolicy.required: "artifact"
  codeSignature?: string;         // composant de fraîcheur : sha1(HEAD + git status) quand pertinent
  inputFingerprint?: string;      // (P0.3) empreinte complète des dépendances du nœud
  createdAt: string;
  sourceRef: string;              // où vérifier la preuve (chemin, URL, journal)
}
```

**Invariant central** (hérité de `tw_state.py`) : *un contrôle ignoré n'est jamais présenté comme réussi* — une entrée `skipped`/`not-run` n'existe qu'avec une raison non vide ; un `pass` technique exige `exitCode: 0`.

### 2.5 EffectRecord — l'effet externe tracé

```ts
interface EffectRecord {
  effectId: string;
  runId: string;
  nodeId: string;
  attempt: number;
  idempotencyKey: string;         // identité stable de l'opération (obligatoire si write)
  classification: "safe" | "reconcile" | "block";   // (P0.2) — cf. §7
  phase: "prepared" | "dispatched" | "confirmed" | "uncertain" | "failed" | "reconciled";
  // prepared  : aucune émission autorisée à cet instant — garantie de PROTOCOLE (un
  //             exécuteur conforme ne part pas tant que dispatched n'est pas journalisé)
  // dispatched: INTENTION D'ÉMISSION durablement enregistrée (journalisée + fsync AVANT
  //             l'appel) — l'appel a pu avoir lieu : une reprise exige une réconciliation.
  //             Ce n'est pas une preuve d'envoi, c'est une intention vérifiable.
  // confirmed : issue positive avec preuve (réponse API, GET de vérification)
  // uncertain : issue réelle inconnue (crash, API muette, timeout ambigu) → protocole §7.2
  // failed    : échec visible AVANT tout effet (l'appel n'a pas pu partir)
  // reconciled: issue rétablie par vérification (getBeforePost/contentHash)
  requestedAt: string;
  confirmedAt?: string;
  reconciledAt?: string;
  outcomeEvidenceRef?: string;    // preuve de l'issue
}
```

**Règles** (P1 + P0.3 — review PO itération 2) :
- **Séquence obligatoire d'émission** : (1) journaliser `prepared` + fsync ; (2) **journaliser `dispatched` + fsync** ; (3) **seulement alors** émettre l'appel externe ; (4) journaliser `confirmed`/`failed` si le résultat est fiable, sinon `uncertain`. Sans l'étape (2), un crash entre (1) et l'appel laisserait croire à « aucun appel émis » alors qu'il a pu partir — c'est la fenêtre de double effet que l'architecture interdit.
- `prepared` au redémarrage = « aucun appel n'a dû être émis par un exécuteur respectant le protocole » — le rejeu est envisageable **après vérification des préconditions** ; `dispatched` sans suite = « l'émission a pu avoir lieu » → réconciliation obligatoire, jamais de rejeu direct.
- Les cas où **l'API ne permet pas de connaître l'issue réelle** (pas de GET fiable, réponse ambiguë) sont classés `uncertain` → protocole `block` — jamais de rejeu sur incertitude.
- **Dérivation permissive** : les opérations sûres et intrinsèquement idempotentes (à préconditions prouvées) peuvent condenser les étapes (1)-(3) — la classification `safe` le documente ; toute écriture non `safe` suit la séquence complète.

### 2.6 TransitionRecord — la source de vérité du journal (I3, review technique F5)

```ts
interface TransitionRecord {
  transitionId: string;           // unique — rejeu idempotent par ce champ (I3, §5)
  runId: string;
  nodeId: string;
  attempt: number;
  kind: "transition" | "invalidation" | "effect";
  from?: string;                  // statut de départ (null pour une invalidation de portée)
  to: string;                     // statut d'arrivée (ou portée d'invalidation)
  generationToken: string;        // génération de l'écrivain — vérifiée au replay (§4, F6)
  timestamp: string;
  payload?: object;               // selon kind : motif d'invalidation + empreinte divergente +
                                  // portée transitive ; phase d'EffectRecord ; refs de preuves ;
                                  // trace human-intervention (motif + identité, cf. S5)
  checksum: string;               // sha256 du corps du record — détection d'écriture partielle
}
```

**Format de persistance** : JSONL (1 record par ligne). La détection d'écriture partielle s'effectue au chargement : **une dernière ligne non parsable ou dont le checksum échoue est traitée comme une queue incomplète ignorée** — jamais comme une transition confirmée (I3). L'append + `fsync` du fichier journal est le point de commit durable ; la **création et la rotation du fichier journal** (par taille, par exemple) sont couvertes par le `fsync` du répertoire.

---

## 3. Invariants de transition

| # | Invariant | Garantie | Héritage |
|---|---|---|---|
| I1 | **Transitions fermées** : les statuts d'un `NodeExecution` n'évoluent que selon la table légale (§3.1) **ou via une opération dédiée journalisée** (invalidation, I5 — l'exception vit dans l'invariant, pas dans un commentaire de table) ; toute autre évolution est refusée et **l'état n'est pas écrit** | moteur | `tw_state.py TRANSITIONS` |
| I2 | **Preuve attachée** : un nœud ne passe à `completed` qu'avec des `EvidenceRecord` conformes à son `evidencePolicy` | moteur | `evidence_guard` |
| I3 | **Journal transactionnel faisant autorité** (P0 — review PO itération 2) : le **journal append-only est la source de vérité** ; chaque transition y est un `TransitionRecord` auto-suffisant (§2.6) dont l'append + `fsync` constitue le **point de commit durable** ; le snapshot JSON n'est qu'une **projection reconstruisible** (un record journalisé mais non projeté est rejoué idempotemment au redémarrage ; une transition préparée mais non journalisée n'a jamais existé — jamais présentée comme acquise). **Invariants techniques M1-M4** : les records sont **identifiables et détectables en cas d'écriture partielle** — au redémarrage, la récupération **ignore une queue incomplète** (dernière ligne non parsable) sans jamais accepter un record corrompu comme transition confirmée ; la **durabilité des opérations sur le répertoire** (création, rotation de fichiers du journal) est également couverte par les `fsync` nécessaires ; les records dont le `generationToken` n'appartient pas à la chaîne de générations connue sont **relevés et rejetés** au replay (fencing, §4) | pilote | ADR-014, review PO, review technique F5/F6 |
| I4 | **DAG vérifié** : un plan avec cycle est rejeté à la validation ; un nœud ne démarre que si toutes ses dépendances sont `completed` avec preuves valides | scheduler | — |
| I5 | **Invalidation transitive explicite** (P1 — review PO itération 2) : l'invalidation est une **opération dédiée et journalisée** (pas une transition ordinaire) qui marque le nœud et **tous ses descendants** (transitivement) `pending` ; les preuves invalidées restent **dans le journal avec un marqueur** (jamais supprimées physiquement — historique préservé) ; un résultat techniquement réussi dont la valeur devient invalide avant consommation ne peut pas servir ; **l'invalidation de calcul n'annule ni ne rejoue jamais implicitement un effet externe déjà réalisé** — la reprise des descendants à effets passe par leur `effectPolicy` (§7). **Descendants `running`** (review technique F3) : l'invalidation d'un nœud `running` le marque `cancelled` (sous verrou — sa preuve sera invalide de toute façon) ; réciproquement, **toute transition vers `completed` revérifie au commit qu'aucun ancêtre n'a été invalidé depuis `startedAt`** (comparaison de révisions journal) — un nœud complétant avec une preuve devenue invalide **pendant** son exécution voit sa complétion **rejetée** et est invalidé transitivement | moteur | `invalidate`, review PO, review technique F3 |
| I6 | **Frais de version** : le `(graphId, version)` d'un run est figé à la création ; jamais de mutation de plan en cours de run | moteur | débat tour 1 |
| I7 | **Preuve périmée ≠ transition** : la fraîcheur est vérifiée au moment de CHAQUE transition qui s'appuie sur une preuve, pas seulement au démarrage | moteur | `codeSignature` bidirectionnelle |
| I8 | **Échecs à budgets indépendants** (contractualisés — review technique F8) : chaque nœud porte `failureBudgets` (§2.2) et chaque `NodeExecution` ses compteurs par classe — technique transitoire, qualité, preuve invalide, permission — incrémentés indépendamment, jamais fusionnés ; **épuisement de budget** : technique → `failed` terminal (sans retry restant) ; qualité → `blocked` (replanification ou intervention) ; preuve invalide / permission → `blocked` (jamais auto-résolus) | moteur | débat tour 1, review technique |
| I9 | **Toute écriture externe passe par un nœud `tool` porteur d'`effectPolicy`** (review technique F4) : les nœuds `agent` n'ont **aucune permission d'écriture directe** (`permissions[]` typées `read:…`/`write:…`, §2.2) — un nœud `agent` qui nécessite un effet externe déclenche un nœud `tool` dédié avec `EffectRecord`. La garantie de protocole du §7.2 couvre donc **toute la surface d'émission** : un contournement par un nœud `agent` est une violation détectable (permission refusée par le moteur) | moteur | review technique |

### 3.1 Table de transitions légales (NodeExecution)

```txt
pending   → running | blocked | cancelled
running   → completed | failed | blocked | cancelled
blocked   → running (gardes complètes, cf. ci-dessous) | pending | cancelled
failed    → pending (retry sous budget) | cancelled
completed → (terminal — l'invalidation passe par l'opération dédiée I5, pas par une transition)
cancelled → (terminal)
```

**Exception intégrée à I1** : l'opération d'invalidation (I5) est une opération dédiée journalisée — elle n'est pas une transition de la table ; elle peut affecter un nœud `completed` (→ `pending`) et un nœud `running` (→ `cancelled`).

**Deux écarts délibérés avec `task-workflow`** (validés par la review PO itération 2) :

- **Écart A — `completed` terminal, invalidation explicite** : une invalidation n'est **pas** une transition `completed → pending` mais une **opération dédiée et journalisée** (type `invalidation` avec motif + empreinte divergente + portée transitive) — cela préserve la sémantique des exécutions terminées et l'historique des preuves (I5).
- **Écart B — `blocked → running` direct, sous gardes déterministes complètes** : accepté uniquement si le moteur **revérifie** (au moment du retour) : dépendances `completed` à preuves fraîches, empreinte des entrées (I7), permissions, budgets restants, **absence d'effet externe incertain** — et si une **réservation exclusive** (verrou + token de génération, §4) précède le retour à `running`. Pas de réintroduction d'une étape `pending` systématique.

---

## 4. Concurrence — exclusion mutuelle et fencing du pilote (P0.1, review PO itération 2)

**Constat** (débat tour 3) : le claim actuel de `task-workflow` est une **convention entre agents**, pas une exclusion mutuelle — deux processus peuvent « claim » au même instant. **Constat review PO** : un lockfile `O_EXCL` + TTL ne suffit pas — un ancien propriétaire peut rester vivant ou reprendre son activité après expiration du verrou pendant qu'un nouveau propriétaire travaille.

**Garanties du pilote JSON mono-exécuteur** (4 mécanismes distincts, rôles séparés) :

1. **Verrou système tenu pendant toute la possession** : `flock` exclusif (Unix) sur un fichier de verrou par `runId`, acquis **avant toute décision de scheduling** et conservé pendant toute la session d'orchestration du run — un seul ordonnanceur actif par construction ; le kernel libère le verrou au crash du processus (pas de TTL à gérer manuellement, pas de fenêtre « verrou expiré mais propriétaire vivant »). Un second orchestrateur qui tente le même run détecte le verrou détenu et s'arrête (S6).
2. **Heartbeat — détection, jamais autorisation** : le propriétaire écrit périodiquement son identité (PID + session + horodatage) ; le heartbeat sert uniquement à détecter les situations suspectes et à documenter l'état — il **n'autorise jamais à lui seul** une reprise concurrente ni une prise de verrou.
3. **Récupération de run orphelin — protocolée, pas automatique** : après crash du propriétaire (verrou relâché par le kernel), la reprise suit le protocole de §5 : vérification d'identité du dernier propriétaire, épinglage des exécutions `running` sans vie, réconciliation des `EffectRecord` orphelins **avant** toute rejeu. L'exclusivité de la reprise reste garantie par le même `flock` (deux récupérateurs ne peuvent pas coexister — le premier tenu gagne, le second détecte et s'arrête).
4. **Token de génération vérifié à chaque écriture d'état** (fencing réel) : chaque session d'orchestration reçoit un `generationToken` à l'acquisition du verrou ; **chaque record de transition journalisé porte la génération attendue** — l'écriture est rejetée si la génération ne correspond pas à celle du détenteur courant du verrou. Un ancien propriétaire qui reprendrait une écriture après reprise du verrou par un nouveau est donc **bloqué par le moteur**, pas seulement par une convention (c'est le fencing demandé par la review PO — le token n'est pas seulement stocké dans `NodeExecution`, il est vérifié à chaque commit de transition). **Invariant technique M1-M4** : la vérification du token et l'écriture correspondante s'effectuent **dans la même section critique protégée par `flock`** — le token seul ne garantit rien si une écriture peut intervenir après sa vérification (fenêtre TOCTOU). **Localisation du token courant** (review technique F6) : le `generationToken` courant est **stocké dans le fichier de verrou lui-même** (lisible par tout repreneur) ; chaque `TransitionRecord` porte le token de son écrivain ; au replay (§5), **les records dont le token n'appartient pas à la chaîne de générations connue du verrou sont relevés et rejetés** — ils ne sont jamais rejoués comme transitions (fencing rétroactif).

**Écritures atomiques** : le snapshot JSON (projection, I3) est réécrit via `write-to-temp + rename` — un lecteur voit toujours un snapshot complet ou l'ancien ; la **source de vérité** reste le journal append-only.

**Détection des exécutions interrompues** : au démarrage d'un run, tout `NodeExecution.status == "running"` sans heartbeat récent est réévalué — l'`EffectRecord` orphelin éventuel déclenche la réconciliation (§7) **avant** toute rejeu.

**Limite assumée du pilote** : un seul processus orchestre un run donné (mono-exécuteur) — le multi-worker actif sur le même état exige la migration PostgreSQL (réservation SQL + lease + fencing, §11). Le verrou garantit dès le pilote que deux sessions ne corrompent pas le même run (scénario de validation S6, enrichi : tentative de reprise d'un ancien propriétaire après récupération). **Limite propriétaire vivant mais bloqué** (review technique F13) : un propriétaire suspendu (SIGSTOP, machine endormie) **conserve** le `flock` indéfiniment — le heartbeat (mécanisme 2) détecte l'absence de vie mais ne peut pas forcer la libération ; le run reste figé jusqu'à **escalade humaine** (tuer le propriétaire → le kernel libère le `flock` → reprise selon §5). Le heartbeat émet un signal d'alerte documenté avant cette escalade.

---

## 5. Reprise déterministe

Au (re)démarrage d'un run (même processus ou session différente) :

1. Acquérir le verrou système (§4) — un seul récupérateur possible par construction.
2. **Réconcilier le journal** (I3) : rejouer les records de transition journalisés mais non projetés dans le snapshot (rejeu idempotent par `transitionId`, records à token étranger rejetés — §4, F6) ; une transition préparée mais **non journalisée** n'a jamais existé. Le snapshot reconstruit depuis le journal est la **projection utilisable** ; **en divergence, le journal tranche** (review technique F14).
3. **Épingler les exécutions interrompues** : réévaluer les `running` sans preuve de vie ; traiter les `EffectRecord` orphelins (`dispatched` sans suite) selon la classification (§7) **avant** toute autre action.
4. Calculer le plan de reprise : `completed` avec preuves **fraîches** = sautés ; preuve périmée = **invalidation explicite transitive** (I5) ; `blocked` = ré-évalué (gardes complètes de l'écart B, §3.1) ; `failed` avec budget de retry restant = re-file.
5. Reprendre l'exécution — **sans réexécuter les nœuds à preuves valides** (scénario de validation S2).

Miroir direct du `resume` déterministe de `tw_state.py` (PASSED à signature courante = sauté, obsolète = invalidé) — la logique est réutilisée, généralisée du niveau phase au niveau nœud.

---

## 6. Fraîcheur — `inputFingerprint` générique (P0.3)

### 6.1 Principe

La signature git `sha1(HEAD + git status --porcelain)` reste un **composant** de l'empreinte de fraîcheur, jamais la totalité : fichiers ignorés, configuration externe, réponses API obsolètes et versions d'outils échappent à git.

### 6.2 Composition

```txt
inputFingerprint = sha256( canonique( [
  ("codeSignature",  codeSignature),          // si le nœud dépend du dépôt (sha1 hérité
                                              // tw_state — composant interne, cf. §6.1)
  ("deps",           deps triés par id →      // sorties des dépendances (chaînage transitif)
                     dep.outputArtifactRefs),
  ("config",         config externe pertinente déclarée),   // effectPolicy-relevant
  ("toolVersions",   versions des outils invoqués),         // quand pertinent
  ("declaredInputs", entrées déclarées du NodeDefinition),
] ) )
```

**Algorithme** (review technique F10) : `sha256` sur une **sérialisation canonique** (JSON, clés triées, composants étiquetés, composants non pertinents **omis** — empreinte minimale déclarée dans le plan). Un nœud sans composant pertinent produit la **chaîne constante** `"sha256:" + sha256("empty-input-fingerprint")` — jamais vide. La signature `codeSignature` reste `sha1(HEAD + git status)` par héritage `tw_state` : c'est un **composant** de l'empreinte, pas l'empreinte elle-même ; toute empreinte produite par le moteur est sha256.

Le `NodeDefinition.evidencePolicy.freshness.inputFingerprint` active la vérification ; les composants non pertinents pour un nœud sont omis (empreinte minimale, déclarée dans le plan).

### 6.3 Usage

- **À l'exécution** : l'empreinte calculée est stockée dans `NodeExecution.inputFingerprint`.
- **À chaque consommation** (I7) : le nœud descendant recalcule l'empreinte de ses prérequis — divergence = preuve périmée = invalidation transitive (I5). C'est le mécanisme qui traite le cas demandé par la review PO : *un nœud techniquement réussi dont le résultat devient invalide avant l'exécution de ses descendants*.
- **Hors réconciliation** : `inputFingerprint` ne sert **jamais** à réconcilier un effet externe — c'est le rôle de l'`EffectRecord` + `idempotencyKey` (§7).

---

## 7. Effets externes — taxonomie et réconciliation (P0.2, ADR-017)

### 7.1 Classification obligatoire

| Classe | Définition | Rejeu | Exemples |
|---|---|---|---|
| **safe** | rejeu sous préconditions vérifiées est sans effet parasite | direct après vérification des préconditions | écriture de fichier à contenu déterministe, création de branche si absente, commit local à contenu identique (hash vérifié avant rejeu) |
| **reconcile** | l'effet doit être vérifié avant toute décision | `GET` de vérification avant rejeu — **seulement si l'opération est identifiable de façon fiable** (clé d'idempotence, id retourné, hash de contenu) | Trello comment (GET-before-POST implémenté), création de MR GitLab, push |
| **block** | réconciliation impossible ou trop risquée | **jamais automatique** — intervention humaine requise si incertain | écritures Infomaniak sans clé d'idempotence, opérations bulk/destructives |

**Nuances du débat (tour 3)** : un `sessionID` OpenCode permet de retrouver une exécution mais ne garantit pas l'absence de doublon à la recréation (→ classe par opération, pas par système) ; `git commit` n'est pas idempotent intrinsèquement (→ safe uniquement à contenu vérifié) ; GET-before-POST suppose une identification fiable de l'opération — sinon l'opération est `block` par défaut.

**Mapping `effectPolicy` → classification** (review technique F9 — une seule règle de dérivation, éliminant le « par défaut » ambigu) :

| `effectPolicy` (NodeDefinition) | classification (EffectRecord) | Séquence d'émission |
|---|---|---|
| `reconciliation: "getBeforePost"` **et** identification fiable (idempotencyKey, id retourné, hash de contenu) | `reconcile` | séquence complète (§7.2) |
| `reconciliation: "contentHash"` **et** contenu vérifiable avant rejeu | `reconcile` (rejeu direct si contenu identique) | séquence complète (§7.2) |
| `mode: "write"` **et** `reconciliation: "none"` | `block` — **jamais automatique** | le nœud ne part pas sans approbation humaine |
| opération sûre et intrinsèquement idempotente, préconditions prouvées (ex. création de branche si absente, écriture à contenu déterministe) | `safe` | **séquence condensée** : un seul record `dispatched` journalisé + fsync **avant** l'émission, puis `confirmed`/`failed`/`uncertain` — la phase `prepared` est inutile quand le rejeu sous préconditions est sans effet parasite |
| `mode: "read"` | — (aucun EffectRecord) | n/a |

Toute écriture non couverte par les lignes ci-dessus est classée `block` par défaut (débat tour 3).

### 7.2 Protocole (séquence stricte — P0.3, review PO itération 2)

1. Journaliser `EffectRecord` `prepared` **+ fsync** (I3).
2. Journaliser `dispatched` **+ fsync** — **l'émission n'est autorisée qu'après ce commit durable**.
3. Émettre l'appel externe.
4. Journaliser `confirmed` (avec preuve) ou `failed` si le résultat est fiable ; sinon `uncertain`.

**Au redémarrage (crash à n'importe quelle étape)** : `prepared` → rejeu sous préconditions (aucune émission autorisée par le protocole à cet état) ; `dispatched` sans suite → réconciliation obligatoire selon la classe, **jamais de rejeu direct** ; `uncertain` non réconciliable (ou API sans GET fiable) → nœud `blocked` **sans rejeu automatique** (intervention humaine requise). Les tests de crash du pilote couvrent explicitement la fenêtre entre `prepared`, `dispatched` et l'émission réelle.

Le catalogue des effets du projet (OpenCode, Git, Trello, GitLab, Infomaniak, filesystem) est maintenu dans la synthèse du brainstorming §3 (Q7) — la RFC n'ajoute pas de système : elle impose la classification **par opération**.

---

## 8. Évaluation sémantique et budgets

- **Niveau 2 du contrat d'exécution** : les évaluations de qualité (review, council, ai-cowork verdict) sont des nœuds/gates LLM produisant un `EvidenceRecord.kind: "semantic"` avec **verdict structuré** `{verdict, findings[], confidence}` — le moteur valide la **structure et les références**, jamais la vérité du jugement.
- **Budgets indépendants** (I8) : `failureBudgets.technical` + `retryPolicy.maxAttempts` (technique) ≠ `failureBudgets.quality` (itérations de correction de la boucle Evaluator/Optimizer bornée) ≠ plafonds `resourcePolicy` (tokens, durée, concurrence). La règle des 2 corrections (`error-correction.md`) devient une instance : `failureBudgets.quality: 2`.
- **Niveau 3** : l'autorisation de transition reste déterministe — preuves présentes **et fraîches**, budgets respectés, attestation product-authority quand la classe de décision l'exige.

---

## 9. Matrice des responsabilités Core / Adapters / Executors

| Responsabilité | Execution Graph Core | Workflow Adapters (5 protocoles) | Executors |
|---|---|---|---|
| Ordre d'exécution, dépendances, topological sort | ✅ | — | — |
| Transitions d'état, preuves, invalidations | ✅ | — | — |
| Verrouillage, leases, reprise | ✅ | — | — |
| Journalisation atomique | ✅ | journal métier local (additif) | logs runtime |
| Classification effets, réconciliation | ✅ (mécanisme) | déclare `effectPolicy` par opération | exécute les appels |
| Vérdicts de qualité (council/meeting/review) | — | ✅ (logique métier : sièges, verdicts, invariants propres) | LLM |
| Permissions et autorisations | vérification déterministe à la transition | déclare les permissions du nœud | product-authority / approbation humaine |
| Persistance | StateRepository + EventLog + EvidenceStore | — | — |
| Sémantique métier (cycle de vie Trello/GitLab, délibération, gate multi-métiers) | — | ✅ **préservée intégralement** | — |

**Invariants d'adoption** : le read-only de council n'est jamais délégué au Core (les sièges restent du métier du skill) ; les garanties de meeting (`incomplete` ne peut jamais émettre `READY`) restent internes à son adapter ; `task-workflow` conserve son modèle de phases tant que sa migration n'est pas validée (Q2 : pas de réécriture des données historiques).

---

## 10. Scénarios de validation du prototype (mesurables)

| # | Propriété | Pré-condition | Action | Résultat observable (mesurable) |
|---|---|---|---|---|
| S1 | **DAG multi-branches + convergence** | graphe ≥ 2 branches indépendantes convergeant vers un nœud | lancer le run (exécution **séquentielle en topo-order** — modèle du pilote tranché, review technique F11) | **assertion sur le journal** : aucune transition `pending→running` du nœud de convergence avant la dernière transition `→completed` de ses deps (I4) ; toutes les branches exécutées avant la convergence ; l'ordre complet figure dans les `TransitionRecord` |
| S2 | **Reprise sans réexécution** | run interrompu après ≥ 2 nœuds complétés avec preuves fraîches | reprendre le run (autre session) | **assertion sur le journal** : 0 transition `pending→running` sur les nœuds à preuves valides ; l'exécution continue du bon nœud |
| S3 | **Invalidation transitive** | run avec branche complétée + modification du code amont (fingerprint divergent) | déclencher la vérification de fraîcheur | le nœud amont ET tous ses descendants transitifs sont **marqués invalidés** (record journal type `invalidation`, I5) et repassent `pending` ; les preuves sont **marquées invalidées dans le journal, jamais supprimées** (review technique F2) ; **assertion** : aucun descendant n'exécute avec une preuve marquée invalide |
| S4 | **Boucle de correction bornée** | review défavorable sur un nœud | laisser la boucle Evaluator/Optimizer tourner | corrections jusqu'à verdict favorable **ou** arrêt à `failureBudgets.quality` ; **assertion sur le journal** : les `TransitionRecord` portent des compteurs `failureCounts.technical` et `failureCounts.quality` distincts, incrémentés indépendamment (I8) |
| S5 | **Interruption sûre avant effet incertain** | nœud avec `effectPolicy` `block` dont l'opération échoue de façon non identifiable | simuler un crash post-appel (executor fake **injectable** — interfaces M2, review technique F19) | `EffectRecord` resté `dispatched`/`uncertain` détecté ; nœud `blocked` sans rejeu ; intervention humaine requise et **tracée par un `TransitionRecord` type `human-intervention`** (payload : motif + identité — rend l'assertion automatisable) |
| S6 | **Exclusion mutuelle + fencing** | 2 sessions tentent de reprendre le même run simultanément **+** un ancien propriétaire tente une écriture après que le verrou a été récupéré par un nouveau | lancer les 2 reprises + simuler l'écriture périmée | un seul obtient le verrou et progresse ; l'autre détecte le verrou détenu et s'arrête proprement ; l'écriture de l'ancien propriétaire est **rejetée par le moteur** (token de génération vérifié à chaque commit) ; l'état reste cohérent (0 transition corrompue) |
| S7 | **Fenêtres de crash sur effet externe** (review technique F11/F19) | pour chaque classe `safe`/`reconcile`/`block`, un nœud dont l'exécuteur (fake injectable) est tué (a) entre `prepared` et `dispatched`, (b) entre `dispatched` et l'émission réelle | simuler les crashes aux 2 fenêtres × 3 classes | `safe` : rejeu sous préconditions sans effet parasite (0 doublon observé) ; `reconcile` : réconciliation obligatoire déclenchée, issue réconciliée journalisée ; `block` : nœud `blocked`, aucun rejeu, `human-intervention` journalisé |

Chaque scénario est exécutable en test automatisé (état temporaire, dépôt jetable) — ils constituent la suite de QA du pilote (itération 3).

---

## 11. Stratégie de migration progressive

| Étape | Contenu | Rollback | Gate |
|---|---|---|---|
| M1 | Extraire `TransitionEngine` de `tw_state.py` (même logique, module importable, tests portés) | les 2 fichiers coexistent | review + tests verts |
| M2 | `StateRepository` JSON + `EventLog` + `EvidenceStore` derrière **interfaces injectables** (test doubles obligatoires — executor fake pour simuler crash post-dispatch, API muette et heartbeat absent, review technique F19) | interface pointe sur l'ancien code | review + e2e |
| M3 | `GraphScheduler` minimal (topo-sort, verrou §4, réservation) | module isolé | review + tests |
| M4 | Implémentation des 5 contrats (validation `schemaVersion` dès le premier nœud) | — | review |
| M5 | **Pilote** (analyse de MR) en shadow-run du système actuel — **effets en mode simulé/sandbox** (idempotencyKey simulée, aucun appel externe réel tant que la bascule n'est pas validée ; les métriques d'effets portent sur la simulation — review technique F12) | flag off | **comparaison mesurée** (S1-S7 + métriques : taux de réussite, durée, tokens, retries, interventions humaines, effets réconciliés en simulation) |
| M6 | ADR définitif (emplacement : `aurora-core/docs/adr/` — décision d'exécution du runtime) + documentation | — | validation PO + humain |
| M7+ | Branchement progressif des skills : loop-engineering → meeting → council → deepwork (task-workflow : StateRepository PostgreSQL **seulement si** besoin multi-worker avéré) | un skill à la fois, shadow-run avant bascule | review + GO PO par skill |

**Discipline transversale** : chaque étape est réversible ; un échec de validation d'invariant = retour à l'étape précédente, jamais un contournement ; aucune suppression du chemin existant avant validation de la suivante.

---

## 12. Questions ouvertes pour l'ADR définitif

1. **Placement du Core** : `aurora-core/workflows/` (emplacement réservé, runtime) avec la logique extraite de `tw_state.py` (aurora-ai) — la décision d'exécution appartient au runtime ; la localisation exacte de l'extraction (copie conforme vs paquet partagé) est tranchée à M1 selon la structure de dépendances réelle.
2. **Schéma PostgreSQL cible** (M7+/multi-worker) : tables `runs`, `node_executions`, `effects`, `evidences` + lease SQL — à dessiner au moment de la migration, hors périmètre RFC.

*La question du format de persistance du pilote a été tranchée par la review PO itération 2 (P0.1) : journal transactionnel source de vérité, snapshot = projection reconstruisible (I3).*

---

## 13. Décision demandée

À la review PO (ChatGPT, product-authority) puis GO humain :

- **APPROVED** → itération 3 : implémentation M1-M4 (extraction, interfaces, scheduler, contrats) dans une branche de travail → PR vers `feat/graph-engineering`.
- **APPROVED WITH CHANGES** → corrections appliquées puis itération 3.
- **CHANGES REQUIRED** → corrections puis nouvelle review.

*Les invariants de cette RFC sont la spécification contraignante de l'implémentation — toute divergence implémentation/RFC est un bug de l'implémentation.*
