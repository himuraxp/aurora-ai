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
        return int(conn.status(mailbox, "(UIDVALIDITY)")[1][0].decode().split("UIDVALIDITY ")[1].rstrip(")]"))
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
    """Revalidation avant CHAQUE déplacement. Retourne une raison de refus ou None."""
    if not policy.destination_is_allowed(move["to_folder"], cfg["destinations"]["allowlist"]):
        return "destination hors allowlist (config changée ?)"
    if not imap_mod.mailbox_exists(conn, move["to_folder"]):
        return "destination absente sur le serveur (jamais de création)"
    if not imap_mod.mailbox_exists(conn, cfg["source"]["mailbox"]):
        return "source absente"
    return None


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

    lock_path = config_dir_path / "locks" / "apply.lock"
    config_mod.ensure_private_dir(lock_path.parent)
    with state_mod.FileLock(lock_path):
        conn = _connect_imap(cfg)
        try:
            imap_mod.ensure_move_capability(conn)
            current_uidvalidity = _uidvalidity(conn, payload["mailbox"])
            if current_uidvalidity != payload["uidvalidity"]:
                state.set_plan_status(plan["id"], "invalidated")
                return _err("uidvalidity_changed",
                            "UIDVALIDITY a changé depuis le plan — invalidated, refaire un plan")

            done, failed, uncertain = [], [], []
            for move in remaining:
                reason = _revalidate_preconditions(cfg, conn, move)
                if reason:
                    failed.append({"uid": move["uid"], "reason": reason})
                    state.set_move_result(plan["id"], move["uid"], "failed", reason)
                    continue
                try:
                    imap_mod.uid_move(conn, move["uid"], move["to_folder"], payload["mailbox"])
                    state.set_move_result(plan["id"], move["uid"], "done")
                    state.mark_processed(
                        move["from_folder"], payload["uidvalidity"], move["uid"],
                        payload["created_at"], "move", move["to_folder"], _now_iso())
                    done.append({"uid": move["uid"], "to_hash": policy.pseudonymize(move["to_folder"])})
                except imap_mod.ImapError as exc:
                    # résultat INCONNU : le move a pu aboutir côté serveur → jamais de retry direct
                    state.set_move_result(plan["id"], move["uid"], "uncertain", str(type(exc).__name__))
                    uncertain.append({"uid": move["uid"]})
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
    """Échappe \\ et \" pour un IMAP quoted-string — les en-têtes sont non fiables."""
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


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
    finally:
        imap_mod.logout(conn)

    built = digest_mod.build_digest(state, messages, cfg, window, digest_id,
                                    mailbox=cfg["source"]["mailbox"], uidvalidity=uidvalidity)
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

    p_rec = sub.add_parser("reconcile", help="réparation après interruption")
    p_rec.add_argument("--plan", default=None)
    p_rec.add_argument("--digest", action="store_true")

    p_dig = sub.add_parser("digest", help="résumé kChat du matin")
    p_dig.add_argument("--send", action="store_true")
    p_dig.add_argument("--force", action="store_true")
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
        "reconcile": lambda: cmd_reconcile(cfg, args),
        "digest": lambda: cmd_digest(cfg, args),
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
