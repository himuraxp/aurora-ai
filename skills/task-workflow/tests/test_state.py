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
        "mrResults": [],
        "notifyResults": [],
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


class TestHandoff(unittest.TestCase):
    """Handoff takeover (strategy A): the state tracks WHO owns the mandate.
    Never two pilots; recovery only through conscious --force."""

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

    # — unit level

    def test_pending_then_claim_accepts(self):
        state = valid_state()
        tw_state.set_handoff(state, "pending", worktree_path="/tmp/wt")
        self.assertEqual(tw_state.validate_state(state), [])
        self.assertEqual(tw_state.claim_handoff(state, "pane:t1"), "claimed")
        self.assertEqual(state["handoff"]["status"], "accepted")
        self.assertEqual(state["handoff"]["session"], "pane:t1")
        self.assertEqual(tw_state.validate_state(state), [])

    def test_claim_idempotent_for_same_session(self):
        state = valid_state()
        tw_state.set_handoff(state, "pending")
        tw_state.claim_handoff(state, "pane:t1")
        self.assertIn("idempotent", tw_state.claim_handoff(state, "pane:t1"))

    def test_concurrent_claim_refused(self):
        state = valid_state()
        tw_state.set_handoff(state, "pending")
        tw_state.claim_handoff(state, "pane:t1")
        with self.assertRaises(ValueError):
            tw_state.claim_handoff(state, "pane:t2")

    def test_force_recovery_is_explicit(self):
        state = valid_state()
        tw_state.set_handoff(state, "pending")
        tw_state.claim_handoff(state, "pane:t1")
        self.assertIn("recovered", tw_state.claim_handoff(state, "pane:t2", force=True))

    def test_claim_requires_a_session_label(self):
        state = valid_state()
        tw_state.set_handoff(state, "pending")
        with self.assertRaises(ValueError):
            tw_state.claim_handoff(state, "")
        with self.assertRaises(ValueError):
            tw_state.claim_handoff(state, "   ")

    def test_set_handoff_contract(self):
        state = valid_state()
        with self.assertRaises(ValueError):
            tw_state.set_handoff(state, "accepted")  # acceptance only via claim
        with self.assertRaises(ValueError):
            tw_state.set_handoff(state, "maybe")
        for status in ("failed", "uncertain", "pending"):
            tw_state.set_handoff(state, status)
            self.assertEqual(tw_state.validate_state(state), [])

    # — validate contract

    def test_validate_accepted_without_session_is_invalid(self):
        state = valid_state()
        state["handoff"] = {"status": "accepted", "at": TS}
        self.assertIn("handoff.status=accepted requires the claimed session",
                      tw_state.validate_state(state))

    def test_validate_unknown_handoff_status_is_invalid(self):
        state = valid_state()
        state["handoff"] = {"status": "maybe", "at": TS}
        self.assertTrue(any("handoff.status must be one of" in p
                            for p in tw_state.validate_state(state)))

    def test_validate_skipped_without_why_is_invalid(self):
        state = valid_state()
        state["handoff"] = {"status": "skipped", "at": TS}
        self.assertTrue(any("skipped requires a why" in p
                            for p in tw_state.validate_state(state)))

    def test_skipped_with_reason_is_valid_and_never_claimable(self):
        state = valid_state()
        tw_state.set_handoff(state, "skipped", why="hors Orca")
        self.assertEqual(tw_state.validate_state(state), [])
        with self.assertRaises(ValueError):
            tw_state.claim_handoff(state, "pane:t1")

    def test_uncertain_is_claimable_conscious_recovery(self):
        # SKILL.md Phase 2: the uncertain recovery is claim + resume from the
        # worktree session — the claim MUST be accepted on uncertain.
        state = valid_state()
        tw_state.set_handoff(state, "uncertain", why="terminal créé, handle absent")
        self.assertEqual(tw_state.claim_handoff(state, "pane:t1"), "claimed")
        self.assertEqual(state["handoff"]["status"], "accepted")
        self.assertEqual(state["handoff"]["session"], "pane:t1")
        self.assertEqual(tw_state.validate_state(state), [])

    # — CLI lifecycle

    def test_cli_full_lifecycle_with_concurrency_refusal(self):
        self.assertEqual(self._run("handoff", self.path, "pending",
                                   "--path", "/tmp/wt").returncode, 0)
        result = self._run("claim", self.path, "--session", "pane:t1")
        self.assertEqual(result.returncode, 0)
        self.assertIn("handoff claimed by pane:t1", result.stdout)
        # Concurrent claim refused, conscious recovery allowed and journaled.
        refused = self._run("claim", self.path, "--session", "pane:t2")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("ILLEGAL", refused.stdout)
        forced = self._run("claim", self.path, "--session", "pane:t2", "--force")
        self.assertEqual(forced.returncode, 0)
        self.assertIn("recovered", forced.stdout)

    def test_cli_claim_without_session_is_usage_error(self):
        result = self._run("claim", self.path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--session", result.stdout)

    def test_cli_resume_warnings_go_to_stderr_and_json_stays_parseable(self):
        self._run("handoff", self.path, "pending", "--handle", "term_1")
        warned = self._run("resume", self.path, "--session", "pane:t9")
        self.assertEqual(warned.returncode, 0)
        self.assertIn("HANDOFF-WARNING", warned.stderr)
        self.assertEqual(json.loads(warned.stdout)["resumeAt"], 1)
        self._run("claim", self.path, "--session", "pane:t1")
        concurrent = self._run("resume", self.path, "--session", "pane:t9")
        self.assertIn("CONCURRENCY-WARNING", concurrent.stderr)
        quiet = self._run("resume", self.path)
        self.assertNotIn("CONCURRENCY-WARNING", quiet.stderr)
        self.assertNotIn("HANDOFF-WARNING", quiet.stderr)

    def test_journal_distinguishes_the_two_actors(self):
        self._run("handoff", self.path, "pending", "--path", "/tmp/wt")
        self._run("claim", self.path, "--session", "pane:t1")
        events = tw_state.read_events(self.path)
        summaries = [event.get("summary", "") for event in events]
        self.assertTrue(any(s.startswith("handoff pending") for s in summaries))
        self.assertTrue(any(s.startswith("handoff claimed") for s in summaries))
        actors = {event.get("actor") for event in events}
        self.assertIn("orchestrator", actors)
        self.assertIn("pane:t1", actors)


class TestEvidenceGuard(unittest.TestCase):
    """P0/P1 tour-2 (cowork 2026-10-15): PASSED = evidence recorded + chain
    freshness. Transition-level guard (cmd_mark) — existing states stay valid."""

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

    def _advance_to(self, phase):
        sig = "a" * 40
        evidence = {4: "testResults", 5: "qaResults", 6: "reviewResults",
                    7: "mrResults"}
        for p in range(1, phase + 1):
            self._run("mark", self.path, str(p), "RUNNING")
            if p in evidence:  # the guard requires recorded evidence for 4+
                state = tw_state.load_state(self.path)
                state[evidence[p]] = [{"phase": p, "name": f"check-{p}",
                                       "status": "pass", "exitCode": 0}]
                tw_state.save_state(self.path, state)
            self._run("mark", self.path, str(p), "PASSED", "--signature", sig)

    def test_phase4_passed_without_results_refused(self):
        self._advance_to(3)
        self._run("mark", self.path, "4", "RUNNING")
        result = self._run("mark", self.path, "4", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ILLEGAL", result.stdout)
        self.assertIn("testResults", result.stdout)
        state = tw_state.load_state(self.path)
        self.assertEqual(state["phaseStatuses"]["4"]["status"], "RUNNING")

    def test_phase4_passed_with_recorded_results_persists(self):
        self._advance_to(3)
        state = tw_state.load_state(self.path)
        state["testResults"] = [{"phase": 4, "name": "unit", "status": "pass", "exitCode": 0}]
        tw_state.save_state(self.path, state)
        self._run("mark", self.path, "4", "RUNNING")
        result = self._run("mark", self.path, "4", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(tw_state.load_state(self.path)["phaseStatuses"]["4"]["status"], "PASSED")

    def test_phase5_skipped_entry_counts_as_evidence(self):
        # Missing evidence ≠ failed control: a legitimate skip is RECORDED,
        # and a recorded skip is valid evidence of an honest decision.
        self._advance_to(4)
        state = tw_state.load_state(self.path)
        state["qaResults"] = [{"phase": 5, "status": "skipped",
                               "name": "QA navigateur", "reason": "aucune UI exposée"}]
        tw_state.save_state(self.path, state)
        self._run("mark", self.path, "5", "RUNNING")
        result = self._run("mark", self.path, "5", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_signature_required_for_code_phases(self):
        self._advance_to(3)
        state = tw_state.load_state(self.path)
        state["testResults"] = [{"phase": 4, "name": "unit", "status": "pass", "exitCode": 0}]
        tw_state.save_state(self.path, state)
        self._run("mark", self.path, "4", "RUNNING")
        result = self._run("mark", self.path, "4", "PASSED")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--signature", result.stdout)

    def test_chain_signature_mismatch_refused(self):
        # Freshness DURING execution, not only at resume: QA passed on other
        # code than the tests → the chain is stale, invalidate first.
        self._advance_to(4)
        state = tw_state.load_state(self.path)
        state["qaResults"] = [{"phase": 5, "status": "pass", "name": "QA", "exitCode": 0}]
        tw_state.save_state(self.path, state)
        self._run("mark", self.path, "5", "RUNNING")
        result = self._run("mark", self.path, "5", "PASSED", "--signature", "b" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("different codeSignature", result.stdout)
        self.assertIn("invalidate", result.stdout)

    def test_chain_same_signature_ok(self):
        self._advance_to(4)
        state = tw_state.load_state(self.path)
        state["qaResults"] = [{"phase": 5, "status": "pass", "name": "QA", "exitCode": 0}]
        tw_state.save_state(self.path, state)
        self._run("mark", self.path, "5", "RUNNING")
        result = self._run("mark", self.path, "5", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_chain_symmetric_mismatch_on_later_phase(self):
        # Partial resume (cowork tour 2): 4,5,6 PASSED on sig A → 5 invalidated
        # → re-run on sig B must be REFUSED while 6 still carries A — the
        # chain is symmetric, a later PASSED phase is stale evidence too.
        self._advance_to(6)
        self.assertEqual(self._run("invalidate", self.path, "5").returncode, 0)
        state = tw_state.load_state(self.path)
        state["qaResults"] = [{"phase": 5, "name": "QA", "status": "pass", "exitCode": 0}]
        tw_state.save_state(self.path, state)
        self._run("mark", self.path, "5", "RUNNING")
        result = self._run("mark", self.path, "5", "PASSED", "--signature", "b" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("different codeSignature", result.stdout)
        # invalidating the remaining stale chain phases unblocks the re-run
        for stale_phase in ("4", "6"):
            self.assertEqual(self._run("invalidate", self.path, stale_phase).returncode, 0)
        result = self._run("mark", self.path, "5", "PASSED", "--signature", "b" * 40)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_skipped_without_reason_not_evidence(self):
        # The contract says "skipped + reason": a reason-less skip entry is
        # not evidence of an honest decision — the guard refuses it.
        self._advance_to(4)
        state = tw_state.load_state(self.path)
        state["qaResults"] = [{"phase": 5, "name": "QA", "status": "skipped"}]
        tw_state.save_state(self.path, state)
        self._run("mark", self.path, "5", "RUNNING")
        result = self._run("mark", self.path, "5", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("reason", result.stdout)

    def test_evidence_requires_phase_attachment(self):
        # An unattached entry proves nothing specific — the guard refuses it
        # (and invalidation could never purge what it cannot attribute).
        self._advance_to(3)
        state = tw_state.load_state(self.path)
        state["testResults"] = [{"name": "unit", "status": "pass", "exitCode": 0}]
        tw_state.save_state(self.path, state)
        self._run("mark", self.path, "4", "RUNNING")
        result = self._run("mark", self.path, "4", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("attached to it", result.stdout)

    def test_invalidate_purges_results_and_rolls_back(self):
        # Evidence may not outlive the phase it proved: invalidate purges the
        # phase's recorded results, rolls currentPhase back, and the purged
        # evidence can no longer satisfy a new PASSED (no silent carry-over).
        self._advance_to(4)
        result = self._run("invalidate", self.path, "4")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("purged", result.stdout)
        state = tw_state.load_state(self.path)
        self.assertEqual(state["currentPhase"], 4)
        self.assertEqual(
            [e for e in state["testResults"] if str(e.get("phase")) == "4"], [])
        self._run("mark", self.path, "4", "RUNNING")
        refusal = self._run("mark", self.path, "4", "PASSED", "--signature", "a" * 40)
        self.assertEqual(refusal.returncode, 1)
        self.assertIn("requires at least one structured entry", refusal.stdout)

    def test_phases_outside_chain_unaffected(self):
        # Phases 1-3 keep the historical behaviour (no evidence guard): the
        # guard must never invent constraints the workflow does not declare.
        result = self._run("mark", self.path, "1", "RUNNING")
        self.assertEqual(result.returncode, 0)
        result = self._run("mark", self.path, "1", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 0, result.stdout)
        self._run("mark", self.path, "2", "RUNNING")
        result = self._run("mark", self.path, "2", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 0, result.stdout)


class TestMrEvidenceGuard(unittest.TestCase):
    """MR !602 post-mortem (2026-10-21): the description was published in the
    skill's default format without the project template and without a
    comparison table — the pipeline was bypassed and the skip was silent.
    Phase 7 joins the evidence guard: a PASSED MR phase must carry mrResults[]
    declaring templateUsed and comparisonTable. Transition-level guard
    (cmd_mark only) — existing states stay valid."""

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

    def _advance_to(self, phase):
        sig = "a" * 40
        evidence = {4: "testResults", 5: "qaResults", 6: "reviewResults",
                    7: "mrResults"}
        for p in range(1, phase + 1):
            self._run("mark", self.path, str(p), "RUNNING")
            if p in evidence:  # the guard requires recorded evidence for 4+
                state = tw_state.load_state(self.path)
                entry = {"phase": p, "name": f"check-{p}",
                         "status": "pass", "exitCode": 0}
                if p == 7:  # the guard requires the declared MR facts
                    entry.update({"templateUsed": "default.md",
                                  "comparisonTable": "visual"})
                state[evidence[p]] = [entry]
                tw_state.save_state(self.path, state)
            self._run("mark", self.path, str(p), "PASSED", "--signature", sig)

    def _with_mr_results(self, entry):
        state = tw_state.load_state(self.path)
        state["mrResults"] = [entry]
        tw_state.save_state(self.path, state)

    def test_phase7_passed_without_mr_results_refused(self):
        self._advance_to(6)
        self._run("mark", self.path, "7", "RUNNING")
        result = self._run("mark", self.path, "7", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ILLEGAL", result.stdout)
        self.assertIn("mrResults", result.stdout)
        state = tw_state.load_state(self.path)
        self.assertEqual(state["phaseStatuses"]["7"]["status"], "RUNNING")

    def test_phase7_passed_with_mr_results_persists(self):
        self._advance_to(6)
        self._with_mr_results({"phase": 7, "name": "create-mr", "status": "pass",
                               "templateUsed": "default.md",
                               "comparisonTable": "visual"})
        self._run("mark", self.path, "7", "RUNNING")
        result = self._run("mark", self.path, "7", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(
            tw_state.load_state(self.path)["phaseStatuses"]["7"]["status"], "PASSED")

    def test_bare_mr_results_entry_refused(self):
        # An entry without templateUsed/comparisonTable satisfies the count
        # while bypassing the declaration — the exact !602 bypass, refused.
        self._advance_to(6)
        self._with_mr_results({"phase": 7, "name": "create-mr", "status": "pass",
                               "exitCode": 0})
        self._run("mark", self.path, "7", "RUNNING")
        result = self._run("mark", self.path, "7", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("templateUsed", result.stdout)

    def test_comparison_none_without_reason_refused(self):
        # The silent-skip hole this guard closes: declaring "no table" without
        # a reason is the !602 failure mode (skip indistinguishable from a
        # forgotten step). The entry is written after the RUNNING mark: the
        # invalid one must be refused at the PASSED transition itself.
        self._advance_to(6)
        self._run("mark", self.path, "7", "RUNNING")
        self._with_mr_results({"phase": 7, "name": "create-mr", "status": "pass",
                               "templateUsed": "default.md",
                               "comparisonTable": "none"})
        result = self._run("mark", self.path, "7", "PASSED", "--signature", "a" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("comparisonTable=none requires a non-empty reason", result.stdout)
        self.assertIn("state NOT saved", result.stdout)

    def test_bad_comparison_mode_invalid(self):
        problems = tw_state.validate_state(valid_state(mrResults=[
            {"phase": 7, "name": "create-mr", "status": "pass",
             "templateUsed": "default.md", "comparisonTable": "screenshot"}]))
        self.assertTrue(any("comparisonTable" in p for p in problems))

    def test_none_without_reason_invalid(self):
        problems = tw_state.validate_state(valid_state(mrResults=[
            {"phase": 7, "name": "create-mr", "status": "pass",
             "templateUsed": "default.md", "comparisonTable": "none"}]))
        self.assertTrue(any("comparisonTable=none" in p for p in problems))

    def test_empty_template_used_invalid(self):
        problems = tw_state.validate_state(valid_state(mrResults=[
            {"phase": 7, "name": "create-mr", "status": "pass",
             "templateUsed": "  ", "comparisonTable": "visual"}]))
        self.assertTrue(any("templateUsed" in p for p in problems))

    def test_none_with_reason_is_valid_evidence(self):
        # A recorded, reasoned "none" is honest evidence — same philosophy as
        # the phase-5 skipped QA entry: a legitimate skip is RECORDED.
        problems = tw_state.validate_state(valid_state(mrResults=[
            {"phase": 7, "name": "create-mr", "status": "pass",
             "templateUsed": "default.md", "comparisonTable": "none",
             "reason": "changement de données, pas de nouveau flux UI"}]))
        self.assertEqual(problems, [])

    def test_v1_state_without_mr_results_stays_valid(self):
        # Transition-level guard: the check runs at mark time, never as a
        # cold re-validation — v1 states without mrResults stay valid.
        state = valid_state()
        del state["mrResults"]
        self.assertEqual(tw_state.validate_state(state), [])

    def test_v1_state_with_phase7_already_passed_stays_valid(self):
        # The !602 production scenario in reverse: a workflow created BEFORE
        # this guard, whose phase 7 is already PASSED without any mrResults,
        # resumes cleanly — the guard never re-validates history at rest.
        state = valid_state(currentPhase=8)
        del state["mrResults"]
        for phase in range(1, 8):
            passed(state, phase, signature="a" * 40)
        self.assertEqual(tw_state.validate_state(state), [])

    def test_phase7_invalidate_purges_mr_results(self):
        # Evidence may not outlive the phase it proved: invalidating the MR
        # phase purges its mrResults (no silent carry-over on re-run).
        self._advance_to(7)
        result = self._run("invalidate", self.path, "7")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("purged", result.stdout)
        state = tw_state.load_state(self.path)
        self.assertEqual(
            [e for e in state["mrResults"] if str(e.get("phase")) == "7"], [])


class TestNotifyResults(unittest.TestCase):
    """Step 7 bis (Trello→MR link): notification outcomes are additive state —
    never a phase proof (no evidence guard: a courtesy notification never gates
    PASSED), but honest when machine-annotated."""

    def test_notify_results_validation_additive(self):
        problems = tw_state.validate_state(valid_state(notifyResults=[
            {"channel": "api", "status": "pass",
             "mergeRequestUrl": "https://gitlab.example/mr/1"}]))
        self.assertEqual(problems, [])

    def test_notify_results_empty_channel_invalid(self):
        problems = tw_state.validate_state(valid_state(notifyResults=[
            {"channel": "  ", "status": "pass"}]))
        self.assertTrue(any("channel" in p for p in problems))

    def test_notify_results_v1_states_stay_valid(self):
        state = valid_state()
        del state["notifyResults"]
        self.assertEqual(tw_state.validate_state(state), [])

    def test_notify_results_skipped_without_reason_invalid(self):
        # Same doctrine as the evidence guard: a skip without a reason is not
        # a record (review F-11).
        problems = tw_state.validate_state(valid_state(notifyResults=[
            {"channel": "api", "status": "skipped"}]))
        self.assertTrue(any("reason" in p for p in problems))

    def test_notify_results_relative_mr_url_invalid(self):
        problems = tw_state.validate_state(valid_state(notifyResults=[
            {"channel": "api", "status": "pass", "mergeRequestUrl": "mr/1"}]))
        self.assertTrue(any("http(s)" in p for p in problems))

    def test_notify_command_records_outcome(self):
        # Sanctioned write path (review F-04): canonical guard + validate +
        # journal — the SKILL forbids manual JSON edits, so notifyResults[]
        # MUST have a CLI.
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "tw-podcast-player--1a2b3c4d.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(), handle)
        result = subprocess.run(
            [sys.executable, script, "notify", path, "--channel", "api",
             "--status", "pass", "--mr-url", "https://gitlab.example/mr/1",
             "--comment-id", "68f0a1b2"],
            capture_output=True, text=True, check=False,
            env={**os.environ, "TW_STATE_STATE_DIR": tmp.name})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = tw_state.load_state(path)
        self.assertEqual(state["notifyResults"][0]["channel"], "api")
        self.assertEqual(state["notifyResults"][0]["status"], "pass")
        self.assertEqual(state["notifyResults"][0]["commentId"], "68f0a1b2")
        self.assertEqual(state["notifyResults"][0]["phase"], 7)

    def test_notify_command_skipped_without_reason_refused(self):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "tw-podcast-player--1a2b3c4d.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(), handle)
        result = subprocess.run(
            [sys.executable, script, "notify", path, "--channel", "browser",
             "--status", "skipped", "--mr-url", "https://gitlab.example/mr/1"],
            capture_output=True, text=True, check=False,
            env={**os.environ, "TW_STATE_STATE_DIR": tmp.name})
        self.assertEqual(result.returncode, 1)
        self.assertIn("reason", result.stdout)
        state = tw_state.load_state(path)
        self.assertEqual(state.get("notifyResults", []), [])

    def test_notify_command_bad_channel_refused(self):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_state.py")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "tw-podcast-player--1a2b3c4d.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(valid_state(), handle)
        result = subprocess.run(
            [sys.executable, script, "notify", path, "--channel", "pigeon",
             "--status", "pass", "--mr-url", "https://gitlab.example/mr/1"],
            capture_output=True, text=True, check=False,
            env={**os.environ, "TW_STATE_STATE_DIR": tmp.name})
        self.assertEqual(result.returncode, 2)


class TestNoOrcaFallback(unittest.TestCase):
    """Fallback contract: without Orca the workflow keeps its historical path —
    no handoff block, state stays valid, resume stays quiet."""

    def test_state_without_handoff_is_the_norm(self):
        state = valid_state()
        self.assertEqual(tw_state.validate_state(state), [])
        self.assertIsNone(state.get("handoff"))


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


class TestRiskLevelAndContract(unittest.TestCase):
    """Software Fundamentals lot 1 (additive): riskLevel + implementationContract."""

    def test_v1_state_without_risk_fields_stays_valid(self):
        legacy = valid_state()
        self.assertNotIn("riskLevel", legacy)
        self.assertNotIn("implementationContract", legacy)
        self.assertEqual(tw_state.validate_state(legacy), [])

    def test_risk_level_values(self):
        for level in ("LOW", "MEDIUM", "HIGH"):
            self.assertEqual(tw_state.validate_state(valid_state(riskLevel=level)), [])
        self.assertEqual(tw_state.validate_state(valid_state(riskLevel=None)), [])

    def test_risk_level_invalid(self):
        bad = valid_state(riskLevel="CRITICAL")
        self.assertTrue(any("riskLevel" in p for p in tw_state.validate_state(bad)))
        bad = valid_state(riskLevel="")
        self.assertTrue(any("riskLevel" in p for p in tw_state.validate_state(bad)))

    def test_contract_valid(self):
        contract = {
            "observableBehaviors": ["sort button disabled while a run is streaming"],
            "invariants": ["no run deleted on cancel"],
            "acceptanceCriteria": ["cancel stops the encoder within 2s"],
            "expectedEvidence": ["unit tests on cancel path"],
            "modulesAffected": ["RunsService", "RunDetailComponent"],
            "constraints": ["API of RunsService stays backward compatible"],
        }
        self.assertEqual(tw_state.validate_state(valid_state(implementationContract=contract)), [])
        # Partial contract (at least one known section) is legitimate.
        self.assertEqual(
            tw_state.validate_state(valid_state(implementationContract={"invariants": ["x"]})), [])

    def test_contract_invalid(self):
        problems = tw_state.validate_state(valid_state(implementationContract={}))
        self.assertTrue(any("implementationContract" in p for p in problems))
        problems = tw_state.validate_state(valid_state(implementationContract="path.json"))
        self.assertTrue(any("implementationContract" in p for p in problems))
        problems = tw_state.validate_state(valid_state(implementationContract={"unknown": ["x"]}))
        self.assertTrue(any("at least one section" in p for p in problems))
        # Co-occurrence: section-level AND "at least one section" errors both
        # surface for an empty unknown section (plan requirement).
        problems = tw_state.validate_state(valid_state(implementationContract={"unknown": []}))
        self.assertTrue(any("non-empty list" in p for p in problems))
        self.assertTrue(any("at least one section" in p for p in problems))

    def test_contract_sections_must_be_non_empty_string_lists(self):
        for bad_section in ({"invariants": []}, {"invariants": ""}, {"invariants": ["", "x"]},
                            {"invariants": [42]}, {"invariants": "one string"}):
            problems = tw_state.validate_state(valid_state(implementationContract=bad_section))
            self.assertTrue(any("non-empty list" in p for p in problems), f"case {bad_section}")

    def test_increment_evidence_additive(self):
        state = valid_state(testResults=[
            {"phase": 4, "name": "unit:cancel", "status": "pass", "exitCode": 0,
             "increment": "increment-2-cancel-path",
             "codeSignature": "a" * 40},
        ])
        self.assertEqual(tw_state.validate_state(state), [])

    def test_increment_evidence_invalid(self):
        base = [{"phase": 4, "name": "unit:cancel", "status": "pass", "exitCode": 0}]
        cases = [
            {"increment": ""},                       # empty string
            {"increment": "   "},                    # whitespace only
            {"codeSignature": "not-a-sha"},          # bad sha1
            {"codeSignature": "b" * 39},             # truncated sha1
        ]
        for extra in cases:
            entry = dict(base[0], **extra)
            problems = tw_state.validate_state(valid_state(testResults=[entry]))
            self.assertTrue(any("must be" in p for p in problems), f"case {extra}")


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
