"""Canal interactif MP kChat → moteur (J3 : propositions ; J4 : confirmations).

Invariants (ARCHITECTURE §11) :
- Seuls les posts du PROPRIÉTAIRE (recipient_id résolu) dans le DM bot–propriétaire
  sont considérés. Tout le reste : IGNORE total (aucune réponse, aucun détail,
  compteur technique sans contenu).
- Un post = une commande : registre `post_id` PRIMARY KEY — idempotence, rejeu
  impossible, reprise après crash sans double traitement.
- Collecte PAGINÉE EXHAUSTIVE jusqu'au checkpoint (jamais « les 60 derniers +
  curseur avancé ») ; checkpoint gelé si la pagination est incomplète.
- Le texte du MP est une donnée non fiable : grammaire en liste blanche (regex
  ancrées), jamais d'exécution libre, jamais de texte intégral en audit.
- J3 : les verbes de tri créent des PROPOSITIONS (jamais d'exécution). Destinations
  par alias strict → chemin canonique → policy.py ; dossier interdit = refus
  immédiat ; références globalement non ambiguës (compteur monotone, t10) ;
  ambiguïté = REFUS ; limites de volume.
- J4 : `ok #pN` consomme la proposition (§11.4/§11.8) — réservation ATOMIQUE
  pending→executing, revalidation (gates, SHA-256 global rules.json, allowlist),
  exécution du contenu FIGÉ dans proposals.action (jamais re-résolu),
  applied/uncertain/rejected. Usage unique ; le MP ne contourne jamais policy.py.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import kchat
import policy
import rules_writer
from rules_writer import rules_sha256  # ré-exporté (empreinte des propositions)
from state import FileLock

MAX_COMMAND_LENGTH = 256     # limite d'une commande (§11.6)
MAX_PAGES = 20               # garde-fou pagination (20 × 30 = 600 posts max)
PAGE_SIZE = 30
MOVE_PROPOSAL_TTL_MIN = 30   # §11.4 : déplacement ponctuel
RULE_PROPOSAL_TTL_HOURS = 24  # §11.4 : règle
RULE_PRIORITY_SENDER = 150   # règle interactive expéditeur (sous les manuelles)
RULE_PRIORITY_DOMAIN = 155   # domaine = plus puissant → perd les égalités
EXECUTING_STALE_HOURS = 26   # sweep des 'executing' orphelins (TTL max 24 h + marge)

_RE_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
_RE_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class InteractiveError(Exception):
    """Échec du canal interactif (pagination incomplète, réponse kChat…)."""


_RE_AIDE = re.compile(r"^\s*(aide|help)\s*$", re.IGNORECASE)
_RE_STATUT = re.compile(r"^\s*statut\s*$", re.IGNORECASE)
_RE_ITEM_MOVE = re.compile(r"^\s*#([a-z]\d+)\s*(?:→|->)\s*(\S.{0,120}?)\s*$", re.IGNORECASE)
_RE_RULE = re.compile(r"^\s*(expediteur|expéditeur|domaine)\s+(\S+)\s*(?:→|->)\s*(\S.{0,120}?)\s*$",
                      re.IGNORECASE)
_RE_OK = re.compile(r"^\s*ok\s+#([a-z0-9]+)\s*$", re.IGNORECASE)
_RE_ANNULE = re.compile(r"^\s*(?:annule|annuler)\s+#([a-z0-9]+)\s*$", re.IGNORECASE)
# J4bis (§12.4) : clôture workflow — `traite #ref → alias` = déplacement stockage
# + \Seen (réconcilié par Message-ID). Destination de stockage EXPLICITE obligatoire
# (jamais de stockage implicite) ; sans flèche → aide au format.
_RE_TRAITE = re.compile(r"^\s*(?:traite|traiter)\s+#([a-z]\d+)\s*(?:→|->)\s*(\S.{0,120}?)\s*$",
                        re.IGNORECASE)
_RE_TRAITE_BARE = re.compile(r"^\s*(?:traite|traiter)\s+#([a-z]\d+)\s*$", re.IGNORECASE)
# `#a1 : texte libre` / `#a1 texte` (sans flèche) : réponse ÉDUCATIVE, jamais
# d'exécution — cas réel 2026-10-26 (`#a1 : quand c'est failed pipeline…`).
# DOTALL : le cas réel multi-lignes (2 instructions en 1 post) doit aussi
# recevoir l'aide au format.
_RE_REF_TYPO = re.compile(r"^\s*#([a-z]\d+)(?!\s*(?:→|->))\s*[:：]?\s*\S.*$", re.IGNORECASE | re.DOTALL)

_REPLY_AIDE = (
    "**Mail Triage — commandes**\n"
    "- `aide` — cette liste\n"
    "- `statut` — état du moteur\n"
    "- `#{ref} → {alias}` — déplacer le message d'un digest (ex. `#n1 → gitlab`)\n"
    "- `expediteur {addr} → {alias}` / `domaine {domaine} → {alias}` — proposer une règle\n"
    "- `traite #{ref} → {alias}` — clôturer du workflow : déplacement stockage + lu (ex. `#l1 → gitlab`)\n"
    "- `ok #{pid}` / `annule #{pid}` — confirmer / annuler une proposition\n"
    "_Les dossiers disponibles (aliases) sont listés par `statut`. "
    "La création de dossier ne se fait pas via le MP._"
)
_REPLY_OK_PENDING = (
    "Confirmation `ok #{pid}` reconnue :heavy_check_mark: "
    "Les confirmations de propositions ne sont pas encore activées "
    "(écriture désactivée). La proposition reste en attente."
)
_REPLY_UNKNOWN = "Commande non reconnue. Réponds `aide` pour la liste des commandes."


def parse_command(text: str) -> dict:
    """Grammaire niveau 1 : verbes reconnus sinon `inconnu`. Le texte du MP est
    une donnée non fiable — aucune exécution libre, jamais (§11.6)."""
    if not text:
        return {"verb": "inconnu"}
    if len(text) > MAX_COMMAND_LENGTH:
        # Post trop long (cas réel : plusieurs instructions multi-lignes) —
        # s'il commence par une ref, aide éducative au lieu du générique ;
        # JAMAIS d'exécution d'un texte hors limite.
        m = re.match(r"^\s*#([a-z]\d+)\b", text, re.IGNORECASE)
        if m:
            return {"verb": "ref_syntax", "ref": m.group(1).lower()}
        return {"verb": "inconnu"}
    if _RE_AIDE.match(text):
        return {"verb": "aide"}
    if _RE_STATUT.match(text):
        return {"verb": "statut"}
    m = _RE_ITEM_MOVE.match(text)
    if m:
        return {"verb": "item_move", "ref": m.group(1).lower(), "dest_text": m.group(2).strip()}
    m = _RE_TRAITE.match(text)
    if m:
        return {"verb": "treat", "ref": m.group(1).lower(), "dest_text": m.group(2).strip()}
    m = _RE_TRAITE_BARE.match(text)
    if m:
        return {"verb": "treat_bare", "ref": m.group(1).lower()}
    m = _RE_RULE.match(text)
    if m:
        return {"verb": "rule_create", "scope": m.group(1).lower().replace("é", "e"),
                "value": m.group(2), "dest_text": m.group(3).strip()}
    m = _RE_OK.match(text)
    if m:
        return {"verb": "ok", "proposal_ref": m.group(1).lower()}
    m = _RE_ANNULE.match(text)
    if m:
        return {"verb": "annule", "proposal_ref": m.group(1).lower()}
    m = _RE_REF_TYPO.match(text)
    if m:
        return {"verb": "ref_syntax", "ref": m.group(1).lower()}
    return {"verb": "inconnu"}


def collect_new_posts(client: kchat.KChatClient, channel_id: str, owner_user_id: str,
                      state) -> list[dict]:
    """Collecte paginée EXHAUSTIVE jusqu'au checkpoint (§11.3) : remonte par
    `before` jusqu'à couvrir le checkpoint ou l'origine du canal. Tri
    (create_at, post_id). Post édité ou supprimé → ignoré. Checkpoint gelé si
    la pagination est incomplète (jamais d'avance sur un trou). Le filtre
    PROPRIÉTAIRE vit dans run_once (point de décision unique, §11.7)."""
    checkpoint = state.interactive_checkpoint()
    seen: dict[str, dict] = {}
    before: str | None = None
    reached_origin = checkpoint is None  # premier run : baseline, fenêtre = 1 page
    for _ in range(MAX_PAGES):
        if before is None:
            posts = client.recent_channel_posts(channel_id, per_page=PAGE_SIZE)
        else:
            posts = client.channel_posts_before(channel_id, before, per_page=PAGE_SIZE)
        if not posts:
            reached_origin = True
            break
        for post in posts:
            seen[post.get("id") or ""] = post
            if checkpoint and post.get("id") == checkpoint["last_post_id"]:
                reached_origin = True
        if reached_origin:
            break
        oldest = min(posts, key=lambda p: (p.get("create_at") or 0, p.get("id") or ""))
        before = oldest.get("id")
    if not reached_origin:
        raise InteractiveError("pagination incomplète — checkpoint gelé (§11.3)")
    if checkpoint is None:
        return []  # baseline : on ne traite pas l'historique antérieur au canal
    last_key = (checkpoint["last_created_at"], checkpoint["last_post_id"])
    candidates = [
        p for p in seen.values()
        if not p.get("edit_at") and not p.get("delete_at")
        and ((p.get("create_at") or 0), p.get("id") or "") > last_key
    ]
    candidates.sort(key=lambda p: ((p.get("create_at") or 0), p.get("id") or ""))
    return candidates


# --- J3 : destinations, empreintes, propositions --------------------------------


def resolve_destination(dest_text: str, cfg: dict) -> tuple[str | None, str]:
    """Alias strict → chemin canonique (§11.6) : alias du config OU nom canonique
    exact de l'allowlist. Retourne (canonique, "ok") ou (None, raison).
    destination_is_allowed vérifie allowlist ET exclusions absolues
    (Trash/Spam/Drafts/Sent) — l'allowlist ne les neutralise jamais (t10)."""
    text = (dest_text or "").strip().strip("`")
    aliases = cfg.get("interactive", {}).get("aliases", {}) or {}
    canonical = aliases.get(text.lower())
    if canonical is None:
        allowlist = cfg.get("destinations", {}).get("allowlist", []) or []
        if text in allowlist:
            canonical = text
    if canonical is None:
        return None, "unknown_alias"
    if not policy.destination_is_allowed(canonical, cfg.get("destinations", {}).get("allowlist", []) or []):
        return None, "forbidden"
    return canonical, "ok"


def _limits(cfg: dict) -> dict:
    inter = cfg.get("interactive", {})
    return {
        "max_rule_per_day": int(inter.get("max_rule_proposals_per_day", 5)),
        "max_pending": int(inter.get("max_pending_proposals", 10)),
        "max_commands_5min": int(inter.get("max_commands_per_5min", 30)),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_rate_limit(state, limits: dict) -> bool:
    """30 commandes / 5 min (§11.6) — anti-flood avant tout traitement.
    Sémantique exacte (F-06 review J3) : la commande courante est DÉJÀ
    enregistrée (ancre d'idempotence) et compte dans la fenêtre → refus dès
    que le total dépasse max : exactement `max` commandes traitées / 5 min."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return state.commands_in_window(now_ms - 5 * 60 * 1000) <= limits["max_commands_5min"]


def _allocate_pid(state, kind: str, cfg: dict) -> tuple[str | None, str]:
    """Vérifie les limites (§11.6) puis alloue un id opaque monotone (p<n> —
    jamais réutilisé). Retourne (pid|None, raison). F-01 : le budget « pending »
    ne compte que les propositions ACTIVES (expires_at > maintenant) — une
    proposition expirée libère son slot. Le quota quotidien de règles compte
    TOUT (annulées comprises, anti-boucle)."""
    limits = _limits(cfg)
    now_iso = _now_iso()
    if state.pending_proposals_count(now_iso) >= limits["max_pending"]:
        return None, "too_many_pending"
    if kind == "rule":
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                       microsecond=0).isoformat()
        if state.rule_proposals_since(day_start) >= limits["max_rule_per_day"]:
            return None, "rule_daily_limit"
    return f"p{state.next_ref_number('p')}", "ok"


def _save_proposal(state, pid: str, kind: str, owner_user_id: str, channel_id: str,
                   action: dict, ttl: timedelta, config_dir_path) -> None:
    now = _now_iso()
    state.create_proposal({
        "proposal_id": pid, "kind": kind, "owner_user_id": owner_user_id,
        "channel_id": channel_id, "action": json.dumps(action, ensure_ascii=False),
        "target_version": rules_sha256(config_dir_path),
        "created_at": now, "expires_at": (datetime.now(timezone.utc) + ttl).isoformat(),
        "status": "pending", "source_post_id": action.get("source_post_id"),
    })


def _proposal_ref_reply(kind: str, pid: str, target_desc: str) -> str:
    if kind in ("move", "treat"):
        ttl = f"{MOVE_PROPOSAL_TTL_MIN} min"
    else:
        ttl = f"{RULE_PROPOSAL_TTL_HOURS} h"
    label = {"move": "Déplacement proposé", "treat": "Clôture proposée (déplacement + lu)",
             "rule": "Règle proposée (mode propose)"}[kind]
    icon = ":white_check_mark:" if kind == "treat" else (
        ":open_file_folder:" if kind == "move" else ":page_facing_up:")
    return (f"{icon} **{label}** : {target_desc} (**#{pid}**)\n"
            f"Réponds `ok #{pid}` (valide {ttl}) ou `annule #{pid}`.")


def handle_command(cmd: dict, cfg: dict, state, config_dir_path, owner_user_id: str,
                   channel_id: str, post_id: str) -> str:
    """Réponse par verbe — J3 : propositions non exécutables, jamais d'effet
    externe (IMAP/rules.json). `ok` reste J4."""
    verb = cmd["verb"]
    interactive = cfg.get("interactive", {})
    if verb == "aide":
        return _REPLY_AIDE
    if verb == "statut":
        return _statut_reply(state, interactive)
    if verb == "ref_syntax":
        return _ref_syntax_reply(cmd["ref"], interactive)  # aide pure, hors gate
    if not interactive.get("proposals_enabled", False):
        # gate 2/4 non activé : verbes de tri en accusé only (comportement J2)
        if verb in ("item_move", "rule_create", "treat", "treat_bare", "annule", "ok"):
            return ("Commande de tri reconnue :heavy_check_mark: "
                    "Les propositions interactives ne sont pas activées. "
                    "Réponds `aide` pour les commandes disponibles.")
        return _REPLY_UNKNOWN
    if verb == "ok":
        # J4 : consommation réelle (§11.4/§11.8). F-09 : une ref de digest
        # (#n1/#a1/#l1) n'est PAS une proposition — réponse dédiée.
        pid = cmd.get("proposal_ref", "")
        if not pid.startswith("p"):
            return (f":information_source: `#{pid}` est une référence de digest (message), "
                    "pas une proposition. Les propositions à confirmer sont les `#p…` — "
                    "crées-en une avec `#ref → alias`.")
        return _handle_ok(cmd, cfg, state, config_dir_path, owner_user_id,
                          channel_id, post_id)
    if verb == "item_move":
        return _handle_item_move(cmd, cfg, state, config_dir_path, owner_user_id,
                                 channel_id, post_id)
    if verb == "treat":
        return _handle_treat(cmd, cfg, state, config_dir_path, owner_user_id,
                             channel_id, post_id)
    if verb == "treat_bare":
        return (":bulb: La clôture exige la destination de stockage explicite : "
                f"`traite #{cmd['ref']} → alias` (le message est déplacé vers le "
                "stockage final et marqué lu — jamais de destination implicite).")
    if verb == "rule_create":
        return _handle_rule_create(cmd, cfg, state, config_dir_path, owner_user_id,
                                   channel_id, post_id)
    if verb == "annule":
        return _handle_annule(cmd, state, owner_user_id, channel_id)
    return _REPLY_UNKNOWN


def _ref_syntax_reply(ref: str | None, interactive: dict) -> str:
    aliases = ", ".join(sorted((interactive.get("aliases", {}) or {}).keys())) or "(aucun)"
    example_ref = f"#{ref}" if ref else "#n1"
    first_alias = aliases.split(", ")[0] if aliases != "(aucun)" else "alias"
    return (f":bulb: Format attendu : `{example_ref} → {first_alias}` (flèche `→`) — "
            "un post = une commande (≤ 256 caractères), envoie tes instructions une par une.\n"
            f"Aliases disponibles : {aliases}\n"
            "Exemples : `#n1 → gitlab` · `expediteur x@y.z → acronis` · `domaine acronis.com → acronis`")


def _statut_reply(state, interactive: dict) -> str:
    lines = ["**Mail Triage — statut**",
             "- Moteur actif : scan / plan / apply / digest / reconcile / listen",
             "- Digest enrichi V4 publié chaque matin (launchd 07:30)",
             f"- Canal interactif : lecture active, propositions "
             f"{'activées' if interactive.get('proposals_enabled', False) else 'désactivées'}"]
    aliases = sorted((interactive.get("aliases", {}) or {}).keys())
    if aliases:
        lines.append(f"- Aliases : {', '.join(aliases)}")
    return "\n".join(lines)


def _handle_item_move(cmd, cfg, state, config_dir_path, owner_user_id, channel_id,
                      post_id) -> str:
    ref = cmd["ref"]
    got = state.resolve_ref(ref, _now_iso())
    if got["status"] == "ambiguous":
        return ("❌ Référence ambiguë — réponse refusée par sécurité. "
                "Utilise la référence du dernier digest (les nouvelles refs sont uniques).")
    if got["status"] == "unknown":
        return f"❌ Référence `#{ref}` inconnue. Vérifie le dernier digest ou réponds `aide`."
    if got["status"] == "expired":
        return (f"❌ Référence `#{ref}` périmée (validité 48 h). "
                "Le message apparaîtra dans un prochain digest s'il reste sans règle.")
    target = got["ref"]
    canonical, reason = resolve_destination(cmd["dest_text"], cfg)
    if canonical is None:
        if reason == "forbidden":
            return ("❌ Destination interdite (Corbeille/Spam/brouillons interdits) — "
                    "aucune proposition possible. Réponds `statut` pour les aliases.")
        return (_ref_syntax_reply(ref, cfg.get("interactive", {}))
                + "\n:information_source: La création de dossier ne se fait pas via le MP.")
    action = {"type": "move", "mailbox": target["mailbox"],
              "uidvalidity": target["uidvalidity"], "uid": target["uid"],
              "folder": canonical, "from_addr": target["from_addr"],
              "source_post_id": post_id}
    pid, reason = _allocate_pid(state, "move", cfg)
    if pid is None:
        return _limit_reply(reason)
    _save_proposal(state, pid, "move", owner_user_id, channel_id, action,
                   timedelta(minutes=MOVE_PROPOSAL_TTL_MIN), config_dir_path)
    return _proposal_ref_reply("move", pid,
                               f"`#{ref}` → `{canonical}` (de {_md_safe(target['from_addr'])})")


def _handle_treat(cmd, cfg, state, config_dir_path, owner_user_id, channel_id,
                  post_id) -> str:
    """J4bis (§12.4) : clôture workflow — proposition `treat` = déplacement du
    message vers le stockage final EXPLICITE + `\\Seen` (réconcilié par Message-ID
    avant STORE, §12.3). Budget des déplacements ponctuels (TTL 30 min)."""
    ref = cmd["ref"]
    got = state.resolve_ref(ref, _now_iso())
    if got["status"] == "ambiguous":
        return ("❌ Référence ambiguë — réponse refusée par sécurité. "
                "Utilise la référence du dernier digest (les nouvelles refs sont uniques).")
    if got["status"] == "unknown":
        return f"❌ Référence `#{ref}` inconnue. Vérifie le dernier digest ou réponds `aide`."
    if got["status"] == "expired":
        return (f"❌ Référence `#{ref}` périmée (validité 48 h). "
                "Le message apparaîtra dans un prochain digest s'il reste sans règle.")
    target = got["ref"]
    canonical, reason = resolve_destination(cmd["dest_text"], cfg)
    if canonical is None:
        if reason == "forbidden":
            return ("❌ Destination interdite (Corbeille/Spam/brouillons interdits) — "
                    "aucune clôture possible. Réponds `statut` pour les aliases.")
        return (_ref_syntax_reply(ref, cfg.get("interactive", {}))
                + "\n:information_source: La clôture exige une destination de stockage explicite.")
    if target["mailbox"] == canonical:
        return (":information_source: Le message est déjà dans `{}` — clôture sans effet "
                "(statut ≠ classement : utiliser `traite #… → stockage` depuis le dossier "
                "workflow).".format(canonical))
    action = {"type": "treat", "mailbox": target["mailbox"],
              "uidvalidity": target["uidvalidity"], "uid": target["uid"],
              "folder": canonical, "from_addr": target["from_addr"],
              "source_post_id": post_id}
    pid, reason = _allocate_pid(state, "move", cfg)
    if pid is None:
        return _limit_reply(reason)
    _save_proposal(state, pid, "treat", owner_user_id, channel_id, action,
                   timedelta(minutes=MOVE_PROPOSAL_TTL_MIN), config_dir_path)
    # D6 : l'item passe 'pending' (une clôture est engagée — jamais re-proposé
    # comme 'new' tant qu'il attend). No-op si l'item n'est pas suivi.
    state.set_workflow_item_state(target["mailbox"], target["uidvalidity"],
                                  target["uid"], "pending", _now_iso())
    return _proposal_ref_reply("treat", pid,
                               f"`#{ref}` traité → `{canonical}` + lu "
                               f"(de {_md_safe(target['from_addr'])})")


def _handle_rule_create(cmd, cfg, state, config_dir_path, owner_user_id, channel_id,
                        post_id) -> str:
    scope, value = cmd["scope"], cmd["value"].strip().lower()
    if scope == "expediteur":
        if not _RE_EMAIL.match(value) or len(value) > 254:
            return "❌ Adresse invalide. Format : `expediteur nom@domaine.tld → {alias}`."
        # F-03 (J4, décision figée §11.6) : match ADRESSE EXACTE dédié
        # (`from_exact`) — jamais la sous-chaîne de `from_any` (une règle
        # « bob@x.com » ne doit pas attraper « bob@x.com.evil.tld »).
        match = {"from_exact": [value]}
        display = f"expediteur `{value}` (adresse exacte)"
    else:
        if not _RE_DOMAIN.match(value) or len(value) > 253:
            return "❌ Domaine invalide. Format : `domaine exemple.tld → {alias}`."
        match = {"from_domain_any": [value]}
        display = f"domaine `{value}`"
    canonical, reason = resolve_destination(cmd["dest_text"], cfg)
    if canonical is None:
        if reason == "forbidden":
            return "❌ Destination interdite — aucune proposition possible."
        return (_ref_syntax_reply(None, cfg.get("interactive", {}))
                + "\n:information_source: La création de dossier ne se fait pas via le MP.")
    rule = {"id": "interactive-pending", "priority": RULE_PRIORITY_SENDER if scope == "expediteur"
            else RULE_PRIORITY_DOMAIN, "mode": "propose", "match": match, "folder": canonical}
    pid, reason = _allocate_pid(state, "rule", cfg)
    if pid is None:
        return _limit_reply(reason)
    rule["id"] = f"interactive-{pid}"
    action = {"type": "rule", "rule": rule, "display": display, "source_post_id": post_id}
    _save_proposal(state, pid, "rule", owner_user_id, channel_id, action,
                   timedelta(hours=RULE_PROPOSAL_TTL_HOURS), config_dir_path)
    return _proposal_ref_reply("rule", pid, f"{display} → `{canonical}`")


def _limit_reply(reason: str) -> str:
    if reason == "too_many_pending":
        return ("⏳ Trop de propositions en attente (max 10). "
                "Confirme ou annule (`annule #…`) avant d'en créer une nouvelle.")
    if reason == "rule_daily_limit":
        return "⏳ Limite quotidienne de nouvelles règles atteinte (max 5/jour)."
    return "⏳ Trop de commandes en peu de temps (max 30/5 min). Réessaie dans quelques minutes."


def _md_safe(text: str) -> str:
    """Neutralisation markdown d'une donnée email échoïe (F-08 review J3) :
    un From non fiable ne doit jamais rendre un lien/gras/backtick cliquable
    dans le DM — même frontière que _sanitize_preview du digest."""
    return (text.replace("[", "(").replace("]", ")").replace("`", "'")
                .replace("mail-triage-digest:", "[marqueur-neutralisé:"))


def _handle_annule(cmd, state, owner_user_id: str, channel_id: str) -> str:
    pid = cmd.get("proposal_ref", "")
    proposal = state.get_proposal(pid)
    # Cross-check owner+canal (F-07 review J3) : refus identique à « inconnue »
    # (ne rien divulguer) si la proposition n'appartient pas à ce propriétaire/DM.
    if (not proposal or proposal["status"] != "pending"
            or proposal["owner_user_id"] != owner_user_id
            or proposal["channel_id"] != channel_id):
        return f"❌ Proposition `#{pid}` inconnue ou déjà traitée."
    state.set_proposal_status(pid, "cancelled")
    return f"✅ Proposition `#{pid}` annulée."


# --- J4 : consommation des propositions (§11.4 / §11.8) --------------------------


def _gate_refused(kind: str, cfg: dict) -> bool:
    """Gates §11.2 : déplacement IMAP (move OU clôture treat) → writes.imap_enabled ;
    écriture de règles → writes.interactive_rules (4e gate) ; les deux exigent
    writes.enabled. \\Seen n'est PAS couvert par interactive_rules (même gate IMAP)."""
    writes = cfg.get("writes", {}) or {}
    if not writes.get("enabled", False):
        return True
    gate_key = "imap_enabled" if kind in ("move", "treat") else "interactive_rules"
    return not writes.get(gate_key, False)


def _handle_ok(cmd, cfg: dict, state, config_dir_path, owner_user_id: str,
               channel_id: str, post_id: str) -> str:
    """J4 : consommation d'une proposition. Séquence §11.8 P0-J4 :
    cross-check (owner+DM+pending) → réservation ATOMIQUE (pending→executing)
    → revalidation (SHA-256 global rules.json, allowlist) → exécution du contenu
    FIGÉ dans proposals.action → applied/uncertain/rejected. Usage unique :
    une fois réservée, la proposition ne repasse JAMAIS par pending."""
    pid = cmd.get("proposal_ref", "")
    now_iso = _now_iso()
    proposal = state.get_proposal(pid)
    if proposal and proposal["owner_user_id"] == owner_user_id \
            and proposal["channel_id"] == channel_id:
        if proposal["status"] == "executing":
            return f"⏳ Proposition `#{pid}` déjà en cours de traitement."
        if proposal["status"] == "applied":
            return f"✅ Proposition `#{pid}` déjà traitée (usage unique)."
    if (not proposal or proposal["status"] != "pending"
            or proposal["owner_user_id"] != owner_user_id
            or proposal["channel_id"] != channel_id):
        return f"❌ Proposition `#{pid}` inconnue, expirée ou déjà traitée."
    kind = proposal["kind"]
    if _gate_refused(kind, cfg):
        # Kill switch (test de sortie #9) : AUCUN write, la proposition reste
        # pending — re-confirmation possible après réactivation.
        return _REPLY_OK_PENDING.format(pid=pid)
    # Réservation atomique AVANT toute exécution (usage unique, deux
    # confirmations concurrentes → une seule transition executing, test #4).
    if not state.reserve_proposal(pid, now_iso, post_id):
        # Review F-08 : distinguer « expirée » (re-confirmation impossible, le
        # propriétaire doit refaire) de « déjà en cours » (traitement en vol).
        fresh = state.get_proposal(pid)
        if fresh and fresh.get("expires_at") and fresh["expires_at"] <= now_iso:
            return (f"❌ Proposition `#{pid}` expirée (TTL dépassé) — "
                    "refais une proposition.")
        return f"⏳ Proposition `#{pid}` déjà en cours de traitement."
    try:
        if kind in ("move", "treat"):
            return _execute_move_proposal(cfg, state, config_dir_path, proposal, now_iso)
        if kind == "rule":
            return _execute_rule_proposal(cfg, state, config_dir_path, proposal, now_iso)
    except Exception:  # fail-closed : l'exécution interrompue reste 'executing'
        # → sweep timeout_stale_executing → uncertain → réconciliation opérateur.
        return (f"⚠️ Proposition `#{pid}` interrompue en cours d'exécution — "
                "état réconciliable, jamais répété aveuglément.")
    state.set_proposal_status(pid, "rejected")
    return f"❌ Proposition `#{pid}` de type inconnu — clôturée sans effet."


def _execute_move_proposal(cfg: dict, state, config_dir_path, proposal: dict,
                           now_iso: str) -> str:
    """Exécution du déplacement FIGÉ dans proposals.action (§11.8 P0-J4) :
    le plan est construit depuis l'action figée (jamais re-résolu depuis les
    digest_refs), le SHA-256 global de rules.json doit être IDENTIQUE à la
    création, la destination doit rester dans l'allowlist."""
    pid = proposal["proposal_id"]
    action = json.loads(proposal["action"])
    if rules_sha256(config_dir_path) != proposal["target_version"]:
        state.set_proposal_status(pid, "rejected")
        return ("❌ Confirmation refusée : les règles ont changé depuis la proposition "
                "(aucun write). Refais une proposition.")
    if not policy.destination_is_allowed(action["folder"],
                                         cfg["destinations"]["allowlist"]):
        state.set_proposal_status(pid, "rejected")
        return ("❌ Confirmation refusée : destination non autorisée (config changée) — "
                "aucun write.")
    # Plan FIGÉ depuis l'action (test de sortie #1 : même si les digest_refs ont
    # changé, c'est bien l'UID figé à la création qui est déplacé). J4bis : le
    # plan porte treat=True pour la clôture (move + \\Seen réconcilié, §12.3).
    now = datetime.now(timezone.utc)
    payload = {
        "mailbox": action["mailbox"],
        "uidvalidity": action["uidvalidity"],
        "treat": action.get("type") == "treat",
        "moves": [{
            "uid": action["uid"],
            "from_folder": action["mailbox"],
            "to_folder": action["folder"],
            "rule_id": f"interactive-{pid}",
            "from_hash": policy.pseudonymize(action.get("from_addr") or "", 10),
            "message_id": action.get("message_id") or "",
        }],
        "created_at": now.isoformat(timespec="seconds"),
    }
    expires = (now + timedelta(hours=int(cfg.get("plan", {}).get("expire_hours", 24)))
               ).isoformat(timespec="seconds")
    plan_id = f"interactive-{pid}"
    state.create_plan(plan_id, now.isoformat(timespec="seconds"), expires, payload)
    # import différé (triage importe interact au chargement)
    import triage as triage_mod
    result = triage_mod.run_plan_apply(cfg, state, config_dir_path, plan_id)
    status = result["status"]
    if status == "applied":
        state.set_proposal_status(pid, "applied")
        if payload["treat"]:
            return (f"✅ Traitement effectué : `{action['folder']}` + marqué lu "
                    f"(réf `#{pid}`).")
        return f"✅ Déplacement effectué : `{action['folder']}` (réf `#{pid}`)."
    if status == "uncertain":
        state.set_proposal_status(pid, "uncertain")
        if payload["treat"]:
            state.set_workflow_item_state(action["mailbox"], action["uidvalidity"],
                                          action["uid"], "uncertain", now_iso)
            return (f"⚠️ Clôture en état inconnu (réf `#{pid}`) — le message a pu être "
                    "déplacé ; le marquage lu ne sera jamais appliqué aveuglément. "
                    "L'opérateur réconciliera.")
        return (f"⚠️ Déplacement en état inconnu (réf `#{pid}`) — le message a pu être "
                "déplacé. L'opérateur réconciliera (aucune répétition aveugle).")
    if status == "partial":
        state.set_proposal_status(pid, "rejected")
        return ("❌ Déplacement impossible (destination indisponible) — "
                f"proposition `#{pid}` clôturée sans write.")
    if status == "reconcile_required":
        state.set_proposal_status(pid, "uncertain")
        return (f"⚠️ Déplacement en attente de réconciliation (réf `#{pid}`) — "
                "jamais de répétition aveugle.")
    # plan_expired / plan_integrity / uidvalidity_changed / plan_invalid_state
    state.set_proposal_status(pid, "rejected")
    return ("❌ Confirmation refusée : préconditions divergentes depuis la "
            f"proposition (aucun write). Réf `#{pid}`.")


def _execute_rule_proposal(cfg: dict, state, config_dir_path, proposal: dict,
                           now_iso: str) -> str:
    """Écriture de la règle FIGÉE via le service atomique unique (§11.7).
    Le SHA-256 global de rules.json doit être identique à la création."""
    pid = proposal["proposal_id"]
    action = json.loads(proposal["action"])
    rule = action["rule"]
    result = rules_writer.append_rule(
        config_dir_path, state, rule, f"op-{pid}",
        proposal["target_version"], now_iso)
    if result["status"] in ("applied", "already_applied"):
        state.set_proposal_status(pid, "applied")
        display = action.get("display") or rule["id"]
        return (f"✅ Règle créée : {_md_safe(display)} → `{rule['folder']}` "
                "(mode propose — les prochains messages seront à examiner).")
    state.set_proposal_status(pid, "rejected")
    if result["status"] == "sha_mismatch":
        return ("❌ Confirmation refusée : les règles ont changé depuis la proposition "
                "(aucun write). Refais une proposition.")
    return f"❌ Confirmation refusée : {result['detail']} Réf `#{pid}`."


def run_once(cfg: dict, state, config_dir_path, client: kchat.KChatClient,
             owner_user_id: str, audit_fn) -> dict:
    """Un tour du poller. J3 : aide/statut libres ; item_move/rule_create/annule
    créent des PROPOSITIONS (aucun effet IMAP/rules.json) si le gate 2 est
    activé ; J4 : `ok` consomme la proposition (réservation atomique + revalidations
    + exécution figée) selon les gates de mutation."""
    interactive = cfg.get("interactive", {})
    if not interactive.get("enabled", False):
        return {"status": "disabled"}
    bot_user_id = (client.me() or {}).get("id")
    if not bot_user_id:
        raise kchat.KChatError(0, "/users/me", "identité bot illisible")
    channel_id = client.ensure_direct_channel(bot_user_id, owner_user_id)

    ignored = 0
    processed = 0
    replies = []
    lock_path = config_dir_path / "locks" / "interactive.lock"
    with FileLock(lock_path):
        # F-01 (review J3) : balayage d'expiration — les propositions pending
        # périmées passent 'expired' et libèrent le budget « simultanées ».
        expired_swept = state.expire_stale_proposals(_now_iso())
        # J4 : sweep des 'executing' orphelins (crash entre réservation et
        # fin) → 'uncertain' réconciliable, jamais re-consommable (usage unique).
        stale_cutoff = (datetime.now(timezone.utc)
                        - timedelta(hours=EXECUTING_STALE_HOURS)).isoformat()
        executing_swept = state.timeout_stale_executing(stale_cutoff)
        posts = collect_new_posts(client, channel_id, owner_user_id, state)
        if not posts:
            if state.interactive_checkpoint() is None:
                # baseline : checkpoint = post le plus récent, sans traitement
                latest = client.recent_channel_posts(channel_id, per_page=1)
                if latest:
                    newest = max(latest, key=lambda p: ((p.get("create_at") or 0), p.get("id") or ""))
                    state.set_interactive_checkpoint(int(newest.get("create_at") or 0),
                                                     newest.get("id") or "", _now_iso())
            return {"status": "ok", "processed": 0, "ignored": 0,
                    "expired_swept": expired_swept, "executing_swept": executing_swept,
                    "baseline": True}
        limits = _limits(cfg)
        last_key = None
        for post in posts:
            post_id = post.get("id") or ""
            sender = post.get("user_id") or ""
            if sender != owner_user_id:
                ignored += 1  # ignore total (§11.7) : aucune réponse, aucun contenu
                last_key = (int(post.get("create_at") or 0), post_id)
                continue
            cmd = parse_command(post.get("message") or "")
            if not state.record_command(post_id, channel_id,
                                        int(post.get("create_at") or 0), sender, cmd["verb"]):
                continue  # déjà traité (idempotence) — jamais de double réponse
            if not _check_rate_limit(state, limits):
                reply = _limit_reply("rate")
                outcome = "rate_limited"
            else:
                reply = handle_command(cmd, cfg, state, config_dir_path, owner_user_id,
                                       channel_id, post_id)
                outcome = "processed"
            sent = client.post_message(channel_id, reply)
            state.set_command_result(post_id, outcome,
                                     sent.get("id") if isinstance(sent, dict) else None,
                                     _now_iso())
            audit_fn(config_dir_path, {
                "event": "interactive_command", "post_id": post_id, "verb": cmd["verb"],
                "status": outcome, "ref": cmd.get("ref") or cmd.get("proposal_ref"),
            })  # jamais le texte intégral du MP (§11.3)
            processed += 1
            replies.append(cmd["verb"])
            last_key = (int(post.get("create_at") or 0), post_id)
        if last_key:
            state.set_interactive_checkpoint(last_key[0], last_key[1], _now_iso())
    return {"status": "ok", "processed": processed, "ignored": ignored,
            "expired_swept": expired_swept, "executing_swept": executing_swept,
            "verbs": replies}
