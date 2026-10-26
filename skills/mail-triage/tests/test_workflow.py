#!/usr/bin/env python3
"""Tests J4bis — workflow « A lire »/« A traiter » (ARCHITECTURE §12).

Étape 1 : sémantique workflow_target (statut ≠ destination ≠ \\Seen).
Étape 3 : commande `workflow` read-only (comptages, zéro reclassification).
Étape 4 : plans/refs liés au dossier source (mailbox + uidvalidity + uid).
Étape 5 : clôture « traité » (move stockage + \\Seen réconcilié, idempotent).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import config as config_mod  # noqa: E402
import digest as digest_mod  # noqa: E402
import imap_client as imap_mod  # noqa: E402
import interact as interact_mod  # noqa: E402
import policy as policy_mod  # noqa: E402
import state as state_mod  # noqa: E402
import triage as triage_mod  # noqa: E402

REAL_NOW = datetime.now(timezone.utc)


def real_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# --- étape 1 : sémantique workflow_target ---------------------------------------


class WorkflowTargetPolicyTestCase(unittest.TestCase):
    MSG = {"from": "Bob <bob@x.com>", "subject": "Rapport", "to": ""}

    def test_auto_with_workflow_target_moves_to_workflow_folder(self) -> None:
        """D3 : la destination du déplacement initial = dossier workflow ;
        `folder` reste le stockage final (appliqué à la clôture « traité »)."""
        doc = {"rules": [{"id": "r1", "priority": 150, "mode": "auto",
                          "match": {"from_exact": ["bob@x.com"]},
                          "workflow_target": "A traiter", "folder": "GitLab"}],
               "sensitive_senders": []}
        result = policy_mod.evaluate(self.MSG, doc, ["GitLab", "A lire", "A traiter"])
        self.assertEqual(result["action"], "move")
        self.assertEqual(result["folder"], "A traiter")
        self.assertEqual(result["workflow_target"], "A traiter")
        self.assertEqual(result["final_folder"], "GitLab")

    def test_auto_workflow_target_without_folder(self) -> None:
        doc = {"rules": [{"id": "r1", "priority": 150, "mode": "auto",
                          "match": {"from_exact": ["bob@x.com"]},
                          "workflow_target": "A lire"}],
               "sensitive_senders": []}
        result = policy_mod.evaluate(self.MSG, doc, ["A lire", "A traiter"])
        self.assertEqual(result["action"], "move")
        self.assertEqual(result["folder"], "A lire")
        self.assertIsNone(result["final_folder"])

    def test_folder_only_unchanged_regression(self) -> None:
        """Régression : folder seul = comportement historique inchangé."""
        doc = {"rules": [{"id": "r1", "priority": 150, "mode": "auto",
                          "match": {"from_exact": ["bob@x.com"]}, "folder": "GitLab"}],
               "sensitive_senders": []}
        result = policy_mod.evaluate(self.MSG, doc, ["GitLab", "A lire", "A traiter"])
        self.assertEqual(result["action"], "move")
        self.assertEqual(result["folder"], "GitLab")
        self.assertIsNone(result["workflow_target"])
        self.assertEqual(result["final_folder"], "GitLab")

    def test_propose_with_workflow_target(self) -> None:
        doc = {"rules": [{"id": "r1", "priority": 150, "mode": "propose",
                          "match": {"from_exact": ["bob@x.com"]},
                          "workflow_target": "A traiter", "folder": "GitLab"}],
               "sensitive_senders": []}
        result = policy_mod.evaluate(self.MSG, doc, ["GitLab", "A traiter"])
        self.assertEqual(result["action"], "keep")
        self.assertEqual(result["folder"], "A traiter")

    def test_invalid_workflow_target_policy_error(self) -> None:
        doc = {"rules": [{"id": "r1", "priority": 150, "mode": "auto",
                          "match": {"from_exact": ["bob@x.com"]},
                          "workflow_target": "Corbeille", "folder": "GitLab"}],
               "sensitive_senders": []}
        with self.assertRaises(policy_mod.PolicyError):
            policy_mod.evaluate(self.MSG, doc, ["GitLab", "A lire", "A traiter"])

    def test_rules_validation_rejects_bad_workflow_target(self) -> None:
        with self.assertRaises(config_mod.ConfigError):
            config_mod.validate_rules_doc(
                {"rules": [{"id": "r1", "priority": 150, "mode": "auto",
                            "match": {"from_exact": ["bob@x.com"]},
                            "workflow_target": "A Trait  "}], "sensitive_senders": []})

    def test_rules_validation_requires_folder_or_workflow_target(self) -> None:
        with self.assertRaises(config_mod.ConfigError):
            config_mod.validate_rules_doc(
                {"rules": [{"id": "r1", "priority": 150, "mode": "auto",
                            "match": {"from_exact": ["bob@x.com"]}}],
                 "sensitive_senders": []})
        # propose + workflow_target sans folder = valide (stockage à la clôture)
        doc = config_mod.validate_rules_doc(
            {"rules": [{"id": "r1", "priority": 150, "mode": "propose",
                        "match": {"from_exact": ["bob@x.com"]},
                        "workflow_target": "A lire"}], "sensitive_senders": []})
        self.assertEqual(doc["rules"][0]["workflow_target"], "A lire")


# --- étape 3+4 : commande `workflow` read-only + plans liés au dossier source ----


class WorkflowFakeConn:
    """IMAP simulé pour le read-only + move workflow : STATUS riche, SEARCH, MOVE."""

    def __init__(self, *, counts: dict | None = None, absent=(), unseen: dict | None = None,
                 dest_mid: dict | None = None, mid_source: dict | None = None):
        self.capabilities = ("IMAP4REV1", "MOVE")
        self.moves: list[tuple[int, str, str]] = []
        self.stores: list[tuple[int, str]] = []
        # Review F-02 : trace des noms REÇUS (bruts) — un serveur IMAP réel
        # rejette (BAD) tout STATUS/SELECT/LIST avec espace non-quoté.
        self.raw_mailbox_names: list[str] = []
        self.mailboxes = {"INBOX", "GitLab", "A lire", "A traiter"} - set(absent)
        self.uidvalidity = {"INBOX": 7, "A lire": 8, "A traiter": 9}
        self.counts = counts or {"INBOX": (12, 4), "A lire": (3, 3), "A traiter": (2, 1)}
        self.unseen = unseen or {}
        self.dest_mid = dest_mid or {}      # mailbox → uids dest (SEARCH Message-ID)
        self.mid_source = mid_source or {}  # uid source → Message-ID (FETCH avant move)

    def capability(self):
        return "OK", [b"IMAP4REV1 MOVE"]

    def status(self, mailbox, spec):
        self.raw_mailbox_names.append(mailbox)
        name = mailbox.strip('"')
        if name not in self.mailboxes:
            return "NO", [b"unknown mailbox"]
        uv = self.uidvalidity.get(name, 1)
        total, unseen = self.counts.get(name, (0, 0))
        fields = {"UIDVALIDITY": str(uv), "MESSAGES": str(total), "UNSEEN": str(unseen)}
        wanted = [f for f in ("UIDVALIDITY", "MESSAGES", "UNSEEN") if f in (spec or "")]
        body = " ".join(f"{f} {fields[f]}" for f in wanted)
        return "OK", [f'"{name}" ({body})'.encode()]

    def list(self, ref=None):
        self.raw_mailbox_names.append(ref or "")
        name = (ref or "").strip('"')
        if name in self.mailboxes:
            return "OK", [f'(\\HasNoChildren) "/" "{name}"'.encode()]
        return "OK", []

    def select(self, mailbox, readonly=False):
        self.raw_mailbox_names.append(mailbox)
        self._selected = mailbox.strip('"')
        return "OK", [b"0"]

    def uid(self, command, *args):
        command = command.upper()
        if command == "MOVE":
            # IMAP réel : le MOVE s'applique à la mailbox SÉLECTIONNÉE (uid_move
            # fait select(source, readonly=False) avant) — jamais un arg MOVE.
            uid = int(args[0])
            dest = args[1].strip('"')
            source = self._selected or "INBOX"
            self.moves.append((uid, source, dest))
            return "OK", [b""]
        if command == "SEARCH":
            query = str(args[-1] if args else "")
            name = self._selected or "INBOX"
            if "HEADER" in query.upper():
                return "OK", [self.dest_mid.get(name, b"")]
            return "OK", [self.unseen.get((name, query), b"")]
        if command == "STORE":
            uid = int(args[0])
            flags = " ".join(str(a) for a in args[1:])
            self.stores.append((uid, flags))
            return "OK", [b""]
        if command == "FETCH":
            mid = self.mid_source.get(int(args[0]))
            if mid is None:
                return "OK", [b""]
            return "OK", [(b"1 (UID %d)" % int(args[0]),
                           b"Message-ID: " + mid + b"\r\n\r\n")]
        raise AssertionError(f"uid({command}) inattendu")

    _selected = None

    def logout(self):
        return "BYE", [b""]


class WorkflowCommandTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir_path = Path(self._tmp.name)
        (self.dir_path / "locks").mkdir()
        (self.dir_path / "rules.json").write_text('{"rules": [], "sensitive_senders": []}',
                                                  encoding="utf-8")
        self.state = state_mod.State(self.dir_path / "state.sqlite")
        self.cfg = {"writes": {"enabled": True, "imap_enabled": True,
                               "digest_enabled": True, "interactive_rules": False},
                    "interactive": {"enabled": True, "proposals_enabled": True,
                                    "aliases": {"gitlab": "GitLab", "lire": "A lire",
                                                "traiter": "A traiter"},
                                    "max_pending_proposals": 10,
                                    "max_rule_proposals_per_day": 5,
                                    "max_commands_per_5min": 30},
                    "destinations": {"allowlist": ["GitLab", "A lire", "A traiter"]},
                    "source": {"mailbox": "INBOX"},
                    "account": {"host": "h", "port": 993, "login_env": "X",
                                "password_env": "Y"},
                    "plan": {"expire_hours": 24},
                    "_config_dir": str(self.dir_path)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _patch(self, conn):
        stack = mock.patch.object(triage_mod, "_connect_imap", lambda cfg: conn)
        stack2 = mock.patch.object(imap_mod, "connect", lambda *a, **k: conn)
        return stack, stack2

    def test_workflow_counts_read_only(self) -> None:
        """Étape 3 : comptages + refs non lus (refs = dossier source + uv + uid),
        aucune mutation IMAP (FakeConn lève si MOVE/STORE est appelé)."""
        conn = WorkflowFakeConn(unseen={
            ("A lire", "UNSEEN"): b"101 102",
            ("A traiter", "UNSEEN"): b"55",
            ("INBOX", "UNSEEN"): b"900 901 902",
        })
        stack, stack2 = self._patch(conn)
        with stack, stack2:
            code, payload = None, None
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = triage_mod.cmd_workflow(self.cfg, None)
        self.assertEqual(code, 0)
        out = json.loads(buf.getvalue())
        folders = out["folders"]
        self.assertEqual(folders["A lire"]["total"], 3)
        self.assertEqual(folders["A lire"]["unseen"], 3)
        self.assertEqual([r["uid"] for r in folders["A lire"]["unseen_refs"]], [101, 102])
        self.assertEqual(folders["A lire"]["unseen_refs"][0]["mailbox"], "A lire")
        self.assertEqual(folders["A lire"]["unseen_refs"][0]["uidvalidity"], 8)
        self.assertEqual(folders["A traiter"]["unseen_refs"], [{"mailbox": "A traiter",
                                                                "uidvalidity": 9, "uid": 55}])
        self.assertEqual(folders["INBOX"]["total"], 12)
        self.assertEqual(conn.moves, [])  # read-only strict

    def test_workflow_absent_folder_signal(self) -> None:
        """Dossier workflow absent → exists:false, jamais de création ni de crash."""
        conn = WorkflowFakeConn(absent=("A traiter",))
        stack, stack2 = self._patch(conn)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with stack, stack2, redirect_stdout(buf):
            code = triage_mod.cmd_workflow(self.cfg, None)
        self.assertEqual(code, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["folders"]["A traiter"], {"exists": False})

    def test_apply_from_workflow_folder_source(self) -> None:
        """Étape 4 (D7) : un plan est lié à son dossier source — apply depuis
        « A traiter » (move["from_folder"]) fonctionne et UID MOVE porte la
        bonne source (jamais INBOX pinné)."""
        payload = {"mailbox": "A traiter", "uidvalidity": 9,
                   "moves": [{"uid": 55, "from_folder": "A traiter", "to_folder": "GitLab",
                              "rule_id": "r1", "from_hash": "abc", "message_id": "<m@x>"}],
                   "created_at": real_iso(REAL_NOW)}
        plan_id = "wf-plan-1"
        self.state.create_plan(plan_id, real_iso(REAL_NOW),
                               real_iso(REAL_NOW + timedelta(hours=2)), payload)
        conn = WorkflowFakeConn()
        stack, stack2 = self._patch(conn)
        with stack, stack2:
            result = triage_mod.run_plan_apply(self.cfg, self.state, self.dir_path, plan_id)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(conn.moves, [(55, "A traiter", "GitLab")])  # source = dossier du plan

    def test_workflow_quotes_mailboxes_with_spaces(self) -> None:
        """Review F-02 : « A lire »/« A traiter » contiennent des espaces —
        STATUS/SELECT/LIST doivent recevoir un quoted-string (sinon BAD sur un
        serveur réel), jamais le nom brut. J4bis serait inopérant en prod sinon."""
        conn = WorkflowFakeConn()
        stack, stack2 = self._patch(conn)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with stack, stack2, redirect_stdout(buf):
            code = triage_mod.cmd_workflow(self.cfg, None)
        self.assertEqual(code, 0)
        raws = conn.raw_mailbox_names
        for folder in ("A lire", "A traiter"):
            self.assertIn(f'"{folder}"', raws)      # quoté présent
            self.assertNotIn(folder, raws)          # brut JAMAIS reçu


# --- étape 5 : clôture « traité » (move stockage + \Seen réconcilié) ------------


# --- corrections review adversariale (F-01/F-02/F-03/F-04/F-08) ------------------


class _MidConn:
    """IMAP minimal pour _fetch_message_id : FETCH retourne un en-tête forgé."""

    def __init__(self, header_bytes: bytes):
        self._h = header_bytes

    def list(self, ref=None):
        return "OK", []

    def select(self, mailbox, readonly=True):
        return "OK", [b"0"]

    def uid(self, command, *args):
        assert command.upper() == "FETCH"
        return "OK", [(b"1 (UID 42)", self._h)]


class InjectionGuardTestCase(unittest.TestCase):
    """Review F-01 : le Message-ID est une donnée NON FIABLE — dépliage RFC 5322
    et rejet de tout contrôle ; _escape_imap_string supprime CR/LF (imaplib
    3.9.6 LIVE n'assume aucune validation → jamais d'injection de commande)."""

    def test_folded_message_id_unfolded_no_crlf(self) -> None:
        move = {"uid": 42, "from_folder": "INBOX"}
        mid = triage_mod._fetch_message_id(
            _MidConn(b"Message-ID: <a\r\n b@c.com>\r\n\r\n"), move)
        self.assertEqual(mid, "<a b@c.com>")
        self.assertNotIn("\r", mid)
        self.assertNotIn("\n", mid)

    def test_control_chars_rejected_fail_closed(self) -> None:
        move = {"uid": 42, "from_folder": "INBOX"}
        self.assertIsNone(triage_mod._fetch_message_id(
            _MidConn(b"Message-ID: <a\x01b@c.com>\r\n\r\n"), move))

    def test_escape_imap_string_neutralizes_controls(self) -> None:
        dirty = ('<a\r\nA002 SELECT INBOX\r\n'
                 'A003 UID STORE 1:* +FLAGS (\\Deleted)\r\n'
                 'A004 EXPUNGE\r\nb>')
        clean = triage_mod._escape_imap_string(dirty)
        self.assertNotIn("\r", clean)
        self.assertNotIn("\n", clean)
        # sans délimiteur CRLF, les octets restent dans l'argument quoted-string
        # (inertes) — aucune ligne de commande n'est délimitée


class TreatCommandTestCase(WorkflowCommandTestCase):
    def _store_workflow_ref(self) -> None:
        self.state.store_digest_refs([
            {"digest_id": "dw", "ref": "l1", "mailbox": "A lire", "uidvalidity": 8,
             "uid": 101, "from_addr": "noreply@acronis.com", "subject": "Rapport",
             "kind": "information", "created_at": real_iso(REAL_NOW - timedelta(hours=1)),
             "expires_at": real_iso(REAL_NOW + timedelta(hours=47))},
        ])

    def _make_treat_proposal(self, dest: str = "gitlab") -> str:
        self._store_workflow_ref()
        reply = interact_mod.handle_command(
            {"verb": "treat", "ref": "l1", "dest_text": dest},
            self.cfg, self.state, self.dir_path, "owner", "chan1", "post-t1")
        self.assertIn("Clôture proposée", reply)
        self.assertEqual(self.state.get_proposal("p1")["kind"], "treat")
        return "p1"

    def test_treat_confirmation_moves_and_marks_seen(self) -> None:
        """Chemin nominal : clôture → move stockage + STORE +FLAGS \\\\Seen
        réconcilié (Message-ID recherché dans la destination, JAMAIS de \\\\Seen
        aveugle)."""
        pid = self._make_treat_proposal()
        conn = WorkflowFakeConn(
            mid_source={101: b"<report@acronis.com>"},
            dest_mid={"GitLab": b"501"})
        with self._patch_two(conn):
            reply = interact_mod.handle_command({"verb": "ok", "proposal_ref": pid},
                                                self.cfg, self.state, self.dir_path,
                                                "owner", "chan1", "post-ok")
        self.assertIn("Traitement effectué", reply)
        self.assertIn("marqué lu", reply)
        self.assertEqual(self.state.get_proposal(pid)["status"], "applied")
        self.assertEqual(conn.moves, [(101, "A lire", "GitLab")])
        self.assertEqual(conn.stores, [(501, "+FLAGS (\\Seen)")])
        plan = self.state.get_plan(f"interactive-{pid}")
        self.assertEqual(plan["status"], "applied")

    def test_treat_seen_not_resolved_stays_uncertain_no_store(self) -> None:
        """§12.3 : cible introuvable dans la destination → move confirmé mais
        \\Seen jamais appliqué aveuglément → uncertain réconciliable."""
        pid = self._make_treat_proposal()
        conn = WorkflowFakeConn(mid_source={101: b"<report@acronis.com>"})
        # dest_mid absent → SEARCH vide → réconciliation impossible
        with self._patch_two(conn):
            reply = interact_mod.handle_command({"verb": "ok", "proposal_ref": pid},
                                                self.cfg, self.state, self.dir_path,
                                                "owner", "chan1", "post-ok")
        self.assertIn("état inconnu", reply)
        self.assertEqual(conn.moves, [(101, "A lire", "GitLab")])  # move fait
        self.assertEqual(conn.stores, [])  # JAMAIS de \Seen aveugle
        self.assertEqual(self.state.get_proposal(pid)["status"], "uncertain")

    def test_treat_bare_reply_requires_explicit_destination(self) -> None:
        self._store_workflow_ref()
        reply = interact_mod.handle_command(
            {"verb": "treat_bare", "ref": "l1"},
            self.cfg, self.state, self.dir_path, "owner", "chan1", "post-t2")
        self.assertIn("destination de stockage explicite", reply)

    def test_ok_on_expired_proposal_says_expired(self) -> None:
        """Review F-08 : une proposition expirée reçoit « expirée » (jamais
        « déjà en cours » — le propriétaire doit refaire, pas réessayer)."""
        interact_mod._save_proposal(self.state, "p9", "move", "owner", "chan1",
                                    {"type": "move"}, timedelta(minutes=-30),
                                    self.dir_path)
        reply = interact_mod.handle_command(
            {"verb": "ok", "proposal_ref": "p9"}, self.cfg, self.state,
            self.dir_path, "owner", "chan1", "post-expired")
        self.assertIn("expirée", reply)

    def test_treat_same_folder_no_effect(self) -> None:
        self._store_workflow_ref()
        reply = interact_mod.handle_command(
            {"verb": "treat", "ref": "l1", "dest_text": "lire"},
            self.cfg, self.state, self.dir_path, "owner", "chan1", "post-t3")
        self.assertIn("sans effet", reply)
        self.assertIsNone(self.state.get_proposal("p1"))  # aucune proposition créée

    def _patch_two(self, conn):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(triage_mod, "_connect_imap", lambda cfg: conn))
        stack.enter_context(mock.patch.object(imap_mod, "connect", lambda *a, **k: conn))
        return stack


# --- étape 6 : état workflow persistant + digest workflow (D6) -------------------


class WorkflowSyncTestCase(WorkflowCommandTestCase):
    def _sync(self, conn, headers_by_folder: dict) -> dict:
        def fake_fetch(c, mailbox, limit=100, min_uid=None):
            return headers_by_folder.get(mailbox, [])
        with mock.patch.object(triage_mod.imap_mod, "fetch_recent_headers", fake_fetch):
            return triage_mod._sync_workflow_items(conn, self.state, self.cfg)

    def _headers(self, uid: int, subject: str) -> dict:
        return {"uid": uid, "from": f"u{uid}@x.com", "subject": subject,
                "message_id": f"<m{uid}@x>", "seen": False}

    def test_sync_allocates_refs_resolves_and_never_reproposes(self) -> None:
        """D6 : new → ref #wN ; absent du dossier → resolved (jamais re-proposé) ;
        réapparition d'un résolu → JAMAIS de réintroduction (état préservé)."""
        conn = WorkflowFakeConn()
        headers = {"A lire": [self._headers(101, "Rapport")],
                   "A traiter": [self._headers(55, "Décision")]}
        r1 = self._sync(conn, headers)
        self.assertEqual(r1["new_refs"], 2)
        self.assertEqual(self.state.active_ref_for_key("A lire", 8, 101,
                                                      real_iso(REAL_NOW)), "w1")
        # re-sync identique : la ref active existe → ZÉRO nouveau ref (pas de doublon)
        r2 = self._sync(conn, headers)
        self.assertEqual(r2["new_refs"], 0)
        # 101 disparaît du dossier (déplacé/clôturé) → resolved
        r3 = self._sync(conn, {"A lire": [], "A traiter": headers["A traiter"]})
        self.assertEqual(r3["resolved"], 1)
        self.assertEqual([i["uid"] for i in self.state.workflow_items_by_state(["new"])], [55])
        # 101 réapparaît dans le dossier → JAMAIS réintroduit (reste resolved,
        # aucune ref NOUVELLE allouée : zéro re-proposition d'un élément pris
        # en charge — l'ancienne ref w1 vit sa course de 48 h puis meurt)
        r4 = self._sync(conn, headers)
        self.assertEqual(r4["new_refs"], 0)
        self.assertEqual(r4["resolved"], 0)
        items_final = self.state.workflow_items_by_state(["resolved"])
        self.assertTrue(any(i["uid"] == 101 for i in items_final))

    def test_pending_state_set_by_treat_not_reset_by_sync(self) -> None:
        """L'item traité passe 'pending' à la proposition ; le sync le garde
        (jamais de re-proposition tant que la clôture est engagée)."""
        conn = WorkflowFakeConn()
        headers = {"A lire": [self._headers(101, "Rapport")], "A traiter": []}
        self._sync(conn, headers)
        self.state.set_workflow_item_state("A lire", 8, 101, "pending",
                                           real_iso(REAL_NOW))
        self._sync(conn, headers)
        items = self.state.workflow_items_by_state(["pending"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["uid"], 101)

    def test_sync_freezes_resolution_when_folder_over_cap(self) -> None:
        """Review F-04 : MESSAGES > cap 300 = scan PARTIEL → résolution GELÉE
        pour ce dossier (fail-closed — jamais un faux 'resolved' pour un item
        simplement hors fenêtre de scan)."""
        conn = WorkflowFakeConn(counts={"INBOX": (12, 4), "A lire": (350, 3),
                                        "A traiter": (2, 1)})
        headers = {"A lire": [self._headers(u, f"m{u}") for u in range(1, 301)],
                   "A traiter": []}
        now = real_iso(REAL_NOW)
        # item PRÉSENT côté serveur (uid 900) mais HORS fenêtre de scan (cap 300)
        self.state.upsert_workflow_items([
            {"mailbox": "A lire", "uidvalidity": 8, "uid": 900,
             "from_addr": "deep@x.com", "subject": "Ancien"},
        ], now)
        r = self._sync(conn, headers)
        self.assertEqual(r["frozen"], ["A lire"])   # gel fail-closed signalé
        self.assertEqual(r["resolved"], 0)          # JAMAIS de faux resolved
        remaining = [i["uid"] for i in self.state.workflow_items_by_state(["new"])]
        self.assertIn(900, remaining)               # l'item hors cap reste 'new'

    def test_pending_without_active_ref_gets_new_ref(self) -> None:
        """Review F-03 : un item 'pending' dont la ref a expiré redevient
        actionnable (nouvelle ref #wN) — pas de cul-de-sac."""
        conn = WorkflowFakeConn()
        headers = {"A lire": [self._headers(101, "Rapport")], "A traiter": []}
        self._sync(conn, headers)                    # w1 allouée, item new
        self.state.set_workflow_item_state("A lire", 8, 101, "pending",
                                           real_iso(REAL_NOW))
        # la ref w1 expire (TTL 48 h dépassé — simulation directe en SQL)
        db = sqlite3.connect(self.dir_path / "state.sqlite")
        try:
            db.execute("UPDATE digest_refs SET expires_at='2000-01-01T00:00:00+00:00' "
                       "WHERE ref='w1'")
            db.commit()
        finally:
            db.close()
        r2 = self._sync(conn, headers)
        self.assertEqual(r2["new_refs"], 1)          # F-03 : re-actionnable
        self.assertEqual(self.state.active_ref_for_key(
            "A lire", 8, 101, real_iso(REAL_NOW)), "w2")


class WorkflowDigestSectionTestCase(WorkflowCommandTestCase):
    WINDOW = {"start": REAL_NOW - timedelta(hours=18), "end": REAL_NOW}

    def _store_workflow_ref(self, ref: str, uid: int) -> None:
        self.state.store_digest_refs([{
            "digest_id": "workflow", "ref": ref, "mailbox": "A lire",
            "uidvalidity": 8, "uid": uid, "from_addr": "noreply@acronis.com",
            "subject": "Rapport", "kind": "workflow",
            "created_at": real_iso(REAL_NOW - timedelta(hours=1)),
            "expires_at": real_iso(REAL_NOW + timedelta(hours=47))}])

    def test_digest_lists_actionable_items_never_resolved(self) -> None:
        """D6 : le digest liste les items new/pending AVEC ref active ; les
        resolved n'apparaissent jamais (zéro re-proposition)."""
        self._store_workflow_ref("w1", 101)
        now = real_iso(REAL_NOW)
        self.state.upsert_workflow_items([
            {"mailbox": "A lire", "uidvalidity": 8, "uid": 101,
             "from_addr": "noreply@acronis.com", "subject": "Rapport"},
            {"mailbox": "A lire", "uidvalidity": 8, "uid": 999,
             "from_addr": "old@x.com", "subject": "Ancien"},
        ], now)
        self.state.set_workflow_item_state("A lire", 8, 999, "resolved", now)
        digest = digest_mod.build_digest(self.state, [], self.cfg, self.WINDOW, "dtest")
        self.assertIsNotNone(digest["workflow"])
        self.assertEqual(digest["workflow"]["total"], 1)
        self.assertEqual([i["uid"] for i in digest["workflow"]["items"]], [101])
        md = digest_mod.render_markdown(digest)
        self.assertIn("En attente de traitement", md)
        self.assertIn("**#w1**", md)
        self.assertNotIn("Ancien", md)  # le resolved n'est JAMAIS listé (D6)
        self.assertNotIn("999", md)

    def test_no_workflow_section_when_no_items(self) -> None:
        """Activation progressive : aucun item → section absente, zéro impact
        sur le digest existant."""
        digest = digest_mod.build_digest(self.state, [], self.cfg, self.WINDOW, "dtest2")
        self.assertIsNone(digest["workflow"])
        md = digest_mod.render_markdown(digest)
        self.assertNotIn("En attente de traitement", md)


if __name__ == "__main__":
    unittest.main()
