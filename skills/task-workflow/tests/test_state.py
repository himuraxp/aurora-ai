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
        self.path = os.path.join(self.tmp.name, "state.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        return subprocess.run(
            [sys.executable, script, *args], capture_output=True, text=True, check=False
        )

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
        # F-09: in task-workflows/, the file name must be <workflowId>.json.
        state = valid_state()
        good = tw_state.validate_state(state, path="/x/task-workflows/tw-podcast-player--1a2b3c4d.json")
        self.assertEqual(good, [])
        bad = tw_state.validate_state(state, path="/x/task-workflows/other-name.json")
        self.assertTrue(any("file name" in p for p in bad))
        # Outside the canonical dir, no name constraint.
        elsewhere = tw_state.validate_state(state, path="/tmp/anything.json")
        self.assertEqual(elsewhere, [])

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
        self.path = os.path.join(self.tmp.name, "state.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        return subprocess.run(
            [sys.executable, script, *args], capture_output=True, text=True, check=False
        )

    def _content(self):
        with open(self.path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_mark_with_signature_persists_and_enables_stale(self):
        self.assertEqual(self._run("mark", self.path, "1", "RUNNING").returncode, 0)
        result = self._run("mark", self.path, "1", "PASSED", "--signature", "sig-1")
        self.assertEqual(result.returncode, 0)
        state = json.loads(self._content())
        self.assertEqual(state["phaseStatuses"]["1"]["codeSignature"], "sig-1")
        self.assertEqual(tw_state.compute_stale(state, "sig-1"), [])
        self.assertEqual(tw_state.compute_stale(state, "sig-2"), [1])

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
        self._run("mark", self.path, "1", "PASSED", "--signature", "sig-1")
        self.assertEqual(self._run("invalidate", self.path, "1").returncode, 0)
        state = json.loads(self._content())
        self.assertEqual(state["phaseStatuses"]["1"]["status"], "PENDING")
        self.assertEqual(self._run("invalidate", self.path, "1").returncode, 1)

    def test_signature_cli(self):
        result = self._run("signature", self.tmp.name)
        self.assertEqual(result.returncode, 1)  # not a git repo → clean error
        self.assertIn("ERROR", result.stdout)


if __name__ == "__main__":
    unittest.main()
