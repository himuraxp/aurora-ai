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
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")  # git sha1 — codeSignature format
RESULT_STATUSES = ("pass", "fail", "skipped", "not-run")  # structured check results
# v1 states and the design-qa integration already wrote phase-style or
# participle values in free-form result entries — accepted as aliases for
# backward compatibility, never required. "pass"/"passed"/"PASSED" all carry
# the same hard rule: exitCode must be 0.
RESULT_STATUS_ALIASES = ("PASSED", "passed", "FAILED", "failed", "SKIPPED",
                         "BLOCKED", "WAITING_APPROVAL", "RUNNING", "PENDING")
EVENT_TYPES = ("phase", "command", "decision", "incident", "recovery", "note")
# Handoff takeover (Orca integration, strategy A): the state tracks the
# transfer of execution from the originating session to the session running
# inside the new worktree. State = the only truth about WHO owns the mandate.
# skipped = handoff evaluated and not applicable (not an Orca session, runtime
# down) — recorded, never silent; requires a "why" for the report.
HANDOFF_STATUSES = ("pending", "accepted", "failed", "uncertain", "skipped")
# Risk classification (Software Fundamentals lot 1, additive): the
# implementation risk level recorded at Phase 3 drives the conditional
# implementation contract and the increment discipline. Rule: when several
# risk characteristics apply, the HIGHEST level wins — a localized change
# touching auth/secrets/finance/security hooks is HIGH regardless of size.
RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")
# Implementation contract (additive, optional): a SECTION of the Phase 3 plan
# (never a separate document nor a gate) required for MEDIUM/HIGH changes.
# Each section is a list of non-empty strings; the contract must carry at
# least one section to exist (an empty contract proves nothing).
IMPLEMENTATION_CONTRACT_SECTIONS = (
    "observableBehaviors", "invariants", "acceptanceCriteria",
    "expectedEvidence", "modulesAffected", "constraints",
)
DEFAULT_STATE_DIR = os.path.expanduser("~/.config/opencode/task-workflows")


def state_dir() -> str:
    """Canonical state directory.

    Overridable for tests and pilots via TW_STATE_STATE_DIR; production
    default is ~/.config/opencode/task-workflows/ (write commands refuse any
    path outside it).
    """
    return os.environ.get("TW_STATE_STATE_DIR") or DEFAULT_STATE_DIR

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


def canonical_task_key(task_url: str) -> str:
    """Stable task identity extracted from any URL form of the same task.

    Trello:  trello.com/c/<id> or trello.com/c/<id>/<slug>  -> trello:<id>
    GitLab:  .../<group>/<project>/-/issues/<n> or /-/work_items/<n>
             -> gitlab:<group>/<project>#<n>
    Fallback: the URL as given (unknown sources keep their previous identity).
    """
    url = task_url.strip().rstrip("/")
    match = re.search(r"trello\.com/c/([A-Za-z0-9]+)", url)
    if match:
        return f"trello:{match.group(1)}"
    match = re.search(r"gitlab[^/]*/(.+?)/-/(?:issues|work_items)/(\d+)", url)
    if match:
        return f"gitlab:{match.group(1)}#{match.group(2)}"
    return url


def new_workflow_id(task_url: str, repository: str) -> str:
    """Deterministic id: tw-<repo-slug>--<hash8 of canonical task key>.

    The hash covers the normalized task identity (Trello card id, GitLab
    project+num), NOT the raw URL — every URL form of the same task yields
    the same workflow id (T-01). Unknown sources fall back to the raw URL,
    preserving the pre-normalization identity.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", repository.rstrip("/").split("/")[-1].lower()).strip("-") or "repo"
    digest = hashlib.sha1(canonical_task_key(task_url).encode("utf-8")).hexdigest()[:8]
    return f"tw-{slug[:40]}--{digest}"


def resolve_state(task_url: str, repository: str, directory: Optional[str] = None) -> Optional[str]:
    """Find the state file of a task from ANY of its URL forms (T-01/T-A1).

    1. exact: canonical dir holds <new_workflow_id>.json;
    2. legacy: scan states whose taskUrls normalize to the same task key
       (pre-normalization ids like tw-site-manager--98e87142 stay resolvable);
    3. multiple matches → ValueError (duplicate states for one task, human
       decision required); none → None.
    """
    directory = directory or state_dir()
    if not os.path.isdir(directory):
        return None
    target = canonical_task_key(task_url)
    exact = os.path.join(directory, f"{new_workflow_id(task_url, repository)}.json")
    if os.path.isfile(exact):
        try:
            state = load_state(exact)
            urls = state.get("taskUrls")
            if isinstance(urls, list) and any(
                    isinstance(entry, dict)
                    and canonical_task_key(str(entry.get("url", ""))) == target
                    for entry in urls):
                return exact
        except (OSError, ValueError):
            pass  # unreadable exact hit → fall through to the legacy scan
    matches: List[str] = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            state = load_state(path)
            urls = state.get("taskUrls")
            if not isinstance(urls, list):
                continue
            for entry in urls:
                if isinstance(entry, dict) and canonical_task_key(str(entry.get("url", ""))) == target:
                    matches.append(path)
                    break
        except (OSError, ValueError):
            continue  # unreadable/corrupt state files are validate-all's job
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous task identity: {len(matches)} states match this task "
            f"({', '.join(os.path.basename(m) for m in matches)}) — resolve manually"
        )
    return matches[0] if matches else None


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
    elif path is not None and os.path.dirname(os.path.abspath(path)) == os.path.abspath(state_dir()):
        # File identity: the state file must be named <workflowId>.json where
        # it lives in the canonical directory (fail-closed on resume mix-ups).
        # Same predicate as the write guard — no substring false positives.
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
                if signature is not None and (
                        not isinstance(signature, str) or not SHA1_RE.match(signature)):
                    problems.append(
                        f"phaseStatuses[{key}].codeSignature must be a 40-char git sha1 when present")
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
    # Additive optional fields (design-qa integration) — validated when
    # present, never required: v1 states without them stay valid.
    design_contract = state.get("designContract")
    if design_contract is not None and (not isinstance(design_contract, str) or not design_contract.strip()):
        problems.append("designContract must be a non-empty path string or null")
    # Risk level (additive, Software Fundamentals lot 1): drives the
    # conditional implementation contract + increment discipline. Absent =
    # legitimate (v1 states and LOW-by-default workflows without triage).
    risk_level = state.get("riskLevel")
    if risk_level is not None and risk_level not in RISK_LEVELS:
        problems.append(f"riskLevel must be one of {list(RISK_LEVELS)} or null when present")
    # Implementation contract (additive, optional): a section of the plan,
    # never a separate document. Validated when present: each section is a
    # list of non-empty strings, and the contract must carry at least one
    # section (an empty contract object would be a ghost requirement).
    contract = state.get("implementationContract")
    if contract is not None:
        if not isinstance(contract, dict) or not contract:
            problems.append("implementationContract must be a non-empty object or null")
        else:
            for section, items in contract.items():
                if not isinstance(items, list) or not items or \
                        not all(isinstance(item, str) and item.strip() for item in items):
                    problems.append(
                        f"implementationContract.{section} must be a non-empty list of non-empty strings")
            if not any(section in contract for section in IMPLEMENTATION_CONTRACT_SECTIONS):
                problems.append(
                    "implementationContract must carry at least one section of "
                    f"{list(IMPLEMENTATION_CONTRACT_SECTIONS)} (got: {sorted(contract)})")
    # Structured check results (additive, B1): when a check entry carries a
    # machine status, it must be honest — a "pass" with a non-zero exitCode is
    # a lie the contract refuses. Entries without these fields stay valid
    # (v1 free-form results).
    for key in ("testResults", "qaResults", "reviewResults"):
        entries = state.get(key, [])
        if not isinstance(entries, list):
            problems.append(f"{key} must be a list")
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            status = entry.get("status")
            if status is not None and status not in RESULT_STATUSES + RESULT_STATUS_ALIASES:
                problems.append(f"{key}[{index}].status must be one of {list(RESULT_STATUSES)}"
                                " (phase-style and participle aliases accepted)")
            exit_code = entry.get("exitCode")
            if exit_code is not None and type(exit_code) is not int:
                problems.append(f"{key}[{index}].exitCode must be an integer when present")
            if status in ("pass", "passed", "PASSED") and isinstance(exit_code, int) and exit_code != 0:
                problems.append(f"{key}[{index}]: exitCode {exit_code} cannot be reported as pass")
            # Increment evidence (additive, Software Fundamentals lot 1): an
            # intermediate proof must reference its increment; when it carries
            # a code signature, it must be a real sha1 (the proof validates
            # the code state it ran on — same honesty rule as phases).
            increment = entry.get("increment")
            if increment is not None and (not isinstance(increment, str) or not increment.strip()):
                problems.append(f"{key}[{index}].increment must be a non-empty string when present")
            entry_signature = entry.get("codeSignature")
            if entry_signature is not None and (
                    not isinstance(entry_signature, str) or not SHA1_RE.match(entry_signature)):
                problems.append(
                    f"{key}[{index}].codeSignature must be a 40-char git sha1 when present")
    # Handoff tracking (additive): a handoff block must be coherent — an
    # "accepted" takeover without a claimed session is an unverifiable mandate.
    handoff = state.get("handoff")
    if handoff is not None:
        if not isinstance(handoff, dict):
            problems.append("handoff must be an object")
        else:
            status = handoff.get("status")
            if status not in HANDOFF_STATUSES:
                problems.append(f"handoff.status must be one of {list(HANDOFF_STATUSES)}")
            elif status == "accepted" and not handoff.get("session"):
                problems.append("handoff.status=accepted requires the claimed session")
            elif status == "skipped" and not handoff.get("why"):
                problems.append("handoff.status=skipped requires a why (reason)")
    return problems


def load_state(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def artifacts_dir_for(state_path: str) -> str:
    """Per-workflow artifacts dir: <canonical dir>/<workflowId>/ (reports, journal)."""
    return os.path.join(os.path.dirname(os.path.abspath(state_path)),
                        os.path.basename(state_path)[:-len(".json")] if state_path.endswith(".json")
                        else os.path.basename(state_path))


def journal_path_for(state_path: str) -> str:
    return os.path.join(artifacts_dir_for(state_path), "events.jsonl")


def append_event(state_path: str, event: dict) -> dict:
    """Append one event to the workflow journal (append-only JSONL).

    The journal is a CHRONICLE, never the transaction: the state file stays
    the single source of truth (mark/invalidate commit the state first, the
    event is appended after). seq is the 1-based line number. No secrets, no
    bulky logs — reference evidence instead of embedding it.
    """
    if event.get("type") not in EVENT_TYPES:
        raise ValueError(f"event type must be one of {list(EVENT_TYPES)}")
    path = journal_path_for(state_path)
    seq = 0
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            seq = sum(1 for line in handle if line.strip())
    event = {"seq": seq + 1, "at": event.get("at") or _now_iso(),
             **{key: value for key, value in event.items() if key not in ("seq", "at")}}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def read_events(state_path: str) -> List[dict]:
    """Tolerant journal reader: corrupt lines are skipped (journal_problems
    reports them; a broken chronicle line must never take the report hostage)."""
    path = journal_path_for(state_path)
    if not os.path.isfile(path):
        return []
    events: List[dict] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue  # corrupt line — surfaced by journal_problems
            if not isinstance(event, dict):
                continue  # valid JSON but not an object — same treatment
            events.append(event)
    return events


def journal_problems(state: dict, state_path: str) -> List[str]:
    """Detect chronicle/state divergence (state is the truth, journal informative).

    Returns problems for: corrupt lines, broken seq ordering, and any decided
    phase transition that has NO corresponding journal event (gap — typically
    a v1 state recorded before the journal existed, or a lost append).
    """
    problems: List[str] = []
    path = journal_path_for(state_path)
    if not os.path.isfile(path):
        return problems  # v1 states legitimately have no journal
    events: List[dict] = []
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                problems.append(f"journal line {number} is not valid JSON")
                continue
            if not isinstance(event, dict):
                problems.append(f"journal line {number} is not a JSON object")
                continue
            events.append(event)
    for index, event in enumerate(events, start=1):
        if event.get("seq") != index:
            problems.append(f"journal seq broken at line {index}")
            break
    recorded = {(event.get("phase"), event.get("status"), event.get("at"))
                for event in events}
    for key, entry in (state.get("phaseStatuses") or {}).items():
        if not isinstance(entry, dict) or not entry.get("at"):
            continue
        marker = (int(key) if str(key).isdigit() else key,
                  entry.get("status"), entry["at"])
        if marker not in recorded:
            problems.append(
                f"phase {key} transition ({entry.get('status')} at {entry['at']}) has no journal event")
    return problems


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
    Rolls currentPhase back to the invalidated phase (the rework happens
    THERE), and purges that phase's recorded evidence: a result may not
    outlive the phase it proved (a stale entry must never satisfy a future
    PASSED).
    """
    key = str(phase)
    if state.get("phaseStatuses", {}).get(key, {}).get("status") != "PASSED":
        raise ValueError(f"phase {phase} is not PASSED — nothing to invalidate")
    timestamp = at or _now_iso()
    state["phaseStatuses"][key] = {"status": "PENDING", "at": timestamp}
    # Roll back ONLY (never forward): rework happens at the earliest
    # invalidated phase — invalidating a later phase must not lift
    # currentPhase above an earlier phase already back in PENDING.
    state["currentPhase"] = min(int(state.get("currentPhase", phase)), phase)
    for result_key in EVIDENCE_RESULT_KEYS:
        entries = state.get(result_key)
        if isinstance(entries, list):
            state[result_key] = [entry for entry in entries
                                 if not (isinstance(entry, dict)
                                         and str(entry.get("phase", "")) == str(phase))]
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


def set_handoff(state: dict, status: str, *, terminal_handle: Optional[str] = None,
                worktree_path: Optional[str] = None,
                source_session: Optional[str] = None,
                why: Optional[str] = None) -> dict:
    """Record a handoff lifecycle step on the state (pending → accepted, or
    failed/uncertain when the Orca launch could not be trusted, or skipped
    when the handoff is not applicable — always with its reason).

    `pending` = a takeover has been prepared (handle present) or is being
    prepared (handle absent). `accepted` is only ever written by claim().
    """
    if status not in HANDOFF_STATUSES:
        raise ValueError(f"handoff status must be one of {list(HANDOFF_STATUSES)}")
    if status == "accepted":
        # Acceptance only flows through claim_handoff (session is mandatory there).
        raise ValueError("use claim_handoff() to record an accepted takeover")
    block = {
        "status": status,
        "at": _now_iso(),
        "terminalHandle": terminal_handle,
        "worktreePath": worktree_path,
        "session": source_session,
    }
    if why:
        block["why"] = why
    state["handoff"] = block
    state["updatedAt"] = state["handoff"]["at"]
    return state


def claim_handoff(state: dict, session: str, force: bool = False) -> str:
    """The taking-over session records itself as the mandate owner.

    - pending → accepted: the normal takeover (the originating session stopped
      driving the workflow when it marked pending).
    - uncertain → accepted: conscious recovery of an unverified mandate (the
      terminal was created but its handle was never recorded — SKILL.md Phase 2
      prescribes claim + resume from the worktree session in that case).
    - accepted + same session: idempotent re-claim (harmless).
    - accepted + different session: refused unless --force — a concurrent
      takeover must be a conscious recovery, never a silent race.
    """
    if not session or not str(session).strip():
        raise ValueError("claim requires a session label (e.g. pane:$ORCA_AGENT_PANE)")
    handoff = state.get("handoff") or {}
    status = handoff.get("status")
    if status == "accepted" and handoff.get("session") == session:
        return "already claimed (idempotent)"
    if status == "accepted" and handoff.get("session") and not force:
        raise ValueError(
            f"handoff already claimed by {handoff['session']!r} — pass --force for a "
            f"conscious recovery (journaled), never for a concurrent duplicate")
    if status not in ("pending", "accepted", "uncertain"):
        raise ValueError(f"no claimable handoff (status: {status or 'none'})")
    was = status
    handoff["status"] = "accepted"
    handoff["session"] = session
    handoff["claimedAt"] = _now_iso()
    state["handoff"] = handoff
    state["updatedAt"] = handoff["claimedAt"]
    return "claimed" if was in ("pending", "uncertain") else "recovered (forced)"


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
    if not problems:
        # Chronicle divergence is a WARNING, never a validation failure:
        # the state file is the transactional truth (see journal_problems).
        for problem in journal_problems(state, path):
            print(f"JOURNAL-WARNING: {problem}")
    print("state valid" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_resume(argv: List[str]) -> int:
    path, signature, worktree_missing = argv[0], "", False
    rest = argv[1:]
    session: Optional[str] = None
    while rest:
        flag = rest.pop(0)
        if flag == "--signature":
            signature = rest.pop(0)
        elif flag == "--worktree-missing":
            worktree_missing = True
        elif flag == "--session":
            session = rest.pop(0)
        else:
            print(f"ERROR: unknown flag {flag}")
            return 2
    state = load_state(path)
    problems = validate_state(state, path)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        return 1
    # Handoff awareness on stdout only for the plan; warnings go to stderr so
    # the machine-readable plan (stdout) stays parseable by tooling.
    handoff = state.get("handoff") or {}
    status = handoff.get("status")
    if status in ("pending", "uncertain"):
        print("HANDOFF-WARNING: takeover not confirmed "
              f"(status: {status}) — claim first if you are the target",
              file=sys.stderr)
    elif status == "accepted" and session and handoff.get("session") \
            and session != handoff["session"]:
        print(f"CONCURRENCY-WARNING: handoff claimed by {handoff['session']!r} — "
              "this resume may be concurrent; recovery is journaled via claim --force",
              file=sys.stderr)
    print(json.dumps(resume_plan(state, signature, worktree_exists=not worktree_missing), indent=2))
    return 0


def _int_arg(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{label} must be an integer (got {value!r})") from None


def _canonical_write_guard(path: str) -> Optional[str]:
    """Write commands only persist inside the canonical state dir (T-02).

    Three real executions created three different directories because no
    path was enforced; this guard makes the divergence impossible.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if os.path.abspath(parent) != os.path.abspath(state_dir()):
        return (f"ERROR: state file must live in the canonical dir {state_dir()} "
                f"(got {parent}) — set TW_STATE_STATE_DIR to override for tests/pilots")
    return None


EVIDENCE_PHASES = {4: "testResults", 5: "qaResults", 6: "reviewResults"}
EVIDENCE_RESULT_KEYS = ("testResults", "qaResults", "reviewResults")
CHAIN_PHASES = (4, 5, 6, 7)  # code-bearing phases: their PASSED evidence must
# all refer to the SAME code state — a validation validates the code it ran on.


def _attached_results(state: dict, key: str, phase: int) -> list:
    """Evidence entries usable for a phase: attached to it (entry.phase),
    honest status, and a non-empty reason when the control was skipped —
    an unrecorded or unexplained control is never a passed one."""
    usable = []
    for entry in state.get(key, []):
        if not isinstance(entry, dict) or not entry.get("status"):
            continue
        if str(entry.get("phase", "")) != str(phase):
            continue  # evidence must be attached to the phase it proves
        if (str(entry.get("status", "")).lower() in ("skipped", "not-run")
                and not str(entry.get("reason", "")).strip()):
            continue  # a skip without a recorded reason proves nothing
        usable.append(entry)
    return usable


def evidence_guard(state: dict, phase: int, status: str,
                   signature: Optional[str]) -> Optional[str]:
    """Transition-level guard (cmd_mark only — existing states stay valid):
    a phase is PASSED only WITH evidence attached to IT, and code-bearing
    phases must share one signature — in BOTH directions (a later PASSED
    phase is stale evidence for an earlier re-run, not only the reverse)."""
    if status != "PASSED":
        return None
    key = EVIDENCE_PHASES.get(phase)
    if key and not _attached_results(state, key, phase):
        return (f"phase {phase} PASSED requires at least one structured entry in "
                f"{key} attached to it ({{\"phase\": {phase}, \"name\", \"status\", ...}}) — "
                f"a skipped/not-run entry needs a non-empty reason; an unrecorded "
                f"control is never a passed one")
    if phase in CHAIN_PHASES:
        if not signature:
            return (f"phase {phase} PASSED requires --signature — evidence must carry "
                    f"the code state it validates (tw_state.py signature <worktreePath>)")
        for other in CHAIN_PHASES:
            if other == phase:
                continue
            entry = state.get("phaseStatuses", {}).get(str(other), {})
            if (entry.get("status") == "PASSED" and entry.get("codeSignature")
                    and entry["codeSignature"] != signature):
                return (f"phase {other} PASSED carries a different codeSignature — its "
                        f"evidence is stale for this code: invalidate it and re-run the "
                        f"impacted controls before marking phase {phase} PASSED")
    return None


def cmd_mark(argv: List[str]) -> int:
    try:
        phase = _int_arg(argv[1], "phase")
    except ValueError as error:
        print(f"ERROR: {error}")
        return 2
    path, status = argv[0], argv[2]
    rest = argv[3:]
    signature: Optional[str] = None
    actor = "orchestrator"
    while rest:
        flag = rest.pop(0)
        if flag == "--signature":
            signature = rest.pop(0)
        elif flag == "--actor":
            actor = rest.pop(0)
    guard = _canonical_write_guard(path)
    if guard:
        print(guard)
        return 1
    state = load_state(path)
    violation = evidence_guard(state, phase, status, signature)
    if violation:
        print(f"ILLEGAL: {violation}")
        return 1
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
    # Chronicle: append AFTER the state commit — the journal never blocks the
    # transaction and a lost append is surfaced by `validate` as a warning.
    try:
        append_event(path, {"type": "phase", "phase": phase, "status": status,
                            "actor": actor, "at": state["phaseStatuses"][str(phase)]["at"]})
    except (OSError, ValueError) as error:
        print(f"JOURNAL-WARNING: transition event not recorded ({error})")
    return 0


def cmd_invalidate(argv: List[str]) -> int:
    try:
        phase = _int_arg(argv[1], "phase")
    except ValueError as error:
        print(f"ERROR: {error}")
        return 2
    path = argv[0]
    guard = _canonical_write_guard(path)
    if guard:
        print(guard)
        return 1
    state = load_state(path)
    purged = sum(1 for result_key in EVIDENCE_RESULT_KEYS
                 for entry in state.get(result_key, [])
                 if isinstance(entry, dict)
                 and str(entry.get("phase", "")) == str(phase))
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
    print(f"phase {phase} invalidated -> PENDING"
          + (f" ({purged} recorded result(s) purged)" if purged else ""))
    try:
        append_event(path, {"type": "phase", "phase": phase, "status": "PENDING",
                            "actor": "orchestrator", "at": state["phaseStatuses"][str(phase)]["at"],
                            "note": "invalidated (STALE or rework)"})
    except (OSError, ValueError) as error:
        print(f"JOURNAL-WARNING: transition event not recorded ({error})")
    return 0


def cmd_handoff(argv: List[str]) -> int:
    path, status = argv[0], argv[1]
    rest = argv[2:]
    handle = wpath = why = None
    while rest:
        flag = rest.pop(0)
        if flag == "--handle":
            handle = rest.pop(0)
        elif flag == "--path":
            wpath = rest.pop(0)
        elif flag == "--why":
            why = rest.pop(0)
        else:
            print(f"ERROR: unknown flag {flag}")
            return 2
    guard = _canonical_write_guard(path)
    if guard:
        print(guard)
        return 1
    state = load_state(path)
    try:
        set_handoff(state, status, terminal_handle=handle, worktree_path=wpath, why=why)
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
    detail = f" (terminal {handle})" if handle else ""
    print(f"handoff -> {status}{detail}")
    # Chronicle after the commit (same rule as mark): informative, never blocking.
    try:
        append_event(path, {"type": "command", "phase": 2, "actor": "orchestrator",
                            "at": state["handoff"]["at"],
                            "summary": f"handoff {status}{detail}"})
    except (OSError, ValueError) as error:
        print(f"JOURNAL-WARNING: handoff event not recorded ({error})")
    return 0


def cmd_claim(argv: List[str]) -> int:
    path = argv[0]
    rest = argv[1:]
    session: Optional[str] = None
    force = False
    while rest:
        flag = rest.pop(0)
        if flag == "--session":
            session = rest.pop(0)
        elif flag == "--force":
            force = True
        else:
            print(f"ERROR: unknown flag {flag}")
            return 2
    if not session:
        print("ERROR: --session <label> required (e.g. pane:$ORCA_AGENT_PANE)")
        return 2
    guard = _canonical_write_guard(path)
    if guard:
        print(guard)
        return 1
    state = load_state(path)
    try:
        outcome = claim_handoff(state, session, force=force)
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
    print(f"handoff {outcome} by {session}")
    try:
        # A forced recovery is an incident-class chronicle entry (type
        # "recovery"), the normal claim stays a plain command.
        forced = "recovered" in outcome
        append_event(path, {"type": "recovery" if forced else "command", "phase": 2,
                            "actor": session,
                            "at": state["handoff"]["claimedAt"],
                            "summary": f"handoff {outcome}",
                            **({"note": "concurrent-takeover recovery"} if forced else {})})
    except (OSError, ValueError) as error:
        print(f"JOURNAL-WARNING: claim event not recorded ({error})")
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


def cmd_resolve(argv: List[str]) -> int:
    """Print the state-file path for a task URL (any URL form), or nothing."""
    try:
        path = resolve_state(argv[0], argv[1])
    except ValueError as error:
        print(f"ERROR: {error}")
        return 1
    print(path if path else "")
    return 0


def cmd_log(argv: List[str]) -> int:
    """Append a structured event to the workflow journal (chronicle, not truth)."""
    path = argv[0]
    rest = argv[1:]
    event: dict = {"type": "note", "actor": "orchestrator"}
    try:
        while rest:
            flag = rest.pop(0)
            if flag == "--type":
                event["type"] = rest.pop(0)
            elif flag == "--phase":
                event["phase"] = _int_arg(rest.pop(0), "--phase")
            elif flag == "--status":
                event["status"] = rest.pop(0)
            elif flag == "--actor":
                event["actor"] = rest.pop(0)
            elif flag == "--summary":
                event["summary"] = rest.pop(0)
            elif flag == "--exit-code":
                event["exitCode"] = _int_arg(rest.pop(0), "--exit-code")
            elif flag == "--evidence":
                event["evidence"] = rest.pop(0)
            elif flag == "--attempt":
                event["attempt"] = _int_arg(rest.pop(0), "--attempt")
            elif flag == "--note":
                event["note"] = rest.pop(0)
    except ValueError as error:
        print(f"ERROR: {error}")
        return 2
    guard = _canonical_write_guard(path)
    if guard:
        print(guard)
        return 1
    try:
        recorded = append_event(path, event)
    except ValueError as error:
        print(f"ERROR: {error}")
        return 1
    print(f"event seq {recorded['seq']} recorded ({recorded['type']})")
    return 0


def cmd_validate_all(argv: List[str]) -> int:
    """Scan the canonical dir: every state must be valid AND correctly named.

    Surfaced the a1b2c3d4-style hand-written placeholders that used to sleep
    next to real states (T-05). Exit 1 if any problem — for pre-resume checks.
    """
    directory = argv[0] if argv else state_dir()
    if not os.path.isdir(directory):
        print(f"no state dir at {directory} — nothing to validate")
        return 0
    count = 0
    problems_found = 0
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        count += 1
        path = os.path.join(directory, name)
        try:
            state = load_state(path)
            problems = validate_state(state, path)
        except (OSError, ValueError) as error:
            # A corrupt state file is exactly what validate-all exists to surface.
            problems_found += 1
            print(f"PROBLEM {name}: unreadable or corrupt state file ({error})")
            continue
        for problem in problems:
            problems_found += 1
            print(f"PROBLEM {name}: {problem}")
    print(f"{count} state(s) checked, {problems_found} problem(s)")
    return 1 if problems_found else 0


def main(argv: List[str]) -> int:
    if not argv:
        print("usage: tw_state.py validate|resume|mark|invalidate|signature|id"
              "|resolve|log|validate-all|handoff|claim ...", file=sys.stderr)
        return 2
    command = argv[0]
    if command == "validate-all":  # optional argument — canonical dir by default
        return cmd_validate_all(argv[1:])
    if len(argv) < 2:
        print("usage: tw_state.py validate|resume|mark|invalidate|signature|id"
              "|resolve|log|validate-all|handoff|claim ...", file=sys.stderr)
        return 2
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
    if command == "resolve":
        return cmd_resolve(argv[1:])
    if command == "log":
        return cmd_log(argv[1:])
    if command == "handoff":
        return cmd_handoff(argv[1:])
    if command == "claim":
        return cmd_claim(argv[1:])
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
