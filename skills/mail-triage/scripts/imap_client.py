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


# --- V4.1 : lecture bornée du début du corps (invariant révisé, ARCHITECTURE §10) ---
# Lectures uniquement via BODY.PEEK (jamais \Seen), section text/plain ciblée via
# BODYSTRUCTURE, fenêtre <0.max_bytes>. Fail-closed : toute structure illisible
# → None (aperçu indisponible). Les pièces jointes ne sont JAMAIS lues.

def _tokenize_bodystructure(text: str) -> list:
    """Tokenise une S-expression BODYSTRUCTURE : '(', ')', ('str', v), ('atom', v),
    ('num', n), ('nil', None)."""
    tokens: list = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            tokens.append((c, c))
            i += 1
        elif c == '"':
            j = i + 1
            buf: list[str] = []
            while j < n:
                ch = text[j]
                if ch == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                elif ch == '"':
                    j += 1
                    break
                else:
                    buf.append(ch)
                    j += 1
            tokens.append(("str", "".join(buf)))
            i = j
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            word = text[i:j]
            if word.upper() == "NIL":
                tokens.append(("nil", None))
            elif word.isdigit():
                tokens.append(("num", int(word)))
            else:
                tokens.append(("atom", word))
            i = j
    return tokens


def _skip_balanced(tokens: list, i: int) -> int:
    """Index après le ')' fermant le groupe ouvert à tokens[i] == '('."""
    depth = 0
    while i < len(tokens):
        kind = tokens[i][0]
        if kind == "(":
            depth += 1
        elif kind == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def _capture_balanced_text(tokens: list, i: int) -> tuple[str, int]:
    """Texte approximatif d'un groupe équilibré (détection 'attachment')."""
    depth = 0
    parts: list[str] = []
    while i < len(tokens):
        kind, val = tokens[i]
        if kind == "(":
            depth += 1
            parts.append("(")
        elif kind == ")":
            depth -= 1
            parts.append(")")
            if depth == 0:
                return " ".join(parts), i + 1
        elif val is not None:
            parts.append(str(val))
        i += 1
    return " ".join(parts), i


def _parse_bodystructure(tokens: list, i: int, path: list) -> tuple[dict, int]:
    """Parse un corps (feuille ou multipart) depuis tokens[i] == '('.

    Feuille : ("TYPE" "SUB" params id desc enc size [lines] md5 disp lang loc).
    Multipart : ( enfant+ "SUBTYPE" params disp lang loc ).
    message/rfc822 → ValueError (hors périmètre preview, fail-closed)."""
    if i >= len(tokens) or tokens[i][0] != "(":
        raise ValueError("structure invalide")
    i += 1
    if i < len(tokens) and tokens[i][0] == "(":
        # multipart : enfants consécutifs puis sous-type puis extensions
        parts: list[dict] = []
        while i < len(tokens) and tokens[i][0] == "(":
            child, i = _parse_bodystructure(tokens, i, path + [len(parts) + 1])
            parts.append(child)
        if i >= len(tokens) or tokens[i][0] != "str":
            raise ValueError("multipart sans sous-type")
        node = {"type": "multipart", "subtype": (tokens[i][1] or "").lower(), "parts": parts}
        i += 1
        # params puis disp/lang/loc
        if i < len(tokens) and tokens[i][0] == "(":
            i = _skip_balanced(tokens, i)
        elif i < len(tokens) and tokens[i][0] == "nil":
            i += 1
        for _ in range(3):  # disposition, language, location
            if i < len(tokens) and tokens[i][0] == "(":
                i = _skip_balanced(tokens, i)
            elif i < len(tokens) and tokens[i][0] != ")":
                i += 1
        while i < len(tokens) and tokens[i][0] == "nil":
            i += 1  # variantes serveur : NIL traînants (jamais un enfant ni un sous-type)
        if i < len(tokens) and tokens[i][0] == ")":
            i += 1  # fermeture de CE corps multipart
        return node, i
    # feuille
    if i + 1 >= len(tokens):
        raise ValueError("feuille incomplète")
    type_ = (tokens[i][1] or "").lower()
    subtype = (tokens[i + 1][1] or "").lower()
    i += 2
    leaf: dict = {"type": type_, "subtype": subtype, "params": {}}
    if i < len(tokens) and tokens[i][0] == "(":
        i += 1
        while i + 1 < len(tokens) and tokens[i][0] != ")":
            key = str(tokens[i][1] or "").lower()
            val = tokens[i + 1][1]
            leaf["params"][key] = val if isinstance(val, str) else str(val)
            i += 2
        if i < len(tokens) and tokens[i][0] == ")":
            i += 1
    elif i < len(tokens) and tokens[i][0] == "nil":
        i += 1
    for _ in range(2):  # id, description (ignorés)
        if i < len(tokens) and tokens[i][0] in ("str", "nil"):
            i += 1
    if i < len(tokens) and tokens[i][0] in ("str", "nil"):
        leaf["encoding"] = (tokens[i][1] or "7bit").lower()
        i += 1
    if i < len(tokens) and tokens[i][0] == "num":
        leaf["size"] = tokens[i][1]
        i += 1
    if type_ == "message":
        # corps d'un email transféré imbriqué : parsing complet hors périmètre
        raise ValueError("message/rfc822 imbriqué non supporté pour l'aperçu")
    if i < len(tokens) and tokens[i][0] == "num":  # body-fld-lines (TEXT)
        i += 1
    # extensions BODYSTRUCTURE : md5, disposition, language, location
    if i < len(tokens) and tokens[i][0] in ("str", "nil"):  # md5
        i += 1
    if i < len(tokens) and tokens[i][0] == "(":  # disposition
        disp_text, i = _capture_balanced_text(tokens, i)
        leaf["disposition"] = disp_text
    elif i < len(tokens) and tokens[i][0] == "nil":
        i += 1
    for _ in range(2):  # language, location
        if i < len(tokens) and tokens[i][0] == "(":
            i = _skip_balanced(tokens, i)
        elif i < len(tokens) and tokens[i][0] != ")":
            i += 1
    while i < len(tokens) and tokens[i][0] == "nil":
        i += 1  # variantes serveur : NIL traînants
    if i < len(tokens) and tokens[i][0] == ")":
        i += 1  # fermeture de CE corps feuille
    return leaf, i


def _pick_text_plain(node: dict) -> dict | None:
    """Première feuille text/plain (préférence : non attachée) + chemin RFC 3501."""
    leaves: list[tuple[list, dict]] = []

    def walk(n: dict, path: list) -> None:
        if n.get("type") == "multipart":
            for idx, child in enumerate(n.get("parts") or [], start=1):
                walk(child, path + [idx])
        else:
            leaves.append((path, n))

    walk(node, [])
    plain = [(p, n) for p, n in leaves if n.get("type") == "text" and n.get("subtype") == "plain"]
    if not plain:
        return None

    def attached(n: dict) -> bool:
        if n.get("params", {}).get("name"):
            return True
        return "attachment" in (n.get("disposition") or "").lower()

    preferred = [(p, n) for p, n in plain if not attached(n)]
    chosen_path, chosen = (preferred or plain)[0]
    return {
        "section": ".".join(str(x) for x in chosen_path) or "1",
        "encoding": chosen.get("encoding") or "7bit",
        "size": chosen.get("size"),
        "charset": chosen.get("params", {}).get("charset"),
    }


def fetch_body_structure(conn: imaplib.IMAP4_SSL, uid: int) -> dict | None:
    """BODYSTRUCTURE → première section text/plain non attachée.

    Retourne {"section": "1.1", "encoding": "quoted-printable", "size": n} ou
    None (absente, illisible, HTML seul, message imbriqué → fail-closed)."""
    try:
        typ, data = conn.uid("fetch", str(uid), "(BODYSTRUCTURE)")
        if typ != "OK" or not data:
            return None
        chunks: list[bytes] = []
        for item in data:
            if isinstance(item, bytes):
                chunks.append(item)
            elif isinstance(item, tuple):
                chunks.extend(part for part in item if isinstance(part, bytes))
        text = b"".join(chunks).decode("utf-8", errors="replace")
        m = re.search(r"BODY(?:STRUCTURE)?\s*\(", text, re.IGNORECASE)
        if not m:
            return None
        tokens = _tokenize_bodystructure(text[m.end() - 1:])
        node, _ = _parse_bodystructure(tokens, 0, [])
        return _pick_text_plain(node)
    except Exception:
        return None


def fetch_body_preview(conn: imaplib.IMAP4_SSL, uid: int, max_bytes: int = 4096) -> dict | None:
    """Début de la section text/plain ciblée — BODY.PEEK (jamais \\Seen),
    fenêtre <0.max_bytes>. Retourne {"raw": bytes, "encoding": str} ou None."""
    max_bytes = max(512, min(int(max_bytes), 65536))
    structure = fetch_body_structure(conn, uid)
    if structure is None:
        return None
    spec = f"(BODY.PEEK[{structure['section']}]<0.{max_bytes}>)"
    try:
        typ, data = conn.uid("fetch", str(uid), spec)
        if typ != "OK" or not data:
            return None
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes) and item[1]:
                return {"raw": item[1], "encoding": structure["encoding"],
                        "charset": structure.get("charset")}
    except Exception:
        return None
    return None
