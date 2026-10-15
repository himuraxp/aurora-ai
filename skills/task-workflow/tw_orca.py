#!/usr/bin/env python3
"""Orca UI integration adapter for the task-workflow handoff.

Strategy A (user-validated, 2026-10-15): `new-worktree` stays the ONLY Git
worktree creator; Orca is the UI integration layer — it reveals the worktree,
opens a terminal inside it and launches the OpenCode session that takes over.

Contract:
- every entry point returns a plain dict {"ok": bool, ...} and NEVER raises
  into the workflow — Orca is an enhancement, never a requirement;
- `handoff_run` is the SINGLE deterministic entry point for the Phase 2
  handoff: it evaluates the trigger, records EVERY outcome in the state
  (pending / failed / uncertain / skipped — never silent), creates the
  takeover terminal and returns one JSON verdict. No prose procedure to skip;
- read-only commands: status, worktree list; mutating commands: terminal
  create / terminal close, always tied to a handle this adapter created;
- CLI only — no AppleScript, no UI automation;
- a successful `terminal create` is NOT the confirmation that the new session
  took over: the confirmation lives in the state (`handoff.status` = accepted
  via `tw_state.py claim`).
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from typing import Any, Optional

DEFAULT_TIMEOUT = 12

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tw_state  # noqa: E402


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
    """Low-level wrapper kept for compat — the Phase 2 entry is now the
    deterministic `handoff_run` / CLI `handoff`."""
    return create_handoff_terminal(selector, title, resume_command, focus=focus)


def _skill_cli(name: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def _journal(state_path: str, summary: str, at: str) -> None:
    """Chronicle after the commit (same rule as mark): informative, never blocking."""
    try:
        tw_state.append_event(state_path, {"type": "command", "phase": 2,
                                           "actor": "orchestrator", "at": at,
                                           "summary": summary})
    except (OSError, ValueError) as error:
        print(f"JOURNAL-WARNING: handoff event not recorded ({error})", file=sys.stderr)


def _record(state_path: str, state: dict, status: str, *, handle: Optional[str] = None,
            worktree_path: Optional[str] = None, why: Optional[str] = None) -> bool:
    """Validate then persist one handoff step — fail-closed, never partial,
    never raising (the OSError of a failing save is caught and reported)."""
    tw_state.set_handoff(state, status, terminal_handle=handle,
                         worktree_path=worktree_path, why=why)
    problems = tw_state.validate_state(state, state_path)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}", file=sys.stderr)
        return False
    try:
        tw_state.save_state(state_path, state)
    except OSError as error:
        print(f"SAVE-ERROR: handoff step not persisted ({error})", file=sys.stderr)
        return False
    detail = f" (terminal {handle})" if handle else ""
    suffix = f" — {why}" if why else ""
    _journal(state_path, f"handoff {status}{detail}{suffix}", state["handoff"]["at"])
    return True


def default_resume_command(state: dict, state_path: str, resume_phase: int = 3,
                           worktree_path: Optional[str] = None) -> str:
    """The taking-over session's bootstrap prompt — short, the state carries the rest.

    The resume plan is signature-based (STALE = fail-closed), so the command
    embeds the signature measured NOW: without it every PASSED phase would
    read stale and contradict the prompt's own "phases déjà validées".
    """
    state_path = os.path.abspath(state_path)
    claim = (f"python3 {shlex.quote(_skill_cli('tw_state.py'))} claim "
             f"{shlex.quote(state_path)} --session pane:$ORCA_AGENT_PANE")
    resume = f"python3 {shlex.quote(_skill_cli('tw_state.py'))} resume {shlex.quote(state_path)}"
    signature = ""
    if worktree_path:
        try:
            signature = f" --signature {shlex.quote(tw_state.compute_code_signature(worktree_path))}"
        except ValueError:
            pass  # no measurable signature — resume degrades to STALE warnings
    prompt = (f"Reprise task-workflow {state.get('workflowId', '?')} : exécute `{claim}` "
              f"puis reprends à la phase {resume_phase} (`{resume}{signature}`). Phases déjà "
              f"validées — ne les rejoue pas. Termine par le rapport compact (Phase 9).")
    return f"opencode --prompt {shlex.quote(prompt)}"


def handoff_run(state_path: str, worktree_path: str, *, title: Optional[str] = None,
                command: Optional[str] = None, focus: bool = True,
                resume_phase: int = 3) -> dict:
    """Single deterministic Phase 2 handoff — evaluate, record, launch, record.

    Every outcome is persisted in the state (skipped / failed / uncertain /
    pending) and journaled, so the final report shows the real fate of the
    takeover — there is NO silent fallback. Returns one JSON-able verdict and
    never raises. `pending` WITHOUT a recorded terminal handle is a crashed
    preparation, not a live takeover: relaunching is allowed and safe (the
    anti-double-prise only protects a handoff a terminal was created for).
    """
    guard = tw_state._canonical_write_guard(state_path)
    if guard:
        return {"ok": False, "status": None, "written": False,
                "why": guard.replace("ERROR: ", "")}
    try:
        state = tw_state.load_state(state_path)
    except (OSError, ValueError) as error:
        return {"ok": False, "status": None, "written": False,
                "why": f"unreadable state: {error}"}
    existing = state.get("handoff") or {}
    existing_status = existing.get("status")
    if existing_status == "accepted" or (existing_status == "pending"
                                         and existing.get("terminalHandle")):
        return {"ok": False, "status": existing_status, "written": False,
                "idempotent": True,
                "why": f"handoff already {existing_status} — relaunch refused "
                       "(anti double prise)"}
    if not in_orca_session():
        why = "session non hébergée par Orca (ORCA_WORKTREE_ID absent)"
        written = _record(state_path, state, "skipped", worktree_path=worktree_path, why=why)
        if written:
            return {"ok": False, "skipped": True, "status": "skipped", "handle": None,
                    "written": True,
                    "why": "session non hébergée par Orca — suite dans la session courante"}
        return {"ok": False, "status": None, "written": False,
                "why": "state rejected by validation — not saved"}
    ready = runtime_ready()
    if not ready["ok"]:
        why = f"runtime Orca indisponible ({ready['why']}) — suite dans la session courante"
        written = _record(state_path, state, "skipped", worktree_path=worktree_path, why=why)
        if written:
            return {"ok": False, "skipped": True, "status": "skipped", "handle": None,
                    "written": True, "why": why}
        return {"ok": False, "status": None, "written": False,
                "why": "state rejected by validation — not saved"}
    selector = find_worktree_selector(worktree_path)
    if not selector["ok"]:
        written = _record(state_path, state, "failed", worktree_path=worktree_path,
                          why=selector["why"])
        if written:
            return {"ok": False, "status": "failed", "handle": None, "written": True,
                    "why": selector["why"]}
        return {"ok": False, "status": None, "written": False,
                "why": "state rejected by validation — not saved"}
    # Pre-launch pending mark: if the machine dies here, the state stays
    # resumable (resume warns "takeover not confirmed") and a relaunch is
    # allowed precisely because no handle was ever recorded.
    if not _record(state_path, state, "pending", worktree_path=worktree_path,
                   why="preparing takeover terminal"):
        return {"ok": False, "status": None, "written": False,
                "why": "state rejected by validation — not saved"}
    cmd = command or default_resume_command(state, state_path, resume_phase,
                                            worktree_path=worktree_path)
    created = create_handoff_terminal(
        selector["selector"], title or str(state.get("featureBranch", "task-workflow")),
        cmd, focus=focus)
    if created["ok"]:
        if _record(state_path, state, "pending", handle=created["handle"],
                   worktree_path=worktree_path):
            return {"ok": True, "status": "pending", "handle": created["handle"],
                    "written": True, "selector": selector["selector"], "why": None}
        return {"ok": False, "status": None, "written": False,
                "why": "terminal created but state rejected by validation — "
                       "claim manually after checking the state"}
    status = "uncertain" if created.get("uncertain") else "failed"
    written = _record(state_path, state, status, worktree_path=worktree_path,
                      why=created.get("why"))
    if written:
        return {"ok": False, "status": status, "handle": None, "written": True,
                "uncertain": bool(created.get("uncertain")), "why": created.get("why")}
    return {"ok": False, "status": None, "written": False,
            "why": "state rejected by validation — not saved"}


def cmd_handoff(argv: list) -> int:
    if not argv:
        print("usage: tw_orca.py handoff <state.json> --worktree-path P [--branch B]"
              " [--title T] [--command CMD] [--no-focus] [--resume-phase N]"
              "  (exit 0 = takeover prepared, 1 = no takeover, 2 = usage error)",
              file=sys.stderr)
        return 2
    state_path, rest = argv[0], argv[1:]
    worktree = branch = title = command = None
    focus, resume_phase = True, 3
    try:
        while rest:
            flag = rest.pop(0)
            if flag == "--worktree-path":
                worktree = rest.pop(0)
            elif flag == "--branch":
                branch = rest.pop(0)
            elif flag == "--title":
                title = rest.pop(0)
            elif flag == "--command":
                command = rest.pop(0)
            elif flag == "--no-focus":
                focus = False
            elif flag == "--resume-phase":
                resume_phase = max(1, min(9, int(rest.pop(0))))
            else:
                print(f"ERROR: unknown flag {flag}", file=sys.stderr)
                return 2
    except (IndexError, ValueError):
        print("ERROR: malformed flag value", file=sys.stderr)
        return 2
    if not worktree:
        print("ERROR: --worktree-path required", file=sys.stderr)
        return 2
    result = handoff_run(state_path, worktree, title=title or branch, command=command,
                         focus=focus, resume_phase=resume_phase)
    print(json.dumps(result, ensure_ascii=False))
    # exit 0 = takeover prepared (pending) — the current session MUST stop;
    # exit 1 = no takeover (skipped/failed/uncertain/refused) — workflow
    # continues here; the outcome is persisted either way.
    return 0 if result["ok"] else 1


def main(argv: list) -> int:
    if argv and argv[0] == "handoff":
        return cmd_handoff(argv[1:])
    print("usage: tw_orca.py handoff <state.json> --worktree-path P [--branch B] ...",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
