#!/usr/bin/env python3
"""Deterministic contract for the design-qa skill (stdlib only, Python 3.9+).

v2 — convergence loop. The MR gate is no longer a status counter: a PASSED
verdict REQUIRES proven convergence — an iteration history whose LAST
iteration is a full visual audit (Designer + DOM) of the rendering at the
CURRENT code signature, cross-checked against the findings file. A finding
can only be `fixed` when a later audit observed its resolution (reconcile);
a previously-fixed issue seen again becomes `reopened`. Figma URL parsing,
contract validation and the final report complete the contract. No network,
no browser, no image processing — multimodal/visual work is delegated
(Designer, chrome-devtools, ImageMagick) and lands here as data only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
HISTORY_SCHEMA_VERSION = 1
SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "INFO")
# `reopened` = a previously fixed issue observed again by a later audit.
FINDING_STATUS = ("open", "fixed", "reopened", "waived", "invalid")
# Blocking statuses: anything else (fixed/waived/invalid) is resolved —
# but `fixed` is only trusted after cross-check against the last audit.
BLOCKING_STATUS_EXEMPT = ("fixed", "waived", "invalid")
CONFIDENCE = ("measured", "estimated", "uncertain")
ORIGINS = ("initial", "new", "reopened")
CATEGORIES = (
    "structure", "component", "content", "action", "state",
    "layout", "typography", "color", "spacing", "responsive", "data", "external",
)
CONTRACT_REQUIRED = ("schemaVersion", "page", "reference", "viewport", "sections")
REFERENCE_SOURCES = ("figma", "image")
FINDING_REQUIRED = (
    "id", "category", "severity", "component", "description",
    "expected", "actual", "evidence", "confidence", "recommendation", "status",
)
FIGMA_HOSTS = ("figma.com", "www.figma.com")
AUDIT_TYPES = ("full", "dom-only", "visual-only")
# A "full" audit (the only kind that can prove visual conformity) must
# include a fresh Designer analysis AND a DOM/CSS inspection.
DEFAULT_MAX_ITERATIONS = 5
# External limitations visible in the UI (out of dev scope, never silent).
EXTERNAL_CATEGORIES = ("data", "external")
OPEN_STATUSES = ("open", "reopened")
# Fields the gate reads to decide — immutable between audits (cross-check
# rejects any post-audit tampering, e.g. a severity downgrade).
GATE_RELEVANT_FIELDS = ("severity", "category", "confidence")


def new_run_id(reference: str, application: str) -> str:
    """Deterministic evidence dir id: dq-<hash8(ref + application url)>."""
    digest = hashlib.sha1(f"{reference}|{application}".encode("utf-8")).hexdigest()[:8]
    return f"dq-{digest}"


def parse_figma_url(url: str) -> Dict[str, Optional[str]]:
    """Parse a Figma design/file URL into {fileKey, nodeId}.

    node-id uses '-' in URLs and ':' in the API — normalized here.
    Raises ValueError on non-Figma or malformed URLs (fail-closed).
    """
    match = re.match(r"https?://([^/]+)/", url.strip())
    if not match or match.group(1) not in FIGMA_HOSTS:
        raise ValueError(f"not a figma.com URL: {url}")
    path = url.split(match.group(1), 1)[1]
    file_match = re.match(r"/(?:design|file|proto)/([A-Za-z0-9]+)", path)
    if not file_match:
        raise ValueError(f"no file key in URL path: {path}")
    node_id: Optional[str] = None
    query_match = re.search(r"[?&]node-id=([0-9]+)-([0-9]+)", url)
    if query_match:
        node_id = f"{query_match.group(1)}:{query_match.group(2)}"
    return {"fileKey": file_match.group(1), "nodeId": node_id}


def _is_iso(value: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(value)))


# ─── Design Contract ─────────────────────────────────────────────────────────

def validate_contract(contract: Any) -> List[str]:
    """Return a list of problems (empty list = valid Design Contract)."""
    problems: List[str] = []
    if not isinstance(contract, dict):
        return ["contract is not a JSON object"]
    for key in CONTRACT_REQUIRED:
        if key not in contract:
            problems.append(f"missing required key: {key}")
    if problems:
        return problems
    schema_version = contract["schemaVersion"]
    if isinstance(schema_version, bool) or schema_version != SCHEMA_VERSION:
        problems.append(f"schemaVersion must be {SCHEMA_VERSION}")
    page = contract.get("page")
    if not isinstance(page, str) or not page.strip():
        problems.append("page must be a non-empty string")

    reference = contract.get("reference")
    if not isinstance(reference, dict):
        problems.append("reference must be an object")
    else:
        if reference.get("source") not in REFERENCE_SOURCES:
            problems.append(f"reference.source must be in {list(REFERENCE_SOURCES)}")
        has_url = isinstance(reference.get("url"), str) and reference["url"].strip()
        has_image = isinstance(reference.get("imagePath"), str) and reference["imagePath"].strip()
        if not has_url and not has_image:
            problems.append("reference needs url (figma) or imagePath (screenshot)")
        if "valuesAvailable" not in reference:
            problems.append("reference.valuesAvailable must be set (exact figma values or not)")
        elif not isinstance(reference["valuesAvailable"], bool):
            problems.append("reference.valuesAvailable must be a boolean")

    viewport = contract.get("viewport")
    if not isinstance(viewport, dict) or type(viewport.get("width")) is not int \
            or type(viewport.get("height")) is not int:
        problems.append("viewport must be {width: int, height: int}")

    sections = contract.get("sections")
    if not isinstance(sections, list) or not sections:
        problems.append("sections must be a non-empty list")
    else:
        for index, section in enumerate(sections):
            if not isinstance(section, dict) or not isinstance(section.get("name"), str) \
                    or not section.get("name", "").strip():
                problems.append(f"sections[{index}].name missing")
            if not isinstance(section, dict) or type(section.get("order")) is not int:
                problems.append(f"sections[{index}].order must be an integer")
            if not isinstance(section, dict) or "required" not in section:
                problems.append(f"sections[{index}].required missing")

    for field in ("criteria", "assumptions", "poQuestions", "dataDeps"):
        value = contract.get(field)
        if value is not None and not isinstance(value, list):
            problems.append(f"{field} must be a list when present")
    for entry in contract.get("criteria", []) or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) \
                or not entry.get("id", "").strip() \
                or entry.get("kind") not in ("exact", "semantic"):
            problems.append(f"invalid criteria entry: {entry!r}")
    return problems


# ─── Findings ────────────────────────────────────────────────────────────────

def validate_findings(findings: Any) -> List[str]:
    """Return a list of problems (empty list = valid findings list)."""
    problems: List[str] = []
    if not isinstance(findings, list):
        return ["findings is not a JSON array"]
    ids: set = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            problems.append(f"findings[{index}] is not an object")
            continue
        for key in FINDING_REQUIRED:
            if key not in finding:
                problems.append(f"findings[{index}] missing required key: {key}")
        fid_raw = finding.get("id")
        fid = str(fid_raw) if isinstance(fid_raw, str) else f"#{index}"
        if isinstance(fid_raw, str):
            # Duplicate detection depends only on the current finding.
            if fid in ids:
                problems.append(f"duplicate finding id: {fid}")
            ids.add(fid)
        if finding.get("severity") not in SEVERITIES:
            problems.append(f"{fid}: severity must be in {list(SEVERITIES)}")
        if finding.get("status") not in FINDING_STATUS:
            problems.append(f"{fid}: status must be in {list(FINDING_STATUS)}")
        if finding.get("confidence") not in CONFIDENCE:
            problems.append(f"{fid}: confidence must be in {list(CONFIDENCE)}")
        if finding.get("category") not in CATEGORIES:
            problems.append(f"{fid}: category must be in {list(CATEGORIES)}")
        if finding.get("status") == "waived":
            if finding.get("waivedBy") != "HUMAN":
                problems.append(f"{fid}: waived requires waivedBy == HUMAN (explicit human trace)")
            if not isinstance(finding.get("waivedReason"), str) or not finding["waivedReason"].strip():
                problems.append(f"{fid}: waived requires a non-empty waivedReason")
        if finding.get("status") == "invalid":
            # Same human-trace bar as waived: an untraceable `invalid` would
            # be an escape hatch to a fake PASSED (R1).
            if finding.get("invalidBy") != "HUMAN":
                problems.append(f"{fid}: invalid requires invalidBy == HUMAN (explicit human trace)")
            if not isinstance(finding.get("invalidReason"), str) or not finding["invalidReason"].strip():
                problems.append(f"{fid}: invalid requires a non-empty invalidReason")
        if finding.get("status") == "fixed" and not _is_iso(str(finding.get("fixedAt", ""))):
            problems.append(f"{fid}: fixed requires an ISO-8601 fixedAt (re-check trace)")
        if finding.get("status") == "reopened" and not _is_iso(str(finding.get("reopenedAt", ""))):
            problems.append(f"{fid}: reopened requires an ISO-8601 reopenedAt")
        origin = finding.get("origin")
        if origin is not None and origin not in ORIGINS:
            problems.append(f"{fid}: origin must be in {list(ORIGINS)}")
        confirmed_in = finding.get("confirmedIn")
        if confirmed_in is not None and (type(confirmed_in) is not int or confirmed_in < 0):
            problems.append(f"{fid}: confirmedIn must be a non-negative integer (confirming audit index)")
    return problems


def observed_counts(findings: List[dict]) -> Dict[str, int]:
    """Per-severity counts of findings currently observed in the rendering
    (open + reopened) — waived, fixed and invalid are not observed."""
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        if finding.get("status") in OPEN_STATUSES:
            counts[finding.get("severity", "INFO")] = counts.get(finding.get("severity", "INFO"), 0) + 1
    return counts


# ─── Iteration history (convergence) ─────────────────────────────────────────

def validate_history(history: Any) -> List[str]:
    """Return a list of problems (empty list = valid iteration history)."""
    problems: List[str] = []
    if not isinstance(history, dict):
        return ["history is not a JSON object"]
    if history.get("schemaVersion") != HISTORY_SCHEMA_VERSION:
        problems.append(f"history schemaVersion must be {HISTORY_SCHEMA_VERSION}")
    if not isinstance(history.get("runId"), str) or not re.match(r"^(dq|tw)-[a-z0-9-]+$", str(history.get("runId"))):
        problems.append("history runId must match dq-… or tw-… pattern")
    iterations = history.get("iterations")
    if not isinstance(iterations, list) or not iterations:
        problems.append("history iterations must be a non-empty list")
        return problems
    max_iterations = history.get("maxIterations", DEFAULT_MAX_ITERATIONS)
    if type(max_iterations) is not int or max_iterations < 1:
        problems.append("maxIterations must be a positive integer")
    last_index: Optional[int] = None
    for index, iteration in enumerate(iterations):
        label = f"iterations[{index}]"
        if not isinstance(iteration, dict):
            problems.append(f"{label} is not an object")
            continue
        iter_index = iteration.get("index")
        if type(iter_index) is not int:
            problems.append(f"{label}.index must be an integer")
        elif last_index is not None and iter_index <= last_index:
            problems.append(f"{label}.index must be strictly ascending (got {iter_index} after {last_index})")
        else:
            last_index = iter_index
        if not isinstance(iteration.get("codeSignature"), str) or not iteration["codeSignature"].strip():
            problems.append(f"{label}.codeSignature missing")
        for path_key in ("capturePath", "diffPath", "findingsPath"):
            if not isinstance(iteration.get(path_key), str) or not iteration[path_key].strip():
                problems.append(f"{label}.{path_key} missing (evidence is kept per iteration, never overwritten)")
        audit = iteration.get("audit")
        if not isinstance(audit, dict) or audit.get("type") not in AUDIT_TYPES:
            problems.append(f"{label}.audit.type must be in {list(AUDIT_TYPES)}")
        elif audit.get("type") == "full" and (audit.get("designerAnalysis") is not True
                                              or audit.get("domInspection") is not True):
            problems.append(f"{label}.audit: a full audit requires designerAnalysis AND domInspection")
        counts = iteration.get("counts")
        if not isinstance(counts, dict) or any(type(counts.get(s)) is not int for s in SEVERITIES):
            problems.append(f"{label}.counts must provide integer counts for {list(SEVERITIES)}")
    return problems


def cross_check(findings: List[dict], snapshot: List[dict]) -> List[str]:
    """Anti-fake check: the findings file vs the LAST audit's snapshot.

    The findings file may only diverge from the last audit snapshot by
    HUMAN decisions (waived/invalid — each requiring its explicit trace).
    Anything else is rejected: a status change without a new audit (the
    exact false-conformity bug) AND any tampering with gate-relevant data
    (severity/category/confidence — e.g. a post-audit downgrade of an open
    BLOCKER to INFO would otherwise fake a PASSED).
    """
    problems: List[str] = []
    snapshot_by_id = {f.get("id"): f for f in snapshot if isinstance(f, dict)}
    findings_by_id = {f.get("id"): f for f in findings if isinstance(f, dict)}
    for fid, snap in snapshot_by_id.items():
        entry = findings_by_id.get(fid)
        if entry is None:
            problems.append(f"{fid}: present in the last audit snapshot but missing from the findings file")
            continue
        for field in GATE_RELEVANT_FIELDS:
            if entry.get(field) != snap.get(field):
                problems.append(
                    f"{fid}: {field} changed after the last audit without a new audit observation "
                    f"({snap.get(field)} -> {entry.get(field)}) — gate-relevant data is immutable "
                    f"between audits"
                )
        if entry.get("status") != snap.get("status"):
            if entry.get("status") == "waived" and finding_has_human_trace(entry, "waived"):
                continue  # documented human decision
            if entry.get("status") == "invalid" and finding_has_human_trace(entry, "invalid"):
                continue  # documented human decision
            problems.append(
                f"{fid}: status changed after the last audit without a new audit observation "
                f"({snap.get('status')} -> {entry.get('status')}) — resolution must be confirmed by a "
                f"new audit, and human decisions require their trace"
            )
    for fid in findings_by_id:
        if fid not in snapshot_by_id:
            problems.append(f"{fid}: not observed by the last audit — new findings require a new audit iteration")
    return problems


def finding_has_human_trace(entry: dict, kind: str) -> bool:
    """True when the waived/invalid entry carries its explicit human trace."""
    actor = entry.get(f"{kind}By")
    reason = entry.get(f"{kind}Reason")
    return actor == "HUMAN" and isinstance(reason, str) and bool(reason.strip())


def reconcile(previous: List[dict], observations: List[dict], iteration: int,
              at: str) -> Tuple[List[dict], List[str]]:
    """Reconcile the previous findings with a NEW full audit's observations.

    Returns (reconciled_findings, notes). Rules:
    - observed again while previously fixed  -> reopened (regression)
    - observed again while open              -> stays open
    - NOT observed while previously open     -> fixed (confirmed BY the audit,
      never by a code change alone) with confirmedIn = iteration
    - NOT observed while previously fixed    -> stays fixed + confirmedIn
    - waived/invalid                         -> untouched (human decisions stand)
    - ids absent from previous               -> added with origin "new"
    """
    if type(iteration) is not int or iteration < 0:
        raise ValueError("iteration must be a non-negative integer")
    notes: List[str] = []
    previous_by_id = {f.get("id"): dict(f) for f in previous if isinstance(f, dict)}
    observed_ids = {f.get("id") for f in observations if isinstance(f, dict)}
    reconciled: List[dict] = []
    for fid, prev in previous_by_id.items():
        entry = dict(prev)
        status = entry.get("status")
        if status in ("waived", "invalid"):
            reconciled.append(entry)
            continue
        if fid in observed_ids:
            if status == "fixed":
                entry["status"] = "reopened"
                entry["reopenedAt"] = at
                entry["origin"] = "reopened"
                notes.append(f"{fid}: reopened — regression observed by audit {iteration}")
            else:
                entry["status"] = "open"
                notes.append(f"{fid}: still observed (open) at audit {iteration}")
        else:
            if status in OPEN_STATUSES:
                entry["status"] = "fixed"
                entry["fixedAt"] = at
                notes.append(f"{fid}: fixed — confirmed by audit {iteration} observation")
            else:
                notes.append(f"{fid}: still absent — remains fixed (confirmed by audit {iteration})")
            entry["confirmedIn"] = iteration
        reconciled.append(entry)
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        fid = obs.get("id")
        if fid in previous_by_id:
            continue
        entry = dict(obs)
        entry["origin"] = "new"
        if entry.get("status") not in OPEN_STATUSES:
            entry["status"] = "open"  # a fresh observation is open by definition
        reconciled.append(entry)
        notes.append(f"{fid}: new finding discovered by audit {iteration}")
    return reconciled, notes


def has_progress(previous_counts: Dict[str, int], current_counts: Dict[str, int]) -> bool:
    """Measurable progress between two audits: fewer observed findings in
    total AND no regression in BLOCKER/MAJOR (per-severity — never a global
    score that could hide a critical regression)."""
    blocking_severities = ("BLOCKER", "MAJOR")
    total_keys = ("BLOCKER", "MAJOR", "MINOR")
    prev_total = sum(previous_counts.get(s, 0) for s in total_keys)
    curr_total = sum(current_counts.get(s, 0) for s in total_keys)
    if curr_total >= prev_total:
        return False
    return all(current_counts.get(s, 0) <= previous_counts.get(s, 0) for s in blocking_severities)


def convergence_check(history: dict, current_signature: Optional[str]) -> Dict[str, Any]:
    """Verify the convergence loop guarantees (garde-fous) on the history."""
    iterations: List[dict] = history.get("iterations", [])
    last = iterations[-1]
    last_audit = last.get("audit", {})
    result: Dict[str, Any] = {"ok": True, "status": "ok", "reason": "",
                              "iterations": len(iterations),
                              "finalAudit": {"index": last.get("index"), "type": last_audit.get("type")}}
    if last_audit.get("type") != "full":
        result.update(ok=False, status="not-full-audit",
                      reason="the last iteration is not a full visual audit — PASSED requires a full "
                             "Designer + DOM audit of the final rendering")
        return result
    if not current_signature:
        result.update(ok=False, status="unbound",
                      reason="current code signature required — a verdict must be bound to the exact code version")
        return result
    if current_signature != last.get("codeSignature"):
        result.update(ok=False, status="stale",
                      reason=f"code changed after the final audit ({last.get('codeSignature')} -> {current_signature}) "
                             f"— the verification is invalidated, re-run the design QA")
        return result
    if len(iterations) >= history.get("maxIterations", DEFAULT_MAX_ITERATIONS):
        remaining = last.get("counts", {})
        open_total = sum(remaining.get(s, 0) for s in ("BLOCKER", "MAJOR", "MINOR"))
        if open_total > 0:
            result.update(ok=False, status="max-iterations",
                          reason=f"max iterations reached with {open_total} observed finding(s) — "
                                 f"the iteration limit is a protection, never a success criterion")
            return result
    if len(iterations) >= 3:
        # The stall guard only applies while criteria remain unsatisfied —
        # a converged run (nothing observed anymore) has nothing to stall on.
        remaining = last.get("counts", {})
        open_total = sum(remaining.get(s, 0) for s in ("BLOCKER", "MAJOR", "MINOR"))
        if open_total > 0:
            no_progress_streak = 0
            for prev_iter, curr_iter in zip(iterations[-3:], iterations[-2:]):
                if not has_progress(prev_iter.get("counts", {}), curr_iter.get("counts", {})):
                    no_progress_streak += 1
                else:
                    no_progress_streak = 0
            if no_progress_streak >= 2:
                result.update(ok=False, status="stalled",
                              reason="2 consecutive iterations without measurable progress — stopping the loop "
                                     "(a protection, never a success criterion)")
                return result
    return result


def criteria_coverage(contract: dict, history: dict) -> List[str]:
    """Every contract criterion must be verified (or carry a finding) —
    checked against the LAST full audit's criteriaVerified list."""
    problems: List[str] = []
    criteria = contract.get("criteria", []) or []
    if not criteria:
        return problems
    iterations = history.get("iterations", [])
    last = iterations[-1] if iterations else {}
    verified = set(last.get("criteriaVerified", []) or [])
    for entry in criteria:
        cid = entry.get("id") if isinstance(entry, dict) else None
        if cid and cid not in verified:
            problems.append(f"criterion {cid} not verified by the final audit")
    return problems


# ─── Gate ────────────────────────────────────────────────────────────────────

def gate(findings: List[dict], reference_available: bool = True,
         history: Optional[dict] = None, current_signature: Optional[str] = None,
         contract: Optional[dict] = None) -> Dict[str, Any]:
    """MR-gate verdict — convergence-aware (v2).

    BLOCKED as soon as a BLOCKER or MAJOR is not resolved (open/reopened).
    A PASSED additionally REQUIRES proven convergence: an iteration history
    whose last iteration is a full visual audit (Designer + DOM) of the
    rendering at the CURRENT code signature, cross-checked against the
    findings file, with every contract criterion verified when a contract
    is provided. Without that proof the verdict is BLOCKED — never PASSED.
    """
    if not reference_available:
        return {"verdict": "SKIPPED", "blocking": [], "remaining": {}, "needsConfirmation": [],
                "convergence": None,
                "reason": "no usable visual reference — functional QA remains the only gate"}
    blocking: List[str] = []
    needs_confirmation: List[str] = []
    remaining: Dict[str, int] = {severity: 0 for severity in SEVERITIES}
    applied = 0
    for finding in findings:
        status = finding.get("status")
        severity = finding.get("severity")
        if status == "fixed":
            applied += 1
            continue
        if status in ("waived", "invalid"):
            continue
        # Anything else (open, reopened, typo, missing) counts as open — fail-closed.
        remaining[severity] = remaining.get(severity, 0) + 1
        if severity in ("BLOCKER", "MAJOR"):
            blocking.append(finding.get("id"))
        if finding.get("confidence") == "uncertain":
            needs_confirmation.append(finding.get("id"))

    convergence: Dict[str, Any] = {"proven": False}
    unproven_reason = ""
    if history is None:
        unproven_reason = ("no iteration history — PASSED requires a full visual audit of the final "
                           "rendering (convergence unproven)")
    else:
        problems = validate_history(history)
        if problems:
            unproven_reason = f"invalid iteration history: {'; '.join(problems[:3])}"
        else:
            iterations = history.get("iterations", [])
            last = iterations[-1]
            snapshot_path = last.get("findingsPath")
            snapshot = None
            if snapshot_path and os.path.exists(snapshot_path):
                snapshot = load(snapshot_path)
                snapshot_problems = validate_findings(snapshot)
                if snapshot_problems:
                    unproven_reason = f"last audit snapshot invalid: {snapshot_problems[0]}"
                else:
                    cross_problems = cross_check(findings, snapshot)
                    if cross_problems:
                        unproven_reason = f"findings inconsistent with the last audit: {cross_problems[0]}"
                    else:
                        # The claimed counts must match what the snapshot
                        # actually contains — recomputed, never trusted.
                        recomputed = observed_counts(snapshot)
                        claimed = last.get("counts", {})
                        if any(recomputed[s] != claimed.get(s, -1) for s in SEVERITIES):
                            unproven_reason = (f"last iteration counts {claimed} do not match its "
                                               f"snapshot {recomputed} — history metadata is tampered")
            elif snapshot_path:
                unproven_reason = f"last audit snapshot not found: {snapshot_path} (evidence must be kept)"
            else:
                unproven_reason = "last iteration has no findings snapshot"
            if not unproven_reason:
                check = convergence_check(history, current_signature)
                convergence.update({"status": check["status"], "iterations": check["iterations"],
                                    "finalAudit": check["finalAudit"]})
                if not check["ok"]:
                    unproven_reason = check["reason"]
                elif contract is not None:
                    coverage_problems = criteria_coverage(contract, history)
                    if coverage_problems:
                        unproven_reason = "; ".join(coverage_problems)
                        convergence["status"] = "criteria-unverified"

    # Single point of truth: proven means every convergence guarantee held.
    convergence["proven"] = not unproven_reason
    if unproven_reason:
        return {"verdict": "BLOCKED", "blocking": blocking, "remaining": remaining,
                "applied": applied, "needsConfirmation": needs_confirmation,
                "convergence": convergence, "reason": unproven_reason}

    verdict = "BLOCKED" if blocking else "PASSED"
    return {"verdict": verdict, "blocking": blocking, "remaining": remaining,
            "applied": applied, "needsConfirmation": needs_confirmation,
            "convergence": convergence, "reason": ""}


# ─── Report ──────────────────────────────────────────────────────────────────

def render_report(summary: Dict[str, Any], contract: Dict[str, Any], findings: List[dict],
                  history: Optional[dict] = None) -> str:
    """Render the final report (iteration timeline + conformity sections)."""
    if not isinstance(summary, dict):
        return "DESIGN QA — FAILED\n\nReason: invalid summary (not a JSON object)"
    if summary.get("processStatus") == "failed":
        return f"DESIGN QA — FAILED\n\nReason: {summary.get('processReason', 'unspecified')}"
    reference = contract.get("reference", {}) if isinstance(contract, dict) else {}
    has_reference = bool(reference.get("url") or reference.get("imagePath"))
    result = gate(findings, reference_available=has_reference, history=history,
                  current_signature=summary.get("signature"), contract=contract)
    tests = summary.get("tests", "skipped")
    if result["verdict"] == "BLOCKED":
        final = "BLOCKED"
    elif tests == "failed":
        final = "FAILED"
    else:
        final = result["verdict"]
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        counts[finding.get("severity", "INFO")] = counts.get(finding.get("severity", "INFO"), 0) + 1
    remaining = sum(result["remaining"].get(severity, 0) for severity in ("BLOCKER", "MAJOR", "MINOR"))
    captures = summary.get("captures", {}) if isinstance(summary.get("captures"), dict) else {}
    lines = [
        f"DESIGN QA — {final}",
        "",
        f"Reference:",
        f"  {reference.get('url') or reference.get('imagePath', '—')}",
        f"Application:",
        f"  {summary.get('application', '—')}",
        f"Viewport:",
        f"  {contract.get('viewport', {}).get('width', '?')} x {contract.get('viewport', {}).get('height', '?')}",
        f"Components checked:",
        f"  {summary.get('componentsChecked', 0)}",
    ]
    if history:
        lines.append("Iterations:")
        for iteration in history.get("iterations", []):
            c = iteration.get("counts", {})
            lines.append(f"  #{iteration.get('index')}: BLOCKER {c.get('BLOCKER', 0)} · "
                         f"MAJOR {c.get('MAJOR', 0)} · MINOR {c.get('MINOR', 0)} · INFO {c.get('INFO', 0)}"
                         f"  ({iteration.get('audit', {}).get('type', '?')} audit)")
    lines += [
        f"Findings:",
        f"  BLOCKER: {counts['BLOCKER']}  MAJOR: {counts['MAJOR']}  MINOR: {counts['MINOR']}  INFO: {counts['INFO']}",
        f"Corrections:",
        f"  Applied: {result.get('applied', 0)}  Remaining: {remaining}",
        f"Tests:",
        f"  {tests}",
    ]
    external = [f for f in findings
                if f.get("category") in EXTERNAL_CATEGORIES and f.get("status") in OPEN_STATUSES]
    lines.append("External limitations visible:")
    if external:
        for finding in external:
            lines.append(f"  {finding.get('id')} ({finding.get('severity')}): {finding.get('description')}")
    else:
        lines.append("  none")
    waived = [f for f in findings if f.get("status") == "waived"]
    lines.append("Accepted risks / PO decisions:")
    if waived:
        for finding in waived:
            lines.append(f"  {finding.get('id')} ({finding.get('severity')}): {finding.get('waivedReason')}")
    else:
        lines.append("  none")
    invalidated = [f for f in findings if f.get("status") == "invalid"]
    lines.append("Invalidated findings (human-confirmed false positives):")
    if invalidated:
        for finding in invalidated:
            lines.append(f"  {finding.get('id')} ({finding.get('severity')}): {finding.get('invalidReason')}")
    else:
        lines.append("  none")
    convergence = result.get("convergence") or {}
    lines.append("Convergence:")
    if convergence.get("proven"):
        lines.append(f"  PROVEN — {convergence.get('iterations', '?')} iteration(s), "
                     f"final full audit #{convergence.get('finalAudit', {}).get('index')} "
                     f"at current code signature")
    else:
        lines.append(f"  UNPROVEN — {result.get('reason', 'no iteration history')}")
    lines.append("Evidence:")
    for name in ("reference", "actual", "diff"):
        if captures.get(name):
            lines.append(f"  {name}: {captures[name]}")
    if result.get("blocking"):
        lines.append(f"Blocking findings: {', '.join(result['blocking'])}")
    if result.get("needsConfirmation"):
        lines.append(f"Needs confirmation before code change: {', '.join(result['needsConfirmation'])}")
    lines.append(f"Final result:")
    lines.append(f"  {final}")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save(path: str, data: Any) -> None:
    """Atomic write (temp file + os.replace) — a crash can never leave a
    half-written evidence file behind."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def _flags(argv: List[str]) -> Dict[str, Any]:
    flags: Dict[str, Any] = {}
    rest = list(argv)
    while rest:
        item = rest.pop(0)
        if item.startswith("--") and "=" in item:
            key, value = item[2:].split("=", 1)
            flags[key] = value
        elif item.startswith("--"):
            flags[item[2:]] = True
        else:
            flags.setdefault("positionals", []).append(item)
    return flags


def cmd_parse_figma_url(argv: List[str]) -> int:
    try:
        print(json.dumps(parse_figma_url(argv[0]), indent=2))
        return 0
    except ValueError as error:
        print(f"ERROR: {error}")
        return 1


def cmd_validate_contract(argv: List[str]) -> int:
    problems = validate_contract(load(argv[0]))
    for problem in problems:
        print(f"INVALID: {problem}")
    print("contract valid" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_validate_findings(argv: List[str]) -> int:
    problems = validate_findings(load(argv[0]))
    for problem in problems:
        print(f"INVALID: {problem}")
    print("findings valid" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_validate_history(argv: List[str]) -> int:
    problems = validate_history(load(argv[0]))
    for problem in problems:
        print(f"INVALID: {problem}")
    print("history valid" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_reconcile(argv: List[str]) -> int:
    flags = _flags(argv[1:])
    previous = load(argv[0])
    observations = load(argv[1])
    iteration = int(flags.get("iteration", 0))
    at = str(flags.get("at", ""))
    reconciled, notes = reconcile(previous, observations, iteration, at)
    # Pipe-friendly: stdout is the findings array itself (feed it straight
    # into history-append / gate); the audit-trail notes go to stderr.
    for note in notes:
        print(f"NOTE: {note}", file=sys.stderr)
    print(json.dumps(reconciled, indent=2))
    return 0


def cmd_history_append(argv: List[str]) -> int:
    """Append (or create) an iteration from the reconciled findings file.

    Creates the immutable per-iteration snapshot (findings-<N>.json next to
    the history file) and computes observed counts from the findings file.
    """
    flags = _flags(argv[1:])
    findings_path = argv[0]
    findings = load(findings_path)
    problems = validate_findings(findings)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        return 1
    signature = flags.get("signature")
    if not isinstance(signature, str) or not signature.strip():
        print("ERROR: --signature <sha> required (the verdict must be bound to a code version)")
        return 2
    capture = flags.get("capture")
    diff = flags.get("diff")
    audit_type = flags.get("audit", "full")
    if audit_type == "full" and (not capture or not diff):
        print("ERROR: a full audit requires --capture and --diff evidence paths")
        return 2
    # Evidence must exist on disk — a fabricated iteration pointing nowhere
    # is refused (fail-closed).
    for label, path in (("capture", capture), ("diff", diff)):
        if path and not os.path.exists(str(path)):
            print(f"ERROR: --{label} file not found: {path}")
            return 2
    history_path = flags.get("history")
    if not history_path:
        print("ERROR: --history <file> required")
        return 2
    history = load(history_path) if os.path.exists(history_path) else {
        "schemaVersion": HISTORY_SCHEMA_VERSION,
        "runId": flags.get("run-id", ""),
        "maxIterations": int(flags.get("max-iterations", DEFAULT_MAX_ITERATIONS)),
        "iterations": [],
    }
    if not history.get("runId"):
        print("ERROR: --run-id required on first append")
        return 2
    index = len(history["iterations"])
    base_dir = os.path.dirname(os.path.abspath(history_path))
    snapshot_path = os.path.join(base_dir, f"findings-{index}.json")
    # Evidence is append-only: an existing snapshot (e.g. crash orphan from
    # a partial append) is never silently overwritten.
    if os.path.exists(snapshot_path):
        print(f"ERROR: snapshot already exists, refusing to overwrite evidence: {snapshot_path}")
        return 1
    save(snapshot_path, findings)
    iteration = {
        "index": index,
        "codeSignature": signature,
        "capturePath": capture or "",
        "diffPath": diff or "",
        "findingsPath": snapshot_path,
        "audit": {"type": audit_type,
                  "designerAnalysis": flags.get("designer-analysis") is True,
                  "domInspection": flags.get("dom-inspection") is True},
        "counts": observed_counts(findings),
    }
    if flags.get("criteria"):
        iteration["criteriaVerified"] = [c.strip() for c in str(flags["criteria"]).split(",") if c.strip()]
    if flags.get("notes"):
        iteration["notes"] = str(flags["notes"])  # reconcile audit trail, persisted (R7)
    history["iterations"].append(iteration)
    problems = validate_history(history)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        os.remove(snapshot_path)
        return 1
    save(history_path, history)
    print(f"iteration {index} appended (audit: {audit_type}, counts: {iteration['counts']})")
    return 0


def cmd_gate(argv: List[str]) -> int:
    flags = _flags(argv[1:])
    findings = load(argv[0])
    problems = validate_findings(findings)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        return 1
    history = load(flags["iterations"]) if flags.get("iterations") else None
    contract = load(flags["contract"]) if flags.get("contract") else None
    signature = flags.get("signature") or None
    no_reference = flags.get("no-reference") is True
    result = gate(findings, reference_available=not no_reference, history=history,
                  current_signature=signature, contract=contract)
    print(json.dumps(result, indent=2))
    # Composable exit codes: 0 = nothing blocks the MR (PASSED or SKIPPED),
    # 3 = BLOCKED (fail-open-proof shell chaining), 1 = invalid input.
    return 3 if result["verdict"] == "BLOCKED" else 0


def cmd_report(argv: List[str]) -> int:
    summary = load(argv[0])
    base = argv[0].rsplit("/", 1)[0] + "/" if "/" in argv[0] else ""
    resolve = lambda p: p if str(p).startswith("/") else base + str(p)  # noqa: E731
    contract = load(resolve(summary.get("contract", "")))
    findings = load(resolve(summary.get("findings", "")))
    history = load(resolve(summary["history"])) if summary.get("history") else None
    for name, data, validator in (("contract", contract, validate_contract),
                                  ("findings", findings, validate_findings)):
        problems = validator(data)
        if problems:
            for problem in problems:
                print(f"INVALID ({name}): {problem}")
            return 1
    if history is not None:
        problems = validate_history(history)
        if problems:
            for problem in problems:
                print(f"INVALID (history): {problem}")
            return 1
    print(render_report(summary, contract, findings, history))
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: dq_contract.py parse-figma-url|validate-contract|validate-findings|validate-history"
              "|reconcile|history-append|gate|report ...", file=sys.stderr)
        return 2
    commands = {
        "parse-figma-url": (cmd_parse_figma_url, 1),
        "validate-contract": (cmd_validate_contract, 1),
        "validate-findings": (cmd_validate_findings, 1),
        "validate-history": (cmd_validate_history, 1),
        "reconcile": (cmd_reconcile, 2),
        "history-append": (cmd_history_append, 1),
        "gate": (cmd_gate, 1),
        "report": (cmd_report, 1),
    }
    entry = commands.get(argv[0])
    if not entry:
        print(f"unknown command: {argv[0]}", file=sys.stderr)
        return 2
    handler, minimum = entry
    if len(argv) - 1 < minimum:
        print(f"ERROR: {argv[0]} needs {minimum} argument(s)", file=sys.stderr)
        return 2
    try:
        return handler(argv[1:])
    except (OSError, json.JSONDecodeError, ValueError) as error:
        # Input errors are distinct from verdicts: exit 2, never a traceback.
        print(f"ERROR: cannot process input: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
