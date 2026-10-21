"""Tests du Workflow Dashboard — Universal Core (contrat, verrous, dérivation)."""

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

ISO = "2026-10-21T10:00:00+00:00"


def _base_topic(**overrides):
    topic = {
        "schemaVersion": 1,
        "topicId": str(__import__("uuid").uuid4()),
        "title": "Objectif de test",
        "kind": "plan",
        "source": "orchestrator-cli",
        "scope": "global",
        "steps": [
            {"id": "s1", "label": "Étape un", "status": "PENDING"},
            {"id": "s2", "label": "Étape deux", "status": "DONE"},
        ],
        "createdAt": ISO,
        "updatedAt": ISO,
        "revision": 1,
    }
    topic.update(overrides)
    return topic


class EnvTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get(wd_core.ENV_PROGRESS_DIR)
        os.environ[wd_core.ENV_PROGRESS_DIR] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop(wd_core.ENV_PROGRESS_DIR, None)
        else:
            os.environ[wd_core.ENV_PROGRESS_DIR] = self._old
        self._tmp.cleanup()


class TestValidation(unittest.TestCase):
    def test_valid_topic_passes(self):
        wd_core.validate_topic(_base_topic())

    def test_rejects_wrong_schema_version(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(schemaVersion=2))

    def test_rejects_non_uuid_topic_id(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(topicId="tw-demo--abcd"))

    def test_rejects_unknown_status(self):
        topic = _base_topic()
        topic["steps"][0]["status"] = "PASSED"
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(topic)

    def test_rejects_unknown_kind(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(kind="workflow"))

    def test_rejects_unknown_source(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(source="agent"))

    def test_rejects_unknown_scope(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(scope="repo"))

    def test_rejects_empty_label(self):
        topic = _base_topic()
        topic["steps"][0]["label"] = "  "
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(topic)

    def test_rejects_duplicate_step_ids(self):
        topic = _base_topic()
        topic["steps"][1]["id"] = "s1"
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(topic)

    def test_rejects_unknown_parent(self):
        topic = _base_topic()
        topic["steps"][0]["parentId"] = "ghost"
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(topic)

    def test_rejects_self_parent(self):
        topic = _base_topic()
        topic["steps"][0]["parentId"] = "s1"
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(topic)

    def test_rejects_missing_worktree_path_for_scope(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(scope="worktree"))

    def test_rejects_missing_session_id_for_scope(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(scope="session"))

    def test_rejects_bad_revision(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(revision=0))

    def test_rejects_bad_timestamp(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.validate_topic(_base_topic(createdAt="not-a-date"))


class TestStore(EnvTestCase):
    def test_create_persists_valid_topic(self):
        topic = wd_core.create_topic(
            title="Mon plan", kind="plan", source="orchestrator-cli",
            scope="global",
            steps=[{"id": "a", "label": "Un"}, {"id": "b", "label": "Deux"}])
        self.assertEqual(topic["revision"], 1)
        self.assertEqual([s["status"] for s in topic["steps"]], ["PENDING", "PENDING"])
        path = wd_core.topic_abspath(topic)
        self.assertTrue(os.path.isfile(path))
        on_disk = json.load(open(path, encoding="utf-8"))
        self.assertEqual(on_disk["topicId"], topic["topicId"])

    def test_create_duplicate_refused(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global")
        path = wd_core.topic_abspath(topic)
        with mock.patch.object(wd_core, "new_topic_id", return_value=topic["topicId"]):
            with self.assertRaises(wd_core.ContractError):
                wd_core.create_topic(title="X", kind="plan",
                                     source="orchestrator-cli", scope="global")
        # le fichier d'origine est intact
        self.assertTrue(os.path.isfile(path))

    def test_update_step_bumps_revision(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        updated = wd_core.update_step(topic["topicId"], "a", "DONE",
                                      detail="fini proprement")
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["steps"][0]["status"], "DONE")
        self.assertEqual(updated["steps"][0]["detail"], "fini proprement")
        self.assertIsNotNone(updated["steps"][0].get("updatedAt"))

    def test_update_step_unknown_step_refused_and_disk_unchanged(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        with self.assertRaises(wd_core.ContractError):
            wd_core.update_step(topic["topicId"], "ghost", "DONE")
        on_disk = wd_core.read_topic(wd_core.find_topic_path(topic["topicId"]))
        self.assertEqual(on_disk["revision"], 1)
        self.assertEqual(on_disk["steps"][0]["status"], "PENDING")

    def test_set_steps_preserves_stable_ids_states(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"},
                                            {"id": "b", "label": "Deux"}])
        wd_core.update_step(topic["topicId"], "a", "DONE")
        rewritten = wd_core.set_steps(topic["topicId"], [
            {"id": "a", "label": "Un (renommé)"}, {"id": "c", "label": "Nouveau"}])
        by_id = {s["id"]: s for s in rewritten["steps"]}
        self.assertEqual(set(by_id), {"a", "c"})  # b supprimé (absent du plan)
        self.assertEqual(by_id["a"]["status"], "DONE")  # état conservé
        self.assertEqual(by_id["a"]["label"], "Un (renommé)")
        self.assertEqual(by_id["c"]["status"], "PENDING")

    def test_close_marks_non_terminal_only(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"},
                                            {"id": "b", "label": "Deux"}])
        wd_core.update_step(topic["topicId"], "a", "FAILED")
        closed = wd_core.close_topic(topic["topicId"], "SKIPPED")
        by_id = {s["id"]: s for s in closed["steps"]}
        self.assertEqual(by_id["a"]["status"], "FAILED")  # terminal : intouché
        self.assertEqual(by_id["b"]["status"], "SKIPPED")
        self.assertIn("was PENDING", by_id["b"]["detail"])

    def test_close_rejects_non_terminal_status(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        with self.assertRaises(wd_core.ContractError):
            wd_core.close_topic(topic["topicId"], "RUNNING")

    def test_set_steps_bumps_revision(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        rewritten = wd_core.set_steps(topic["topicId"],
                                      [{"id": "a", "label": "Un"}])
        self.assertEqual(rewritten["revision"], 2)

    def test_create_with_explicit_topic_id(self):
        # review J4 : les sources NATIVES imposent leur identité (UUID v5
        # dérivé — relais todowrite, adaptateur task-workflow)
        topic = wd_core.create_topic(title="X", kind="plan",
                                     source="todowrite-relay", scope="session",
                                     session_id="ses_1",
                                     topic_id="11111111-1111-4111-8111-222222222222")
        self.assertEqual(topic["topicId"], "11111111-1111-4111-8111-222222222222")
        self.assertEqual(wd_core.find_topic_path(topic["topicId"]),
                         wd_core.topic_abspath(topic))

    def test_create_duplicate_explicit_id_refused(self):
        wd_core.create_topic(title="X", kind="plan", source="todowrite-relay",
                             scope="session", session_id="ses_1",
                             topic_id="11111111-1111-4111-8111-222222222222")
        with self.assertRaises(wd_core.ContractError):
            wd_core.create_topic(title="Y", kind="plan", source="todowrite-relay",
                                 scope="session", session_id="ses_1",
                                 topic_id="11111111-1111-4111-8111-222222222222")

    def test_set_steps_forced_status_wins(self):
        # review J4 : mode PAYLOAD (relais) — le statut fourni gagne sur la
        # conservation t4 ; le label reste éditable
        topic = wd_core.create_topic(title="X", kind="plan",
                                     source="todowrite-relay", scope="session",
                                     session_id="ses_1",
                                     steps=[{"id": "a", "label": "Un"}])
        wd_core.update_step(topic["topicId"], "a", "RUNNING")
        rewritten = wd_core.set_steps(topic["topicId"], [
            {"id": "a", "label": "Un", "status": "DONE"}])
        self.assertEqual(rewritten["steps"][0]["status"], "DONE")

    def test_set_steps_without_status_preserves(self):
        # règle t4 inchangée : sans statut fourni, l'état stable est conservé
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        wd_core.update_step(topic["topicId"], "a", "RUNNING")
        rewritten = wd_core.set_steps(topic["topicId"],
                                      [{"id": "a", "label": "Un"}])
        self.assertEqual(rewritten["steps"][0]["status"], "RUNNING")

    def test_set_steps_payload_mode_detail_wins(self):
        # review J4 F1 : en mode PAYLOAD, le detail fourni gagne sur l'ancien
        # (et l'absence de detail tue l'ancien — le payload est complet)
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        wd_core.update_step(topic["topicId"], "a", "BLOCKED", detail="ancien")
        rewritten = wd_core.set_steps(topic["topicId"], [
            {"id": "a", "label": "Un", "status": "DONE",
             "detail": "nouveau"}])
        self.assertEqual(rewritten["steps"][0]["detail"], "nouveau")
        cleaned = wd_core.set_steps(topic["topicId"], [
            {"id": "a", "label": "Un", "status": "DONE"}])
        self.assertNotIn("detail", cleaned["steps"][0])  # l'ancien ne revit pas

    def test_set_steps_cli_mode_preserves_detail(self):
        # rétrocompat : les specs CLI (id=label sans status) conservent
        # le détail existant (règle t4)
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        wd_core.update_step(topic["topicId"], "a", "BLOCKED", detail="ancien")
        rewritten = wd_core.set_steps(topic["topicId"],
                                      [{"id": "a", "label": "Un modifié"}])
        self.assertEqual(rewritten["steps"][0]["detail"], "ancien")

    def test_create_topic_exists_typed_error(self):
        wd_core.create_topic(title="X", kind="plan", source="todowrite-relay",
                             scope="session", session_id="ses_1",
                             topic_id="11111111-1111-4111-8111-222222222222")
        with self.assertRaises(wd_core.TopicExistsError):
            wd_core.create_topic(title="Y", kind="plan", source="todowrite-relay",
                                 scope="session", session_id="ses_1",
                                 topic_id="11111111-1111-4111-8111-222222222222")

    def test_set_steps_forced_transition_bumps_step_timestamp(self):
        topic = wd_core.create_topic(title="X", kind="plan",
                                     source="todowrite-relay", scope="session",
                                     session_id="ses_1",
                                     steps=[{"id": "a", "label": "Un"}])
        first = wd_core.set_steps(topic["topicId"],
                                  [{"id": "a", "label": "Un"}])["steps"][0]
        time.sleep(0.002)  # now_iso a une résolution µs — garantir l'écart
        second = wd_core.set_steps(topic["topicId"],
                                   [{"id": "a", "label": "Un",
                                     "status": "RUNNING"}])["steps"][0]
        self.assertGreater(second["updatedAt"], first["updatedAt"])  # transition réelle

    def test_close_bumps_revision_and_preserves_existing_detail(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        wd_core.update_step(topic["topicId"], "a", "BLOCKED", detail="attente PO")
        closed = wd_core.close_topic(topic["topicId"], "SKIPPED")
        self.assertEqual(closed["revision"], 3)
        self.assertIn("attente PO", closed["steps"][0]["detail"])
        self.assertIn("was BLOCKED", closed["steps"][0]["detail"])

    def test_write_failure_leaves_original_intact(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "a", "label": "Un"}])
        path = wd_core.topic_abspath(topic)
        before = open(path, encoding="utf-8").read()
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                wd_core.update_step(topic["topicId"], "a", "DONE")
        self.assertEqual(open(path, encoding="utf-8").read(), before)
        leftovers = [f for f in os.listdir(os.path.dirname(path))
                     if f.startswith(".wd-")]
        self.assertEqual(leftovers, [])  # tmp nettoyé, original intact

    def test_concurrent_append_steps_preserve_both(self):
        # review J1 #2 : deux writers réels (process séparés) — aucun step perdu
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global",
                                     steps=[{"id": "base", "label": "Base"}])
        root = os.environ[wd_core.ENV_PROGRESS_DIR]

        def worker(step_id):
            import multiprocessing as mp
            # l'enfant fork hérite de l'env + des modules déjà importés

        import multiprocessing as mp
        ctx = mp.get_context("fork")

        def _run(step_id):
            os.environ[wd_core.ENV_PROGRESS_DIR] = root
            wd_core.append_step(topic["topicId"],
                                {"id": step_id, "label": f"Step {step_id}"})

        procs = [ctx.Process(target=_run, args=(f"x{i}",)) for i in range(2)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=30)
            self.assertEqual(proc.exitcode, 0)
        on_disk = wd_core.read_topic(wd_core.find_topic_path(topic["topicId"]))
        ids = {step["id"] for step in on_disk["steps"]}
        self.assertEqual(ids, {"base", "x0", "x1"})  # aucun lost update

    def test_operations_on_unknown_topic_refused(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.update_step("00000000-0000-4000-8000-000000000000", "a", "DONE")

    def test_read_topic_tolerates_corrupt_json(self):
        topic = wd_core.create_topic(title="X", kind="plan", source="orchestrator-cli",
                                     scope="global")
        path = wd_core.topic_abspath(topic)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"broken": [1, 2,]}')  # trailing comma (état réel vécu)
        self.assertIsNone(wd_core.read_topic(path))

    def test_list_topics_reports_errors(self):
        wd_core.create_topic(title="OK", kind="plan", source="orchestrator-cli",
                             scope="global")
        bad_dir = os.path.join(os.environ[wd_core.ENV_PROGRESS_DIR], "global")
        with open(os.path.join(bad_dir, "00000000-0000-4000-8000-00000000000f.json"),
                  "w", encoding="utf-8") as handle:
            handle.write("{oops")
        entries = wd_core.list_topics()
        oks = [e for e in entries if e["topic"] is not None]
        errors = [e for e in entries if e["topic"] is None]
        self.assertEqual(len(oks), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("unreadable", errors[0]["error"])


class TestScope(unittest.TestCase):
    def test_scope_key_deterministic_for_worktree(self):
        key1 = wd_core.scope_key("worktree", worktree_path="/tmp/wt-demo")
        key2 = wd_core.scope_key("worktree", worktree_path="/tmp/wt-demo")
        self.assertEqual(key1, key2)
        self.assertTrue(key1.startswith("worktree-"))

    def test_scope_key_differs_for_different_worktrees(self):
        k1 = wd_core.scope_key("worktree", worktree_path="/tmp/wt-a")
        k2 = wd_core.scope_key("worktree", worktree_path="/tmp/wt-b")
        self.assertNotEqual(k1, k2)

    def test_scope_key_session_sanitized(self):
        self.assertEqual(wd_core.scope_key("session", session_id="ses_abc-123"),
                         "session-ses_abc-123")
        weird = wd_core.scope_key("session", session_id="un id/étrange à moi")
        self.assertTrue(weird.startswith("session-"))
        self.assertNotIn("/", weird)

    def test_scope_key_requires_fields(self):
        with self.assertRaises(wd_core.ContractError):
            wd_core.scope_key("worktree")
        with self.assertRaises(wd_core.ContractError):
            wd_core.scope_key("session")
        self.assertEqual(wd_core.scope_key("global"), "global")


class TestLocks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lock_path = os.path.join(self._tmp.name, "topic.json.lock")

    def tearDown(self):
        self._tmp.cleanup()

    def _stale_mtime(self):
        old = time.time() - 300
        os.utime(self.lock_path, (old, old))

    def test_busy_lock_raises(self):
        lock = wd_core.FileLock(self.lock_path, stale_age=3600)
        lock.acquire()
        try:
            with self.assertRaises(wd_core.LockError):
                wd_core.FileLock(self.lock_path, timeout=0.2, poll=0.02,
                                 stale_age=3600).acquire()
        finally:
            lock.release()

    def test_stale_lock_taken_over_when_pid_dead(self):
        proc = subprocess.Popen(["true"])
        proc.wait()
        with open(self.lock_path, "w", encoding="utf-8") as handle:
            handle.write(f"{proc.pid} 2026-10-21T10:00:00+00:00\n")
        self._stale_mtime()
        lock = wd_core.FileLock(self.lock_path, timeout=1.0, poll=0.02)
        lock.acquire()  # pid mort + âge dépassé => takeover légitime
        lock.release()

    def test_lock_not_taken_over_when_pid_alive(self):
        with open(self.lock_path, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()} 2026-10-21T10:00:00+00:00\n")
        self._stale_mtime()  # âge seul ne suffit JAMAIS (improvement t4 #2)
        with self.assertRaises(wd_core.LockError):
            wd_core.FileLock(self.lock_path, timeout=0.3, poll=0.02).acquire()

    def test_release_removes_own_lock(self):
        lock = wd_core.FileLock(self.lock_path)
        lock.acquire()
        self.assertTrue(os.path.isfile(self.lock_path))
        lock.release()
        self.assertFalse(os.path.isfile(self.lock_path))

    def test_release_keeps_foreign_lock(self):
        proc = subprocess.Popen(["true"])
        proc.wait()
        lock = wd_core.FileLock(self.lock_path)
        lock.acquire()
        with open(self.lock_path, "w", encoding="utf-8") as handle:
            handle.write(f"{proc.pid} 2026-10-21T10:00:00+00:00\n")  # contenu remplacé
        lock.release()
        self.assertTrue(os.path.isfile(self.lock_path))  # pas notre verrou : intouché
        os.unlink(self.lock_path)


class TestProgress(unittest.TestCase):
    def test_compute_progress_counts_top_level_only(self):
        topic = _base_topic(steps=[
            {"id": "a", "label": "A", "status": "DONE"},
            {"id": "b", "label": "B", "status": "RUNNING"},
            {"id": "b1", "label": "B.1", "parentId": "b", "status": "DONE"},
        ])
        progress = wd_core.compute_progress(topic)
        self.assertEqual(progress["total"], 2)  # b1 n'est pas compté deux fois
        self.assertEqual(progress["counts"]["DONE"], 1)
        self.assertEqual(progress["derivedStatus"], "RUNNING")

    def test_derive_status_matrix(self):
        def topic(*statuses):
            return _base_topic(steps=[
                {"id": f"s{i}", "label": f"S{i}", "status": status}
                for i, status in enumerate(statuses)])
        self.assertEqual(wd_core.derive_status(topic("RUNNING", "DONE")), "RUNNING")
        self.assertEqual(wd_core.derive_status(topic("BLOCKED", "DONE")), "BLOCKED")
        self.assertEqual(wd_core.derive_status(topic("DONE", "FAILED")), "FAILED")
        self.assertEqual(wd_core.derive_status(topic("DONE", "DONE")), "DONE")
        self.assertEqual(wd_core.derive_status(topic("SKIPPED")), "SKIPPED")
        self.assertEqual(wd_core.derive_status(topic("DONE", "PENDING")), "RUNNING")
        self.assertEqual(wd_core.derive_status(topic("PENDING")), "PENDING")
        empty = _base_topic(steps=[])
        self.assertEqual(wd_core.derive_status(empty), "PENDING")

    def test_terminal_ratio(self):
        topic = _base_topic(steps=[
            {"id": "a", "label": "A", "status": "DONE"},
            {"id": "b", "label": "B", "status": "PENDING"},
        ])
        self.assertEqual(wd_core.compute_progress(topic)["terminalRatio"], 0.5)


if __name__ == "__main__":
    unittest.main()
