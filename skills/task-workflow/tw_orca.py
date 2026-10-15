#!/usr/bin/env python3
"""Orca UI integration adapter for the task-workflow handoff.

Strategy A (user-validated, 2026-10-15): `new-worktree` stays the ONLY Git
worktree creator; Orca is the UI integration layer — it reveals the worktree,
opens a terminal inside it and launches the OpenCode session that takes over.

Contract:
- every entry point returns a plain dict {"ok": bool, ...} and NEVER raises
  into the workflow — Orca is an enhancement, never a requirement;
- read-only commands: status, worktree list; mutating commands: terminal
  create / terminal close, always tied to a handle this adapter created;
- CLI only — no AppleScript, no UI automation;
- a successful `terminal create` is NOT the confirmation that the new session
  took over: the confirmation lives in the state (`handoff.status` = accepted
  via `tw_state.py claim`).
"""

import json
import os
import shutil
import subprocess
from typing import Any, Optional

DEFAULT_TIMEOUT = 12


def _orca_bin() -> str:
    return os.environ.get("TW_ORCA_BIN", "orca")


def _run(args: list, timeout: int = DEFAULT_TIMEOUT) -> dict:
    if shutil.which(_orca_bin()) is None:
        return {"ok": False, "why": f"orca CLI not found ({_orca_bin()})"}
    try:
        proc = subprocess.run([_orca_bin(), *args], capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": f"orca {' '.join(args[:2])} timed out after {timeout}s"}
    except OSError as error:
        return {"ok": False, "why": f"orca spawn failed: {error}"}
    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout or "").strip()
        why = output.splitlines()[-1][:200] if output else f"exit code {proc.returncode}"
        return {"ok": False, "rc": proc.returncode, "why": why}
    return {"ok": True, "rc": 0, "stdout": proc.stdout, "why": None}


def runtime_ready() -> dict:
    """The app may be closed — this single check decides the fallback."""
    res = _run(["status"])
    if not res["ok"]:
        return {"ok": False, "why": res["why"]}
    if "runtimeReachable: true" not in res["stdout"]:
        return {"ok": False, "why": "Orca runtime not reachable (app closed?)"}
    return {"ok": True, "why": None}


def in_orca_session() -> bool:
    """True when the current OpenCode session itself lives in an Orca terminal
    (Orca injects ORCA_* variables into terminals it hosts)."""
    return bool(os.environ.get("ORCA_WORKTREE_ID"))


def find_worktree_selector(worktree_path: str) -> dict:
    """Resolve the Orca selector `<repoId>::<path>` of a worktree.

    new-worktree worktrees are NOT Orca-created but ARE discovered and indexed
    by Orca (verified live) — this lookup finds them; it never creates or
    registers anything.
    """
    res = _run(["worktree", "list", "--json", "--limit", "80"])
    if not res["ok"]:
        return {"ok": False, "why": res["why"]}
    try:
        data = json.loads(res["stdout"])
        rows = (data.get("result") or {}).get("worktrees") or []
    except (ValueError, TypeError):
        return {"ok": False, "why": "unparsable orca worktree list output"}
    wanted = os.path.realpath(worktree_path)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if os.path.realpath(row.get("path") or "") == wanted:
            return {"ok": True, "selector": row.get("id"), "why": None}
    return {"ok": False, "why": f"worktree not indexed by Orca: {worktree_path}"}


def create_handoff_terminal(selector: str, title: str, command: str,
                            focus: bool = True) -> dict:
    """Open a visible terminal tab inside the worktree and (by default) bring
    it to the foreground — the UI switch of the handoff."""
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
        # The tab may exist while the machine-readable handle is missing —
        # report uncertain, never claim a success the caller cannot verify.
        return {"ok": False, "uncertain": True,
                "why": "terminal created but handle missing — treat as uncertain"}
    return {"ok": True, "handle": handle, "paneKey": term.get("paneKey"), "why": None}


def close_terminal(handle: str) -> dict:
    """Cleanup helper for tests/validation only — never called on user tabs."""
    res = _run(["terminal", "close", "--terminal", handle])
    return {"ok": res["ok"], "why": res["why"]}


def handoff_command(selector: str, title: str, resume_command: str,
                    focus: bool = True) -> dict:
    """Full handoff step: resolve nothing, just create the terminal.
    Kept as the single mutation entry point for callers (SKILL.md Phase 2)."""
    return create_handoff_terminal(selector, title, resume_command, focus=focus)
