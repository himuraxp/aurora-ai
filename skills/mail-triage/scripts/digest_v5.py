#!/usr/bin/env python3
"""Digest V5 — classification éditoriale + agrégation (cowork ChatGPT, 2026-11-04).

Fonction pure : ``render_digest_v5(built, config) -> str`` (markdown kChat).
Même ``built`` + même ``config`` → octets Markdown identiques. Aucune horloge,
aucun réseau, aucune écriture d'état.

La V5 est un MODE DE PRÉSENTATION additionnel, pas un nouveau traitement
métier : la fenêtre, le scan IMAP, l'idempotence (digest_id + marqueur de
dédup) et le moteur de publication ne changent pas. Désactivée par défaut
(shadow mode) : aperçu via ``digest --format 5`` ; publication basculée par
la clé de config ``digest_v5.enabled``.

Principes (conception ChatGPT validée) :
1. Attention humaine d'abord — clients, RH, demandes explicites, échéances.
2. Exceptions avant volumes — un pipeline en échec mérite plus d'attention
   que 20 notifications GitLab sans anomalie.
3. Silence utile — une boîte sans exception produit un digest de 2-3 lignes.

Classification déterministe par TABLE DE DÉCISIONS (jamais de score additif) :
chaque conversation reçoit importance (P0-P4), état d'action (required /
review / none) et un reason_code explicable. Les sources automatisées
canoniques (config) ne produisent JAMAIS d'action requise (pas de fausses
tâches) ; les événements d'échec sont comptés et libellés « N notifications
d'échec » — jamais « N pipelines en échec » (l'état courant n'est pas
vérifiable depuis les emails).

Sécurité du rendu : sujets/expéditeurs = données non fiables (échappement
markdown, troncature, contrôle neutralisé, préfixe de marqueur anti-
falsification) ; icônes et libellés générés par le moteur uniquement, jamais
extraits du contenu des emails.
"""
from __future__ import annotations

import re

MARKER_PREFIX = "mail-triage-digest:"

# Budgets éditoriaux (configurables, bornés : les valeurs du concept V5).
_BUDGET_BOUNDS = {
    "max_human_items": (1, 10, 4),
    "max_automated_sources": (1, 10, 3),
    "max_failure_examples": (0, 5, 2),
    "subject_max_chars": (30, 200, 80),
}

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


class DigestV5Error(ValueError):
    """Config V5 invalide (fail-closed : le digest V4 reste utilisable)."""


def load_config(config: dict) -> dict:
    """Charge et valide le bloc ``digest_v5`` (valeurs par défaut bornées)."""
    raw = dict(config.get("digest_v5") or {})
    raw.pop("enabled", None)  # gate de publication (shadow mode), pas un paramètre de rendu
    cfg: dict = {}
    for key, (low, high, default) in _BUDGET_BOUNDS.items():
        value = raw.pop(key, default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise DigestV5Error(f"digest_v5.{key} doit être un entier") from None
        if not low <= value <= high:
            raise DigestV5Error(f"digest_v5.{key} hors bornes [{low}, {high}]")
        cfg[key] = value

    cfg["critical_patterns"] = _compile_patterns(raw.pop("critical_patterns", []),
                                                 "critical_patterns")
    cfg["vip_senders"] = _str_list(raw.pop("vip_senders", []), "vip_senders")
    cfg["client_domains"] = _str_list(raw.pop("client_domains", []), "client_domains")
    cfg["hr_senders"] = _str_list(raw.pop("hr_senders", []), "hr_senders")

    action = raw.pop("action_patterns", [])
    _require(isinstance(action, list), "digest_v5.action_patterns doit être une liste")
    compiled = []
    for entry in action:
        _require(isinstance(entry, dict), "action_patterns: entrée non objet")
        pid = str(entry.get("id") or "")
        _require(bool(pid), "action_patterns: id requis")
        compiled.append({"id": pid, "re": _compile(str(entry.get("pattern") or ""),
                                                   f"action_patterns.{pid}")})
    cfg["action_patterns"] = compiled

    sources = raw.pop("automation_sources", [])
    _require(isinstance(sources, list), "digest_v5.automation_sources doit être une liste")
    parsed_sources = []
    for entry in sources:
        _require(isinstance(entry, dict), "automation_sources: entrée non objet")
        sid = str(entry.get("id") or "")
        sender = str(entry.get("sender") or "").strip().lower()
        _require(bool(sid) and bool(sender), "automation_sources: id et sender requis")
        parsed_sources.append({
            "id": sid,
            "sender": sender,
            "failure": _compile_patterns(entry.get("failure_patterns", []),
                                         f"automation_sources.{sid}.failure"),
            "recovery": _compile_patterns(entry.get("recovery_patterns", []),
                                          f"automation_sources.{sid}.recovery"),
        })
    cfg["automation_sources"] = parsed_sources

    if raw:
        raise DigestV5Error(f"clés digest_v5 inconnues: {sorted(raw)}")
    return cfg


def _str_list(value, name: str) -> list[str]:
    _require(isinstance(value, list) and all(isinstance(v, str) for v in value),
             f"digest_v5.{name} doit être une liste de chaînes")
    return [v.strip().lower() for v in value if v.strip()]


def _compile_patterns(patterns, name: str) -> list:
    _require(isinstance(patterns, list), f"digest_v5.{name} doit être une liste")
    return [_compile(str(p), name) for p in patterns]


def _compile(pattern: str, name: str):
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise DigestV5Error(f"digest_v5.{name}: regex invalide ({exc})") from None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DigestV5Error(message)


# --- Classification (table de décisions, précédence explicite) ---

def _sender_of(item: dict) -> str:
    """Adresse email normalisée ; « display <a@b> » → « a@b » (donnée non
    fiable : jamais interprétée comme instruction, uniquement comparée)."""
    sender = str(item.get("from") or "").strip().lower()
    if "<" in sender and ">" in sender:
        sender = sender.split("<", 1)[1].split(">", 1)[0].strip()
    return sender


def _domain_of(sender: str) -> str:
    return sender.rsplit("@", 1)[-1] if "@" in sender else ""


def _source_of(item: dict, sources: list) -> dict | None:
    sender = _sender_of(item)
    for source in sources:
        if sender == source["sender"]:
            return source
    return None


def _any_match(patterns: list, subject: str) -> bool:
    return any(p.search(subject) for p in patterns)


def classify_item(item: dict, config: dict) -> dict:
    """Classe un message selon la table de décisions (premier match gagne)."""
    subject = str(item.get("subject") or "")
    source = _source_of(item, config["automation_sources"])
    if _any_match(config["critical_patterns"], subject):
        return {"importance": "P0", "action_state": "required", "automation": "human",
                "reason_code": "critical-pattern"}
    if source is not None:
        if _any_match(source["failure"], subject):
            return {"importance": "P3", "action_state": "none", "automation": "automated",
                    "reason_code": f"automation-failure:{source['id']}"}
        if _any_match(source["recovery"], subject):
            return {"importance": "P4", "action_state": "none", "automation": "automated",
                    "reason_code": f"automation-recovery:{source['id']}"}
        return {"importance": "P4", "action_state": "none", "automation": "automated",
                "reason_code": f"automation-normal:{source['id']}"}
    if item.get("mode") == "propose":
        return {"importance": "P1", "action_state": "required", "automation": "human",
                "reason_code": "proposed"}
    if _any_match([p["re"] for p in config["action_patterns"]], subject):
        return {"importance": "P1", "action_state": "required", "automation": "human",
                "reason_code": "action-pattern"}
    sender = _sender_of(item)
    if sender in config["vip_senders"]:
        return {"importance": "P2", "action_state": "review", "automation": "human",
                "reason_code": "vip"}
    domain = _domain_of(sender)
    if domain and domain in config["hr_senders"]:
        return {"importance": "P2", "action_state": "review", "automation": "human",
                "reason_code": "hr"}
    if domain and domain in config["client_domains"]:
        return {"importance": "P2", "action_state": "review", "automation": "human",
                "reason_code": "client-domain"}
    if item.get("decision_action") == "move":
        # Automatisé sans source canonique : jamais associé à une source connue.
        return {"importance": "P4", "action_state": "none", "automation": "automated",
                "reason_code": "automation-unclassified"}
    return {"importance": "P2", "action_state": "review", "automation": "human",
            "reason_code": "human-unclassified"}


def classify_conversation(conv: dict, config: dict) -> dict:
    """Classification de conversation = membre de plus haute précédence."""
    best: dict | None = None
    for member in conv["items"]:
        classification = classify_item(member, config)
        if best is None or (_PRIORITY_RANK[classification["importance"]]
                            < _PRIORITY_RANK[best["importance"]]):
            best = classification
    assert best is not None
    return best


# --- Échappement / troncature (données non fiables) ---

def _escape(value: str, max_chars: int) -> str:
    """Neutralise le markdown kChat, les retours à la ligne et les caractères
    de contrôle, puis tronque. Le préfixe de marqueur est neutralisé
    (anti-falsification du reconcile, même règle que le rendu V4)."""
    value = str(value or "").replace(MARKER_PREFIX, "[marqueur-neutralisé:")
    value = value.replace("\\", "\\\\")
    for char in "*_`[]()~>#|":
        value = value.replace(char, f"\\{char}")
    value = "".join(c for c in value if c.isprintable())
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_chars:
        value = value[: max_chars - 1].rstrip() + "…"
    return value


# --- Agrégation ---

def _aggregate_sources(items: list, config: dict) -> list:
    """Une ligne par source canonique (compteurs + exemples d'anomalie).
    Les automatisés sans source canonique tombent sous leur adresse (jamais
    associés à une source connue)."""
    buckets: dict = {}
    for item in items:
        classification = classify_item(item, config)
        if classification["automation"] == "human":
            continue
        source = _source_of(item, config["automation_sources"])
        sid = source["id"] if source else _sender_of(item) or "(inconnu)"
        bucket = buckets.setdefault(sid, {"id": sid, "count": 0, "conversations": 0,
                                          "failures": 0, "recoveries": 0, "examples": []})
        bucket["count"] += 1
        if classification["reason_code"].startswith("automation-failure:"):
            bucket["failures"] += 1
            if len(bucket["examples"]) < config["max_failure_examples"]:
                bucket["examples"].append(str(item.get("subject") or ""))
        elif classification["reason_code"].startswith("automation-recovery:"):
            bucket["recoveries"] += 1
    for bucket in buckets.values():
        bucket["conversations"] = _distinct_conversations(items, bucket["id"], config)
    ordered = sorted(buckets.values(),
                     key=lambda b: (-b["failures"], -b["count"], b["id"]))
    return ordered


def _distinct_conversations(items: list, source_id: str, config: dict) -> int:
    senders = {source["sender"]: source["id"] for source in config["automation_sources"]}
    subjects: set = set()
    for item in items:
        if _source_of(item, config["automation_sources"]):
            sid = senders[_sender_of(item)]
        else:
            sid = _sender_of(item) or "(inconnu)"
        if sid != source_id:
            continue
        subjects.add(str(item.get("subject") or "").strip().lower())
    return len(subjects)


# --- Rendu ---

def _budget(built: dict, config: dict) -> dict:
    """Sectionne les conversations par état d'action + conservation des compteurs.

    Chaque message unique appartient à une seule catégorie primaire :
    N messages = N humains + N automatisés canoniques + N non classés.
    Le backlog (non lus plus anciens que la fenêtre, jamais digestés —
    ``always_inbox`` du built) est traité à part : humain → section
    rattrapage, automatisé → compteur de bilan (silence utile)."""
    categories = {"human": 0, "automated": 0, "unclassified": 0}
    required: list = []
    review: list = []
    for conv in built.get("conversations", []):
        classification = classify_conversation(conv, config)
        for member in conv["items"]:
            member_class = classify_item(member, config)
            if member_class["automation"] == "human":
                categories["human"] += 1
            elif member_class["reason_code"] == "automation-unclassified":
                categories["unclassified"] += 1
            else:
                categories["automated"] += 1
        if classification["action_state"] == "required":
            required.append((conv, classification))
        elif classification["action_state"] == "review":
            review.append((conv, classification))

    backlog_human: list = []
    backlog_automated = 0
    for item in built.get("always_inbox", []):
        classification = classify_item(item, config)
        if classification["automation"] == "human":
            backlog_human.append((item, classification))
        else:
            backlog_automated += 1
    # Tri stable en deux passes : récence descendante, puis priorité.
    backlog_human.sort(key=lambda pair: (pair[0].get("internaldate") or ""), reverse=True)
    backlog_human.sort(key=lambda pair: _PRIORITY_RANK[pair[1]["importance"]])

    # Tri stable en deux passes : priorité croissante, puis récence descendante
    # (le plus récent d'abord à priorité égale).
    required.sort(key=lambda pair: (pair[0].get("last_time") or ""), reverse=True)
    required.sort(key=lambda pair: _PRIORITY_RANK[pair[1]["importance"]])
    review.sort(key=lambda pair: (pair[0].get("last_time") or ""), reverse=True)
    review.sort(key=lambda pair: _PRIORITY_RANK[pair[1]["importance"]])
    return {"required": required, "review": review, "categories": categories,
            "backlog_human": backlog_human, "backlog_automated": backlog_automated}


def _human_line(conv: dict, config: dict) -> str:
    """Ligne de conversation humaine : expéditeur + sujet échappés, sans
    horodatage (densité V5 — la récence guide déjà l'ordre de tri)."""
    subject = _escape(conv.get("title") or "", config["subject_max_chars"])
    sender = _escape(conv["items"][-1].get("from") or "", 60)
    count = conv.get("count", 1)
    suffix = f" · {count} notif." if count > 1 else ""
    return f"- **{sender}** — {subject}{suffix}"


def _backlog_line(item: dict, config: dict) -> str:
    """Ligne de rattrapage (message isolé, hors fenêtre, jamais digesté)."""
    subject = _escape(item.get("subject") or "", config["subject_max_chars"])
    sender = _escape(item.get("from") or "", 60)
    return f"- **{sender}** — {subject}"


def _fr(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {plural}"


def _source_line(bucket: dict, config: dict) -> list:
    """Ligne de source agrégée : une ligne par source, exemples d'anomalie
    bornés sous la ligne (↳). Compteur factuel — jamais d'état courant affirmé."""
    label = _escape(bucket["id"], 40)
    parts = [f"{bucket['count']} notif."]
    if bucket["conversations"] and bucket["conversations"] != bucket["count"]:
        parts.append(f"{bucket['conversations']} conv.")
    if bucket["failures"]:
        parts.append(_fr(bucket["failures"], "échec", "échecs"))
    if bucket["recoveries"]:
        parts.append(_fr(bucket["recoveries"], "rétablissement", "rétablissements"))
    lines = [f"- {label} — {' · '.join(parts)}"]
    if bucket["examples"]:
        shown = [_escape(example, config["subject_max_chars"])
                 for example in bucket["examples"]]
        lines.append(f"  ↳ {', '.join(shown)}")
    return lines


def render_digest_v5(built: dict, config: dict) -> str:
    """Rend le markdown kChat V5 — fonction pure (built + config → octets).

    Sections conditionnelles (les vides disparaissent) :
    À traiter → À lire → rattrapage → Automatiques (seulement si au
    moins une anomalie) → bilan + marqueur de dédup. Sans icônes :
    les compteurs et libellés portent l'information.
    """
    cfg = load_config(config)
    budget = _budget(built, cfg)
    counters = built.get("counters", {})
    received = int(counters.get("messages_received", 0))
    lines: list = []

    for state, label in (("required", "À traiter"),
                         ("review", "À lire")):
        conversations = budget[state]
        if not conversations:
            continue
        lines.append(f"**{label} ({len(conversations)})**")
        for conv, _cls in conversations[: cfg["max_human_items"]]:
            lines.append(_human_line(conv, cfg))
        if len(conversations) > cfg["max_human_items"]:
            hidden = len(conversations) - cfg["max_human_items"]
            lines.append(f"- + {hidden} autre(s)")
        lines.append("")

    # Rattrapage : non lus plus anciens que la fenêtre, JAMAIS digestés
    # (parité V4 « Encore non lus »). Humain → lignes ; automatisé → bilan.
    backlog = budget["backlog_human"]
    if backlog:
        lines.append(f"**À lire — rattrapage ({len(backlog)})**")
        for item, _cls in backlog[: cfg["max_human_items"]]:
            lines.append(_backlog_line(item, cfg))
        if len(backlog) > cfg["max_human_items"]:
            lines.append(f"- + {len(backlog) - cfg['max_human_items']} autre(s)")
        lines.append("")

    automated_items = [item for item in built.get("unique", [])
                       if classify_item(item, cfg)["automation"] == "automated"]
    sources = _aggregate_sources(built.get("unique", []), cfg)
    if sources and any(bucket["failures"] for bucket in sources):
        lines.append(f"**Automatiques — {len(automated_items)} notif.**")
        for bucket in sources[: cfg["max_automated_sources"]]:
            lines.extend(_source_line(bucket, cfg))
        if len(sources) > cfg["max_automated_sources"]:
            lines.append(f"- + {len(sources) - cfg['max_automated_sources']} autre(s) source(s)")
        lines.append("")

    # Bilan : factuel — attention requise + couverture du tri. Les échecs
    # sont des événements reçus, jamais un état courant affirmé.
    required_n = sum(conv.get("count", 1) for conv, _cls in budget["required"])
    review_n = sum(conv.get("count", 1) for conv, _cls in budget["review"])
    covered = int(counters.get("auto_eligible", 0))
    bilan_parts: list = []
    if required_n:
        bilan_parts.append(f"{required_n} message(s) attendent une action")
    if review_n:
        bilan_parts.append(f"{review_n} à lire")
    if budget["backlog_automated"]:
        bilan_parts.append(_fr(budget["backlog_automated"],
                               "notification automatique plus ancienne non lue",
                               "notifications automatiques plus anciennes non lues"))
    if required_n or review_n:
        if covered:
            bilan_parts.append(f"{covered}/{received} couverts par le tri automatique")
    elif covered:
        bilan_parts.append(f"Aucune action humaine identifiée · {covered}/{received} couverts par le tri automatique")
    else:
        bilan_parts.append(f"Aucune action humaine identifiée · {received} notification(s) automatiquement classée(s)")
    lines.append(" · ".join(bilan_parts))
    lines.append("")
    lines.append(str(built.get("marker") or "").strip())
    return "\n".join(lines)
