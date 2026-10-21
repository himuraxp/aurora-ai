"""Tests de l'adaptateur task-workflow (source native -> ProgressTopic)."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import wd_core  # noqa: E402
import wd_taskworkflow as twa  # noqa: E402

ISO = "2026-10-21T10:00:00+00:00"


def make_state(workflow_id="tw-demo--abcd1234", phases=None, worktree=True):
    return {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "taskUrls": [{"source": "trello", "url": "https://trello.com/c/Tx92vbIR/533"}],
        "repository": "demo/repo",
        "baseBranch": "develop",
        "baseCommit": "a" * 40,
        "featureBranch": "feat/demo--do-something",
        "worktreePath": "/tmp/wt-demo" if worktree else None,
        "currentPhase": 2,
        "phaseStatuses": phases if phases is not None else {
            "1": {"status": "PASSED", "at": ISO},
            "2": {"status": "RUNNING", "at": ISO},
        },
        "createdAt": ISO,
        "updatedAt": ISO,
        "plan": {"objective": "Objectif de démonstration"},
    }


class EnvTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get(twa.ENV_STATE_DIR)
        os.environ[twa.ENV_STATE_DIR] = self._tmp.name
        self._old_progress = os.environ.get(wd_core.ENV_PROGRESS_DIR)
        os.environ[wd_core.ENV_PROGRESS_DIR] = os.path.join(self._tmp.name, "progress")

    def tearDown(self):
        if self._old is None:
            os.environ.pop(twa.ENV_STATE_DIR, None)
        else:
            os.environ[twa.ENV_STATE_DIR] = self._old
        if self._old_progress is None:
            os.environ.pop(wd_core.ENV_PROGRESS_DIR, None)
        else:
            os.environ[wd_core.ENV_PROGRESS_DIR] = self._old_progress
        self._tmp.cleanup()

    def write_state(self, state, suffix=".json", content=None):
        name = f"{state['workflowId']}{suffix}" if state else "orphan.json"
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            if content is None:
                json.dump(state, handle, ensure_ascii=False)
            else:
                handle.write(content)
        return path


class TestStateToTopic(EnvTestCase):
    def test_happy_path(self):
        topic = twa.state_to_topic(make_state())
        self.assertEqual(topic["kind"], "skill")
        self.assertEqual(topic["source"], "task-workflow")
        self.assertEqual(topic["scope"], "worktree")
        self.assertEqual(topic["worktreePath"], "/tmp/wt-demo")
        self.assertEqual(topic["title"], "Objectif de démonstration")
        self.assertEqual(len(topic["steps"]), 9)
        self.assertEqual(topic["steps"][0]["status"], "DONE")  # PASSED -> DONE
        self.assertEqual(topic["steps"][1]["status"], "RUNNING")
        self.assertEqual(topic["steps"][2]["status"], "PENDING")  # non marquée
        self.assertEqual(topic["steps"][0]["label"], "Contexte")
        self.assertEqual(topic["steps"][0]["updatedAt"], ISO)

    def test_topic_passes_contract_validation(self):
        wd_core.validate_topic(twa.state_to_topic(make_state()))  # ne lève pas

    def test_topic_id_deterministic_uuid5(self):
        t1 = twa.state_to_topic(make_state())
        t2 = twa.state_to_topic(make_state())
        self.assertEqual(t1["topicId"], t2["topicId"])
        other = twa.state_to_topic(make_state(workflow_id="tw-demo--eeee5678"))
        self.assertNotEqual(t1["topicId"], other["topicId"])

    def test_waiting_approval_maps_to_blocked_with_detail(self):
        state = make_state(phases={"3": {"status": "WAITING_APPROVAL", "at": ISO}})
        topic = twa.state_to_topic(state)
        step = topic["steps"][2]
        self.assertEqual(step["status"], "BLOCKED")
        self.assertIn("WAITING_APPROVAL", step["detail"])

    def test_unknown_status_defaults_pending_with_detail(self):
        state = make_state(phases={"4": {"status": "MYSTERY", "at": ISO}})
        topic = twa.state_to_topic(state)
        step = topic["steps"][3]
        self.assertEqual(step["status"], "PENDING")
        self.assertIn("MYSTERY", step["detail"])

    def test_missing_phases_default_pending(self):
        topic = twa.state_to_topic(make_state(phases={}))
        self.assertEqual([s["status"] for s in topic["steps"]],
                         ["PENDING"] * 9)

    def test_global_scope_without_worktree(self):
        topic = twa.state_to_topic(make_state(worktree=False))
        self.assertEqual(topic["scope"], "global")
        self.assertNotIn("worktreePath", topic)

    def test_title_fallback_feature_branch(self):
        state = make_state()
        state["plan"] = {}
        topic = twa.state_to_topic(state)
        self.assertEqual(topic["title"], "feat/demo--do-something")

    def test_session_id_from_handoff(self):
        # review J1 #3 : la session de claim réelle = handoff.session
        state = make_state()
        state["handoff"] = {"status": "pending", "session": "pane:wt-demo-123"}
        topic = twa.state_to_topic(state)
        self.assertEqual(topic["sessionId"], "pane:wt-demo-123")

    def test_malformed_handoff_ignored(self):
        state = make_state()
        state["handoff"] = "not-a-dict"
        topic = twa.state_to_topic(state)
        self.assertNotIn("sessionId", topic)

    def test_corrupt_phases_entry_tolerated(self):
        state = make_state(phases={"1": "not-a-dict"})
        topic = twa.state_to_topic(state)
        self.assertEqual(topic["steps"][0]["status"], "PENDING")


class TestListTopics(EnvTestCase):
    def test_ignores_design_artifact_and_mismatched_names(self):
        self.write_state(make_state())
        design = make_state(workflow_id="tw-demo--abcd1234")
        design.pop("plan")
        design_name = "tw-demo--abcd1234.design.json"
        with open(os.path.join(self._tmp.name, design_name), "w",
                  encoding="utf-8") as handle:
            json.dump(design, handle)
        result = twa.list_topics()
        # l'artefact design-qa est ignoré silencieusement (jamais un topic)
        self.assertEqual(len(result["topics"]), 1)
        self.assertNotIn(design_name, [t["topicId"] for t in result["topics"]])
        self.assertEqual([t["title"] for t in result["topics"]],
                         ["Objectif de démonstration"])

    def test_reports_corrupt_file_without_crash(self):
        self.write_state(make_state())
        bad = make_state(workflow_id="tw-demo--badfile99")
        bad_name = f"{bad['workflowId']}.json"
        with open(os.path.join(self._tmp.name, bad_name), "w",
                  encoding="utf-8") as handle:
            handle.write('{"workflowId": "tw-demo--badfile99", "x": [1,]}')
        result = twa.list_topics()
        self.assertEqual(len(result["topics"]), 1)
        self.assertEqual(len(result["ignored"]), 1)
        self.assertIn(bad_name, result["ignored"][0]["file"])
        self.assertEqual(result["ignored"][0]["reason"], "unreadable JSON")

    def test_empty_or_missing_dir(self):
        result = twa.list_topics()
        self.assertEqual(result, {"topics": [], "ignored": []})


if __name__ == "__main__":
    unittest.main()
