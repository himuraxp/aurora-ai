#!/usr/bin/env python3
"""CLI mail-triage : scan | plan | apply | status | reconcile | digest.

Contrats (ARCHITECTURE.md) :
- Sorties JSON garanties, exit 0 (OK) / 1 (erreur métier) / 2 (usage/config).
- Fail-closed : toute erreur → aucune action.
- Sorties plan/apply/status/reconcile pseudonymisées (jamais d'adresse complète).
  `scan` et `digest` (sans --send) affichent des données lisibles : inspection
  volontaire en session — jamais journalisées par le moteur.
- Kills switches (writes.enabled / imap_enabled / digest_enabled) vérifiés avant
  toute mutation, quel que soit l'appelant (skill, launchd, CLI direct).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import imaplib
import sqlite3

import config as config_mod  # noqa: E402
import digest as digest_mod  # noqa: E402
import interact as interact_mod  # noqa: E402
import imap_client as imap_mod  # noqa: E402
import kchat as kchat_mod  # noqa: E402
import policy  # noqa: E402
import state as state_mod  # noqa: E402

AUDIT_MAX_BYTES = 5 * 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _out(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def _err(kind: str, message: str, exit_code: int = 1, **extra) -> int:
    print(json.dumps({"error": kind, "message": message, **extra}, ensure_ascii=False, indent=2))
    return exit_code


def audit(config_dir_path: Path, event: dict) -> None:
    """audit.jsonl : append + rotation par taille. Contenu pseudonymisé par l'appelant."""
    path = config_dir_path / "audit.jsonl"
    try:
        if path.exists() and path.stat().st_size > AUDIT_MAX_BYTES:
            path.replace(path.with_suffix(".jsonl.1"))
        line = json.dumps({"ts": _now_iso(), **event}, ensure_ascii=False, separators=(",", ":"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        os.chmod(path, 0o600)
    except OSError:
        # L'audit ne doit jamais faire échouer une action déjà validée.
        pass


def _connect_imap(cfg: dict):
    account = cfg["account"]
    login = config_mod.get_secret(account.get("login_env") or "MAIL_TRIAGE_IMAP_LOGIN")
    password = config_mod.get_secret(account["password_env"])
    return imap_mod.connect(account["host"], account["port"], login, password)


def _fetch_recent(cfg: dict, conn, state, uidvalidity: int) -> list[dict]:
    digest_cfg = cfg.get("digest", {})
    window = int(digest_cfg.get("scan_recent_uid_window", 300))
    seen = state.seen_uids(cfg["source"]["mailbox"], uidvalidity)
    min_uid = (max(seen) - window) if seen else None
    return imap_mod.fetch_recent_headers(conn, cfg["source"]["mailbox"], limit=200, min_uid=min_uid)


def _uidvalidity(conn, mailbox: str) -> int:
    try:
        # Review F-02 : mailbox TOUJOURS quoté (les dossiers workflow « A lire »
        # / « A traiter » contiennent des espaces — STATUS non-quoté = BAD serveur).
        return int(conn.status(imap_mod.quote_mailbox(mailbox), "(UIDVALIDITY)")
                   [1][0].decode().split("UIDVALIDITY ")[1].rstrip(")]"))
    except Exception as exc:  # pragma: no cover - dépend du serveur
        raise imap_mod.ImapError(f"UIDVALIDITY illisible: {type(exc).__name__}") from exc


# --- commandes ---------------------------------------------------------------

def cmd_scan(cfg: dict) -> int:
    writes = cfg["writes"]
    conn = _connect_imap(cfg)
    try:
        move_capability = imap_mod.has_move_capability(conn)
        folders = [b["name"] for b in imap_mod.list_mailboxes(conn)]
        uidvalidity = _uidvalidity(conn, cfg["source"]["mailbox"])
        messages = _fetch_recent(cfg, conn, state_mod.State(
            config_mod.config_dir(cfg.get("_config_dir")) / "state.sqlite"), uidvalidity)
    finally:
        imap_mod.logout(conn)

    rules_doc = cfg["rules"]
    allowlist = cfg["destinations"]["allowlist"]
    results = []
    for msg in messages:
        try:
            decision = policy.evaluate(msg, rules_doc, allowlist, cfg)
        except policy.PolicyError as exc:
            decision = {"action": "keep", "rule_id": None, "folder": None, "mode": "never",
                        "reason": f"fail-closed: {exc}"}
        results.append({
            "uid": msg["uid"],
            "from_hash": policy.pseudonymize(msg.get("from") or "", 10),
            "subject": msg.get("subject") or "(sans sujet)",
            "internaldate": msg.get("internaldate"),
            "seen": msg.get("seen", False),
            "decision": decision,
        })

    return _out({
        "command": "scan",
        "mailbox": cfg["source"]["mailbox"],
        "uidvalidity": uidvalidity,
        "capabilities": {"move": move_capability},
        "folders": folders,
        "notice": "sortie lisible (inspection volontaire) — ne pas journaliser",
        "writes": {k: writes[k] for k in ("enabled", "imap_enabled", "digest_enabled")},
        "messages": results,
    })


def cmd_plan(cfg: dict, args) -> int:
    if not cfg["writes"]["enabled"]:
        return _err("writes_disabled", "kill switch writes.enabled=false — aucune construction de plan")
    state = state_mod.State(config_mod.config_dir(cfg.get("_config_dir")) / "state.sqlite")
    conn = _connect_imap(cfg)
    try:
        uidvalidity = _uidvalidity(conn, cfg["source"]["mailbox"])
        messages = _fetch_recent(cfg, conn, state, uidvalidity)
    finally:
        imap_mod.logout(conn)

    moves = []
    kept = 0
    for msg in messages:
        decision = policy.evaluate(msg, cfg["rules"], cfg["destinations"]["allowlist"], cfg)
        if decision["action"] != "move":
            kept += 1
            continue
        moves.append({
            "uid": msg["uid"],
            "from_folder": cfg["source"]["mailbox"],
            "to_folder": decision["folder"],
            "rule_id": decision["rule_id"],
            "from_hash": policy.pseudonymize(msg.get("from") or "", 10),
            "message_id": (msg.get("message_id") or "").strip(),
        })

    if not moves:
        return _out({"command": "plan", "moves": [], "kept": kept,
                     "message": "aucun déplacement planifié (rien à appliquer)"})

    now = datetime.now(timezone.utc)
    payload = {
        "mailbox": cfg["source"]["mailbox"],
        "uidvalidity": uidvalidity,
        "moves": moves,
        "created_at": now.isoformat(timespec="seconds"),
    }
    plan_id = uuid.uuid4().hex[:12]
    expires = (now + timedelta(hours=cfg.get("plan", {}).get("expire_hours", 24))).isoformat(timespec="seconds")
    sha = state.create_plan(plan_id, now.isoformat(timespec="seconds"), expires, payload)
    audit(config_mod.config_dir(cfg.get("_config_dir")),
          {"event": "plan_created", "plan_id": plan_id, "moves": len(moves), "sha256": sha[:12]})
    return _out({
        "command": "plan",
        "plan_id": plan_id,
        "sha256": sha,
        "expires_at": expires,
        "uidvalidity": uidvalidity,
        "moves": [{k: m[k] for k in ("uid", "from_hash", "to_folder", "rule_id")} for m in moves],
        "kept": kept,
        "note": "destinations pseudonymisées à l'affichage du diff — apply revalide tout",
    })


def _revalidate_preconditions(cfg: dict, conn, move: dict) -> str | None:
    """Revalidation avant CHAQUE déplacement. Retourne une raison de refus ou None.
    J4bis (D7) : la source est le DOSSIER du move (from_folder — INBOX ou dossier
    workflow), jamais une source globale pinnée : les plans/refs sont liés au
    dossier source (mailbox + uidvalidity + uid)."""
    if not policy.destination_is_allowed(move["to_folder"], cfg["destinations"]["allowlist"]):
        return "destination hors allowlist (config changée ?)"
    if not imap_mod.mailbox_exists(conn, move["to_folder"]):
        return "destination absente sur le serveur (jamais de création)"
    source = move.get("from_folder") or cfg["source"]["mailbox"]
    if not imap_mod.mailbox_exists(conn, source):
        return "source absente"
    return None


def _fetch_message_id(conn, move: dict) -> str | None:
    """Message-ID du message SOURCE (fetch read-only, AVANT le move — l'UID
    source disparaît au MOVE) : identité stable pour la réconciliation `\\Seen`
    dans la destination (§12.3). None = réconciliation impossible (fail-silent
    ici : le move reste possible, le \\Seen ne sera JAMAIS appliqué aveuglément).
    Review F-01 : dépliage RFC 5322 (CRLF+WSP → espace) puis rejet de tout
    octet hors ASCII imprimable — un Message-ID forgé ne doit JAMAIS atteindre
    le socket (imaplib n'assume aucune validation CR/LF)."""
    import re as _re
    try:
        imap_mod.select_mailbox(conn, move.get("from_folder") or "INBOX", readonly=True)
        typ, data = conn.uid("fetch", str(move["uid"]),
                             "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        if typ != "OK" or not data:
            return None
        for item in data:
            raw = item[1] if isinstance(item, tuple) and len(item) > 1 else item
            if isinstance(raw, bytes):
                m = _re.search(rb"(?i)message-id\s*:\s*(<[^>]+>)", raw)
                if m:
                    unfolded = _re.sub(rb"\r?\n[ \t]+", b" ", m.group(1))
                    try:
                        mid = unfolded.decode("ascii")
                    except UnicodeDecodeError:
                        return None
                    if not mid or not all(0x20 <= ord(c) <= 0x7E for c in mid):
                        return None
                    return mid.strip()
    except imap_mod.ImapError:
        return None
    return None


def _store_seen_on_destination(conn, move: dict) -> bool:
    """STORE +FLAGS \\Seen sur la DESTINATION après réconciliation identité
    (SEARCH HEADER Message-ID — l'UID change au MOVE). Cible absente ou
    ambiguë = False (jamais de \\Seen aveugle, §12.3) — résultat uncertain."""
    mid = (move.get("message_id") or "").strip()
    dest = move.get("to_folder")
    if not mid or not dest:
        return False
    try:
        imap_mod.select_mailbox(conn, dest, readonly=False)
        typ, data = conn.uid("search", None,
                             f'HEADER Message-ID "{_escape_imap_string(mid)}"')
        if typ != "OK" or not data or not data[0]:
            return False
        uids = data[0].split()
        if len(uids) != 1:
            return False  # doublons → cible incertaine, jamais de \\Seen
        typ, _ = conn.uid("store", uids[0].decode("ascii", "replace"),
                          "+FLAGS", "(\\Seen)")
        return typ == "OK"
    except imap_mod.ImapError:
        return False


def _execute_moves(cfg: dict, conn, state, plan_id: str, payload: dict,
                   moves: list[dict]) -> tuple[list, list, list]:
    """Boucle de déplacement PARTAGÉE (CLI apply / confirmation interactive J4/J4bis).
    Revalide les préconditions de CHAQUE déplacement puis UID MOVE ; résultat
    INCONNU sur erreur IMAP (le move a pu aboutir côté serveur) → jamais de
    retry direct (reconcile obligatoire). J4bis (§12.3) : payload["treat"] = clôture
    workflow — fetch Message-ID source avant move, STORE \\Seen sur la destination
    APRÈS réconciliation identité ; échec du \\Seen = uncertain (jamais aveugle)."""
    done, failed, uncertain = [], [], []
    for move in moves:
        reason = _revalidate_preconditions(cfg, conn, move)
        if reason:
            failed.append({"uid": move["uid"], "reason": reason})
            state.set_move_result(plan_id, move["uid"], "failed", reason)
            continue
        try:
            if payload.get("treat") and not move.get("message_id"):
                mid = _fetch_message_id(conn, move)
                if mid:
                    move = dict(move, message_id=mid)
            imap_mod.uid_move(conn, move["uid"], move["to_folder"], payload["mailbox"])
            state.set_move_result(plan_id, move["uid"], "done")
            state.mark_processed(
                move["from_folder"], payload["uidvalidity"], move["uid"],
                payload["created_at"], "move", move["to_folder"], _now_iso())
            if payload.get("treat") and not _store_seen_on_destination(conn, move):
                # move confirmé mais \\Seen non appliqué → uncertain réconciliable
                state.set_move_result(plan_id, move["uid"], "uncertain", "seen_failed")
                uncertain.append({"uid": move["uid"], "reason": "seen_failed"})
                continue
            done.append({"uid": move["uid"], "to_hash": policy.pseudonymize(move["to_folder"])})
        except imap_mod.ImapError as exc:
            # résultat INCONNU : le move a pu aboutir côté serveur → jamais de retry direct
            state.set_move_result(plan_id, move["uid"], "uncertain", str(type(exc).__name__))
            uncertain.append({"uid": move["uid"]})
    return done, failed, uncertain


def _run_plan_checked(cfg: dict, state, config_dir_path: Path, plan: dict, payload: dict,
                      remaining: list[dict]) -> dict:
    """Exécution SOUS VERROU d'un plan déjà validé par l'appelant (état, expiry,
    intégrité, --confirm-apply). Utilisé par cmd_apply ET run_plan_apply (J4)."""
    lock_path = config_dir_path / "locks" / "apply.lock"
    config_mod.ensure_private_dir(lock_path.parent)
    with state_mod.FileLock(lock_path):
        conn = _connect_imap(cfg)
        try:
            imap_mod.ensure_move_capability(conn)
            current_uidvalidity = _uidvalidity(conn, payload["mailbox"])
            if current_uidvalidity != payload["uidvalidity"]:
                state.set_plan_status(plan["id"], "invalidated")
                return {"status": "uidvalidity_changed"}
            done, failed, uncertain = _execute_moves(
                cfg, conn, state, plan["id"], payload, remaining)
        finally:
            imap_mod.logout(conn)

    all_results = state.get_move_results(plan["id"])
    still_uncertain = [r for r in all_results if r["status"] == "uncertain"]
    if not still_uncertain and not failed:
        state.set_plan_status(plan["id"], "applied")
        final_status = "applied"
    else:
        final_status = "uncertain" if still_uncertain else "partial"

    audit(config_dir_path, {
        "event": "apply", "plan_id": plan["id"], "done": len(done),
        "failed": len(failed), "uncertain": len(uncertain),
    })
    return {"status": final_status, "done": done, "failed": failed, "uncertain": uncertain}


def run_plan_apply(cfg: dict, state, config_dir_path: Path, plan_id: str) -> dict:
    """Cœur d'exécution d'un plan pour le canal interactif (J4, §11.8) : mêmes
    revalidations que la CLI (état, expiration, intégrité, garde reconcile)
    sans les flags CLI. Retourne {status: applied|partial|uncertain|…, ...}."""
    plan = state.get_plan(plan_id)
    if plan is None:
        return {"status": "plan_not_found"}
    if plan["status"] == "applied":
        return {"status": "plan_already_applied"}
    if plan["status"] not in ("open", "uncertain"):
        return {"status": "plan_invalid_state", "plan_state": plan["status"]}
    now = datetime.now(timezone.utc)
    if plan["expires_at"] and datetime.fromisoformat(plan["expires_at"]) < now:
        state.set_plan_status(plan["id"], "expired")
        return {"status": "plan_expired", "expires_at": plan["expires_at"]}
    payload = plan["payload"]
    if state_mod.plan_sha256(payload) != plan["sha256"]:
        state.set_plan_status(plan["id"], "invalidated")
        return {"status": "plan_integrity"}
    previous_results = state.get_move_results(plan["id"])
    if any(r["status"] == "uncertain" for r in previous_results):
        return {"status": "reconcile_required", "plan_id": plan["id"]}
    remaining = [m for m in payload["moves"]
                 if m["uid"] not in {r["uid"] for r in previous_results if r["status"] == "done"}]
    return _run_plan_checked(cfg, state, config_dir_path, plan, payload, remaining)


def cmd_apply(cfg: dict, args) -> int:
    writes = cfg["writes"]
    if not writes["enabled"] or not writes["imap_enabled"]:
        return _err("writes_disabled", "kill switch (writes.enabled/imap_enabled=false) — aucune mutation")

    config_dir_path = config_mod.config_dir(cfg.get("_config_dir"))
    state = state_mod.State(config_dir_path / "state.sqlite")
    plan = state.get_plan(args.plan)
    if plan is None:
        return _err("plan_not_found", f"plan inconnu: {args.plan}")
    if plan["status"] == "applied":
        return _err("plan_already_applied", f"plan déjà appliqué: {args.plan}", **{"plan_id": args.plan})
    if plan["status"] not in ("open", "uncertain"):
        return _err("plan_invalid_state", f"plan en état {plan['status']} — non applicable")

    now = datetime.now(timezone.utc)
    if plan["expires_at"] and datetime.fromisoformat(plan["expires_at"]) < now:
        state.set_plan_status(plan["id"], "expired")
        return _err("plan_expired", f"plan expiré ({plan['expires_at']}) — refaire un plan")

    payload = plan["payload"]
    sha = state_mod.plan_sha256(payload)
    if sha != plan["sha256"]:
        state.set_plan_status(plan["id"], "invalidated")
        return _err("plan_integrity", "empreinte du plan divergente — invalidé, refaire un plan")

    if not args.confirm_apply:
        return _err("confirm_required", "apply exige --confirm-apply (garde d'exécution)")

    previous_results = state.get_move_results(plan["id"])
    uncertain_uids = {r["uid"] for r in previous_results if r["status"] == "uncertain"}
    if uncertain_uids:
        # Invariant 5 : reconcile OBLIGATOIRE avant toute nouvelle tentative après timeout.
        return _err("reconcile_required",
                    "déplacements incertains présents — lancer 'reconcile --plan "
                    + plan["id"] + "' avant toute nouvelle tentative",
                    plan_id=plan["id"])
    remaining = [m for m in payload["moves"]
                 if m["uid"] not in {r["uid"] for r in previous_results if r["status"] == "done"}]

    outcome = _run_plan_checked(cfg, state, config_dir_path, plan, payload, remaining)
    if outcome["status"] == "uidvalidity_changed":
        return _err("uidvalidity_changed",
                    "UIDVALIDITY a changé depuis le plan — invalidated, refaire un plan")
    done, failed, uncertain = outcome["done"], outcome["failed"], outcome["uncertain"]
    final_status = outcome["status"]

    all_results = state.get_move_results(plan["id"])
    still_uncertain = [r for r in all_results if r["status"] == "uncertain"]
    return _out({
        "command": "apply",
        "plan_id": plan["id"],
        "status": final_status,
        "done": done,
        "failed": failed,
        "uncertain": uncertain,
        "results": all_results,
        "note": ("déplacements incertains présents — lancer 'reconcile --plan "
                 + plan["id"] + "' avant toute nouvelle tentative"),
    }, exit_code=1 if (still_uncertain or failed) else 0)


def cmd_status(cfg: dict) -> int:
    config_dir_path = config_mod.config_dir(cfg.get("_config_dir"))
    state = state_mod.State(config_dir_path / "state.sqlite")
    last_digest = state.last_confirmed_digest()
    return _out({
        "command": "status",
        "writes": {k: cfg["writes"][k] for k in ("enabled", "imap_enabled", "digest_enabled")},
        "digest_enabled_config": cfg.get("digest", {}).get("enabled", False),
        "allowlist_size": len(cfg["destinations"]["allowlist"]),
        "rules_count": len(cfg.get("rules", {}).get("rules", [])),
        "last_confirmed_digest": last_digest,
        "secrets_present": {
            "imap_password": bool(os.environ.get(cfg["account"]["password_env"])
                                  or config_mod._read_env_file(config_mod.DEFAULT_ENV_FILE).get(
                                      cfg["account"]["password_env"])),
            "kchat_token": bool(os.environ.get(cfg["kchat"]["token_env"])
                                or config_mod._read_env_file(config_mod.DEFAULT_ENV_FILE).get(
                                    cfg["kchat"]["token_env"])),
        },
    })


def _escape_imap_string(value: str) -> str:
    """Échappe \\ et \" pour un IMAP quoted-string — les en-têtes sont non fiables.
    Review F-01 : tout octet de contrôle (CR/LF, < 0x20) est SUPPRIMÉ en amont —
    imaplib (3.9.6 LIVE vérifié) n'assume aucune validation : jamais d'injection
    de commande IMAP via une valeur d'en-tête."""
    cleaned = "".join(c for c in (value or "") if 0x20 <= ord(c) <= 0x7E)
    return cleaned.replace("\\", "\\\\").replace('"', '\\"')


# J4bis (§12.4) : cap des refs renvoyées par dossier (read-only, inspection).
WORKFLOW_REF_CAP = 20


def _workflow_folder_state(conn, name: str) -> dict:
    """État read-only d'un dossier workflow : total, non lus, refs non lus (cap).
    Aucune mutation, aucune reclassification ; dossier absent = exists:false."""
    import re as _re
    if not imap_mod.mailbox_exists(conn, name):
        return {"exists": False}
    quoted = imap_mod.quote_mailbox(name)
    typ, data = conn.status(quoted, "(UIDVALIDITY MESSAGES UNSEEN)")
    if typ != "OK" or not data or not data[0]:
        raise imap_mod.ImapError(f"STATUS illisible pour {name!r}")
    raw = data[0] if isinstance(data[0], bytes) else str(data[0]).encode()
    m_uv = _re.search(rb"UIDVALIDITY (\d+)", raw)
    m_total = _re.search(rb"MESSAGES (\d+)", raw)
    m_unseen = _re.search(rb"UNSEEN (\d+)", raw)
    refs: list[dict] = []
    # UID SEARCH exige une mailbox sélectionnée (SELECT readonly, aucune mutation).
    imap_mod.select_mailbox(conn, name, readonly=True)
    typ2, data2 = conn.uid("search", None, "UNSEEN")
    if typ2 == "OK" and data2 and data2[0]:
        uids = data2[0].split()
        uv = int(m_uv.group(1)) if m_uv else None
        for uid_bytes in uids[:WORKFLOW_REF_CAP]:
            refs.append({"mailbox": name, "uidvalidity": uv, "uid": int(uid_bytes)})
    return {
        "exists": True,
        "uidvalidity": int(m_uv.group(1)) if m_uv else None,
        "total": int(m_total.group(1)) if m_total else None,
        "unseen": int(m_unseen.group(1)) if m_unseen else None,
        "unseen_refs": refs,
        "refs_truncated": len(refs) == WORKFLOW_REF_CAP,
    }


def cmd_workflow(cfg: dict, args) -> int:
    """État du workflow (J4bis, §12.4) : read-only STRICT — comptages « A lire » /
    « A traiter » / INBOX + refs (mailbox, uidvalidity, uid) des non lus.
    Zéro reclassification, zéro mutation IMAP ; les 20 dossiers historiques de
    stockage ne sont JAMAIS re-scanés ici (D1/D7). --sync : maintien de l'état
    persistant (new→ref #wN active, absents→resolved — D6 zéro re-proposition)."""
    sync_requested = bool(getattr(args, "sync", False))
    config_dir_path = config_mod.config_dir(cfg.get("_config_dir"))
    state = state_mod.State(config_dir_path / "state.sqlite")
    conn = _connect_imap(cfg)
    try:
        folders = {
            "A lire": _workflow_folder_state(conn, "A lire"),
            "A traiter": _workflow_folder_state(conn, "A traiter"),
            cfg["source"]["mailbox"]: _workflow_folder_state(conn, cfg["source"]["mailbox"]),
        }
        sync_result = _sync_workflow_items(conn, state, cfg) if sync_requested else None
    finally:
        imap_mod.logout(conn)
    out = {
        "command": "workflow",
        "folders": folders,
        "note": ("read-only — statut de traitement ≠ classement ≠ \\Seen (§12.2) ; "
                 "refs = dossier source + uidvalidity + uid, cap "
                 + str(WORKFLOW_REF_CAP) + "/dossier"),
    }
    if sync_result is not None:
        out["sync"] = sync_result
    return _out(out)


# J4bis : cap de la sync par dossier (les dossiers workflow sont courts par
# conception — au-delà : le plus ancien n'est PAS suivi, jamais de boucle infinie).
WORKFLOW_SYNC_CAP = 300
WORKFLOW_REF_TTL_HOURS = 48


def _dispatch_read_items(conn, state, cfg: dict, now_iso: str) -> int:
    """J4bis (décision utilisateur 2026-10-26) : dans « A lire », un message LU
    (\\Seen posé par la lecture humaine) est dispatché vers le stockage final
    déterminé par sa règle (`folder` — jamais implicite). « A traiter » n'est
    PAS concerné (la lecture n'y suffit pas — une action est attendue).
    Garde-fous : items pending/uncertain jamais dispatchés ; destination
    revalidée (règle courante + allowlist, fail-closed PolicyError → skip) ;
    erreur IMAP → uncertain réconciliable (jamais re-dispatché auto) ;
    \\Seen JAMAIS écrit ici (déjà posé par la lecture humaine) ; items hors
    cap de scan attendent (pas de dispatch partiel)."""
    folder_a_lire = config_mod.WORKFLOW_FOLDERS[0]
    items = [i for i in state.workflow_items_by_state(["new"])
             if i["mailbox"] == folder_a_lire]
    if not items:
        return 0
    uv = _uidvalidity(conn, folder_a_lire)
    headers = {h["uid"]: h for h in imap_mod.fetch_recent_headers(
        conn, folder_a_lire, limit=WORKFLOW_SYNC_CAP)}
    dispatched = 0
    for item in items:
        h = headers.get(item["uid"])
        if h is None or not h.get("seen", False):
            continue  # non lu (ou hors cap) : il attend sa lecture
        try:
            decision = policy.evaluate(h, cfg["rules"],
                                       cfg["destinations"]["allowlist"], cfg)
        except policy.PolicyError:
            continue  # fail-closed : jamais de destination invalide
        dest = decision.get("final_folder")
        if decision.get("action") != "move" or not dest or dest == folder_a_lire:
            continue  # pas de stockage déterminé par règle : reste dans « A lire »
        try:
            imap_mod.uid_move(conn, item["uid"], dest, folder_a_lire)
        except imap_mod.ImapError:
            state.set_workflow_item_state(item["mailbox"], item["uidvalidity"],
                                          item["uid"], "uncertain", now_iso)
            continue  # réconciliable, jamais re-dispatché automatiquement
        state.mark_processed(item["mailbox"], item["uidvalidity"], item["uid"],
                             now_iso, "move", dest, now_iso)
        state.set_workflow_item_state(item["mailbox"], item["uidvalidity"],
                                      item["uid"], "resolved", now_iso)
        dispatched += 1
    return dispatched


def _sync_workflow_items(conn, state, cfg: dict) -> dict:
    """Maintien de l'état workflow (read-only IMAP) :
    1. scan ALL des dossiers workflow (cap 300/dossier) → upsert (new si inconnu) ;
    2. items new/pending absents du scan → resolved (D6 : jamais re-proposés) ;
       Review F-04 : si STATUS MESSAGES > cap, le scan est PARTIEL → résolution
       GELÉE pour ce dossier (fail-closed, jamais un faux 'resolved') ;
    3. items new/pending SANS ref active → allocation ref #wN (48 h, compteur
       partagé) — Review F-03 : pending SANS ref active est re-actionnable
       (cul-de-sac supprimé). Allocation APRÈS la résolution uniquement."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    present: set = set()
    rows = []
    frozen_mailboxes: set[str] = set()
    for name in config_mod.WORKFLOW_FOLDERS:
        uv = _uidvalidity(conn, name)
        total = _mailbox_message_count(conn, name)
        headers = imap_mod.fetch_recent_headers(conn, name, limit=WORKFLOW_SYNC_CAP)
        if total is not None and total > WORKFLOW_SYNC_CAP:
            frozen_mailboxes.add(name)  # scan partiel → résolution gelée (F-04)
        for h in headers:
            key = (name, uv, h["uid"])
            present.add(key)
            rows.append({"mailbox": name, "uidvalidity": uv, "uid": h["uid"],
                         "from_addr": h.get("from") or "", "subject": h.get("subject") or ""})
    state.upsert_workflow_items(rows, now_iso)
    resolved = state.resolve_workflow_items(present, frozen_mailboxes, now_iso)
    dispatched = _dispatch_read_items(conn, state, cfg, now_iso)
    expires_at = (now + timedelta(hours=WORKFLOW_REF_TTL_HOURS)).isoformat(timespec="seconds")
    refs_new = 0
    for item in state.workflow_items_by_state(["new", "pending"]):
        key = (item["mailbox"], item["uidvalidity"], item["uid"])
        if key not in present:
            continue  # résolu ou hors cap — jamais de ref pour un item absent
        if state.active_ref_for_key(item["mailbox"], item["uidvalidity"],
                                    item["uid"], now_iso):
            continue  # ref active existante : zéro doublon
        ref_number = state.next_ref_number("w")
        ref = f"w{ref_number}"
        state.store_digest_refs([{
            "digest_id": "workflow", "ref": ref, "mailbox": item["mailbox"],
            "uidvalidity": item["uidvalidity"], "uid": item["uid"],
            "from_addr": item["from_addr"], "subject": item["subject"],
            "kind": "workflow", "created_at": now_iso, "expires_at": expires_at,
        }])
        refs_new += 1
    return {"new_refs": refs_new, "resolved": resolved, "present": len(present),
            "frozen": sorted(frozen_mailboxes), "dispatched": dispatched}


def _mailbox_message_count(conn, name: str) -> int | None:
    """Total MESSAGES d'un dossier via STATUS (Review F-04 : détection scan partiel)."""
    import re as _re
    try:
        typ, data = conn.status(imap_mod.quote_mailbox(name), "(MESSAGES)")
    except Exception:
        return None
    if typ != "OK" or not data or not data[0]:
        return None
    m = _re.search(rb"MESSAGES (\d+)", data[0])
    return int(m.group(1)) if m else None


def cmd_reconcile(cfg: dict, args) -> int:
    config_dir_path = config_mod.config_dir(cfg.get("_config_dir"))
    state = state_mod.State(config_dir_path / "state.sqlite")

    if args.digest:
        return _reconcile_digest(cfg, state, config_dir_path)

    if not args.plan:
        return _err("usage", "reconcile exige --plan <id> et/ou --digest", exit_code=2)

    plan = state.get_plan(args.plan)
    if plan is None:
        return _err("plan_not_found", f"plan inconnu: {args.plan}")
    results = state.get_move_results(plan["id"])
    uncertain = [r for r in results if r["status"] == "uncertain"]
    if not uncertain:
        return _out({"command": "reconcile", "plan_id": plan["id"],
                     "uncertain": [], "message": "aucun déplacement incertain"})

    payload = plan["payload"]
    moves_by_uid = {m["uid"]: m for m in payload["moves"]}
    outcomes = []
    # Le reconcile écrit dans l'état : même verrou que l'apply (anti-entrelacement).
    lock_path = config_dir_path / "locks" / "apply.lock"
    config_mod.ensure_private_dir(lock_path.parent)
    with state_mod.FileLock(lock_path):
        conn = _connect_imap(cfg)
        try:
            for item in uncertain:
                uid = item["uid"]
                move = moves_by_uid.get(uid, {})
                # Le message est-il encore dans la source ?
                imap_mod.select_mailbox(conn, payload["mailbox"], readonly=True)
                typ, data = conn.uid("search", None, f"UID {uid}")
                still_source = bool(typ == "OK" and data and data[0] and data[0].split())
                moved_confirmed = False
                if not still_source:
                    # UID destination ≠ UID source : confirmation par Message-ID (identifiant stable)
                    mid = (move.get("message_id") or "").strip()
                    dest = move.get("to_folder")
                    if mid and dest:
                        try:
                            imap_mod.select_mailbox(conn, dest, readonly=True)
                            typ, data = conn.uid(
                                "search", None, f'HEADER Message-ID "{_escape_imap_string(mid)}"')
                            moved_confirmed = bool(typ == "OK" and data and data[0] and data[0].split())
                        except imap_mod.ImapError:
                            moved_confirmed = False
                if still_source:
                    status, detail = "not_executed", "message encore dans la source — re-apply possible"
                    state.set_move_result(plan["id"], uid, "not_executed", detail)
                elif moved_confirmed:
                    status, detail = "done", "confirmé dans la destination (Message-ID)"
                    state.set_move_result(plan["id"], uid, "done", detail)
                else:
                    status, detail = "moved_assumed", (
                        "absent de la source (déplacé ou traité manuellement) — jamais de repost ; vérifier le webmail")
                    state.set_move_result(plan["id"], uid, "done", detail)
                outcomes.append({"uid": uid, "status": status, "detail": detail})
        finally:
            imap_mod.logout(conn)

    remaining_uncertain = [r for r in state.get_move_results(plan["id"]) if r["status"] == "uncertain"]
    state.set_plan_status(plan["id"], "applied" if not remaining_uncertain else "partial")
    audit(config_dir_path, {"event": "reconcile_plan", "plan_id": plan["id"], "outcomes": len(outcomes)})
    return _out({"command": "reconcile", "plan_id": plan["id"], "outcomes": outcomes})


def _reconcile_digest(cfg: dict, state, config_dir_path: Path) -> int:
    if not cfg["writes"]["enabled"] or not cfg["writes"]["digest_enabled"]:
        return _err("writes_disabled", "kill switch digest — aucune publication")
    # Même verrou que digest --send (anti-doublon de repost concurrent).
    lock_path = config_dir_path / "locks" / "digest.lock"
    config_mod.ensure_private_dir(lock_path.parent)
    with state_mod.FileLock(lock_path):
        return _reconcile_digest_locked(cfg, state)


def _reconcile_digest_locked(cfg: dict, state) -> int:
    uncertain = state.uncertain_digests()
    if not uncertain:
        return _out({"command": "reconcile", "digest": True, "uncertain": [],
                     "message": "aucune publication incertaine"})

    client = _kchat_client(cfg)
    bot_id = client.me().get("id")
    if not bot_id:
        return _err("kchat_identity", "identité du bot kChat illisible")
    dm_channel = client.ensure_direct_channel(bot_id, _recipient_id(cfg, client))

    outcomes = []
    for item in uncertain:
        stored = state.get_digest(item["id"])
        found = client.find_marker_in_channel(dm_channel, item["marker"])
        if found:
            state.set_digest_state(item["id"], "sent", post_id=found, resolved_at=_now_iso())
            _mark_digest_msgs(state, cfg, stored)
            outcomes.append({"digest_id": item["id"], "status": "confirmed_existing", "post_id": found})
            continue
        # Marqueur absent = publication réellement non parvenue → repost autorisé (pas aveugle)
        if not stored:
            outcomes.append({"digest_id": item["id"], "status": "missing_state"})
            continue
        markdown = stored.get("markdown")
        if not markdown:
            # Contenu non stocké : on n'invente rien — invalidé ; les messages
            # repartiront dans le prochain digest (jamais marqués digestés ici).
            state.set_digest_state(item["id"], "invalidated", resolved_at=_now_iso())
            outcomes.append({"digest_id": item["id"], "status": "invalidated_no_content"})
            continue
        post = client.post_message(dm_channel, markdown)
        state.set_digest_state(item["id"], "sent", post_id=post.get("id"), resolved_at=_now_iso())
        _mark_digest_msgs(state, cfg, stored)
        outcomes.append({"digest_id": item["id"], "status": "reposted", "post_id": post.get("id")})

    return _out({"command": "reconcile", "digest": True, "outcomes": outcomes})


def _mark_digest_msgs(state, cfg: dict, stored: dict | None) -> None:
    """Marque les messages couverts par un digest confirmé (reconcile) — anti-doublon."""
    if not stored or not stored.get("msg_uids"):
        return
    mailbox = cfg["source"]["mailbox"]
    uidvalidity = stored.get("uidvalidity") or 0
    for uid_text in str(stored["msg_uids"]).split(","):
        uid_text = uid_text.strip()
        if uid_text.isdigit():
            state.mark_digest_msg(mailbox, int(uidvalidity), int(uid_text), None, stored["id"])


def _kchat_client(cfg: dict) -> kchat_mod.KChatClient:
    kc = cfg["kchat"]
    token = config_mod.get_secret(kc["token_env"])
    return kchat_mod.KChatClient(kc["base_url"], token, int(kc.get("timeout_seconds", 15)))


def _recipient_id(cfg: dict, client: kchat_mod.KChatClient) -> str:
    kc = cfg["kchat"]
    username = config_mod.get_secret(kc["dm_username_env"])
    user = client.user_by_username(username)
    user_id = user.get("id")
    if not user_id:
        raise kchat_mod.KChatError(0, "/users/username", "destinataire introuvable")
    return user_id


def cmd_digest(cfg: dict, args) -> int:
    if not cfg.get("digest", {}).get("enabled", False):
        return _err("digest_disabled", "digest.enabled=false dans config.json", exit_code=2)
    if args.send and (not cfg["writes"]["enabled"] or not cfg["writes"]["digest_enabled"]):
        # Kill switch vérifié AVANT toute connexion IMAP (invariant 9).
        return _err("writes_disabled", "kill switch (writes.enabled/digest_enabled=false) — aucune publication")
    config_dir_path = config_mod.config_dir(cfg.get("_config_dir"))
    state = state_mod.State(config_dir_path / "state.sqlite")
    now = datetime.now(timezone.utc)

    window = digest_mod.compute_window(state, cfg, now)
    digest_id = digest_mod.new_digest_id()
    marker = digest_mod.new_marker(digest_id)

    conn = _connect_imap(cfg)
    try:
        uidvalidity = _uidvalidity(conn, cfg["source"]["mailbox"])
        messages = _fetch_recent(cfg, conn, state, uidvalidity)
        built = digest_mod.build_digest(state, messages, cfg, window, digest_id,
                                        mailbox=cfg["source"]["mailbox"], uidvalidity=uidvalidity)

        # V4.1 (opt-in digest.enrichment.enabled, ARCHITECTURE §10) : aperçus bornés.
        # Gated off → enrich_previews ne fait AUCUN fetch. Sensibles jamais ciblés.
        def _fetch_preview(uid: int, max_bytes: int):
            return imap_mod.fetch_body_preview(conn, uid, max_bytes)

        previews = digest_mod.enrich_previews(built, cfg, _fetch_preview)
    finally:
        imap_mod.logout(conn)
    digest_mod.attach_previews(built, previews)
    # Références courtes (V4, §11.5 corrigé t10) : GLOBALEMENT non ambiguës —
    # compteur monotone de l'état, assignées AVANT rendu et persistance.
    digest_mod.assign_refs(built, state)
    markdown = digest_mod.render_markdown(built)

    if not args.send:
        return _out({
            "command": "digest",
            "digest_id": digest_id,
            "send": False,
            "format_version": built["format_version"],
            "window": {"start": built["window_start"], "end": built["window_end"]},
            "counters": built["counters"],
            "new_count": len(built["new"]),
            "always_inbox_count": len(built["always_inbox"]),
            "moved_counts": built["moved_counts"],
            "markdown": markdown,
            "notice": "sortie lisible (inspection volontaire) — ne pas journaliser",
        })

    min_interval = int(cfg.get("digest", {}).get("min_interval_hours", 20))
    lock_path = config_dir_path / "locks" / "digest.lock"
    config_mod.ensure_private_dir(lock_path.parent)
    with state_mod.FileLock(lock_path):
        # Garde min_interval RE-VÉRIFIÉE dans le lock : deux runs chevauchés
        # (launchd + RunAtLoad) ne doivent poster qu'un seul digest.
        last = state.last_confirmed_digest()
        if last and last.get("resolved_at") and not args.force:
            last_dt = datetime.fromisoformat(last["resolved_at"])
            if now - last_dt < timedelta(hours=min_interval):
                return _out({"command": "digest", "digest_id": digest_id, "send": True,
                             "skipped": "already_sent",
                             "last_confirmed_at": last["resolved_at"],
                             "message": (f"dernier digest confirmé il y a moins de {min_interval} h "
                                         f"— utiliser --force pour outrepasser")})
        state.create_digest(digest_id, built["window_start"], built["window_end"], marker,
                            _now_iso(), uidvalidity=uidvalidity, markdown=markdown,
                            msg_uids=",".join(str(m["uid"]) for m in built["new"]))
        # Références courtes (V4, §11.5) : persistées à la PUBLICATION (digest
        # confirmé), expiration 48 h — résolues par le canal interactif (J3).
        ref_rows = digest_mod.digest_ref_rows(built, cfg["source"]["mailbox"],
                                              uidvalidity, _now_iso())
        if ref_rows:
            state.store_digest_refs(ref_rows)
        try:
            client = _kchat_client(cfg)
            bot_id = client.me().get("id")
            if not bot_id:
                raise kchat_mod.KChatError(0, "/users/me", "identité bot illisible")
            dm_channel = client.ensure_direct_channel(bot_id, _recipient_id(cfg, client))
            post = client.post_message(dm_channel, markdown)
            state.set_digest_state(digest_id, "sent", post_id=post.get("id"), resolved_at=_now_iso())
        except kchat_mod.KChatError as exc:
            state.set_digest_state(digest_id, "uncertain", resolved_at=_now_iso())
            audit(config_dir_path, {"event": "digest_uncertain", "digest_id": digest_id,
                                    "kchat_status": exc.status})
            return _err("digest_uncertain",
                        f"publication kChat en état inconnu: {exc} — lancer 'reconcile --digest'",
                        digest_id=digest_id)
        except Exception as exc:  # SecretError, sqlite, interruption : pending orphelin → uncertain
            state.set_digest_state(digest_id, "uncertain", resolved_at=_now_iso())
            audit(config_dir_path, {"event": "digest_uncertain", "digest_id": digest_id,
                                    "kchat_status": 0})
            return _err("digest_uncertain",
                        f"publication en état inconnu ({type(exc).__name__}) — lancer 'reconcile --digest'",
                        digest_id=digest_id)

    for msg in built["new"]:
        state.mark_digest_msg(cfg["source"]["mailbox"], uidvalidity, msg["uid"],
                              msg.get("internaldate"), digest_id)

    audit(config_dir_path, {
        "event": "digest_sent", "digest_id": digest_id,
        "new": len(built["new"]), "always_inbox": len(built["always_inbox"]),
    })
    return _out({
        "command": "digest",
        "digest_id": digest_id,
        "send": True,
        "status": "sent",
        "window": {"start": built["window_start"], "end": built["window_end"]},
        "new_count": len(built["new"]),
        "always_inbox_count": len(built["always_inbox"]),
    })


def cmd_listen(cfg: dict, args) -> int:
    """Poller interactif (J2 lecture + J3 propositions, ARCHITECTURE §11) :
    traite les MP du propriétaire, répond, avance le checkpoint."""
    interactive = cfg.get("interactive", {})
    if not interactive.get("enabled", False):
        return _err("interactive_disabled", "interactive.enabled=false dans config.json", exit_code=2)
    config_dir_path = config_mod.config_dir(cfg.get("_config_dir"))
    state = state_mod.State(config_dir_path / "state.sqlite")
    client = _kchat_client(cfg)
    owner_user_id = _recipient_id(cfg, client)
    try:
        result = interact_mod.run_once(cfg, state, config_dir_path, client, owner_user_id, audit)
    except state_mod.LockError:
        # J5/t10 : un tour précédent > 300 s tient encore le verrou → skip PROPRE
        # (exit 0, checkpoint intact) ; la pagination exhaustive rattrapera.
        audit(config_dir_path, {"event": "interactive_skipped_locked"})
        return _out({"command": "listen", "status": "skipped_locked"})
    except interact_mod.InteractiveError as exc:
        # F-04 (review J3) : pagination incomplète > 20 pages — fail-closed
        # voulu (checkpoint gelé), mais signal dédié + audit exploitable
        # (reprise opérateur : traiter le DM ou réinitialiser le checkpoint).
        audit(config_dir_path, {"event": "interactive_pagination_incomplete",
                                "detail": str(exc)[:200]})
        return _err("interactive_pagination_incomplete",
                    f"{exc} — reprise opérateur requise (voir ARCHITECTURE §11.3)")
    return _out({"command": "listen", **result})


# --- entrée -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triage", description="Moteur mail-triage (JSON, exit 0/1/2)")
    parser.add_argument("--config-dir", default=None, help="répertoire privé (défaut ~/.config/opencode/mail-triage)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="lecture seule : dossiers + messages + évaluation règles")

    p_plan = sub.add_parser("plan", help="construit un plan de déplacements (dry-run)")

    p_apply = sub.add_parser("apply", help="exécute un plan validé")
    p_apply.add_argument("--plan", required=True)
    p_apply.add_argument("--confirm-apply", action="store_true")

    sub.add_parser("status", help="état du moteur")

    p_wf = sub.add_parser("workflow", help="état du workflow A lire/A traiter/INBOX (read-only, J4bis)")
    p_wf.add_argument("--sync", action="store_true",
                      help="maintien de l'état workflow persistant (new→ref #wN, absents→resolved)")

    p_rec = sub.add_parser("reconcile", help="réparation après interruption")
    p_rec.add_argument("--plan", default=None)
    p_rec.add_argument("--digest", action="store_true")

    p_dig = sub.add_parser("digest", help="résumé kChat du matin")
    p_dig.add_argument("--send", action="store_true")
    p_dig.add_argument("--force", action="store_true")

    p_lis = sub.add_parser("listen", help="canal interactif MP kChat (J2 : lecture seule)")
    p_lis.add_argument("--once", action="store_true",
                       help="un seul tour du poller (mode manuel J2 ; launchd à venir en J5)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config_dir_path = config_mod.config_dir(args.config_dir)
        cfg = config_mod.load(config_dir_path)
        cfg["_config_dir"] = str(config_dir_path)
    except (config_mod.ConfigError, config_mod.SecretError) as exc:
        return _err("config", str(exc), exit_code=2)

    handlers = {
        "scan": lambda: cmd_scan(cfg),
        "plan": lambda: cmd_plan(cfg, args),
        "apply": lambda: cmd_apply(cfg, args),
        "status": lambda: cmd_status(cfg),
        "workflow": lambda: cmd_workflow(cfg, args),
        "reconcile": lambda: cmd_reconcile(cfg, args),
        "digest": lambda: cmd_digest(cfg, args),
        "listen": lambda: cmd_listen(cfg, args),
    }
    try:
        return handlers[args.command]()
    except config_mod.SecretError as exc:
        return _err("secret", str(exc))
    except policy.PolicyError as exc:
        audit(config_mod.config_dir(cfg.get("_config_dir")), {"event": "policy_error", "detail": str(exc)[:200]})
        return _err("policy", str(exc))
    except imap_mod.ImapError as exc:
        return _err("imap", str(exc))
    except imaplib.IMAP4.error as exc:
        # erreurs protocole brut (BAD/NO) hors ImapError : JSON garanti quand même
        return _err("imap", f"protocole IMAP: {exc}")
    except kchat_mod.KChatError as exc:
        return _err("kchat", str(exc))
    except state_mod.LockError as exc:
        return _err("lock", str(exc))
    except sqlite3.Error as exc:
        return _err("state", f"état local illisible ou verrouillé: {exc}")
    except KeyboardInterrupt:  # pragma: no cover
        return _err("interrupted", "interrompu", exit_code=1)
    except Exception as exc:  # dernier recours : jamais de traceback hors contrat JSON
        return _err("internal", f"{type(exc).__name__}: {str(exc)[:200]}")


if __name__ == "__main__":
    sys.exit(main())
