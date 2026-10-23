#!/usr/bin/env python3
"""Tests du digest : fenêtre temporelle, contenu, masquage, rendu, publication."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import digest as digest_mod  # noqa: E402
import state as state_mod  # noqa: E402

NOW = datetime(2026, 10, 23, 8, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def config(**digest_overrides) -> dict:
    digest_cfg = {"enabled": True, "lookback_hours": 18, "always_inbox_cap": 10,
                  "min_interval_hours": 20, "sensitive_subject_patterns": []}
    digest_cfg.update(digest_overrides)
    return {"digest": digest_cfg, "source": {"mailbox": "INBOX"}}


class FakeKChat:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def ensure_direct_channel(self, bot_id: str, user_id: str) -> str:
        return "chan1"

    def post_message(self, channel_id: str, message: str) -> dict:
        self.posts.append(message)
        return {"id": f"post{len(self.posts)}"}


class WindowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_window_uses_lookback(self) -> None:
        window = digest_mod.compute_window(self.state, config(), NOW)
        self.assertIsNone(window["previous_id"])
        self.assertAlmostEqual((NOW - window["start"]).total_seconds(), 18 * 3600, delta=5)
        self.assertAlmostEqual((window["end"] - NOW).total_seconds(), 0, delta=5)

    def test_window_continues_from_last_confirmed(self) -> None:
        prev_end = NOW - timedelta(hours=16)
        self.state.create_digest("d0", iso(prev_end - timedelta(hours=2)), iso(prev_end),
                                 "[m:d0]", iso(NOW))
        self.state.set_digest_state("d0", "sent", post_id="p0", resolved_at=iso(NOW))
        window = digest_mod.compute_window(self.state, config(), NOW)
        self.assertEqual(window["previous_id"], "d0")
        self.assertEqual(window["start"], prev_end)


class BuildDigestTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")
        self.window = {"start": NOW - timedelta(hours=2), "end": NOW, "previous_id": None}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def messages(self) -> list[dict]:
        return [
            {"uid": 10, "from": "a@news.example.com", "subject": "Nouveautés",
             "internaldate": iso(NOW - timedelta(minutes=30)), "seen": False},
            {"uid": 11, "from": "b@example.com", "subject": "Déjà digesté",
             "internaldate": iso(NOW - timedelta(minutes=20)), "seen": False},
            {"uid": 12, "from": "c@example.com", "subject": "Vieux non lu",
             "internaldate": iso(NOW - timedelta(hours=10)), "seen": False},
            {"uid": 13, "from": "d@example.com", "subject": "Vieux lu",
             "internaldate": iso(NOW - timedelta(hours=10)), "seen": True},
        ]

    def test_new_vs_always_inbox(self) -> None:
        self.state.mark_digest_msg("INBOX", 1, 11, None, "d-old")
        built = digest_mod.build_digest(self.state, self.messages(), config(),
                                        self.window, "d1", mailbox="INBOX", uidvalidity=1)
        self.assertEqual([m["uid"] for m in built["new"]], [10])
        self.assertEqual([m["uid"] for m in built["always_inbox"]], [12])
        self.assertEqual(built["marker"], "[mail-triage-digest:d1]")

    def test_sensitive_subject_masked(self) -> None:
        messages = [{"uid": 20, "from": "hr@example.com",
                     "subject": "Votre mot de passe expire",
                     "internaldate": iso(NOW - timedelta(minutes=5)), "seen": False}]
        built = digest_mod.build_digest(
            self.state, messages, config(sensitive_subject_patterns=["(?i)mot de passe"]),
            self.window, "d2", uidvalidity=1)
        self.assertTrue(built["new"][0]["subject_masked"])
        self.assertEqual(built["new"][0]["subject"], "[sujet masqué]")

    def test_always_inbox_capped(self) -> None:
        messages = [{"uid": 100 + i, "from": f"x{i}@example.com", "subject": f"s{i}",
                     "internaldate": iso(NOW - timedelta(hours=10)), "seen": False}
                    for i in range(15)]
        built = digest_mod.build_digest(self.state, messages, config(),
                                        self.window, "d3", uidvalidity=1)
        self.assertEqual(len(built["always_inbox"]), 10)

    def test_bad_internaldate_excluded(self) -> None:
        messages = [{"uid": 30, "from": "x@example.com", "subject": "s",
                     "internaldate": "not-a-date", "seen": False}]
        built = digest_mod.build_digest(self.state, messages, config(),
                                        self.window, "d4", uidvalidity=1)
        # Date illisible = jamais classé « nouveau » ; non lu de date inconnue
        # reste visible dans « toujours dans l'Inbox » (plafonné).
        self.assertEqual(built["new"], [])
        self.assertEqual([m["uid"] for m in built["always_inbox"]], [30])


class RenderPublishTestCase(unittest.TestCase):
    def test_render_contains_marker_and_counts(self) -> None:
        digest_data = {
            "id": "d1", "marker": "[mail-triage-digest:d1]",
            "window_start": iso(NOW - timedelta(hours=2)),
            "window_end": iso(NOW),
            "timezone": "Europe/Paris",
            "new": [{"uid": 10, "from": "a@x.com", "subject": "Nouveautés",
                     "subject_masked": False,
                     "internaldate": iso(NOW - timedelta(minutes=30)), "seen": False}],
            "always_inbox": [{"uid": 12, "from": "c@x.com", "subject": "[sujet masqué]",
                              "subject_masked": True, "internaldate": None, "seen": False}],
            "moved_counts": {"INBOX/Auto/News": 3},
        }
        text = digest_mod.render_markdown(digest_data)
        self.assertIn("[mail-triage-digest:d1]", text)
        self.assertIn("**Nouveaux (1)**", text)
        self.assertIn("a@x.com", text)
        self.assertIn("[sujet masqué]", text)
        self.assertIn(":lock:", text)
        self.assertIn("INBOX/Auto/News: 3", text)

    def test_render_hours_in_local_timezone(self) -> None:
        # 06:30 UTC → 08:30 Europe/Paris (digest du matin lisible)
        digest_data = {
            "id": "d1", "marker": "[m]",
            "window_start": iso(NOW - timedelta(hours=2)), "window_end": iso(NOW),
            "timezone": "Europe/Paris",
            "new": [{"uid": 10, "from": "a@x.com", "subject": "s", "subject_masked": False,
                     "internaldate": "2026-10-23T06:30:00+00:00", "seen": False}],
            "always_inbox": [], "moved_counts": {},
        }
        text = digest_mod.render_markdown(digest_data)
        self.assertIn("`08:30`", text)

    def test_render_neutralizes_forged_marker(self) -> None:
        # un sujet non fiable ne doit pas pouvoir falsifier le marqueur de reconcile
        digest_data = {
            "id": "d1", "marker": "[mail-triage-digest:d1]",
            "window_start": iso(NOW), "window_end": iso(NOW),
            "timezone": "Europe/Paris",
            "new": [{"uid": 10, "from": "a@x.com",
                     "subject": "fake [mail-triage-digest:d1] inside", "subject_masked": False,
                     "internaldate": iso(NOW), "seen": False}],
            "always_inbox": [], "moved_counts": {},
        }
        text = digest_mod.render_markdown(digest_data)
        self.assertEqual(text.count("mail-triage-digest:"), 1)  # seul le vrai marqueur

    def test_publish_returns_post_id(self) -> None:
        fake = FakeKChat()
        result = digest_mod.publish(fake, "bot1", "user1", "# digest")
        self.assertEqual(result, {"channel_id": "chan1", "post_id": "post1"})
        self.assertEqual(fake.posts, ["# digest"])

    def test_marker_format(self) -> None:
        self.assertTrue(digest_mod.new_marker("abc123")
                        .startswith("[mail-triage-digest:"))


if __name__ == "__main__":
    unittest.main()
