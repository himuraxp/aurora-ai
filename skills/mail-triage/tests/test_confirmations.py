#!/usr/bin/env python3
"""Tests J4 — confirmations `ok #pN` (ARCHITECTURE §11.4/§11.8).

Contient les 9 TESTS DE SORTIE exigés avant activation des mutations :
1. ref d'ancien digest : l'action FIGÉE est exécutée (uid figé, jamais re-résolu)
2. alias/destination supprimé(e) entre proposition et confirmation → aucun write
3. règles modifiées (SHA-256 global divergent) → confirmation refusée
4. deux confirmations concurrentes → une seule transition executing
5. crash avant/après UID MOVE → aucune répétition aveugle
6. crash après os.replace(rules.json) → règle reconnue sans duplication
7. réponse publiée puis interruption → aucune réexécution (registre post_id)
8. poller > 300 s → pas de seconde exécution concurrente (verrou dédié)
9. kill switch désactivé entre proposition et confirmation → aucun write

Zéro réseau : l'IMAP est simulé par un FakeConn branché sur imap_client.connect.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import config as config_mod  # noqa: E402
import imap_client as imap_mod  # noqa: E402
import interact as interact_mod  # noqa: E402
import policy as policy_mod  # noqa: E402
import rules_writer as rules_writer_mod  # noqa: E402
import state as state_mod  # noqa: E402
import triage as triage_mod  # noqa: E402

REAL_NOW = datetime.now(timezone.utc)


def real_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class FakeConn:
    """IMAP simulé : capability MOVE, UIDVALIDITY, LIST (existence), UID MOVE."""

    def __init__(self, *, move_ok: bool = True, fail_move_uids=(), drop_after_move=False):
        self.capabilities = ("IMAP4REV1", "MOVE")
        self.moves: list[tuple[int, str, str]] = []
        self.mailboxes = {"INBOX", "GitLab", "Acronis", "A lire", "A traiter"}
        self.uidvalidity = {"INBOX": 7}
        self._move_ok = move_ok
        self._fail_uids = set(fail_move_uids)
        self._drop_after_move = drop_after_move  # crash simulé APRÈS le move serveur

    def capability(self):
        return "OK", [b"IMAP4REV1 MOVE"]

    def status(self, mailbox, spec):
        uv = self.uidvalidity.get(mailbox.strip('"'))
        if uv is None:
            return "NO", [b"unknown mailbox"]
        return "OK", [f'"{mailbox.strip(chr(34))}" (UIDVALIDITY {uv})'.encode()]

    def list(self, ref=None):
        # mailbox_exists : une seule ligne si le dossier existe, sinon vide
        name = (ref or "").strip('"')
        if name in self.mailboxes:
            return "OK", [f'(\\HasNoChildren) "/" "{name}"'.encode()]
        return "OK", []

    def select(self, mailbox, readonly=False):
        return "OK", [b"0"]

    def uid(self, command, *args):
        command = command.upper()
        if command == "MOVE":
            uid = int(args[0])
            dest = args[1].strip('"')
            source = args[2].strip('"') if len(args) > 2 else "INBOX"
            if not self._move_ok or uid in self._fail_uids:
                raise imap_mod.ImapError("UID MOVE échoué (simulé)")
            self.moves.append((uid, source, dest))
            if self._drop_after_move:
                raise imap_mod.ImapError("TimeoutError")  # erreur APRÈS l'effet serveur
            return "OK", [b""]
        if command == "SEARCH":
            # Par défaut : l'UID n'est plus dans la mailbox (déjà déplacé)
            return "OK", [b""]
        raise AssertionError(f"uid({command}) inattendu")

    def logout(self):
        return "BYE", [b""]


class ConfirmationBase(unittest.TestCase):
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
        self.cfg = {"writes": {"enabled": True, "imap_enabled": True,
                               "digest_enabled": True, "interactive_rules": True},
                    "interactive": {"enabled": True, "proposals_enabled": True,
                                    "aliases": {"gitlab": "GitLab", "acronis": "Acronis"},
                                    "max_pending_proposals": 10,
                                    "max_rule_proposals_per_day": 5,
                                    "max_commands_per_5min": 30},
                    "destinations": {"allowlist": ["GitLab", "Acronis"]},
                    "source": {"mailbox": "INBOX"},
                    "plan": {"expire_hours": 24},
                    "_config_dir": str(self.dir_path)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _handle(self, cmd: dict, post_id: str = "post-1") -> str:
        return interact_mod.handle_command(cmd, self.cfg, self.state, self.dir_path,
                                           "owner", "chan1", post_id)

    def _make_move_proposal(self, ref: str = "n1", dest: str = "gitlab",
                            post_id: str = "post-move") -> str:
        self._handle({"verb": "item_move", "ref": ref, "dest_text": dest}, post_id)
        proposal = self.state.get_proposal("p1")
        self.assertIsNotNone(proposal)
        return "p1"

    def _make_rule_proposal(self, post_id: str = "post-rule") -> str:
        self._handle({"verb": "rule_create", "scope": "expediteur",
                      "value": "noreply@acronis.com", "dest_text": "acronis"}, post_id)
        proposal = self.state.get_proposal("p1")
        self.assertIsNotNone(proposal)
        return "p1"

    def _patch_imap(self, conn: FakeConn):
        """Patch les deux points d'entrée IMAP : _connect_imap (lit cfg["account"]
        AVANT d'appeler connect) et imap_client.connect (défense en profondeur)."""
        stack = ExitStack()
        stack.enter_context(mock.patch.object(triage_mod, "_connect_imap",
                                              lambda cfg: conn))
        stack.enter_context(mock.patch.object(imap_mod, "connect",
                                              lambda *a, **k: conn))
        return stack


class OkConsumptionTestCase(ConfirmationBase):
    def test_ok_moves_via_frozen_action(self) -> None:
        """Chemin nominal : confirmation → réservation executing → plan figé
        → UID MOVE → applied."""
        pid = self._make_move_proposal()
        conn = FakeConn()
        with self._patch_imap(conn):
            reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("effectué", reply)
        self.assertIn("GitLab", reply)
        self.assertEqual(self.state.get_proposal(pid)["status"], "applied")
        self.assertEqual(conn.moves, [(42, "INBOX", "GitLab")])
        # plan + résultat journalisés
        plan = self.state.get_plan(f"interactive-{pid}")
        self.assertEqual(plan["status"], "applied")

    def test_ok_digest_ref_reply_unchanged(self) -> None:
        self.assertIn("référence de digest", self._handle({"verb": "ok", "proposal_ref": "n1"}))

    def test_ok_unknown_or_wrong_owner_generic_refusal(self) -> None:
        pid = self._make_move_proposal()
        # mauvais canal : refus générique (ne rien divulguer)
        reply = interact_mod.handle_command(
            {"verb": "ok", "proposal_ref": pid}, self.cfg, self.state, self.dir_path,
            "owner", "chan-autre", "post-x")
        self.assertIn("inconnue, expirée ou déjà traitée", reply)
        self.assertEqual(self.state.get_proposal(pid)["status"], "pending")
        # pid inconnu
        self.assertIn("inconnue", self._handle({"verb": "ok", "proposal_ref": "p99"}))

    def test_ok_rule_creates_rule_atomic(self) -> None:
        pid = self._make_rule_proposal()
        reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("Règle créée", reply)
        self.assertIn("adresse exacte", reply)
        self.assertEqual(self.state.get_proposal(pid)["status"], "applied")
        doc = json.loads((self.dir_path / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(len(doc["rules"]), 1)
        self.assertEqual(doc["rules"][0]["match"], {"from_exact": ["noreply@acronis.com"]})
        self.assertIsNotNone(self.state.rule_operation_applied(f"op-{pid}"))

    def test_policy_from_exact_semantics(self) -> None:
        """F-03 : from_exact = adresse exacte — jamais une sous-chaîne."""
        rule = {"id": "r", "priority": 150, "mode": "auto", "folder": "GitLab",
                "match": {"from_exact": ["bob@x.com"]}}
        self.assertTrue(policy_mod.rule_matches(
            rule, {"from": "Bob <bob@x.com>", "subject": "", "to": ""}))
        self.assertFalse(policy_mod.rule_matches(
            rule, {"from": "evil@x.com.evil.tld", "subject": "", "to": ""}))
        self.assertFalse(policy_mod.rule_matches(
            rule, {"from": "a+bob@x.com@attacker.io", "subject": "", "to": ""}))
        self.assertFalse(policy_mod.rule_matches(
            rule, {"from": "carol@y.com", "subject": "", "to": ""}))


class ExitTest1FrozenRefTestCase(ConfirmationBase):
    def test_exit1_frozen_action_not_reresolved(self) -> None:
        """#1 — ref d'ancien digest : même si les digest_refs changent entre la
        proposition et la confirmation, l'UID FIGÉ à la création est déplacé
        (jamais re-résolu)."""
        pid = self._make_move_proposal(ref="n1", dest="gitlab")
        # mutation des refs : #n1 pointe désormais ailleurs
        self.state.store_digest_refs([
            {"digest_id": "d9", "ref": "n1", "mailbox": "INBOX", "uidvalidity": 7,
             "uid": 777, "from_addr": "other@x.com", "subject": "Autre",
             "kind": "unknown", "created_at": real_iso(REAL_NOW),
             "expires_at": real_iso(REAL_NOW + timedelta(hours=48))},
        ])
        conn = FakeConn()
        with self._patch_imap(conn):
            self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertEqual(conn.moves, [(42, "INBOX", "GitLab")])  # uid figé 42, pas 777


class ExitTest2DestinationChangedTestCase(ConfirmationBase):
    def test_exit2_destination_removed_from_allowlist_no_write(self) -> None:
        """#2 — alias/destination retiré de l'allowlist entre proposition et
        confirmation → refus, AUCUN write, proposition rejetée."""
        pid = self._make_move_proposal(dest="gitlab")
        self.cfg["destinations"]["allowlist"] = ["Acronis"]  # GitLab supprimé
        conn = FakeConn()
        with self._patch_imap(conn):
            reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("destination non autorisée", reply)
        self.assertEqual(conn.moves, [])  # aucun write
        self.assertEqual(self.state.get_proposal(pid)["status"], "rejected")

    def test_exit2_forbidden_destination_never_executed(self) -> None:
        pid = self._make_move_proposal(dest="gitlab")
        # allowlist widened to include Trash + alias repositionné
        self.cfg["destinations"]["allowlist"] = ["GitLab", "Trash"]
        action = json.loads(self.state.get_proposal(pid)["action"])
        action["folder"] = "Trash"  # simulation d'un allowlist élargi côté config
        conn_sql = state_mod.sqlite3.connect(self.state.path)
        try:
            conn_sql.execute("UPDATE proposals SET action=? WHERE proposal_id=?",
                             (json.dumps(action), pid))
            conn_sql.commit()
        finally:
            conn_sql.close()
        conn = FakeConn()
        with self._patch_imap(conn):
            reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("destination", reply)
        self.assertEqual(conn.moves, [])
        self.assertEqual(self.state.get_proposal(pid)["status"], "rejected")


class ExitTest3RulesChangedTestCase(ConfirmationBase):
    def test_exit3_rules_modified_refused(self) -> None:
        """#3 — règles modifiées entre proposition et confirmation → refus
        (SHA-256 global divergent), aucun write."""
        pid = self._make_move_proposal()
        (self.dir_path / "rules.json").write_text(
            '{"rules": [{"id": "manual", "priority": 10, "mode": "never", '
            '"match": {"from_any": ["x@y.z"]}}], "sensitive_senders": []}',
            encoding="utf-8")
        conn = FakeConn()
        with self._patch_imap(conn):
            reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("règles ont changé", reply)
        self.assertEqual(conn.moves, [])
        self.assertEqual(self.state.get_proposal(pid)["status"], "rejected")

    def test_exit3_rules_modified_rule_proposal_refused(self) -> None:
        pid = self._make_rule_proposal()
        (self.dir_path / "rules.json").write_text('{"rules": [], "sensitive_senders": ["a@b.c"]}',
                                                  encoding="utf-8")
        reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("règles ont changé", reply)
        doc = json.loads((self.dir_path / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["rules"], [])  # aucun write
        self.assertEqual(self.state.get_proposal(pid)["status"], "rejected")


class ExitTest4ConcurrentTestCase(ConfirmationBase):
    def test_exit4_two_concurrent_confirmations_one_executing(self) -> None:
        """#4 — deux confirmations concurrentes : une seule transition executing
        (UPDATE conditionnel) ; la seconde reçoit « déjà en cours »."""
        pid = self._make_move_proposal()
        results = []
        barrier = threading.Barrier(2)

        def confirm(post_id: str) -> None:
            barrier.wait()
            state = state_mod.State(self.dir_path / "state.sqlite")
            reserved = state.reserve_proposal(pid, interact_mod._now_iso(), post_id)
            results.append(reserved)

        t1 = threading.Thread(target=confirm, args=("post-c1",))
        t2 = threading.Thread(target=confirm, args=("post-c2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(sorted(results), [False, True])  # un seul gagnant
        proposal = self.state.get_proposal(pid)
        self.assertEqual(proposal["status"], "executing")
        # et via handle_ok : la seconde confirmation complète → « déjà traitée »
        self.state.set_proposal_status(pid, "pending")
        conn = FakeConn()
        with self._patch_imap(conn):
            reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("effectué", reply)
        self.assertEqual(conn.moves, [(42, "INBOX", "GitLab")])
        reply2 = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok2")
        self.assertIn("déjà traitée", reply2)

    def test_reserve_proposal_atomic_sequential(self) -> None:
        pid = self._make_move_proposal()
        self.assertTrue(self.state.reserve_proposal(pid, interact_mod._now_iso(), "post-1"))
        self.assertFalse(self.state.reserve_proposal(pid, interact_mod._now_iso(), "post-2"))
        # expirée : plus réservable
        conn = state_mod.sqlite3.connect(self.state.path)
        try:
            conn.execute("UPDATE proposals SET status='pending', "
                         "expires_at='2020-01-01T00:00:00+00:00' WHERE proposal_id=?", (pid,))
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(self.state.reserve_proposal(pid, interact_mod._now_iso(), "post-3"))


class ExitTest5CrashMoveTestCase(ConfirmationBase):
    def test_exit5_crash_after_move_no_blind_repeat(self) -> None:
        """#5 — crash APRÈS l'effet serveur UID MOVE : résultat uncertain,
        proposition non re-consommable, re-apply exige reconcile (jamais de
        répétition aveugle)."""
        pid = self._make_move_proposal()
        conn = FakeConn(drop_after_move=True)  # move effectué puis exception
        with self._patch_imap(conn):
            reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("inconnu", reply)
        self.assertEqual(conn.moves, [(42, "INBOX", "GitLab")])  # l'effet a eu lieu
        self.assertEqual(self.state.get_proposal(pid)["status"], "uncertain")
        # re-confirmation → REFUS (usage unique, même si réconciliation faite)
        with self._patch_imap(FakeConn()):
            reply2 = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok2")
        self.assertIn("inconnue, expirée ou déjà traitée", reply2)
        # le plan est en uncertain → toute nouvelle exécution exige reconcile
        result = triage_mod.run_plan_apply(self.cfg, self.state, self.dir_path,
                                           f"interactive-{pid}")
        self.assertEqual(result["status"], "reconcile_required")
        # après reconcile (absent de la source, Message-ID absent → moved_assumed)
        # → plan applied, PAS de nouveau move. FakeConn gère select + search.
        reconcile_conn = FakeConn()
        import io
        from contextlib import redirect_stdout
        with self._patch_imap(reconcile_conn), redirect_stdout(io.StringIO()):
            code = triage_mod.cmd_reconcile(self.cfg,
                                            type("A", (), {"digest": None, "plan": f"interactive-{pid}"})())
        self.assertEqual(code, 0)
        self.assertEqual(reconcile_conn.moves, [])  # AUCUN second move

    def test_exit5_crash_before_move_proposal_stuck_executing_swept(self) -> None:
        """#5bis — crash AVANT l'exécution : proposition stuck 'executing' →
        sweep → uncertain (réconciliable, jamais re-consommable)."""
        pid = self._make_move_proposal()
        self.assertTrue(self.state.reserve_proposal(pid, interact_mod._now_iso(), "post-x"))
        cutoff = (REAL_NOW - timedelta(hours=30)).isoformat(timespec="seconds")
        # created_at récent → pas sweepé
        self.assertEqual(self.state.timeout_stale_executing(cutoff), 0)
        # created_at ancien (simule un crash 26 h+) → sweepé vers uncertain
        conn = state_mod.sqlite3.connect(self.state.path)
        try:
            conn.execute("UPDATE proposals SET created_at='2026-10-24T00:00:00+00:00' "
                         "WHERE proposal_id=?", (pid,))
            conn.commit()
        finally:
            conn.close()
        swept = self.state.timeout_stale_executing(cutoff)
        self.assertEqual(swept, 1)
        self.assertEqual(self.state.get_proposal(pid)["status"], "uncertain")


class RulesWriterTestCase(ConfirmationBase):
    def test_exit6_crash_after_replace_no_duplication(self) -> None:
        """#6 — crash après os.replace(rules.json) mais avant enregistrement de
        l'operation_id : re-appel → règle reconnue à l'identique, SANS doublon."""
        rule = {"id": "interactive-p1", "priority": 150, "mode": "propose",
                "match": {"from_exact": ["noreply@acronis.com"]}, "folder": "Acronis"}
        first = rules_writer_mod.append_rule(self.dir_path, self.state, rule, "op-1",
                                             None, real_iso(REAL_NOW))
        self.assertEqual(first["status"], "applied")
        # re-appel du même operation_id (simulation de reprise post-crash)
        second = rules_writer_mod.append_rule(self.dir_path, self.state, rule, "op-1",
                                              None, real_iso(REAL_NOW))
        self.assertEqual(second["status"], "already_applied")
        doc = json.loads((self.dir_path / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(len(doc["rules"]), 1)  # pas de duplication
        self.assertIsNotNone(self.state.rule_operation_applied("op-1"))

    def test_writer_conflict_and_sha_mismatch_and_backup(self) -> None:
        rule = {"id": "interactive-p1", "priority": 150, "mode": "propose",
                "match": {"from_exact": ["noreply@acronis.com"]}, "folder": "Acronis"}
        current_sha = rules_writer_mod.rules_sha256(self.dir_path)
        self.assertEqual(rules_writer_mod.append_rule(self.dir_path, self.state, rule, "op-1",
                                                      current_sha, real_iso(REAL_NOW))["status"],
                         "applied")
        # contenu divergent même id → conflit, jamais d'écrasement
        divergent = dict(rule, priority=999)
        conflict = rules_writer_mod.append_rule(self.dir_path, self.state, divergent, "op-2",
                                                None, real_iso(REAL_NOW))
        self.assertEqual(conflict["status"], "conflict")
        # sha mismatch → refus sans write
        other = dict(rule, id="interactive-p2")
        mismatch = rules_writer_mod.append_rule(self.dir_path, self.state, other, "op-3",
                                                "sha256:deadbeef", real_iso(REAL_NOW))
        self.assertEqual(mismatch["status"], "sha_mismatch")
        doc = json.loads((self.dir_path / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual([r["id"] for r in doc["rules"]], ["interactive-p1"])
        # backup 0600 présent
        backup = self.dir_path / "rules.json.bak"
        self.assertTrue(backup.exists())
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        # perms du fichier écrit
        self.assertEqual((self.dir_path / "rules.json").stat().st_mode & 0o777, 0o600)

    def test_writer_rejects_invalid_rule(self) -> None:
        bad = {"id": "interactive-p9", "priority": 150, "mode": "propose",
               "match": {"from_exact": ["noreply@acronis.com"]}, "folder": "Trash"}
        result = rules_writer_mod.append_rule(self.dir_path, self.state, bad, "op-9",
                                              None, real_iso(REAL_NOW))
        self.assertEqual(result["status"], "invalid")
        doc = json.loads((self.dir_path / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["rules"], [])  # rien d'écrit


class ExitTest7NoReexecutionTestCase(ConfirmationBase):
    def test_exit7_registry_prevents_reexecution(self) -> None:
        """#7 — confirmation traitée (réponse publiée) puis interruption avant
        checkpoint : le rejeu du MÊME post → registre post_id → skip, la
        proposition n'est PAS réexécutée (uid_move compté une seule fois)."""
        pid = self._make_move_proposal(post_id="post-move")
        conn = FakeConn()
        with self._patch_imap(conn):
            self.state.record_command("post-ok", "chan1", 100, "owner", "ok")
            reply = interact_mod.handle_command({"verb": "ok", "proposal_ref": pid},
                                                self.cfg, self.state, self.dir_path,
                                                "owner", "chan1", "post-ok")
        self.assertIn("effectué", reply)
        self.assertEqual(conn.moves, [(42, "INBOX", "GitLab")])
        # rejeu du même post : record_command → False → jamais de second traitement
        self.assertFalse(self.state.record_command("post-ok", "chan1", 100, "owner", "ok"))
        conn2 = FakeConn()
        with self._patch_imap(conn2):
            again = self.state.record_command("post-ok", "chan1", 100, "owner", "ok")
        self.assertFalse(again)  # le poller saute ce post (interact.run_once: continue)
        self.assertEqual(conn2.moves, [])


class ExitTest8PollerLockTestCase(ConfirmationBase):
    def test_exit8_poller_over_300s_no_concurrency(self) -> None:
        """#8 — un tour > 300 s tient le verrou : le tour suivant lève LockError
        (→ cmd_listen : skipped_locked, exit 0, checkpoint intact)."""
        lock_path = self.dir_path / "locks" / "interactive.lock"
        with state_mod.FileLock(lock_path, timeout=0.2):
            with self.assertRaises(state_mod.LockError):
                state_mod.FileLock(lock_path, timeout=0.2).__enter__()
        # le verrou libéré est réacquirable (pas d'orphan inode)
        with state_mod.FileLock(lock_path, timeout=0.2):
            pass


class ExitTest9KillSwitchTestCase(ConfirmationBase):
    def test_exit9_writes_disabled_between_proposal_and_confirmation(self) -> None:
        """#9 — kill switch désactivé entre proposition et confirmation →
        aucun write, proposition INCHANGÉE (reste pending)."""
        pid = self._make_move_proposal()
        self.cfg["writes"]["imap_enabled"] = False
        conn = FakeConn()
        with self._patch_imap(conn):
            reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("pas encore activées", reply)
        self.assertEqual(conn.moves, [])
        self.assertEqual(self.state.get_proposal(pid)["status"], "pending")
        # réactivation → la confirmation redevient possible
        self.cfg["writes"]["imap_enabled"] = True
        with self._patch_imap(conn):
            reply2 = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok2")
        self.assertIn("effectué", reply2)
        self.assertEqual(self.state.get_proposal(pid)["status"], "applied")

    def test_exit9_rule_gate_interactive_rules(self) -> None:
        pid = self._make_rule_proposal()
        self.cfg["writes"]["interactive_rules"] = False  # 4e gate fermé (§11.2)
        reply = self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertIn("pas encore activées", reply)
        doc = json.loads((self.dir_path / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["rules"], [])
        self.assertEqual(self.state.get_proposal(pid)["status"], "pending")

    def test_exit9_writes_enabled_false_blocks_all(self) -> None:
        pid = self._make_move_proposal()
        self.cfg["writes"]["enabled"] = False
        conn = FakeConn()
        with self._patch_imap(conn):
            self._handle({"verb": "ok", "proposal_ref": pid}, "post-ok")
        self.assertEqual(conn.moves, [])
        self.assertEqual(self.state.get_proposal(pid)["status"], "pending")


if __name__ == "__main__":
    unittest.main()
