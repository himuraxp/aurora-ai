#!/usr/bin/env python3
"""Tests du CLI : exit codes 0/1/2, JSON garantis, kill switches avant toute
connexion IMAP, garde --confirm-apply. Aucun réseau (aucune commande testée
n'atteint la connexion IMAP dans ces scénarios)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import config as config_mod  # noqa: E402
import state as state_mod  # noqa: E402
import triage  # noqa: E402

TS = "2026-10-23T08:00:00+00:00"


def base_config(**writes) -> dict:
    return {
        "account": {"host": "mail.example.com", "port": 993,
                    "password_env": "MAIL_TRIAGE_IMAP_PASSWORD"},
        "source": {"mailbox": "INBOX"},
        "destinations": {"allowlist": ["INBOX/Auto/News"]},
        "writes": {"enabled": writes.get("enabled", True),
                   "imap_enabled": writes.get("imap_enabled", True),
                   "digest_enabled": writes.get("digest_enabled", True)},
        "digest": {"enabled": writes.get("digest", True)},
    }


def run_cli(args: list[str]) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = triage.main(args)
    try:
        payload = json.loads(buffer.getvalue())
    except json.JSONDecodeError:
        payload = {"_raw": buffer.getvalue()}
    return code, payload


class CliBaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        # Isolation stricte : jamais le vrai ~/.config/opencode/.env
        self._env_patcher = mock.patch.dict(os.environ)
        self._env_patcher.start()
        self._env_file_patcher = mock.patch.object(
            config_mod, "DEFAULT_ENV_FILE", self.dir / "absent.env")
        self._env_file_patcher.start()
        for key in ("MAIL_TRIAGE_IMAP_LOGIN", "MAIL_TRIAGE_IMAP_PASSWORD",
                    "MAIL_TRIAGE_KCHAT_TOKEN", "MAIL_TRIAGE_KCHAT_DM_USERNAME"):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        self._env_file_patcher.stop()
        self._env_patcher.stop()
        self._tmp.cleanup()

    def write_config(self, cfg: dict) -> None:
        (self.dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


class ConfigGuardTestCase(CliBaseTestCase):
    def test_missing_config_exit_2(self) -> None:
        code, payload = run_cli(["--config-dir", str(self.dir), "status"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "config")

    def test_invalid_config_exit_2(self) -> None:
        (self.dir / "config.json").write_text("{oops", encoding="utf-8")
        code, payload = run_cli(["--config-dir", str(self.dir), "status"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "config")


class StatusTestCase(CliBaseTestCase):
    def test_status_ok(self) -> None:
        self.write_config(base_config())
        code, payload = run_cli(["--config-dir", str(self.dir), "status"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["command"], "status")
        self.assertFalse(payload["secrets_present"]["imap_password"])
        self.assertFalse(payload["secrets_present"]["kchat_token"])
        self.assertEqual(payload["allowlist_size"], 1)


class KillSwitchTestCase(CliBaseTestCase):
    def test_plan_blocked_when_writes_disabled(self) -> None:
        self.write_config(base_config(enabled=False))
        code, payload = run_cli(["--config-dir", str(self.dir), "plan"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "writes_disabled")

    def test_apply_blocked_when_imap_writes_disabled(self) -> None:
        self.write_config(base_config(imap_enabled=False))
        code, payload = run_cli(
            ["--config-dir", str(self.dir), "apply", "--plan", "x", "--confirm-apply"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "writes_disabled")

    def test_digest_send_blocked_before_imap(self) -> None:
        self.write_config(base_config(enabled=False))
        code, payload = run_cli(
            ["--config-dir", str(self.dir), "digest", "--send"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "writes_disabled")

    def test_digest_disabled_exit_2(self) -> None:
        self.write_config(base_config(digest=False))
        code, payload = run_cli(["--config-dir", str(self.dir), "digest"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "digest_disabled")


class ApplyGuardTestCase(CliBaseTestCase):
    def test_apply_unknown_plan(self) -> None:
        self.write_config(base_config())
        code, payload = run_cli(
            ["--config-dir", str(self.dir), "apply", "--plan", "nope", "--confirm-apply"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "plan_not_found")

    def test_apply_requires_confirm(self) -> None:
        self.write_config(base_config())
        state = state_mod.State(self.dir / "state.sqlite")
        state.create_plan("p1", TS, "2027-10-23T08:00:00+00:00",
                          {"mailbox": "INBOX", "uidvalidity": 7, "moves": [],
                           "created_at": TS})
        code, payload = run_cli(["--config-dir", str(self.dir), "apply", "--plan", "p1"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "confirm_required")

    def test_apply_blocks_when_uncertain_results(self) -> None:
        self.write_config(base_config())
        state = state_mod.State(self.dir / "state.sqlite")
        state.create_plan("p1", TS, "2027-10-23T08:00:00+00:00",
                          {"mailbox": "INBOX", "uidvalidity": 7, "moves": [],
                           "created_at": TS})
        state.set_move_result("p1", 10, "uncertain", "timeout")
        code, payload = run_cli(
            ["--config-dir", str(self.dir), "apply", "--plan", "p1", "--confirm-apply"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "reconcile_required")

    def test_apply_expired_plan(self) -> None:
        self.write_config(base_config())
        state = state_mod.State(self.dir / "state.sqlite")
        state.create_plan("p1", "2020-01-01T00:00:00+00:00", "2020-01-02T00:00:00+00:00",
                          {"mailbox": "INBOX", "uidvalidity": 7, "moves": [],
                           "created_at": "2020-01-01T00:00:00+00:00"})
        code, payload = run_cli(
            ["--config-dir", str(self.dir), "apply", "--plan", "p1", "--confirm-apply"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "plan_expired")
        self.assertEqual(state.get_plan("p1")["status"], "expired")


class ReconcileUsageTestCase(CliBaseTestCase):
    def test_reconcile_requires_target(self) -> None:
        self.write_config(base_config())
        code, payload = run_cli(["--config-dir", str(self.dir), "reconcile"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "usage")

    def test_reconcile_unknown_plan(self) -> None:
        self.write_config(base_config())
        code, payload = run_cli(
            ["--config-dir", str(self.dir), "reconcile", "--plan", "nope"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "plan_not_found")


class SecretGuardTestCase(CliBaseTestCase):
    def test_scan_missing_secret_exit_1_no_network(self) -> None:
        self.write_config(base_config())
        code, payload = run_cli(["--config-dir", str(self.dir), "scan"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "secret")


if __name__ == "__main__":
    unittest.main()
