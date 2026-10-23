"""Canal interactif MP kChat → moteur (J2 : lecture seule + aide/statut).

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
- Aucune mutation au niveau J2 : les verbes de tri sont reconnus mais répondent
  que les mutations interactives ne sont pas encore activées (J3/J4).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import kchat
from state import FileLock

MAX_COMMAND_LENGTH = 256     # limite d'une commande (§11.6)
MAX_PAGES = 20               # garde-fou pagination (20 × 30 = 600 posts max)
PAGE_SIZE = 30


class InteractiveError(Exception):
    """Échec du canal interactif (pagination incomplète, réponse kChat…)."""


_RE_AIDE = re.compile(r"^\s*(aide|help)\s*$", re.IGNORECASE)
_RE_STATUT = re.compile(r"^\s*statut\s*$", re.IGNORECASE)
_RE_ITEM_MOVE = re.compile(r"^\s*#([a-z]\d+)\s*(?:→|->)\s*(\S.{0,120}?)\s*$", re.IGNORECASE)
_RE_RULE = re.compile(r"^\s*(expediteur|expéditeur|domaine)\s+(\S+)\s*(?:→|->)\s*(\S.{0,120}?)\s*$",
                      re.IGNORECASE)
_RE_OK = re.compile(r"^\s*ok\s+#([a-z0-9]+)\s*$", re.IGNORECASE)
_RE_ANNULE = re.compile(r"^\s*(?:annule|annuler)\s+#([a-z0-9]+)\s*$", re.IGNORECASE)

_REPLY_AIDE = (
    "**Mail Triage — commandes**\n"
    "- `aide` — cette liste\n"
    "- `statut` — état du moteur\n"
    "_Bientôt (en cours d'activation) : `#ref → dossier`, `expediteur X → dossier`, `ok #p1`._"
)
_REPLY_MUTATION_PENDING = (
    "Commande de tri reconnue :heavy_check_mark: "
    "Les mutations interactives ne sont pas encore activées (contrat §11 figé, "
    "activation à venir). Réponds ici avec `aide` pour les commandes disponibles."
)
_REPLY_UNKNOWN = "Commande non reconnue. Réponds `aide` pour la liste des commandes."


def parse_command(text: str) -> dict:
    """Grammaire niveau 1 : verbes reconnus sinon `inconnu`. Le texte du MP est
    une donnée non fiable — aucune exécution libre, jamais (§11.6)."""
    if not text or len(text) > MAX_COMMAND_LENGTH:
        return {"verb": "inconnu"}
    if _RE_AIDE.match(text):
        return {"verb": "aide"}
    if _RE_STATUT.match(text):
        return {"verb": "statut"}
    m = _RE_ITEM_MOVE.match(text)
    if m:
        return {"verb": "item_move", "ref": m.group(1).lower(), "dest_text": m.group(2).strip()}
    m = _RE_RULE.match(text)
    if m:
        return {"verb": "rule_create", "scope": m.group(1).lower().replace("é", "e"),
                "value": m.group(2), "dest_text": m.group(3).strip()}
    m = _RE_OK.match(text)
    if m:
        return {"verb": "ok", "proposal_ref": m.group(1).lower()}
    if _RE_ANNULE.match(text):
        return {"verb": "annule"}
    return {"verb": "inconnu"}


def collect_new_posts(client: kchat.KChatClient, channel_id: str, owner_user_id: str,
                      state) -> list[dict]:
    """Collecte paginée EXHAUSTIVE jusqu'au checkpoint (§11.3) : remonte par
    `before` jusqu'à couvrir le checkpoint ou l'origine du canal. Tri
    (create_at, post_id). Post du bot, édité, supprimé ou d'un autre expéditeur
    → ignoré. Checkpoint gelé si la pagination est incomplète (jamais d'avance
    sur un trou)."""
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
    # NOTE : le filtre PROPRIÉTAIRE n'est PAS ici — il vit dans run_once (point de
    # décision unique, §11.7 : ignore total + compteur). La collecte retourne la
    # fenêtre ordonnée du canal (éditions/suppressions exclues).
    candidates = [
        p for p in seen.values()
        if not p.get("edit_at") and not p.get("delete_at")
        and ((p.get("create_at") or 0), p.get("id") or "") > last_key
    ]
    candidates.sort(key=lambda p: ((p.get("create_at") or 0), p.get("id") or ""))
    return candidates


def _reply_for(cmd: dict, state, config_dir_path) -> str:
    """Réponse par verbe — read-only strict au niveau J2 (aucune mutation)."""
    verb = cmd["verb"]
    if verb == "aide":
        return _REPLY_AIDE
    if verb == "statut":
        return ("**Mail Triage — statut**\n"
                "- Moteur actif : scan / plan / apply / digest / reconcile\n"
                "- Digest enrichi V4.1 publié chaque matin (launchd 07:30)\n"
                "- Canal interactif : lecture active, mutations à venir")
    if verb in ("item_move", "rule_create", "ok", "annule"):
        return _REPLY_MUTATION_PENDING
    return _REPLY_UNKNOWN


def run_once(cfg: dict, state, config_dir_path, client: kchat.KChatClient,
             owner_user_id: str, audit_fn) -> dict:
    """Un tour du poller. Read-only strict au niveau J2 : aide/statut + accusé
    des verbes de tri (sans exécution). Aucun write IMAP, aucune règle."""
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
        posts = collect_new_posts(client, channel_id, owner_user_id, state)
        if not posts:
            if state.interactive_checkpoint() is None:
                # baseline : checkpoint = post le plus récent, sans traitement
                latest = client.recent_channel_posts(channel_id, per_page=1)
                if latest:
                    newest = max(latest, key=lambda p: ((p.get("create_at") or 0), p.get("id") or ""))
                    state.set_interactive_checkpoint(int(newest.get("create_at") or 0),
                                                     newest.get("id") or "",
                                                     _now_iso())
            return {"status": "ok", "processed": 0, "ignored": 0, "baseline": True}
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
            reply = _reply_for(cmd, state, config_dir_path)
            sent = client.post_message(channel_id, reply)
            state.set_command_result(post_id, "processed",
                                     sent.get("id") if isinstance(sent, dict) else None,
                                     _now_iso())
            audit_fn(config_dir_path, {
                "event": "interactive_command", "post_id": post_id, "verb": cmd["verb"],
                "status": "processed",
            })  # jamais le texte intégral du MP (§11.3)
            processed += 1
            replies.append(cmd["verb"])
            last_key = (int(post.get("create_at") or 0), post_id)
        if last_key:
            state.set_interactive_checkpoint(last_key[0], last_key[1], _now_iso())
    return {"status": "ok", "processed": processed, "ignored": ignored, "verbs": replies}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
