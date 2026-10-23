#!/usr/bin/env python3
"""Tests du canal interactif J1/J2 (ARCHITECTURE §11) : grammaire, idempotence,
collecte paginée exhaustive, références courtes V4, section config interactive."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import config as config_mod  # noqa: E402
import digest as digest_mod  # noqa: E402
import interact as interact_mod  # noqa: E402
import state as state_mod  # noqa: E402

NOW = datetime(2026, 10, 23, 8, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# --- grammaire (§11.6) ---------------------------------------------------------


class ParseCommandTestCase(unittest.TestCase):
    def test_aide(self) -> None:
        self.assertEqual(interact_mod.parse_command("aide"), {"verb": "aide"})
        self.assertEqual(interact_mod.parse_command("  Aide  "), {"verb": "aide"})
        self.assertEqual(interact_mod.parse_command("help"), {"verb": "aide"})

    def test_statut(self) -> None:
        self.assertEqual(interact_mod.parse_command("statut"), {"verb": "statut"})
        self.assertEqual(interact_mod.parse_command("STATUT"), {"verb": "statut"})

    def test_item_move_fleches(self) -> None:
        cmd = interact_mod.parse_command("#n1 → INBOX/Auto/News")
        self.assertEqual(cmd["verb"], "item_move")
        self.assertEqual(cmd["ref"], "n1")
        self.assertEqual(cmd["dest_text"], "INBOX/Auto/News")
        cmd2 = interact_mod.parse_command("#A3 -> Dossiers/X")
        self.assertEqual((cmd2["ref"], cmd2["dest_text"]), ("a3", "Dossiers/X"))

    def test_rule_create(self) -> None:
        cmd = interact_mod.parse_command("expediteur noreply@acronis.com → Corbeille")
        self.assertEqual(cmd["verb"], "rule_create")
        self.assertEqual(cmd["scope"], "expediteur")
        self.assertEqual(cmd["value"], "noreply@acronis.com")
        self.assertEqual(cmd["dest_text"], "Corbeille")
        cmd2 = interact_mod.parse_command("domaine acronis.com → INBOX/Auto")
        self.assertEqual((cmd2["scope"], cmd2["value"]), ("domaine", "acronis.com"))
        cmd3 = interact_mod.parse_command("expéditeur a@b.c -> X")
        self.assertEqual(cmd3["scope"], "expediteur")  # accent normalisé par regex

    def test_ok_et_annule(self) -> None:
        self.assertEqual(interact_mod.parse_command("ok #p1"),
                         {"verb": "ok", "proposal_ref": "p1"})
        self.assertEqual(interact_mod.parse_command("Annule #p12"),
                         {"verb": "annule"})

    def test_inconnu_texte_libre_jamais_execute(self) -> None:
        self.assertEqual(interact_mod.parse_command("déplace tout en corbeille stp"),
                         {"verb": "inconnu"})
        self.assertEqual(interact_mod.parse_command(""), {"verb": "inconnu"})
        self.assertEqual(interact_mod.parse_command("rm -rf /"), {"verb": "inconnu"})

    def test_trop_long_inconnu(self) -> None:
        self.assertEqual(interact_mod.parse_command("#n1 → " + "x" * 300),
                         {"verb": "inconnu"})


# --- état : idempotence, checkpoint, refs, propositions ------------------------


class StateInteractiveTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_record_command_idempotent(self) -> None:
        first = self.state.record_command("p1", "chan1", 1000, "owner", "aide")
        self.assertTrue(first)
        replay = self.state.record_command("p1", "chan1", 1000, "owner", "aide")
        self.assertFalse(replay)  # rejeu → jamais de double traitement

    def test_set_command_result_roundtrip(self) -> None:
        self.state.record_command("p1", "chan1", 1000, "owner", "statut")
        self.state.set_command_result("p1", "processed", "reply1", iso(NOW))
        conn = state_mod.sqlite3.connect(self.state.path)
        try:
            row = conn.execute(
                "SELECT status, reply_post_id, processed_at FROM interactive_commands "
                "WHERE post_id='p1'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("processed", "reply1", iso(NOW)))

    def test_checkpoint_roundtrip(self) -> None:
        self.assertIsNone(self.state.interactive_checkpoint())
        self.state.set_interactive_checkpoint(12345, "post9", iso(NOW))
        self.assertEqual(self.state.interactive_checkpoint(),
                         {"last_created_at": 12345, "last_post_id": "post9"})
        self.state.set_interactive_checkpoint(99999, "post10", iso(NOW))
        self.assertEqual(self.state.interactive_checkpoint(),
                         {"last_created_at": 99999, "last_post_id": "post10"})

    def test_digest_refs_store_and_resolve(self) -> None:
        rows = [{"digest_id": "d1", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
                 "uid": 42, "from_addr": "a@x.com", "subject": "Rapport",
                 "kind": "unknown", "created_at": iso(NOW - timedelta(hours=1)),
                 "expires_at": iso(NOW + timedelta(hours=47))}]
        self.state.store_digest_refs(rows)
        got = self.state.resolve_digest_ref("n1", iso(NOW))
        self.assertEqual(got["uid"], 42)
        self.assertEqual(got["digest_id"], "d1")

    def test_digest_ref_most_recent_wins(self) -> None:
        """Deux digests publient #n1 : la référence la plus récente gagne (§11.5)."""
        self.state.store_digest_refs([
            {"digest_id": "d_old", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 1, "from_addr": "old@x.com", "subject": "Ancien", "kind": "unknown",
             "created_at": iso(NOW - timedelta(days=2)),
             "expires_at": iso(NOW + timedelta(hours=24))},
            {"digest_id": "d_new", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 2, "from_addr": "new@x.com", "subject": "Récent", "kind": "unknown",
             "created_at": iso(NOW - timedelta(hours=1)),
             "expires_at": iso(NOW + timedelta(hours=47))},
        ])
        got = self.state.resolve_digest_ref("n1", iso(NOW))
        self.assertEqual(got["digest_id"], "d_new")
        self.assertEqual(got["uid"], 2)

    def test_digest_ref_expired_gives_none(self) -> None:
        self.state.store_digest_refs([
            {"digest_id": "d1", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 1, "from_addr": "a@x.com", "subject": "S", "kind": "unknown",
             "created_at": iso(NOW - timedelta(hours=49)),
             "expires_at": iso(NOW - timedelta(hours=1))},
        ])
        self.assertIsNone(self.state.resolve_digest_ref("n1", iso(NOW)))

    def test_create_proposal_roundtrip(self) -> None:
        self.state.create_proposal({
            "proposal_id": "p1", "kind": "rule", "owner_user_id": "owner",
            "channel_id": "chan1", "action": '{"scope":"domaine"}',
            "target_version": "sha256:abc", "created_at": iso(NOW),
            "expires_at": iso(NOW + timedelta(hours=24)), "source_post_id": "p0",
        })
        conn = state_mod.sqlite3.connect(self.state.path)
        try:
            row = conn.execute(
                "SELECT kind, status, source_post_id FROM proposals "
                "WHERE proposal_id='p1'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("rule", "pending", "p0"))


# --- collecte paginée exhaustive (§11.3) ---------------------------------------


class FakePostsClient:
    """Client factice : pages fixes du plus récent au plus ancien."""

    def __init__(self, pages: list[list[dict]]) -> None:
        self.pages = pages
        self.calls: list[str | None] = []

    def recent_channel_posts(self, channel_id: str, per_page: int = 30) -> list[dict]:
        return self._page(0)

    def channel_posts_before(self, channel_id: str, before: str,
                             per_page: int = 30) -> list[dict]:
        idx = self.calls[-1] if self.calls else None
        self.calls.append(before)
        # page suivante = la première contenant un post plus ancien que `before`
        for i, page in enumerate(self.pages):
            ids = {p["id"] for p in page}
            if before in ids and i + 1 < len(self.pages):
                return self.pages[i + 1]
        return []

    def _page(self, i: int) -> list[dict]:
        self.calls.append(None)
        return self.pages[i] if i < len(self.pages) else []


def post(pid: str, created: int, user: str = "owner", **over) -> dict:
    p = {"id": pid, "user_id": user, "create_at": created, "edit_at": 0,
         "delete_at": 0, "message": "aide"}
    p.update(over)
    return p


class CollectTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_baseline_no_checkpoint_returns_empty(self) -> None:
        client = FakePostsClient([[post("p5", 500), post("p4", 400)]])
        got = interact_mod.collect_new_posts(client, "chan", "owner", self.state)
        self.assertEqual(got, [])  # baseline : jamais l'historique antérieur

    def test_pagination_stops_at_checkpoint_and_sorts(self) -> None:
        self.state.set_interactive_checkpoint(400, "p4", iso(NOW))
        # page 1 : p7 (nouveau) + p6 (intrus) + p5 (nouveau) ; page 2 : sous le checkpoint
        pages = [
            [post("p7", 700), post("p6", 600, user="intruder"), post("p5", 500)],
            [post("p3", 300), post("p2", 200)],
        ]
        client = FakePostsClient(pages)
        got = interact_mod.collect_new_posts(client, "chan", "owner", self.state)
        # checkpoint (400, p4) atteint → stop ; p3/p2 exclus (sous le checkpoint) ;
        # tri croissant (create_at, post_id). L'intrus p6 est DANS la fenêtre
        # collectée : le filtre propriétaire vit dans run_once (point unique).
        self.assertEqual([p["id"] for p in got], ["p5", "p6", "p7"])

    def test_checkpoint_post_itself_excluded(self) -> None:
        self.state.set_interactive_checkpoint(500, "p5", iso(NOW))
        client = FakePostsClient([[post("p6", 600), post("p5", 500)]])
        got = interact_mod.collect_new_posts(client, "chan", "owner", self.state)
        self.assertEqual([p["id"] for p in got], ["p6"])

    def test_edited_and_deleted_excluded(self) -> None:
        self.state.set_interactive_checkpoint(100, "p1", iso(NOW))
        client = FakePostsClient([[post("p3", 300, edit_at=999),
                                   post("p2", 200, delete_at=999)]])
        got = interact_mod.collect_new_posts(client, "chan", "owner", self.state)
        self.assertEqual(got, [])

    def test_incomplete_pagination_fails_closed(self) -> None:
        """Pagination jamais revenue au checkpoint → InteractiveError, jamais
        d'avance du checkpoint sur un trou (§11.3)."""
        self.state.set_interactive_checkpoint(0, "p_never_seen", iso(NOW))
        # 2 pages sans le post du checkpoint (MAX_PAGES=20 ne les couvre pas)
        big_page = [post(f"p{i:03d}", 10_000 + i) for i in range(30)]
        client = FakePostsClient([big_page, big_page, big_page, big_page])
        with self.assertRaises(interact_mod.InteractiveError):
            interact_mod.collect_new_posts(client, "chan", "owner", self.state)

    def test_same_timestamp_ordering(self) -> None:
        """Posts à create_at égal : l'ordre (create_at, post_id) fixe l'ordre."""
        self.state.set_interactive_checkpoint(500, "p5b", iso(NOW))
        client = FakePostsClient([[post("p5c", 500), post("p5a", 500), post("p5b", 500),
                                   post("p5d", 500)]])
        got = interact_mod.collect_new_posts(client, "chan", "owner", self.state)
        self.assertEqual([p["id"] for p in got], ["p5c", "p5d"])


# --- run_once : lecture seule + baseline + idempotence --------------------------


class PollClient:
    """Client factice à pages mutables : run 1 = baseline, run 2 = nouvelle page."""

    def __init__(self, pages: list[list[dict]]) -> None:
        self.pages = pages
        self.replies: list[str] = []

    def me(self) -> dict:
        return {"id": "bot"}

    def ensure_direct_channel(self, bot_id: str, user_id: str) -> str:
        return "chan1"

    def recent_channel_posts(self, channel_id: str, per_page: int = 30) -> list[dict]:
        return self.pages[0] if self.pages else []

    def channel_posts_before(self, channel_id: str, before: str,
                             per_page: int = 30) -> list[dict]:
        for i, page in enumerate(self.pages):
            if any(p["id"] == before for p in page) and i + 1 < len(self.pages):
                return self.pages[i + 1]
        return []

    def post_message(self, channel_id: str, message: str) -> dict:
        self.replies.append(message)
        return {"id": f"r{len(self.replies)}"}


class RunOnceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir_path = Path(self._tmp.name)
        (self.dir_path / "locks").mkdir()
        self.state = state_mod.State(self.dir_path / "state.sqlite")
        self.audit_events: list[dict] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _cfg(self, enabled: bool = True) -> dict:
        return {"interactive": {"enabled": enabled}}

    def _audit(self, _path, event: dict) -> None:
        self.audit_events.append(event)

    def test_disabled_no_api_call(self) -> None:
        class Boom:
            def me(self):
                raise AssertionError("ne doit pas être appelé")

        got = interact_mod.run_once(self._cfg(False), self.state, self.dir_path,
                                    Boom(), "owner", self._audit)
        self.assertEqual(got, {"status": "disabled"})

    def test_baseline_then_processes_and_replies(self) -> None:
        """Run 1 = baseline (checkpoint posé, rien traité). Run 2 traite les
        nouveaux posts, avance le checkpoint, journalise l'audit (sans le texte)."""
        client = PollClient([[post("p2", 200, message="statut"),
                              post("p1", 100, message="aide")]])
        got1 = interact_mod.run_once(self._cfg(), self.state, self.dir_path,
                                     client, "owner", self._audit)
        self.assertEqual(got1["processed"], 0)
        self.assertTrue(got1["baseline"])
        # baseline : checkpoint posé sur le post le plus récent, sans traitement
        self.assertEqual(self.state.interactive_checkpoint(),
                         {"last_created_at": 200, "last_post_id": "p2"})

        client.pages = [[post("p4", 400, message="#n1 → INBOX/Auto/News"),
                         post("p3", 300, message="aide"),
                         post("p2", 200, message="statut")]]
        got2 = interact_mod.run_once(self._cfg(), self.state, self.dir_path,
                                     client, "owner", self._audit)
        self.assertEqual(got2["processed"], 2)  # p3 aide + p4 item_move
        self.assertEqual(self.state.interactive_checkpoint(),
                         {"last_created_at": 400, "last_post_id": "p4"})
        self.assertEqual([e["verb"] for e in self.audit_events], ["aide", "item_move"])
        self.assertNotIn("#n1 → INBOX/Auto/News", str(self.audit_events))  # jamais le texte
        # idempotence : rejeu du même tour → 0 traité
        got3 = interact_mod.run_once(self._cfg(), self.state, self.dir_path,
                                     client, "owner", self._audit)
        self.assertEqual(got3["processed"], 0)

    def test_run_ignores_non_owner_silently(self) -> None:
        client = PollClient([[post("p1", 100)]])
        interact_mod.run_once(self._cfg(), self.state, self.dir_path,
                              client, "owner", self._audit)  # baseline
        client.pages = [[post("p3", 300, user="intruder", message="aide"),
                         post("p0", 50)]]  # p0 sous le checkpoint → exclu
        got = interact_mod.run_once(self._cfg(), self.state, self.dir_path,
                                    client, "owner", self._audit)
        self.assertEqual(got["ignored"], 1)   # compteur technique sans contenu
        self.assertEqual(got["processed"], 0)
        self.assertEqual(self.audit_events, [])
        # l'intrus ne bloque pas le curseur
        self.assertEqual(self.state.interactive_checkpoint(),
                         {"last_created_at": 300, "last_post_id": "p3"})

    def test_mutation_verbs_acknowledged_not_executed(self) -> None:
        client = PollClient([[post("p1", 100)]])
        interact_mod.run_once(self._cfg(), self.state, self.dir_path,
                              client, "owner", self._audit)  # baseline
        client.pages = [[post("p2", 200, message="#n1 → INBOX/Auto/News")]]
        got = interact_mod.run_once(self._cfg(), self.state, self.dir_path,
                                    client, "owner", self._audit)
        self.assertEqual(got["processed"], 1)
        self.assertEqual(len(client.replies), 1)
        self.assertIn("pas encore activées", client.replies[0])
        # aucune écriture IMAP ni règle : aucun event autre que interactive_command
        self.assertTrue(all(e["event"] == "interactive_command"
                            for e in self.audit_events))


# --- rendu V4 : références courtes (§11.5) -------------------------------------


def conv(uid: int, frm: str, subject: str, internaldate: str, *, count: int = 1,
         label: str | None = None, mode: str | None = None,
         action: str = "keep") -> dict:
    items = [{"uid": uid + i, "from": frm, "subject": subject, "subject_masked": False,
              "message_id": f"<m{uid+i}@x>", "references": "",
              "internaldate": internaldate, "seen": False,
              "mode": mode, "rule_id": None, "decision_action": action}
             for i in range(count)]
    return {"items": items, "count": count, "title": subject,
            "label": label, "last_time": internaldate}


class RefsRenderTestCase(unittest.TestCase):
    @staticmethod
    def _built(conversations: list[dict], always: list[dict] | None = None) -> dict:
        return {
            "id": "d1", "marker": "[mail-triage-digest:d1]",
            "window_start": iso(NOW - timedelta(hours=2)),
            "window_end": iso(NOW), "timezone": "Europe/Paris",
            "conversations": conversations, "counters": {},
            "always_inbox": always or [], "moved_counts": {},
        }

    def test_render_includes_refs(self) -> None:
        review = conv(10, "a@x.com", "Planning", iso(NOW), label="à examiner", mode="propose")
        review["ref"] = "a1"
        unknown = conv(20, "b@x.com", "Rapport", iso(NOW))
        unknown["ref"] = "n1"
        text = digest_mod.render_markdown(self._built([review, unknown]))
        self.assertIn("#a1", text)
        self.assertIn("#n1", text)
        self.assertIn("à examiner", text.lower())

    def test_render_auto_without_ref(self) -> None:
        auto = conv(30, "c@x.com", "Notif", iso(NOW), count=2, action="move")
        auto["ref"] = None
        text = digest_mod.render_markdown(self._built([auto]))
        self.assertNotIn("#a1", text)
        self.assertNotIn("#n1", text)
        self.assertIn("c@x.com", text)

    def test_render_always_with_refs(self) -> None:
        always = [{"uid": 12, "from": "c@x.com", "subject": "Vieux", "subject_masked": False,
                   "internaldate": None, "seen": False, "ref": "l1"}]
        text = digest_mod.render_markdown(self._built([], always))
        self.assertIn("#l1", text)
        self.assertIn("Encore non lus", text)

    def test_digest_ref_rows_convs_and_always(self) -> None:
        review = conv(10, "a@x.com", "Planning", iso(NOW), label="à examiner", mode="propose")
        review["ref"] = "a1"
        unknown = conv(20, "b@x.com", "Rapport", iso(NOW))
        unknown["ref"] = "n1"
        auto = conv(30, "c@x.com", "Notif", iso(NOW), action="move")
        auto["ref"] = None  # pas de ref pour l'auto
        always = [{"uid": 12, "from": "c@x.com", "subject": "Vieux", "subject_masked": False,
                   "internaldate": None, "seen": False, "ref": "l1"}]
        rows = digest_mod.digest_ref_rows(
            self._built([review, unknown, auto], always), "INBOX", 7, iso(NOW))
        kinds = {r["ref"]: r["kind"] for r in rows}
        self.assertEqual(kinds, {"a1": "review", "n1": "unknown", "l1": "always"})
        for row in rows:
            self.assertEqual(row["digest_id"], "d1")
            self.assertEqual(row["uidvalidity"], 7)
            self.assertEqual(row["mailbox"], "INBOX")
            exp = datetime.fromisoformat(row["expires_at"])
            created = datetime.fromisoformat(row["created_at"])
            self.assertEqual(exp - created, timedelta(hours=digest_mod.REF_EXPIRY_HOURS))

    def test_digest_ref_rows_one_message_per_conv(self) -> None:
        """1 ref = 1 message : le DERNIER de la conversation (§11.5) — jamais
        un thread entier de N notifications."""
        multi = conv(40, "d@x.com", "Thread GitLab", iso(NOW), count=3)
        multi["ref"] = "n1"
        rows = digest_mod.digest_ref_rows(self._built([multi]), "INBOX", 7, iso(NOW))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["uid"], 42)  # 40 + 2 = dernier message

    def test_build_digest_assigns_refs(self) -> None:
        class FakeState:
            def last_confirmed_digest(self):
                return None

            def digested_msg_keys(self, mailbox, uidvalidity):
                return set()

            def moved_counts_since(self, since_iso):
                return {}

        messages = [
            {"uid": 10, "from": "a@x.com", "subject": "À valider",
             "internaldate": iso(NOW - timedelta(minutes=10)), "seen": False,
             "message_id": "<m10@x>", "references": ""},
            {"uid": 20, "from": "b@x.com", "subject": "Sans règle",
             "internaldate": iso(NOW - timedelta(minutes=20)), "seen": False,
             "message_id": "<m20@x>", "references": ""},
            {"uid": 30, "from": "c@x.com", "subject": "Notif CI",
             "internaldate": iso(NOW - timedelta(minutes=30)), "seen": False,
             "message_id": "<m30@x>", "references": ""},
        ]
        cfg = {"digest": {"enabled": True, "lookback_hours": 18, "always_inbox_cap": 10,
                          "min_interval_hours": 20, "sensitive_subject_patterns": []},
               "source": {"mailbox": "INBOX"},
               "rules": {"rules": [{"id": "r1", "mode": "propose",
                                    "match": {"subject_any": ["À valider"]},
                                    "folder": "INBOX/Auto/X", "priority": 10}],
                         "sensitive_senders": []},
               "destinations": {"allowlist": ["INBOX/Auto/X"]}}
        built = digest_mod.build_digest(FakeState(), messages, cfg,
                                        {"start": NOW - timedelta(hours=2),
                                         "end": NOW}, "dX")
        refs = [c.get("ref") for c in built["conversations"]]
        self.assertIn("a1", refs)     # propose → #a1
        self.assertIn("n1", refs)     # unknown → #n1
        self.assertEqual(digest_mod.DIGEST_FORMAT_VERSION, 4)


# --- config : section interactive -----------------------------------------------


class ConfigInteractiveTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _base(self) -> str:
        return ('{\n'
                '  "account": {"host": "mail.example.com", "port": 993,\n'
                '              "password_env": "MAIL_TRIAGE_IMAP_PASSWORD"},\n'
                '  "source": {"mailbox": "INBOX"},\n'
                '  "destinations": {"allowlist": ["INBOX/Auto/X"]},\n'
                '  "writes": {"enabled": true, "imap_enabled": true, "digest_enabled": true}')

    def test_interactive_default_false(self) -> None:
        (self.dir_path / "config.json").write_text(self._base() + '\n}\n', encoding="utf-8")
        cfg = config_mod.load(self.dir_path)
        self.assertEqual(cfg["interactive"]["enabled"], False)

    def test_interactive_enabled_bool_validation(self) -> None:
        (self.dir_path / "config.json").write_text(
            self._base() + ',\n  "interactive": {"enabled": "oui"}\n}\n', encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir_path)


if __name__ == "__main__":
    unittest.main()
