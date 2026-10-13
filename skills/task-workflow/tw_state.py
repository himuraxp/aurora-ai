#!/usr/bin/env python3
"""State contract for the task-workflow skill (stdlib only, Python 3.9+).

Deterministic part of the skill: state-file schema validation, legal phase
transitions, code-signature computation (HEAD + clean tree), STALE detection
(a PASSED phase whose codeSignature no longer matches current reality),
resume planning, idempotence and file identity. No network, no MR creation —
tests use fixtures and temp git repos only (see tests/).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
STATUSES = ("PENDING", "RUNNING", "WAITING_APPROVAL", "BLOCKED", "FAILED", "PASSED", "SKIPPED")
# STALE is derived, never stored.
PHASES = tuple(range(1, 10))  # 1..9 — Phase 8 = état/reprise (see SKILL.md)
WORKFLOW_ID_RE = re.compile(r"^tw-[a-z0-9][a-z0-9-]{0,78}[a-z0-9]$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

REQUIRED_TOP = (
    "schemaVersion", "workflowId", "taskUrls", "repository", "baseBranch",
    "baseCommit", "featureBranch", "worktreePath", "currentPhase", "phaseStatuses",
    "createdAt", "updatedAt",
)

TRANSITIONS = {
    "PENDING": {"RUNNING", "SKIPPED", "BLOCKED"},
    "RUNNING": {"PASSED", "FAILED", "BLOCKED", "WAITING_APPROVAL", "SKIPPED"},
    "WAITING_APPROVAL": {"RUNNING", "BLOCKED", "PENDING"},
    "BLOCKED": {"RUNNING", "PENDING", "SKIPPED"},
    "FAILED": {"RUNNING", "PENDING", "SKIPPED"},
    "PASSED": set(),  # only invalidate() may move out of PASSED
    "SKIPPED": {"RUNNING"},
}


def new_workflow_id(task_url: str, repository: str) -> str:
    """Deterministic id: tw-<repo-slug>--<hash8 of task url>."""
    slug = re.sub(r"[^a-z0-9]+", "-", repository.rstrip("/").split("/")[-1].lower()).strip("-") or "repo"
    digest = hashlib.sha1(task_url.encode("utf-8")).hexdigest()[:8]
    return f"tw-{slug[:40]}--{digest}"


def compute_code_signature(worktree_path: str) -> str:
    """Deterministic worktree signature: sha1(HEAD sha + git status --porcelain).

    A dirty tree produces a different signature — uncommitted changes AFTER a
    phase was marked PASSED invalidate it (fail-closed STALE detection).
    """
    def git(*args: str) -> str:
        result = subprocess.run(["git", "-C", worktree_path, *args],
                                capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ValueError(f"not a usable git worktree: {worktree_path} ({result.stderr.strip()})")
        return result.stdout

    head = git("rev-parse", "HEAD").strip()
    status = git("status", "--porcelain")
    return hashlib.sha1((head + "\n" + status).encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_iso(value: str) -> bool:
    if not ISO_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_state(state: Any, path: Optional[str] = None) -> List[str]:
    """Return a list of problems (empty list = valid state)."""
    problems: List[str] = []
    if not isinstance(state, dict):
        return ["state is not a JSON object"]

    for key in REQUIRED_TOP:
        if key not in state:
            problems.append(f"missing required key: {key}")
    if problems:
        return problems

    if state["schemaVersion"] != SCHEMA_VERSION:
        problems.append(f"schemaVersion must be {SCHEMA_VERSION}")
    if not WORKFLOW_ID_RE.match(str(state["workflowId"])):
        problems.append("workflowId must match tw-<slug>--<hash8> pattern")
    elif path is not None and "task-workflows" in os.path.abspath(path):
        # File identity: the state file must be named <workflowId>.json where
        # it lives in the canonical directory (fail-closed on resume mix-ups).
        if os.path.basename(path) != f"{state['workflowId']}.json":
            problems.append("file name must be <workflowId>.json in task-workflows/")

    urls = state["taskUrls"]
    if not isinstance(urls, list) or not urls:
        problems.append("taskUrls must be a non-empty list")
    else:
        for entry in urls:
            if not isinstance(entry, dict) or entry.get("source") not in ("trello", "gitlab") \
                    or not str(entry.get("url", "")).startswith(("http://", "https://")):
                problems.append(f"invalid taskUrls entry: {entry!r}")

    for key in ("repository", "baseBranch", "baseCommit", "featureBranch", "worktreePath"):
        if not str(state.get(key, "")).strip():
            problems.append(f"{key} must be a non-empty string")
    if state.get("baseBranch") and state.get("baseBranch") == state.get("featureBranch"):
        problems.append("baseBranch and featureBranch must differ")

    phase = state.get("currentPhase")
    if type(phase) is not int or phase not in PHASES:
        problems.append(f"currentPhase must be an integer in {list(PHASES)}")

    statuses = state["phaseStatuses"]
    if not isinstance(statuses, dict):
        problems.append("phaseStatuses must be an object keyed by phase number")
    else:
        for key, entry in statuses.items():
            try:
                num = int(key)
            except (TypeError, ValueError):
                problems.append(f"phaseStatuses key not numeric: {key}")
                continue
            if num not in PHASES:
                problems.append(f"phaseStatuses key out of range: {key}")
            if not isinstance(entry, dict) or entry.get("status") not in STATUSES:
                problems.append(f"phaseStatuses[{key}].status invalid")
            else:
                if isinstance(entry.get("at"), str) and not _is_iso(entry["at"]):
                    problems.append(f"phaseStatuses[{key}].at is not ISO-8601")
                signature = entry.get("codeSignature")
                if signature is not None and (not isinstance(signature, str) or not signature.strip()):
                    problems.append(f"phaseStatuses[{key}].codeSignature must be a non-empty string when present")
        # Coherence: phases strictly before currentPhase must be decided
        # (PASSED/SKIPPED/FAILED/BLOCKED/WAITING_APPROVAL) — never idle.
        if type(phase) is int:
            for num in PHASES:
                if num >= phase:
                    break
                entry = statuses.get(str(num))
                if entry is None or entry.get("status") in (None, "PENDING", "RUNNING"):
                    problems.append(f"phase {num} < currentPhase but not decided")

    if state.get("mergeRequestUrl") not in (None, "") and not str(state["mergeRequestUrl"]).startswith(("http://", "https://")):
        problems.append("mergeRequestUrl must be an absolute URL or null")
    for key in ("createdAt", "updatedAt"):
        if not _is_iso(str(state.get(key, ""))):
            problems.append(f"{key} must be ISO-8601")
    blockers = state.get("blockers", [])
    if not isinstance(blockers, list):
        problems.append("blockers must be a list")
    return problems


def load_state(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def mark_phase(state: dict, phase: int, status: str, code_signature: Optional[str] = None,
               at: Optional[str] = None) -> dict:
    """Apply a legal transition and return the mutated state (raises on illegal)."""
    if phase not in PHASES:
        raise ValueError(f"unknown phase: {phase}")
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    statuses = state.setdefault("phaseStatuses", {})
    key = str(phase)
    current_entry = statuses.get(key, {})
    if not isinstance(current_entry, dict):
        raise ValueError(f"corrupt phaseStatuses entry for phase {phase}")
    current = current_entry.get("status", "PENDING")
    if status not in TRANSITIONS[current]:
        raise ValueError(f"illegal transition phase {phase}: {current} -> {status}")
    entry = {"status": status, "at": at or _now_iso()}
    if code_signature is not None:
        entry["codeSignature"] = code_signature
    statuses[key] = entry
    state["updatedAt"] = entry["at"]
    if status == "RUNNING":
        state["currentPhase"] = max(int(state.get("currentPhase", 0)), phase)
    return state


def invalidate_phase(state: dict, phase: int, at: Optional[str] = None) -> dict:
    """Retire a PASSED phase whose result no longer matches current code (-> PENDING).

    The ONLY legal move out of PASSED — bypasses the normal transition table.
    """
    key = str(phase)
    if state.get("phaseStatuses", {}).get(key, {}).get("status") != "PASSED":
        raise ValueError(f"phase {phase} is not PASSED — nothing to invalidate")
    timestamp = at or _now_iso()
    state["phaseStatuses"][key] = {"status": "PENDING", "at": timestamp}
    state["updatedAt"] = timestamp
    return state


def compute_stale(state: dict, current_signature: str) -> List[int]:
    """PASSED phases whose codeSignature differs from (or is missing vs) current worktree state.

    Fail-closed: a PASSED phase without a recorded signature is unverifiable → STALE.
    """
    stale: List[int] = []
    for key, entry in state.get("phaseStatuses", {}).items():
        if entry.get("status") == "PASSED" and entry.get("codeSignature") != current_signature:
            stale.append(int(key))
    return sorted(stale)


def resume_plan(state: dict, current_signature: str, worktree_exists: bool = True) -> Dict[str, Any]:
    """Deterministic resume plan from persisted state vs measured reality.

    rerun is sorted ascending — apply it in order. A phase BLOCKED re-entered
    at resume must RE-EVALUATE its blocker, never bypass it.
    """
    statuses = state.get("phaseStatuses", {})
    stale = compute_stale(state, current_signature) if worktree_exists else []

    if state.get("mergeRequestUrl"):
        # MR already exists → the cycle is complete; Phase 9 only. STALE phases
        # are informational: the MR may be missing later commits — the final
        # report MUST mention them.
        return {
            "reuseExisting": True,
            "invalidate": stale,
            "staleAfterMergeRequest": stale,
            "rerun": [],
            "skip": [p for p in PHASES if p != 9],
            "resumeAt": 9,
        }

    rerun: set = set(stale)
    if not worktree_exists:
        rerun.add(2)  # worktree/branch reality must be re-established first
    for phase in PHASES:
        if phase in rerun:
            continue
        entry = statuses.get(str(phase))
        status = entry.get("status") if isinstance(entry, dict) else None
        if status == "PASSED" and worktree_exists:
            continue  # skip (fresh signature — already in rerun otherwise)
        if status == "SKIPPED":
            continue
        if status == "BLOCKED" and worktree_exists:
            rerun.add(phase)  # re-evaluate the blocker, never bypass it
            continue
        rerun.add(phase)  # PENDING/RUNNING/FAILED/WAITING_APPROVAL/None, or no worktree
    ordered = sorted(rerun)
    return {
        "reuseExisting": True,
        "invalidate": sorted(stale),
        "staleAfterMergeRequest": [],
        "rerun": ordered,
        "skip": [p for p in PHASES if p not in ordered],
        "resumeAt": ordered[0] if ordered else 9,
    }


def cmd_validate(argv: List[str]) -> int:
    path = argv[0]
    state = load_state(path)
    problems = validate_state(state, path)
    for problem in problems:
        print(f"INVALID: {problem}")
    print("state valid" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_resume(argv: List[str]) -> int:
    path, signature, worktree_missing = argv[0], "", False
    rest = argv[1:]
    while rest:
        flag = rest.pop(0)
        if flag == "--signature":
            signature = rest.pop(0)
        elif flag == "--worktree-missing":
            worktree_missing = True
    state = load_state(path)
    problems = validate_state(state, path)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        return 1
    print(json.dumps(resume_plan(state, signature, worktree_exists=not worktree_missing), indent=2))
    return 0


def cmd_mark(argv: List[str]) -> int:
    path, phase, status = argv[0], int(argv[1]), argv[2]
    rest = argv[3:]
    signature: Optional[str] = None
    while rest:
        flag = rest.pop(0)
        if flag == "--signature":
            signature = rest.pop(0)
    state = load_state(path)
    try:
        mark_phase(state, phase, status, code_signature=signature)
    except ValueError as error:
        print(f"ILLEGAL: {error}")
        return 1
    problems = validate_state(state, path)
    if problems:
        # Fail-closed: never persist a state the contract itself rejects
        # (e.g. jumping to phase 7 while 1-6 are undecided).
        for problem in problems:
            print(f"INVALID: {problem}")
        print("state NOT saved")
        return 1
    save_state(path, state)
    print(f"phase {phase} -> {status}")
    return 0


def cmd_invalidate(argv: List[str]) -> int:
    path, phase = argv[0], int(argv[1])
    state = load_state(path)
    try:
        invalidate_phase(state, phase)
    except ValueError as error:
        print(f"ILLEGAL: {error}")
        return 1
    problems = validate_state(state, path)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        print("state NOT saved")
        return 1
    save_state(path, state)
    print(f"phase {phase} invalidated -> PENDING")
    return 0


def cmd_signature(argv: List[str]) -> int:
    try:
        print(compute_code_signature(argv[0]))
        return 0
    except ValueError as error:
        print(f"ERROR: {error}")
        return 1


def cmd_id(argv: List[str]) -> int:
    print(new_workflow_id(argv[0], argv[1]))
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: tw_state.py validate|resume|mark|invalidate|signature|id ...", file=sys.stderr)
        return 2
    command = argv[0]
    if command == "validate":
        return cmd_validate(argv[1:])
    if command == "resume":
        return cmd_resume(argv[1:])
    if command == "mark":
        return cmd_mark(argv[1:])
    if command == "invalidate":
        return cmd_invalidate(argv[1:])
    if command == "signature":
        return cmd_signature(argv[1:])
    if command == "id":
        return cmd_id(argv[1:])
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
