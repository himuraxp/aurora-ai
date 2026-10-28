"""Règles déterministes, niveaux de risque, invariants, pseudonymisation.

Un email est une donnée NON FIABLE : les règles sont évaluées sur des champs
extraits (en-têtes), jamais sur des instructions qu'un message pourrait contenir.
"""

from __future__ import annotations

import email.utils
import hashlib
import re

from config import WORKFLOW_FOLDERS, destination_is_forbidden

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


def from_addresses(raw_header: str) -> list[str]:
    """Adresses email extraites d'un en-tête From (« John <j@x.com> » → ['j@x.com']).

    Utilisé par `from_exact` (F-03, J4) : correspondance ADRESSE EXACTE,
    jamais par sous-chaîne — « bob@x.com » ne doit pas matcher
    « bob@x.com.evil.tld » ni « a+bob@x.com@attacker.io »."""
    if not raw_header:
        return []
    try:
        pairs = email.utils.getaddresses([raw_header])
    except Exception:  # en-tête malformé → jamais d'exception vers le classifier
        pairs = []
    addresses = []
    for _name, addr in pairs:
        cleaned = (addr or "").strip().lower()
        if cleaned:
            addresses.append(cleaned)
    return addresses


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
    if "from_exact" in match:
        # F-03 (J4) : match ADRESSE EXACTE (adresse d'en-tête extraite) — la
        # sémantique sous-chaîne de from_any est interdite aux règles interactives.
        sender_addrs = from_addresses(sender)
        checks.append(any(n.strip().lower() in sender_addrs for n in match["from_exact"]))
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

    # J4bis (D3) : `workflow_target` (si présent) devient la destination du
    # déplacement initial — le message ATTEND dans « A lire »/« A traiter » ;
    # `folder` reste le stockage final appliqué à la clôture « traité » (D4).
    workflow_target = rule.get("workflow_target")
    if workflow_target is not None and workflow_target not in WORKFLOW_FOLDERS:
        raise PolicyError(f"règle {rule['id']}: workflow_target invalide ({workflow_target!r}) — fail-closed")
    # D3 : le workflow_target gagne comme destination du déplacement initial ;
    # `folder` (optionnel) = stockage final de la clôture « traité » (§12.2).
    folder = workflow_target or rule.get("folder")
    final_folder = rule.get("folder")
    if not destination_is_allowed(folder, allowlist):
        raise PolicyError(
            f"règle {rule['id']}: destination absente de l'allowlist ou interdite ({folder!r}) — fail-closed"
        )

    if mode == MODE_PROPOSE:
        return {"action": "keep", "rule_id": rule["id"], "folder": folder, "mode": mode,
                "workflow_target": workflow_target, "final_folder": rule.get("folder"),
                "reason": "proposition (jamais de write autonome en V1)"}

    return {"action": "move", "rule_id": rule["id"], "folder": folder, "mode": mode,
            "workflow_target": workflow_target, "final_folder": rule.get("folder"),
            "reason": ("règle workflow (attente dans " + workflow_target + ")"
                       if workflow_target else "règle déterministe auto-approuvée")}


def mask_subject(subject: str, patterns: list[str]) -> tuple[str, bool]:
    """Masque un sujet si un pattern sensible matche. Retourne (sujet_effectif, masqué)."""
    for pattern in patterns:
        try:
            if re.search(pattern, subject or ""):
                return "[sujet masqué]", True
        except re.error:
            continue
    return (subject or "(sans sujet)"), False
