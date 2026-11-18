#!/usr/bin/env python3
"""Tests for project-context-health context_health.py.

Offline, stdlib-only, unittest. Git binary required for the git scenarios
(skipped when absent — non-git scenarios always run).

Coverage follows the reviewed contract: first-run state, record→fresh,
staleness variants (memory changed / git moved / standard changed /
max-age), tool_version decoupling, journal hardening (truncated tail,
corrupt line, empty, symlink, foreign-worktree filtering, per-worktree
isolation), strict semantics, idempotence, append-only history, validate
non-mutation, record fail-closed, git whitelist + log bounds, cross-tool
fingerprint pins vs session-finalize, referenced-path spot checks.
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
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(os.path.dirname(SKILL_DIR))
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, "skills", "session-finalize"))

import context_health as ch  # noqa: E402

MEMORY_FILES = ch.MEMORY_FILES
DATE = "2026-11-05"
GIT_IDENTITY = ["-c", "user.name=test", "-c", "user.email=test@example.com"]


def real_memory_content(name: str, dated: bool = True, marker: str = "v1") -> str:
    if name == "STATUS.md" and dated:
        return "# STATUS\n\n### %s 10:00\n\n- worked on the thing %s\n" % (DATE, marker)
    if name == "CHANGELOG.md" and dated:
        return "# CHANGELOG\n\n## %s (1)\n\n- entry one %s\n" % (DATE, marker)
    return "# %s\n\nReal maintained content for this project (%s).\n" % (name[:-3], marker)


def write_memory(root: str, dated: bool = True, marker: str = "v1") -> None:
    docs = os.path.join(root, "docs", "ai")
    os.makedirs(docs, exist_ok=True)
    for name in MEMORY_FILES:
        with open(os.path.join(docs, name), "w", encoding="utf-8") as handle:
            handle.write(real_memory_content(name, dated=dated, marker=marker))


def git(cwd: str, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(
        ["git", "-C", cwd, "-c", "core.fsmonitor=false", *args],
        capture_output=True, text=True, check=True, env=env,
    )
    return proc.stdout


def make_git_repo(root: str, commit_memory: bool = True) -> None:
    git(root, "init")
    if commit_memory:
        write_memory(root)
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("# sample project\n")
        git(root, "add", "-A")
        git(root, *GIT_IDENTITY, "commit", "-m", "init")


def run_tool(root: str, *extra: str, extra_env: dict = None) -> tuple:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, os.path.join(SKILL_DIR, "context_health.py"),
         "--project", root, *extra],
        capture_output=True, text=True, env=env,
        timeout=30,  # a hung tool (regression) must fail the suite, never hang CI
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, payload, proc.stdout, proc.stderr


def axis(payload, axis_id: str):
    return payload["snapshot"]["axes"][axis_id]


def _read_journal(journal: str) -> bytes:
    """Read the journal bytes with an explicit close (no ResourceWarning)."""
    with open(journal, "rb") as handle:
        return handle.read()


def journal_of(root: str) -> str:
    out = git(root, "rev-parse", "--absolute-git-dir").strip()
    return os.path.join(out, ch.JOURNAL_SUBDIR, ch.JOURNAL_FILENAME)


GIT_AVAILABLE = shutil.which("git") is not None


def fresh_baseline(git_dir: str, root_real: str, head_sha=None, fingerprint=None,
                   generated_at=None, tool_version=None, standard_version=None) -> dict:
    return {
        "generated_at": generated_at or "2026-11-05T10:00:00+00:00",
        "tool_version": tool_version or ch.TOOL_VERSION,
        "standard_version": standard_version or ch.STANDARD_VERSION,
        "record_schema_version": ch.RECORD_SCHEMA_VERSION,
        "project_root": root_real,
        "branch": "main",
        "head_sha": head_sha,
        "memory_fingerprint": fingerprint,
        "git_status_signature": None,
        "file_hashes": {name: {"sha256": "0" * 64, "bytes": 10} for name in MEMORY_FILES},
        "result": "pass",
        "mission": None,
    }


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class FirstRunTest(unittest.TestCase):
    def test_first_run_without_journal_is_incomplete_exit0(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            self.assertEqual("pass", axis(payload, "initialization")["result"])
            self.assertEqual("not_applicable", axis(payload, "last_validation")["result"])
            self.assertEqual("unknown", axis(payload, "freshness")["result"])
            self.assertIn("no recorded baseline", axis(payload, "freshness")["reason"])

    def test_first_run_is_the_documented_normal_state(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            self.assertIn("documented as normal", axis(payload, "freshness")["reason"])


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class RecordThenFreshTest(unittest.TestCase):
    def test_record_then_validate_is_fresh_pass(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, payload, _, stderr = run_tool(root, "--record")
            self.assertEqual(0, code, msg=stderr)
            self.assertTrue(payload["recorded"])
            code2, payload2, _, _ = run_tool(root)
            self.assertEqual(0, code2)
            self.assertEqual("pass", payload2["summary"]["verdict"])
            self.assertEqual("pass", axis(payload2, "freshness")["result"])
            self.assertEqual("pass", axis(payload2, "last_validation")["result"])
            self.assertIn("covered", payload2["snapshot"]["coverage"])
            self.assertIn("not_covered", payload2["snapshot"]["coverage"])

    def test_record_is_mechanical_baseline_not_truth_certification(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "STATUS.md"), "w", encoding="utf-8") as handle:
                handle.write("# STATUS\n\nFALSE CLAIM RECORDED\n")  # false content
            code, payload, _, _ = run_tool(root, "--record")
            self.assertEqual(0, code)
            self.assertTrue(payload["recorded"])  # record freezes an OBSERVATION,
            # it never certifies the content truth — the honesty boundary holds.

    def test_record_twice_appends_history_without_loss(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record", "--mission", "one")
            run_tool(root, "--record", "--mission", "two")
            code, payload, _, _ = run_tool(root, "--history")
            self.assertEqual(0, code)
            history = payload["snapshot"]["history"]
            self.assertEqual("diagnostic", history["state"])
            ok_entries = [e for e in history["entries"] if e["status"] == "ok"]
            self.assertEqual(2, len(ok_entries))
            with open(journal_of(root), encoding="utf-8") as handle:
                lines = [l for l in handle.read().splitlines() if l.strip()]
            self.assertEqual(2, len(lines))  # append-only, nothing rewritten

    def test_record_refuses_broken_memory_state_journal_untouched(self):
        """P0-a: --record refuses to baseline a broken state (fail OR unknown
        initialization) and leaves the journal untouched."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")  # healthy baseline first
            journal = journal_of(root)
            before = _read_journal(journal)
            os.remove(os.path.join(root, "docs", "ai", "BUFFER.md"))  # fail
            code, payload, _, _ = run_tool(root, "--record")
            self.assertEqual(2, code)
            self.assertFalse(payload["recorded"])
            self.assertTrue(payload["refused"])
            self.assertIn("refusing to baseline a broken state", payload["reason"])
            self.assertEqual(before, _read_journal(journal))
            # unknown variant: file present but unreadable (symlink outside)
            os.remove(os.path.join(root, "docs", "ai", "STATUS.md"))
            external_dir = tempfile.mkdtemp()
            try:
                external = os.path.join(external_dir, "STATUS.md")
                with open(external, "w", encoding="utf-8") as handle:
                    handle.write("external\n")
                os.symlink(external, os.path.join(root, "docs", "ai", "STATUS.md"))
                code2, payload2, _, _ = run_tool(root, "--record")
                self.assertEqual(2, code2)
                self.assertTrue(payload2["refused"])
            finally:
                shutil.rmtree(external_dir, ignore_errors=True)
            self.assertEqual(before, _read_journal(journal))


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class StaleTest(unittest.TestCase):
    def test_memory_changed_after_record_is_stale_warning(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "STATUS.md"), "w", encoding="utf-8") as handle:
                handle.write("# STATUS\n\n### %s 10:00\n\n- v2 changed content\n" % DATE)
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)  # stale is a WARNING, never blocking
            self.assertEqual("warning", payload["summary"]["verdict"])
            fresh_axis = axis(payload, "freshness")
            self.assertEqual("warning", fresh_axis["result"])
            self.assertIn("fingerprint mismatch", fresh_axis["reason"])

    def test_deep_memory_diff_on_mismatch_is_bounded_diagnostic(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "STATUS.md"), "w", encoding="utf-8") as handle:
                handle.write("# STATUS\n\n### %s 10:00\n\n- v2 changed content\n" % DATE)
            code, payload, _, _ = run_tool(root, "--deep")
            diff = payload["snapshot"]["deep_diagnostics"]["memory_diff"]
            self.assertEqual("partial", diff["coverage"])
            self.assertEqual("changed", diff["per_file"]["STATUS.md"]["delta"])
            self.assertEqual("unchanged", diff["per_file"]["PLAN.md"]["delta"])
            self.assertIn("sha256", diff["per_file"]["STATUS.md"]["current"])

    def test_git_head_moved_is_conservative_stale_with_reason(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# sample project — touched\n")
            git(root, "add", "-A")
            git(root, *GIT_IDENTITY, "commit", "-m", "move head")
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            self.assertEqual("warning", payload["summary"]["verdict"])
            fresh_axis = axis(payload, "freshness")
            self.assertEqual("warning", fresh_axis["result"])
            self.assertIn("git reference moved", fresh_axis["reason"])
            self.assertIn("conservative indicator", fresh_axis["reason"])

    def test_deep_git_log_bounded_since_baseline(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            for i in range(3):
                with open(os.path.join(root, "README.md"), "a", encoding="utf-8") as handle:
                    handle.write("touch %d\n" % i)
                git(root, "add", "-A")
                git(root, *GIT_IDENTITY, "commit", "-m", "touch %d" % i)
            code, payload, _, _ = run_tool(root, "--deep")
            log_diag = payload["snapshot"]["deep_diagnostics"]["git_log_since_baseline"]
            self.assertEqual("partial", log_diag["coverage"])
            self.assertTrue(log_diag["computed"])
            self.assertEqual(3, log_diag["count"])

    def test_standard_version_change_is_stale_reason_standard_changed(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            with open(journal_of(root), encoding="utf-8") as handle:
                records = [json.loads(l) for l in handle.read().splitlines() if l.strip()]
            records[-1]["standard_version"] = "0.9.0"
            with open(journal_of(root), "w", encoding="utf-8") as handle:
                handle.write("\n".join(json.dumps(r) for r in records) + "\n")
            code, payload, _, _ = run_tool(root)
            fresh_axis = axis(payload, "freshness")
            self.assertEqual("warning", fresh_axis["result"])
            self.assertIn("standard-changed", fresh_axis["reason"])

    def test_tool_version_change_alone_never_invalidates_baseline(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            with open(journal_of(root), encoding="utf-8") as handle:
                records = [json.loads(l) for l in handle.read().splitlines() if l.strip()]
            records[-1]["tool_version"] = "0.0.1"
            with open(journal_of(root), "w", encoding="utf-8") as handle:
                handle.write("\n".join(json.dumps(r) for r in records) + "\n")
            code, payload, _, _ = run_tool(root)
            self.assertEqual("pass", axis(payload, "freshness")["result"])

    def test_max_age_optin_only(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            code, payload, _, _ = run_tool(root)  # absent → no age constraint
            self.assertEqual("pass", axis(payload, "freshness")["result"])
            code2, payload2, _, _ = run_tool(root, "--max-age-hours", "0")
            self.assertEqual(0, code2)
            fresh_axis = axis(payload2, "freshness")
            self.assertEqual("warning", fresh_axis["result"])
            self.assertIn("max-age-hours", fresh_axis["reason"])


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class JournalHardeningTest(unittest.TestCase):
    def _record(self, root: str) -> None:
        code, payload, _, stderr = run_tool(root, "--record")
        self.assertEqual(0, code, msg=stderr)

    def test_truncated_tail_is_unknown_no_fallback_to_earlier_baseline(self):
        """Unified rule (P0-c): a truncated tail corrupts the NEWEST evidence —
        freshness is unknown, NEVER substituted by the earlier baseline."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            self._record(root)
            with open(journal_of(root), "a", encoding="utf-8") as handle:
                handle.write('{"generated_at": "2026-11-0')  # interrupted append
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            fresh_axis = axis(payload, "freshness")
            self.assertEqual("unknown", fresh_axis["result"])
            self.assertIn("journal-tail-truncated", fresh_axis["reason"])
            self.assertIn("no fallback", fresh_axis["reason"])
            # the earlier record stays visible as a bounded DIAGNOSTIC only:
            code2, payload2, _, _ = run_tool(root, "--deep", "--history")
            hist = payload2["snapshot"]["history"]
            self.assertTrue(hist["tail_truncated"])
            self.assertEqual(1, len([e for e in hist["entries"] if e["status"] == "ok"]))

    def test_complete_but_invalid_line_is_corrupt_without_silent_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            self._record(root)
            bad = json.dumps({"generated_at": "2026-11-05T11:00:00+00:00"}) + "\n"
            with open(journal_of(root), "a", encoding="utf-8") as handle:
                handle.write(bad)  # complete line, fails strict schema
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            fresh_axis = axis(payload, "freshness")
            self.assertEqual("unknown", fresh_axis["result"])
            self.assertIn("journal-tail-corrupt", fresh_axis["reason"])
            self.assertIn("no fallback", fresh_axis["reason"])

    def test_unsupported_schema_version_is_corrupt_not_crash(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            self._record(root)
            incompatible = fresh_baseline(git_dir="", root_real=root)
            incompatible["record_schema_version"] = 99
            with open(journal_of(root), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(incompatible) + "\n")
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            fresh_axis = axis(payload, "freshness")
            self.assertEqual("unknown", fresh_axis["result"])
            self.assertIn("schema-incompatible", fresh_axis["reason"])

    def test_empty_journal_is_declared_absent(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            os.makedirs(os.path.dirname(journal_of(root)), exist_ok=True)
            open(journal_of(root), "w").close()
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            self.assertEqual("not_applicable", axis(payload, "last_validation")["result"])

    def test_symlinked_journal_outside_is_refused_fail_closed(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            make_git_repo(root)
            self._record(root)
            os.remove(journal_of(root))
            external = os.path.join(outside, "journal.jsonl")
            with open(external, "w", encoding="utf-8") as handle:
                handle.write('{"evil": "record"}\n')
            os.symlink(external, journal_of(root))
            code, payload, stdout, _ = run_tool(root, "--deep", "--history")
            self.assertEqual(0, code)
            self.assertEqual("unknown", axis(payload, "freshness")["result"])
            self.assertNotIn("evil", stdout)

    def test_foreign_record_owns_no_baseline_and_older_records_are_diagnostics(self):
        """Per-worktree filtering (defense in depth): a foreign record can
        never provide a baseline. As the LAST record it makes freshness
        unknown (no fallback to the valid own-root record before it —
        unified rule); older foreign lines are --history diagnostics only."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            self._record(root)
            with open(journal_of(root), encoding="utf-8") as handle:
                record = json.loads(handle.read().splitlines()[0])
            # (a) valid own-root record is last → comparison allowed
            code, payload, _, _ = run_tool(root)
            self.assertEqual("pass", payload["summary"]["verdict"])
            # (b) foreign record appended AFTER → it is now the last record
            record["project_root"] = "/somewhere/else"
            with open(journal_of(root), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            code2, payload2, _, _ = run_tool(root)
            self.assertEqual(0, code2)
            self.assertEqual("incomplete", payload2["summary"]["verdict"])
            self.assertEqual("unknown", axis(payload2, "freshness")["result"])
            self.assertEqual("not_applicable", axis(payload2, "last_validation")["result"])


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class WorktreeIsolationTest(unittest.TestCase):
    def test_two_worktrees_never_share_baselines(self):
        with tempfile.TemporaryDirectory() as main_root:
            make_git_repo(main_root)
            wt_a = tempfile.mkdtemp()
            wt_b = tempfile.mkdtemp()
            try:
                git(main_root, "worktree", "add", wt_a, "HEAD")
                git(main_root, "worktree", "add", wt_b, "HEAD")
                write_memory(wt_a)
                write_memory(wt_b)
                # baseline recorded from worktree A only
                code, _, _, stderr = run_tool(wt_a, "--record")
                self.assertEqual(0, code, msg=stderr)
                self.assertNotEqual(journal_of(wt_a), journal_of(wt_b))
                # A is fresh; B never sees A's baseline
                code_a, payload_a, _, _ = run_tool(wt_a)
                self.assertEqual("pass", payload_a["summary"]["verdict"])
                code_b, payload_b, _, _ = run_tool(wt_b)
                self.assertEqual(0, code_b)
                self.assertEqual("incomplete", payload_b["summary"]["verdict"])
                self.assertIn("no recorded baseline",
                              axis(payload_b, "freshness")["reason"])
            finally:
                subprocess.run(["git", "-C", main_root, "worktree", "prune"],
                               capture_output=True)


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class StructureAndBoundaryTest(unittest.TestCase):
    def test_missing_memory_file_fails(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            os.remove(os.path.join(root, "docs", "ai", "BUFFER.md"))
            code, payload, _, _ = run_tool(root)
            self.assertEqual(1, code)
            self.assertEqual("fail", payload["summary"]["verdict"])
            self.assertEqual("fail", axis(payload, "initialization")["result"])
            self.assertIn("BUFFER.md", json.dumps(axis(payload, "initialization")))

    def test_scaffold_identical_file_fails(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "CHANGELOG.md"), "w", encoding="utf-8") as handle:
                handle.write("# CHANGELOG\n\n## YYYY-MM-DD\n\n- \n")
            code, payload, _, _ = run_tool(root)
            self.assertEqual(1, code)

    def test_docs_ai_absent_is_no_docs_and_record_refuses(self):
        with tempfile.TemporaryDirectory() as root:
            git(root, "init")
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            self.assertEqual("no_docs", payload["summary"]["verdict"])
            code2, payload2, _, _ = run_tool(root, "--record")
            self.assertEqual(2, code2)
            self.assertFalse(payload2["recorded"])

    def test_non_git_project_declared_channel(self):
        with tempfile.TemporaryDirectory() as root:
            write_memory(root)
            code, payload, _, _ = run_tool(root)
            self.assertEqual(0, code)
            self.assertEqual("incomplete", payload["summary"]["verdict"])
            self.assertEqual("not_applicable", axis(payload, "last_validation")["result"])
            self.assertEqual("unknown", axis(payload, "freshness")["result"])
            self.assertIn("no journal channel", json.dumps(payload))

    def test_strict_turns_stale_warning_into_exit1_never_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            # move the git reference (committed work) → conservative stale
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# sample project — moved\n")
            git(root, "add", "-A")
            git(root, *GIT_IDENTITY, "commit", "-m", "move head")
            code_normal, _, _, _ = run_tool(root)
            code_strict, _, _, _ = run_tool(root, "--strict")
            self.assertEqual(0, code_normal)  # stale is a warning, never blocking
            self.assertEqual(1, code_strict)  # --strict promotes warnings to exit 1

    def test_strict_never_converts_incomplete_to_exit1(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, _, _, _ = run_tool(root, "--strict")  # first run = incomplete
            self.assertEqual(0, code)


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class CertificateShapeTest(unittest.TestCase):
    def test_idempotence_same_state_same_report(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            code1, p1, _, _ = run_tool(root)
            code2, p2, _, _ = run_tool(root)
            self.assertEqual(code1, code2)
            self.assertEqual(p1["snapshot"]["memory_fingerprint"], p2["snapshot"]["memory_fingerprint"])
            self.assertEqual(p1["snapshot"]["git_status_signature"], p2["snapshot"]["git_status_signature"])
            self.assertEqual(p1["snapshot"]["axes"], p2["snapshot"]["axes"])
            self.assertNotEqual(p1["snapshot"]["generated_at"], p2["snapshot"]["generated_at"])

    def test_json_guaranteed_on_fail(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            os.remove(os.path.join(root, "docs", "ai", "INDEX.md"))
            code, payload, stdout, _ = run_tool(root)
            self.assertEqual(1, code)
            self.assertEqual("fail", payload["summary"]["verdict"])
            self.assertIn("report_schema_version", payload)

    def test_non_ascii_mission_never_tracebacks(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, payload, stdout, stderr = run_tool(
                root, "--record", "--mission", "chantier étoile ✔",
                extra_env={"LANG": "C", "LC_ALL": "C"})
            self.assertEqual(0, code)
            self.assertNotIn("Traceback", stderr)
            self.assertEqual("chantier étoile ✔", payload["record"]["mission"])

    def test_hostile_git_dir_env_is_purged(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            dummy = tempfile.mkdtemp()
            subprocess.run(["git", "init", dummy], capture_output=True, check=True)
            try:
                code, payload, _, _ = run_tool(
                    root, extra_env={"GIT_DIR": os.path.join(dummy, ".git")})
                self.assertEqual(0, code)
                self.assertEqual("pass", payload["summary"]["verdict"])
            finally:
                shutil.rmtree(dummy, ignore_errors=True)


class RecordFailClosedTest(unittest.TestCase):
    @unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
    @unittest.skipIf(getattr(os, "getuid", lambda: -1)() == 0,
                     "permission bits are ineffective when running as root (CI containers)")
    def test_unwritable_journal_dir_is_exit2_never_partial(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code, _, stdout, stderr = run_tool(root, "--record")
            self.assertEqual(0, code)
            journal = journal_of(root)
            before = _read_journal(journal)
            os.chmod(journal, 0o400)  # read-only FILE: opening for append fails
            try:
                code2, payload2, stdout2, stderr2 = run_tool(root, "--record")
                # fail-closed: exit 2 + stderr report + NO partial record
                self.assertEqual(2, code2)
                self.assertIn("environmental failure", stderr2)
                self.assertEqual("", stdout2.strip())
            finally:
                os.chmod(journal, 0o600)
            after = _read_journal(journal)
            self.assertEqual(before, after)  # never a partial record

    def test_nonexistent_project_exit2(self):
        code, payload, stdout, _ = run_tool(os.path.join("/", "nonexistent", "xyz"))
        self.assertEqual(2, code)
        self.assertIsNone(payload)


@unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
class NoWriteTest(unittest.TestCase):
    def test_validate_mode_never_writes_anything(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            run_tool(root, "--record")
            journal = journal_of(root)
            journal_before = hashlib.sha256(_read_journal(journal)).hexdigest()
            docs_before = self._tree_hash(os.path.join(root, "docs", "ai"))
            index_before = self._index_hash(root)
            status_before = git(root, "status", "--porcelain")
            code, payload, _, stderr = run_tool(root, "--deep", "--history")
            self.assertEqual(0, code, msg=stderr)
            self.assertEqual(journal_before, hashlib.sha256(_read_journal(journal)).hexdigest())
            self.assertEqual(docs_before, self._tree_hash(os.path.join(root, "docs", "ai")))
            self.assertEqual(index_before, self._index_hash(root))
            self.assertEqual(status_before, git(root, "status", "--porcelain"))

    @staticmethod
    def _tree_hash(base: str) -> str:
        digest = hashlib.sha256()
        for current, dirs, files in os.walk(base):
            dirs.sort()
            for name in sorted(files):
                with open(os.path.join(current, name), "rb") as handle:
                    digest.update(handle.read())
        return digest.hexdigest()

    @staticmethod
    def _index_hash(root: str) -> str:
        index = git(root, "rev-parse", "--git-path", "index").strip()
        if not os.path.isabs(index):
            index = os.path.join(root, index)
        if not os.path.exists(index):
            return "absent"
        with open(index, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()


class WhitelistTest(unittest.TestCase):
    def test_mutating_subcommand_refused(self):
        with self.assertRaises(ValueError):
            ch.git_run("/tmp", "commit")
        with self.assertRaises(ValueError):
            ch.git_run("/tmp", "add")
        with self.assertRaises(ValueError):
            ch.git_run("/tmp", "fetch", "--all")

    def test_log_must_use_bounded_form(self):
        with self.assertRaises(ValueError):
            ch.git_run("/tmp", "log", "--oneline")
        with self.assertRaises(ValueError):
            ch.git_run("/tmp", "log", "--oneline", "-n", "999999")
        with self.assertRaises(ValueError):
            ch.git_run("/tmp", "log", "--oneline", "-n", "5", "--", "path")

    def test_parse_record_strictness(self):
        record = fresh_baseline(git_dir="", root_real="/x")
        parsed, flag = ch.parse_record(json.dumps(record), "/x")
        self.assertIsNone(flag)
        self.assertEqual("/x", parsed["project_root"])
        bad = dict(record)
        del bad["generated_at"]
        parsed2, flag2 = ch.parse_record(json.dumps(bad), "/x")
        self.assertIsNone(parsed2)
        self.assertIn("generated_at", flag2)
        parsed3, flag3 = ch.parse_record(json.dumps(record), "/y")
        self.assertEqual("foreign", parsed3)


class ReferencedPathsTest(unittest.TestCase):
    @unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
    def test_missing_referenced_path_is_l2_warning_never_l1(self):
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            docs = os.path.join(root, "docs", "ai")
            with open(os.path.join(docs, "INDEX.md"), "w", encoding="utf-8") as handle:
                handle.write("# INDEX\n\n## Key files\n\n"
                             "- skills/session-finalize/finalize.py\n"
                             "- standards/memory-checklist.md\n"
                             "- docs/ai/ghost-reference.md\n")
            os.makedirs(os.path.join(root, "skills", "session-finalize"), exist_ok=True)
            with open(os.path.join(root, "skills", "session-finalize", "finalize.py"), "w",
                      encoding="utf-8") as handle:
                handle.write("# existing\n")
            code, payload, _, _ = run_tool(root, "--record")
            self.assertEqual(0, code)
            code_l1, payload_l1, _, _ = run_tool(root)
            self.assertEqual("pass", payload_l1["summary"]["verdict"])
            self.assertNotIn("referenced_paths", json.dumps(payload_l1["snapshot"].get(
                "deep_diagnostics", {})))
            code_l2, payload_l2, _, _ = run_tool(root, "--deep")
            diag = payload_l2["snapshot"]["deep_diagnostics"]["referenced_paths"]
            self.assertEqual("partial", diag["coverage"])
            self.assertEqual(1, diag["missing"])
            self.assertEqual("warning", payload_l2["summary"]["verdict"])
            # Convergence pin: a deep axis that counts toward the verdict MUST
            # be visible in snapshot.axes (never a hidden backing evidence).
            self.assertEqual("warning",
                             payload_l2["snapshot"]["axes"]["referenced_paths"]["result"])

    def test_extraction_bounded_at_max_tokens(self):
        content = "# INDEX\n\n" + "\n".join("path/to/file%02d.md" % i for i in range(40))
        root_real = "/nonexistent-root"
        states = {"INDEX.md": "ok", "WARNINGS.md": "absent"}
        contents = {"INDEX.md": content.encode(), "WARNINGS.md": None}
        result = ch.deep_referenced_paths(contents, states, root_real)
        self.assertEqual(ch.REFERENCED_PATHS_MAX, result["observed"])
        self.assertEqual("partial", result["coverage"])


class CrossToolPinTest(unittest.TestCase):
    def test_memory_fingerprint_matches_session_finalize_byte_for_byte(self):
        try:
            import finalize  # skills/session-finalize
        except ImportError:
            self.skipTest("session-finalize not available")
        contents = {name: ("x %s" % name).encode() for name in MEMORY_FILES}
        contents["INDEX.md"] = None  # exercise ABSENT branch
        self.assertEqual(finalize.compute_memory_fingerprint(contents),
                         ch.compute_memory_fingerprint(contents))

    def test_git_status_signature_matches_session_finalize(self):
        try:
            import finalize  # skills/session-finalize
        except ImportError:
            self.skipTest("session-finalize not available")
        self.assertEqual(finalize.compute_git_status_signature("abc123", " M a\n"),
                         ch.compute_git_status_signature("abc123", " M a\n"))

    def test_skeleton_hashes_match_session_finalize(self):
        """Pin promised by context_health.py (SKELETON_SHA256 comment): the
        copy that gates --record must stay byte-identical to finalize's."""
        try:
            import finalize  # skills/session-finalize
        except ImportError:
            self.skipTest("session-finalize not available")
        self.assertEqual(finalize.SKELETON_SHA256, ch.SKELETON_SHA256)

    @unittest.skipUnless(GIT_AVAILABLE, "git binary not found")
    def test_first_commit_after_zero_commit_baseline_is_stale_warning(self):
        """P1 pin: a baseline recorded on a 0-commit repo (head_sha=None) then
        a first commit is a MOVED reference — stale warning, never false-fresh."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root, commit_memory=False)  # zero-commit, empty repo
            write_memory(root)
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# sample project\n")
            code, _, _, _ = run_tool(root, "--record")  # baseline head_sha=None
            self.assertEqual(0, code)
            git(root, "add", "-A")
            git(root, *GIT_IDENTITY, "commit", "-m", "first commit")
            code2, payload2, _, _ = run_tool(root)
            self.assertEqual("warning", payload2["summary"]["verdict"])
            fresh = axis(payload2, "freshness")
            self.assertEqual("warning", fresh["result"])
            self.assertIn("git reference moved", fresh["reason"])

    def test_naive_baseline_timestamp_is_corrupt_never_crash_with_max_age(self):
        """P1 pin: a schema-valid but timezone-naive baseline must fail-closed
        at the schema gate (unknown) — never a TypeError exit 2 crash."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code_r, _, _, _ = run_tool(root, "--record")
            self.assertEqual(0, code_r)
            naive = fresh_baseline(git_dir="", root_real=root)
            naive["generated_at"] = "2026-11-05T10:00:00"  # no UTC offset
            with open(journal_of(root), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(naive) + "\n")
            code, payload, _, stderr = run_tool(root, "--max-age-hours", "24")
            self.assertEqual(0, code)  # verdict rendered, never an environmental failure
            self.assertEqual("unknown", axis(payload, "freshness")["result"])
            self.assertIn("timezone-aware", axis(payload, "freshness")["reason"])

    def test_future_baseline_beyond_clock_skew_is_unknown(self):
        """A baseline dated in the future beyond the 24 h clock-skew tolerance
        never silently bypasses --max-age-hours (negative age guard)."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            code_r, _, _, _ = run_tool(root, "--record")
            self.assertEqual(0, code_r)
            with open(journal_of(root), encoding="utf-8") as handle:
                real_record = json.loads(handle.read().splitlines()[0])
            # Reuse the real fingerprint: the injected record must reach the age
            # guard (matching content + git reference) with only its date forged.
            future = fresh_baseline(git_dir="", root_real=os.path.realpath(root),
                                    head_sha=real_record["head_sha"],
                                    fingerprint=real_record["memory_fingerprint"],
                                    generated_at="2030-01-01T10:00:00+00:00")
            with open(journal_of(root), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(future) + "\n")
            code, payload, _, _ = run_tool(root, "--max-age-hours", "24")
            self.assertEqual(0, code)
            fresh = axis(payload, "freshness")
            self.assertEqual("unknown", fresh["result"])
            self.assertIn("future", fresh["reason"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "mkfifo not available (non-POSIX)")
    def test_fifo_journal_path_is_refused_never_hangs(self):
        """P1 pin: a FIFO at the journal path (INSIDE the git-dir, passing the
        confinement check) must be refused by S_ISREG on every journal access
        path — --record exits 2, --deep --history reports refused, never hang."""
        with tempfile.TemporaryDirectory() as root:
            make_git_repo(root)
            os.makedirs(os.path.dirname(journal_of(root)), exist_ok=True)
            os.mkfifo(journal_of(root))
            code, payload, stdout, stderr = run_tool(root, "--record")
            self.assertEqual(2, code)
            self.assertIn("environmental failure", stderr)
            self.assertEqual("", stdout.strip())
            code2, payload2, _, _ = run_tool(root, "--deep", "--history")
            self.assertEqual(0, code2)
            hist = payload2["snapshot"]["history"]
            self.assertEqual("refused", hist["state"])
            self.assertIn("not a regular file", hist["reason"])


if __name__ == "__main__":
    unittest.main()
