"""Tests du relais todowrite (J4 — mapping 1:1 déterministe, CLI)."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import wd_core  # noqa: E402
import wd_dashboard as dash  # noqa: E402
import wd_relay  # noqa: E402

SESSION = "ses_abcdef1234567890"
NOW = "2026-10-21T12:00:00+00:00"


def todos(*states):
    return [{"content": f"Tâche {chr(97 + i)}", "status": s}
            for i, s in enumerate(states)]


class RelayTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patcher = mock.patch.dict(os.environ, {
            wd_core.ENV_PROGRESS_DIR: os.path.join(self._tmp.name, "progress"),
        })
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()


class TestTopicId(RelayTestCase):
    def test_deterministic_per_session(self):
        # improvement t4 #3 : association session→topic STABLE sans état
        self.assertEqual(wd_relay.topic_id_for_session(SESSION),
                         wd_relay.topic_id_for_session(SESSION))

    def test_distinct_sessions_distinct_topics(self):
        self.assertNotEqual(wd_relay.topic_id_for_session(SESSION),
                            wd_relay.topic_id_for_session("ses_other"))

    def test_id_is_valid_canonical_uuid(self):
        topic_id = wd_relay.topic_id_for_session(SESSION)
        self.assertTrue(wd_core.canonical_uuid(topic_id))


class TestMapTodo(RelayTestCase):
    def test_mapping_is_one_to_one(self):
        # pas d'invention : pending/in_progress/completed seulement
        self.assertEqual(wd_relay.map_todo(0, todos("pending")[0])["status"],
                         "PENDING")
        self.assertEqual(
            wd_relay.map_todo(0, todos("in_progress")[0])["status"], "RUNNING")
        self.assertEqual(
            wd_relay.map_todo(0, todos("completed")[0])["status"], "DONE")

    def test_unknown_status_pending_with_trace(self):
        step = wd_relay.map_todo(0, {"content": "X", "status": "weird"})
        self.assertEqual(step["status"], "PENDING")
        self.assertIn("weird", step["detail"])  # trace du brut, jamais muet

    def test_missing_status_maps_to_pending(self):
        step = wd_relay.map_todo(0, {"content": "X"})
        self.assertEqual(step["status"], "PENDING")

    def test_newlines_stripped_from_label(self):
        step = wd_relay.map_todo(0, {"content": "ligne1\nligne2",
                                     "status": "pending"})
        self.assertEqual(step["label"], "ligne1 ligne2")

    def test_empty_content_refused(self):
        with self.assertRaises(wd_core.ContractError):
            wd_relay.map_todo(0, {"content": "  ", "status": "pending"})

    def test_non_object_todo_refused(self):
        with self.assertRaises(wd_core.ContractError):
            wd_relay.map_todo(0, "not-a-dict")


class TestReconcile(RelayTestCase):
    def test_first_call_creates_topic(self):
        result = wd_relay.reconcile(SESSION, todos("pending", "in_progress"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["created"])
        self.assertEqual(result["topicId"],
                         wd_relay.topic_id_for_session(SESSION))
        topic = wd_core.read_topic(
            wd_core.find_topic_path(result["topicId"]))
        self.assertEqual(topic["source"], "todowrite-relay")
        self.assertEqual(topic["kind"], "plan")
        self.assertEqual(topic["scope"], "session")
        self.assertEqual(topic["sessionId"], SESSION)
        self.assertEqual([s["status"] for s in topic["steps"]],
                         ["PENDING", "RUNNING"])

    def test_reconciliation_is_complete_payload_wins(self):
        # 1er event : deux todos, la première en cours
        result = wd_relay.reconcile(SESSION, todos("in_progress", "pending"))
        topic_id = result["topicId"]
        # 2e event : la première passe DONE, la seconde in_progress, la
        # troisième apparaît — les statuts du PAYLOAD gagnent (relais)
        wd_relay.reconcile(SESSION, todos("completed", "in_progress"))
        wd_relay.reconcile(
            SESSION, todos("completed", "completed") + [
                {"content": "Tâche c", "status": "pending"}])
        topic = wd_core.read_topic(wd_core.find_topic_path(topic_id))
        self.assertEqual([s["status"] for s in topic["steps"]],
                         ["DONE", "DONE", "PENDING"])
        self.assertEqual(len(topic["steps"]), 3)  # todo absente du payload = partie

    def test_reconciliation_after_reuse_keeps_same_topic(self):
        # reprise : même session → même topic, réinitialisation nulle
        first = wd_relay.reconcile(SESSION, todos("completed"))
        second = wd_relay.reconcile(SESSION, todos("in_progress"))
        self.assertFalse(second["created"])  # pas de doublon
        self.assertEqual(first["topicId"], second["topicId"])

    def test_empty_payload_creates_empty_topic(self):
        # limite assumée (docstring) : payload vidé → topic sans steps
        result = wd_relay.reconcile(SESSION, [])
        topic = wd_core.read_topic(wd_core.find_topic_path(result["topicId"]))
        self.assertEqual(topic["steps"], [])

    def test_racing_create_falls_back_to_reconcile(self):
        # deux writers : le create perdu sur « already exists » → set-steps.
        # Simulation : l'autre writer a créé le topic, notre vue est stale
        # (find → None au 1er appel), le create rate, la réconciliation suit.
        wd_relay.reconcile(SESSION, todos("completed"))  # l'autre writer
        real_find = wd_core.find_topic_path
        calls = {"n": 0}

        def stale_find(topic_id, root=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # vue stale au moment du check d'existence
            return real_find(topic_id, root=root)

        with mock.patch.object(wd_core, "find_topic_path", stale_find), \
             mock.patch.object(
                 wd_core, "create_topic",
                 side_effect=wd_core.TopicExistsError(
                     f"topic already exists: "
                     f"{wd_relay.topic_id_for_session(SESSION)}")):
            result = wd_relay.reconcile(SESSION, todos("pending"))
        self.assertTrue(result["ok"])
        self.assertFalse(result["created"])
        topic = wd_core.read_topic(wd_core.find_topic_path(result["topicId"]))
        self.assertEqual(len(topic["steps"]), 1)

    def test_mixed_case_statuses_mapped(self):
        # review J4 F7 : le .lower() n'était pas testé
        wd_relay.reconcile(SESSION, [
            {"content": "A", "status": "PENDING"},
            {"content": "B", "status": "In_Progress"},
            {"content": "C", "status": "COMPLETED"}])
        topic = wd_core.read_topic(
            wd_core.find_topic_path(wd_relay.topic_id_for_session(SESSION)))
        self.assertEqual([s["status"] for s in topic["steps"]],
                         ["PENDING", "RUNNING", "DONE"])

    def test_stale_trace_dies_when_status_becomes_known(self):
        # review J4 F1 : le détail « statut non reconnu » ne doit PAS survivre
        # à la réconciliation une fois le statut corrigé (le payload gagne)
        first = wd_relay.reconcile(SESSION, todos("weird"))
        wd_relay.reconcile(SESSION, todos("pending"))  # statut redevenu connu
        topic = wd_core.read_topic(wd_core.find_topic_path(first["topicId"]))
        self.assertNotIn("detail", topic["steps"][0])

    def test_identical_reconcile_preserves_step_age(self):
        # review J4 F7 : re-réconciliation à l'identique → updatedAt step
        # préservé (l'âge reflète la transition, pas le polling)
        first = wd_relay.reconcile(SESSION, todos("in_progress"))
        topic_before = wd_core.read_topic(
            wd_core.find_topic_path(first["topicId"]))
        time.sleep(0.002)
        wd_relay.reconcile(SESSION, todos("in_progress"))
        topic_after = wd_core.read_topic(
            wd_core.find_topic_path(first["topicId"]))
        self.assertEqual(topic_before["steps"][0]["updatedAt"],
                         topic_after["steps"][0]["updatedAt"])

    def test_control_chars_neutralized(self):
        # review J4 F3 : le label traverse JSON → disque → terminal ;
        # l'invariant = AUCUN caractère de contrôle ne survit (les caractères
        # imprimables résiduels d'une séquence restent du texte inoffensif)
        step = wd_relay.map_todo(0, {"content": "A\x1b]0;pwned\x07B\r\nC"})
        for forbidden in "\x00\x1b\x07\r\n\x7f":
            self.assertNotIn(forbidden, step["label"])
        self.assertEqual(step["label"], "A ]0;pwned B C")

    def test_session_appears_in_renderer_with_relay_source(self):
        # intégration : le sujet relais est visible, source affichée
        wd_relay.reconcile(SESSION, todos("in_progress"))
        frame = dash.render(width=200)
        self.assertIn("[todowrite-relay]", frame)
        self.assertIn("Todos — session", frame)  # ligne compacte = titre
        verbose = dash.render(width=200, verbose=True)
        self.assertIn("Tâche a", verbose)  # vue détaillée = steps


class TestCli(RelayTestCase):
    def run_relay(self, *args):
        proc = subprocess.run(
            [sys.executable, os.path.join(PARENT, "wd_relay.py"), *args],
            capture_output=True, text=True, env=dict(os.environ))
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
        return proc.returncode, payload

    def test_reconcile_exit_0_json(self):
        code, payload = self.run_relay("reconcile", SESSION,
                                       json.dumps(todos("pending")))
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["created"])

    def test_invalid_json_exit_1(self):
        code, payload = self.run_relay("reconcile", SESSION, "{broken")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("JSON", payload["error"])

    def test_non_array_exit_1(self):
        code, payload = self.run_relay("reconcile", SESSION, '{"a": 1}')
        self.assertEqual(code, 1)
        self.assertIn("array", payload["error"])

    def test_empty_session_exit_1(self):
        code, payload = self.run_relay("reconcile", "  ",
                                       json.dumps(todos("pending")))
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_bad_todo_exit_1_json_guaranteed(self):
        # les erreurs de mapping sortent en JSON, jamais en traceback
        code, payload = self.run_relay("reconcile", SESSION,
                                       json.dumps(["not-a-dict"]))
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("not an object", payload["error"])

    def test_stdin_payload_supported(self):
        # review J4 F4 : mode stdin ('-') — les gros payloads ne passent
        # pas la limite MAX_ARG_STRLEN d'argv
        proc = subprocess.run(
            [sys.executable, os.path.join(PARENT, "wd_relay.py"),
             "reconcile", SESSION, "-"],
            input=json.dumps(todos("in_progress")),
            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])

    def test_usage_missing_args_exit_2(self):
        # review J4 F7 : exit 2 = usage argparse (texte stderr, pas JSON)
        proc = subprocess.run(
            [sys.executable, os.path.join(PARENT, "wd_relay.py"), "reconcile"],
            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stderr)


if __name__ == "__main__":
    unittest.main()
