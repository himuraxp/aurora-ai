#!/usr/bin/env python3
"""Suite de tests send_kchat.py — zéro réseau (client kChat mocké).

Lancement : python3 -m unittest discover -s skills/daily-brief/tests -p 'test_*.py'
Compatible 3.9+ (python système live) et 3.14.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import send_kchat  # noqa: E402

MARKER = send_kchat.MARKER_TEMPLATE.format(day=date.today().isoformat())


class _Base(unittest.TestCase):
    """Fixtures tmpdir : .env, config, fichier de briefing."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.env_path = base / "env"
        self.config_path = base / "config.json"
        self.brief_path = base / "brief.md"
        self.env_path.write_text(
            "# comment\n"
            f'{send_kchat.DEFAULT_TOKEN_ENV}="secret-token-value"\n'
            f"{send_kchat.DEFAULT_DM_USERNAME_ENV}=target-user\n",
            encoding="utf-8",
        )
        self.brief_path.write_text("# Briefing test\n", encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def run_main(self, extra_args=None, env_path=None, config_path=None,
                 brief_path=None) -> tuple[int, dict]:
        argv = ["send_kchat.py",
                "--file", str(brief_path or self.brief_path),
                "--env-file", str(env_path or self.env_path),
                "--config", str(config_path or self.config_path)] + list(extra_args or [])
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), redirect_stdout(out):
            code = send_kchat.main()
        return code, json.loads(out.getvalue())

    def fake_request(self, responses):
        """Retourne un mock _request : les GET /channels/*/posts renvoient `responses`."""
        posts = json.dumps({"posts": {f"p{i}": {"id": f"p{i}", "message": m}
                                     for i, m in enumerate(responses)}})
        def _request(path, method="GET", body=None):
            if "/posts?" in path or (method == "GET" and "/posts" in path):
                return json.loads(posts)
            if path == "/posts" and method == "POST":
                return {"id": "new-post-id"}
            if path == "/users/me":
                return {"id": "bot-id"}
            if path.startswith("/users/username/"):
                return {"id": "target-id"}
            if path == "/channels/direct" and method == "POST":
                return {"id": "channel-id"}
            raise AssertionError(f"appel inattendu: {method} {path}")
        return _request


class TestCliFailures(_Base):
    """Échecs fail-closed : source du message et config."""

    def test_missing_file_failed_exit2(self):
        code, out = self.run_main([], brief_path=Path(self._tmp.name) / "nope.md")
        self.assertEqual((code, out["status"], out["reason"]), (2, "failed", "file_not_found"))

    def test_empty_message_failed_exit2(self):
        self.brief_path.write_text("   \n", encoding="utf-8")
        code, out = self.run_main()
        self.assertEqual((code, out["status"], out["reason"]), (2, "failed", "empty_message"))

    def test_invalid_config_json_exit2(self):
        self.config_path.write_text("{not json", encoding="utf-8")
        code, out = self.run_main()
        self.assertEqual((code, out["status"], out["reason"]), (2, "failed", "invalid_config"))

    def test_invalid_timeout_exit2(self):
        self.config_path.write_text(
            json.dumps({"kchat": {"timeout_seconds": "abc"}}), encoding="utf-8")
        code, out = self.run_main()
        self.assertEqual((code, out["status"], out["reason"]), (2, "failed", "invalid_config"))

    def test_missing_env_exit2_no_secret_echo(self):
        empty_env = Path(self._tmp.name) / "empty.env"
        empty_env.write_text("", encoding="utf-8")
        code, out = self.run_main(["--dry-run"], env_path=empty_env)
        self.assertEqual((code, out["status"], out["reason"]), (2, "failed", "missing_env"))
        self.assertEqual(out["variables"], [send_kchat.DEFAULT_TOKEN_ENV,
                                            send_kchat.DEFAULT_DM_USERNAME_ENV])
        self.assertNotIn("secret-token-value", json.dumps(out))


class TestDryRunAndSkip(_Base):
    """Chemins sans réseau : dry-run et kill switch config."""

    def test_dry_run_exit0_marker_of_today(self):
        code, out = self.run_main(["--dry-run"])
        self.assertEqual((code, out["status"]), (0, "dry_run"))
        self.assertEqual(out["marker"], MARKER)

    def test_stdin_brief(self):
        argv = ["send_kchat.py", "--file", "-",
                "--env-file", str(self.env_path),
                "--config", str(self.config_path), "--dry-run"]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sys, "stdin", io.StringIO("# via stdin\n")), \
                redirect_stdout(out):
            code = send_kchat.main()
        payload = json.loads(out.getvalue())
        self.assertEqual((code, payload["status"]), (0, "dry_run"))

    def test_kchat_disabled_skipped_exit0(self):
        self.config_path.write_text(json.dumps({"kchat": {"enabled": False}}),
                                    encoding="utf-8")
        code, out = self.run_main()
        self.assertEqual((code, out["status"]), (0, "skipped"))


class TestSendFlow(_Base):
    """Flux complet : client kChat mocké — sent, dedup, force, marker, erreur API."""

    def run_send(self, recent_posts=None, extra=None):
        posts = list(recent_posts or [])
        client_mock = mock.patch.object(send_kchat.MinimalKChat, "_request",
                                        side_effect=self.fake_request(posts))
        argv = ["send_kchat.py", "--file", str(self.brief_path),
                "--env-file", str(self.env_path),
                "--config", str(self.config_path)] + list(extra or [])
        out = io.StringIO()
        with client_mock, mock.patch.object(sys, "argv", argv), redirect_stdout(out):
            code = send_kchat.main()
        return code, json.loads(out.getvalue())

    def test_sent_exit0(self):
        with mock.patch.object(send_kchat.MinimalKChat, "post_message",
                               return_value={"id": "new-post-id"}) as post:
            code, out = self.run_send()
        self.assertEqual((code, out["status"]), (0, "sent"))
        self.assertEqual(out["post_id"], "new-post-id")
        # Le marqueur du jour est apposé au message publié.
        sent_message = post.call_args[0][1]
        self.assertIn(MARKER, sent_message)

    def test_dedup_already_sent_exit0(self):
        code, out = self.run_send(recent_posts=[f"ancien post\n{MARKER}\n"])
        self.assertEqual((code, out["status"]), (0, "already_sent"))

    def test_force_bypasses_dedup(self):
        code, out = self.run_send(recent_posts=[MARKER], extra=["--force"])
        self.assertEqual((code, out["status"]), (0, "sent"))

    def test_existing_marker_not_duplicated(self):
        self.brief_path.write_text(f"# Briefing\n\n{MARKER}\n", encoding="utf-8")
        with mock.patch.object(send_kchat.MinimalKChat, "post_message",
                               return_value={"id": "p"}) as post:
            code, out = self.run_send()
        self.assertEqual((code, out["status"]), (0, "sent"))
        sent_message = post.call_args[0][1]
        self.assertEqual(sent_message.count(MARKER), 1)

    def test_kchat_error_exit1(self):
        def boom(client_self, dm_username):
            raise send_kchat.KChatError(401, "/users/me", "unauthorized")
        with mock.patch.object(send_kchat.MinimalKChat, "direct_channel_id", boom):
            code, out = self.run_main()
        self.assertEqual((code, out["status"], out["reason"]), (1, "failed", "kchat_error"))
        self.assertEqual(out["status_code"], 401)
        self.assertNotIn("secret-token-value", json.dumps(out))


class TestEnvParsing(unittest.TestCase):
    """Parsing .env : robustesse + jamais de valeur en sortie."""

    def test_parsing(self):
        env_file = Path(tempfile.mkdtemp()) / "env"
        env_file.write_text(
            "# commentaire\n"
            "KEY1=value\n"
            'KEY2="quoted value"\n'
            "KEY3='single quoted'\n"
            "KEY4=a=b=c\n"
            "SANS_EGAL_LIGNE_IGNOREE\n"
            "\n",
            encoding="utf-8")
        found = send_kchat.read_env_vars(env_file, ["KEY1", "KEY2", "KEY3", "KEY4"])
        self.assertEqual(found, {"KEY1": "value", "KEY2": "quoted value",
                                 "KEY3": "single quoted", "KEY4": "a=b=c"})
        self.assertEqual(send_kchat.read_env_vars(env_file, ["MISSING"]), {})

    def test_absent_env_file(self):
        self.assertEqual(send_kchat.read_env_vars(Path("/nonexistent/.env"), ["KEY"]), {})


if __name__ == "__main__":
    unittest.main()
