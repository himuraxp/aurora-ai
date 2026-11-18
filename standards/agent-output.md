# Standard — Format de retour des sous-agents

## Principe

Tous les sous-agents retournent leur résultat dans un **format JSON structuré** inclus dans leur message final. Ce format permet à Aurora de **parser, consolider, comparer et afficher** les résultats de manière déterministe, quel que soit l'agent émetteur.

Le format est **obligatoire** pour toute délégation via `task`. Les agents qui ne respectent pas ce format sont considérés comme en échec partiel (voir `delegation-failure.md`).

## Schéma JSON

```json
{
  "$schema": "agent-output.v1",
  "agent": "string",
  "task": "string",
  "status": "success | partial | failure",
  "summary": "string (1-3 phrases)",
  "findings": [
    {
      "id": "string (unique dans le rapport)",
      "category": "string (ex: seo, technical, content, growth, security, code, performance, accessibility)",
      "severity": "critical | high | medium | low | info",
      "title": "string (court, descriptif)",
      "description": "string (explication du constat)",
      "evidence": "string (preuve : fichier, ligne, URL, header HTTP, métrique, etc.)",
      "recommendation": "string (action concrète proposée)",
      "expected_outcome": "string (résultat attendu)",
      "effort": "low | medium | high",
      "confidence": "established | reasonable | experimental",
      "files": ["string (chemins de fichiers concernés)"],
      "dependencies": ["string (agents ou équipes dépendantes)"],
      "kpi": "string (métrique à suivre, si pertinent)",
      "tags": ["string (mots-clés libres pour cross-referencing)"]
    }
  ],
  "metrics": [
    {
      "name": "string",
      "value": "string | number",
      "unit": "string",
      "benchmark": "string (référence de comparaison, si pertinent)"
    }
  ],
  "conflicts": [
    {
      "topic": "string (sujet du conflit)",
      "position": "string (position de cet agent)",
      "reasoning": "string (justification)"
    }
  ],
  "gaps": ["string (informations manquantes ou périmètre non couvert)"],
  "next_steps": ["string (actions suivantes recommandées, ordonnées par priorité)"],
  "metadata": {
    "duration_hint": "fast | medium | slow",
    "scope": "string (périmètre couvert)",
    "sources": ["string (URLs ou références consultées)"]
  }
}
```

## Règles de remplissage

### Champs obligatoires vs optionnels

| Champ | Obligatoire | Notes |
|-------|-------------|-------|
| `agent` | Oui | Nom de l'agent émetteur |
| `task` | Oui | Description courte de la tâche reçue |
| `status` | Oui | `success` / `partial` / `failure` |
| `summary` | Oui | 1-3 phrases, synthèse exécutive |
| `findings` | Oui si `status != failure` | Peut être vide `[]` si aucun finding |
| `findings[].id` | Oui si finding présent | Unique dans le rapport (ex: `F-01`, `F-02`) |
| `findings[].category` | Oui si finding présent | Voir catégories normalisées ci-dessous |
| `findings[].severity` | Oui si finding présent | `critical` > `high` > `medium` > `low` > `info` |
| `findings[].title` | Oui si finding présent | Court et descriptif |
| `findings[].description` | Oui si finding présent | Explication du constat |
| `findings[].recommendation` | Oui si finding présent | Action concrète |
| `findings[].evidence` | Recommandé | Preuve observable |
| `findings[].expected_outcome` | Recommandé | Résultat attendu |
| `findings[].effort` | Optionnel | `low` / `medium` / `high` |
| `findings[].confidence` | Optionnel | Sage : obligatoire. Autres : si pertinent |
| `findings[].files` | Optionnel | Crawler/Security : recommandé |
| `findings[].dependencies` | Optionnel | Voir `findings[].tags` pour cross-referencing |
| `findings[].kpi` | Optionnel | Pulse/Beacon : recommandé |
| `findings[].tags` | Optionnel | Mots-clés pour consolidation transversale |
| `metrics` | Optionnel | Beacon : recommandé. Scores, counts, etc. |
| `conflicts` | Optionnel | Position de l'agent sur un sujet controversé |
| `gaps` | Optionnel | Ce qui n'a pas pu être couvert |
| `next_steps` | Recommandé | Actions suivantes par priorité |
| `metadata` | Optionnel | Contexte d'exécution |

### Catégories normalisées

| Catégorie | Description | Agents typiques |
|-----------|-------------|-----------------|
| `seo` | Stratégie SEO, keywords, content gaps, SERP | Atlas |
| `technical` | SEO technique, indexation, rendu, Core Web Vitals | Crawler |
| `aio` | AI Overviews, GEO, extractability, citation potential | Sage |
| `content` | Contenu éditorial, copywriting, meta | Scribe |
| `growth` | Acquisition, conversion, funnel, CRO | Pulse |
| `social` | Distribution sociale, multi-canal | Echo |
| `analytics` | Mesure, GA4, GSC, rank tracking | Beacon |
| `code` | Qualité code, architecture, breaking changes | Reviewer, Architect |
| `security` | Vulnérabilités, secrets, injections, exploits, pentest | Security, Cybersec |
| `performance` | Perf applicative, bundle, latence | Tester, Crawler |
| `accessibility` | A11y, ARIA, contrast, keyboard | Reviewer |
| `tests` | Couverture, edge cases, qualité des tests | Tester |

### Niveaux de sévérité

| Sévérité | Définition | Action attendue |
|----------|------------|-----------------|
| `critical` | Bloquant, risque immédiat (indexation, sécurité, breaking change) | Action immédiate |
| `high` | Impact significatif, doit être traité rapidement | Priorité 1 |
| `medium` | Amélioration notable, à planifier | Priorité 2 |
| `low` | Optimisation mineure, nice-to-have | Priorité 3 |
| `info` | Observation sans action requise | Information |

## Format de transmission

Le sous-agent inclut le JSON dans son message final, dans un bloc de code marqué `json` :

````markdown
## Résultat

```json
{
  "$schema": "agent-output.v1",
  "agent": "atlas",
  "task": "Audit SEO stratégique - exemple.com",
  ...
}
```

Le sous-agent peut ajouter du texte libre **avant** le bloc JSON pour le contexte, mais le bloc JSON doit être **le dernier élément** du message.
````

## Règles

- **Obligatoire** : tout sous-agent sollicité via `task` par Aurora doit retourner le format JSON. Un retour sans JSON est un échec partiel.
- **Unicité** : les `findings[].id` doivent être uniques dans le rapport d'un agent.
- **Honnêteté** : `status: partial` ou `status: failure` doit être utilisé honnêtement. Ne jamais masquer un échec.
- **Pas d'invention** : si une information manque (evidence, metric), utiliser `null` ou omettre le champ. Ne jamais inventer.
- **Concision** : les champs textuels (`description`, `recommendation`, `summary`) doivent être concis. Pas de pavés.
- **Confidence** : le champ `confidence` est obligatoire pour Sage, optionnel pour les autres. Ne jamais présenter une hypothèse comme `established`.

## Consolidation par Aurora

Quand Aurora reçoit plusieurs retours d'agents (délégation parallèle), elle doit :

1. **Parser** chaque bloc JSON.
2. **Détecter les conflits** : deux agents avec des `findings` ou `conflicts` contradictoires sur le même `category` + `tags`.
3. **Fusionner** les `findings` de tous les agents en une liste unique triée par `severity` puis `effort`.
4. **Agréger** les `metrics` dans un tableau de bord.
5. **Produire un rapport unifié** au format défini ci-dessous.

### Rapport de consolidation

```markdown
## Rapport consolidé — [sujet de la demande]

### Synthèse exécutive

[Brief de 3-5 phrases]

### Tableau de bord

| Agent | Statut | Findings | Critiques | Score |
|-------|--------|----------|-----------|-------|
| ... | ... | ... | ... | ... |

### Findings consolidés (triés par sévérité)

#### Critical
- **[F-XX]** [Agent] — [Title] — [Recommendation]
  - Evidence: ...
  - Effort: ... | Confidence: ...

#### High
...

#### Medium
...

### Conflits détectés

| Sujet | Agent A | Position A | Agent B | Position B | Résolution |
|-------|---------|-----------|---------|-----------|------------|
| ... | ... | ... | ... | ... | [recommandation d'Aurora] |

### Métriques agrégées

| Métrique | Valeur | Benchmark | Source |
|----------|--------|-----------|--------|
| ... | ... | ... | ... |

### Prochaines étapes (priorisées)

1. [Action] — [Agent responsable] — [Priorité]
2. ...

### Gaps

- ...
```

## Anti-patterns

- ❌ Retourner du texte libre sans bloc JSON.
- ❌ `status: success` avec `findings: []` et `gaps` non vide (masquer un échec).
- ❌ Inventer des `evidence` ou `metrics` non observés.
- ❌ `findings[].id` dupliqués dans le même rapport.
- ❌ Champs textuels de plus de 500 caractères (utiliser `description` court + renvoi).
- ❌ Omettre le bloc JSON "par oubli" — c'est un échec partiel.

## Compatibilité avec les formats existants

Les agents qui ont déjà une section `## Output expectations` conservent leurs conventions métier (sévérité, niveaux de confiance, etc.). Le schéma JSON est une **couche de transport** qui encapsule ces conventions :
| Format agent | Mapping vers le schéma |
|---------------|----------------------|
| Atlas : Finding / Impact / Recommendation / Priority / Expected outcome | `findings[].title` / `findings[].description` / `findings[].recommendation` / `findings[].severity` / `findings[].expected_outcome` |
| Crawler : Issue / Evidence / SEO impact / Recommended fix / Files concerned | `findings[].title` / `findings[].evidence` / `findings[].description` / `findings[].recommendation` / `findings[].files` |
| Sage : Finding / Mechanism / Confidence / Recommendation / Expected outcome | `findings[].title` / `findings[].description` / `findings[].confidence` / `findings[].recommendation` / `findings[].expected_outcome` |
| Pulse : Hypothesis / Target audience / Action / Expected impact / Effort / KPI | `findings[].title` / `findings[].tags` / `findings[].recommendation` / `findings[].expected_outcome` / `findings[].effort` / `findings[].kpi` |
| Reviewer : Verdict / Points bloquants / Axes / Suggestions / Tests | `summary` / `findings[]` (severity=critical) / `findings[]` (category=code) / `findings[]` (category=tests) / `next_steps` |
| Scribe : Livrable / Title / Meta / H1-H3 / Structured data | `summary` + `findings[]` (category=content) / contenu en texte libre avant le JSON |
| Echo : Déclinaison par canal / Hook / Body / CTA | `findings[]` (category=social, tags=[canal]) / `findings[].title` / `findings[].description` / `findings[].recommendation` |
| Beacon : Observation / Evidence / Interpretation / Action / KPI / Before-After-Delta | `findings[].title` / `findings[].evidence` / `findings[].description` / `findings[].recommendation` / `findings[].kpi` + `metrics[]` |
| Security : Vulnérabilité / Sévérité / Cause racine / Remédiation / Retest / Fichier | `findings[]` (category=security) / `findings[].severity` / `findings[].evidence` / `findings[].recommendation` / `findings[].expected_outcome` / `findings[].files` + `metrics[]` (risk-score) |
| Cybersec : Vecteur / Exploit / Preuve / Impact / Action défensive | `findings[]` (category=security, tags=["initial-access"...]) / `findings[].description` / `findings[].evidence` / `findings[].expected_outcome` / `findings[].recommendation` + `metrics[]` (access-depth) |
| Architect : Objectif / Fichiers / Plan / Risques / Tests | `summary` / `findings[].files` / `next_steps` / `findings[]` (category=code) / `findings[]` (category=tests) |
| Tester : Tests créés / Fichiers / Comportement / Statut | `findings[]` (category=tests) / `findings[].files` / `findings[].title` / `findings[].tags` |
| Spark : Commit / MR / Skill CLI | `summary` (résultat de l'action) + `status` + `metadata.scope` (commande exécutée) |
| Vision : Description d'image / UI / diagramme | `summary` (synthèse visuelle) + `findings[]` (category=code pour UI, tags=["visual"]) + `metadata.sources` (référence image) |
| Designer : Composant / États / Accessibilité / Tokens | `findings[]` (category=accessibility) / `findings[].recommendation` / `metadata.scope` (UX/UI/DA/DS) |
| Mobile : Performance / Code mobile | `findings[]` (category=performance, files[]) / `findings[].recommendation` / `metadata.scope` (iOS/Android/RN/Flutter) |

## Extensions Council (skills/council)

Deux écarts au schéma de base, **délibérés et standardisés** pour les agents `council-*` (délégation via `skills/council/SKILL.md`) :

1. **`missing_context_or_framing_bias`** — champ top-level (string) obligatoire dans les retours des sièges `council-architect` / `council-skeptic` / `council-guardian`. Signale un angle mort du brief ou un cadrage orienté ; valeur `"none"` si le cadrage est neutre et complet. Il s'ajoute au schéma sans remplacer aucun champ standard.
2. **Synthétiseur en markdown** — `council-synthesizer` retourne un rapport markdown structuré (Council Response / Per-Seat Details / Council Summary) et **non** un bloc JSON : c'est l'exception unique à la règle « bloc JSON obligatoire ». Justification : il n'a aucun outil et son contrat de sortie est intégralement spécifié dans son prompt système ; la consolidation Aurora le traite comme un document, pas comme un set de findings.

Les identités `agent` des sièges sont `council-architect`, `council-skeptic`, `council-guardian` (jamais `architect`/`skeptic`/`guardian` seuls — collision avec les agents généraux existants).
