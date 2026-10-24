#!/usr/bin/env python3
"""Unit tests of the M5 pilot (shadow-run MR analysis, RFC §11 M5).

All executors are STUBBED here — no gh call, no external effect. The real
shadow-run is performed outside the suite (evidence step).

Run: python3 -m unittest discover -s skills/graph_core/tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from skills.graph_core import (  # noqa: E402
    GraphScheduler, PlanMismatch, validate_graph_definition,
)
from skills.graph_core.pilot import (  # noqa: E402
    SandboxEffectDispatcher, build_mr_analysis_graph, collect_metrics,
    run_shadow_pilot,
)


def stub_executors(fail_first_fetch: bool = False, bad_evidence: bool = False):
    state = {"fetch_calls": 0}

    def fetch(node_id, node):
        state["fetch_calls"] += 1
        if fail_first_fetch and state["fetch_calls"] == 1:
            error = RuntimeError("transient network")
            error.failureClass = "technical"
            raise error
        return {"output": {"title": "feat(x): ok", "diffFiles": 3},
                "evidences": [{"evidenceId": "ev-fetch", "kind": "technical",
                               "exitCode": 0}], "artifactRefs": []}

    def analyze(node_id, node):
        return {"output": {"analysis": "static"}, "evidences": [
            {"evidenceId": "ev-analyze", "kind": "technical", "exitCode": 0}],
            "artifactRefs": []}

    def conventions(node_id, node):
        return {"output": {"conventionalCommit": True}, "evidences": [
            {"evidenceId": "ev-conventions", "kind": "technical", "exitCode": 0}],
            "artifactRefs": []}

    def report(node_id, node):
        return {"output": {"report": "built"}, "evidences": [
            {"evidenceId": "ev-report", "kind": "technical", "exitCode": 0}],
            "artifactRefs": []}

    def comment(node_id, node):
        if bad_evidence:
            # Non-conforming proof (exitCode 1) — I2 must refuse the completion.
            return {"output": {}, "evidences": [
                {"evidenceId": "ev-comment", "kind": "technical", "exitCode": 1}],
                "artifactRefs": []}
        return {"output": {"comment": "prepared (sandbox)"}, "evidences": [
            {"evidenceId": "ev-comment", "kind": "technical", "exitCode": 0}],
            "artifactRefs": []}

    return {"fetch-diff": fetch, "analyze-diff": analyze,
            "check-conventions": conventions, "build-report": report,
            "post-comment": comment}, state


class TestPilotGraph(unittest.TestCase):

    def test_graph_is_valid_and_shapes_are_rfc_conform(self):
        graph = build_mr_analysis_graph(49)
        self.assertEqual(validate_graph_definition(graph), [])
        post = next(n for n in graph["nodes"] if n["id"] == "post-comment")
        self.assertEqual(post["type"], "tool")  # I9: write only on tool nodes
        self.assertTrue(any(p.startswith("write:") for p in post["permissions"]))
        self.assertEqual(post["effectPolicy"]["mode"], "write")
        # effectPolicy omitted on read nodes (R-05) is LEGAL.
        fetch = next(n for n in graph["nodes"] if n["id"] == "fetch-diff")
        self.assertNotIn("effectPolicy", fetch)
        self.assertEqual(validate_graph_definition(
            {**graph, "nodes": [n for n in graph["nodes"]]}), [])


class TestShadowRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")
        self.lock_path = os.path.join(self.tmp.name, "run.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, pr_number=49, **kwargs):
        executors, state = stub_executors(**kwargs)
        result = run_shadow_pilot(pr_number, self.run_dir, self.lock_path,
                                  executors=executors)
        return result, state

    def test_happy_path_all_nodes_completed(self):
        result, _state = self._run()
        metrics = result["metrics"]
        self.assertEqual(metrics["nodes"]["completed"], 5)
        self.assertEqual(metrics["nodes"]["failed"], 0)
        self.assertEqual(metrics["nodes"]["blocked"], 0)
        self.assertEqual(metrics["nodes"]["successRate"], 1.0)
        # The write node went through the journaled effect protocol.
        self.assertEqual(metrics["effects"]["realExternalCalls"], 0)  # SANDBOX
        self.assertEqual(metrics["effects"]["simulatedDispatches"], 1)
        self.assertIn("confirmed", metrics["effects"]["phases"])
        self.assertEqual(metrics["humanInterventions"], 0)

    def test_reconcile_effect_uses_full_sequence(self):
        """§7.1: getBeforePost → reconcile classification → prepared AND
        dispatched records before the (simulated) emission."""
        result, _state = self._run()
        phases = result["metrics"]["effects"]["phases"]
        self.assertEqual(phases, ["prepared", "dispatched", "confirmed"])

    def test_transient_failure_retried_under_budget(self):
        result, _state = self._run(fail_first_fetch=True)
        metrics = result["metrics"]
        self.assertEqual(metrics["nodes"]["completed"], 5)  # recovered
        self.assertGreaterEqual(metrics["retries"], 1)
        fetch = metrics["perNode"]["fetch-diff"]
        self.assertEqual(fetch["attempts"], 2)  # initial + retry

    def test_i2_refusal_blocks_the_comment_node(self):
        result, _state = self._run(bad_evidence=True)
        metrics = result["metrics"]
        self.assertEqual(metrics["perNode"]["post-comment"]["status"], "blocked")
        self.assertEqual(metrics["nodes"]["completed"], 4)
        self.assertEqual(metrics["effects"]["simulatedDispatches"], 0)  # never dispatched

    def test_heartbeat_cabled_in_run_loop(self):
        """R-06: run() appends a heartbeat per scheduling decision —
        detection only, RFC §4.2."""
        self._run()
        events = [json.loads(line) for line in open(self.lock_path, encoding="utf-8")
                  if line.strip()]
        beats = [e for e in events if e.get("event") == "heartbeat"]
        self.assertGreaterEqual(len(beats), 5)  # one per node visited

    def test_runid_adopted_from_journal_when_file_lost(self):
        """R-03: a lost run-id file does NOT silently restart the run — the
        identity is adopted from the journal's records."""
        result, _state = self._run(pr_number=51)
        os.remove(os.path.join(self.run_dir, "run-id"))
        graph = build_mr_analysis_graph(51)
        scheduler = GraphScheduler(graph, self.run_dir, self.lock_path)
        scheduler.start()  # no explicit run_id → adopts from the journal
        self.assertEqual(scheduler.run_id, result["runId"])
        scheduler.release_lock()

    def test_explicit_runid_mismatch_refused_after_loss(self):
        """R-03: an EXPLICIT different run_id over a populated run-dir whose
        run-id file was lost is refused (PlanMismatch)."""
        self._run(pr_number=52)
        os.remove(os.path.join(self.run_dir, "run-id"))
        graph = build_mr_analysis_graph(52)
        scheduler = GraphScheduler(graph, self.run_dir, self.lock_path,
                                   run_id="run-someoneelse")
        with self.assertRaises(PlanMismatch):
            scheduler.start()

    def test_core_suite_unchanged(self):
        """The pilot adds nodes, never modifies the core's behavior: the
        graph validation refuses a mutated plan on resume (I6)."""
        self._run(pr_number=53)
        mutated = build_mr_analysis_graph(53)
        mutated["version"] = "1.0.1"
        scheduler = GraphScheduler(mutated, self.run_dir, self.lock_path)
        with self.assertRaises(PlanMismatch):
            scheduler.start()


class TestMetrics(unittest.TestCase):

    def test_collect_metrics_shape(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            run_dir = os.path.join(tmp.name, "run")
            lock = os.path.join(tmp.name, "run.lock")
            executors, _state = stub_executors()
            result = run_shadow_pilot(99, run_dir, lock, executors=executors)
            metrics = result["metrics"]
            for key in ("mode", "nodes", "perNode", "durationsSeconds",
                        "retries", "effects", "humanInterventions",
                        "journalProblems", "journalRecords"):
                self.assertIn(key, metrics)
            self.assertEqual(metrics["mode"], "shadow-run/sandbox")
            self.assertEqual(metrics["journalProblems"], [])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
