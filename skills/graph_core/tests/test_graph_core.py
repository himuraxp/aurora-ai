#!/usr/bin/env python3
"""Unit tests of the Execution Graph Core (stdlib unittest, RFC M1-M4).

Covers the reviewer's test axes T-01 (journal-revision staleness, not
timestamps), T-02 (post-rebuild assertions: the projection carries
evidenceIds and recovery works) and T-03 (crash during a node, snapshot loss
with an intact journal, budget exhaustion, I2 refusals, PlanMismatch,
S5/S7 through a fake dispatcher, same-revision invalidation, duplicated
deps).

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
    EffectDispatcher, EventLog, EvidenceStore, GraphScheduler, LockHeld,
    PlanMismatch, StateRepository, StaleCompletion, StaleGeneration,
    budget_exhausted, compute_input_fingerprint, count_failure,
    derive_classification, invalidate_node, mark_transition, node_status,
    record_checksum, repin_orphan_running, replay_records, stamp_record,
    validate_evidence_record, validate_effect_record,
    validate_graph_definition, validate_node_definition,
    validate_node_execution, validate_schema_version,
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
            _node("a", "tool", []),
            _node("b", "tool", []),
            _node("final", "agent", ["a", "b"]),
        ],
    }


def _node(node_id: str, node_type: str, deps: list) -> dict:
    return {
        "schemaVersion": 1, "id": node_id, "type": node_type, "deps": deps,
        "inputs": {}, "outputSchema": {"type": "object"},
        "permissions": ["read:fs"], "successCriteria": [],
        "evidencePolicy": {"required": ["exitCode"],
                           "freshness": {"inputFingerprint": False}},
        "failureBudgets": {"technical": 1, "quality": 2},
        "retryPolicy": {"maxAttempts": 2, "backoff": "none"},
        "timeoutSeconds": 60,
        "effectPolicy": {"mode": "read", "onUncertainOutcome": "block"},
    }


def _write_node(node_id: str, reconciliation: str = "getBeforePost",
                classification: str | None = None) -> dict:
    node = _node(node_id, "tool", [])
    node["permissions"] = ["write:gitlab"]
    policy = {"mode": "write", "idempotencyKey": f"idem-{node_id}",
              "reconciliation": reconciliation, "onUncertainOutcome": "block"}
    if classification:
        policy["classification"] = classification
    node["effectPolicy"] = policy
    return node


class RecordingDispatcher(EffectDispatcher):
    """Fake dispatcher (review F-19): records calls, optional scripted
    behavior — crash simulation between phases (S5/S7)."""

    def __init__(self, behavior="confirmed"):
        self.calls = []
        self.behavior = behavior

    def dispatch(self, node_id, node, idempotency_key):
        self.calls.append((node_id, idempotency_key))
        if self.behavior == "crash":
            raise RuntimeError("network down after emission")
        return {"outcome": self.behavior, "evidenceRef": "ev-out"}


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

    def test_duplicated_deps_do_not_fake_a_cycle(self):
        graph = two_branch_graph()
        graph["nodes"][2]["deps"] = ["a", "a", "b"]  # review F-17
        self.assertEqual(validate_graph_definition(graph), [])

    def test_agent_cannot_write(self):
        graph = two_branch_graph()
        graph["nodes"][2]["permissions"] = ["write:gitlab"]
        self.assertTrue(any("I9" in p for p in validate_graph_definition(graph)))

    def test_write_effect_reserved_to_tool_nodes(self):
        node = _node("x", "agent", [])
        node["permissions"] = ["write:gitlab"]
        node["effectPolicy"] = {"mode": "write", "idempotencyKey": "k",
                                "reconciliation": "getBeforePost",
                                "onUncertainOutcome": "block"}
        self.assertTrue(any("reserved to tool nodes" in p
                            for p in validate_node_definition(node, 0)))  # F-19/I9

    def test_write_requires_idempotency_key(self):
        node = _node("x", "tool", [])
        node["effectPolicy"] = {"mode": "write", "onUncertainOutcome": "block"}
        self.assertTrue(any("idempotencyKey" in p for p in validate_node_definition(node, 0)))

    def test_reserved_fields_rejected(self):
        graph = two_branch_graph()
        graph["filiation"] = {"parentGraphId": "x", "parentVersion": "1", "reason": "y"}
        self.assertTrue(any("RESERVED for M7+" in p for p in validate_graph_definition(graph)))
        graph = two_branch_graph()
        graph["nodes"][0]["resourcePolicy"] = {"concurrencyKey": "r1"}
        self.assertTrue(any("RESERVED for M7+" in p for p in validate_graph_definition(graph)))

    def test_failure_budgets_shape(self):
        node = _node("x", "tool", [])
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

    def test_evidence_record_i2_guards(self):
        ok = {"evidenceId": "e1", "kind": "technical", "exitCode": 0}
        self.assertEqual(validate_evidence_record(ok, required=["exitCode"]), [])
        failed = {"evidenceId": "e1", "kind": "technical", "exitCode": 1}
        self.assertTrue(any("exitCode == 0" in p for p in
                            validate_evidence_record(failed, required=["exitCode"])))  # I2
        no_artifact = {"evidenceId": "e2", "kind": "technical", "exitCode": 0}
        self.assertTrue(any("artifactRef" in p for p in
                            validate_evidence_record(no_artifact, required=["artifact"])))  # F17
        no_approval = {"evidenceId": "e3", "kind": "authorization"}
        self.assertTrue(any("approvalRef" in p for p in
                            validate_evidence_record(no_approval, required=["humanApproval"])))
        no_verdict = {"evidenceId": "e4", "kind": "semantic"}
        self.assertTrue(any("structuredVerdict" in p for p in
                            validate_evidence_record(no_verdict, required=["structuredVerdict"])))


class TestTransitionEngine(unittest.TestCase):
    """M1 — legal transitions, invalidation, budgets, replay (RFC §3)."""

    def setUp(self):
        self.state = {"runId": "r", "nodeExecutions": {}}

    def test_legal_path(self):
        mark_transition(self.state, "a", "running", started_revision=1)
        self.assertEqual(node_status(self.state, "a"), "running")
        mark_transition(self.state, "a", "completed", started_revision=2,
                        invalidation_revisions={}, ancestors=[])
        self.assertEqual(node_status(self.state, "a"), "completed")

    def test_completed_is_terminal(self):
        mark_transition(self.state, "a", "running", started_revision=1)
        mark_transition(self.state, "a", "completed", started_revision=2)
        with self.assertRaises(Exception) as ctx:
            mark_transition(self.state, "a", "pending")  # I1 — not a transition
        self.assertIn("illegal transition", str(ctx.exception))

    def test_invalid_via_dedicated_operation(self):
        mark_transition(self.state, "a", "running", started_revision=1)
        mark_transition(self.state, "a", "completed", started_revision=2)
        outcome = invalidate_node(self.state, "a", "fingerprint divergent",
                                  invalidation_revision=3)
        self.assertEqual(outcome["to"], "pending")
        self.assertEqual(node_status(self.state, "a"), "pending")
        self.assertEqual(self.state["invalidations"]["a"], 3)  # journal REVISION (T-01)

    def test_running_invalidated_becomes_cancelled(self):
        mark_transition(self.state, "a", "running", started_revision=1)
        outcome = invalidate_node(self.state, "a", "upstream invalidated",
                                  invalidation_revision=2)
        self.assertEqual(outcome["to"], "cancelled")

    def test_failed_and_blocked_invalidation_refiles_pending(self):
        mark_transition(self.state, "a", "running", started_revision=1)
        mark_transition(self.state, "a", "failed", started_revision=2)
        outcome = invalidate_node(self.state, "a", "scope", invalidation_revision=3)
        self.assertEqual(outcome["to"], "pending")  # review F-12
        mark_transition(self.state, "b", "running", started_revision=1)
        mark_transition(self.state, "b", "blocked", started_revision=2)
        outcome = invalidate_node(self.state, "b", "scope", invalidation_revision=3)
        self.assertEqual(outcome["to"], "pending")  # review F-12

    def test_stale_completion_rejected_by_revision_even_same_second(self):
        """T-01: the staleness check uses JOURNAL REVISIONS — two records
        sharing the same wall-clock second are still ordered."""
        mark_transition(self.state, "a", "running", started_revision=5)
        self.state.setdefault("invalidations", {})["upstream"] = 7  # AFTER start
        with self.assertRaises(StaleCompletion):
            mark_transition(self.state, "a", "completed", started_revision=8,
                            invalidation_revisions=self.state["invalidations"],
                            ancestors=["upstream"])

    def test_fresh_completion_accepted(self):
        mark_transition(self.state, "a", "running", started_revision=5)
        self.state.setdefault("invalidations", {})["upstream"] = 3  # BEFORE start
        mark_transition(self.state, "a", "completed", started_revision=8,
                        invalidation_revisions=self.state["invalidations"],
                        ancestors=["upstream"])
        self.assertEqual(node_status(self.state, "a"), "completed")

    def test_failure_counts_independent(self):
        count_failure(self.state, "a", "technical")
        count_failure(self.state, "a", "quality")
        counts = self.state["nodeExecutions"]["a"]["failureCounts"]
        self.assertEqual((counts["technical"], counts["quality"]), (1, 1))
        self.assertEqual(counts["invalidEvidence"], 0)

    def test_budget_exhausted(self):
        node = _node("a", "tool", [])
        node["failureBudgets"] = {"technical": 2, "quality": 2}
        state = {"runId": "r", "nodeExecutions": {}}
        count_failure(state, "a", "technical")
        self.assertFalse(budget_exhausted(node, state, "a", "technical"))
        count_failure(state, "a", "technical")
        self.assertTrue(budget_exhausted(node, state, "a", "technical"))
        # Classes with NO budget are always "exhausted" (blocked — I8).
        self.assertTrue(budget_exhausted(node, state, "a", "invalidEvidence"))
        self.assertTrue(budget_exhausted(node, state, "a", "permission"))

    def test_repin_orphan_running(self):
        mark_transition(self.state, "a", "running", started_revision=1)
        outcome = repin_orphan_running(self.state, "a")
        self.assertEqual((outcome["from"], outcome["to"]), ("running", "pending"))
        self.assertEqual(node_status(self.state, "a"), "pending")
        self.assertEqual(self.state["nodeExecutions"]["a"]["attempt"], 2)
        self.assertNotIn("startedRevision", self.state["nodeExecutions"]["a"])
        # Non-running nodes are skipped, never corrupted.
        outcome = repin_orphan_running(self.state, "a")
        self.assertTrue(outcome["skipped"])

    def test_replay_rejects_foreign_generation_and_filters_run_id(self):
        records = [
            {"transitionId": "t1", "generationToken": "gen-1", "runId": "r1"},
            {"transitionId": "t2", "generationToken": "gen-9", "runId": "r1"},  # foreign
            {"transitionId": "t1", "generationToken": "gen-1", "runId": "r1"},  # duplicate
            {"transitionId": "t3", "generationToken": "gen-1", "runId": "r2"},  # other run
        ]
        result = replay_records(records, ["gen-1"], run_id="r1")
        self.assertEqual([r["transitionId"] for r in result["applied"]], ["t1"])
        self.assertEqual([r["transitionId"] for r in result["rejected"]], ["t2"])


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

    def test_append_and_read_with_checksum_and_revisions(self):
        stamped = self.log.append(self.base)
        records, problems = self.log.read()
        self.assertEqual(len(records), 1)
        self.assertEqual(problems, [])
        self.assertEqual(records[0]["checksum"], record_checksum(self.base))
        self.assertEqual(records[0]["_revision"], 1)  # journal revision (F-11)

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
        result = self.log.replay(["gen-1"], run_id="r")
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

    def test_projection_carries_evidence_and_artifact_refs(self):
        """T-02 (F-05): after a rebuild the guards still see evidenceIds and
        output refs — the projection is faithful."""
        repo = StateRepository(os.path.join(self.run_dir, "snapshot.json"))
        self.log.append({**self.base, "transitionId": "t1", "to": "running"})
        self.log.append({**self.base, "transitionId": "t2", "to": "completed",
                         "payload": {"evidenceIds": ["e-1"],
                                     "outputArtifactRefs": ["/tmp/out.json"]}})
        state = repo.rebuild("r", self.log, ["gen-1"])
        entry = state["nodeExecutions"]["a"]
        self.assertEqual(entry["evidenceIds"], ["e-1"])
        self.assertEqual(entry["outputArtifactRefs"], ["/tmp/out.json"])
        self.assertEqual(entry["failureCounts"],
                         {"technical": 0, "quality": 0,
                          "invalidEvidence": 0, "permission": 0})

    def test_projection_effect_phase_never_corrupts_status(self):
        repo = StateRepository(os.path.join(self.run_dir, "snapshot.json"))
        self.log.append({**self.base, "transitionId": "t1", "to": "running"})
        self.log.append({**self.base, "transitionId": "t2", "kind": "effect",
                         "to": "dispatched",
                         "payload": {"effectPhase": "dispatched",
                                     "idempotencyKey": "k"}})
        state = repo.rebuild("r", self.log, ["gen-1"])
        entry = state["nodeExecutions"]["a"]
        self.assertEqual(entry["status"], "running")  # NOT 'dispatched' (I1)
        self.assertEqual(entry["effectPhase"], "dispatched")

    def test_projection_affected_statuses_faithful(self):
        repo = StateRepository(os.path.join(self.run_dir, "snapshot.json"))
        self.log.append({**self.base, "transitionId": "t1", "to": "running"})
        self.log.append({**self.base, "transitionId": "t2", "kind": "invalidation",
                         "to": "cancelled",
                         "payload": {"affected": [{"nodeId": "down",
                                                   "to": "cancelled"}]}})
        state = repo.rebuild("r", self.log, ["gen-1"])
        self.assertEqual(node_status(state, "down"), "cancelled")  # faithful (F-05)

    def test_projection_replays_attempt_after_retry(self):
        """R-01: each record carries its attempt — a rebuilt projection is
        faithful after a re-filed retry."""
        repo = StateRepository(os.path.join(self.run_dir, "snapshot.json"))
        self.log.append({**self.base, "transitionId": "t1", "to": "running",
                         "attempt": 1})
        self.log.append({**self.base, "transitionId": "t2", "to": "failed",
                         "attempt": 1,
                         "payload": {"failureClass": "technical"}})
        self.log.append({**self.base, "transitionId": "t3", "to": "pending",
                         "from": "failed", "attempt": 2})
        self.log.append({**self.base, "transitionId": "t4", "to": "running",
                         "attempt": 2})
        state = repo.rebuild("r", self.log, ["gen-1"])
        self.assertEqual(state["nodeExecutions"]["a"]["attempt"], 2)  # faithful

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

    def test_evidence_marker_idempotent_and_journal_reapplication(self):
        """F-13: markers are idempotent and re-appliable from the journal."""
        store = EvidenceStore(os.path.join(self.run_dir, "evidences.jsonl"),
                              os.path.join(self.run_dir, "evidence-invalidations.jsonl"))
        store.append({"evidenceId": "e1", "kind": "technical", "exitCode": 0})
        first = store.mark_invalidated("e1", "r1", "now")
        second = store.mark_invalidated("e1", "r2", "now2")
        self.assertEqual(second, {})  # idempotent
        self.assertTrue(first)
        self.assertEqual(store.reapply_from_journal(["e1"], "replay", "now3"), 0)
        self.assertEqual(store.reapply_from_journal(["e2"], "replay", "now3"), 1)


class TestSchedulerScenarios(unittest.TestCase):
    """M3 + RFC §10 scenarios (automated, temp state)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")
        self.lock_path = os.path.join(self.tmp.name, "run.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def _scheduler(self, graph=None, **kwargs):
        scheduler = GraphScheduler(graph or two_branch_graph(), self.run_dir,
                                   self.lock_path, **kwargs)
        scheduler.start()
        return scheduler

    @staticmethod
    def _ok_executor():
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
            # Journal REVISION ordering (T-01): the convergence node starts
            # only after BOTH deps completed (I4).
            self.assertTrue(dep_completed[0]["_revision"] < final_running["_revision"])

    def test_s2_resume_skips_fresh_completed(self):
        scheduler = self._scheduler()
        scheduler.run(self._ok_executor(), max_nodes=2)  # a + b complete, "crash" before final
        scheduler.release_lock()
        resumed = self._scheduler()  # new session, new generation
        resumed.run(self._ok_executor())
        records, _ = resumed.log.read()
        first_token = records[0]["generationToken"]
        reruns = [r for r in records
                  if r["from"] == "pending" and r["to"] == "running"
                  and r["nodeId"] in ("a", "b")
                  and r["generationToken"] != first_token]
        self.assertEqual(reruns, [])  # 0 re-execution of fresh completed nodes
        self.assertEqual(node_status(resumed._state(), "final"), "completed")

    def test_s2b_crash_during_node_orphan_running_re_pinned(self):
        """T-03 (F-03): a crash while a node is running leaves an orphan
        `running` — the next session re-pins it to pending (journaled as
        kind=invalidation) and the node re-executes."""
        scheduler = self._scheduler()
        scheduler.run(self._ok_executor(), max_nodes=1)  # a completes
        # Crash during b: journal the running record, then "die" (release).
        state = scheduler._state()
        mark_transition(state, "b", "running", started_revision=scheduler._next_revision())
        scheduler._journal("transition", "b", 1, "running", from_status="pending",
                           payload={"executor": "crashed-session"})
        scheduler.repository.save(state)
        scheduler.release_lock()
        resumed = self._scheduler()
        resumed.run(self._ok_executor())
        records, _ = resumed.log.read()
        repins = [r for r in records if r["kind"] == "invalidation"
                  and r["nodeId"] == "b" and r["to"] == "pending"
                  and r["from"] == "running"]
        self.assertEqual(len(repins), 1)  # §5.3 re-pin journalisé
        self.assertEqual(node_status(resumed._state(), "b"), "completed")

    def test_s2c_snapshot_loss_with_intact_journal_recovers(self):
        """T-03 (F-01): the snapshot is a projection — deleting it must NOT
        lose the run: the generation chain lives in the LOCK FILE and the
        journal replays."""
        scheduler = self._scheduler()
        scheduler.run(self._ok_executor())
        os.remove(os.path.join(self.run_dir, "snapshot.json"))
        scheduler.release_lock()
        resumed = self._scheduler()
        state = resumed._state()
        for node_id in ("a", "b", "final"):
            self.assertEqual(node_status(state, node_id), "completed",
                             "recovery from the journal + lockfile chain failed")
        results = resumed.run(self._ok_executor())
        self.assertEqual(results, [])  # nothing re-executed

    def test_s2d_mutated_plan_refused(self):
        """T-03 (F-09): a run is immutable — resuming with a different plan
        is refused (PlanMismatch)."""
        scheduler = self._scheduler()
        scheduler.release_lock()
        mutated = two_branch_graph()
        mutated["version"] = "1.0.1"
        with self.assertRaises(PlanMismatch):
            self._scheduler(mutated)
        # A different runId on the same run-dir is refused too (F-14).
        with self.assertRaises(PlanMismatch):
            self._scheduler(run_id="run-somethingelse")

    def test_invalidate_never_executed_node_does_not_crash(self):
        """R-02: an invalidation requested on a node with no execution entry
        is traced, never a KeyError."""
        scheduler = self._scheduler()
        outcome = scheduler.invalidate("never-ran", "scope test")
        self.assertTrue(outcome.get("skipped"))  # nothing consumable to invalidate

    def test_s3_transitive_invalidation_marks_never_deletes(self):
        graph = two_branch_graph()
        graph["nodes"][2]["deps"] = ["a"]  # final depends on a only (simpler)
        scheduler = self._scheduler(graph)
        scheduler.run(self._ok_executor())
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
        invalidation = next(r for r in records if r["kind"] == "invalidation")
        self.assertIn("e-a", invalidation["payload"]["invalidatedEvidenceIds"])
        self.assertIn({"nodeId": "final", "to": "pending"},
                      invalidation["payload"]["affected"])

    def test_s6_mutual_exclusion_and_fencing(self):
        scheduler = self._scheduler()
        with self.assertRaises(LockHeld):
            GraphScheduler(two_branch_graph(), self.run_dir,
                           self.lock_path).start()  # second session refused
        # A stale owner whose lock was recovered is rejected by the ENGINE.
        with open(self.lock_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": "acquire", "generationToken": "gen-NEW",
                                     "pid": 999, "session": "other"}) + "\n")
        with self.assertRaises(StaleGeneration):
            scheduler._journal("transition", "a", 1, "running", from_status="pending")
        scheduler.release_lock()

    def test_s6b_generation_chain_survives_in_lockfile(self):
        scheduler = self._scheduler()
        chain = scheduler.generation_chain()
        self.assertEqual(chain, [scheduler.generationToken])  # token lives IN the lock (F6)
        scheduler.release_lock()
        second = self._scheduler()
        self.assertEqual(len(second.generation_chain()), 2)  # append-only chain (F-01)
        second.release_lock()

    def test_technical_budget_exhausted_is_terminal(self):
        """T-03 (I8): once the technical budget is exhausted the node stays
        failed — no further attempt is ever filed."""
        graph = two_branch_graph()
        graph["nodes"][0]["failureBudgets"] = {"technical": 1, "quality": 2}

        def failing_executor(node_id, node):
            raise RuntimeError("boom")

        scheduler = self._scheduler(graph)
        results = scheduler.run(failing_executor)
        self.assertEqual(results[0]["status"], "failed")
        scheduler.run(failing_executor)  # second pass: no retry (budget = 1)
        records, _ = scheduler.log.read()
        runnings = [r for r in records if r["nodeId"] == "a" and r["to"] == "running"]
        self.assertEqual(len(runnings), 1)
        self.assertEqual(node_status(scheduler._state(), "a"), "failed")

    def test_technical_retry_under_remaining_budget(self):
        graph = two_branch_graph()
        graph["nodes"][0]["failureBudgets"] = {"technical": 2, "quality": 2}
        calls = {"n": 0}

        def flaky_executor(node_id, node):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return {"output": {"ok": True},
                    "evidences": [{"evidenceId": f"e-{node_id}",
                                   "kind": "technical", "exitCode": 0}],
                    "artifactRefs": []}

        scheduler = self._scheduler(graph)
        scheduler.run(flaky_executor)   # first pass: a fails (transient), b runs
        scheduler.run(flaky_executor)   # second pass: a re-filed under budget, completes
        self.assertEqual(node_status(scheduler._state(), "a"), "completed")
        records, _ = scheduler.log.read()
        retries = [r for r in records if r["nodeId"] == "a"
                   and r["to"] == "pending" and r["from"] == "failed"]
        self.assertEqual(len(retries), 1)  # re-filed once under remaining budget

    def test_i2_refuses_nonconforming_evidence(self):
        """T-03 (F-04): exitCode 1 never completes; the proof is never
        persisted as valid; the failure class is invalidEvidence → blocked."""
        graph = two_branch_graph()
        scheduler = self._scheduler(graph)

        def bad_executor(node_id, node):
            return {"output": {}, "evidences": [{"evidenceId": "e-bad",
                                                 "kind": "technical",
                                                 "exitCode": 1}],
                    "artifactRefs": []}

        result = scheduler.run(bad_executor)
        self.assertEqual(result[0]["status"], "blocked")
        self.assertEqual(node_status(scheduler._state(), "a"), "blocked")
        self.assertEqual(scheduler.evidence.list_valid(), [])  # never persisted valid
        entry = scheduler._state()["nodeExecutions"]["a"]
        self.assertEqual(entry["failureCounts"]["invalidEvidence"], 1)

    def test_i2_refuses_missing_evidence(self):
        graph = two_branch_graph()
        scheduler = self._scheduler(graph)
        result = scheduler.run(lambda node_id, node: {"output": {}, "evidences": [],
                                                      "artifactRefs": []})
        self.assertEqual(result[0]["status"], "blocked")  # required non-empty, evidence empty

    def test_engine_output_satisfies_node_execution_contract(self):
        """The projected entries satisfy the NodeExecution contract (§2.3)."""
        scheduler = self._scheduler()
        scheduler.run(self._ok_executor())
        for node_id, entry in scheduler._state()["nodeExecutions"].items():
            self.assertEqual(validate_node_execution(entry), [], node_id)

    def test_s5_s7_reconcile_effect_crash_blocks_without_rejeu(self):
        """T-03 (F-08/F-19, S5/S7): a crash between `dispatched` and the real
        emission leaves an UNCERTAIN effect — the node is blocked, never
        re-dispatched, and the human intervention is journalized."""
        graph = two_branch_graph()
        graph["nodes"][0] = _write_node("a", reconciliation="getBeforePost")
        graph["nodes"][2]["deps"] = ["a"]  # keep final reachable
        dispatcher = RecordingDispatcher(behavior="crash")
        scheduler = self._scheduler(graph, dispatcher=dispatcher)
        results = scheduler.run(self._ok_executor())
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(node_status(scheduler._state(), "a"), "blocked")
        records, _ = scheduler.log.read()
        effect_records = [r for r in records if r["kind"] == "effect"
                          and r["nodeId"] == "a"]
        phases = [r["payload"]["effectPhase"] for r in effect_records]
        self.assertEqual(phases, ["prepared", "dispatched", "uncertain"])  # §7.2 order
        scheduler.run(self._ok_executor())  # a second pass NEVER re-dispatches
        records, _ = scheduler.log.read()
        self.assertEqual(len([r for r in records if r["kind"] == "effect"]), 3)
        scheduler.record_human_intervention("a", actor="human", decision="reconciled",
                                            reason="API confirmed idempotent write")
        records, _ = scheduler.log.read()
        interventions = [r for r in records if r["kind"] == "human-intervention"]
        self.assertEqual(len(interventions), 1)
        self.assertEqual(interventions[0]["payload"]["actor"], "human")

    def test_s7_safe_effect_uses_condensed_sequence(self):
        """§7.1 (F9): classification safe → ONE dispatched record, no
        prepared phase."""
        graph = two_branch_graph()
        graph["nodes"][0] = _write_node("a", reconciliation="none",
                                        classification="safe")
        graph["nodes"][2]["deps"] = ["a"]
        dispatcher = RecordingDispatcher(behavior="confirmed")
        scheduler = self._scheduler(graph, dispatcher=dispatcher)
        results = scheduler.run(self._ok_executor())
        self.assertEqual(results[0]["status"], "completed")
        records, _ = scheduler.log.read()
        phases = [r["payload"]["effectPhase"] for r in records
                  if r["kind"] == "effect" and r["nodeId"] == "a"]
        self.assertEqual(phases, ["dispatched", "confirmed"])  # condensed (§7.1)

    def test_s7_block_effect_never_reaches_dispatcher(self):
        """§7.1: reconciliation none → block — the effect NEVER emits without
        human approval; the node is blocked, the dispatcher is never called."""
        graph = two_branch_graph()
        graph["nodes"][0] = _write_node("a", reconciliation="none")
        graph["nodes"][2]["deps"] = ["a"]
        dispatcher = RecordingDispatcher(behavior="confirmed")
        scheduler = self._scheduler(graph, dispatcher=dispatcher)
        results = scheduler.run(self._ok_executor())
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(dispatcher.calls, [])  # never dispatched
        records, _ = scheduler.log.read()
        self.assertTrue(any(r["kind"] == "effect" and r["to"] == "blocked"
                            for r in records))

    def test_i9_runtime_permission_refusal(self):
        """T-03 (F-16): a write effect WITHOUT the write: permission is
        refused by the engine — the node is blocked, permission counted."""
        graph = two_branch_graph()
        node = _write_node("a", reconciliation="none")
        node["permissions"] = ["read:fs"]  # no write permission
        graph["nodes"][0] = node
        graph["nodes"][2]["deps"] = ["a"]
        dispatcher = RecordingDispatcher()
        scheduler = self._scheduler(graph, dispatcher=dispatcher)
        results = scheduler.run(self._ok_executor())
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(dispatcher.calls, [])
        entry = scheduler._state()["nodeExecutions"]["a"]
        self.assertEqual(entry["failureCounts"]["permission"], 1)

    def test_s3b_same_second_invalidation_rejected_at_completion(self):
        """T-01 end-to-end: the invalidation lands BETWEEN the node's
        running record and its completion — the completion is rejected even
        within the same wall-clock second (journal revisions)."""
        graph = two_branch_graph()
        graph["nodes"][2]["deps"] = ["a"]
        scheduler = self._scheduler(graph)
        state = scheduler._state()

        def executor_invalidate_midway(node_id, node):
            if node_id == "final":
                # The upstream is invalidated WHILE final is running.
                scheduler.invalidate("a", "upstream changed mid-run")
            return {"output": {"ok": True},
                    "evidences": [{"evidenceId": f"e-{node_id}",
                                   "kind": "technical", "exitCode": 0}],
                    "artifactRefs": []}

        results = scheduler.run(executor_invalidate_midway)
        final_result = next(r for r in results if r["nodeId"] == "final")
        self.assertEqual(final_result["status"], "invalidated")  # I5/F3 enforced
        state = scheduler._state()
        self.assertEqual(node_status(state, "final"), "cancelled")

    def test_fingerprint_dedup_and_constant(self):
        """F-17 (§6.2): duplicated deps count once; an empty-component node
        yields the constant string — never empty."""
        fingerprint = compute_input_fingerprint({"inputs": {}}, {})
        self.assertEqual(fingerprint, compute_input_fingerprint({"inputs": {}}, {}))
        with_deps = compute_input_fingerprint(
            {"inputs": {}}, {"a": "sha256:x", "a-dup": "sha256:x"})
        self.assertTrue(with_deps.startswith("sha256:"))
        self.assertNotEqual(with_deps, fingerprint)
        self.assertNotEqual(fingerprint, "")


if __name__ == "__main__":
    unittest.main()
