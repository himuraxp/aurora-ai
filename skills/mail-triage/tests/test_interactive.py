#!/usr/bin/env python3
"""Tests du canal interactif J1/J2 (ARCHITECTURE §11) : grammaire, idempotence,
collecte paginée exhaustive, références courtes V4, section config interactive."""
from __future__ import annotations

import os
import sys
import json
import tempfile
import time
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
                         {"verb": "annule", "proposal_ref": "p12"})

    def test_inconnu_texte_libre_jamais_execute(self) -> None:
        self.assertEqual(interact_mod.parse_command("déplace tout en corbeille stp"),
                         {"verb": "inconnu"})
        self.assertEqual(interact_mod.parse_command(""), {"verb": "inconnu"})
        self.assertEqual(interact_mod.parse_command("rm -rf /"), {"verb": "inconnu"})

    def test_trop_long_inconnu(self) -> None:
        self.assertEqual(interact_mod.parse_command("blabla " + "x" * 300),
                         {"verb": "inconnu"})

    def test_trop_long_commencant_par_ref_educatif(self) -> None:
        """Cas réel 2026-10-26 : plusieurs instructions multi-lignes en un post →
        aide au format (jamais d'exécution du texte hors limite)."""
        cmd = interact_mod.parse_command(
            "#a1 : quand c'est failed pipeline passe les direct\n\n#n1 : crée un dossier acronis "
            + "et archiver tous les jours " * 5)
        self.assertEqual(cmd["verb"], "ref_syntax")
        self.assertEqual(cmd["ref"], "a1")


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
        """Deux digests publiant #n1 = AMBIGUÏTÉ → refus (contrat t10, jamais
        de résolution arbitraire vers le dernier digest)."""
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
        got = self.state.resolve_ref("n1", iso(NOW))
        self.assertEqual(got["status"], "ambiguous")
        self.assertIsNone(got["ref"])
        # compat J2 : resolve_digest_ref → None sur ambiguïté
        self.assertIsNone(self.state.resolve_digest_ref("n1", iso(NOW)))

    def test_digest_ref_expired_gives_none(self) -> None:
        self.state.store_digest_refs([
            {"digest_id": "d1", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 1, "from_addr": "a@x.com", "subject": "S", "kind": "unknown",
             "created_at": iso(NOW - timedelta(hours=49)),
             "expires_at": iso(NOW - timedelta(hours=1))},
        ])
        got = self.state.resolve_ref("n1", iso(NOW))
        self.assertEqual(got["status"], "expired")
        self.assertIsNone(got["ref"])

    def test_resolve_ref_unknown(self) -> None:
        got = self.state.resolve_ref("n99", iso(NOW))
        self.assertEqual(got["status"], "unknown")

    def test_next_ref_number_monotonic(self) -> None:
        """Compteur monotone par type : jamais réutilisé, même après expiration
        (contrat t10 — références globalement non ambiguës)."""
        first = self.state.next_ref_number("n")
        second = self.state.next_ref_number("n")
        self.assertEqual(second, first + 1)
        other = self.state.next_ref_number("a")
        self.assertEqual(other, 1)  # compteurs indépendants par type

    def test_next_ref_number_initializes_above_existing(self) -> None:
        """Les refs pré-compteur (#n1 du premier digest V4) ne sont jamais
        réémises : initialisation = max existant + 1."""
        self.state.store_digest_refs([
            {"digest_id": "d1", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 1, "from_addr": "a@x.com", "subject": "S", "kind": "unknown",
             "created_at": iso(NOW), "expires_at": iso(NOW + timedelta(hours=48))},
        ])
        nxt = self.state.next_ref_number("n")
        self.assertEqual(nxt, 2)
        self.assertEqual(self.state.next_ref_number("n"), 3)

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
        self.assertIn("pas activées", client.replies[0])
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

    def test_assign_refs_monotonic_global(self) -> None:
        """assign_refs hors build : compteur monotone global (t10) — les refs
        ne sont JAMAIS réémises d'un digest à l'autre."""
        class FakeState:
            def last_confirmed_digest(self):
                return None

            def digested_msg_keys(self, mailbox, uidvalidity):
                return set()

            def moved_counts_since(self, since_iso):
                return {}

            def __init__(self):
                self._counters = {}

            def next_ref_number(self, kind):
                self._counters[kind] = self._counters.get(kind, 0) + 1
                return self._counters[kind]

        messages = [
            {"uid": 10, "from": "a@x.com", "subject": "À valider",
             "internaldate": iso(NOW - timedelta(minutes=10)), "seen": False,
             "message_id": "<m10@x>", "references": ""},
            {"uid": 20, "from": "b@x.com", "subject": "Sans règle",
             "internaldate": iso(NOW - timedelta(minutes=20)), "seen": False,
             "message_id": "<m20@x>", "references": ""},
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
        self.assertTrue(all(c.get("ref") is None for c in built["conversations"]))
        digest_mod.assign_refs(built, FakeState())
        refs = [c.get("ref") for c in built["conversations"]]
        self.assertIn("a1", refs)
        self.assertIn("n1", refs)
        self.assertEqual(digest_mod.DIGEST_FORMAT_VERSION, 4)


# --- J3 : destinations, propositions, limites, annule ---------------------------


class DestinationTestCase(unittest.TestCase):
    CFG = {"interactive": {"aliases": {"gitlab": "GitLab", "acronis": "Acronis"}},
           "destinations": {"allowlist": ["GitLab", "Acronis"]}}

    def test_alias_resolves_canonical(self) -> None:
        canonical, reason = interact_mod.resolve_destination("GitLab", self.CFG)
        self.assertEqual((canonical, reason), ("GitLab", "ok"))
        canonical, reason = interact_mod.resolve_destination("  gitlab  ", self.CFG)
        self.assertEqual((canonical, reason), ("GitLab", "ok"))

    def test_canonical_name_accepted_directly(self) -> None:
        canonical, reason = interact_mod.resolve_destination("Acronis", self.CFG)
        self.assertEqual((canonical, reason), ("Acronis", "ok"))

    def test_unknown_alias_refused(self) -> None:
        canonical, reason = interact_mod.resolve_destination("boite-mystere", self.CFG)
        self.assertIsNone(canonical)
        self.assertEqual(reason, "unknown_alias")

    def test_forbidden_destination_never_resolved(self) -> None:
        """t10 : un alias (ou un chemin) pointant vers Trash/Spam reste INTERDIT —
        l'allowlist ne neutralise jamais les exclusions absolues."""
        cfg = {"interactive": {"aliases": {"poubelle": "Trash"}},
               "destinations": {"allowlist": ["GitLab", "Trash"]}}
        canonical, reason = interact_mod.resolve_destination("poubelle", cfg)
        self.assertIsNone(canonical)
        self.assertEqual(reason, "forbidden")


REAL_NOW = datetime.now(timezone.utc)


def real_iso(dt: datetime) -> str:
    """Horodatage RÉEL (la résolution des refs compare au temps courant)."""
    return dt.isoformat(timespec="seconds")


class ProposalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir_path = Path(self._tmp.name)
        (self.dir_path / "locks").mkdir()
        (self.dir_path / "rules.json").write_text('{"rules": [], "sensitive_senders": []}',
                                                  encoding="utf-8")
        self.state = state_mod.State(self.dir_path / "state.sqlite")
        self.state.store_digest_refs([
            {"digest_id": "d1", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 42, "from_addr": "noreply@acronis.com", "subject": "Rapport",
             "kind": "unknown", "created_at": real_iso(REAL_NOW - timedelta(hours=1)),
             "expires_at": real_iso(REAL_NOW + timedelta(hours=47))},
            {"digest_id": "d1", "ref": "a1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 43, "from_addr": "gitlab@infomaniak.com", "subject": "Pipeline",
             "kind": "review", "created_at": real_iso(REAL_NOW - timedelta(hours=1)),
             "expires_at": real_iso(REAL_NOW + timedelta(hours=47))},
        ])
        self.cfg = {"interactive": {"enabled": True, "proposals_enabled": True,
                                    "aliases": {"gitlab": "GitLab", "acronis": "Acronis"},
                                    "max_pending_proposals": 10,
                                    "max_rule_proposals_per_day": 5,
                                    "max_commands_per_5min": 30},
                    "destinations": {"allowlist": ["GitLab", "Acronis"]}}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _handle(self, cmd: dict) -> str:
        return interact_mod.handle_command(cmd, self.cfg, self.state, self.dir_path,
                                           "owner", "chan1", "post-1")

    def test_item_move_creates_proposal(self) -> None:
        reply = self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        self.assertIn("#p1", reply)
        self.assertIn("`GitLab`", reply)
        self.assertIn("ok #p1", reply)
        proposal = self.state.get_proposal("p1")
        self.assertEqual(proposal["kind"], "move")
        self.assertEqual(proposal["status"], "pending")
        action = json.loads(proposal["action"])
        self.assertEqual(action["type"], "move")
        self.assertEqual(action["uid"], 42)
        self.assertEqual(action["folder"], "GitLab")
        self.assertTrue(proposal["target_version"].startswith("sha256:"))
        self.assertEqual(proposal["source_post_id"], "post-1")

    def test_item_move_second_ref_monotonic(self) -> None:
        self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        reply = self._handle({"verb": "item_move", "ref": "a1", "dest_text": "Acronis"})
        self.assertIn("#p2", reply)  # ids opaques monotones, jamais réutilisés

    def test_unknown_alias_gets_syntax_help(self) -> None:
        reply = self._handle({"verb": "item_move", "ref": "n1", "dest_text": "archive-sans-nom"})
        self.assertIn("Aliases disponibles", reply)
        self.assertIsNone(self.state.get_proposal("p1"))

    def test_forbidden_alias_refused(self) -> None:
        self.cfg["interactive"]["aliases"]["poubelle"] = "Trash"
        self.cfg["destinations"]["allowlist"].append("Trash")
        reply = self._handle({"verb": "item_move", "ref": "n1", "dest_text": "poubelle"})
        self.assertIn("interdite", reply)
        self.assertIsNone(self.state.get_proposal("p1"))

    def test_ambiguous_ref_refused(self) -> None:
        """Deux digests avec #n1 actifs → REFUS (t10), jamais le dernier gagne."""
        self.state.store_digest_refs([
            {"digest_id": "d0", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 999, "from_addr": "other@x.com", "subject": "Autre",
             "kind": "unknown", "created_at": real_iso(REAL_NOW - timedelta(days=1)),
             "expires_at": real_iso(REAL_NOW + timedelta(hours=40))},
        ])
        reply = self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        self.assertIn("ambiguë", reply)
        self.assertIsNone(self.state.get_proposal("p1"))

    def test_unknown_and_expired_ref(self) -> None:
        self.assertIn("inconnue", self._handle({"verb": "item_move", "ref": "n9",
                                                "dest_text": "gitlab"}))
        self.state.store_digest_refs([
            {"digest_id": "d2", "ref": "n2", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 5, "from_addr": "a@x.com", "subject": "S", "kind": "unknown",
             "created_at": real_iso(REAL_NOW - timedelta(hours=49)),
             "expires_at": real_iso(REAL_NOW - timedelta(hours=1))},
        ])
        self.assertIn("périmée", self._handle({"verb": "item_move", "ref": "n2",
                                               "dest_text": "gitlab"}))

    def test_rule_proposal_sender_then_domain(self) -> None:
        reply = self._handle({"verb": "rule_create", "scope": "expediteur",
                              "value": "noreply@acronis.com", "dest_text": "acronis"})
        self.assertIn("#p1", reply)
        self.assertIn("mode propose", reply)
        rule = json.loads(self.state.get_proposal("p1")["action"])["rule"]
        self.assertEqual(rule["mode"], "propose")
        # F-03 (J4) : les règles interactives « expediteur » matchent l'ADRESSE
        # EXACTE (from_exact), jamais la sous-chaîne de from_any.
        self.assertEqual(rule["match"], {"from_exact": ["noreply@acronis.com"]})
        self.assertEqual(rule["priority"], 150)
        self.assertEqual(rule["folder"], "Acronis")

        reply2 = self._handle({"verb": "rule_create", "scope": "domaine",
                               "value": "Acronis.com", "dest_text": "acronis"})
        self.assertIn("#p2", reply2)
        rule2 = json.loads(self.state.get_proposal("p2")["action"])["rule"]
        self.assertEqual(rule2["match"], {"from_domain_any": ["acronis.com"]})
        self.assertEqual(rule2["priority"], 155)  # domaine plus large → perd les égalités

    def test_rule_invalid_values_refused(self) -> None:
        self.assertIn("invalide", self._handle({"verb": "rule_create", "scope": "expediteur",
                                                "value": "pas-un-email", "dest_text": "acronis"}))
        self.assertIn("invalide", self._handle({"verb": "rule_create", "scope": "domaine",
                                                "value": "acronis.com/x", "dest_text": "acronis"}))
        self.assertIsNone(self.state.get_proposal("p1"))

    def test_annule_cancels_pending_only(self) -> None:
        self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        self.assertIn("annulée", self._handle({"verb": "annule", "proposal_ref": "p1"}))
        self.assertEqual(self.state.get_proposal("p1")["status"], "cancelled")
        self.assertIn("inconnue ou déjà traitée",
                      self._handle({"verb": "annule", "proposal_ref": "p1"}))

    def test_ok_still_pending_j4(self) -> None:
        """Kill switch (test de sortie #9, §11.8) : sans gates d'écriture,
        `ok #p1` = accusé et AUCUN write — la proposition reste pending."""
        self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        reply = self._handle({"verb": "ok", "proposal_ref": "p1"})
        self.assertIn("pas encore activées", reply)
        self.assertEqual(self.state.get_proposal("p1")["status"], "pending")

    def test_ok_digest_ref_gets_dedicated_reply(self) -> None:
        """F-09 : `ok #n1` (ref de digest, pas une proposition) — réponse dédiée,
        jamais « la proposition reste en attente » (trompeur)."""
        reply = self._handle({"verb": "ok", "proposal_ref": "n1"})
        self.assertIn("référence de digest", reply)
        self.assertIn("#p", reply)

    def test_expired_proposal_releases_budget(self) -> None:
        """F-01 : une proposition EXPIRÉE libère le budget « simultanées » —
        sans le sweep, le canal se bloque définitivement après max propositions."""
        self.cfg["interactive"]["max_pending_proposals"] = 1
        self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        self.assertIn("Trop de propositions",
                      self._handle({"verb": "item_move", "ref": "a1", "dest_text": "gitlab"}))
        # faire expirer p1 puis sweeper (comme run_once en tête de tour)
        conn = state_mod.sqlite3.connect(self.state.path)
        conn.execute("UPDATE proposals SET expires_at='2020-01-01T00:00:00+00:00' "
                     "WHERE proposal_id='p1'")
        conn.commit()
        conn.close()
        self.state.expire_stale_proposals(interact_mod._now_iso())
        self.assertEqual(self.state.pending_proposals_count(), 0)
        reply = self._handle({"verb": "item_move", "ref": "a1", "dest_text": "gitlab"})
        self.assertIn("#p2", reply)  # budget libéré, ids toujours monotones

    def test_annule_owner_crosscheck(self) -> None:
        """F-07 : une proposition d'un autre owner/canal → refus « inconnue »
        (ne rien divulguer)."""
        self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        reply = interact_mod.handle_command(
            {"verb": "annule", "proposal_ref": "p1"}, self.cfg, self.state, self.dir_path,
            "ATTACKER", "chan1", "post-9")
        self.assertIn("inconnue ou déjà traitée", reply)
        self.assertEqual(self.state.get_proposal("p1")["status"], "pending")

    def test_md_echo_neutralized(self) -> None:
        """F-08 : un From non fiable n'est jamais écho en markdown cliquable."""
        self.state.store_digest_refs([
            {"digest_id": "d3", "ref": "n3", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 7, "from_addr": "[Urgent](http://evil) <a@b.c>", "subject": "S",
             "kind": "unknown", "created_at": real_iso(REAL_NOW - timedelta(hours=1)),
             "expires_at": real_iso(REAL_NOW + timedelta(hours=47))},
        ])
        reply = self._handle({"verb": "item_move", "ref": "n3", "dest_text": "gitlab"})
        self.assertNotIn("[Urgent](http://evil)", reply)
        self.assertIn("(Urgent)(http://evil)", reply)

    def test_next_ref_concurrent_allocations_distinct(self) -> None:
        """F-02 : BEGIN IMMEDIATE — deux allocations concurrentes (connexions
        distinctes) ne peuvent JAMAIS retourner le même numéro."""
        import threading
        results: list[int] = []
        barrier = threading.Barrier(2)

        def allocate():
            barrier.wait()
            results.append(self.state.next_ref_number("n"))

        self.state.store_digest_refs([
            {"digest_id": "d1", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 1, "from_addr": "a@x.com", "subject": "S", "kind": "unknown",
             "created_at": real_iso(REAL_NOW), "expires_at": real_iso(REAL_NOW + timedelta(hours=48))},
        ])
        threads = [threading.Thread(target=allocate) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [2, 3])  # distincts, au-dessus de n1

    def test_resolve_ref_mixed_time_precision(self) -> None:
        """F-05 : expires_at en précision « seconds » (triage) vs now en
        microsecondes (interact) — l'ordre lexicographique reste correct."""
        self.state.store_digest_refs([
            {"digest_id": "d1", "ref": "n4", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 4, "from_addr": "a@x.com", "subject": "S", "kind": "unknown",
             "created_at": "2026-10-25T06:05:02+00:00",
             "expires_at": "2099-10-27T07:05:02+00:00"},
            {"digest_id": "d2", "ref": "n5", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 5, "from_addr": "b@x.com", "subject": "S", "kind": "unknown",
             "created_at": "2026-10-25T06:05:02+00:00",
             "expires_at": "2020-10-27T07:05:02+00:00"},
        ])
        now_micro = "2026-10-26T06:07:39.062556+00:00"
        self.assertEqual(self.state.resolve_ref("n4", now_micro)["status"], "ok")
        self.assertEqual(self.state.resolve_ref("n5", now_micro)["status"], "expired")

    def test_gate_off_triage_verbs_acknowledged(self) -> None:
        self.cfg["interactive"]["proposals_enabled"] = False
        reply = self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        self.assertIn("pas activées", reply)
        self.assertIsNone(self.state.get_proposal("p1"))

    def test_pending_limit_refuses(self) -> None:
        self.cfg["interactive"]["max_pending_proposals"] = 1
        self._handle({"verb": "item_move", "ref": "n1", "dest_text": "gitlab"})
        reply = self._handle({"verb": "item_move", "ref": "a1", "dest_text": "gitlab"})
        self.assertIn("Trop de propositions", reply)

    def test_rule_daily_limit(self) -> None:
        self.cfg["interactive"]["max_rule_proposals_per_day"] = 1
        self._handle({"verb": "rule_create", "scope": "expediteur",
                      "value": "a@b.com", "dest_text": "acronis"})
        reply = self._handle({"verb": "rule_create", "scope": "domaine",
                              "value": "b.com", "dest_text": "acronis"})
        self.assertIn("quotidienne", reply)

    def test_ref_syntax_educational(self) -> None:
        """Cas réel 2026-10-26 : `#a1 : texte libre` → aide au format, jamais
        d'exécution du texte."""
        cmd = interact_mod.parse_command("#a1 : quand c'est failed pipeline passe les direct")
        self.assertEqual(cmd["verb"], "ref_syntax")
        self.assertEqual(cmd["ref"], "a1")
        reply = self._handle(cmd)
        self.assertIn("Format attendu", reply)
        self.assertIn("→", reply)
        self.assertIsNone(self.state.get_proposal("p1"))

    def test_rate_limit_30_per_5min(self) -> None:
        self.cfg["interactive"]["max_commands_per_5min"] = 1
        now_ms = int(time.time() * 1000)

        class Client:
            def __init__(self, state):
                self.state = state
                self.pages = [[post("p2", now_ms - 2000, message="aide"),
                               post("p1", now_ms - 3000, message="statut")]]
                self.replies: list[str] = []

            def me(self):
                return {"id": "bot"}

            def ensure_direct_channel(self, bot_id, user_id):
                return "chan1"

            def recent_channel_posts(self, channel_id, per_page=30):
                return self.pages[0] if self.pages else []

            def channel_posts_before(self, channel_id, before, per_page=30):
                return []

            def post_message(self, channel_id, message):
                self.replies.append(message)
                return {"id": f"r{len(self.replies)}"}

        client = Client(self.state)
        got = interact_mod.run_once(self.cfg, self.state, self.dir_path,
                                    client, "owner", lambda *a: None)  # baseline
        client.pages = [[post("p4", now_ms - 500, message="aide"),
                         post("p3", now_ms - 1000, message="statut"),
                         post("p2", now_ms - 2000, message="aide")]]
        got2 = interact_mod.run_once(self.cfg, self.state, self.dir_path,
                                     client, "owner", lambda *a: None)
        self.assertEqual(got2["processed"], 2)
        self.assertEqual(len(client.replies), 2)
        self.assertIn("Trop de commandes", client.replies[1])  # 2e commande floodée


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
