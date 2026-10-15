#!/usr/bin/env python3
"""Tests for tw_report.py — deterministic, idempotent, never-inventing renderer.
Fixtures only: no network, no git side effects, no real worktree."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tw_state  # noqa: E402
import tw_report  # noqa: E402

TS = "2026-10-15T06:28:10+00:00"
SIG = "a" * 40


def rich_state(**overrides):
    """A !570-shaped state: 7 phases done, QA skipped, 1 HUMAN decision, MR open."""
    state = {
        "schemaVersion": 1,
        "workflowId": "tw-site-manager--98e87142",
        "taskUrls": [{"source": "trello",
                      "url": "https://trello.com/c/M5JkpDlj/518-ordre-de-la-selection"}],
        "repository": "/dev/split-manager-media/site-manager",
        "baseBranch": "develop",
        "baseCommit": "be8572c",
        "featureBranch": "fix/trello-M5JkpDlj--reorder-profile-options",
        "worktreePath": "/nowhere",
        "currentPhase": 9,
        "phaseStatuses": {
            str(phase): {"status": "PASSED", "at": TS, "codeSignature": SIG}
            for phase in (1, 2, 3, 4, 6, 7, 8, 9)
        },
        "createdAt": "2026-10-15T06:27:59+00:00",
        "updatedAt": "2026-10-15T06:30:34+00:00",
        "decisions": [{"question": "Default sur standard : changer quelque chose ?",
                       "answer": "Réordonner seulement", "source": "HUMAN"}],
        "testResults": [
            {"phase": 4, "name": "tests ciblés", "status": "pass", "exitCode": 0},
            {"phase": 4, "name": "lint", "status": "pass", "exitCode": 0},
            {"phase": 4, "name": "tsc", "status": "fail", "exitCode": 2,
             "baseline": "69 erreurs préexistantes identiques sur develop, 0 sur le diff",
             "note": "préexistant, pas une régression"},
        ],
        "qaResults": [{"phase": 5, "status": "skipped", "name": "QA navigateur",
                       "reason": "auth manager + convertisseur réel requis"}],
        "reviewResults": [{"phase": 6, "name": "pre-mr-review", "status": "pass", "exitCode": 0}],
        "mergeRequestUrl": "https://gitlab.example.com/g/r/-/merge_requests/570",
        "blockers": [],
        "phaseStatuses_5": None,
    }
    state["phaseStatuses"]["5"] = {"status": "SKIPPED", "at": TS}
    state.pop("phaseStatuses_5")
    state.update(overrides)
    return state


CONTEXT = {"files_changed": 2, "head_commit": "5b8bf5f", "detail_path": "/x/report-detailed.md"}


class TestOperational(unittest.TestCase):
    def test_compact_at_most_15_non_empty_lines(self):
        out = tw_report.render_operational(rich_state(), [], CONTEXT)
        self.assertLessEqual(len([l for l in out.splitlines() if l.strip()]), 15)

    def test_passed_runs_are_grouped(self):
        out = tw_report.render_operational(rich_state(), [], CONTEXT)
        self.assertIn("1-4 ✅", out)
        self.assertIn("6-9 ✅", out)

    def test_skipped_is_visible_with_short_name_and_reason(self):
        out = tw_report.render_operational(rich_state(), [], CONTEXT)
        self.assertIn("⏭️ QA", out)
        self.assertIn("auth manager", out)

    def test_mr_ready_status_and_next_action(self):
        out = tw_report.render_operational(rich_state(), [], CONTEXT)
        self.assertIn("MR !570 prête", out)
        self.assertIn("revue humaine de MR !570", out)

    def test_blocked_status_and_blocker_next_action(self):
        state = rich_state()
        state["phaseStatuses"]["4"] = {"status": "BLOCKED", "at": TS}
        state["blockers"] = [{"phase": 4, "note": "PO arbitrage requis sur le défaut"}]
        out = tw_report.render_operational(state, [], CONTEXT)
        self.assertIn("⛔", out)
        self.assertIn("lever le blocker", out)
        self.assertIn("PO arbitrage", out)

    def test_no_mr_omits_mr_line_and_asks_resume(self):
        out = tw_report.render_operational(rich_state(mergeRequestUrl=None), [], CONTEXT)
        self.assertNotIn("**MR**", out)
        self.assertIn("reprendre", out)

    def test_git_facts_rendered_when_measured(self):
        out = tw_report.render_operational(rich_state(), [], CONTEXT)
        self.assertIn("commit `5b8bf5f`", out)
        self.assertIn("2 fichiers", out)

    def test_unmeasured_git_facts_omitted_not_invented(self):
        out = tw_report.render_operational(rich_state(), [], {})
        self.assertNotIn("commit `", out)
        self.assertNotIn("fichiers", out)

    def test_corrupt_journal_line_does_not_take_report_hostage(self):
        # A broken chronicle line never takes the report hostage (review A):
        # the corrupt line is skipped, valid events still render.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tw-x--1a2b3c4d.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(rich_state(), handle)
            artifacts = os.path.join(tmp, "tw-x--1a2b3c4d")
            os.makedirs(artifacts)
            with open(os.path.join(artifacts, "events.jsonl"), "w", encoding="utf-8") as handle:
                handle.write("not-json\n")
                handle.write(json.dumps({"seq": 2, "type": "phase", "phase": 1,
                                         "status": "RUNNING", "at": TS}) + "\n")
            events = tw_state.read_events(path)
            self.assertEqual(len(events), 1)  # corrupt line skipped, valid kept
            out = tw_report.render_detailed(rich_state(), events, CONTEXT)
            self.assertIn("## Phase 1", out)

    def test_baseline_surfaced(self):
        out = tw_report.render_operational(rich_state(), [], CONTEXT)
        self.assertIn("baseline", out)
        self.assertIn("69 erreurs", out)

    def test_deterministic_idempotent(self):
        first = tw_report.render_operational(rich_state(), [], CONTEXT)
        second = tw_report.render_operational(rich_state(), [], CONTEXT)
        self.assertEqual(first, second)


class TestDetailed(unittest.TestCase):
    def test_pending_phases_have_no_section(self):
        state = rich_state()
        state["mergeRequestUrl"] = None
        state["phaseStatuses"]["8"] = {"status": "PENDING", "at": TS}
        state["phaseStatuses"].pop("9")
        out = tw_report.render_detailed(state, [], CONTEXT)
        self.assertNotIn("## Phase 9", out)

    def test_skipped_phase_shown_as_not_passed(self):
        out = tw_report.render_detailed(rich_state(), [], CONTEXT)
        self.assertIn("## Phase 5 — QA", out)
        self.assertIn("SKIPPED", out)
        self.assertIn("SKIPPED ≠ réussi", out)

    def test_decisions_listed_with_source(self):
        out = tw_report.render_detailed(rich_state(), [], CONTEXT)
        self.assertIn("[HUMAN]", out)
        self.assertIn("Réordonner seulement", out)

    def test_missing_journal_declared_not_hidden(self):
        out = tw_report.render_detailed(rich_state(), [], CONTEXT)
        self.assertIn("non enregistrée", out)

    def test_structured_validations_with_exit_codes(self):
        out = tw_report.render_detailed(rich_state(), [], CONTEXT)
        self.assertIn("tests ciblés ✅ (exit 0)", out)
        self.assertIn("tsc ❌ (exit 2)", out)
        self.assertIn("préexistantes identiques sur develop", out)

    def test_deterministic_idempotent(self):
        first = tw_report.render_detailed(rich_state(), [], CONTEXT)
        second = tw_report.render_detailed(rich_state(), [], CONTEXT)
        self.assertEqual(first, second)


class TestSkipReasonFallback(unittest.TestCase):
    def _state_skipped(self, skip_phases, with_phase_key):
        state = rich_state(mergeRequestUrl=None)
        for phase in skip_phases:
            state["phaseStatuses"][str(phase)] = {"status": "SKIPPED", "at": TS}
        entry = {"status": "skipped", "name": "QA navigateur", "reason": "auth manager requise"}
        if with_phase_key:
            entry["phase"] = skip_phases[0]
        state["qaResults"] = [entry]
        return state

    def test_orphan_reason_attached_to_single_skipped_phase(self):
        # v1 fallback (fix H): un-attributed reason attaches only when the
        # phase is the single SKIPPED phase — no guessing.
        out = tw_report.render_operational(self._state_skipped([5], with_phase_key=False), [], CONTEXT)
        self.assertIn("⏭️ QA (auth manager requise)", out)

    def test_orphan_reason_not_attached_when_ambiguous(self):
        # Two SKIPPED phases + un-attributed reason → honest omission, no guess.
        out = tw_report.render_operational(self._state_skipped([5, 6], with_phase_key=False), [], CONTEXT)
        self.assertNotIn("auth manager requise)", out)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tw-site-manager--98e87142.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(rich_state(worktreePath=self.tmp.name), handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        script = os.path.join(os.path.dirname(__file__), "..", "tw_report.py")
        return subprocess.run(
            [sys.executable, script, *args], capture_output=True, text=True, check=False,
            env={**os.environ, "TW_STATE_STATE_DIR": self.tmp.name})

    def test_operational_printed_and_written_idempotently(self):
        first = self._run(self.path)
        self.assertEqual(first.returncode, 0)
        self.assertIn("MR !570 prête", first.stdout)
        report = os.path.join(self.tmp.name, "tw-site-manager--98e87142", "report-operational.md")
        content_first = open(report, encoding="utf-8").read()
        second = self._run(self.path)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(content_first, open(report, encoding="utf-8").read())

    def test_detailed_written_not_printed(self):
        result = self._run(self.path, "--kind", "detailed")
        self.assertEqual(result.returncode, 0)
        self.assertIn("written:", result.stdout)
        self.assertNotIn("## Phase 4", result.stdout)  # never printed in full
        report = os.path.join(self.tmp.name, "tw-site-manager--98e87142", "report-detailed.md")
        self.assertIn("## Phase 4", open(report, encoding="utf-8").read())

    def test_meetup_refused_with_ready_architecture(self):
        result = self._run(self.path, "--kind", "meetup")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not implemented", result.stderr)

    def test_unknown_kind_refused(self):
        self.assertEqual(self._run(self.path, "--kind", "podium").returncode, 2)


if __name__ == "__main__":
    unittest.main()
