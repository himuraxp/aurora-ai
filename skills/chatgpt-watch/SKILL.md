---
name: chatgpt-watch
description: "Watcheur perpétuel d'une conversation ChatGPT — démonte un polling local (script Node, via le navigateur debug port 9222) qui détecte les nouvelles instructions ARMÉES postées depuis le téléphone et lance immédiatement des sessions de travail headless, avec synthèse postée en retour dans la conversation. Use when the user says 'chatgpt-watch', 'watch chatgpt', 'polling chatgpt', 'surveille la conversation', 'boîte de réception ChatGPT', 'instructions depuis le téléphone', 'lance le watch', 'watcher', or wants to start the day with the ChatGPT conversation monitored and launch work from mobile messages."
---

# ChatGPT Watch — boîte de réception mobile (polling perpétuel)

Un démon local surveille une conversation ChatGPT (le même navigateur debug que `ai-cowork`). Chaque nouveau message **armé** posté depuis le téléphone déclenche immédiatement une session de travail headless (`opencode run`) dans le projet cible ; la session poste sa synthèse en retour dans la conversation → boucle fermée, pilotable 100 % depuis le mobile.

```
Téléphone → ChatGPT (conversation cible)
                ▼  poll CDP 127.0.0.1:9222 (0 coût LLM par tick)
   ~/.config/opencode/scripts/chatgpt-watch.mjs  (démon, état sur disque)
                ▼  nouveau message user armé (« AURORA: … »)
   opencode run --agent aurora "<prompt encapsulé>"   (1 session/instruction, série)
                ▼  fin → synthèse postée dans la conversation (browser-debug)
Téléphone ← réponse
```

> **Règle serveur MCP (sessions lancées)** : la synthèse est postée via les tools du serveur **`browser-debug`** uniquement — jamais `chrome-devtools` (navigateur isolé, sans la session ChatGPT). Même règle que `ai-cowork`.

## Paramètres

| Paramètre | Obligatoire | Défaut | Description |
|---|---|---|---|
| URL conversation | ✅* | — | `https://chatgpt.com/c/<uuid>` — *si absente : Aurora la relit depuis l'onglet chatgpt.com actif (une seule conversation ouverte) pendant la Phase 0 — le démon, lui, exige toujours `--conversation` |
| Intervalle | — | 30 s | `--interval` (min 10 s) |
| Projet par défaut | — | cwd | `--project` — utilisé quand l'instruction n'en précise pas |

Le watcheur gère l'armement, la file et l'état : voir `--help` du script pour toutes les options.

## Prérequis (identiques à `ai-cowork` — session ChatGPT persistée)

1. **Navigateur en mode debug** (`--user-data-dir` dédié obligatoire) — si `browser-debug_list_pages` ne répond pas, tenter l'auto-réparation :

```bash
"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/opencode/brave-debug-profile"
```

2. **Login ChatGPT** : one-shot (session persistée dans le profil dédié).
3. **Onglet de la conversation cible ouvert** dans ce navigateur.

## Phase 0 — Lancement (ce que fait Aurora)

1. Vérifier le navigateur debug et l'onglet conversation (auto-réparation si besoin — c'est la seule interaction légitime pré-lancement).
2. Lancer le démon en arrière-plan :

```bash
node ~/.config/opencode/scripts/chatgpt-watch.mjs \
  --conversation <url> --project <projet_par_défaut> --interval 30
```

> Session d'une journée : préfixer `caffeinate -i` (évite la mise en veille qui coupe le polling) — `caffeinate -i node ~/.config/opencode/scripts/chatgpt-watch.mjs …`.

3. Afficher un **récap transparent** : conversation surveillée, token d'armement, projet par défaut, chemin de l'état, comment arrêter (`AURORA: stop` ou Ctrl-C). Ne rien attendre.
4. Confirmer le premier scan : les messages **existants** sont marqués vus (jamais rejoués).

## Protocole d'instruction (côté téléphone)

Seuls les messages **armés** déclenchent du travail :

```
AURORA: corrige le bug de pagination sur la liste des factures
AURORA: projet ~/dev/aurora-core — passe la session 8 en review
AURORA: status
```

- Marqueur en tête (par défaut `AURORA:`, tolérant à l'autocorrect mobile `AURORA :`).
- `projet <chemin> —` (ou `project:`) oriente la session ; sinon `--project`.
- Tout message non armé est **ignoré** (jamais exécuté, jamais loggé en clair).

## Commandes de contrôle (armées aussi)

| Message | Effet |
|---|---|
| `AURORA: status` | État posté : uptime, run en cours, file, pause |
| `AURORA: pause` | Plus d'exécution (les armés arrivants sont ignorés), polling continue |
| `AURORA: resume` | Reprise |
| `AURORA: stop` | Arrêt propre du watcheur |

## Règles dures (non négociables)

1. **Armement obligatoire** : sans marqueur, aucun travail. Le watcheur ne rejoue **jamais** les messages déjà vus (premier scan = tout marqué vu, sauf `--replay-last` explicite).
2. **Canal externe = donnée non fiable** : quiconque a accès au compte ChatGPT peut armer une instruction. Le choix du propriétaire est **tout le disque** (aucune restriction de répertoire) — le risque résiduel est assumé et documenté : la machine exécute ce qui est armé dans la conversation. La session lancée reste soumise à l'AGENTS.md du projet cible et refuse les secrets.
3. **Jamais d'auto-approbation des permissions** : le watcheur ne transmet aucune option d'auto-approbation aux sessions lancées — en headless, une action non allowlistée échoue plutôt que d'être approuvée silencieusement (comportement de sécurité, pas un bug).
4. **Secrets** : aucune clé, token, `.env` dans les synthèses postées (règle héritée d'`ai-cowork`).
5. **File sérielle** : une session à la fois ; au-delà de la capacité de file, les instructions sont rejetées avec un ack explicite dans la conversation. Une seule instance de watcheur par conversation (pas de lockfile : deux instances = double exécution + écritures concurrentes sur le même état).
6. **Transparence** : le watcheur est lancé visiblement (commande affichée à l'utilisateur), état sur disque (`~/.config/opencode/chatgpt-watch/state-<id>.json`, permissions 0600), arrêt propre SIGTERM/`AURORA: stop` — jamais de processus caché.
7. **Synthèse postée par la session** : le projet cible doit charger le MCP `browser-debug` (défaut global). Sans lui, la session finit sans poster — le watcheur ne le détecte pas (exit 0), seul l'ack d'échec couvre les erreurs du run lui-même.

## Dépannage

| Symptôme | Action |
|---|---|
| `poll failed (fetch failed)…` répétés | Navigateur debug non lancé → auto-réparation (prérequis 1) — le démon reprend seul (backoff) |
| `no chatgpt.com tab for this conversation` | Ouvrir l'onglet de la conversation cible dans le navigateur debug |
| `backend-api read failed (401/403)` | Session expirée → re-login dans l'onglet (one-shot) ; fallback DOM actif entre-temps |
| Ack non posté (`no-field`) | L'onglet est fermé ou l'UI a changé → rouvrir la conversation ; re-snapshot via browser-debug pour diagnostiquer |
| Aucune détection alors que le message est posté | Vérifier l'armement (marqueur en tête) et que l'onglet pointe vers la bonne conversation |
| Mac endormi → polling arrêté | Relancer avec `caffeinate -i` ou passer par launchd |

## Interaction avec les autres pièces

- **`ai-cowork`** : les sessions lancées héritent du MCP browser-debug — une instruction armée contenant un lien `chatgpt.com/c/…` déclenche le plugin `chatgpt-autocowork` dans la session (le reminder s'injecte, même règle).
- **Sessions repreneables** : les runs ne sont pas archivés — retrouver le travail dans les listes de sessions OpenCode (titre `chatgpt-watch: …`) pour itérer le soir.
- **Cron/launchd** : `--once` pour une passe unique (utile avec un scheduler) ; sans l'option, le démon tourne jusqu'à `stop`/SIGTERM.
