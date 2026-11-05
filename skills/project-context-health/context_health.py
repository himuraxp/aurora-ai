#!/usr/bin/env python3
"""project-context-health — deterministic project-memory preflight validator.

Read-only, idempotent, non-editorial. Answers one question at session/task
OPEN: "is docs/ai/ usable and fresh BEFORE work starts?" — the opening
complement of session-finalize (closure at the END).

Honesty boundary (same as session-finalize): mechanical conformity only —
never proves content truth. A stale baseline means "something changed"; it
never says the memory is wrong.

Three NON-EXCLUSIVE axes (contract improvement #2):
- initialization: the 7 canonical files exist and are minimally structured.
- last_validation: the last recorded mechanical baseline — present / absent
  (never validated: legitimate declared state, the NORMAL first run) /
  corrupt (evidence unreadable: unknown, never a crash, never a silent
  fallback to an older baseline).
- freshness: an explicit COVERAGE-bounded statement about mechanical
  stability — fresh means "the 7 files are byte-identical to the recorded
  baseline AND the git reference matches"; NEVER a claim about the global
  currency of project knowledge. Doubt = unknown, never a fake fresh.

Persistence (unlike session-finalize, a persisted proof is REQUIRED by the
validated concept: "git reference of the last validation"): an append-only
JSONL journal isolated PER WORKTREE at $(git rev-parse --absolute-git-dir)/
project-context-health/journal.jsonl — a linked worktree owns its own git
dir (.git/worktrees/<name>), so two worktrees of one repo can never see each
other's baselines. Writes are isolated in the explicit --record mode (the
ONLY writing mode; append-only; never inside the working tree or docs/ai;
fail-closed exit 2). validate/history never write anywhere.

--record records a MECHANICAL BASELINE (an observation frozen at time T),
never a documentary-truth certification or a semantic validation. It is
normally produced after a verified closure (usually via the session-finalize
certificate) — the record is not the proof of that verification.

Report/verdict taxonomy: identical to session-finalize (pass / fail /
warning / unknown / not_applicable; precedence fail > no_docs > incomplete >
warning > pass; exit 0/1/2; --strict never converts a missing proof into a
business failure). stale is a WARNING (conservative indicator, never
blocking). A first run without a journal is INCOMPLETE, exit 0 — the
documented NORMAL state.

Cross-tool pin: memory_fingerprint and git_status_signature are
byte-for-byte identical to session-finalize (live test imports finalize).
Recorded entries carry three DECOUPLED versions: record_schema_version
(governs parseability), standard_version (changed -> stale reason
"standard-changed"), tool_version (a change alone NEVER invalidates a
baseline).

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

try:  # platform-standard advisory locking (POSIX target: macOS/Linux)
    import fcntl as _FCNTL
except ImportError:  # non-POSIX: single-process tool by contract
    _FCNTL = None
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)  # anti-symlink swap at open (POSIX)

TOOL_VERSION = "1.0.0"
STANDARD_VERSION = "1.0.0"   # version of the memory-standard contract validated here
REPORT_SCHEMA_VERSION = 1
RECORD_SCHEMA_VERSION = 1    # governs journal record parseability only

# Canonical memory files, fixed alphabetical order (same as session-finalize).
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
JOURNAL_SUBDIR = "project-context-health"
JOURNAL_FILENAME = "journal.jsonl"

# Same canonical scaffolds as session-finalize (kept in sync by a live test).
SKELETON_SHA256: Dict[str, str] = {
    "STATUS.md": "a811ac1bbebc53777a97dfc29ab71fd86514d6dc6801b91b907520fb9ef647ca",
    "PLAN.md": "0c5319372ed652a48632ec128eb6572973d046dfb663fe869b58e746347abea9",
    "CHANGELOG.md": "e616d425f2cbe55a9f5920cb98dc097b4ed963b2944bf9542bfb46cae0b3d49e",
    "DECISIONS.md": "bdb0426d9bd87de662a95002d8216cc36255e119fa9447aca18c6385d68b0dc3",
    "BUFFER.md": "c4db56bc3fb67ff2c110f0ec48e066648ca9eaf5f53ad99e74988890c93c6553",
    "INDEX.md": "79a919e9c48750f2deec2aa820690ff14ce2eae47e58934be00e5f19ecd87cf9",
    "WARNINGS.md": "c60e59d0047df193c2ea0333b732f0ce254fb46eb681fa81d248c2823d5c1d3b",
}

# Read-only git contract: whitelist + hard bounds. `log` is L2-only and
# always invoked with the fixed bounded form below (never with free args).
GIT_ALLOWED_SUBCOMMANDS = frozenset(("rev-parse", "status", "ls-files", "log"))
GIT_LOG_BOUND = 20
GIT_TIMEOUT_SECONDS = 30

# Journal safety bounds (contract P0-4): bounded reads, capped records.
JOURNAL_MAX_BYTES = 4 * 1024 * 1024
JOURNAL_MAX_RECORDS = 100
JOURNAL_MAX_LINE_BYTES = 64 * 1024

HEADING_RE = re.compile(r"^#{1,6} ", re.MULTILINE)
# Path-like token: contains a separator, no whitespace, and a suffix-ish tail.
PATH_TOKEN_RE = re.compile(r"(?<![\w.\-/])([\w.\-]+(?:/[\w.\-@+]+){1,6}/[\w.\-@+]+)(?![\w.\-/])")
REFERENCED_PATHS_MAX = 20

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

VERDICT_EXIT = {
    VERDICT_PASS: 0,
    VERDICT_WARNING: 0,
    VERDICT_INCOMPLETE: 0,
    VERDICT_NO_DOCS: 0,
    VERDICT_FAIL: 1,
}


def _normalize(content_bytes: bytes) -> str:
    return content_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip("\n")


def git_run(project_root: str, *args: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Run a whitelisted, read-only git subcommand (same hardening as
    session-finalize: GIT_* env purged, GIT_OPTIONAL_LOCKS=0, fsmonitor off,
    no shell, timeout). `log` callers must use the bounded form."""
    if not args or args[0] not in GIT_ALLOWED_SUBCOMMANDS:
        raise ValueError("non-read-only git subcommand refused: %s" % (args[0] if args else "<none>"))
    if args[0] == "log":
        if "--" in args or "-n" not in args or int(args[args.index("-n") + 1]) > GIT_LOG_BOUND:
            raise ValueError("git log must use the bounded -n form (max %d)" % GIT_LOG_BOUND)
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
    """Git observability + per-worktree git-dir discovery. Uses
    --absolute-git-dir: a linked worktree gets ITS OWN git dir
    (<main>/.git/worktrees/<name>) — per-worktree journal isolation by
    construction (contract P0-2)."""
    out, err, rc = git_run(project_root, "rev-parse", "--show-toplevel")
    if out is None:
        if rc is None:
            if err == "git binary not found":
                return {"state": "not_applicable", "reason": "git binary not found"}
            return {"state": "unknown", "reason": err or "git command failed"}
        return {"state": "not_applicable", "reason": err or "not a git repository"}
    out2, err2, _ = git_run(project_root, "rev-parse", "--absolute-git-dir")
    if out2 is None:
        return {"state": "unknown", "reason": err2 or "git dir unavailable"}
    git_dir = os.path.realpath(out2.strip())  # normalize relative/symlinked forms
    out3, err3, _ = git_run(project_root, "rev-parse", "HEAD")
    if out3 is None:
        head_sha: Optional[str] = None  # fresh init, zero commits
    else:
        head_sha = out3.strip()
    out4, err4, _ = git_run(project_root, "rev-parse", "--abbrev-ref", "HEAD")
    branch = out4.strip() if out4 else None
    if branch == "HEAD":
        branch = None  # detached HEAD
    out5, err5, _ = git_run(project_root, "status", "--porcelain")
    if out5 is None:
        return {"state": "unknown", "reason": err5 or "git status failed"}
    return {"state": "ok", "branch": branch, "head_sha": head_sha,
            "porcelain": out5, "git_dir": git_dir}


def compute_git_status_signature(head_sha: str, porcelain_raw: str) -> str:
    """sha1(head + "\\n" + porcelain_raw) — byte-for-byte the task-workflow /
    session-finalize serialization (cross-tool pin, live-tested)."""
    payload = head_sha + "\n" + porcelain_raw
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def compute_memory_fingerprint(contents: Dict[str, Optional[bytes]]) -> str:
    """sha256, canonical order, length-prefixed, PRESENT/ABSENT — byte-for-byte
    identical to session-finalize.compute_memory_fingerprint (cross-tool pin)."""
    digest = hashlib.sha256()
    for name in MEMORY_FILES:
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
    """Read confined to the project root — full-component realpath resolution,
    regular files only (FIFO/device refused). Same discipline as
    session-finalize (symlink-out => not read)."""
    try:
        target_real = os.path.realpath(path)
        if not (target_real == project_root_real or target_real.startswith(project_root_real + os.sep)):
            return "outside", None, "path escapes project root: %s" % target_real
        mode = os.stat(target_real).st_mode
        if not stat.S_ISREG(mode):
            return "unreadable", None, "not a regular file"
        with open(target_real, "rb") as handle:
            return "ok", handle.read(), None
    except FileNotFoundError:
        return "absent", None, None
    except OSError as exc:
        return "unreadable", None, str(exc)


def _confined_in(base_real: str, path: str) -> Tuple[bool, Optional[str]]:
    """Containment check only (no read): full realpath of `path` must stay
    under base_real (symlinks on any component refused)."""
    target_real = os.path.realpath(path)
    if not (target_real == base_real or target_real.startswith(base_real + os.sep)):
        return False, "path escapes boundary: %s" % target_real
    return True, None


# --------------------------------------------------------------------------
# Initialization axis (semantics shared with session-finalize)
# --------------------------------------------------------------------------

def check_initialization(contents: Dict[str, Optional[bytes]], states: Dict[str, str],
                         reasons: Dict[str, str], docs_ai_absent: bool) -> Dict[str, Any]:
    """Presence + minimal structure of the 7 canonical files (session-finalize
    semantics). docs/ai absent -> not_applicable (verdict no_docs)."""
    if docs_ai_absent:
        return {"result": RESULT_NA, "reason": "docs/ai absent — declared state (verdict no_docs)"}
    per_file: Dict[str, Any] = {}
    results: List[str] = []
    missing: List[str] = []
    for name in MEMORY_FILES:
        state = states.get(name, "absent")
        if state == "absent":
            per_file[name] = {"result": RESULT_FAIL, "reason": "file absent"}
            results.append(RESULT_FAIL)
            missing.append(name)
            continue
        data = contents.get(name)
        if data is None:
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
            per_file[name] = {"result": RESULT_PASS}
            results.append(RESULT_PASS)
            continue
        per_file[name] = {"result": RESULT_UNKNOWN, "reason": "non-empty, no interpretable heading"}
        results.append(RESULT_UNKNOWN)
    detail: Dict[str, Any] = {"per_file": per_file}
    if missing:
        detail["missing"] = missing
    worst = _worst(results)
    if worst == RESULT_UNKNOWN:
        detail["reason"] = "some files present but unreadable or non-interpretable"
    return {"result": worst, "detail": detail}


def _worst(results: List[str]) -> str:
    applicable = [r for r in results if r != RESULT_NA]
    if not applicable:
        return RESULT_NA
    for bad in (RESULT_FAIL, RESULT_WARNING, RESULT_UNKNOWN):
        if bad in applicable:
            return bad
    return RESULT_PASS


# --------------------------------------------------------------------------
# Journal (contract P0-2/P0-4): per-worktree, strict schema, bounded reads,
# no silent fallback.
# --------------------------------------------------------------------------

RECORD_REQUIRED_STRING_FIELDS = ("generated_at", "tool_version", "standard_version",
                                 "project_root")
RECORD_ENUM_FIELDS = {"result": (RESULT_PASS, RESULT_FAIL, RESULT_WARNING,
                                 RESULT_UNKNOWN, RESULT_NA)}


def journal_path(git_dir: str) -> str:
    return os.path.join(git_dir, JOURNAL_SUBDIR, JOURNAL_FILENAME)


def parse_record(line: str, root_real: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Strict schema validation of one journal record. Returns
    (record, None) when valid AND belonging to this project root,
    (None, reason) when the line is a complete-but-invalid record, and
    ("foreign", None) when valid but from another worktree (ignored by
    contract, never compared)."""
    try:
        raw = json.loads(line)
    except ValueError:
        return None, "record is not valid JSON"
    if not isinstance(raw, dict):
        return None, "record is not a JSON object"
    if isinstance(raw.get("record_schema_version"), bool) \
            or raw.get("record_schema_version") != RECORD_SCHEMA_VERSION:
        return None, "record_schema_version unsupported (%r)" % (raw.get("record_schema_version"),)
    for field in RECORD_REQUIRED_STRING_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            return None, "missing or invalid field: %s" % field
    try:
        baseline_at = datetime.fromisoformat(raw["generated_at"])
    except ValueError:
        return None, "generated_at is not ISO-8601"
    if baseline_at.tzinfo is None or baseline_at.tzinfo.utcoffset(baseline_at) is None:
        # A naive timestamp would crash the age computation later (aware - naive
        # TypeError). Fail-closed at the schema gate: corrupt evidence -> unknown.
        return None, "generated_at is not timezone-aware (naive timestamps refused)"
    if not os.path.isabs(raw["project_root"]):
        return None, "project_root is not absolute"
    for field, default in (("head_sha", None), ("memory_fingerprint", None),
                           ("git_status_signature", None), ("branch", None)):
        value = raw.get(field, default)
        if value is not None and not isinstance(value, str):
            return None, "invalid field: %s" % field
    file_hashes = raw.get("file_hashes")
    if not isinstance(file_hashes, dict) or set(file_hashes.keys()) != set(MEMORY_FILES):
        return None, "missing or invalid field: file_hashes (expected one entry per canonical file)"
    for value in file_hashes.values():
        if value is None:
            continue  # ABSENT file (defensive: the record gate refuses those)
        if (not isinstance(value, dict) or not isinstance(value.get("sha256"), str)
                or len(value["sha256"]) != 64 or not isinstance(value.get("bytes"), int)
                or isinstance(value.get("bytes"), bool) or value.get("bytes") < 0):
            return None, "invalid field: file_hashes entry"
    if raw.get("project_root") != root_real:
        return "foreign", None
    for field, allowed in RECORD_ENUM_FIELDS.items():
        value = raw.get(field)
        if value is not None and value not in allowed:
            return None, "invalid field: %s" % field
    record = {key: raw.get(key) for key in
              ("generated_at", "tool_version", "standard_version", "record_schema_version",
               "project_root", "branch", "head_sha", "memory_fingerprint",
               "git_status_signature", "file_hashes", "result", "mission")}
    if record["mission"] is not None and not isinstance(record["mission"], str):
        record["mission"] = None
    return record, None


def read_journal(git_dir: str, root_real: str) -> Dict[str, Any]:
    """Bounded, fail-closed journal read (contract P0-4, unified rule).

    L1 trusts ONLY the last record. Unified no-fallback rule:
    - journal absent / empty           -> no baseline (freshness unknown)
    - last line TRUNCATED (no newline)  -> corrupt, reason journal-tail-truncated
    - last line invalid / incompatible  -> corrupt, reason journal-tail-corrupt
    - last record foreign root          -> no baseline for this worktree
    In all corrupt cases freshness is UNKNOWN and we NEVER fall back to an
    earlier baseline. --deep --history parses older records as a bounded
    diagnostic, never as L1 evidence."""
    path = journal_path(git_dir)
    if not os.path.exists(path):
        return {"state": "absent", "records": [], "baseline": None}
    inside, reason = _confined_in(git_dir, path)
    if not inside:
        return {"state": "refused", "reason": reason, "records": [], "baseline": None}
    try:
        mode = os.stat(path).st_mode
        if not stat.S_ISREG(mode):
            return {"state": "refused", "reason": "journal is not a regular file",
                    "records": [], "baseline": None}
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - JOURNAL_MAX_BYTES))  # bounded tail read
            raw = handle.read(JOURNAL_MAX_BYTES)
    except OSError as exc:
        return {"state": "refused", "reason": "journal unreadable: %s" % exc,
                "records": [], "baseline": None}
    if not raw.strip():
        return {"state": "empty", "records": [], "baseline": None}
    text = raw.decode("utf-8", errors="replace")
    complete_tail = text.endswith("\n")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return {"state": "empty", "records": [], "baseline": None}
    if not complete_tail:
        # Interrupted append: the newest write never completed. Per the
        # unified contract this is corruption of the newest evidence —
        # flagged, never silently substituted by an older baseline.
        return {"state": "corrupt",
                "reason": "journal-tail-truncated: last append interrupted — "
                          "no fallback to an earlier baseline",
                "records": [], "baseline": None}
    last_line = lines[-1]
    if len(last_line.encode("utf-8", errors="replace")) > JOURNAL_MAX_LINE_BYTES:
        return {"state": "corrupt", "reason": "journal-tail-corrupt: record exceeds line size cap",
                "records": [], "baseline": None}
    parsed, flag = parse_record(last_line, root_real)
    if parsed is None:
        detail_reason = flag or "record fails strict schema"
        if "record_schema_version" in detail_reason:
            reason_out = "journal-tail-corrupt: schema-incompatible (%s) — no fallback" % detail_reason
        else:
            reason_out = "journal-tail-corrupt: %s — no fallback" % detail_reason
        return {"state": "corrupt", "reason": reason_out, "records": [], "baseline": None}
    if parsed == "foreign":
        return {"state": "ok", "records": [], "baseline": None, "foreign_last": True}
    return {"state": "ok", "records": [parsed], "baseline": parsed,
            "foreign_records_ignored": max(0, len(lines) - 1)}


def read_journal_history(git_dir: str, root_real: str) -> Dict[str, Any]:
    """--deep --history only: bounded diagnostic parsing of the tail (last
    100 complete lines). NEVER used by the L1 freshness decision."""
    path = journal_path(git_dir)
    inside, reason = _confined_in(git_dir, path)
    if not inside:
        return {"coverage": "partial", "state": "refused", "reason": reason, "entries": []}
    try:
        st_mode = os.lstat(path).st_mode
    except OSError as exc:
        return {"coverage": "partial", "state": "refused", "reason": str(exc), "entries": []}
    if not stat.S_ISREG(st_mode):
        return {"coverage": "partial", "state": "refused",
                "reason": "journal is not a regular file", "entries": []}
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - JOURNAL_MAX_BYTES))
            raw = handle.read(JOURNAL_MAX_BYTES)
    except OSError as exc:
        return {"coverage": "partial", "state": "refused", "reason": str(exc), "entries": []}
    text = raw.decode("utf-8", errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    entries: List[Dict[str, Any]] = []
    for index, line in enumerate(lines[-JOURNAL_MAX_RECORDS:]):
        parsed, flag = parse_record(line, root_real)
        if parsed == "foreign":
            entries.append({"line": index, "status": "foreign"})
        elif parsed is None:
            entries.append({"line": index, "status": "invalid", "reason": flag})
        else:
            entries.append({"line": index, "status": "ok",
                            "generated_at": parsed.get("generated_at"),
                            "head_sha": parsed.get("head_sha")})
    tail_truncated = bool(lines) and not text.endswith("\n")
    return {"coverage": "partial", "state": "diagnostic", "entries": entries,
            "tail_truncated": tail_truncated}


def _verify_written_tail(path: str, encoded: bytes, record: Dict[str, Any]) -> None:
    """Write control: the tail must re-parse to THIS record, else fail-closed
    (detection of interrupted records — promised by the contract)."""
    try:
        with open(path, "rb") as check:
            check.seek(0, os.SEEK_END)
            size = check.tell()
            check.seek(max(0, size - len(encoded) - 1))
            tail = check.read()
        tail_text = tail.decode("utf-8", errors="replace")
        last_line = [ln for ln in tail_text.split("\n") if ln.strip()][-1]
        parsed, flag = parse_record(last_line, record["project_root"])
    except (OSError, IndexError, UnicodeDecodeError) as exc:
        raise OSError("journal write verification failed: %s" % exc)
    if parsed is None or parsed == "foreign" or parsed.get("generated_at") != record["generated_at"]:
        raise OSError("journal write verification failed — record incomplete or unreadable back")


def append_record(git_dir: str, record: Dict[str, Any]) -> str:
    """--record only: append ONE line under an exclusive platform-standard
    advisory lock (fcntl.flock — POSIX target), then VERIFY the write by
    reading the tail back and re-parsing it WHILE STILL HOLDING the lock (a
    concurrent writer cannot interleave, so the check cannot report a complete
    write as incomplete). The contract promises DETECTION of
    interrupted/incomplete records, never absolute crash atomicity.
    Fail-closed: any error raises; main() maps to exit 2. Never rewrites,
    never truncates — history is preserved without loss."""
    directory = os.path.join(git_dir, JOURNAL_SUBDIR)
    os.makedirs(directory, exist_ok=True)  # explicit record mode only
    path = journal_path(git_dir)
    inside, reason = _confined_in(git_dir, path)
    if not inside:
        raise OSError("journal path escapes git dir: %s" % reason)
    try:
        st_mode = os.lstat(path).st_mode
    except FileNotFoundError:
        st_mode = None  # absent: legitimate first write (O_CREAT below)
    except OSError as exc:
        raise OSError("journal not statable: %s" % exc)
    if st_mode is not None and not stat.S_ISREG(st_mode):
        raise OSError("journal is not a regular file")  # FIFO/device/symlink refused
    line = json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"
    encoded = line.encode("utf-8")
    if len(encoded) > JOURNAL_MAX_LINE_BYTES:
        raise ValueError("record exceeds line size cap")
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | _O_NOFOLLOW, 0o600)
    try:
        if _FCNTL is not None:
            _FCNTL.flock(handle, _FCNTL.LOCK_EX)
        try:
            os.write(handle, encoded)
            _verify_written_tail(path, encoded, record)
        finally:
            if _FCNTL is not None:
                _FCNTL.flock(handle, _FCNTL.LOCK_UN)
    finally:
        os.close(handle)
    return path


# --------------------------------------------------------------------------
# Freshness (contract P0-3/P0-4 + P1-1/P1-2): mechanical stability of the
# COVERED elements — never global knowledge currency.
# --------------------------------------------------------------------------

def evaluate_freshness(baseline: Optional[Dict[str, Any]], journal_state: str,
                       journal_reason: Optional[str], current: Dict[str, Any],
                       docs_ai_absent: bool, max_age_hours: Optional[float],
                       now: datetime) -> Dict[str, Any]:
    def _freshness(result: str, reason: Optional[str] = None) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"result": result}
        if reason:
            entry["reason"] = reason
        if baseline:
            entry["baseline_record"] = {
                "generated_at": baseline.get("generated_at"),
                "head_sha": baseline.get("head_sha"),
                "standard_version": baseline.get("standard_version"),
                "tool_version": baseline.get("tool_version"),
            }
        return entry

    if journal_state in ("absent", "empty"):
        return _freshness(RESULT_UNKNOWN,
                          "no recorded baseline yet — run --record after a verified closure "
                          "(first-run state, documented as normal)")
    if journal_state == "unavailable":
        return _freshness(RESULT_UNKNOWN, journal_reason or "no journal channel")
    if journal_state == "refused":
        return _freshness(RESULT_UNKNOWN, journal_reason or "journal refused")
    if journal_state == "corrupt":
        return _freshness(RESULT_UNKNOWN,
                          journal_reason or ("journal tail corrupt — newest evidence "
                                             "unreadable, no silent fallback"))
    # journal ok
    if baseline is None:
        return _freshness(RESULT_UNKNOWN,
                          "no baseline recorded for this worktree yet — run --record")
    if docs_ai_absent or current.get("memory_fingerprint") is None:
        return _freshness(RESULT_UNKNOWN, "docs/ai absent — no fingerprint computed")
    if baseline.get("memory_fingerprint") is None:
        return _freshness(RESULT_UNKNOWN, "baseline has no fingerprint (incomplete record)")
    if baseline["memory_fingerprint"] != current["memory_fingerprint"]:
        return _freshness(RESULT_WARNING,
                          "memory changed since baseline (fingerprint mismatch — "
                          "memory may not cover the latest state)")
    if baseline.get("standard_version") != STANDARD_VERSION:
        return _freshness(RESULT_WARNING,
                          "standard-changed: standard_version moved since baseline "
                          "(%s -> %s)" % (baseline.get("standard_version"), STANDARD_VERSION))
    base_head = baseline.get("head_sha")
    current_head = current.get("head_sha")
    # Guard: alert when EITHER side carries a reference and they differ. Two
    # None values are equal (no git reference at all on both sides — fresh on
    # this covered item); None->SHA (first commit after a 0-commit baseline)
    # and SHA->None are MOVED references, never silently treated as unchanged.
    if base_head != current_head and (base_head is not None or current_head is not None):
        return _freshness(RESULT_WARNING,
                          "git reference moved since baseline — memory may not cover "
                          "recent work (conservative indicator, no editorial claim)")
    if max_age_hours is not None:
        baseline_at = datetime.fromisoformat(baseline["generated_at"])
        age_hours = (now - baseline_at).total_seconds() / 3600.0
        if age_hours < -24.0:
            return _freshness(RESULT_UNKNOWN,
                              "baseline timestamp is in the future beyond clock-skew "
                              "tolerance (%.2f h) — evidence is doubtful" % age_hours)
        if age_hours > max_age_hours:
            return _freshness(RESULT_WARNING,
                              "baseline older than --max-age-hours (%.2f h > %s h)"
                              % (age_hours, max_age_hours))
    return _freshness(RESULT_PASS)


# --------------------------------------------------------------------------
# L2 targeted reconciliation (--deep): bounded, coverage-bounded diagnostics.
# --------------------------------------------------------------------------

def deep_memory_diff(baseline_hashes: Optional[Dict[str, Any]],
                     contents: Dict[str, Optional[bytes]], states: Dict[str, str]) -> Dict[str, Any]:
    """Which of the 7 files changed since the baseline — per-file sha256 and
    size, never content dumps (bounded diagnostic, coverage partial)."""
    per_file: Dict[str, Any] = {}
    for name in MEMORY_FILES:
        data = contents.get(name)
        base = (baseline_hashes or {}).get(name)
        current: Optional[Dict[str, Any]] = None
        if states.get(name) == "ok" and data is not None:
            current = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        if current is None:
            delta = "disappeared" if base else "unchanged-absent"
        elif base is None:
            delta = "appeared"
        elif base.get("sha256") == current["sha256"]:
            delta = "unchanged"
        else:
            delta = "changed"
        per_file[name] = {"baseline": base, "current_state": states.get(name, "absent"),
                          "current": current, "delta": delta}
    return {"coverage": "partial", "observed": len(MEMORY_FILES), "per_file": per_file}


def deep_git_log(project_root: str, since_head: Optional[str]) -> Dict[str, Any]:
    """Bounded list of commits since the baseline head (diagnostic). No
    baseline head -> not computed (never guessed)."""
    if since_head is None:
        return {"coverage": "partial", "computed": False,
                "reason": "baseline has no git reference"}
    out, err, _ = git_run(project_root, "log", "--oneline", "-n", str(GIT_LOG_BOUND),
                          "%s..HEAD" % since_head)
    if out is None:
        return {"coverage": "partial", "computed": False, "reason": err or "git log failed"}
    commits = [line for line in out.splitlines() if line.strip()]
    return {"coverage": "partial", "computed": True, "count": len(commits),
            "bounded_by": GIT_LOG_BOUND, "commits": commits}


def deep_referenced_paths(contents: Dict[str, Optional[bytes]], states: Dict[str, str],
                          root_real: str) -> Dict[str, Any]:
    """Bounded existence spot-check of path-like tokens referenced by
    INDEX.md and WARNINGS.md — read-only, never editorial (existence only,
    same confinement as file reads). Coverage: partial, bounded."""
    tokens: List[str] = []
    seen = set()
    for name in ("INDEX.md", "WARNINGS.md"):
        data = contents.get(name)
        if data is None or states.get(name) != "ok":
            continue
        for match in PATH_TOKEN_RE.finditer(_normalize(data)):
            token = match.group(1)
            if token not in seen and not token.startswith(("http://", "https://")):
                seen.add(token)
                tokens.append(token)
            if len(tokens) >= REFERENCED_PATHS_MAX:
                break
        if len(tokens) >= REFERENCED_PATHS_MAX:
            break
    checks: List[Dict[str, Any]] = []
    missing = 0
    for token in tokens:
        candidate = os.path.join(root_real, token)
        inside, _ = _confined_in(root_real, candidate)
        if not inside:
            checks.append({"path": token, "result": RESULT_UNKNOWN,
                           "reason": "path escapes project root"})
            continue
        if os.path.lexists(candidate):
            checks.append({"path": token, "result": RESULT_PASS})
        else:
            checks.append({"path": token, "result": RESULT_WARNING, "reason": "referenced path missing"})
            missing += 1
    return {"coverage": "partial", "observed": len(checks), "bounded_by": REFERENCED_PATHS_MAX,
            "missing": missing, "checks": checks}


# --------------------------------------------------------------------------
# Report assembly + verdict (precedence identical to session-finalize)
# --------------------------------------------------------------------------

def resolve_verdict(results: List[str], docs_ai_absent: bool) -> Tuple[str, Dict[str, int]]:
    counts: Dict[str, int] = {RESULT_PASS: 0, RESULT_FAIL: 0, RESULT_WARNING: 0,
                              RESULT_UNKNOWN: 0, RESULT_NA: 0}
    for result in results:
        counts[result] += 1
    if counts[RESULT_FAIL] > 0:
        return VERDICT_FAIL, counts
    if docs_ai_absent:
        return VERDICT_NO_DOCS, counts
    if counts[RESULT_UNKNOWN] > 0:
        return VERDICT_INCOMPLETE, counts
    if counts[RESULT_WARNING] > 0:
        return VERDICT_WARNING, counts
    return VERDICT_PASS, counts


def validate(project_root: str, deep: bool, history: bool, strict: bool,
             mission: Optional[str], max_age_hours: Optional[float],
             now: datetime) -> Tuple[Dict[str, Any], int]:
    root_real = os.path.realpath(project_root)
    docs_ai_path = os.path.join(root_real, DOCS_AI_DIR)
    docs_ai_absent = not os.path.isdir(docs_ai_path)

    contents: Dict[str, Optional[bytes]] = {}
    states: Dict[str, str] = {}
    reasons: Dict[str, str] = {}
    for name in MEMORY_FILES:
        state, data, reason = confined_read(root_real, os.path.join(docs_ai_path, name))
        states[name] = state
        contents[name] = data if state == "ok" else None
        if state in ("outside", "unreadable") and reason:
            reasons[name] = reason

    git_info = discover_git(project_root)
    git_ok = git_info.get("state") == "ok"
    current: Dict[str, Any] = {
        "memory_fingerprint": compute_memory_fingerprint(contents) if not docs_ai_absent else None,
        "head_sha": git_info.get("head_sha") if git_ok else None,
        "git_status_signature": compute_git_status_signature(git_info["head_sha"], git_info["porcelain"])
        if git_ok and git_info.get("head_sha") and git_info.get("porcelain") is not None else None,
    }

    init_axis = check_initialization(contents, states, reasons, docs_ai_absent)

    if git_ok:
        journal = read_journal(git_info["git_dir"], root_real)
        journal_state = journal["state"]
    else:
        git_reason = git_info.get("reason", "git unavailable")
        journal = {"state": "unavailable", "reason": git_reason, "records": [], "baseline": None}
        journal_state = "unavailable"
    baseline = journal.get("baseline")

    last_validation_axis: Dict[str, Any] = {"result": RESULT_UNKNOWN}
    if journal_state in ("absent", "empty"):
        last_validation_axis = {"result": RESULT_NA, "state": "absent",
                                "reason": "never validated yet — record a mechanical baseline "
                                          "with --record after a verified closure"}
    elif journal_state == "unavailable":
        last_validation_axis = {"result": RESULT_NA, "state": "unavailable",
                                "reason": "no journal channel (declared): %s" % journal.get("reason")}
    elif journal_state == "corrupt":
        last_validation_axis = {"result": RESULT_UNKNOWN, "state": "corrupt",
                                "reason": journal.get("reason")}
    elif journal_state == "refused":
        last_validation_axis = {"result": RESULT_UNKNOWN, "state": "refused",
                                "reason": journal.get("reason")}
    elif baseline is None:
        last_validation_axis = {"result": RESULT_NA, "state": "absent",
                                "reason": "no baseline recorded for this worktree yet — run --record"}
    else:
        last_validation_axis = {"result": RESULT_PASS, "state": "ok",
                                "baseline_generated_at": baseline.get("generated_at"),
                                "baseline_head_sha": baseline.get("head_sha")}

    freshness = evaluate_freshness(baseline, journal_state, journal.get("reason"),
                                   current, docs_ai_absent, max_age_hours, now)

    axes: List[Dict[str, Any]] = [init_axis, last_validation_axis, freshness]
    deep_diagnostics: Optional[Dict[str, Any]] = None
    if deep:
        deep_diagnostics = {"coverage": "partial"}
        baseline_for_diff = baseline if journal_state == "ok" else None
        current_fingerprint = current.get("memory_fingerprint")
        if baseline_for_diff is not None and baseline_for_diff.get("memory_fingerprint") \
                and baseline_for_diff["memory_fingerprint"] != current_fingerprint:
            deep_diagnostics["memory_diff"] = deep_memory_diff(
                baseline_for_diff.get("file_hashes"), contents, states)
        base_head = baseline_for_diff.get("head_sha") if baseline_for_diff else None
        if git_ok and base_head is not None and current.get("head_sha") is not None \
                and base_head != current["head_sha"]:
            deep_diagnostics["git_log_since_baseline"] = deep_git_log(project_root, base_head)
        if not docs_ai_absent:
            deep_diagnostics["referenced_paths"] = deep_referenced_paths(contents, states, root_real)
            if deep_diagnostics["referenced_paths"].get("missing", 0) > 0:
                axes.append({"id": "referenced_paths", "result": RESULT_WARNING,
                             "coverage": "partial",
                             "detail": deep_diagnostics["referenced_paths"]})

    if history:
        if git_ok:
            deep_history = read_journal_history(git_info["git_dir"], root_real)
        else:
            deep_history = {"coverage": "partial", "state": "unavailable",
                            "reason": git_info.get("reason", "git unavailable"), "entries": []}

    axis_results = [axis["result"] for axis in axes]
    verdict, counts = resolve_verdict(axis_results, docs_ai_absent)

    coverage = {
        "covered": [
            "content of the 7 canonical memory files (canonical sha256 fingerprint)",
            "git reference (head_sha)",
            "standard_version of the memory-standard contract",
        ],
        "not_covered": [
            "editorial truth of the memory content (honesty boundary)",
            "other repository files",
            "global currency of project knowledge",
        ],
    }

    report: Dict[str, Any] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "standard_version": STANDARD_VERSION,
        "mission": mission,
        "snapshot": {
            "project_root": root_real,
            "branch": git_info.get("branch") if git_ok else None,
            "head_sha": current.get("head_sha"),
            "git_status_signature": current.get("git_status_signature"),
            "memory_fingerprint": current.get("memory_fingerprint"),
            "generated_at": now.isoformat(),
            "axes": {
                "initialization": init_axis,
                "last_validation": last_validation_axis,
                "freshness": freshness,
                # Additional deep axes count toward the verdict, so they MUST be
                # visible in the report (never a verdict backed by hidden axes).
                # The list starts with the 3 canonical (id-less) axes — deep axes
                # are appended after and always carry their "id".
                **{axis["id"]: axis for axis in axes[3:]},
            },
            "coverage": coverage,
        },
        "summary": {"verdict": verdict, "counts": counts},
    }
    if deep:
        report["snapshot"]["deep_diagnostics"] = deep_diagnostics
    if history:
        report["snapshot"]["history"] = deep_history

    exit_code = VERDICT_EXIT[verdict]
    if strict and verdict == VERDICT_WARNING:
        exit_code = 1
    return report, exit_code


def record(project_root: str, mission: Optional[str], now: datetime) -> Tuple[Dict[str, Any], int]:
    """--record: freeze a MECHANICAL BASELINE observation (never a truth
    certification). Refuses to baseline a broken state: when the
    initialization axis (or any observation essential to the baseline) is
    fail or unknown, the record is REFUSED and the journal is left
    untouched (contract: an explicit refusal, never a partial write).
    The only writing mode; appends to the per-worktree journal; fail-closed."""
    root_real = os.path.realpath(project_root)
    docs_ai_path = os.path.join(root_real, DOCS_AI_DIR)
    docs_ai_absent = not os.path.isdir(docs_ai_path)

    contents: Dict[str, Optional[bytes]] = {}
    states: Dict[str, str] = {}
    reasons: Dict[str, str] = {}
    for name in MEMORY_FILES:
        state, data, reason = confined_read(root_real, os.path.join(docs_ai_path, name))
        states[name] = state
        contents[name] = data if state == "ok" else None
        if state in ("outside", "unreadable") and reason:
            reasons[name] = reason

    if docs_ai_absent:
        return ({"recorded": False, "refused": True,
                 "reason": "docs/ai absent — nothing to baseline (verdict no_docs)"}, 2)

    init_axis = check_initialization(contents, states, reasons, docs_ai_absent)
    if init_axis["result"] in (RESULT_FAIL, RESULT_UNKNOWN):
        return ({"recorded": False, "refused": True,
                 "reason": "initialization is %s — refusing to baseline a broken state "
                           "(journal untouched)" % init_axis["result"],
                 "detail": init_axis.get("detail")}, 2)

    git_info = discover_git(project_root)
    if git_info.get("state") != "ok":
        return ({"recorded": False, "refused": True,
                 "reason": "git unavailable — the journal requires a git worktree",
                 "detail": {"state": git_info.get("state"), "reason": git_info.get("reason")}}, 2)

    record_entry = {
        "generated_at": now.isoformat(),
        "tool_version": TOOL_VERSION,
        "standard_version": STANDARD_VERSION,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "project_root": root_real,
        "branch": git_info.get("branch"),
        "head_sha": git_info.get("head_sha"),
        "memory_fingerprint": compute_memory_fingerprint(contents),
        "git_status_signature": compute_git_status_signature(git_info["head_sha"], git_info["porcelain"])
        if git_info.get("head_sha") and git_info.get("porcelain") is not None else None,
        "file_hashes": {
            name: ({"sha256": hashlib.sha256(contents[name]).hexdigest(),
                    "bytes": len(contents[name])}
                   if contents.get(name) is not None else None)
            for name in MEMORY_FILES
        },
        "result": RESULT_PASS,
        "mission": mission,
    }
    path = append_record(git_info["git_dir"], record_entry)
    return {"recorded": True, "journal": path, "record": record_entry}, 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="project-context-health",
        description="Deterministic read-only project-memory preflight validator "
                    "(report as JSON on stdout). --record is the ONLY writing mode: "
                    "it appends a mechanical baseline to the per-worktree journal.",
    )
    parser.add_argument("--project", default=os.getcwd(),
                        help="project root (default: current directory)")
    parser.add_argument("--deep", action="store_true",
                        help="L2: targeted reconciliation on anomalies only — bounded, "
                             "coverage-partial diagnostics (never exhaustive)")
    parser.add_argument("--history", action="store_true",
                        help="L2: bounded listing of this worktree's journal records (diagnostic)")
    parser.add_argument("--max-age-hours", type=float, default=None,
                        help="opt-in age constraint on the baseline timestamp; when ABSENT "
                             "no age constraint is applied at all")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on warnings; never converts a missing proof "
                             "(incomplete) into a business failure")
    parser.add_argument("--mission", default=None,
                        help="free-form mission label embedded in the report/record")
    parser.add_argument("--record", action="store_true",
                        help="record a MECHANICAL BASELINE of the current docs/ai/ + git state "
                             "(the only writing mode; normally run after a verified closure — "
                             "it is not a documentary-truth certification)")
    args = parser.parse_args(argv)

    project_root = args.project
    if not os.path.isdir(project_root):
        print("project-context-health: project root is not a directory: %s" % project_root,
              file=sys.stderr)
        return 2

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # never exit 1 for a locale artifact
    except (AttributeError, OSError, ValueError):
        pass
    now = datetime.now(timezone.utc)
    try:
        if args.record:
            payload, exit_code = record(project_root, args.mission, now)
            json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
            return exit_code
        report, exit_code = validate(project_root, args.deep, args.history, args.strict,
                                     args.mission, args.max_age_hours, now)
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return exit_code
    except Exception as exc:  # fail-closed: report on stderr, exit 2, never crash
        print("project-context-health: environmental failure: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
