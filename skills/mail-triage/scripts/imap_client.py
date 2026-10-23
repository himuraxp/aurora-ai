"""Wrapper IMAP minimal (imaplib stdlib) : TLS, capabilities, fetch en-têtes, UID MOVE.

Invariants portés ici : UID MOVE obligatoire pour toute mutation (RFC 6851) —
la capability MOVE est vérifiée AVANT toute opération ; son absence lève
ImmcapableError (fail-closed, jamais de fallback COPY/EXPUNGE).
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
from datetime import datetime, timezone


class ImapError(Exception):
    """Erreur IMAP (connexion, commande, parse)."""


class ImcpableError(ImapError):
    """Capability MOVE absente — writes désactivés (invariant 5)."""


def connect(host: str, port: int, login: str, password: str, timeout: int = 30) -> imaplib.IMAP4_SSL:
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=timeout)
        conn.login(login, password)
        conn.select("INBOX", readonly=True)
        return conn
    except imaplib.IMAP4.error as exc:
        raise ImapError(f"authentification IMAP échouée: {type(exc).__name__}") from exc
    except OSError as exc:
        raise ImapError(f"connexion IMAP échouée: {type(exc).__name__}") from exc


def has_move_capability(conn: imaplib.IMAP4_SSL) -> bool:
    """Capability MOVE vérifiée via CAPABILITY explicite — la liste du greeting
    (pré-auth) omet souvent MOVE sur les serveurs Infomaniak."""
    try:
        typ, data = conn.capability()
        caps = data[0].decode().split() if typ == "OK" and data and data[0] else []
    except Exception:
        caps = []
    if not caps:
        caps = [str(c) for c in (conn.capabilities or ())]
    return any(c.upper().startswith("MOVE") for c in caps)


def ensure_move_capability(conn: imaplib.IMAP4_SSL) -> None:
    if not has_move_capability(conn):
        raise ImcpableError("capability MOVE absente — writes IMAP désactivés (fallback = décision séparée)")


def _decode_header_value(raw) -> str:
    if raw is None:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for value, charset in parts:
        if isinstance(value, bytes):
            try:
                decoded.append(value.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                decoded.append(value.decode("utf-8", errors="replace"))
        else:
            decoded.append(value)
    # Les en-têtes repliés ne doivent pas injecter de sauts de ligne : on collapse.
    collapsed = re.sub(r"\s+", " ", "".join(decoded))
    return collapsed.strip()


def parse_list_line(line: bytes) -> tuple[str, str] | None:
    """Parse une ligne LIST: b'(\\HasNoChildren) "/" "INBOX/Auto/News"' → (delim, name)."""
    try:
        text = line.decode("utf-8", errors="replace")
    except Exception:
        return None
    text = text.rstrip("\r\n")
    if not text:
        return None
    # dernier segment quoté = nom de boîte
    import re
    m = re.match(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"[^"]*"|NIL)\s+(?P<name>.+)$', text)
    if not m:
        return None
    name = m.group("name").strip()
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    delim = m.group("delim")
    if delim == "NIL":
        return None, name
    return delim.strip('"'), name


def list_mailboxes(conn: imaplib.IMAP4_SSL) -> list[dict]:
    typ, data = conn.list()
    if typ != "OK":
        raise ImapError("LIST échoué")
    boxes = []
    for item in data:
        if isinstance(item, bytes):
            parsed = parse_list_line(item)
            if parsed is not None:
                delim, name = parsed
                boxes.append({"name": name, "delimiter": delim})
    return boxes


def quote_mailbox(name: str) -> str:
    """Quote un nom de dossier IMAP (les espaces cassent SELECT/LIST/MOVE sinon)."""
    escaped = (name or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def select_mailbox(conn: imaplib.IMAP4_SSL, name: str, *, readonly: bool = True):
    """SELECT avec nom quoté (dossiers avec espaces : 'JIRA - Trello - Redmine')."""
    return conn.select(quote_mailbox(name), readonly=readonly)


def mailbox_exists(conn: imaplib.IMAP4_SSL, name: str) -> bool:
    """Vérifie l'existence d'un dossier via LIST (jamais de création par le moteur).

    Comparaison EXACTE du nom (pas de sous-chaîne : INBOX/Auto ≠ INBOX/Auto2)."""
    typ, data = conn.list(quote_mailbox(name))
    if typ != "OK":
        return False
    for item in data or []:
        if isinstance(item, bytes):
            parsed = parse_list_line(item)
            if parsed is not None and parsed[1] == name:
                return True
    return False


def _parse_internaldate(raw) -> datetime | None:
    if not raw:
        return None
    text = raw.decode() if isinstance(raw, bytes) else str(raw)
    try:
        # format imaplib : "23-Oct-2026 08:15:00 +0200"
        dt = datetime.strptime(text.strip(), "%d-%b-%Y %H:%M:%S %z")
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def fetch_recent_headers(conn: imaplib.IMAP4_SSL, mailbox: str, limit: int = 100,
                         min_uid: int | None = None) -> list[dict]:
    """Récupère les en-têtes (jamais de corps) des messages les plus récents.

    min_uid: borne basse d'UID optionnelle (fenêtre de scan) ; sinon derniers `limit`.
    Trié par UID croissant. Marquage lu : impossible (readonly).
    """
    conn.select(mailbox, readonly=True)
    typ, data = conn.uid("search", None, "ALL")
    if typ != "OK":
        raise ImapError("UID SEARCH échoué")
    all_uids = [int(u) for u in data[0].split()] if data and data[0] else []
    if not all_uids:
        return []
    if min_uid is not None:
        uids = [u for u in all_uids if u >= min_uid][-limit:]
    else:
        uids = all_uids[-limit:]

    messages: list[dict] = []
    idset = ",".join(str(u) for u in uids)
    typ, fetched = conn.uid(
        "fetch", idset,
        "(FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID REFERENCES IN-REPLY-TO)])",
    )
    if typ != "OK":
        raise ImapError("UID FETCH échoué")

    current_uid: int | None = None
    flags = ""
    internaldate: datetime | None = None
    header_bytes = b""
    for item in fetched:
        if isinstance(item, tuple):
            meta, payload = item
            meta_text = meta.decode("utf-8", errors="replace")
            import re
            m = re.search(r"UID\s+(\d+)", meta_text)
            current_uid = int(m.group(1)) if m else None
            f = re.search(r"FLAGS\s+\(([^)]*)\)", meta_text)
            flags = f.group(1) if f else ""
            d = re.search(r'INTERNALDATE\s+"([^"]+)"', meta_text)
            internaldate = _parse_internaldate(d.group(1).encode()) if d else None
            header_bytes = payload or b""
        elif isinstance(item, bytes) and item.strip() == b")":
            if current_uid is None:
                continue
            msg = email.message_from_bytes(header_bytes)
            sender = email.utils.parseaddr(_decode_header_value(msg.get("From")))[1]
            to = email.utils.parseaddr(_decode_header_value(msg.get("To")))[1]
            messages.append({
                "uid": current_uid,
                "from": sender,
                "to": to,
                "subject": _decode_header_value(msg.get("Subject")),
                "date": _decode_header_value(msg.get("Date")),
                "message_id": _decode_header_value(msg.get("Message-ID")),
                "references": _decode_header_value(msg.get("References")),
                "in_reply_to": _decode_header_value(msg.get("In-Reply-To")),
                "internaldate": internaldate.isoformat() if internaldate else None,
                "seen": "\\Seen" in flags,
                "flags": flags,
            })
            current_uid, flags, internaldate, header_bytes = None, "", None, b""

    messages.sort(key=lambda m: m["uid"])
    return messages


def uid_move(conn: imaplib.IMAP4_SSL, uid: int, destination: str, source: str = "INBOX") -> None:
    """UID MOVE (atomicité serveur). Capability MOVE vérifiée au préalable — fail-closed.

    source : la boîte du plan (payload["mailbox"]) — JAMAIS un INBOX hardcodé,
    sinon les UIDs seraient interprétés dans le mauvais contexte (déplacement
    silencieux de messages arbitraires)."""
    ensure_move_capability(conn)
    conn.select(quote_mailbox(source), readonly=False)
    if "MOVE" not in imaplib.Commands:
        imaplib.Commands["MOVE"] = ("SELECTED",)
    typ, _ = conn.uid("MOVE", str(uid), quote_mailbox(destination))
    if typ != "OK":
        raise ImapError(f"UID MOVE {uid} → destination échoué")
    conn.select(quote_mailbox(source), readonly=True)


def logout(conn: imaplib.IMAP4_SSL) -> None:
    try:
        conn.logout()
    except Exception:
        pass
