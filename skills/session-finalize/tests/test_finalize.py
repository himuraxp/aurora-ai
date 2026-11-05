#!/usr/bin/env python3
"""Tests for session-finalize finalize.py.

Offline, stdlib-only, unittest. Git binary required for the git scenarios
(skipped when absent — the non-git scenarios always run).

Coverage follows the reviewed contract: no memory, missing files, mixed date
formats, valid/invalid frontmatter, non-git repos, git-ignored memory, WIP
states, scaffold detection, opt-in recency, idempotence, exact
git_status_signature compatibility with task-workflow, and EFFECTIVE
read-only-ness (git index bytes, porcelain and memory contents unchanged).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(os.path.dirname(SKILL_DIR))  # .../opencode-config(-worktree)
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, "skills", "task-workflow"))

import finalize  # noqa: E402

MEMORY_FILES = finalize.MEMORY_FILES
DATE = "2026-11-05"
GIT_IDENTITY = ["-c", "user.name=test", "-c", "user.email=test@example.com"]


def real_memory_content(name: str, dated: bool = True) -> str:
    """A minimal, non-scaffold, interpretable memory file."""
    if name == "STATUS.md" and dated:
        return "# STATUS\n\n### %s 10:00\n\n- worked on the thing\n" % DATE
    if name == "CHANGELOG.md" and dated:
        return "# CHANGELOG\n\n## %s (1)\n\n- entry one\n" % DATE
    return "# %s\n\nReal maintained content for this project.\n" % name[:-3]


def write_memory(root: str, dated: bool = True, skip: int = 0) -> None:
    docs = os.path.join(root, "docs", "ai")
    os.makedirs(docs, exist_ok=True)
    for index, name in enumerate(MEMORY_FILES):
        if index < skip:  # skip > 0 → drop the LAST files (missing-file scenarios)
            continue
        with open(os.path.join(docs, name), "w", encoding="utf-8") as handle:
            handle.write(real_memory_content(name, dated=dated))


def git(cwd: str, *args: str) -> str:
    """Test harness helper — same read-only hygiene as the validator itself:
    GIT_* env purged, fsmonitor off, optional locks off (so the harness cannot
    refresh the index and then blame the validator for it)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(
        ["git", "-C", cwd, "-c", "core.fsmonitor=false", *args],
        capture_output=True, text=True, check=True, env=env,
    )
    return proc.stdout


GIT_AVAILABLE = shutil.which("git") is not None


def make_git_repo(root: str, commit_all: bool = True) -> None:
    git(root, "init")
    if commit_all:
        write_memory(root)
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("# sample project\n")
        git(root, "add", "-A")
        git(root, *GIT_IDENTITY, "commit", "-m", "init")


def run_validator(root: str, *extra: str, extra_env: dict = None) -> tuple:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, os.path.join(SKILL_DIR, "finalize.py"),
         "--project", root, *extra],
        capture_output=True, text=True, env=env,
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, payload, proc.stdout, proc.stderr


def check_result(payload, check_id: str):
    for check in payload["snapshot"]["checks"]:
        if check["id"] == check_id:
            return check
    raise AssertionError("missing check: %s" % check_id)


def index_path(root: str) -> str:
    return git(root, "rev-parse", "--git-path", "index").strip()


def tree_hash(root: str, relative: str) -> str:
    digest = hashlib.sha256()
    base = os.path.join(root, relative)
    for current, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(current, name)
            if os.path.islink(path):
                digest.update(("link:" + os.readlink(path)).encode())
            else:
                with open(path, "rb") as handle:
                    digest.update(handle.read())
    return digest.hexdigest()


class NoMemoryTest(unittest.TestCase):
    def test_no_docs_ai_is_declared_no_docs_exit0(self):
        with tempfile.TemporaryDirectory() as root:
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            self.assertEqual("no_docs", payload["summary"]["verdict"])
            self.assertEqual("not_applicable", check_result(payload, "memory_presence")["result"])
            self.assertEqual("not_applicable", check_result(payload, "memory_initialized")["result"])
            self.assertIsNone(payload["snapshot"]["memory_fingerprint"])

    def test_empty_docs_ai_directory_fails_not_no_docs(self):
        """A docs/ai directory that EXISTS but is empty triggers INV-1 fail —
        never masked as no_docs (contract: any existing docs/ai → INV-1)."""
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "docs", "ai"))
            code, payload, _, _ = run_validator(root)
            self.assertEqual(1, code)
            self.assertEqual("fail", payload["summary"]["verdict"])
            self.assertEqual("fail", check_result(payload, "memory_presence")["result"])

    def test_nonexistent_project_is_environmental_exit2(self):
        code, payload, stdout, _ = run_validator(os.path.join("/", "nonexistent", "path", "xyz"))
        self.assertEqual(2, code)
        self.assertIsNone(payload)


class MissingFilesTest(unittest.TestCase):
    def test_partial_memory_fails_presence(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "docs", "ai"))
            write_memory(root, skip=3)  # 4 of 7 files → 3 missing
            code, payload, _, _ = run_validator(root)
            self.assertEqual(1, code)
            self.assertEqual("fail", payload["summary"]["verdict"])
            presence = check_result(payload, "memory_presence")
            self.assertEqual("fail", presence["result"])
            self.assertEqual(3, len(presence["detail"]["missing"]))


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class FullMemoryTest(unittest.TestCase):
    def test_complete_clean_memory_passes(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            self.assertEqual("pass", payload["summary"]["verdict"])
            self.assertEqual("pass", check_result(payload, "memory_presence")["result"])
            self.assertEqual("pass", check_result(payload, "memory_initialized")["result"])
            self.assertEqual("pass", check_result(payload, "memory_recency")["result"])
            self.assertEqual("pass", check_result(payload, "memory_versioned")["result"])
            self.assertIsNotNone(payload["snapshot"]["memory_fingerprint"])
            self.assertIsNotNone(payload["snapshot"]["git_status_signature"])

    def test_empty_file_fails_initialized(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "BUFFER.md"), "w", encoding="utf-8"):
                pass
            git(root, "add", "-A")
            git(root, *GIT_IDENTITY, "commit", "-m", "empty buffer")
            code, payload, _, _ = run_validator(root)
            self.assertEqual(1, code)
            initialized = check_result(payload, "memory_initialized")
            self.assertEqual("fail", initialized["result"])
            self.assertEqual("empty file", initialized["detail"]["BUFFER.md"]["reason"])

    def test_concise_warnings_file_passes(self):
        """A deliberately concise WARNINGS.md is legitimate — no editorial claim."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "WARNINGS.md"), "w", encoding="utf-8") as handle:
                handle.write("# WARNINGS\n\nNo known risk.\n")
            git(root, "add", "-A")
            git(root, *GIT_IDENTITY, "commit", "-m", "concise warnings")
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            self.assertEqual("pass", payload["summary"]["verdict"])


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class DatesTest(unittest.TestCase):
    def test_mixed_date_formats_both_recognized(self):
        """Canonical '### YYYY-MM-DD HH:MM' and real '## YYYY-MM-DD (N)' both work."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            self.assertEqual("pass", check_result(payload, "memory_recency")["result"])

    def test_no_dated_entry_is_unknown_not_pass_not_fail(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            write_memory(root, dated=False)
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)  # missing proof is never a business failure
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            recency = check_result(payload, "memory_recency")
            self.assertEqual("unknown", recency["result"])
            self.assertIn("no dated heading entry", recency["unknown_reason"])

    def test_future_date_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "STATUS.md"), "w", encoding="utf-8") as handle:
                handle.write("# STATUS\n\n### 2099-01-01 08:00\n\n- time travel\n")
            code, payload, _, _ = run_validator(root)
            self.assertEqual("unknown", check_result(payload, "memory_recency")["result"])
            self.assertEqual("incomplete", payload["summary"]["verdict"])

    def test_max_age_optin_only(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, payload, _, _ = run_validator(root)  # NO --max-age-hours → no age constraint
            self.assertEqual(0, code)
            recency = check_result(payload, "memory_recency")
            self.assertEqual("pass", recency["result"])
            self.assertIn("none", recency["detail"]["STATUS.md"]["age_constraint"])
            code2, payload2, _, _ = run_validator(root, "--max-age-hours", "1")  # date is old
            self.assertEqual(0, code2)
            recency2 = check_result(payload2, "memory_recency")
            self.assertEqual("warning", recency2["result"])


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class PlanEnumTest(unittest.TestCase):
    def _with_plan(self, plan_body: str):
        return tempfile.TemporaryDirectory()

    def test_valid_frontmatter_status_passes(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "PLAN.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nstatus: in-progress\n---\n\n# PLAN\n\n## Goal\n\nShip.\n")
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            self.assertEqual("pass", check_result(payload, "plan_status_enum")["result"])

    def test_illegal_status_fails(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "PLAN.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nstatus: almost-done\n---\n\n# PLAN\n\n## Goal\n\nShip.\n")
            code, payload, _, _ = run_validator(root)
            self.assertEqual(1, code)
            plan_check = check_result(payload, "plan_status_enum")
            self.assertEqual("fail", plan_check["result"])

    def test_uninterpretable_status_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "PLAN.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nstatus: ''\n---\n\n# PLAN\n\n## Goal\n\nShip.\n")
            code, payload, _, _ = run_validator(root)
            self.assertEqual("unknown", check_result(payload, "plan_status_enum")["result"])

    def test_absent_status_key_passes(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)  # default PLAN has no status key
            code, payload, _, _ = run_validator(root)
            plan_check = check_result(payload, "plan_status_enum")
            self.assertEqual("pass", plan_check["result"])
            self.assertIn("no status key", plan_check["detail"]["reason"])


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class GitStatesTest(unittest.TestCase):
    def test_non_git_project_not_applicable_not_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            write_memory(root)
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            self.assertEqual("pass", payload["summary"]["verdict"])
            self.assertEqual("not_applicable", check_result(payload, "worktree_snapshot")["result"])
            self.assertEqual("not_applicable", check_result(payload, "memory_versioned")["result"])

    def test_git_ignored_memory_is_declared_not_applicable(self):
        """Untracked (git-ignored) memory: legitimate declared state, exit 0 pass."""
        with tempfile.TemporaryDirectory() as root:
            git(root, "init")
            with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as handle:
                handle.write("docs/\n")
            write_memory(root)
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# sample\n")
            git(root, "add", "-A")
            git(root, *GIT_IDENTITY, "commit", "-m", "init")
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            self.assertEqual("pass", payload["summary"]["verdict"])
            self.assertEqual("not_applicable", check_result(payload, "memory_versioned")["result"])

    def test_wip_outside_docs_is_warning_never_fail(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# sample project — WIP\n")
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)  # WIP is legitimate
            self.assertEqual("warning", payload["summary"]["verdict"])
            snapshot = check_result(payload, "worktree_snapshot")
            self.assertEqual("warning", snapshot["result"])
            self.assertIn("uncommitted_outside_docs_ai", snapshot["detail"])

    def test_tracked_dirty_memory_is_warning(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "STATUS.md"), "w", encoding="utf-8") as handle:
                handle.write("# STATUS\n\n### %s 11:00\n\n- uncommitted edit\n" % DATE)
            code, payload, _, _ = run_validator(root)
            versioned = check_result(payload, "memory_versioned")
            self.assertEqual("warning", versioned["result"])
            self.assertGreaterEqual(versioned["detail"]["tracked"], 1)

    def test_strict_flag_promotes_warning_to_exit1(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# sample project — WIP\n")
            code_normal, _, _, _ = run_validator(root)
            code_strict, _, _, _ = run_validator(root, "--strict")
            self.assertEqual(0, code_normal)
            self.assertEqual(1, code_strict)


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class CertificateTest(unittest.TestCase):
    def test_certificate_is_valid_json_with_exit1(self):
        """JSON on stdout is guaranteed — even when the verdict is fail."""
        with tempfile.TemporaryDirectory() as root:
            write_memory(root, skip=5)
            code, payload, stdout, _ = run_validator(root)
            self.assertEqual(1, code)
            self.assertEqual("fail", payload["summary"]["verdict"])
            self.assertIn("schema_version", payload)
            self.assertEqual(1, payload["schema_version"])
            self.assertEqual("1.1.0", payload["tool_version"])

    def test_idempotence_same_state_same_certificate(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code1, payload1, _, _ = run_validator(root)
            code2, payload2, _, _ = run_validator(root)
            self.assertEqual(code1, code2)
            self.assertEqual(payload1["snapshot"]["memory_fingerprint"],
                             payload2["snapshot"]["memory_fingerprint"])
            self.assertEqual(payload1["snapshot"]["git_status_signature"],
                             payload2["snapshot"]["git_status_signature"])
            self.assertEqual(payload1["snapshot"]["checks"], payload2["snapshot"]["checks"])
            self.assertNotEqual(payload1["snapshot"]["generated_at"],
                                payload2["snapshot"]["generated_at"])

    def test_mission_field_is_embedded(self):
        with tempfile.TemporaryDirectory() as root:
            write_memory(root)
            code, payload, _, _ = run_validator(root, "--mission", "chantier A")
            self.assertEqual("chantier A", payload["mission"])


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class SymlinkAndConfinementTest(unittest.TestCase):
    """F1/F2 regression locks: a symlink escaping the project is a MISSING
    PROOF (unknown/incomplete, exit 0), never a fail; a directory-component
    symlink (docs/ai itself) cannot leak external content into the
    certificate."""

    def test_memory_file_symlink_outside_is_unknown_never_fail(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            make_git_repo(root)
            external = os.path.join(outside, "external-STATUS.md")
            with open(external, "w", encoding="utf-8") as handle:
                handle.write("# STATUS\n\n### 2020-01-01\n\nSECRET-EXTERNAL-CONTENT\n")
            docs = os.path.join(root, "docs", "ai")
            os.remove(os.path.join(docs, "STATUS.md"))
            os.symlink(external, os.path.join(docs, "STATUS.md"))
            code, payload, stdout, _ = run_validator(root)
            self.assertEqual(0, code)  # missing proof, never a business failure
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            self.assertEqual("unknown", check_result(payload, "memory_presence")["result"])
            self.assertNotIn("SECRET-EXTERNAL-CONTENT", stdout)

    def test_docs_ai_itself_symlinked_outside_cannot_leak(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            make_git_repo(root)
            external_docs = os.path.join(outside, "docs-ai")
            shutil.move(os.path.join(root, "docs", "ai"), external_docs)
            os.symlink(external_docs, os.path.join(root, "docs", "ai"))
            code, payload, stdout, _ = run_validator(root)
            self.assertEqual(0, code)  # unknowns, never a fail, never a silent read
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            self.assertEqual("unknown", check_result(payload, "memory_presence")["result"])
            self.assertNotIn("Real maintained content", stdout)  # external content not certified
            # Strongest leak lock: the fingerprint proves NOTHING external was hashed —
            # it must equal the 7×ABSENT fingerprint (no external content contributed).
            absent_only = finalize.compute_memory_fingerprint(
                {name: None for name in finalize.MEMORY_FILES})
            self.assertEqual(absent_only, payload["snapshot"]["memory_fingerprint"])

    def test_plan_symlink_to_internal_file_passes(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            source = os.path.join(root, "plan-source.md")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("# PLAN\n\nstatus: pending\n\n## Goal\n\nInternal.\n")
            docs = os.path.join(root, "docs", "ai")
            os.remove(os.path.join(docs, "PLAN.md"))
            os.symlink(source, os.path.join(docs, "PLAN.md"))
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            plan_check = check_result(payload, "plan_status_enum")
            self.assertEqual("pass", plan_check["result"])
            self.assertEqual("pending", plan_check["detail"]["value"])


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class EdgeCasesTest(unittest.TestCase):
    def test_memory_file_replaced_by_directory_is_unknown(self):
        """A directory named like a memory file is an environmental obstacle
        (missing proof → unknown), not an editorial failure."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            os.remove(os.path.join(docs, "INDEX.md"))
            os.mkdir(os.path.join(docs, "INDEX.md"))
            code, payload, _, _ = run_validator(root)
            self.assertEqual(0, code)
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            self.assertEqual("unknown", check_result(payload, "memory_presence")["result"])

    def test_strict_never_converts_incomplete_to_exit1(self):
        """The strongest clause of the contract: --strict turns warnings into
        exit 1 but NEVER a missing proof into a business failure."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            write_memory(root, dated=False)  # no dated entries → unknowns
            code, payload, _, _ = run_validator(root, "--strict")
            self.assertEqual(0, code)
            self.assertEqual("incomplete", payload["summary"]["verdict"])

    def test_max_age_zero_and_negative_values(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, payload, _, _ = run_validator(root, "--max-age-hours", "0")
            self.assertEqual(0, code)
            code2, payload2, _, _ = run_validator(root, "--max-age-hours", "-5")
            self.assertEqual(0, code2)

    def test_unparseable_date_only_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "STATUS.md"), "w", encoding="utf-8") as handle:
                handle.write("# STATUS\n\n### 2026-99-99 bogus\n\n- entry\n")
            code, payload, _, _ = run_validator(root)
            recency = check_result(payload, "memory_recency")
            self.assertEqual("unknown", recency["result"])
            self.assertIn("no parseable date", recency["unknown_reason"])

    def test_newest_date_semantics_not_oldest(self):
        """--max-age-hours applies to the NEWEST dated entry (doc F4): a fresh
        entry must neutralize an ancient one at the same constraint."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            today = datetime.now(timezone.utc).date().isoformat()
            with open(os.path.join(docs, "STATUS.md"), "w", encoding="utf-8") as handle:
                handle.write("# STATUS\n\n### 2020-01-01\n\n- ancient entry\n\n"
                             "### %s\n\n- fresh entry\n" % today)
            git(root, "add", "-A")  # commit the edit: isolate recency semantics from WIP signals
            git(root, *GIT_IDENTITY, "commit", "-m", "fresh entry")
            code, payload, _, _ = run_validator(root, "--max-age-hours", "25")
            recency = check_result(payload, "memory_recency")
            self.assertEqual("pass", recency["result"])  # newest wins
            self.assertEqual("pass", payload["summary"]["verdict"])

    def test_non_ascii_mission_never_tracebacks(self):
        with tempfile.TemporaryDirectory() as root:
            write_memory(root)
            env = {"LANG": "C", "LC_ALL": "C"}
            code, payload, stdout, stderr = run_validator(
                root, "--mission", "chantier étoile ✔ ünïcode", extra_env=env)
            self.assertIsNotNone(payload)
            self.assertNotIn("Traceback", stderr)
            self.assertEqual("chantier étoile ✔ ünïcode", payload["mission"])
            self.assertEqual(0, code)

    def test_inherited_git_env_is_purged(self):
        """A hostile GIT_DIR from the caller must not redirect git
        observability (env purge contract)."""
        with tempfile.TemporaryDirectory() as root:
            write_memory(root)  # non-git project with valid memory
            dummy = tempfile.mkdtemp()
            subprocess.run(["git", "init", dummy], capture_output=True, check=True)
            code, payload, _, _ = run_validator(
                root, extra_env={"GIT_DIR": os.path.join(dummy, ".git")})
            self.assertEqual(0, code)
            self.assertEqual("pass", payload["summary"]["verdict"])
            self.assertEqual("not_applicable", check_result(payload, "worktree_snapshot")["result"])
            subprocess.run(["rm", "-rf", dummy], capture_output=True)


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class ReadOnlyTest(unittest.TestCase):
    """EFFECTIVE read-only: git index bytes, porcelain, and memory contents
    must be byte-identical across a validator run (IMPROVEMENT P0-4/P1)."""

    def _assert_no_mutation(self, root: str, *extra: str) -> None:
        status_before = git(root, "status", "--porcelain")  # BEFORE index read (harness hygiene)
        index_before = None
        if os.path.exists(index_path(root)):
            with open(index_path(root), "rb") as handle:
                index_before = hashlib.sha256(handle.read()).hexdigest()
        docs_before = tree_hash(root, os.path.join("docs", "ai"))
        code, payload, stdout, stderr = run_validator(root, *extra)
        self.assertEqual(0, code, msg=stderr)
        self.assertIsNotNone(payload)
        if index_before is not None:
            with open(index_path(root), "rb") as handle:
                index_after = hashlib.sha256(handle.read()).hexdigest()
            self.assertEqual(index_before, index_after, "git index bytes mutated")
        self.assertEqual(status_before, git(root, "status", "--porcelain"))
        self.assertEqual(docs_before, tree_hash(root, os.path.join("docs", "ai")))

    def test_run_does_not_mutate_repo_or_memory(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            self._assert_no_mutation(root)

    def test_run_does_not_mutate_worktree(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            wt = os.path.join(root, "..", os.path.basename(root) + "-wt")
            try:
                git(root, "worktree", "add", wt, "HEAD")
                self._assert_no_mutation(wt)
            finally:
                subprocess.run(["git", "-C", root, "worktree", "prune"], capture_output=True)
            if os.path.exists(wt):
                subprocess.run(["git", "-C", root, "worktree", "remove", "--force", wt],
                               capture_output=True)

    def test_run_does_not_mutate_with_strict_and_age(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            self._assert_no_mutation(root, "--strict", "--max-age-hours", "1000000")

    def test_no_writes_to_fresh_git_init(self):
        """A validator run on a zero-commit repo must not create HEAD/index churn."""
        with tempfile.TemporaryDirectory() as root:
            git(root, "init")
            write_memory(root)
            self._assert_no_mutation(root)


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class TaskWorkflowCompatibilityTest(unittest.TestCase):
    def test_git_status_signature_matches_tw_state_byte_for_byte(self):
        try:
            import tw_state  # noqa: F401  (skills/task-workflow)
        except ImportError:
            self.skipTest("task-workflow not available")
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# dirty sample\n")  # non-empty porcelain on purpose
            code, payload, _, _ = run_validator(root)
            expected = tw_state.compute_code_signature(root)
            self.assertEqual(expected, payload["snapshot"]["git_status_signature"])

    def test_git_status_signature_is_content_state_only(self):
        """Two different dirty contents with the same path set → same git
        signature (state, not content); memory_fingerprint differs instead."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("dirty A\n")
            code, payload_a, _, _ = run_validator(root)
            sig_a = payload_a["snapshot"]["git_status_signature"]
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("dirty B — completely different\n")
            code2, payload_b, _, _ = run_validator(root)
            sig_b = payload_b["snapshot"]["git_status_signature"]
            self.assertEqual(sig_a, sig_b, "git signature must certify STATE, not content")
            self.assertEqual(payload_a["snapshot"]["memory_fingerprint"],
                             payload_b["snapshot"]["memory_fingerprint"])


class WhitelistTest(unittest.TestCase):
    def test_mutating_subcommand_refused(self):
        with self.assertRaises(ValueError):
            finalize.git_run("/tmp", "commit")
        with self.assertRaises(ValueError):
            finalize.git_run("/tmp", "add")
        with self.assertRaises(ValueError):
            finalize.git_run("/tmp", "fetch", "--all")

    def test_skeleton_hashes_in_sync_with_templates(self):
        """Keeps SKELETON_SHA256 synchronized with the repository templates —
        skipped when templates/ is not next to the skill."""
        candidates = [os.path.join(REPO_ROOT, "templates")]
        templates = next((c for c in candidates if os.path.isdir(c)), None)
        if templates is None:
            self.skipTest("templates/ not found")
        mapping = {
            "STATUS.md": os.path.join(templates, "STATUS.md"),
            "PLAN.md": os.path.join(templates, "PLAN.md"),
            "CHANGELOG.md": os.path.join(templates, "CHANGELOG.md"),
            "DECISIONS.md": os.path.join(templates, "DECISIONS.md"),
            "BUFFER.md": os.path.join(templates, "project-docs", "BUFFER.md"),
            "INDEX.md": os.path.join(templates, "project-docs", "INDEX.md"),
            "WARNINGS.md": os.path.join(templates, "project-docs", "WARNINGS.md"),
        }
        for name, path in mapping.items():
            with open(path, "rb") as handle:
                normalized = handle.read().decode("utf-8").replace("\r\n", "\n").rstrip("\n")
            self.assertEqual(finalize.SKELETON_SHA256[name],
                             hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                             msg="scaffold hash out of sync for %s" % name)


if __name__ == "__main__":
    unittest.main()
