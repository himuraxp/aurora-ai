"""Tests e2e de la CLI de publication (wd_publish)."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import wd_core  # noqa: E402
import wd_publish  # noqa: E402
import wd_taskworkflow  # noqa: E402

ISO = "2026-10-21T10:00:00+00:00"


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patcher = mock.patch.dict(os.environ,
                                        {wd_core.ENV_PROGRESS_DIR: self._tmp.name})
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def run_cli(self, *argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = wd_publish.main(list(argv))
        return code, json.loads(stdout.getvalue())

    def _create(self):
        code, payload = self.run_cli(
            "create", "--title", "Plan de test", "--kind", "plan",
            "--source", "orchestrator-cli", "--scope", "global",
            "--step", "s1=Première étape", "--step", "s2=Seconde étape")
        self.assertEqual(code, 0)
        return payload["topic"]

    def test_create_ok(self):
        code, payload = self.run_cli(
            "create", "--title", "Mon plan", "--kind", "skill",
            "--source", "todowrite-relay", "--scope", "worktree",
            "--worktree-path", "/tmp/wt-demo", "--step", "a=Un")
        self.assertEqual(code, 0)
        topic = payload["topic"]
        self.assertEqual(topic["scope"], "worktree")
        self.assertTrue(os.path.isfile(payload["path"]))
        self.assertEqual(topic["steps"][0]["status"], "PENDING")

    def test_create_bad_step_spec_fails(self):
        code, payload = self.run_cli(
            "create", "--title", "X", "--kind", "plan",
            "--source", "orchestrator-cli", "--scope", "global",
            "--step", "no-separator")
        self.assertEqual(code, 1)
        self.assertIn("id=label", payload["error"])

    def test_step_updates_and_show_reports_progress(self):
        topic = self._create()
        code, payload = self.run_cli("step", topic["topicId"], "s1", "DONE",
                                     "--detail", "preuve enregistrée")
        self.assertEqual(code, 0)
        self.assertEqual(payload["topic"]["revision"], 2)
        code, payload = self.run_cli("show", topic["topicId"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["progress"]["derivedStatus"], "RUNNING")
        self.assertEqual(payload["progress"]["terminalRatio"], 0.5)

    def test_step_unknown_topic_fails(self):
        code, payload = self.run_cli(
            "step", "00000000-0000-4000-8000-00000000000f", "s1", "DONE")
        self.assertEqual(code, 1)
        self.assertIn("not found", payload["error"])

    def test_step_invalid_status_fails_with_usage(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli("step", "00000000-0000-4000-8000-00000000000f",
                         "s1", "PASSED")
        self.assertEqual(ctx.exception.code, 2)

    def test_close_marks_remaining_steps(self):
        topic = self._create()
        code, payload = self.run_cli("close", topic["topicId"],
                                     "--status", "SKIPPED", "--detail", "abandon assumé")
        self.assertEqual(code, 0)
        statuses = [s["status"] for s in payload["topic"]["steps"]]
        self.assertEqual(statuses, ["SKIPPED", "SKIPPED"])

    def test_set_steps_rewrites_plan(self):
        topic = self._create()
        code, payload = self.run_cli("set-steps", topic["topicId"],
                                     "s1=Repris", "s3=Ajoutée")
        self.assertEqual(code, 0)
        by_id = {s["id"]: s for s in payload["topic"]["steps"]}
        self.assertEqual(set(by_id), {"s1", "s3"})
        self.assertEqual(by_id["s1"]["status"], "PENDING")

    def test_add_step_appends(self):
        topic = self._create()
        code, payload = self.run_cli("add-step", topic["topicId"],
                                     "s9=Étape ajoutée", "--parent-id", "s1")
        self.assertEqual(code, 0)
        added = payload["topic"]["steps"][-1]
        self.assertEqual(added["id"], "s9")
        self.assertEqual(added["parentId"], "s1")

    def test_list_json(self):
        self._create()
        code, payload = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["topics"]), 1)
        self.assertEqual(payload["topics"][0]["topic"]["title"], "Plan de test")

    def test_list_includes_errors(self):
        bad_dir = os.path.join(self._tmp.name, "global")
        os.makedirs(bad_dir, exist_ok=True)
        with open(os.path.join(bad_dir, "00000000-0000-4000-8000-0000000000e5.json"),
                  "w", encoding="utf-8") as handle:
            handle.write("{broken")
        code, payload = self.run_cli("list", "--include-errors")
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("unreadable", payload["errors"][0]["error"])

    def test_list_scope_worktree_returns_worktree_topics(self):
        # review J1 #1 : régression du filtre mort (scope_dir != scope)
        code, _ = self.run_cli(
            "create", "--title", "Sujet worktree", "--kind", "plan",
            "--source", "orchestrator-cli", "--scope", "worktree",
            "--worktree-path", "/tmp/wt-scope-test")
        self.assertEqual(code, 0)
        code, _ = self.run_cli(
            "create", "--title", "Sujet global", "--kind", "plan",
            "--source", "orchestrator-cli", "--scope", "global")
        self.assertEqual(code, 0)
        code, payload = self.run_cli("list", "--scope", "worktree")
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["topics"]), 1)
        self.assertEqual(payload["topics"][0]["topic"]["title"], "Sujet worktree")
        code, payload = self.run_cli("list", "--scope", "global")
        self.assertEqual(len(payload["topics"]), 1)
        self.assertEqual(payload["topics"][0]["topic"]["title"], "Sujet global")

    def test_list_source_taskworkflow_includes_native(self):
        # review J1 : branche --source task-workflow (topics natifs, non stockés)
        tw_dir = os.path.join(self._tmp.name, "tw-states")
        os.makedirs(tw_dir)
        state = {
            "schemaVersion": 1,
            "workflowId": "tw-demo--cli0001",
            "taskUrls": [], "repository": "demo/repo",
            "baseBranch": "develop", "baseCommit": "a" * 40,
            "featureBranch": "feat/demo--cli",
            "worktreePath": "/tmp/wt-cli", "currentPhase": 1,
            "phaseStatuses": {"1": {"status": "PASSED", "at": ISO}},
            "createdAt": ISO, "updatedAt": ISO,
            "plan": {"objective": "Objectif natif"},
        }
        with open(os.path.join(tw_dir, f"{state['workflowId']}.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(state, handle)
        with mock.patch.dict(os.environ, {wd_taskworkflow.ENV_STATE_DIR: tw_dir}):
            code, payload = self.run_cli("list", "--source", "task-workflow")
        self.assertEqual(code, 0)
        native = [t for t in payload["topics"]
                  if t["topic"]["source"] == "task-workflow"]
        self.assertEqual(len(native), 1)
        self.assertEqual(native[0]["topic"]["title"], "Objectif natif")


if __name__ == "__main__":
    unittest.main()
