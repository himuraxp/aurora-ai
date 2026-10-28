"""Service UNIQUE de mutation de rules.json (§11.7, J4).

Séquence (ARCHITECTURE §11.7) : verrou dédié `rules.lock` → charger l'état courant
→ idempotence (règle identique déjà présente = already_applied, contenu divergent
= conflit) → revérifier l'empreinte SHA-256 globale SOUS verrou (rules.json
modifié depuis la proposition = refus sans write) → validation schéma du document
candidat → tmp 0600 + fsync + `os.replace` → backup 0600 de la version valide
précédente → recharger + revalider. Réconciliation par `operation_id` : une
coupure après remplacement reconnaît la règle à l'identique (pas de doublon).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import config as config_mod
import state as state_mod

# Plafond global de règles (garde-fou §11.7) — au-delà : refus, pas d'accumulation.
MAX_RULES = 100


def rules_sha256(config_dir_path: Path) -> str:
    """Empreinte SHA-256 GLOBALE de rules.json (t10 : simple, conservateur)."""
    path = Path(config_dir_path) / "rules.json"
    if not path.exists():
        return "sha256:none"
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _read_doc(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write(path: Path, payload: dict, previous_bytes: bytes | None) -> None:
    """tmp 0600 + fsync + os.replace ; backup 0600 de la dernière version valide."""
    tmp = path.with_suffix(".json.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    if previous_bytes is not None:
        backup = path.with_suffix(".json.bak")
        bfd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(bfd, previous_bytes)
            os.fsync(bfd)
        finally:
            os.close(bfd)
    os.replace(tmp, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def append_rule(config_dir_path: Path, state, rule: dict, operation_id: str,
                expected_sha: str | None, now_iso: str) -> dict:
    """Ajoute une règle à rules.json de façon atomique et idempotente.

    expected_sha : empreinte SHA-256 globale attendue AVANT l'ajout (= target_version
    de la proposition) — tout rules.json modifié entre-temps → refus sans write.
    Retourne {"status": "applied"|"already_applied"|"conflict"|"sha_mismatch"|"invalid",
    "detail": str}."""
    config_dir_path = Path(config_dir_path)
    path = config_dir_path / "rules.json"
    lock_path = config_dir_path / "locks" / "rules.lock"
    config_mod.ensure_private_dir(lock_path.parent)
    with state_mod.FileLock(lock_path):
        current_sha = rules_sha256(config_dir_path)
        previous_bytes = path.read_bytes() if path.exists() else None
        doc = _read_doc(path) if path.exists() else None
        if path.exists() and doc is None:
            return {"status": "invalid", "detail": "rules.json illisible — mutation refusée"}
        if doc is None:
            doc = {"rules": [], "sensitive_senders": []}
        rules = doc.get("rules", [])
        # Idempotence §11.7 : même id déjà présent → l'identique = réconciliation
        # (coupure après remplacement), le divergent = conflit (jamais d'écrasement).
        for existing in rules:
            if existing.get("id") == rule.get("id"):
                if existing == rule:
                    state.record_rule_operation(operation_id, rule["id"], now_iso)
                    return {"status": "already_applied",
                            "detail": "règle identique déjà présente (réconciliation operation_id)"}
                return {"status": "conflict",
                        "detail": "id de règle déjà présent avec un contenu différent"}
        if expected_sha is not None and current_sha != expected_sha:
            return {"status": "sha_mismatch",
                    "detail": "rules.json modifié depuis la proposition — refus sans write"}
        if len(rules) >= MAX_RULES:
            return {"status": "invalid", "detail": "plafond de règles atteint"}
        candidate = {"rules": rules + [rule],
                     "sensitive_senders": doc.get("sensitive_senders", [])}
        try:
            config_mod.validate_rules_doc(candidate)
        except config_mod.ConfigError as exc:
            return {"status": "invalid", "detail": f"règle invalide: {exc}"}
        _atomic_write(path, candidate, previous_bytes)
        # Recharger + revalider depuis le disque (§11.7 : la version écrite fait foi)
        reloaded = _read_doc(path)
        try:
            if reloaded is None:
                raise config_mod.ConfigError("rules.json illisible après écriture")
            config_mod.validate_rules_doc(reloaded)
        except config_mod.ConfigError as exc:
            # Restauration : la version précédente validée redevient la vérité.
            if previous_bytes is not None:
                path.write_bytes(previous_bytes)
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            return {"status": "invalid", "detail": f"revalidation post-écriture échouée: {exc}"}
        state.record_rule_operation(operation_id, rule["id"], now_iso)
        return {"status": "applied", "detail": "règle écrite"}
