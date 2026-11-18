#!/usr/bin/env python3
"""Unit tests of the M7 skill adapter (shadow-read-first, RFC §11 M7).

The adapter must NEVER express a real external write (PO NO-GO), must
force read-only permissions, and must run skill-shaped tasks through the
Core in shadow mode.

Run: python3 -m unittest discover -s skills/graph_core/tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from skills.graph_core.contracts import validate_graph_definition  # noqa: E402
from skills.graph_core.skill_adapter import (  # noqa: E402
    SkillSpecError, build_executors, build_graph_from_specs, run_skill_graph,
)


def specs_simple():
    return [
        {"id": "fetch", "kind": "process",
         "command": ["python3", "-c", "print('diff-ok')"]},
        {"id": "analyze", "kind": "analysis", "deps": ["fetch"]},
    ]


class TestSpecToGraph(unittest.TestCase):

    def test_specs_produce_a_valid_graph(self):
        graph = build_graph_from_specs("g-test", specs_simple())
        self.assertEqual(validate_graph_definition(graph), [])
        fetch = next(n for n in graph["nodes"] if n["id"] == "fetch")
        self.assertEqual(fetch["type"], "tool")
        analyze = next(n for n in graph["nodes"] if n["id"] == "analyze")
        self.assertEqual(analyze["type"], "agent")  # I9 shape

    def test_write_permissions_are_forced_read_only(self):
        """The adapter FORCES read: permissions — a caller cannot sneak a
        write: past it (PO NO-GO, defense in depth on top of I9)."""
        specs = [{"id": "rogue", "kind": "process",
                  "command": ["python3", "-c", "print('x')"],
                  "permissions": ["write:gitlab"]}]  # ignored by design
        graph = build_graph_from_specs("g-rogue", specs)
        rogue = next(n for n in graph["nodes"] if n["id"] == "rogue")
        self.assertFalse(any(str(p).startswith("write:") for p in rogue["permissions"]))

    def test_effect_policy_refused_fail_closed(self):
        """A write effect is NOT expressible through the M7 adapter — the
        PO NO-GO is enforced at the adapter level (fail-closed)."""
        specs = [{"id": "w", "kind": "process",
                  "command": ["python3", "-c", "print('x')"],
                  "effectPolicy": {"mode": "write", "idempotencyKey": "k",
                                   "reconciliation": "getBeforePost",
                                   "onUncertainOutcome": "block"}}]
        with self.assertRaises(SkillSpecError) as ctx:
            build_graph_from_specs("g-w", specs)
        self.assertIn("NO-GO", str(ctx.exception))

    def test_unknown_dep_and_duplicated_ids_refused(self):
        with self.assertRaises(SkillSpecError) as ctx:
            build_graph_from_specs("g-bad", [
                {"id": "a", "kind": "analysis", "deps": ["ghost"]}])
        self.assertIn("unknown deps", str(ctx.exception))
        with self.assertRaises(SkillSpecError) as ctx:
            build_graph_from_specs("g-dup", [
                {"id": "a", "kind": "analysis"},
                {"id": "a", "kind": "analysis"}])
        self.assertIn("duplicated", str(ctx.exception))

    def test_process_task_needs_a_command(self):
        with self.assertRaises(SkillSpecError) as ctx:
            build_graph_from_specs("g-nocmd", [{"id": "a", "kind": "process"}])
        self.assertIn("command", str(ctx.exception))


class TestShadowExecution(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run")
        self.lock_path = os.path.join(self.tmp.name, "run.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path_process_and_analysis_nodes(self):
        result = run_skill_graph("g-demo", specs_simple(),
                                 self.run_dir, self.lock_path)
        metrics = result["metrics"]
        self.assertEqual(metrics["nodes"]["completed"], 2)
        self.assertEqual(metrics["nodes"]["successRate"], 1.0)
        self.assertEqual(metrics["effects"]["realEffectEmissions"], 0)  # SANDBOX
        self.assertEqual(metrics["humanInterventions"], 0)
        fetch = metrics["perNode"]["fetch"]
        self.assertEqual(fetch["status"], "completed")
        self.assertEqual(fetch["attempts"], 1)

    def test_process_stdout_captured_as_artifact(self):
        result = run_skill_graph("g-artifact", specs_simple(),
                                 self.run_dir, self.lock_path)
        # The run's evidence store carries the exitCode-0 proof.
        evidences_path = os.path.join(self.run_dir, "evidences.jsonl")
        with open(evidences_path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn('"exitCode":0', content)  # canonical JSON (no spaces)
        self.assertIn('"artifactRef":"stdout:fetch"', content)  # stdout kept
        self.assertIn("ev-fetch", content)

    def test_failing_command_is_terminal_after_budget(self):
        """A persistently failing process exhausts its technical budget and
        lands TERMINAL failed — descendants stay visibly pending (I8)."""
        specs = [
            {"id": "boom", "kind": "process",
             "command": ["python3", "-c", "import sys; sys.exit(3)"],
             "technicalBudget": 1},
            {"id": "after", "kind": "analysis", "deps": ["boom"]},
        ]
        result = run_skill_graph("g-fail", specs, self.run_dir, self.lock_path)
        metrics = result["metrics"]
        self.assertEqual(metrics["perNode"]["boom"]["status"], "failed")
        self.assertEqual(metrics["perNode"]["boom"]["attempts"], 1)
        self.assertEqual(metrics["perNode"]["after"]["status"], "pending")
        self.assertEqual(metrics["perNode"]["after"]["attempts"], 0)

    def test_timeout_is_a_technical_failure(self):
        specs = [{"id": "slow", "kind": "process",
                  "command": ["python3", "-c", "import time; time.sleep(5)"],
                  "timeoutSeconds": 1, "technicalBudget": 1}]
        result = run_skill_graph("g-slow", specs, self.run_dir, self.lock_path)
        self.assertEqual(result["metrics"]["perNode"]["slow"]["status"], "failed")

    def test_analysis_executor_override_is_used(self):
        def custom(node_id, node):
            return {"output": {"custom": True},
                    "evidences": [{"evidenceId": f"ev-{node_id}",
                                   "kind": "technical", "exitCode": 0}],
                    "artifactRefs": []}
        result = run_skill_graph("g-custom", specs_simple(),
                                 self.run_dir, self.lock_path,
                                 extra_executors={"analyze": custom})
        self.assertEqual(result["metrics"]["nodes"]["completed"], 2)

    def test_executors_map_covers_every_spec(self):
        executors = build_executors(specs_simple())
        self.assertEqual(set(executors), {"fetch", "analyze"})


if __name__ == "__main__":
    unittest.main()
