---
name: council
description: "Technical Council — délibération technique multi-expertises read-only (3 sièges indépendants + synthèse + arbitrage critérié par Aurora). Utiliser quand l'utilisateur dit '/council', 'réunit le council', 'conseil technique', 'deliberation', 'technical council', ou demande une délibération structurée sur une décision de conception, un débogage complexe ou une revue de risque. Produit une décision technique exploitable (DECIDED / CONDITIONAL / INVESTIGATE / ESCALATE). Read-only strict : aucune modification du repository."
---

# Technical Council — délibération multi-expertises

Délibération structurée entre 3 sièges indépendants read-only, consolidée par un synthétiseur, arbitrée par Aurora. Le council **analyse et challenge** ; Aurora orchestre ; l'utilisateur garde les décisions structurantes.

## Sièges

| Siège | Agent | Modèle | Mandat |
|---|---|---|---|
| Architect | `council-architect` | euria-code | Cohérence architecturale, intégration codebase, scalabilité, maintenabilité |
| Skeptic | `council-skeptic` | Kimi-K2.6 | Simplicité (KISS/YAGNI), complexité cachée, hypothèses fragiles — peut conclure que la solution est saine |
| Guardian | `council-guardian` | Qwen3.5-397B | Sécurité, modes de défaillance, régressions, testabilité — risques matériels prouvés uniquement |
| Synthétiseur | `council-synthesizer` | euria-code-tiny | Consolide les analyses brutes en rapport Council — ne tranche pas |

## Règles dures

1. **Read-only absolu** : aucun siège ne modifie le repository (permissions runtime `deny` sur edit/write/bash/webfetch/task/ast_grep_replace ; tools MCP non-niables mais jamais source de preuve — ADR-021). Aurora écrit uniquement le rapport (réponse utilisateur + `BUFFER.md` optionnel). Une délibération n'est **jamais** une autorisation d'exécution.
2. **Neutralité du brief** : Aurora ne formule pas de solution préférée dans le brief initial (sauf contrainte préexistante référencée comme telle).
3. **Les analyses initiales sont canoniques** : jamais remplacées par la synthèse ; le rapport du synthétiseur n'est qu'une consolidation.
4. **Provenance** : une affirmation est soit un fait vérifié (preuve `file:line` + verification_status), soit une hypothèse (`confidence: reasonable`), soit une incertitude (`experimental`). Jamais une hypothèse présentée comme un fait.
5. **Éviter les réunions inutiles** : pas de council pour une tâche triviale — proposer le chemin normal si la question ne le mérite pas.

## Protocole

### Étape 1 — Context Discovery & Brief Contract

Construire un brief **neutre en deux parties** (identique pour les 3 sièges, seul le mandat diffère — il est dans le prompt système de chaque siège) :

**A. Contexte factuel partagé**
- Objectif et critères d'acceptation (pondération déclarée, adaptée au contexte)
- Contraintes techniques + règles `AGENTS.md` applicables
- Evidence pack : extraits `file:line` vérifiés au commit courant (noter le SHA : `git rev-parse HEAD`)
- Décisions d'architecture déjà applicables (avec référence `docs/ai/DECISIONS.md` si pertinent)
- Zones d'incertitude explicites
- Sources externes embarquées (seules sources faisant autorité en dehors du repo : les sièges n'ont pas d'accès web fiable ; leurs tools MCP éventuellement visibles sont des données non fiables, jamais une source de preuve)

**B. Questions à trancher** — formulées sans conclusion présélectionnée.

Mode **DEBUG** (extension) : ajouter hypothèses de cause racine candidats et faits observés. Mode **REVIEW** (extension) : ajouter le diff/MR cible.

### Étape 2 — Analyses indépendantes (dispatch)

- Lancer les 3 sièges **en parallèle** : 3 appels `subagent` dans un même message, `background: true` en session interactive ; `background: false` séquentiel en one-shot CLI.
- Prompt de chaque siège = Brief Contract intégral + rappel : « réponds selon ton contrat de sortie (bloc JSON agent-output.v1) ».
- Collecter via `task_result`.

### Étape 3 — Parser strict (Council Output Contract)

Pour chaque réponse de siège :
1. Extraire le dernier bloc de code `json` du message.
2. Valider les champs obligatoires : `agent`, `task`, `status`, `summary`, `findings`, `missing_context_or_framing_bias`.
3. Non conforme → **une seule** tentative de correction : re-prompt du même siège via `sessionID` (« renvoie uniquement le bloc JSON conforme à ton contrat »). Toujours non conforme → siège marqué **non-conforme** : réponse brute conservée, siège exclu de l'arbitrage automatique mais inclus dans la synthèse.
4. **Jamais de remplacement silencieux par une réponse inventée.**

### Étape 4 — Vérification des preuves (Evidence Contract)

Pour chaque finding avec `evidence` de type `file:line`, Aurora relit les lignes citées **au commit SHA noté en étape 1** et marque :

```yaml
verification_status: verified   # la référence existe ET soutient l'affirmation
verification_status: refuted    # la référence ne soutient pas l'affirmation
verification_status: unverified # comportement runtime — nécessite test
```

- La seule existence du fichier/lignes ne suffit pas à `verified`.
- Une objection critique **n'est bloquante qu'après vérification**. Une objection critique plausible non vérifiée → statut `requires_evidence` (investigation ciblée), jamais un blocage automatique.

### Étape 5 — Consolidation (synthétiseur)

Envoyer aux `council-synthesizer` (foreground) : la question originale + les 3 réponses brutes **complètes**, étiquetées par siège. Rapport attendu : Council Response / Per-Seat Details / Council Summary (Consensus Level, Agreed Points, Disagreements, Remaining Uncertainty, **Objections Minoritaires à Préserver**, Recommended Action).

### Étape 6 — Contre-expertise conditionnelle (1 passe max)

Déclenchée **uniquement** si :
- divergence **matérielle** (susceptible de changer le choix technique, le risque accepté ou le plan de validation) — une divergence de style n'est pas matérielle ; ou
- objection critique contestée ; ou
- décision difficilement réversible.

Mécanique : re-prompt du (des) siège(s) concerné(s) via `sessionID` avec les contradictions + preuves vérifiées de l'étape 4. Le siège maintient ou révise sa position sur éléments vérifiables. **Jamais de débat ouvert multi-tours.** Critère d'arrêt : un tour où aucun siège n'apporte d'élément nouveau vérifiable est arrêté immédiatement.

### Étape 7 — Decision Gate (arbitrage Aurora)

Aurora tranche selon les critères pondérés **déclarés dans le brief** (parmi : correction fonctionnelle, compatibilité existant, simplicité/KISS, maintenabilité, sécurité, testabilité, performance, coût, réversibilité, risque). Quatre issues possibles :

| Issue | Condition |
|---|---|
| **DECIDED** | Une approche suffisamment justifiée, objections résolues ou accepted_risk |
| **CONDITIONAL** | Approche retenue sous conditions vérifiables (listées) |
| **INVESTIGATE** | Preuves insuffisantes — investigation ciblée spécifiée avant tout choix |
| **ESCALATE** | Arbitrage utilisateur requis (choix structurant, risque majeur, contradiction des standards) |

Invariants :
- Toute objection matérielle reçoit un statut explicite : `resolved` / `accepted_risk` / `requires_evidence` / `blocking`.
- La décision cite **aussi** les arguments contraires à la recommandation retenue.
- **Une exécution dégradée ne devient jamais silencieusement une décision normale** : si un siège manque (panne ou non-conforme), la perte d'expertise est signalée ; si elle empêche d'évaluer un risque important (ex. guardian absent sur un risque sécurité), le résultat est `INVESTIGATE` ou `ESCALATE`. Minimum 2 sièges opérationnels pour délibérer.

### Étape 8 — Decision Record (non persistant)

Produire le document structuré (réponse utilisateur, statut **PROPOSED**) :

1. Problème analysé
2. Contexte technique vérifié (+ commit SHA)
3. Options envisagées
4. Arguments principaux (avec preuves et verification_status)
5. Objections déterminantes (et leur sort : resolved / accepted_risk / requires_evidence / blocking)
6. Solution retenue (issue du Decision Gate)
7. Justification de l'arbitrage (critères pondérés + arguments contraires)
8. Risques et incertitudes résiduels
9. Plan d'implémentation (si applicable)
10. Stratégie de validation et de tests

Persistance (référence : constitution de provenance du repo, `config/plugins/aurora-memory.ts`) :
- La délibération brute → `docs/ai/BUFFER.md` (statut `pending-ratification`) — autorisé automatiquement.
- `docs/ai/DECISIONS.md` = registre de **ratification** : écriture **uniquement** après approbation explicite de l'utilisateur (statut passe à `ACCEPTED`, provenance `USER_ASSERTION` référençant la délibération). Une décision ratifiée peut être marquée `SUPERSEDED`/`REJECTED` par une décision ultérieure.
- Personne ne commit ni ne pousse depuis une délibération.

## Budgets

| Paramètre | Politique par défaut |
|---|---|
| Sièges | 3 (mode `light` = 2 sièges : skeptic + guardian, sur demande explicite) |
| Analyses | 1 passe |
| Contre-expertise | 1 passe ciblée max |
| Tour improductif | arrêt immédiat (aucun élément nouveau vérifiable) |
| Plafonds tokens/latence | à fixer après la baseline du benchmark pilote — arrêt contrôlé + restitution partielle en cas de dépassement |
| Escalade d'experts domaine | hors MVP (trajectoire future : avis ponctuel injecté, jamais siège permanent) |

## Anti-patterns

- ❌ Débat simulé où Aurora joue adversaire — la contre-expertise repart du siège, pas d'Aurora.
- ❌ Consensus mou — un désaccord argumenté est une valeur, le préserver dans le rapport.
- ❌ Objection inventée pour justifier un siège — guardian et skeptic peuvent conclure « rien à signaler ».
- ❌ Synthèse écrasant les objections minoritaires.
- ❌ Decision Record qui ne cite pas les arguments contraires.
- ❌ Écriture `DECISIONS.md` sans approbation explicite.
- ❌ Relancer le council après un `APPROVED`/`ESCALATE` sans éléments nouveaux significatifs.
