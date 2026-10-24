#!/usr/bin/env python3
"""Unit tests of the Execution Graph Core (stdlib unittest, RFC M1-M4).

Ported from the tw_state.py test style: fixtures + temp dirs, no network.
Run: python3 -m unittest discover -s skills/graph-core/tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from skills.graph_core import (  # noqa: E402
    EventLog, EvidenceStore, GraphScheduler, IllegalTransition, LockHeld,
    StateRepository, StaleCompletion, StaleGeneration, count_failure,
    invalidate_node, mark_transition, node_status, record_checksum,
    replay_records, stamp_record, validate_effect_record, validate_graph_definition,
    validate_node_definition, validate_node_execution, validate_schema_version,
    validate_transition_record,
)


def two_branch_graph():
    """S1 shape: 2 independent roots converging on a final node (RFC §2.1/F7)."""
    return {
        "schemaVersion": 1,
        "graphId": "test-graph-v1",
        "version": "1.0.0",
        "initialNodes": ["a", "b"],
        "nodes": [
            {"schemaVersion": 1, "id": "a", "type": "tool", "deps": [],
             "inputs": {}, "outputSchema": {"type": "object"},
             "permissions": ["read:fs"], "successCriteria": [],
             "evidencePolicy": {"required": ["exitCode"],
                                "freshness": {"inputFingerprint": False}},
             "failureBudgets": {"technical": 1, "quality": 2},
             "retryPolicy": {"maxAttempts": 2, "backoff": "none"},
             "timeoutSeconds": 60,
             "effectPolicy": {"mode": "read", "onUncertainOutcome": "block"}},
            {"schemaVersion": 1, "id": "b", "type": "tool", "deps": [],
             "inputs": {}, "outputSchema": {"type": "object"},
             "permissions": ["read:fs"], "successCriteria": [],
             "evidencePolicy": {"required": ["exitCode"],
                                "freshness": {"inputFingerprint": False}},
             "failureBudgets": {"technical": 1, "quality": 2},
             "retryPolicy": {"maxAttempts": 2, "backoff": "none"},
             "timeoutSeconds": 60,
             "effectPolicy": {"mode": "read", "onUncertainOutcome": "block"}},
            {"schemaVersion": 1, "id": "final", "type": "agent", "deps": ["a", "b"],
             "inputs": {}, "outputSchema": {"type": "object"},
             "permissions": ["read:fs"], "successCriteria": [],
             "evidencePolicy": {"required": ["structuredVerdict"],
                                "freshness": {"inputFingerprint": False}},
             "failureBudgets": {"technical": 1, "quality": 2},
             "retryPolicy": {"maxAttempts": 2, "backoff": "none"},
             "timeoutSeconds": 60,
             "effectPolicy": {"mode": "read", "onUncertainOutcome": "block"}},
        ],
    }


class TestContracts(unittest.TestCase):
    """M4 — the six formal contracts (RFC §2)."""

    def test_schema_version_window(self):
        self.assertEqual(validate_schema_version(1), [])
        self.assertEqual(validate_schema_version(0), ["schemaVersion must be >= 1"])
        self.assertTrue(validate_schema_version(2))  # beyond {N, N-1} → rejected

    def test_valid_graph(self):
        self.assertEqual(validate_graph_definition(two_branch_graph()), [])

    def test_initial_nodes_multi_root_required(self):
        graph = two_branch_graph()
        graph["initialNodes"] = ["final"]
        self.assertTrue(any("dependency-free" in p for p in validate_graph_definition(graph)))

    def test_cycle_rejected(self):
        graph = two_branch_graph()
        graph["nodes"][0]["deps"] = ["final"]  # a → final → a
        self.assertTrue(any("cycle" in p for p in validate_graph_definition(graph)))

    def test_agent_cannot_write(self):
        graph = two_branch_graph()
        graph["nodes"][2]["permissions"] = ["write:gitlab"]
        self.assertTrue(any("I9" in p for p in validate_graph_definition(graph)))
        graph["nodes"][2]["effectPolicy"]["mode"] = "write"
        self.assertTrue(any("I9" in p for p in validate_graph_definition(graph)))

    def test_write_requires_idempotency_key(self):
        graph = two_branch_graph()
        graph["nodes"][0]["effectPolicy"] = {"mode": "write",
                                             "onUncertainOutcome": "block"}
        self.assertTrue(any("idempotencyKey" in p for p in validate_graph_definition(graph)))

    def test_reserved_fields_rejected(self):
        graph = two_branch_graph()
        graph["filiation"] = {"parentGraphId": "x", "parentVersion": "1", "reason": "y"}
        self.assertTrue(any("RESERVED for M7+" in p for p in validate_graph_definition(graph)))
        graph = two_branch_graph()
        graph["nodes"][0]["resourcePolicy"] = {"concurrencyKey": "r1"}
        self.assertTrue(any("RESERVED for M7+" in p for p in validate_graph_definition(graph)))

    def test_failure_budgets_shape(self):
        node = two_branch_graph()["nodes"][0]
        node["failureBudgets"]["invalidEvidence"] = 3
        self.assertTrue(any("never-auto-resolved" in p
                            for p in validate_node_definition(node, 0)))

    def test_node_execution_contract(self):
        execution = {"runId": "r", "nodeId": "a", "attempt": 1, "status": "running",
                     "inputFingerprint": "sha256:abc",
                     "failureCounts": {"technical": 0, "quality": 0,
                                       "invalidEvidence": 0, "permission": 0}}
        self.assertEqual(validate_node_execution(execution), [])
        execution["failureCounts"].pop("quality")
        self.assertTrue(validate_node_execution(execution))

    def test_transition_record_contract(self):
        record = stamp_record({"transitionId": "t1", "runId": "r", "nodeId": "a",
                               "attempt": 1, "kind": "transition", "from": "pending",
                               "to": "running", "generationToken": "gen-1",
                               "timestamp": "2026-10-24T00:00:00+00:00"})
        self.assertEqual(validate_transition_record(record), [])
        broken = dict(record)
        broken.pop("generationToken")
        self.assertTrue(validate_transition_record(broken))

    def test_effect_record_contract(self):
        record = {"effectId": "e1", "idempotencyKey": "k1", "classification": "reconcile",
                  "phase": "prepared", "requestedAt": "2026-10-24T00:00:00+00:00"}
        self.assertEqual(validate_effect_record(record), [])


class TestTransitionEngine(unittest.TestCase):
    """M1 — legal transitions, invalidation, budgets, replay (RFC §3)."""

    def setUp(self):
        self.state = {"runId": "r", "nodeExecutions": {}}

    def test_legal_path(self):
        mark_transition(self.state, "a", "running", timestamp="t0")
        self.assertEqual(node_status(self.state, "a"), "running")
        mark_transition(self.state, "a", "completed", timestamp="t1")
        self.assertEqual(node_status(self.state, "a"), "completed")

    def test_completed_is_terminal(self):
        mark_transition(self.state, "a", "running")
        mark_transition(self.state, "a", "completed")
        with self.assertRaises(IllegalTransition):
            mark_transition(self.state, "a", "pending")  # I1 — not a transition

    def test_invalid_via_dedicated_operation(self):
        mark_transition(self.state, "a", "running")
        mark_transition(self.state, "a", "completed")
        outcome = invalidate_node(self.state, "a", "fingerprint divergent",
                                  timestamp="t2")
        self.assertEqual(outcome["to"], "pending")
        self.assertEqual(node_status(self.state, "a"), "pending")
        self.assertEqual(self.state["invalidations"]["a"], "t2")

    def test_running_invalidated_becomes_cancelled(self):
        mark_transition(self.state, "a", "running")
        outcome = invalidate_node(self.state, "a", "upstream invalidated",
                                  timestamp="t3")
        self.assertEqual(outcome["to"], "cancelled")

    def test_stale_completion_rejected(self):
        mark_transition(self.state, "a", "running", timestamp="t0")
        self.state.setdefault("invalidations", {})["upstream"] = "t1"  # after t0
        with self.assertRaises(StaleCompletion):
            mark_transition(self.state, "a", "completed", timestamp="t2",
                            ancestors=["upstream"])

    def test_fresh_completion_accepted(self):
        mark_transition(self.state, "a", "running", timestamp="t0")
        self.state.setdefault("invalidations", {})["upstream"] = "t-1"  # before start
        mark_transition(self.state, "a", "completed", timestamp="t2",
                        ancestors=["upstream"])
        self.assertEqual(node_status(self.state, "a"), "completed")

    def test_failure_counts_independent(self):
        count_failure(self.state, "a", "technical")
        count_failure(self.state, "a", "quality")
        counts = self.state["nodeExecutions"]["a"]["failureCounts"]
        self.assertEqual((counts["technical"], counts["quality"]), (1, 1))
        self.assertEqual(counts["invalidEvidence"], 0)

    def test_replay_rejects_foreign_generation(self):
        records = [
            {"transitionId": "t1", "generationToken": "gen-1"},
            {"transitionId": "t2", "generationToken": "gen-9"},  # foreign
            {"transitionId": "t1", "generationToken": "gen-1"},  # duplicate
        ]
        result = replay_records(records, ["gen-1"])
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["rejected"]), 1)


class TestPersistence(unittest.TestCase):
    """M2 — EventLog checksums, incomplete tail, projection, evidence markers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = self.tmp.name
        self.log = EventLog(os.path.join(self.run_dir, "journal.jsonl"))
        self.base = {"transitionId": "t1", "runId": "r", "nodeId": "a", "attempt": 1,
                     "kind": "transition", "from": "pending", "to": "running",
                     "generationToken": "gen-1", "timestamp": "2026-10-24T00:00:00+00:00"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_read_with_checksum(self):
        stamped = self.log.append(self.base)
        records, problems = self.log.read()
        self.assertEqual(len(records), 1)
        self.assertEqual(problems, [])
        self.assertEqual(records[0]["checksum"], record_checksum(self.base))

    def test_incomplete_tail_ignored(self):
        self.log.append(self.base)
        with open(self.log.path, "a", encoding="utf-8") as handle:
            handle.write('{"transitionId": "t2", "runId": "r", "trunc')  # torn write
        records, problems = self.log.read()
        self.assertEqual(len(records), 1)  # the valid record survives
        self.assertEqual(len(problems), 1)
        self.assertIn("incomplete tail ignored", problems[0])

    def test_corrupted_checksum_never_confirmed(self):
        self.log.append(self.base)
        with open(self.log.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({**self.base, "transitionId": "t2",
                                     "checksum": "0" * 64}) + "\n")
        records, problems = self.log.read()
        self.assertEqual(len(records), 1)
        self.assertTrue(any("checksum mismatch" in p for p in problems))

    def test_replay_rejects_foreign_generation(self):
        self.log.append(self.base)
        self.log.append({**self.base, "transitionId": "t2",
                         "generationToken": "gen-foreign"})
        result = self.log.replay(["gen-1"])
        self.assertEqual([r["transitionId"] for r in result["applied"]], ["t1"])
        self.assertEqual([r["transitionId"] for r in result["rejected"]], ["t2"])

    def test_repository_projection_rebuild_idempotent(self):
        repo = StateRepository(os.path.join(self.run_dir, "snapshot.json"))
        self.log.append(self.base)
        self.log.append({**self.base, "transitionId": "t2", "to": "completed"})
        state = repo.rebuild("r", self.log, ["gen-1"])
        self.assertEqual(node_status(state, "a"), "completed")
        again = repo.rebuild("r", self.log, ["gen-1"])
        self.assertEqual(again["projectedTransitionIds"], state["projectedTransitionIds"])

    def test_snapshot_atomic_write(self):
        repo = StateRepository(os.path.join(self.run_dir, "snapshot.json"))
        repo.save({"runId": "r"})
        self.assertFalse(os.path.exists(repo.path + ".tmp"))
        self.assertEqual(repo.load()["runId"], "r")

    def test_evidence_invalidation_marker(self):
        store = EvidenceStore(os.path.join(self.run_dir, "evidences.jsonl"),
                              os.path.join(self.run_dir, "evidence-invalidations.jsonl"))
        store.append({"evidenceId": "e1", "kind": "technical", "exitCode": 0})
        self.assertEqual(len(store.list_valid()), 1)
        store.mark_invalidated("e1", "fingerprint divergent", "2026-10-24T00:00:00Z")
        self.assertEqual(len(store.list_valid()), 0)
        self.assertEqual(len(store.list_all()), 1)  # history preserved — never deleted


class TestSchedulerScenarios(unittest.TestCase):
    """M3 + RFC §10 scenarios S1/S2/S3/S6 (automated, temp state)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")
        self.lock_path = os.path.join(self.tmp.name, "run.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def _scheduler(self, graph=None):
        scheduler = GraphScheduler(graph or two_branch_graph(), self.run_dir,
                                   self.lock_path)
        scheduler.start()
        return scheduler

    def _ok_executor(self):
        def executor(node_id, node):
            return {"output": {"ok": True},
                    "evidences": [{"evidenceId": f"e-{node_id}",
                                   "kind": "technical", "exitCode": 0}],
                    "artifactRefs": []}
        return executor

    def test_s1_convergence_after_all_deps(self):
        scheduler = self._scheduler()
        results = scheduler.run(self._ok_executor())
        self.assertEqual(len(results), 3)
        records, _ = scheduler.log.read()
        final_running = next(r for r in records
                             if r["nodeId"] == "final" and r["to"] == "running")
        for dep in ("a", "b"):
            dep_completed = [r for r in records if r["nodeId"] == dep and r["to"] == "completed"]
            self.assertTrue(dep_completed)
            self.assertTrue(dep_completed[0]["timestamp"] <= final_running["timestamp"])

    def test_s2_resume_skips_fresh_completed(self):
        scheduler = self._scheduler()
        scheduler.run(self._ok_executor(), max_nodes=2)  # a + b complete, crash before final
        scheduler.release_lock()
        # New session resumes the same run (different scheduler instance).
        resumed = self._scheduler()
        resumed.run(self._ok_executor())
        records, _ = resumed.log.read()
        reruns = [r for r in records if r["from"] == "pending" and r["to"] == "running"
                  and r["nodeId"] in ("a", "b") and r["generationToken"] != records[0]["generationToken"]]
        self.assertEqual(reruns, [])  # 0 re-execution of fresh completed nodes
        self.assertEqual(node_status(resumed._state(), "final"), "completed")

    def test_s3_transitive_invalidation_marks_never_deletes(self):
        graph = two_branch_graph()
        graph["nodes"][2]["deps"] = ["a"]  # final depends on a only (simpler)
        scheduler = self._scheduler(graph)
        scheduler.run(self._ok_executor())  # executes a, b, final (b has no dependant)
        scheduler.invalidate("a", "code changed upstream",
                             fingerprint_divergence="sha256:xxx")
        state = scheduler._state()
        self.assertEqual(node_status(state, "a"), "pending")
        self.assertEqual(node_status(state, "final"), "pending")  # transitive
        evidences = scheduler.evidence.list_all()
        self.assertEqual(len(evidences), 3)  # marked, NOT deleted (F2)
        valid_ids = {e["evidenceId"] for e in scheduler.evidence.list_valid()}
        self.assertEqual(valid_ids, {"e-b"})  # b is untouched (not a descendant of a)
        records, _ = scheduler.log.read()
        self.assertTrue(any(r["kind"] == "invalidation" for r in records))

    def test_s6_mutual_exclusion_and_fencing(self):
        scheduler = self._scheduler()
        with self.assertRaises(LockHeld):
            GraphScheduler(two_branch_graph(), self.run_dir,
                           self.lock_path).start()  # second session refused
        # A stale owner whose lock file was overwritten is rejected by the ENGINE.
        with open(self.lock_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"generationToken": "gen-NEW",
                                     "pid": 999, "session": "other"}) + "\n")
        with self.assertRaises(StaleGeneration):
            scheduler._journal("transition", "a", 1, "running")
        scheduler.release_lock()

    def test_fencing_same_critical_section(self):
        scheduler = self._scheduler()
        scheduler._lock_handle.seek(0)
        payload = json.loads(scheduler._lock_handle.read())
        self.assertIn("generationToken", payload)  # token lives IN the lock file (F6)
        scheduler.release_lock()


if __name__ == "__main__":
    unittest.main()
