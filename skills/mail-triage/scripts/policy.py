"""Règles déterministes, niveaux de risque, invariants, pseudonymisation.

Un email est une donnée NON FIABLE : les règles sont évaluées sur des champs
extraits (en-têtes), jamais sur des instructions qu'un message pourrait contenir.
"""

from __future__ import annotations

import hashlib
import re

from config import destination_is_forbidden

MODE_AUTO = "auto"
MODE_PROPOSE = "propose"
MODE_NEVER = "never"


class PolicyError(Exception):
    """Évaluation impossible (règle invalide, destination interdite...)."""


def pseudonymize(value: str, length: int = 12) -> str:
    """Empreinte tronquée pour toute sortie CLI (jamais d'adresse complète)."""
    if value is None:
        return "none"
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:length]


def destination_is_allowed(folder: str, allowlist: list[str]) -> bool:
    """Destination dans l'allowlist ET jamais Corbeille/Spam/brouillons (invariants 1+2)."""
    if not folder:
        return False
    if folder not in allowlist:
        return False
    return not destination_is_forbidden(folder)


def _match_value(field: str, needle: str, *, domain: bool = False, contains: bool = False) -> bool:
    field_l = (field or "").lower()
    needle_l = (needle or "").lower()
    if not needle_l:
        return False
    if domain:
        return field_l.endswith(f"@{needle_l}") or field_l.endswith(f".{needle_l}") or field_l == needle_l
    if contains:
        return needle_l in field_l
    return needle_l in field_l


def rule_matches(rule: dict, message: dict) -> bool:
    """Match déterministe sur les en-têtes extraits : from/from_domain/subject/to."""
    match = rule.get("match", {})
    if not match:
        return False
    sender = message.get("from") or ""
    subject = message.get("subject") or ""
    to = message.get("to") or ""

    checks = []
    if "from_any" in match:
        checks.append(any(_match_value(sender, n, contains=True) for n in match["from_any"]))
    if "from_domain_any" in match:
        checks.append(any(_match_value(sender, n, domain=True) for n in match["from_domain_any"]))
    if "subject_any" in match:
        checks.append(any(_match_value(subject, n) for n in match["subject_any"]))
    if "to_contains_any" in match:
        checks.append(any(_match_value(to, n, contains=True) for n in match["to_contains_any"]))
    if not checks:
        return False
    # ET logique entre les clés de match présentes, OU à l'intérieur d'une liste.
    return all(checks)


def evaluate(message: dict, rules_doc: dict, allowlist: list[str], config: dict | None = None) -> dict:
    """Évalue les règles (priorité ascendante : 1 = prioritaire).

    Retourne {"action": "move"|"keep", "rule_id", "folder", "mode", "reason"}.
    La garde `never` gagne toujours sur une règle plus basse dans la liste.
    """
    rules = rules_doc.get("rules", [])
    sensitive = rules_doc.get("sensitive_senders", [])

    # Garde expéditeur sensible explicite (mode never implicite, priorité absolue).
    for s in sensitive:
        if s and _match_value(message.get("from") or "", s, contains=True):
            return {"action": "keep", "rule_id": "sensitive_sender", "folder": None, "mode": MODE_NEVER,
                    "reason": "expéditeur sensible (liste de garde)"}

    applicable = sorted(
        [r for r in rules if rule_matches(r, message)],
        key=lambda r: r.get("priority", 100),
    )
    if not applicable:
        return {"action": "keep", "rule_id": None, "folder": None, "mode": MODE_NEVER,
                "reason": "aucune règle (inconnu conservé en Inbox)"}

    rule = applicable[0]
    mode = rule["mode"]

    if mode == MODE_NEVER:
        return {"action": "keep", "rule_id": rule["id"], "folder": None, "mode": mode, "reason": "garde sensible"}

    folder = rule.get("folder")
    if not destination_is_allowed(folder, allowlist):
        raise PolicyError(
            f"règle {rule['id']}: destination absente de l'allowlist ou interdite ({folder!r}) — fail-closed"
        )

    if mode == MODE_PROPOSE:
        return {"action": "keep", "rule_id": rule["id"], "folder": folder, "mode": mode,
                "reason": "proposition (jamais de write autonome en V1)"}

    return {"action": "move", "rule_id": rule["id"], "folder": folder, "mode": mode,
            "reason": "règle déterministe auto-approuvée"}


def mask_subject(subject: str, patterns: list[str]) -> tuple[str, bool]:
    """Masque un sujet si un pattern sensible matche. Retourne (sujet_effectif, masqué)."""
    for pattern in patterns:
        try:
            if re.search(pattern, subject or ""):
                return "[sujet masqué]", True
        except re.error:
            continue
    return (subject or "(sans sujet)"), False
