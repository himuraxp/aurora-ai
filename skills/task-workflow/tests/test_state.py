#!/usr/bin/env python3
"""Tests for the task-workflow state contract (fixtures only — no network,
no GitLab/Trello access, no MR creation). Python 3.9+, stdlib only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tw_state  # noqa: E402

TS = "2026-10-13T10:00:00Z"


def valid_state(**overrides):
    state = {
        "schemaVersion": 1,
        "workflowId": "tw-podcast-player--1a2b3c4d",
        "taskUrls": [{"source": "trello", "url": "https://trello.com/c/abc123"}],
        "repository": "/Users/x/dev/podcast-player",
        "baseBranch": "develop",
        "baseCommit": "88c12ba",
        "featureBranch": "feat/podcast--dynamic-form-management",
        "worktreePath": "/Users/x/dev/podcast-player.worktrees/feat-podcast--dynamic-form-management",
        "currentPhase": 1,
        "phaseStatuses": {},
        "createdAt": TS,
        "updatedAt": TS,
        "decisions": [],
        "testResults": [],
        "qaResults": [],
        "reviewResults": [],
        "mergeRequestUrl": None,
        "blockers": [],
    }
    state.update(overrides)
    return state


def passed(state, phase, signature="sig-1"):
    state["phaseStatuses"][str(phase)] = {"status": "PASSED", "at": TS, "codeSignature": signature}
    return state


class TestSchemaValidation(unittest.TestCase):
    def test_valid_fixture_passes(self):
        self.assertEqual(tw_state.validate_state(valid_state()), [])

    def test_missing_required_key(self):
        state = valid_state()
        del state["worktreePath"]
        problems = tw_state.validate_state(state)
        self.assertTrue(any("worktreePath" in p for p in problems))

    def test_bad_workflow_id(self):
        problems = tw_state.validate_state(valid_state(workflowId="not-an-id"))
        self.assertTrue(any("workflowId" in p for p in problems))

    def test_bad_task_urls(self):
        problems = tw_state.validate_state(valid_state(taskUrls=[{"source": "jira", "url": "https://x"}]))
        self.assertTrue(any("taskUrls" in p for p in problems))
        problems = tw_state.validate_state(valid_state(taskUrls=[]))
        self.assertTrue(any("taskUrls" in p for p in problems))

    def test_base_and_feature_must_differ(self):
        problems = tw_state.validate_state(valid_state(featureBranch="develop"))
        self.assertTrue(any("must differ" in p for p in problems))

    def test_undecided_phase_before_current(self):
        state = valid_state(currentPhase=4)
        state["phaseStatuses"] = {"3": {"status": "RUNNING", "at": TS}}
        problems = tw_state.validate_state(state)
        self.assertTrue(any("phase 3" in p for p in problems))

    def test_bad_merge_request_url(self):
        problems = tw_state.validate_state(valid_state(mergeRequestUrl="not-a-url"))
        self.assertTrue(any("mergeRequestUrl" in p for p in problems))

    def test_bad_iso_dates(self):
        problems = tw_state.validate_state(valid_state(createdAt="13/10/2026"))
        self.assertTrue(any("createdAt" in p for p in problems))


class TestWorkflowId(unittest.TestCase):
    def test_deterministic_and_distinct(self):
        first = tw_state.new_workflow_id("https://trello.com/c/abc", "/dev/podcast-player")
        second = tw_state.new_workflow_id("https://trello.com/c/abc", "/dev/podcast-player")
        other = tw_state.new_workflow_id("https://trello.com/c/xyz", "/dev/podcast-player")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("tw-podcast-player--"))

    def test_gitlab_issue_distinct_from_trello(self):
        trello = tw_state.new_workflow_id("https://trello.com/c/abc", "/dev/r")
        gitlab = tw_state.new_workflow_id("https://gitlab.example.com/g/r/-/issues/1", "/dev/r")
        self.assertNotEqual(trello, gitlab)


class TestTransitions(unittest.TestCase):
    def test_happy_path(self):
        state = valid_state()
        tw_state.mark_phase(state, 1, "RUNNING", at=TS)
        tw_state.mark_phase(state, 1, "PASSED", code_signature="s1", at=TS)
        self.assertEqual(state["phaseStatuses"]["1"]["status"], "PASSED")

    def test_waiting_approval_cycle(self):
        state = valid_state()
        tw_state.mark_phase(state, 3, "RUNNING", at=TS)
        tw_state.mark_phase(state, 3, "WAITING_APPROVAL", at=TS)
        tw_state.mark_phase(state, 3, "RUNNING", at=TS)
        self.assertEqual(state["phaseStatuses"]["3"]["status"], "RUNNING")

    def test_blocked_reopens(self):
        state = valid_state()
        tw_state.mark_phase(state, 5, "RUNNING", at=TS)
        tw_state.mark_phase(state, 5, "BLOCKED", at=TS)
        tw_state.mark_phase(state, 5, "RUNNING", at=TS)
        self.assertEqual(state["phaseStatuses"]["5"]["status"], "RUNNING")

    def test_skipped_can_reopen(self):
        state = valid_state()
        tw_state.mark_phase(state, 5, "SKIPPED", at=TS)
        tw_state.mark_phase(state, 5, "RUNNING", at=TS)
        self.assertEqual(state["phaseStatuses"]["5"]["status"], "RUNNING")

    def test_illegal_direct_pass(self):
        state = valid_state()
        with self.assertRaises(ValueError):
            tw_state.mark_phase(state, 1, "PASSED", at=TS)

    def test_illegal_from_passed(self):
        state = passed(valid_state(), 1)
        with self.assertRaises(ValueError):
            tw_state.mark_phase(state, 1, "RUNNING", at=TS)

    def test_unknown_status(self):
        state = valid_state()
        with self.assertRaises(ValueError):
            tw_state.mark_phase(state, 1, "DONE", at=TS)

    def test_invalidate_passed_only(self):
        state = passed(valid_state(), 2)
        tw_state.invalidate_phase(state, 2, at=TS)
        self.assertEqual(state["phaseStatuses"]["2"]["status"], "PENDING")
        with self.assertRaises(ValueError):
            tw_state.invalidate_phase(state, 2, at=TS)  # not PASSED anymore


class TestStale(unittest.TestCase):
    def test_matching_signature_not_stale(self):
        state = passed(valid_state(), 3, signature="sig-1")
        self.assertEqual(tw_state.compute_stale(state, "sig-1"), [])

    def test_changed_signature_is_stale(self):
        state = passed(valid_state(), 3, signature="sig-1")
        self.assertEqual(tw_state.compute_stale(state, "sig-2"), [3])

    def test_missing_signature_is_stale(self):
        state = passed(valid_state(), 4, signature=None)
        state["phaseStatuses"]["4"].pop("codeSignature")
        self.assertEqual(tw_state.compute_stale(state, "sig-2"), [4])


class TestResumePlan(unittest.TestCase):
    def test_fresh_state_runs_from_phase_1(self):
        plan = tw_state.resume_plan(valid_state(), "sig-1")
        self.assertEqual(plan["resumeAt"], 1)
        self.assertIn(1, plan["rerun"])
        self.assertTrue(plan["reuseExisting"])

    def test_mid_workflow_resume_after_passed(self):
        state = valid_state(currentPhase=4)
        for phase in (1, 2, 3):
            passed(state, phase, signature="sig-1")
        state["phaseStatuses"]["4"] = {"status": "RUNNING", "at": TS}
        plan = tw_state.resume_plan(state, "sig-1")
        self.assertEqual(plan["resumeAt"], 4)
        self.assertEqual(sorted(plan["skip"]), [1, 2, 3])
        self.assertEqual(plan["invalidate"], [])

    def test_stale_passed_is_invalidated(self):
        state = valid_state(currentPhase=4)
        for phase in (1, 2, 3):
            passed(state, phase, signature="sig-1")
        plan = tw_state.resume_plan(state, "sig-2")  # code changed after PASSED
        self.assertEqual(plan["invalidate"], [1, 2, 3])
        self.assertEqual(plan["resumeAt"], 1)

    def test_missing_worktree_reruns_phase_2(self):
        state = passed(valid_state(), 1, signature="sig-1")
        plan = tw_state.resume_plan(state, "sig-1", worktree_exists=False)
        self.assertIn(2, plan["rerun"])
        # Full shape (F-04): rerun sorted ascending, resumeAt = min(rerun).
        self.assertEqual(plan["rerun"], sorted(plan["rerun"]))
        self.assertEqual(plan["resumeAt"], plan["rerun"][0])
        self.assertEqual(plan["resumeAt"], 1)  # no worktree → everything re-runs from the top

    def test_existing_mr_completes_at_phase_9(self):
        state = passed(valid_state(), 1, signature="sig-1")
        state["mergeRequestUrl"] = "https://gitlab.example.com/g/r/-/merge_requests/9"
        plan = tw_state.resume_plan(state, "sig-1")
        self.assertEqual(plan["resumeAt"], 9)
        self.assertEqual(sorted(plan["skip"]), [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(plan["rerun"], [])
        self.assertEqual(plan["staleAfterMergeRequest"], [])

    def test_existing_mr_with_stale_code_reports_it(self):
        # F-05: MR exists AND code changed after → never re-run, but the plan
        # must surface the staleness for the final report.
        state = passed(valid_state(), 1, signature="sig-1")
        state["mergeRequestUrl"] = "https://gitlab.example.com/g/r/-/merge_requests/9"
        plan = tw_state.resume_plan(state, "sig-2")
        self.assertEqual(plan["rerun"], [])
        self.assertEqual(plan["staleAfterMergeRequest"], [1])

    def test_blocked_phase_is_rerun_for_reevaluation(self):
        # F-10: BLOCKED re-run = re-evaluate the blocker, never bypass it.
        state = valid_state(currentPhase=5)
        for phase in (1, 2, 3):
            passed(state, phase, signature="sig-1")
        state["phaseStatuses"]["4"] = {"status": "BLOCKED", "at": TS}
        plan = tw_state.resume_plan(state, "sig-1")
        self.assertEqual(plan["rerun"], [4, 5, 6, 7, 8, 9])  # 4 re-evaluated, 5-9 still to run
        self.assertEqual(plan["resumeAt"], 4)
        self.assertEqual(sorted(plan["skip"]), [1, 2, 3])


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tw-podcast-player--1a2b3c4d.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        return subprocess.run(
            [sys.executable, script, *args], capture_output=True, text=True, check=False,
            env={**os.environ, "TW_STATE_STATE_DIR": self.tmp.name})

    def test_validate_cli_ok(self):
        result = self._run("validate", self.path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("state valid", result.stdout)

    def test_validate_cli_rejects_corruption(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"schemaVersion": 99}, handle)
        result = self._run("validate", self.path)
        self.assertEqual(result.returncode, 1)

    def test_mark_illegal_transition_fails(self):
        result = self._run("mark", self.path, "1", "PASSED")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ILLEGAL", result.stdout)

    def test_resume_cli_emits_plan(self):
        result = self._run("resume", self.path, "--signature", "sig-1")
        self.assertEqual(result.returncode, 0)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["resumeAt"], 1)

    def test_id_cli(self):
        result = self._run("id", "https://trello.com/c/abc", "/dev/repo")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.strip().startswith("tw-repo--"))


    def test_code_signature_type_checked(self):
        state = passed(valid_state(), 2)
        state["phaseStatuses"]["2"]["codeSignature"] = 123
        problems = tw_state.validate_state(state)
        self.assertTrue(any("codeSignature" in p for p in problems))

    def test_current_phase_bool_refused(self):
        # F-11: JSON true == 1 — a bool must never count as a phase number.
        problems = tw_state.validate_state(valid_state(currentPhase=True))
        self.assertTrue(any("currentPhase" in p for p in problems))

    def test_corrupt_entry_raises_clean_error(self):
        # F-12: corrupted phaseStatuses entry → ValueError, not AttributeError.
        state = valid_state()
        state["phaseStatuses"]["2"] = "garbage"
        with self.assertRaises(ValueError):
            tw_state.mark_phase(state, 2, "RUNNING", at=TS)

    def test_file_identity_enforced_in_canonical_dir(self):
        # F-09: in the canonical dir, the file name must be <workflowId>.json.
        state = valid_state()
        os.environ["TW_STATE_STATE_DIR"] = "/x/task-workflows"
        try:
            good = tw_state.validate_state(state, path="/x/task-workflows/tw-podcast-player--1a2b3c4d.json")
            self.assertEqual(good, [])
            bad = tw_state.validate_state(state, path="/x/task-workflows/other-name.json")
            self.assertTrue(any("file name" in p for p in bad))
        finally:
            os.environ.pop("TW_STATE_STATE_DIR", None)
        # Outside the canonical dir, no name constraint — and no substring
        # false positive: a path merely CONTAINING "task-workflows" is not
        # canonical (exact-dir equality, same predicate as the write guard).
        elsewhere = tw_state.validate_state(state, path="/tmp/anything.json")
        self.assertEqual(elsewhere, [])
        substring = tw_state.validate_state(state, path="/pilots/task-workflows-v2/my-state.json")
        self.assertEqual([p for p in substring if "file name" in p], [])

    def test_design_contract_additive_optional(self):
        # design-qa integration: additive optional field, never required —
        # v1 states recorded BEFORE this field existed must stay valid.
        legacy = valid_state()
        self.assertNotIn("designContract", legacy)
        self.assertEqual(tw_state.validate_state(legacy), [])
        with_contract = valid_state(designContract="/x/task-workflows/tw-podcast-player--1a2b3c4d.design.json")
        self.assertEqual(tw_state.validate_state(with_contract), [])
        with_null = valid_state(designContract=None)
        self.assertEqual(tw_state.validate_state(with_null), [])
        bad = valid_state(designContract="")
        self.assertTrue(any("designContract" in p for p in tw_state.validate_state(bad)))


class TestCodeSignatureComputation(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        for args in (["git", "init", "-q", self.repo],
                     ["git", "-C", self.repo, "config", "user.email", "t@t.local"],
                     ["git", "-C", self.repo, "config", "user.name", "t"]):
            subprocess.run(args, check=True, capture_output=True)
        with open(os.path.join(self.repo, "file.txt"), "w", encoding="utf-8") as handle:
            handle.write("content\n")
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "init"], check=True, capture_output=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_clean_tree_signature_stable(self):
        first = tw_state.compute_code_signature(self.repo)
        second = tw_state.compute_code_signature(self.repo)
        self.assertEqual(first, second)

    def test_dirty_tree_changes_signature(self):
        # A committed change AND an uncommitted change must both invalidate.
        clean = tw_state.compute_code_signature(self.repo)
        with open(os.path.join(self.repo, "file.txt"), "a", encoding="utf-8") as handle:
            handle.write("uncommitted\n")
        dirty = tw_state.compute_code_signature(self.repo)
        self.assertNotEqual(clean, dirty)

    def test_not_a_git_repo_raises_clean_error(self):
        with self.assertRaises(ValueError):
            tw_state.compute_code_signature(tempfile.mkdtemp())


class TestCliStatePersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tw-podcast-player--1a2b3c4d.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        return subprocess.run(
            [sys.executable, script, *args], capture_output=True, text=True, check=False,
            env={**os.environ, "TW_STATE_STATE_DIR": self.tmp.name})

    def _content(self):
        with open(self.path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_mark_with_signature_persists_and_enables_stale(self):
        self.assertEqual(self._run("mark", self.path, "1", "RUNNING").returncode, 0)
        result = self._run("mark", self.path, "1", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 0)
        state = json.loads(self._content())
        self.assertEqual(state["phaseStatuses"]["1"]["codeSignature"], "a" * 40)
        self.assertEqual(tw_state.compute_stale(state, "a" * 40), [])
        self.assertEqual(tw_state.compute_stale(state, "b" * 40), [1])

    def test_mark_out_of_order_refused_and_file_unchanged(self):
        # F-06: never persist a state the contract rejects.
        before = self._content()
        result = self._run("mark", self.path, "7", "RUNNING")
        self.assertEqual(result.returncode, 1)
        self.assertIn("INVALID", result.stdout)
        self.assertIn("state NOT saved", result.stdout)
        self.assertEqual(self._content(), before)

    def test_invalidate_cli_roundtrip(self):
        self._run("mark", self.path, "1", "RUNNING")
        self._run("mark", self.path, "1", "PASSED", "--signature", "a" * 40)
        self.assertEqual(self._run("invalidate", self.path, "1").returncode, 0)
        state = json.loads(self._content())
        self.assertEqual(state["phaseStatuses"]["1"]["status"], "PENDING")
        self.assertEqual(self._run("invalidate", self.path, "1").returncode, 1)

    def test_signature_cli(self):
        result = self._run("signature", self.tmp.name)
        self.assertEqual(result.returncode, 1)  # not a git repo → clean error
        self.assertIn("ERROR", result.stdout)


class TestCanonicalTaskKey(unittest.TestCase):
    def test_trello_url_forms_share_one_key(self):
        # T-01: 3 URL forms of the same card must normalize to one identity.
        forms = [
            "https://trello.com/c/M5JkpDlj",
            "https://trello.com/c/M5JkpDlj/ordre-de-la-selection",
            "https://trello.com/c/M5JkpDlj/518-ordre-de-la-selection",
        ]
        keys = {tw_state.canonical_task_key(url) for url in forms}
        self.assertEqual(keys, {"trello:M5JkpDlj"})

    def test_gitlab_issue_and_work_item_share_one_key(self):
        self.assertEqual(tw_state.canonical_task_key(
            "https://gitlab.infomaniak.ch/infomaniak/media/site-manager/-/issues/13"),
            tw_state.canonical_task_key(
            "https://gitlab.infomaniak.ch/infomaniak/media/site-manager/-/work_items/13"))

    def test_unknown_source_falls_back_to_raw_url(self):
        url = "https://linear.app/proj/issue/ABC-1"
        self.assertEqual(tw_state.canonical_task_key(url), url)

    def test_normalized_id_same_for_all_url_forms(self):
        repo = "/dev/site-manager"
        ids = {tw_state.new_workflow_id(url, repo) for url in (
            "https://trello.com/c/M5JkpDlj",
            "https://trello.com/c/M5JkpDlj/518-ordre-de-la-selection")}
        self.assertEqual(len(ids), 1)
        self.assertTrue(list(ids)[0].startswith("tw-site-manager--"))


class TestResolveState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _state(self, workflow_id, url):
        state = valid_state(workflowId=workflow_id,
                            taskUrls=[{"source": "trello", "url": url}])
        path = os.path.join(self.tmp.name, f"{workflow_id}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        return path

    def test_exact_hit_by_normalized_id(self):
        path = self._state("tw-site-manager--98e87142", "https://trello.com/c/M5JkpDlj")
        self.assertEqual(tw_state.resolve_state(
            "https://trello.com/c/M5JkpDlj/518-ordre-de-la-selection",
            "/dev/site-manager", directory=self.tmp.name), path)

    def test_legacy_lookup_through_taskurls(self):
        # Legacy id (hash of the raw URL) stays resolvable from any URL form.
        path = self._state("tw-site-manager--98e87142", "https://trello.com/c/M5JkpDlj")
        self.assertEqual(tw_state.resolve_state(
            "https://trello.com/c/M5JkpDlj/ordre-de-la-selection",
            "/dev/site-manager", directory=self.tmp.name), path)

    def test_ambiguous_matches_raise(self):
        self._state("tw-site-manager--aaaaaaaa", "https://trello.com/c/M5JkpDlj")
        self._state("tw-site-manager--bbbbbbbb", "https://trello.com/c/M5JkpDlj/518-x")
        with self.assertRaises(ValueError):
            tw_state.resolve_state("https://trello.com/c/M5JkpDlj",
                                   "/dev/site-manager", directory=self.tmp.name)

    def test_no_match_returns_none(self):
        self.assertIsNone(tw_state.resolve_state(
            "https://trello.com/c/nothing", "/dev/site-manager", directory=self.tmp.name))

    def test_exact_hit_with_foreign_taskurls_not_resolved(self):
        # A renamed/copied state file whose taskUrls describe another task is
        # never silently resolved — only the legacy scan (with ambiguity
        # detection) decides.
        self._state("tw-site-manager--98e87142", "https://trello.com/c/OTHERCARD")
        self.assertIsNone(tw_state.resolve_state(
            "https://trello.com/c/M5JkpDlj", "/dev/site-manager", directory=self.tmp.name))


class TestJournalNeverBlocksTransition(unittest.TestCase):
    def test_mark_succeeds_when_journal_unwritable(self):
        # R2: the journal is a chronicle, never the transaction — an
        # unwritable artifacts dir must NOT fail the transition (warning,
        # exit 0, state persisted).
        tmp = tempfile.TemporaryDirectory()
        try:
            path = os.path.join(tmp.name, "tw-x--1a2b3c4d.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(valid_state(workflowId="tw-x--1a2b3c4d"), handle)
            artifacts = os.path.join(tmp.name, "tw-x--1a2b3c4d")
            os.makedirs(artifacts)
            os.chmod(artifacts, 0o500)  # read-only → append must fail
            script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
            result = subprocess.run(
                [sys.executable, script, "mark", path, "1", "RUNNING"],
                capture_output=True, text=True, check=False,
                env={**os.environ, "TW_STATE_STATE_DIR": tmp.name})
            os.chmod(artifacts, 0o700)
            self.assertEqual(result.returncode, 0)
            self.assertIn("JOURNAL-WARNING", result.stdout)
            state = json.load(open(path, encoding="utf-8"))
            self.assertEqual(state["phaseStatuses"]["1"]["status"], "RUNNING")
        finally:
            tmp.cleanup()

    def test_validate_reports_journal_gap_as_warning_not_failure(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = os.path.join(tmp.name, "tw-x--1a2b3c4d.json")
            state = valid_state(workflowId="tw-x--1a2b3c4d")
            state["phaseStatuses"]["1"] = {"status": "PASSED", "at": TS}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
            # journal exists but does not record the phase-1 transition → gap
            artifacts = os.path.join(tmp.name, "tw-x--1a2b3c4d")
            os.makedirs(artifacts)
            with open(os.path.join(artifacts, "events.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"seq": 1, "type": "note", "at": TS}) + "\n")
            script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
            result = subprocess.run(
                [sys.executable, script, "validate", path],
                capture_output=True, text=True, check=False,
                env={**os.environ, "TW_STATE_STATE_DIR": tmp.name})
            self.assertEqual(result.returncode, 0)  # state = truth: still valid
            self.assertIn("JOURNAL-WARNING", result.stdout)
            self.assertIn("phase 1", result.stdout)
        finally:
            tmp.cleanup()


class TestCliLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tw-x--1a2b3c4d.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(workflowId="tw-x--1a2b3c4d"), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        return subprocess.run(
            [sys.executable, script, *args], capture_output=True, text=True, check=False,
            env={**os.environ, "TW_STATE_STATE_DIR": self.tmp.name})

    def test_log_records_event_with_seq_and_facts(self):
        result = self._run("log", self.path, "--type", "command", "--phase", "4",
                           "--actor", "spark", "--status", "pass",
                           "--summary", "yarn test: 121 passed", "--exit-code", "0")
        self.assertEqual(result.returncode, 0)
        events = tw_state.read_events(self.path)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["seq"], events[0]["type"], events[0]["status"],
                          events[0]["exitCode"]), (1, "command", "pass", 0))

    def test_log_unknown_type_clean_error(self):
        result = self._run("log", self.path, "--type", "gossip")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR", result.stdout)

    def test_log_outside_canonical_dir_refused(self):
        result = self._run("log", "/tmp/nowhere/tw-x--1a2b3c4d.json", "--type", "note")
        self.assertEqual(result.returncode, 1)
        self.assertIn("canonical dir", result.stdout)

    def test_log_non_integer_flag_clean_error(self):
        result = self._run("log", self.path, "--type", "command", "--phase", "four")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be an integer", result.stdout)


class TestCanonicalWriteGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tw-podcast-player--1a2b3c4d.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args, state_dir=None):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        env = dict(os.environ)
        if state_dir is not None:
            env["TW_STATE_STATE_DIR"] = state_dir
        else:
            env.pop("TW_STATE_STATE_DIR", None)
        return subprocess.run(
            [sys.executable, script, *args], capture_output=True, text=True, check=False, env=env)

    def test_write_outside_canonical_dir_refused(self):
        # T-02: without the env override, writes outside the canonical dir fail.
        result = self._run("mark", self.path, "1", "RUNNING")
        self.assertEqual(result.returncode, 1)
        self.assertIn("canonical dir", result.stdout)

    def test_write_inside_state_dir_allowed(self):
        result = self._run("mark", self.path, "1", "RUNNING", state_dir=self.tmp.name)
        self.assertEqual(result.returncode, 0)

    def test_mark_and_invalidate_non_integer_phase_clean_error(self):
        # Review follow-up (fix F): same clean exit-2 as cmd_log.
        for command in ("mark", "invalidate"):
            result = self._run(command, self.path, "four", state_dir=self.tmp.name)
            self.assertEqual(result.returncode, 2, command)
            self.assertIn("must be an integer", result.stdout)


class TestJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tw-x--1a2b3c4d.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(workflowId="tw-x--1a2b3c4d"), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_event_numbered_and_readable(self):
        first = tw_state.append_event(self.path, {"type": "phase", "phase": 1, "status": "RUNNING"})
        second = tw_state.append_event(self.path, {"type": "command", "summary": "yarn test"})
        self.assertEqual((first["seq"], second["seq"]), (1, 2))
        events = tw_state.read_events(self.path)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["summary"], "yarn test")

    def test_unknown_event_type_refused(self):
        with self.assertRaises(ValueError):
            tw_state.append_event(self.path, {"type": "gossip"})

    def test_journal_problems_detect_missing_transition_events(self):
        # Gap: a decided transition with no chronicle line is surfaced, not hidden.
        tw_state.append_event(self.path, {"type": "phase", "phase": 1, "status": "RUNNING", "at": TS})
        state = valid_state()
        state["phaseStatuses"]["2"] = {"status": "PASSED", "at": TS}
        problems = tw_state.journal_problems(state, self.path)
        self.assertTrue(any("phase 2" in p for p in problems))

    def test_journal_problems_empty_without_journal(self):
        # v1 states legitimately have no journal — no problem reported.
        self.assertEqual(tw_state.journal_problems(valid_state(), self.path), [])

    def test_journal_problems_detect_corrupt_line(self):
        journal = tw_state.journal_path_for(self.path)
        os.makedirs(os.path.dirname(journal), exist_ok=True)
        with open(journal, "w", encoding="utf-8") as handle:
            handle.write("not-json\n")
        problems = tw_state.journal_problems(valid_state(), self.path)
        self.assertTrue(any("not valid JSON" in p for p in problems))

    def test_readers_tolerate_valid_json_non_object_lines(self):
        # Review follow-up: a line like `42` is valid JSON but not an event —
        # readers must skip it, never crash with AttributeError.
        journal = tw_state.journal_path_for(self.path)
        os.makedirs(os.path.dirname(journal), exist_ok=True)
        with open(journal, "w", encoding="utf-8") as handle:
            handle.write("42\nnull\n")
        self.assertEqual(tw_state.read_events(self.path), [])
        problems = tw_state.journal_problems(valid_state(), self.path)
        self.assertTrue(any("not a JSON object" in p for p in problems))

    def test_append_event_ignores_caller_seq_keeps_at(self):
        # Review follow-up (fix E): the computed seq is authoritative; a
        # caller-provided `at` is honored (transition markers rely on it).
        event = tw_state.append_event(self.path, {"type": "phase", "phase": 1,
                                                  "status": "RUNNING", "seq": 99, "at": TS})
        self.assertEqual(event["seq"], 1)
        self.assertEqual(event["at"], TS)

    def test_mark_cli_records_transition_event(self):
        env_dir = self.tmp.name
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        env = {**os.environ, "TW_STATE_STATE_DIR": env_dir}
        subprocess.run([sys.executable, script, "mark", self.path, "1", "RUNNING"],
                       capture_output=True, text=True, check=True, env=env)
        subprocess.run([sys.executable, script, "mark", self.path, "1", "PASSED",
                        "--signature", "a" * 40], capture_output=True, text=True, check=True, env=env)
        events = tw_state.read_events(self.path)
        self.assertEqual([(e["type"], e["status"]) for e in events],
                         [("phase", "RUNNING"), ("phase", "PASSED")])
        # The recorded transition matches the persisted state entry exactly.
        state = json.load(open(self.path, encoding="utf-8"))
        self.assertEqual(events[-1]["at"], state["phaseStatuses"]["1"]["at"])


class TestStructuredResults(unittest.TestCase):
    def test_pass_with_nonzero_exit_code_refused(self):
        state = valid_state()
        state["testResults"] = [{"name": "yarn test", "status": "pass", "exitCode": 1}]
        self.assertTrue(any("cannot be reported as pass" in p
                            for p in tw_state.validate_state(state)))

    def test_not_run_is_valid_and_never_pass(self):
        state = valid_state()
        state["qaResults"] = [{"name": "browser QA", "status": "not-run", "note": "auth required"}]
        self.assertEqual(tw_state.validate_state(state), [])

    def test_unknown_status_refused(self):
        state = valid_state()
        state["testResults"] = [{"name": "x", "status": "green"}]
        self.assertTrue(any("status" in p for p in tw_state.validate_state(state)))

    def test_passed_alias_accepted(self):
        # design-qa integration writes "passed" — an alias, same hard rule.
        state = valid_state()
        state["testResults"] = [{"type": "design", "status": "passed", "exitCode": 0}]
        self.assertEqual(tw_state.validate_state(state), [])

    def test_passed_alias_with_nonzero_exit_refused(self):
        state = valid_state()
        state["testResults"] = [{"type": "design", "status": "passed", "exitCode": 1}]
        self.assertTrue(any("cannot be reported as pass" in p
                            for p in tw_state.validate_state(state)))

    def test_freeform_v1_results_stay_valid(self):
        state = valid_state()
        state["testResults"] = [{"suites": "video-encoding-form", "result": "121 passed"}]
        self.assertEqual(tw_state.validate_state(state), [])


class TestSignatureFormat(unittest.TestCase):
    def test_non_sha1_signature_refused(self):
        state = passed(valid_state(), 2, signature="pending")
        problems = tw_state.validate_state(state)
        self.assertTrue(any("40-char git sha1" in p for p in problems))

    def test_sha1_signature_accepted(self):
        state = passed(valid_state(), 2, signature="a" * 40)
        self.assertEqual(tw_state.validate_state(state), [])


class TestValidateAll(unittest.TestCase):
    def test_placeholder_state_detected(self):
        # T-05: hand-written states like tw-site-manager--a1b2c3d4 must surface.
        tmp = tempfile.TemporaryDirectory()
        try:
            placeholder = {
                "schemaVersion": 1, "workflowId": "tw-site-manager--a1b2c3d4",
                "codeSignature": "pending",
            }
            path = os.path.join(tmp.name, "tw-site-manager--a1b2c3d4.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(placeholder, handle)
            script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
            result = subprocess.run(
                [sys.executable, script, "validate-all", tmp.name],
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing required key", result.stdout)
        finally:
            tmp.cleanup()

    def test_corrupt_state_file_reported_not_crash(self):
        # validate-all exists to surface T-05-style corruption — a broken JSON
        # must print a readable PROBLEM, never a traceback.
        tmp = tempfile.TemporaryDirectory()
        try:
            with open(os.path.join(tmp.name, "tw-x--deadbeef.json"), "w", encoding="utf-8") as handle:
                handle.write("{not json at all")
            script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
            result = subprocess.run(
                [sys.executable, script, "validate-all", tmp.name],
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("PROBLEM tw-x--deadbeef.json", result.stdout)
            self.assertIn("corrupt", result.stdout)
        finally:
            tmp.cleanup()

    def test_clean_dir_passes(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            with open(os.path.join(tmp.name, "tw-podcast-player--1a2b3c4d.json"),
                      "w", encoding="utf-8") as handle:
                json.dump(valid_state(), handle)
            script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
            result = subprocess.run(
                [sys.executable, script, "validate-all", tmp.name],
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
