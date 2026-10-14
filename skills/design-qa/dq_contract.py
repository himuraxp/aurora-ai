#!/usr/bin/env python3
"""Deterministic contract for the design-qa skill (stdlib only, Python 3.9+).

Figma URL parsing, Design Contract validation, finding validation, the
MR-gate verdict (BLOCKED as soon as a confirmed BLOCKER/MAJOR stays open —
a waived finding requires an explicit human trace) and the final report.
No network, no browser, no image processing — the multimodal/visual parts
are delegated (Designer, chrome-devtools, ImageMagick) and only their
results land here as data. Tests use fixtures only (see tests/).
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "INFO")
FINDING_STATUS = ("open", "fixed", "waived", "invalid")
CONFIDENCE = ("measured", "estimated", "uncertain")
CATEGORIES = (
    "structure", "component", "content", "action", "state",
    "layout", "typography", "color", "spacing", "responsive", "data",
)
CONTRACT_REQUIRED = ("schemaVersion", "page", "reference", "viewport", "sections")
REFERENCE_SOURCES = ("figma", "image")
FINDING_REQUIRED = (
    "id", "category", "severity", "component", "description",
    "expected", "actual", "evidence", "confidence", "recommendation", "status",
)
FIGMA_HOSTS = ("figma.com", "www.figma.com")


def new_run_id(reference: str, application: str) -> str:
    """Deterministic evidence dir id: dq-<hash8(ref + application url)>."""
    import hashlib
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
            # Duplicate detection depends only on the current finding (R-07).
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
            if not str(finding.get("waivedReason", "")).strip():
                problems.append(f"{fid}: waived requires a non-empty waivedReason")
        if finding.get("status") == "fixed" and not _is_iso(str(finding.get("fixedAt", ""))):
            problems.append(f"{fid}: fixed requires an ISO-8601 fixedAt (re-check trace)")
    return problems


def gate(findings: List[dict], reference_available: bool = True) -> Dict[str, Any]:
    """MR-gate verdict from validated findings.

    BLOCKED as soon as a BLOCKER or MAJOR is not resolved. Fail-closed by
    default: any status other than fixed/waived/invalid counts as open
    (defense in depth — callers must validate first, but gate() can never
    under-block). Waived findings are excluded only when the human trace is
    complete (validated upstream). Uncertain open BLOCKER/MAJOR findings
    block AND are returned in needsConfirmation; MINOR/INFO uncertain are
    flagged without blocking.
    """
    if not reference_available:
        return {"verdict": "SKIPPED", "blocking": [], "remaining": {}, "needsConfirmation": [],
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
        # Anything else (open, typo, missing) counts as open — fail-closed.
        remaining[severity] = remaining.get(severity, 0) + 1
        if severity in ("BLOCKER", "MAJOR"):
            blocking.append(finding.get("id"))
        if finding.get("confidence") == "uncertain":
            needs_confirmation.append(finding.get("id"))
    return {
        "verdict": "BLOCKED" if blocking else "PASSED",
        "blocking": blocking,
        "remaining": remaining,
        "applied": applied,
        "needsConfirmation": needs_confirmation,
    }


def render_report(summary: Dict[str, Any], contract: Dict[str, Any], findings: List[dict]) -> str:
    """Render the final report (spec §11 format)."""
    if not isinstance(summary, dict):
        return "DESIGN QA — FAILED\n\nReason: invalid summary (not a JSON object)"
    if summary.get("processStatus") == "failed":
        return f"DESIGN QA — FAILED\n\nReason: {summary.get('processReason', 'unspecified')}"
    reference = contract.get("reference", {}) if isinstance(contract, dict) else {}
    has_reference = bool(reference.get("url") or reference.get("imagePath"))
    result = gate(findings, reference_available=has_reference)
    tests = summary.get("tests", "skipped")
    # Priority: a blocked gate always wins; failed functional tests turn any
    # non-blocked run into FAILED (a SKIPPED design QA must never hide a
    # functional failure); otherwise the gate verdict stands.
    if result["verdict"] == "BLOCKED":
        final = "BLOCKED"
    elif tests == "failed":
        final = "FAILED"
    else:
        final = result["verdict"]
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        counts[finding.get("severity", "INFO")] = counts.get(finding.get("severity", "INFO"), 0) + 1
    # Remaining derives from the gate result (open findings only) — waived,
    # fixed and invalid findings are never reported as "remaining" (R-01).
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
        f"Findings:",
        f"  BLOCKER: {counts['BLOCKER']}  MAJOR: {counts['MAJOR']}  MINOR: {counts['MINOR']}  INFO: {counts['INFO']}",
        f"Corrections:",
        f"  Applied: {result.get('applied', 0)}  Remaining: {remaining}",
        f"Iterations:",
        f"  {summary.get('iterations', 0)}",
        f"Tests:",
        f"  {tests}",
        f"Evidence:",
    ]
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


def load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


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


def cmd_gate(argv: List[str]) -> int:
    findings = load(argv[0])
    problems = validate_findings(findings)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        return 1
    no_reference = "--no-reference" in argv[1:]
    result = gate(findings, reference_available=not no_reference)
    print(json.dumps(result, indent=2))
    # Composable exit codes: 0 = nothing blocks the MR (PASSED or SKIPPED),
    # 3 = BLOCKED (fail-open-proof shell chaining), 1 = invalid input.
    return 3 if result["verdict"] == "BLOCKED" else 0


def cmd_report(argv: List[str]) -> int:
    summary = load(argv[0])
    base = argv[0].rsplit("/", 1)[0] + "/" if "/" in argv[0] else ""
    contract_path = summary.get("contract")
    findings_path = summary.get("findings")
    if not contract_path or not findings_path:
        print("ERROR: summary needs 'contract' and 'findings' paths")
        return 1
    contract = load(contract_path if contract_path.startswith("/") else base + str(contract_path))
    findings = load(findings_path if findings_path.startswith("/") else base + str(findings_path))
    for name, data, validator in (("contract", contract, validate_contract), ("findings", findings, validate_findings)):
        problems = validator(data)
        if problems:
            for problem in problems:
                print(f"INVALID ({name}): {problem}")
            return 1
    print(render_report(summary, contract, findings))
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: dq_contract.py parse-figma-url|validate-contract|validate-findings|gate|report ...",
              file=sys.stderr)
        return 2
    commands = {
        "parse-figma-url": (cmd_parse_figma_url, 1),
        "validate-contract": (cmd_validate_contract, 1),
        "validate-findings": (cmd_validate_findings, 1),
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
    except (OSError, json.JSONDecodeError) as error:
        # Input errors are distinct from verdicts: exit 2, never a traceback.
        print(f"ERROR: cannot read input: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
