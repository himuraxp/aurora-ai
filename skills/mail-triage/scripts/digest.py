"""Digest kChat du matin : fenêtre temporelle fiable, contenu pseudonymisé côté CLI,
marqueur unique, idempotence (garde SQLite + réconciliation sans repost aveugle).

Frontière : le digest contient expéditeurs/sujets lisibles (boîte pro → kChat pro,
même organisation) MAIS jamais de corps ni de pièce jointe ; sujets sensibles masqués.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import policy
from kchat import KChatError

MARKER_PREFIX = "mail-triage-digest:"


def new_digest_id() -> str:
    return uuid.uuid4().hex[:16]


def new_marker(digest_id: str) -> str:
    return f"[{MARKER_PREFIX}{digest_id}]"


def compute_window(state, config: dict, now: datetime) -> dict:
    """Fenêtre = depuis la fin du dernier digest confirmé, sinon now - lookback_hours.

    La fenêtre suivante commence au dernier point de coupure confirmé (jamais un
    filtre IMAP SINCE dont la granularité est journalière).
    """
    digest_cfg = config.get("digest", {})
    lookback = int(digest_cfg.get("lookback_hours", 18))
    last = state.last_confirmed_digest()
    if last and last.get("window_end"):
        try:
            start = datetime.fromisoformat(last["window_end"])
        except ValueError:
            start = None
        if start is not None:
            return {"start": start, "end": now, "previous_id": last["id"]}
    return {"start": now - timedelta(hours=lookback), "end": now, "previous_id": None}


def build_digest(state, messages: list[dict], config: dict, window: dict, digest_id: str,
                 mailbox: str = "INBOX", uidvalidity: int = 0) -> dict:
    """Construit le contenu du digest.

    messages: liste normalisée de imap_client.fetch_recent_headers (from/subject/uid/...).
    new = messages dans la fenêtre ET jamais digestés (identité technique = uid).
    always_inbox = non lus HORS fenêtre (plus anciens, encore présents), plafonnés.
    """
    digest_cfg = config.get("digest", {})
    sensitive_patterns = digest_cfg.get("sensitive_subject_patterns", [])
    cap = int(digest_cfg.get("always_inbox_cap", 10))
    already = state.digested_msg_keys(mailbox, uidvalidity)

    start = window["start"]
    end = window["end"]

    new_items: list[dict] = []
    always: list[dict] = []
    for msg in messages:
        subject, masked = policy.mask_subject(msg.get("subject") or "", sensitive_patterns)
        item = {
            "uid": msg["uid"],
            "from": msg.get("from") or "",
            "subject": subject,
            "subject_masked": masked,
            "internaldate": msg.get("internaldate"),
            "seen": msg.get("seen", False),
        }
        internal = msg.get("internaldate")
        in_window = False
        if internal:
            try:
                dt = datetime.fromisoformat(internal)
                in_window = start <= dt < end
            except ValueError:
                in_window = False
        if in_window and msg["uid"] not in already:
            new_items.append(item)
        elif not in_window and not msg.get("seen", False) and msg["uid"] not in already:
            if len(always) < cap:
                always.append(item)

    new_items.sort(key=lambda m: (m["internaldate"] or "", m["uid"]))
    return {
        "id": digest_id,
        "marker": new_marker(digest_id),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "timezone": config.get("digest", {}).get("timezone", "Europe/Paris"),
        "new": new_items,
        "always_inbox": always,
        "moved_counts": state.moved_counts_since(start.isoformat()),
    }


def _safe_local_hour(iso_ts: str | None, tz_name: str) -> str:
    """Heure locale (config digest.timezone, défaut Europe/Paris) ; fallback UTC."""
    if not iso_ts:
        return "??:??"
    try:
        dt = datetime.fromisoformat(iso_ts)
        try:
            from zoneinfo import ZoneInfo
            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass
        return dt.strftime("%H:%M")
    except ValueError:
        return "??:??"


def render_markdown(digest: dict) -> str:
    """Rendu kChat (Mattermost markdown). Marqueur unique inclus (réconciliation).

    Les sujets viennent d'emails (données non fiables) : toute occurrence du
    préfixe de marqueur y est neutralisée (anti-falsification de reconcile)."""
    lines: list[str] = []
    window_start = digest["window_start"][:16].replace("T", " ")
    window_end = digest["window_end"][:16].replace("T", " ")
    lines.append(f"**:incoming_envelope: Digest emails — {window_start} → {window_end}**")
    lines.append("")

    new_items = digest.get("new", [])
    if new_items:
        lines.append(f"**Nouveaux ({len(new_items)})**")
        for item in new_items:
            time_part = _safe_local_hour(item.get("internaldate"),
                                         digest.get("timezone", "Europe/Paris"))
            subject = item["subject"].replace(MARKER_PREFIX, "[marqueur-neutralisé:")
            if item.get("subject_masked"):
                subject = f"{subject} :lock:"
            lines.append(f"- `{time_part}` **{item['from']}** — {subject}")
        lines.append("")
    else:
        lines.append("**Nouveaux** : aucun.")
        lines.append("")

    always = digest.get("always_inbox", [])
    if always:
        lines.append(f"**Toujours dans l'Inbox (non lus, plus anciens) ({len(always)})**")
        for item in always:
            subject = item["subject"].replace(MARKER_PREFIX, "[marqueur-neutralisé:")
            if item.get("subject_masked"):
                subject = f"{subject} :lock:"
            lines.append(f"- **{item['from']}** — {subject}")
        lines.append("")

    moved = digest.get("moved_counts") or {}
    if moved:
        total = sum(moved.values())
        detail = ", ".join(f"{folder}: {count}" for folder, count in sorted(moved.items()))
        lines.append(f"**:file_folder: Tri automatique** : {total} message(s) déplacé(s) ({detail})")
        lines.append("")

    lines.append(digest["marker"])
    return "\n".join(lines)


def publish(kchat_client, bot_user_id: str, recipient_user_id: str, markdown: str) -> dict:
    """Publie le digest en DM. Aucun retry : un timeout remonte en exception
    (le CLI marque 'uncertain' et reconcile tranche)."""
    channel_id = kchat_client.ensure_direct_channel(bot_user_id, recipient_user_id)
    post = kchat_client.post_message(channel_id, markdown)
    post_id = post.get("id") if isinstance(post, dict) else None
    if not post_id:
        raise KChatError(0, "/posts", "réponse sans id")
    return {"channel_id": channel_id, "post_id": post_id}
