#!/usr/bin/env python3
"""Workflow Dashboard — intégration Orca (J3) : pane persistant idempotent.

Ouvre et gère le pane terminal qui héberge le renderer (wd_dashboard.py
--watch) DANS Orca, par worktree. Ce module est la voie d'intégration côté
orchestrateur (pattern tw_orca) : le renderer lui-même reste un lecteur
strict, ce module écrit UNIQUEMENT son propre état de gestion des handles
(workflow-dashboard-panes.json — hors du répertoire progress/ du contrat).

Garanties (consensus t3/t4, critères E2E) :
- IDEMPOTENT : un handle enregistré est réutilisé — `ensure` appelé deux fois
  ne crée jamais deux panes ; `restart` (close + recreate) est explicite.
- PERSISTANCE : l'état des handles survit aux crashs de session (comme
  handoff dans tw_state) — la reprise ne réinitialise rien.
- SAGESSE tw_orca : un `terminal create` réussi n'est PAS la confirmation
  que le renderer tourne ; handle manquant = résultat incertain, jamais un
  succès prétendu.
- ISOLATION : une clé de pane = realpath(worktree) — deux worktrees
  coexistent sans collision.

Le CLI orca est le SEUL mécanisme (aucune API runtime OpenCode) :
  worktree list --json          -> selector <id> du worktree
  terminal create --worktree <sel> --title <t> --command <c> --json [--focus]
  terminal close --terminal <handle>
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Optional

import wd_core
import wd_dashboard

DEFAULT_ORCA_BIN = "orca"
ENV_ORCA_BIN = "WD_ORCA_BIN"
ENV_PANES_STATE = "WD_PANES_STATE_FILE"
DEFAULT_PANES_STATE = os.path.expanduser(
    "~/.config/opencode/workflow-dashboard-panes.json")
DEFAULT_TIMEOUT = 15
DASHBOARD_TITLE = "Workflow Dashboard"
PANES_LOCK_TIMEOUT = 30.0  # create orca peut prendre ~20 s


def _orca_bin() -> str:
    return os.environ.get(ENV_ORCA_BIN) or DEFAULT_ORCA_BIN


def panes_state_path() -> str:
    return os.environ.get(ENV_PANES_STATE) or DEFAULT_PANES_STATE


def read_panes_state() -> Dict[str, Any]:
    """Lecture tolérante : état absent/corrompu => {} (jamais de crash)."""
    try:
        with open(panes_state_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_panes_state(data: Dict[str, Any]) -> None:
    path = panes_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = None
    tmp = None
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix=".wd-orca-", suffix=".tmp",
                                   dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


def pane_key(worktree_path: Optional[str]) -> str:
    """Clé d'isolation : realpath du worktree, ou 'global'."""
    if not worktree_path:
        return "global"
    return os.path.realpath(os.path.expanduser(worktree_path))


def _why_from_output(output: str, rc: int) -> str:
    """Extrait le message d'erreur orca (leçon tw_orca 2026-10-15 : orca
    imprime des erreurs JSON, la dernière ligne seule est inutile)."""
    try:
        data = json.loads(output or "")
        if isinstance(data, dict):
            message = data.get("error") or data.get("message")
            if message:
                return str(message)
    except (ValueError, TypeError):
        pass
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    return lines[-1] if lines else f"rc {rc}"


def _run(args: List[str], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Wrapper CLI orca (pattern tw_orca) : jamais d'exception, why complet."""
    try:
        proc = subprocess.run([_orca_bin(), *args], capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "why": f"orca CLI not found ({_orca_bin()})"}
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "why": f"orca {' '.join(args[:2])} timed out after {timeout}s"}
    except OSError as exc:
        return {"ok": False, "why": f"orca spawn failed: {exc}"}
    if proc.returncode != 0:
        return {"ok": False, "stdout": proc.stdout, "rc": proc.returncode,
                "why": f"orca {' '.join(args[:2])} failed: "
                       f"{_why_from_output(proc.stdout, proc.returncode)}"}
    return {"ok": True, "stdout": proc.stdout, "rc": 0, "why": None}


def runtime_ready() -> bool:
    """App orca joignable — leçon tw_orca : `--version` réussit même app
    fermée ; le check fiable est `orca status` (runtimeReachable)."""
    res = _run(["status"], timeout=10)
    if not res["ok"]:
        return False
    try:
        data = json.loads(res["stdout"])
        reachable = (data.get("result") or {}).get("runtimeReachable")
        return reachable is True
    except (ValueError, TypeError):
        return "runtimeReachable: true" in (res["stdout"] or "")


def in_orca_session() -> bool:
    """Le process courant est hébergé par Orca (var injectée ORCA_WORKTREE_ID)."""
    return bool(os.environ.get("ORCA_WORKTREE_ID"))


def find_worktree_selector(worktree_path: str) -> Dict[str, Any]:
    """Selector orca du worktree — découverte, jamais création/registre."""
    res = _run(["worktree", "list", "--json", "--limit", "80"])
    if not res["ok"]:
        return {"ok": False, "why": res["why"]}
    try:
        data = json.loads(res["stdout"])
        rows = (data.get("result") or {}).get("worktrees") or []
    except (ValueError, TypeError):
        return {"ok": False, "why": "unparsable orca worktree list output"}
    wanted = os.path.realpath(os.path.expanduser(worktree_path))
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not row.get("id"):  # review J3 : selector None => jamais propagé
            continue
        if os.path.realpath(row.get("path") or "") == wanted:
            return {"ok": True, "selector": row.get("id"), "why": None}
    return {"ok": False,
            "why": f"worktree not indexed by Orca: {worktree_path}"}


def create_dashboard_terminal(selector: str, title: str, command: str,
                              focus: bool = True) -> Dict[str, Any]:
    """Crée le pane et retourne handle/paneKey — incertain si handle absent."""
    args = ["terminal", "create", "--worktree", selector, "--title", title,
            "--command", command, "--json"]
    if focus:
        args.append("--focus")
    res = _run(args, timeout=20)
    if not res["ok"]:
        return res
    try:
        data = json.loads(res["stdout"])
        term = (data.get("result") or {}).get("terminal") or {}
    except ValueError:
        term = {}
    handle = term.get("handle")
    if not handle:
        return {"ok": False, "uncertain": True,
                "why": "terminal created but handle missing — treat as uncertain"}
    return {"ok": True, "handle": handle,
            "paneKey": term.get("paneKey"), "why": None}


def close_terminal(handle: str) -> Dict[str, Any]:
    res = _run(["terminal", "close", "--terminal", handle])
    return {"ok": res["ok"], "why": res["why"]}


def renderer_command(watch: float = 0.5,
                     session_id: Optional[str] = None) -> str:
    """Commande du pane : renderer en boucle, chemin absolu, auto-suffisant."""
    here = os.path.dirname(os.path.abspath(__file__))
    parts = [sys.executable, os.path.join(here, "wd_dashboard.py"),
             "--watch", str(watch)]
    if session_id:
        parts.extend(["--session-id", session_id])
    return " ".join(shlex.quote(part) for part in parts)


def ensure(worktree_path: Optional[str] = None, *,
           session_id: Optional[str] = None, watch: float = 0.5,
           focus: bool = True, force: bool = False) -> Dict[str, Any]:
    """Idempotent : réutilise le pane enregistré, sinon le crée.

    force=True (= restart) : close du handle existant puis recreate — la
    relance sans duplication du critère E2E passe par ensure, jamais par un
    second create.

    Review J3 : le read-modify-write de l'état GLOBAL des panes (partagé par
    toutes les sessions) est sous wd_core.FileLock — le create orca (~20 s)
    est DANS la section critique, sinon le second writer écrase le handle du
    premier (pane orphelin + duplication)."""
    if not wd_dashboard.WATCH_MIN <= watch <= wd_dashboard.WATCH_MAX:
        return {"ok": False, "skipped": True, "handle": None,
                "why": f"watch must be in [{wd_dashboard.WATCH_MIN}, "
                       f"{wd_dashboard.WATCH_MAX}] (renderer l'exigerait)"}
    state_path = panes_state_path()
    lock = wd_core.FileLock(state_path + ".lock", timeout=PANES_LOCK_TIMEOUT)
    try:
        lock.acquire()
    except wd_core.LockError:
        return {"ok": False, "skipped": True, "handle": None,
                "why": "panes state busy — réessayer"}
    try:
        state = read_panes_state()
        panes = state.get("panes") if isinstance(state.get("panes"), dict) else {}
        key = pane_key(worktree_path)
        existing = panes.get(key)
        if existing and isinstance(existing, dict) and existing.get("handle") \
                and not force:
            return {"ok": True, "reused": True, "handle": existing["handle"],
                    "why": None}
        if not in_orca_session():
            return {"ok": False, "skipped": True, "handle": None,
                    "why": "session non hébergée par Orca (ORCA_WORKTREE_ID absent)"}
        if key == "global":
            return {"ok": False, "skipped": True, "handle": None,
                    "why": "ensure nécessite --worktree-path dans une session Orca"}
        if not runtime_ready():
            return {"ok": False, "skipped": True, "handle": None,
                    "why": "orca runtime indisponible (app fermée ?)"}
        selector_res = find_worktree_selector(key)
        if not selector_res["ok"]:
            return {"ok": False, "skipped": False, "handle": None,
                    "why": selector_res["why"]}
        if force and existing and isinstance(existing, dict) and existing.get("handle"):
            close_terminal(existing["handle"])  # best-effort : pane peut-être déjà mort
        created = create_dashboard_terminal(
            selector_res["selector"], DASHBOARD_TITLE,
            renderer_command(watch=watch, session_id=session_id), focus=focus)
        if not created["ok"]:
            # handle incertain : on N'ENREGISTRE PAS un succès invérifiable
            return {"ok": False, "uncertain": created.get("uncertain", False),
                    "handle": None, "why": created["why"]}
        panes[key] = {"handle": created["handle"], "paneKey": created.get("paneKey"),
                      "startedAt": wd_now_iso(), "command":
                          renderer_command(watch=watch, session_id=session_id)}
        state["panes"] = panes
        write_panes_state(state)
        return {"ok": True, "reused": False, "handle": created["handle"],
                "why": None}
    finally:
        lock.release()


def close(worktree_path: Optional[str] = None) -> Dict[str, Any]:
    state_path = panes_state_path()
    lock = wd_core.FileLock(state_path + ".lock", timeout=PANES_LOCK_TIMEOUT)
    try:
        lock.acquire()
    except wd_core.LockError:
        return {"ok": False, "why": "panes state busy — réessayer"}
    try:
        state = read_panes_state()
        panes = state.get("panes") if isinstance(state.get("panes"), dict) else {}
        key = pane_key(worktree_path)
        existing = panes.get(key)
        if not existing or not isinstance(existing, dict) or not existing.get("handle"):
            return {"ok": True, "why": "aucun pane enregistré pour ce worktree"}
        res = close_terminal(existing["handle"])
        # review J3 : on n'oublie le handle QUE si le close a réussi —
        # sinon le pane vit peut-être encore (orphelin + duplication)
        if res["ok"]:
            panes.pop(key, None)
            state["panes"] = panes
            write_panes_state(state)
            return {"ok": True, "why": None}
        return {"ok": False, "why": res["why"]}
    finally:
        lock.release()


def status() -> Dict[str, Any]:
    return read_panes_state()


def wd_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wd_orca",
        description="Workflow Dashboard — intégration pane Orca (idempotent)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ensure", help="créer le pane s'il n'existe pas (idempotent)")
    p.add_argument("--worktree-path", default=None)
    p.add_argument("--session-id", default=None)
    p.add_argument("--watch", type=float, default=0.5)
    p.add_argument("--no-focus", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="restart : close du pane existant puis recreate")
    p.set_defaults(func=_cmd_ensure)

    p = sub.add_parser("close", help="fermer le pane du worktree")
    p.add_argument("--worktree-path", default=None)
    p.set_defaults(func=_cmd_close)

    p = sub.add_parser("status", help="état des panes enregistrés")
    p.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


def _emit(payload: Dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


def _cmd_ensure(args: argparse.Namespace) -> int:
    try:
        return _emit(ensure(args.worktree_path, session_id=args.session_id,
                            watch=args.watch, focus=not args.no_focus,
                            force=args.force))
    except (OSError, wd_core.LockError) as exc:
        # garantie « toutes les sorties sont JSON » (review J3 : OSError après
        # un create réussi ne doit jamais sortir en traceback)
        return _emit({"ok": False, "why": f"{type(exc).__name__}: {exc}"})


def _cmd_close(args: argparse.Namespace) -> int:
    try:
        return _emit(close(args.worktree_path))
    except (OSError, wd_core.LockError) as exc:
        return _emit({"ok": False, "why": f"{type(exc).__name__}: {exc}"})


def _cmd_status(_args: argparse.Namespace) -> int:
    state = status()
    return _emit({"ok": True, "panes": state.get("panes", {})})


if __name__ == "__main__":
    sys.exit(main())
