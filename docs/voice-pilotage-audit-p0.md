# Pilotage vocal d'Aurora / OpenCode V2 depuis ChatGPT — rapport P0 (version publique)

**Date :** 24 octobre 2026 · **Statut :** audit P0 réalisé en lecture seule · **Version :** publique, expurgée
**Source :** carte Trello du projet — « Pilotage vocal d'Aurora / OpenCode depuis ChatGPT »

> **Note de publication.** Ce document est la version publique du rapport P0. Un lecteur anonyme doit pouvoir comprendre le produit, ses limites et ses garanties attendues — il ne doit pas pouvoir en déduire les chemins sensibles, les surfaces d'administration, les faiblesses observées ni leur enchaînement. Le rapport détaillé (preuves par commandes), le threat model et le plan de remédiation sont conservés dans un espace privé hors de ce dépôt.

---

## 1. Objectif et exigences

Depuis une conversation ChatGPT (voix puis dictée), confier une mission de développement à un agent local (Aurora, piloté par OpenCode) qui l'exécute de manière isolée (worktree dédié), avec suivi, résultats et reprise possibles.

La mission P0 fixait sept exigences : **diagramme réel du pipeline** ; **interfaces réellement disponibles** (avec preuves) ; **couplage à la session existante** ; **points d'intégration possibles** ; **risques et cas d'échec** ; **prototype minimal** ; **décision d'intégration**. Aucune modification de production, aucun déploiement.

## 2. Diagramme logique du pipeline

```txt
Mobile (ChatGPT Voice → dictée → texte) — ou — raccourci vocal natif
  │
  ▼  transport authentifié (connecteur distant OU appel local direct)
Passerelle locale : auth · allowlist projets · contrat de mission · anti-rejeu · journal
  │
  ▼  API locale de l'exécuteur (service permanent de la plateforme d'agents)
Exécuteur isolé (agent dédié, permissions minimales, outils filtrés)
  │
  ▼  orchestration de workflow existante (skills + scripts CLI purs)
Espace de travail isolé (worktree) → état de mission persistant hors dépôt → revue humaine (MR)
  │
  ▼  traçabilité : suivi d'avancement, recherche de sessions, reprise après interruption
```

## 3. Interfaces réellement disponibles (familles fonctionnelles)

| Famille | Capacités | Rôle dans le pilotage |
|---|---|---|
| **Service permanent de l'exécuteur** | Serveur local auto-découvrable ; création/attachement de sessions ; injection d'instructions ; flux d'événements de suivi ; export de résultats ; lecture des demandes d'autorisation | Point d'ancrage de la passerelle — couvre toute la boucle mission |
| **CLI non interactive** | Exécution d'un message dans une session nommée (idempotente) ; listage/export des sessions | Pilotage scriptable sans API ; attachement déterministe |
| **SDK clients** | Client typé généré du contrat d'API (promises + streams) | Passerelle implémentée proprement, sans ad-hoc |
| **Orchestration de workflow existante** | Skills chargés dans une session ; outils d'état et de création d'espace de travail isolé (CLI purs, exploitables directement) ; bascule vers l'environnement interactif | Réutilisés tels quels — aucune réimplémentation |
| **Surface vocale native de l'exécuteur** | Endpoints expérimentaux de session vocale (transport temps réel) | Alternative vocale locale à qualifier, indépendante de ChatGPT |

Les détails précis (versions, adresses, endpoints, preuves par commandes) sont volontairement absents de ce document public — ils figurent dans le rapport détaillé privé.

## 4. Couplage à la session existante

- Les briques d'**état** et de **création d'espace de travail** sont des CLI purs, exploitables directement par une passerelle.
- L'**orchestration** (analyse, développement, QA, MR) reste un travail de session d'agent — voulu et sain.
- Architecture cible : **la passerelle crée ou attache une session dédiée via l'API, puis y injecte la mission** ; elle associe de façon persistante l'identifiant de mission, la session, le projet et le périmètre autorisé — dans un état persistant hors dépôt, jamais dans le seul prompt.
- Trois opérations à distinguer : **création** (session dédiée), **attachement** (session existante vérifiée : identité + politique effective + contexte), **reprise** après interruption (idempotente). Une session non conforme est refusée.

## 5. Options d'intégration (abstraites)

| Option | Principe | Statut |
|---|---|---|
| **A — API locale de l'exécuteur** | La passerelle pilote sessions et instructions via l'API du service permanent | Recommandée (contrat officiel, testable) |
| **B — Déclenchement par skill** | Invocation d'un skill dans une session via un endpoint expérimental | Complément seulement (instabilité possible entre versions) |
| **C — Basculer vers l'environnement interactif** | Transfert de la mission vers un terminal visible pour l'humain | Confort interactif, jamais un prérequis |

**Transport amont** : connecteur distant de ChatGPT (serveur distant public ou tunnel dédié du fournisseur, avec authentification) — **le tool-calling vocal natif n'est pas validé** : une limitation confirmée et spécifique (les actions de GPT custom ne s'exécutent pas en mode voix) ne démontre pas l'impossibilité de tous les mécanismes vocaux ; la validation du transport retenu reste une dépendance externe. Alternative immédiate : **raccourcis vocaux natifs (Siri Shortcuts)** vers un appel local authentifié — voix 100 % locale, aucun tunnel.

## 6. Contrat de mission (générique) et machine d'états

```json
{
  "mission_id": "uuid",
  "project_key": "projet-autorise",
  "task": "intention de mission",
  "mode": "read_only",
  "requested_by": "derive-du-canal-authentifie"
}
```

Principes contractuels :

- **L'autorité est côté serveur** : le transport ne transmet qu'une *intention de mission* (identifiant, projet autorisé, demande utilisateur). Le mode, la politique d'approbation et la politique d'outils sont fixés par la passerelle — jamais par le client.
- **Validation serveur** obligatoire (présence des champs, projet ∈ allowlist, mode ∈ ensemble fermé) — refus explicite sinon.
- **Machine d'états minimale** : `queued → running → (awaiting_approval → running)* → done | failed | blocked` (+ `cancelled`) ; une demande d'autorisation humaine met la mission en `awaiting_approval`, jamais un état « réussi » silencieux.
- **Déduplication idempotente** : soumission répétée d'un identifiant connu → état existant ; jamais une seconde session ni un second espace de travail.

## 7. Prototype minimal (spécification générique, non codé)

Une passerelle locale unique (~200 lignes) exposant : création de mission (`start_task`), consultation d'état (`get_status`), lecture du rapport (`get_report`). Elle applique :

- une **sémantique de mode garantie techniquement** : `read_only` = aucune écriture dans le projet ni les fichiers de production ; écritures techniques limitées au journal et à l'état de mission (hors dépôt) ; le périmètre est imposé **par la politique d'outils de la session créée**, vérifiée avant tout instruction — le contenu d'un prompt n'est jamais une garantie ;
- des **rapports structurés** produits par une voie de sortie contrôlée (résumé déterministe) — jamais l'export brut d'une session vers un tiers ;
- des **limites de ressources** (payload, missions concurrentes, quota par canal) et un **journal d'audit** local sans contenu de payload.

## 8. Sécurité — synthèse publiable

Un audit de sécurité défensif (threat model, 15 constats) a été réalisé sur le design et la configuration ; ses détails exploitables restent **privés**. Catégories de risques traitées :

1. **Isolation des privilèges d'exécution** — une mission ne doit jamais hériter des privilèges de l'agent orchestrateur principal : agents dédiés à permissions minimales, sélection fail-closed, exclusion des outils à accès authentifié.
2. **Gestion des secrets** — l'agent de mission ne doit avoir aucun chemin d'accès aux credentials personnels (pas seulement via les outils fichiers : tout canal d'exécution) ; aucun secret dans les journaux, rapports ou exports.
3. **Exposition réseau locale** — l'API de l'exécuteur n'est pas une frontière de confiance : contrôle d'origine/hôte, anti-CSRF, limites de fréquence, supervision des demandes d'autorisation avec notification humaine (jamais d'approbation automatique).
4. **Intégrité de la configuration** — prévention de l'altération persistante (contrôles d'intégrité, périmètre d'écriture restreint).
5. **Divulgation dans un dépôt public** — ce dépôt est public : séparation stricte entre documentation publiable et informations opérationnelles (voir politique ci-dessous).

**Politique de publication** (définitive) :

| Niveau | Contenu |
|---|---|
| **PUBLIC** (ce dépôt) | Architecture logique, interfaces produit, contrats génériques, principes de sécurité, documentation utilisateur |
| **PRIVÉ** (hors dépôt, accès restreint) | Threat model détaillé, constats de sécurité, chaînes d'exploitation, preuves, plans de remédiation opérationnels |
| **LOCAL UNIQUEMENT** | Secrets, configuration d'exécution effective, mappings de projets personnels, journaux, état des missions |

Règle directrice : **un prompt, un message de carte ou un agent intermédiaire ne peut jamais déléguer une autorisation** (approbation, merge, publication).

## 9. Décision d'intégration (mise à jour PO)

> **NO-GO développement fonctionnel — suspendu jusqu'à complétion du P0 de confinement.** L'APPROVED antérieur sur la forme documentaire est révoqué : le risque principal n'est plus le transport vocal mais l'exécution de missions non fiables dans un environnement héritant de privilèges trop élevés, aggravé par la publication dans un dépôt public.

Ordre de résolution strict :

1. **Confidentialité du dépôt** — assainissement des artefacts publiés, politique de publication appliquée (fait : ce document est la version publique expurgée ; le détaillé est en privé) ;
2. **Isolation des agents** — exécuteurs dédiés à permissions minimales, isolation prouvée des secrets ;
3. **Contrats et permissions** — autorité côté serveur, validation, refus explicites ;
4. **Passerelle** — baseline de sécurité complète (auth, anti-CSRF, limites, journal) ;
5. **Tests** — refus, concurrence, permissions, reprise, isolation ;
6. **Transport vocal** — raccourcis natifs authentifiés d'abord ; connecteur distant et voix native réévalués après nouvelle revue de sécurité.

**Décision d'intégration globale : CONDITIONAL** — l'architecture est cohérente ; sa mise en œuvre est conditionnée aux critères de sortie de chaque phase, avec validation humaine aux jalons (aucun GO P1 avant validation du P0 de confinement).

## 10. Prochaines étapes (publiques, abstraites)

- P0 : assainissement des artefacts publiés (fait), revue de publication, traitement de l'historique de branche, vérification qu'aucun credential n'a été exposé ;
- P1 : exécuteurs isolés → passerelle minimale → tests d'intégration → transport vocal local authentifié ;
- P2 : mode contrôlé, intégrations avancées — après nouvel audit de sécurité et arbitrage humain explicite.
