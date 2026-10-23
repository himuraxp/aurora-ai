"""Digest kChat du matin : fenêtre temporelle fiable, contenu pseudonymisé côté CLI,
marqueur unique, idempotence (garde SQLite + réconciliation sans repost aveugle).

Frontière : le digest contient expéditeurs/sujets lisibles (boîte pro → kChat pro,
même organisation) MAIS jamais de corps complet ni de pièce jointe ; sujets
sensibles masqués. V4.1 (opt-in `digest.enrichment.enabled`, ARCHITECTURE §10) :
extraits textuels BORNÉS (lecture ≤ 4 096 octets, publication ≤ 180 chars) des
catégories autorisées, après contrôle de confidentialité et neutralisation —
les messages sensibles (`never` / sujet masqué) ne donnent lieu à AUCUNE lecture.
"""

from __future__ import annotations

import base64
import quopri
import re
import uuid
from datetime import datetime, timedelta, timezone

import policy
from kchat import KChatError

MARKER_PREFIX = "mail-triage-digest:"
DIGEST_FORMAT_VERSION = 3

_RE_PREFIX_RE = re.compile(r"^(?:\s*(?:re|fwd?|tr|aw)\s*(?:\[\d+\])?\s*:\s*)+", re.IGNORECASE)
_GITLAB_ID_RE = re.compile(r"\(([!#]\d+)\)\s*$")
_REF_SPLIT_RE = re.compile(r"\s+")

_DAYS_FR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
_MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
              "juil.", "août", "sept.", "oct.", "nov.", "déc."]

# Budget éditorial (lignes de contenu par section, hors titres)
MAX_REVIEW_LINES = 8
MAX_AUTO_LINES = 4
MAX_UNKNOWN_LINES = 4


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
    rules_doc = config.get("rules") or {}
    dest_cfg = config.get("destinations")
    allowlist = dest_cfg.get("allowlist", []) if isinstance(dest_cfg, dict) else []
    for msg in messages:
        subject, masked = policy.mask_subject(msg.get("subject") or "", sensitive_patterns)
        try:
            decision = policy.evaluate(msg, rules_doc, allowlist, config)
        except policy.PolicyError as exc:
            decision = {"action": "keep", "rule_id": None, "mode": "never",
                        "folder": None, "reason": f"fail-closed: {exc}"}
        # V4.1 (§10) : lecture de corps autorisée seulement pour les non-sensibles.
        # "mode never" couvre 2 cas : garde sensible (rule_id présent → jamais lu)
        # vs inconnu sans règle (rule_id None → cible d'aperçu valide).
        is_sensitive = (decision.get("mode") == "never"
                        and decision.get("rule_id") is not None)
        item = {
            "uid": msg["uid"],
            "from": msg.get("from") or "",
            "subject": subject,
            "subject_masked": masked,
            "message_id": msg.get("message_id") or "",
            "references": msg.get("references") or "",
            "internaldate": msg.get("internaldate"),
            "seen": msg.get("seen", False),
            "mode": decision.get("mode"),
            "rule_id": decision.get("rule_id"),
            "decision_action": decision.get("action"),
            "body_readable": not is_sensitive and not masked,
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
    unique_items, duplicate_count = _dedupe_by_message_id(new_items)
    conversations = group_conversations(unique_items)
    moved_counts = state.moved_counts_since(start.isoformat())
    counters = _counters(new_items, unique_items, conversations, moved_counts)
    return {
        "id": digest_id,
        "marker": new_marker(digest_id),
        "format_version": DIGEST_FORMAT_VERSION,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "timezone": config.get("digest", {}).get("timezone", "Europe/Paris"),
        "new": new_items,
        "unique": unique_items,
        "conversations": conversations,
        "counters": counters,
        "always_inbox": always,
        "moved_counts": moved_counts,
    }


def _dedupe_by_message_id(items: list[dict]) -> tuple[list[dict], int]:
    """Déduplication forte : Message-ID identique = même message (multi-delivery).

    Deux notifications GitLab d'une même MR ont des Message-ID DISTINCTS :
    elles restent des messages uniques — le regroupement est la tâche de
    group_conversations, jamais celle de la déduplication.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    duplicates = 0
    for item in items:
        mid = (item.get("message_id") or "").strip()
        if mid and mid in seen:
            duplicates += 1
            continue
        if mid:
            seen.add(mid)
        unique.append(item)
    return unique, duplicates


def normalized_subject(subject: str) -> str:
    stripped = _RE_PREFIX_RE.sub("", subject or "").strip().lower()
    return re.sub(r"\s+", " ", stripped)


def gitlab_key(subject: str) -> str | None:
    """Clé applicative GitLab : projet + identifiant (!MR / #issue) en fin de sujet.

    Ex. « Re: Player | chore(podcast): refactor (!89) » → « player|!89 ».
    !89 seul n'est pas une clé globale : le projet est obligatoire.
    """
    m = _GITLAB_ID_RE.search(subject or "")
    if not m:
        return None
    prefix = _RE_PREFIX_RE.sub("", (subject[:m.start()]).strip()).strip()
    project = prefix.split("|", 1)[0].strip().lower() if "|" in prefix else prefix.lower()
    if not project:
        return None
    return f"{project}|{m.group(1)}"


def group_conversations(items: list[dict]) -> list[dict]:
    """Regroupe les messages en conversations (union-find sur les clés fortes).

    Clés : Message-ID + chaîne References/In-Reply-To (graphe de thread), puis
    clé applicative GitLab projet+identifiant. Le sujet normalisé SANS
    identifiant structurel ne fusionne jamais deux messages (jamais de fusion
    de deux mails distincts au seul motif d'un sujet similaire).
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    item_keys: list[list[str]] = []
    for idx, item in enumerate(items):
        keys: list[str] = []
        mid = (item.get("message_id") or "").strip()
        if mid:
            keys.append(f"id:{mid}")
        for ref in _REF_SPLIT_RE.split(item.get("references") or ""):
            if ref:
                keys.append(f"id:{ref}")
        gk = gitlab_key(item.get("subject") or "")
        if gk:
            keys.append(f"gl:{gk}")
        if not keys:
            keys = [f"idx:{idx}"]
        item_keys.append(keys)
        for k in keys[1:]:
            union(keys[0], k)

    groups: dict[str, list[int]] = {}
    for idx, keys in enumerate(item_keys):
        groups.setdefault(find(keys[0]), []).append(idx)

    conversations: list[dict] = []
    for idxs in groups.values():
        members = [items[i] for i in idxs]
        members.sort(key=lambda m: (m["internaldate"] or "", m["uid"]))
        title_src = members[-1]["subject"] or ""
        gk = gitlab_key(title_src)
        label: str | None = None
        title = _RE_PREFIX_RE.sub("", title_src).strip()
        if gk:
            _, ident = gk.split("|", 1)
            title = _RE_PREFIX_RE.sub("", _GITLAB_ID_RE.sub("", title_src)).strip()
            # affichage : casse d'origine du projet (la clé de regroupement est lowercase)
            m = _GITLAB_ID_RE.search(title_src)
            prefix_display = _RE_PREFIX_RE.sub("", title_src[:m.start()].strip()).strip()
            project_display = (prefix_display.split("|", 1)[0].strip()
                               if "|" in prefix_display else prefix_display)
            label = f"{project_display} {ident}"
            if len(label) > 40:
                label = label[:37] + "…"
        if len(title) > 70:
            title = title[:67] + "…"
        conversations.append({
            "items": members,
            "count": len(members),
            "title": title,
            "label": label,
            "last_time": members[-1]["internaldate"],
        })
    conversations.sort(key=lambda c: (c["last_time"] or "", c["items"][-1]["uid"]), reverse=True)
    return conversations


def conversation_category(members: list[dict]) -> str:
    """Catégorie de présentation : review (à examiner) > auto (tri automatique) > unknown."""
    if any(m.get("mode") == "propose" for m in members):
        return "review"
    if all(m.get("decision_action") == "move" for m in members):
        return "auto"
    return "unknown"


def _counters(new_items: list[dict], unique_items: list[dict],
              conversations: list[dict], moved_counts: dict | None) -> dict:
    """Compteurs séparés — les termes ne sont pas interchangeables :
    reçu ≠ unique, éligible au tri ≠ déplacé confirmé, proposé ≠ déplacé."""
    moved = moved_counts or {}
    return {
        "messages_received": len(new_items),
        "unique_messages": len(unique_items),
        "duplicate_messages": len(new_items) - len(unique_items),
        "conversations": len(conversations),
        "auto_eligible": sum(1 for i in unique_items
                             if i.get("mode") == "auto" and i.get("decision_action") == "move"),
        "proposed": sum(1 for i in unique_items if i.get("mode") == "propose"),
        "auto_moved": sum(moved.values()),
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


def _window_local_label(iso_start: str, iso_end: str, tz_name: str) -> str:
    """Fenêtre affichée dans le fuseau métier (digest.timezone) — MÊME fuseau que
    les horaires des messages (sinon le digest paraît contenir des messages
    postérieurs à sa fenêtre). Fallback : heures brutes si tz inconnue."""
    def to_local(iso_ts: str) -> datetime:
        dt = datetime.fromisoformat(iso_ts)
        try:
            from zoneinfo import ZoneInfo
            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass
        return dt
    try:
        s = to_local(iso_start)
        e = to_local(iso_end)
        return (f"{_DAYS_FR[s.weekday()]} {s.day:02d} {_MONTHS_FR[s.month - 1]}, "
                f"{s:%H:%M} → {e:%H:%M}")
    except (ValueError, TypeError):
        return f"{iso_start[:16].replace('T', ' ')} → {iso_end[:16].replace('T', ' ')}"


def _fr(n: int, singular: str, plural: str) -> str:
    """Pluralisation française naturelle (« 1 nouveau message » / « 19 nouveaux messages »)."""
    return f"{n} {singular if n == 1 else plural}"


def _conv_line(conv: dict, tz_name: str) -> str:
    subject = conv["title"].replace(MARKER_PREFIX, "[marqueur-neutralisé:")
    if any(m.get("subject_masked") for m in conv["items"]):
        subject = f"{subject} :lock:"
    time_part = _safe_local_hour(conv["last_time"], tz_name)
    n = conv["count"]
    if conv["label"]:
        if n > 1:
            return f"- **{conv['label']}** · {n} notif. ({time_part}) — {subject}"
        return f"- **{conv['label']}** ({time_part}) — {subject}"
    sender = conv["items"][-1].get("from") or ""
    if n > 1:
        return f"- **{sender}** — {subject} · {n} notif. ({time_part})"
    return f"- **{sender}** — {subject} ({time_part})"


def _section(lines: list[str], header: str, convs: list[dict], max_lines: int, tz_name: str) -> None:
    if not convs:
        return
    lines.append(header)
    for conv in convs[:max_lines]:
        lines.append(_conv_line(conv, tz_name))
        lines.extend(_preview_lines(conv))
    if len(convs) > max_lines:
        lines.append(f"- + {_fr(len(convs) - max_lines, 'autre conversation', 'autres conversations')}")
    lines.append("")


def render_markdown(digest: dict) -> str:
    """Rendu kChat V3 (format_version 3) : « En bref » en tête, conversations
    regroupées (jamais 1 ligne par notification), conclusion actionnable
    (style Muse : savoir d'un coup d'œil s'il faut agir), budget éditorial
    ~15 lignes utiles. Marqueur unique inclus (réconciliation).

    Les sujets viennent d'emails (données non fiables) : toute occurrence du
    préfixe de marqueur y est neutralisée (anti-falsification de reconcile)."""
    tz_name = digest.get("timezone", "Europe/Paris")
    counters = digest.get("counters", {})
    conversations = digest.get("conversations", [])
    lines: list[str] = []

    window_label = _window_local_label(digest["window_start"], digest["window_end"], tz_name)
    lines.append(f"**:incoming_envelope: Digest emails — {window_label}**")
    lines.append("")

    brief: list[str] = []
    received = counters.get("messages_received", 0)
    brief.append(_fr(received, "nouveau message", "nouveaux messages"))
    if counters.get("duplicate_messages"):
        brief.append(_fr(counters["duplicate_messages"], "doublon ignoré", "doublons ignorés"))
    if counters.get("conversations"):
        brief.append(_fr(counters["conversations"], "conversation", "conversations"))
    if counters.get("proposed"):
        brief.append(f":warning: {_fr(counters['proposed'], 'message à valider', 'messages à valider')}")
    if counters.get("auto_eligible"):
        brief.append(f":white_check_mark: {_fr(counters['auto_eligible'], 'nouvel email couvert par les règles automatiques', 'nouveaux emails couverts par les règles automatiques')}")
    if counters.get("auto_moved"):
        brief.append(f":file_folder: {_fr(counters['auto_moved'], 'déplacé confirmé depuis le dernier digest', 'déplacés confirmés depuis le dernier digest')}")
    lines.append("**:sunny: En bref**")
    lines.extend(f"- {part}" for part in brief)
    lines.append("")

    review = [c for c in conversations if conversation_category(c["items"]) == "review"]
    auto = [c for c in conversations if conversation_category(c["items"]) == "auto"]
    unknown = [c for c in conversations if conversation_category(c["items"]) == "unknown"]

    _section(lines, f"**:warning: À examiner — proposés à validation**", review, MAX_REVIEW_LINES, tz_name)
    _section(lines, "**:repeat: Notifications regroupées (tri automatique)**", auto, MAX_AUTO_LINES, tz_name)
    _section(lines, "**:question: En attente (conservés dans l'Inbox)**", unknown, MAX_UNKNOWN_LINES, tz_name)

    always = digest.get("always_inbox", [])
    if always:
        lines.append(f"**Encore non lus ({len(always)})**")
        for item in always:
            subject = item["subject"].replace(MARKER_PREFIX, "[marqueur-neutralisé:")
            if item.get("subject_masked"):
                subject = f"{subject} :lock:"
            lines.append(f"- **{item['from']}** — {subject}")
            lines.extend(_preview_lines(item))
        lines.append("")

    moved = digest.get("moved_counts") or {}
    if len(moved) > 1:
        # ventilation multi-dossiers utile ; à 1 seul dossier, « En bref » suffit
        # (anti-répétition, retour ChatGPT P2)
        total = sum(moved.values())
        detail = ", ".join(f"{folder}: {count}" for folder, count in sorted(moved.items()))
        lines.append(f"**:file_folder: Tri automatique confirmé** : {_fr(total, 'message déplacé', 'messages déplacés')} ({detail})")
        lines.append("")

    lines.append(_conclusion(review, unknown, counters))
    lines.append("")

    lines.append(digest["marker"])
    return "\n".join(lines)


def _conclusion(review: list[dict], unknown: list[dict], counters: dict) -> str:
    """Conclusion actionnable (style Muse) : l'utilisateur sait d'un coup d'œil
    s'il doit décider. Factuel — le tri auto exige toujours un `apply --confirm-apply`
    humain : le digest indique l'action MÉTIER (décider), jamais les commandes."""
    proposed_n = counters.get("proposed", 0)
    unknown_n = sum(c["count"] for c in unknown)
    if proposed_n:
        return f"**:warning: {_fr(proposed_n, 'message attend', 'messages attendent')} ta décision** — cf. « À examiner »."
    if unknown_n:
        return f"**:question: {_fr(unknown_n, 'message sans règle reste', 'messages sans règle restent')} dans l'Inbox**."
    return "**:thumbsup: Rien à décider — tous les nouveaux emails sont couverts par les règles de tri.**"


# --- V4.1 : aperçus bornés (invariant révisé, ARCHITECTURE §10) ---

_PREVIEW_MAX_NORMALIZED = 500  # texte normalisé avant neutralisation
_PREVIEW_MAX_LINES = 2         # lignes publiées max par aperçu
_PREVIEW_MAX_CHARS_AUTO = 140  # plafond réduit pour les notifications auto enrichies
MAX_PREVIEW_FETCHES = 16       # plafond d'appels IMAP par digest (budget)
_SANITIZE_URL_RE = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)


def _decode_section(raw: bytes, encoding: str, charset: str | None = None) -> str | None:
    """Décode le payload d'une section MIME. Le charset DÉCLARÉ est prioritaire
    (reconnu uniquement — un charset inconnu retombe sur utf-8 → latin-1)."""
    try:
        enc = (encoding or "7bit").strip().lower()
        if enc == "base64":
            # validate=True : un base64 corrompu → renonciation (jamais un texte fabriqué)
            data = base64.b64decode(b"".join(raw.split()), validate=True)
        elif enc in ("quoted-printable", "quoted printable"):
            data = quopri.decodestring(raw)
        else:
            data = raw
        declared = (charset or "").strip().lower()
        if declared:
            try:
                return data.decode(declared)
            except (UnicodeDecodeError, LookupError):
                pass  # charset inconnu ou texte incohérent : fallback ci-dessous
        for fallback in ("utf-8", "latin-1"):
            try:
                return data.decode(fallback)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None


def _clean_preview(raw: bytes, encoding: str, charset: str | None = None) -> str | None:
    """Texte normalisé (≤ 500 chars) depuis le début d'une section text/plain :
    décodage MIME, retrait citations « > », signatures et lignes image
    décoratives, caractères de contrôle éliminés. HTML détecté → None
    (fail-closed : aperçu indisponible). Les corps sont des données non
    fiables : aucune structure n'est interprétée."""
    text = _decode_section(raw, encoding, charset)
    if not text:
        return None
    if re.search(r"<(?:html|body|div|table|p|br)\b", text[:400], re.IGNORECASE):
        return None
    kept: list[str] = []
    for line in text.splitlines():
        clean_line = line.strip()
        if not clean_line:
            if kept and kept[-1]:
                kept.append("")
            continue
        if clean_line.startswith(">"):
            continue  # citation d'un message précédent
        if (clean_line.startswith("-- ") or re.fullmatch(r"[-_=]{2,}", clean_line)
                or re.match(r"(?:sent|envoyé|envoyer)\s+(?:from|de|avec|via)\s",
                            clean_line, re.IGNORECASE)):
            break  # délimiteur/pied de signature : on s'arrête
        kept.append(clean_line)
        if len("\n".join(kept)) >= _PREVIEW_MAX_NORMALIZED:
            break
    # lignes décoratives (image markdown seule, ex. logo Trello) écartées
    # dès qu'une autre candidate utile existe — sélection déterministe
    while len(kept) > 1 and kept[0].startswith("!["):
        kept = kept[1:]
    joined = "\n".join(kept).strip()
    if not joined or re.search(r"</?(?:html|body|div|table|tr|td|p)\b", joined, re.IGNORECASE):
        return None
    joined = "".join(" " if ch == "\t" else ch
                     for ch in joined
                     if ch == "\n" or ch == "\t" or (32 <= ord(ch) != 127))
    joined = re.sub(r"\n{2,}", "\n", joined).strip()
    if not joined:
        return None
    return joined[:_PREVIEW_MAX_NORMALIZED]


def _sanitize_preview(text: str, sensitive_patterns: list, max_chars: int) -> dict:
    """Neutralisation avant publication (données non fiables) : marqueur digest
    falsifié → neutralisé, URL → [url-masquée] (jetons d'accès), markdown
    neutralisé, contenu sensible (patterns digest) → aperçu SUPPRIMÉ.
    ≤ max_chars / 2 lignes. Retourne {"preview", "suppressed"}."""
    lowered = text.lower()
    for pattern in sensitive_patterns or []:
        pat = str(pattern or "").strip().lower()
        if pat and pat in lowered:
            return {"preview": None, "suppressed": "sensitive"}
    out = text.replace("`", "'").replace("[", "\\[").replace("]", "\\]")
    out = out.replace(MARKER_PREFIX, "[marqueur-neutralisé:")
    out = _SANITIZE_URL_RE.sub("(url masquée)", out)
    lines = [ln.strip() for ln in out.split("\n") if ln.strip()][:_PREVIEW_MAX_LINES]
    out = " … ".join(lines)
    if len(out) > max_chars:
        out = out[: max_chars - 1].rstrip() + "…"
    if not out.strip("_… "):
        return {"preview": None, "suppressed": "empty"}
    return {"preview": out, "suppressed": None}


def build_preview(raw: bytes, encoding: str, charset: str | None, sensitive_patterns: list,
                  max_chars: int) -> dict:
    """Extrait publiable (V4.1) depuis un payload de section text/plain.
    Retourne {"preview": str|None, "suppressed": None|"sensitive"|"unavailable"|"empty"}."""
    cleaned = _clean_preview(raw, encoding, charset)
    if not cleaned:
        return {"preview": None, "suppressed": "unavailable"}
    return _sanitize_preview(cleaned, sensitive_patterns, max_chars)


def _body_readable(item: dict) -> bool:
    """Autorisation de lecture du corps (ARCHITECTURE §10.2) : jamais les
    sensibles (garde `never` avec règle/expéditeur, sujet masqué) ; un message
    sans règle (inconnu) reste une cible valide. Les items construits par
    build_digest portent `body_readable` ; fallback dérivé sinon (tests)."""
    if "body_readable" in item:
        return bool(item["body_readable"])
    if item.get("subject_masked"):
        return False
    if item.get("mode") == "never" and item.get("rule_id") is not None:
        return False
    return True


def preview_targets(built: dict, gitlab_enrich: bool = False) -> list[int]:
    """UIDs autorisés pour l'enrichissement (ARCHITECTURE §10.2) : conversations
    review/unknown + always_inbox ; notifications auto UNIQUEMENT si allowlist
    d'enrichissement explicite (`gitlab_enrich`). JAMAIS les sensibles
    (garde `never`, sujet masqué) — aucune lecture de corps pour eux."""
    targets: list[int] = []
    for conv in built.get("conversations", []):
        cat = conversation_category(conv["items"])
        if cat == "auto" and not gitlab_enrich:
            continue
        last = conv["items"][-1]
        if not _body_readable(last):
            continue
        targets.append(last["uid"])
    for item in built.get("always_inbox", []):
        if not _body_readable(item):
            continue
        targets.append(item["uid"])
    ordered: list[int] = []
    seen: set[int] = set()
    for uid in targets:
        if uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    return ordered


def enrich_previews(built: dict, cfg: dict, fetch_fn) -> dict:
    """Collecte des aperçus pour les cibles autorisées. Gated :
    `digest.enrichment.enabled=false` → AUCUN appel fetch_fn (retour {}).
    fetch_fn(uid, max_bytes) → {"raw", "encoding"} | None ; toute exception →
    aperçu indisponible (fail-closed, jamais une erreur de commande)."""
    enrichment = (cfg.get("digest") or {}).get("enrichment") or {}
    if not enrichment.get("enabled", False):
        return {}
    max_bytes = int(enrichment.get("max_fetch_bytes", 4096))
    max_chars = int(enrichment.get("max_preview_chars", 180))
    sensitive = (cfg.get("digest") or {}).get("sensitive_subject_patterns") or []
    gitlab_enrich = bool(enrichment.get("gitlab_enrich", False))
    # notifications auto enrichies : plafond d'extrait réduit (retour t5 P2)
    auto_uids: set[int] = set()
    if gitlab_enrich:
        for conv in built.get("conversations", []):
            if conversation_category(conv["items"]) == "auto":
                auto_uids.add(conv["items"][-1]["uid"])
    previews: dict[int, dict] = {}
    for uid in preview_targets(built, gitlab_enrich=gitlab_enrich)[:MAX_PREVIEW_FETCHES]:
        effective_max = min(max_chars, _PREVIEW_MAX_CHARS_AUTO) if uid in auto_uids else max_chars
        try:
            fetched = fetch_fn(uid, max_bytes)
        except Exception:
            fetched = None
        if fetched and fetched.get("raw"):
            previews[uid] = build_preview(fetched["raw"], fetched.get("encoding") or "7bit",
                                          fetched.get("charset"), sensitive, effective_max)
        else:
            previews[uid] = {"preview": None, "suppressed": "unavailable"}
    return previews


def attach_previews(built: dict, previews: dict) -> None:
    """Injecte les aperçus construits (clé = uid) dans conversations et
    always_inbox. Aperçu indisponible → mention discrète ; contenu sensible →
    RIEN (l'aperçu est supprimé, jamais même suggéré)."""
    for conv in built.get("conversations", []):
        _attach_one(conv, previews.get(conv["items"][-1]["uid"]))
    for item in built.get("always_inbox", []):
        _attach_one(item, previews.get(item["uid"]))


def _attach_one(entry: dict, pv: dict | None) -> None:
    if not pv:
        return
    if pv.get("preview"):
        entry["preview"] = pv["preview"]
    elif pv.get("suppressed") == "sensitive":
        entry.pop("preview_unavailable", None)  # sensible : aucune trace
    else:
        entry["preview_unavailable"] = True


def _preview_lines(entry: dict) -> list[str]:
    """Ligne(s) d'aperçu sous une conversation / un item (rendu kChat)."""
    if entry.get("preview"):
        return [f"> _{entry['preview']}_"]
    if entry.get("preview_unavailable"):
        return ["> _(aperçu indisponible)_"]
    return []


def publish(kchat_client, bot_user_id: str, recipient_user_id: str, markdown: str) -> dict:
    """Publie le digest en DM. Aucun retry : un timeout remonte en exception
    (le CLI marque 'uncertain' et reconcile tranche)."""
    channel_id = kchat_client.ensure_direct_channel(bot_user_id, recipient_user_id)
    post = kchat_client.post_message(channel_id, markdown)
    post_id = post.get("id") if isinstance(post, dict) else None
    if not post_id:
        raise KChatError(0, "/posts", "réponse sans id")
    return {"channel_id": channel_id, "post_id": post_id}
