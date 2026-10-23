#!/usr/bin/env python3
"""Tests de l'état SQLite : SHA-256 d'intégrité, autorisation à usage unique,
digests (réconciliation), résultats de plans, verrou d'exécution."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import state as state_mod  # noqa: E402

TS = "2026-10-23T08:00:00+00:00"


class PlanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def payload(self) -> dict:
        return {"mailbox": "INBOX", "uidvalidity": 7,
                "moves": [{"uid": 10, "to_folder": "INBOX/Auto/News"}],
                "created_at": TS}

    def test_sha256_canonical(self) -> None:
        a = state_mod.plan_sha256({"x": 1, "y": [1, 2]})
        b = state_mod.plan_sha256({"y": [1, 2], "x": 1})
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_plan_roundtrip(self) -> None:
        sha = self.state.create_plan("p1", TS, "2027-10-23T08:00:00+00:00", self.payload())
        plan = self.state.get_plan("p1")
        self.assertEqual(plan["sha256"], sha)
        self.assertEqual(plan["payload"], self.payload())
        self.assertEqual(plan["status"], "open")
        self.assertIsNone(self.state.get_plan("nope"))

    def test_plan_status_transitions(self) -> None:
        self.state.create_plan("p1", TS, "2027-10-23T08:00:00+00:00", self.payload())
        self.state.set_plan_status("p1", "applied")
        self.assertEqual(self.state.get_plan("p1")["status"], "applied")

    def test_authorization_single_use(self) -> None:
        self.state.authorize_plan("sha1", "batch_approved", TS)
        first = self.state.consume_authorization("sha1", "batch_approved", TS)
        self.assertIsNotNone(first)
        second = self.state.consume_authorization("sha1", "batch_approved", TS)
        self.assertIsNone(second)

    def test_authorization_kind_scoped(self) -> None:
        self.state.authorize_plan("sha1", "batch_approved", TS)
        self.assertIsNone(self.state.consume_authorization("sha1", "other_kind", TS))


class DigestStateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_digest_roundtrip_with_content(self) -> None:
        self.state.create_digest("d1", TS, "2026-10-23T09:00:00+00:00", "[m:d1]", TS,
                                 uidvalidity=7, markdown="# digest", msg_uids="10,11")
        d = self.state.get_digest("d1")
        self.assertEqual(d["state"], "pending")
        self.assertEqual(d["uidvalidity"], 7)
        self.assertEqual(d["markdown"], "# digest")
        self.assertEqual(d["msg_uids"], "10,11")

    def test_digest_state_transitions(self) -> None:
        self.state.create_digest("d1", TS, "2026-10-23T09:00:00+00:00", "[m:d1]", TS)
        self.state.set_digest_state("d1", "uncertain", resolved_at=TS)
        self.assertEqual(self.state.get_digest("d1")["state"], "uncertain")
        self.state.set_digest_state("d1", "sent", post_id="p1",
                                    resolved_at="2026-10-23T09:05:00+00:00")
        d = self.state.get_digest("d1")
        self.assertEqual(d["state"], "sent")
        self.assertEqual(d["post_id"], "p1")

    def test_last_confirmed_and_uncertain(self) -> None:
        self.state.create_digest("d1", TS, "2026-10-23T09:00:00+00:00", "[m:d1]", TS,
                                 markdown="x")
        self.state.set_digest_state("d1", "uncertain", resolved_at=TS)
        self.state.create_digest("d2", TS, "2026-10-23T10:00:00+00:00", "[m:d2]", TS,
                                 markdown="y")
        self.state.set_digest_state("d2", "sent", post_id="p2",
                                    resolved_at="2026-10-23T10:05:00+00:00")
        last = self.state.last_confirmed_digest()
        self.assertEqual(last["id"], "d2")
        self.assertEqual([d["id"] for d in self.state.uncertain_digests()], ["d1"])

    def test_digested_msgs(self) -> None:
        self.state.mark_digest_msg("INBOX", 7, 10, TS, "d1")
        self.state.mark_digest_msg("INBOX", 7, 11, TS, "d1")
        self.assertEqual(self.state.digested_msg_keys("INBOX", 7), {10, 11})


class ProcessedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mark_and_seen(self) -> None:
        self.state.mark_processed("INBOX", 7, 10, TS, "move", "INBOX/Auto/News", TS)
        self.state.mark_processed("INBOX", 7, 11, TS, None, None, TS)
        self.assertEqual(self.state.seen_uids("INBOX", 7), {10, 11})
        self.assertEqual(self.state.seen_uids("INBOX", 8), set())

    def test_moved_counts_since(self) -> None:
        self.state.mark_processed("INBOX", 7, 10, TS, "move", "INBOX/Auto/News",
                                  "2026-10-23T09:00:00+00:00")
        self.state.mark_processed("INBOX", 7, 11, TS, "move", "INBOX/Auto/News",
                                  "2026-10-23T10:00:00+00:00")
        counts = self.state.moved_counts_since("2026-10-23T09:30:00+00:00")
        self.assertEqual(counts, {"INBOX/Auto/News": 1})

    def test_plan_results_upsert(self) -> None:
        self.state.set_move_result("p1", 10, "uncertain", "timeout")
        self.state.set_move_result("p1", 10, "done", None)
        results = self.state.get_move_results("p1")
        self.assertEqual(results, [{"uid": 10, "status": "done", "detail": None}])


class FileLockTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lock_path = Path(self._tmp.name) / "apply.lock"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_exclusive(self) -> None:
        first = state_mod.FileLock(self.lock_path, timeout=0.2)
        first.acquire()
        second = state_mod.FileLock(self.lock_path, timeout=0.2)
        with self.assertRaises(state_mod.LockError):
            second.acquire()
        first.release()
        second.acquire()  # libéré → acquisition possible
        second.release()

    def test_release_keeps_file_flock_is_truth(self) -> None:
        # flock est la vérité ; le fichier persiste (pas d'unlink → pas de
        # course fd-orphan où un waiter verrouille un inode retiré).
        with state_mod.FileLock(self.lock_path, timeout=0.5):
            self.assertTrue(self.lock_path.exists())
        self.assertTrue(self.lock_path.exists())
        with state_mod.FileLock(self.lock_path, timeout=0.5):
            pass  # ré-acquis sans takeover

    def test_lock_released_on_close_is_reacquirable(self) -> None:
        lock = state_mod.FileLock(self.lock_path, timeout=0.5)
        lock.acquire()
        lock.release()
        lock2 = state_mod.FileLock(self.lock_path, timeout=0.5)
        lock2.acquire()
        lock2.release()

    def test_context_manager(self) -> None:
        with state_mod.FileLock(self.lock_path, timeout=0.5):
            self.assertTrue(self.lock_path.exists())


if __name__ == "__main__":
    unittest.main()
