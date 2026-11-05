#!/usr/bin/env python3
"""session-finalize — deterministic project-memory closure validator.

Read-only, idempotent, non-editorial. Emits a closure certificate (JSON on
stdout) certifying the mechanical state of the project memory (docs/ai/) and
the git worktree at evaluation time. It NEVER edits files, never writes to the
repository, never decides mission status, and never blocks session end. The
certificate is evidence, not a lock: an agent must report the verdict in its
handoff message (procedural rule), but failure never erases work.

Honesty boundary (same as design-qa): the validator certifies mechanical
conformity (presence, freshness, coherence) — it never proves that the
content is true. A fresh but false STATUS passes.

Contract (spec v1.1, reviewed in the Serena→Aurora brainstorming thread):
- Six mechanical invariants INV-1..INV-6, one check each, no editorial claims.
- Per-check results: pass / fail / warning / unknown / not_applicable.
- Global verdict precedence: fail > no_docs > incomplete > warning > pass.
- Exit codes: 0 pass/warning/incomplete/no_docs · 1 fail · 2 usage/environment.
- --strict turns warnings into exit 1 but NEVER turns a missing proof
  (incomplete) into a business failure.
- Read-only is effective, not incidental: whitelisted git subcommands only
  (rev-parse, status, ls-files) under GIT_OPTIONAL_LOCKS=0, no shell,
  symlink-confined file reads, no writes anywhere.

git_status_signature = sha1(head + "\\n" + status_raw) where status_raw is the
unstripped stdout of `git status --porcelain` — byte-for-byte the same
serialization as task-workflow's compute_code_signature (cross-tool
compatibility). It certifies git STATE (which paths differ from HEAD), never
working-tree CONTENT; content validity of docs/ai/ is attested solely by
memory_fingerprint (sha256, length-prefixed, canonical file order).

Idempotence: identical observed state + identical evaluation instant yields
identical results except generated_at. When --max-age-hours is active the
recency verdict depends on the evaluation instant — documented, not a defect.

Python 3.9+ stdlib only, offline, deterministic. No dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

TOOL_VERSION = "1.1.0"
SCHEMA_VERSION = 1

# Canonical memory files, fixed alphabetical order (fingerprint canonicalization).
MEMORY_FILES = (
    "BUFFER.md",
    "CHANGELOG.md",
    "DECISIONS.md",
    "INDEX.md",
    "PLAN.md",
    "STATUS.md",
    "WARNINGS.md",
)

DOCS_AI_DIR = "docs/ai"

# PLAN status enum checked by plan_status_enum (simple `status:` key).
PLAN_STATUS_ENUM = ("pending", "in-progress", "implemented", "reviewed", "blocked")

# SHA-256 of the canonical scaffold contents shipped in this repository's
# templates/ (CRLF→LF normalized, trailing newlines stripped). A memory file
# whose normalized content hashes to one of these is an UNINITIALIZED
# scaffold, not a maintained file. A test keeps these in sync with templates/.
SKELETON_SHA256: Dict[str, str] = {
    "STATUS.md": "a811ac1bbebc53777a97dfc29ab71fd86514d6dc6801b91b907520fb9ef647ca",
    "PLAN.md": "0c5319372ed652a48632ec128eb6572973d046dfb663fe869b58e746347abea9",
    "CHANGELOG.md": "e616d425f2cbe55a9f5920cb98dc097b4ed963b2944bf9542bfb46cae0b3d49e",
    "DECISIONS.md": "bdb0426d9bd87de662a95002d8216cc36255e119fa9447aca18c6385d68b0dc3",
    "BUFFER.md": "c4db56bc3fb67ff2c110f0ec48e066648ca9eaf5f53ad99e74988890c93c6553",
    "INDEX.md": "79a919e9c48750f2deec2aa820690ff14ce2eae47e58934be00e5f19ecd87cf9",
    "WARNINGS.md": "c60e59d0047df193c2ea0333b732f0ce254fb46eb681fa81d248c2823d5c1d3b",
}

# Read-only git contract: only these subcommands may ever be invoked.
GIT_ALLOWED_SUBCOMMANDS = frozenset(("rev-parse", "status", "ls-files"))
GIT_TIMEOUT_SECONDS = 30

HEADING_DATE_RE = re.compile(r"^#{1,6} .*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
HEADING_RE = re.compile(r"^#{1,6} ", re.MULTILINE)
STATUS_KEY_RE = re.compile(r"^\s*status:\s*(.*)$", re.MULTILINE)

# Check-level results. not_applicable counts in NO verdict category: an
# observation that does not apply (no git repo, untracked docs/ai) is not a
# missing proof and must never produce systematic `incomplete`.
RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_WARNING = "warning"
RESULT_UNKNOWN = "unknown"
RESULT_NA = "not_applicable"

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_WARNING = "warning"
VERDICT_INCOMPLETE = "incomplete"
VERDICT_NO_DOCS = "no_docs"


class Check:
    """One mechanical invariant observation."""

    def __init__(self, check_id: str, result: str, detail: Any,
                 unknown_reason: Optional[str] = None) -> None:
        self.id = check_id
        self.result = result
        self.detail = detail
        self.unknown_reason = unknown_reason

    def to_dict(self) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"id": self.id, "result": self.result}
        if self.result == RESULT_UNKNOWN and self.unknown_reason:
            entry["unknown_reason"] = self.unknown_reason
        entry["detail"] = self.detail
        return entry


def _normalize(content_bytes: bytes) -> str:
    return content_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip("\n")


def git_run(project_root: str, *args: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Run a whitelisted, read-only git subcommand.

    Returns (stdout, None, None) on success, (None, reason, None) when git is
    unusable for an environmental reason, (None, stderr, returncode) on a
    clean non-zero exit. Never runs a mutating subcommand; the whitelist is
    the contract, not a convention. Hardening: the inherited GIT_* environment
    is purged (no caller redirection like GIT_DIR/GIT_WORK_TREE), the
    filesystem monitor is pinned off (no fsmonitor daemon spawned, nothing
    written into .git/), and GIT_OPTIONAL_LOCKS=0 forbids index refresh.
    """
    if not args or args[0] not in GIT_ALLOWED_SUBCOMMANDS:
        raise ValueError("non-read-only git subcommand refused: %s" % (args[0] if args else "<none>"))
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        proc = subprocess.run(
            ["git", "-C", project_root, "-c", "core.fsmonitor=false", *args],
            capture_output=True, text=True, check=False,
            timeout=GIT_TIMEOUT_SECONDS, env=env,
        )
    except FileNotFoundError:
        return None, "git binary not found", None
    except subprocess.TimeoutExpired:
        return None, "git command timed out", None
    except OSError as exc:
        return None, "git command failed: %s" % exc, None
    if proc.returncode != 0:
        return None, proc.stderr.strip(), proc.returncode
    return proc.stdout, None, None


def discover_git(project_root: str) -> Dict[str, Any]:
    """Establish git observability. A non-repo (or absent git binary) is a
    DECLARED state (not_applicable); a usable repo failing mid-run (timeout,
    I/O error) is a missing proof (unknown). A clean non-zero exit that is not
    a repository is also declared non-observability."""
    out, err, rc = git_run(project_root, "rev-parse", "--show-toplevel")
    if out is None:
        if rc is None:
            # Environmental: git binary missing (declared — no git capability),
            # or transient I/O failure (unknown). Distinguish explicitly.
            if err == "git binary not found":
                return {"state": "not_applicable", "reason": "git binary not found"}
            if err == "git command timed out":
                return {"state": "unknown", "reason": "git command timed out"}
            return {"state": "unknown", "reason": err or "git command failed"}
        return {"state": "not_applicable", "reason": err or "git rev-parse failed"}
    out2, err2, _ = git_run(project_root, "rev-parse", "HEAD")
    if out2 is None:
        # No HEAD yet (fresh git init, zero commits) — git observable, history absent.
        out3, err3, _ = git_run(project_root, "status", "--porcelain")
        if out3 is not None:
            return {"state": "ok", "branch": None, "head_sha": None,
                    "porcelain": out3, "reason": "no commits yet"}
        return {"state": "unknown", "reason": err3 or "git HEAD unavailable"}
    head_sha = out2.strip()
    out4, err4, _ = git_run(project_root, "rev-parse", "--abbrev-ref", "HEAD")
    branch = out4.strip() if out4 else None
    if branch == "HEAD":
        branch = None  # detached HEAD
    out5, err5, _ = git_run(project_root, "status", "--porcelain")
    if out5 is None:
        return {"state": "unknown", "reason": err5 or "git status failed"}
    return {"state": "ok", "branch": branch, "head_sha": head_sha, "porcelain": out5}


def compute_git_status_signature(head_sha: str, porcelain_raw: str) -> str:
    """sha1(head + "\\n" + porcelain_raw) — serialization byte-for-byte identical
    to task-workflow tw_state.compute_code_signature (compatibility contract).
    porcelain_raw is the UNSTRIPPED git stdout."""
    payload = head_sha + "\n" + porcelain_raw
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def compute_memory_fingerprint(contents: Dict[str, Optional[bytes]]) -> str:
    """sha256 over the 7 memory files, canonical alphabetical order,
    length-prefixed encoding, explicit PRESENT/ABSENT distinction (an absent
    file and an empty file are different observations)."""
    digest = hashlib.sha256()
    for name in MEMORY_FILES:  # canonical order
        data = contents.get(name)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        if data is None:
            digest.update(b"ABSENT")
        else:
            digest.update(b"PRESENT\0")
            digest.update(len(data).to_bytes(8, "big"))
        digest.update(b"\0")
        if data is not None:
            digest.update(data)
    return "sha256:" + digest.hexdigest()


def confined_read(project_root_real: str, path: str) -> Tuple[str, Optional[bytes], Optional[str]]:
    """Read a file confined to the project root, refusing to follow symlinks
    outside it — including DIRECTORY-component symlinks (e.g. docs/ai itself
    being a symlink to outside): the realpath of the FULL path is verified
    before any open. Returns (state, content, reason): state in
    ok | absent | outside | unreadable."""
    try:
        target_real = os.path.realpath(path)  # resolves every component
        if not (target_real == project_root_real or target_real.startswith(project_root_real + os.sep)):
            return "outside", None, "path escapes project root: %s" % target_real
        mode = os.stat(target_real).st_mode
        if not stat.S_ISREG(mode):  # FIFO/device would hang a plain open()
            return "unreadable", None, "not a regular file"
        with open(target_real, "rb") as handle:  # binary read: no side effects possible
            return "ok", handle.read(), None
    except FileNotFoundError:
        return "absent", None, None
    except OSError as exc:
        return "unreadable", None, str(exc)


def parse_heading_dates(content: str) -> List[str]:
    """All YYYY-MM-DD dates found in markdown headings (any level)."""
    return HEADING_DATE_RE.findall(content)


def _worst(results: List[str]) -> str:
    """Aggregate sub-results of one check. fail > warning > unknown > pass;
    not_applicable never dominates, and an entirely non-applicable check is
    itself not_applicable (a declared state, not a missing proof)."""
    applicable = [r for r in results if r != RESULT_NA]
    if not applicable:
        return RESULT_NA
    for bad in (RESULT_FAIL, RESULT_WARNING, RESULT_UNKNOWN):
        if bad in applicable:
            return bad
    return RESULT_PASS


def check_memory_presence(states: Dict[str, str], reasons: Dict[str, str],
                          docs_ai_absent: bool) -> Check:
    if docs_ai_absent:
        return Check("memory_presence", RESULT_NA,
                     {"reason": "docs/ai absent — declared state (verdict no_docs), not a failure"})
    missing: List[str] = []
    refused: List[str] = []
    for name in MEMORY_FILES:
        state = states.get(name, "absent")
        if state == "ok":
            continue
        if state == "absent":
            missing.append(name)
        else:
            refused.append(name)
    if missing:
        return Check("memory_presence", RESULT_FAIL, {"missing": missing})
    if refused:
        return Check("memory_presence", RESULT_UNKNOWN, {"refused": refused},
                     unknown_reason="some files exist but are unreadable or symlinked outside project root")
    return Check("memory_presence", RESULT_PASS, {"all_present": True, "files": list(MEMORY_FILES)})


def check_memory_initialized(contents: Dict[str, Optional[bytes]],
                             states: Dict[str, str], reasons: Dict[str, str]) -> Check:
    """Renamed from the draft's memory_substantive: mechanical initialization
    only — empty file, scaffold-identical file, or no interpretable heading.
    No byte-size threshold, no editorial quality claim. A deliberately
    concise WARNINGS.md ('Aucun risque connu' under a heading) passes."""
    per_file: Dict[str, Any] = {}
    results: List[str] = []
    for name in MEMORY_FILES:
        state = states.get(name, "absent")
        if state == "absent":
            per_file[name] = {"result": RESULT_NA, "reason": "file absent (see memory_presence)"}
            continue
        data = contents.get(name)
        if data is None:  # unreadable or symlink-out: missing proof, not a failure
            per_file[name] = {"result": RESULT_UNKNOWN, "reason": reasons.get(name, "content unreadable")}
            results.append(RESULT_UNKNOWN)
            continue
        normalized = _normalize(data)
        if not normalized:
            per_file[name] = {"result": RESULT_FAIL, "reason": "empty file"}
            results.append(RESULT_FAIL)
            continue
        if hashlib.sha256(normalized.encode("utf-8")).hexdigest() == SKELETON_SHA256.get(name):
            per_file[name] = {"result": RESULT_FAIL, "reason": "identical to canonical scaffold"}
            results.append(RESULT_FAIL)
            continue
        if HEADING_RE.search(normalized):
            per_file[name] = {"result": RESULT_PASS, "reason": "minimal structure present"}
            results.append(RESULT_PASS)
            continue
        per_file[name] = {"result": RESULT_UNKNOWN, "reason": "non-empty, no interpretable heading"}
        results.append(RESULT_UNKNOWN)
    return Check("memory_initialized", _worst(results), per_file)


def check_memory_recency(contents: Dict[str, Optional[bytes]], states: Dict[str, str],
                         reasons: Dict[str, str], max_age_hours: Optional[float],
                         now: datetime) -> Check:
    """STATUS + CHANGELOG carry at least one dated entry (YYYY-MM-DD in any
    heading) — compatible with both repository practices (canonical '### YYYY-MM-DD
    HH:MM' and real '## YYYY-MM-DD (N)'). No age constraint unless --max-age-hours
    is explicitly provided (opt-in, no default). A dateless file is unknown
    (insufficient proof), never a fake pass and never a fail."""
    per_file: Dict[str, Any] = {}
    results: List[str] = []
    for name in ("STATUS.md", "CHANGELOG.md"):
        state = states.get(name, "absent")
        if state == "absent":
            per_file[name] = {"result": RESULT_NA, "reason": "file absent (see memory_presence)"}
            continue
        data = contents.get(name)
        if data is None:  # unreadable or symlink-out: missing proof, not a failure
            per_file[name] = {"result": RESULT_UNKNOWN, "reason": reasons.get(name, "content unreadable")}
            results.append(RESULT_UNKNOWN)
            continue
        dates = parse_heading_dates(_normalize(data))
        if not dates:
            per_file[name] = {"result": RESULT_UNKNOWN, "reason": "no dated heading entry"}
            results.append(RESULT_UNKNOWN)
            continue
        parsed: List[datetime] = []
        bad_dates: List[str] = []
        for raw in dates:
            try:
                parsed.append(datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc))
            except ValueError:
                bad_dates.append(raw)
        latest = max(parsed) if parsed else None
        if latest is None:
            per_file[name] = {"result": RESULT_UNKNOWN,
                              "reason": "dated headings present but no parseable date",
                              "unparseable": bad_dates}
            results.append(RESULT_UNKNOWN)
            continue
        if latest > now + timedelta(days=1):
            per_file[name] = {"result": RESULT_UNKNOWN, "reason": "future date: %s" % latest.date().isoformat()}
            results.append(RESULT_UNKNOWN)
            continue
        detail: Dict[str, Any] = {"latest_date": latest.date().isoformat() if latest else None,
                                  "dated_entries": len(dates)}
        if bad_dates:
            detail["unparseable"] = bad_dates
        if max_age_hours is None:
            detail["age_constraint"] = "none (--max-age-hours not provided)"
            detail["result"] = RESULT_PASS
            per_file[name] = {"result": RESULT_PASS, **detail}
            results.append(RESULT_PASS)
            continue
        age_hours = (now - latest).total_seconds() / 3600.0 if latest else None
        detail["age_hours"] = round(age_hours, 2) if age_hours is not None else None
        detail["age_constraint"] = "max_age_hours=%s" % max_age_hours
        if age_hours is not None and age_hours > max_age_hours:
            detail["result"] = RESULT_WARNING
            per_file[name] = {"result": RESULT_WARNING, **detail}
            results.append(RESULT_WARNING)
        else:
            detail["result"] = RESULT_PASS
            per_file[name] = {"result": RESULT_PASS, **detail}
            results.append(RESULT_PASS)
    return Check("memory_recency", _worst(results), per_file)


def check_memory_versioned(project_root: str, git_info: Dict[str, Any]) -> Check:
    """docs/ai tracked in git? Untracked memory is a legitimate declared state
    (not_applicable). Tracked-but-dirty is a warning, never a fail."""
    if git_info.get("state") == "not_applicable":
        return Check("memory_versioned", RESULT_NA, {"reason": git_info.get("reason", "git unavailable")})
    if git_info.get("state") == "unknown":
        return Check("memory_versioned", RESULT_UNKNOWN, {"reason": git_info.get("reason", "git error")})
    out, err, _ = git_run(project_root, "ls-files", "--", DOCS_AI_DIR)
    if out is None:
        return Check("memory_versioned", RESULT_UNKNOWN, {"reason": err or "git ls-files failed"})
    tracked = [line for line in out.splitlines() if line.strip()]
    if not tracked:
        return Check("memory_versioned", RESULT_NA, {"reason": "no memory files tracked in git"})
    out2, err2, _ = git_run(project_root, "status", "--porcelain", "--", DOCS_AI_DIR)
    if out2 is None:
        return Check("memory_versioned", RESULT_UNKNOWN, {"reason": err2 or "git status failed"})
    dirty = [line for line in out2.splitlines() if line.strip()]
    if dirty:
        return Check("memory_versioned", RESULT_WARNING,
                     {"tracked": len(tracked), "dirty_entries": dirty})
    return Check("memory_versioned", RESULT_PASS, {"tracked": len(tracked), "dirty": 0})


def check_worktree_snapshot(project_root: str, git_info: Dict[str, Any]) -> Check:
    """Observational: branch, HEAD, git_status_signature. Certifies git STATE
    only (which paths differ from HEAD) — never working-tree content; docs/ai
    content validity is attested solely by memory_fingerprint. Uncommitted
    work OUTSIDE docs/ai/ is legitimate WIP → warning, never a fail."""
    if git_info.get("state") == "not_applicable":
        return Check("worktree_snapshot", RESULT_NA, {"reason": git_info.get("reason", "git unavailable")})
    if git_info.get("state") == "unknown":
        return Check("worktree_snapshot", RESULT_UNKNOWN, {"reason": git_info.get("reason", "git error")})
    porcelain = git_info.get("porcelain", "")
    entries = [line for line in porcelain.splitlines() if line.strip()]
    outside_docs = []
    for line in entries:
        parts = line[3:].strip().strip('"')
        if not (parts == DOCS_AI_DIR or parts.startswith(DOCS_AI_DIR + "/")):
            outside_docs.append(line)
    detail: Dict[str, Any] = {
        "branch": git_info.get("branch"),
        "head_sha": git_info.get("head_sha"),
        "git_status_signature": compute_git_status_signature(git_info["head_sha"], porcelain)
        if git_info.get("head_sha") else None,
        "dirty_entries": len(entries),
        "dirty_outside_docs_ai": len(outside_docs),
        "no_commits_yet": git_info.get("head_sha") is None,
    }
    if outside_docs:
        detail["uncommitted_outside_docs_ai"] = outside_docs
        return Check("worktree_snapshot", RESULT_WARNING, detail)
    return Check("worktree_snapshot", RESULT_PASS, detail)


def check_plan_status_enum(contents: Dict[str, Optional[bytes]], states: Dict[str, str],
                           reasons: Dict[str, str]) -> Check:
    """If PLAN carries a simple `status:` key anywhere in the markdown, its
    value must be in the standard enum. Absent key = pass (the standard makes
    it optional). Uninterpretable form = unknown; clearly illegal value = fail.
    No YAML parser: only the simple key is supported, by contract."""
    state = states.get("PLAN.md", "absent")
    if state == "absent":
        return Check("plan_status_enum", RESULT_NA, {"reason": "PLAN.md absent (see memory_presence)"})
    data = contents.get("PLAN.md")
    if data is None:
        return Check("plan_status_enum", RESULT_UNKNOWN,
                     {"reason": reasons.get("PLAN.md", "PLAN.md content unreadable")})
    matches = STATUS_KEY_RE.findall(_normalize(data))
    if not matches:
        return Check("plan_status_enum", RESULT_PASS, {"reason": "no status key found (optional)"})
    raw_value = matches[0].strip()
    value = raw_value.strip("'\"").lower()
    detail: Dict[str, Any] = {"raw": raw_value, "enum": list(PLAN_STATUS_ENUM)}
    if not value or value.startswith(("'", '"', "[", "{", ":", "#")) or " " in value:
        detail["reason"] = "uninterpretable value form"
        return Check("plan_status_enum", RESULT_UNKNOWN, detail)
    if value in PLAN_STATUS_ENUM:
        detail["value"] = value
        return Check("plan_status_enum", RESULT_PASS, detail)
    detail["value"] = value
    detail["reason"] = "value outside the standard enum"
    return Check("plan_status_enum", RESULT_FAIL, detail)


def _derive_unknown_reasons(checks: List[Check]) -> None:
    """Propagate a per-file unknown reason to check level when the check itself
    resolves to unknown (e.g. recency on files with no dated entry)."""
    for check in checks:
        if check.result != RESULT_UNKNOWN or check.unknown_reason:
            continue
        if isinstance(check.detail, dict):
            for value in check.detail.values():
                if isinstance(value, dict) and value.get("result") == RESULT_UNKNOWN and value.get("reason"):
                    check.unknown_reason = value["reason"]
                    break


def resolve_verdict(checks: List[Check], docs_ai_absent: bool) -> Tuple[str, Dict[str, int]]:
    """Verdict precedence, exactly:
    1. any fail → fail
    2. docs/ai absent → no_docs (independent failures already caught by rule 1)
    3. any unknown → incomplete
    4. any warning → warning
    5. all applicable checks pass → pass
    not_applicable never contributes to any category."""
    counts: Dict[str, int] = {RESULT_PASS: 0, RESULT_FAIL: 0, RESULT_WARNING: 0,
                              RESULT_UNKNOWN: 0, RESULT_NA: 0}
    for check in checks:
        counts[check.result] += 1
    if counts[RESULT_FAIL] > 0:
        return VERDICT_FAIL, counts
    if docs_ai_absent:
        return VERDICT_NO_DOCS, counts
    if counts[RESULT_UNKNOWN] > 0:
        return VERDICT_INCOMPLETE, counts
    if counts[RESULT_WARNING] > 0:
        return VERDICT_WARNING, counts
    return VERDICT_PASS, counts


VERDICT_EXIT = {
    VERDICT_PASS: 0,
    VERDICT_WARNING: 0,
    VERDICT_INCOMPLETE: 0,
    VERDICT_NO_DOCS: 0,
    VERDICT_FAIL: 1,
}


def finalize(project_root: str, max_age_hours: Optional[float], mission: Optional[str],
             now: datetime) -> Tuple[Dict[str, Any], int]:
    """Produce (certificate, exit_code). Zero writes, guaranteed."""
    root_real = os.path.realpath(project_root)
    docs_ai_path = os.path.join(root_real, DOCS_AI_DIR)
    docs_ai_absent = not os.path.isdir(docs_ai_path)

    # Confined reads of the 7 memory files (None when absent/unreadable).
    contents: Dict[str, Optional[bytes]] = {}
    present: Dict[str, bool] = {}
    states: Dict[str, str] = {}
    reasons: Dict[str, str] = {}
    for name in MEMORY_FILES:
        path = os.path.join(docs_ai_path, name)
        state, data, reason = confined_read(root_real, path)
        states[name] = state
        contents[name] = data if state == "ok" else None
        present[name] = state == "ok"
        if state in ("outside", "unreadable") and reason:
            reasons[name] = reason

    git_info = discover_git(project_root)
    memory_fingerprint = compute_memory_fingerprint(contents) if not docs_ai_absent else None

    checks: List[Check] = [
        check_memory_presence(states, reasons, docs_ai_absent),
        check_memory_initialized(contents, states, reasons),
        check_memory_recency(contents, states, reasons, max_age_hours, now),
        check_memory_versioned(project_root, git_info),
        check_worktree_snapshot(project_root, git_info),
        check_plan_status_enum(contents, states, reasons),
    ]
    _derive_unknown_reasons(checks)

    verdict, counts = resolve_verdict(checks, docs_ai_absent)
    porcelain = git_info.get("porcelain") if git_info.get("state") == "ok" else None
    head_sha = git_info.get("head_sha") if git_info.get("state") == "ok" else None

    certificate: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "mission": mission,
        "snapshot": {
            "project_root": root_real,
            "branch": git_info.get("branch") if git_info.get("state") == "ok" else None,
            "head_sha": head_sha,
            "git_status_signature": compute_git_status_signature(head_sha, porcelain)
            if head_sha and porcelain is not None else None,
            "memory_fingerprint": memory_fingerprint,
            "generated_at": now.isoformat(),
            "checks": [check.to_dict() for check in checks],
        },
        "summary": {"verdict": verdict, "counts": counts},
    }

    exit_code = VERDICT_EXIT[verdict]
    return certificate, exit_code


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="session-finalize",
        description="Deterministic read-only project-memory closure validator "
                    "(certificate as JSON on stdout; never writes).",
    )
    parser.add_argument("--project", default=os.getcwd(),
                        help="project root (default: current directory)")
    parser.add_argument("--max-age-hours", type=float, default=None,
                        help="opt-in age constraint on the newest dated entry; "
                             "when ABSENT no age constraint is applied at all")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on warnings; never converts a missing proof "
                             "(incomplete) into a business failure")
    parser.add_argument("--mission", default=None,
                        help="free-form mission label embedded in the certificate")
    args = parser.parse_args(argv)

    project_root = args.project
    if not os.path.isdir(project_root):
        print("session-finalize: project root is not a directory: %s" % project_root, file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    try:
        certificate, exit_code = finalize(project_root, args.max_age_hours, args.mission, now)
        if args.strict and verdict_is_warning(certificate):
            exit_code = 1
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # never exit 1 for a locale artifact
        except (AttributeError, OSError, ValueError):
            pass
        json.dump(certificate, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return exit_code
    except Exception as exc:  # fail-closed: report on stderr, exit 2, never crash
        print("session-finalize: environmental failure: %s" % exc, file=sys.stderr)
        return 2


def verdict_is_warning(certificate: Dict[str, Any]) -> bool:
    return certificate.get("summary", {}).get("verdict") == VERDICT_WARNING


if __name__ == "__main__":
    sys.exit(main())
