#!/usr/bin/env python3
"""Tests du chargement de config — fail-closed, aucun réseau, aucun secret réel."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import config as config_mod  # noqa: E402


def base_config() -> dict:
    return {
        "account": {"host": "mail.example.com", "port": 993,
                    "password_env": "MAIL_TRIAGE_IMAP_PASSWORD"},
        "source": {"mailbox": "INBOX"},
        "destinations": {"allowlist": ["INBOX/Auto/News"]},
        "writes": {"enabled": True, "imap_enabled": True, "digest_enabled": True},
        "kchat": {"base_url": "https://kchat.example.com/api/v4"},
    }


class ConfigLoadTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, cfg: dict) -> None:
        (self.dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def test_missing_config_raises(self) -> None:
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_invalid_json_raises(self) -> None:
        (self.dir / "config.json").write_text("{pas du json", encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_valid_load_fills_defaults(self) -> None:
        self.write(base_config())
        cfg = config_mod.load(self.dir)
        self.assertEqual(cfg["digest"]["lookback_hours"], 18)
        self.assertEqual(cfg["digest"]["min_interval_hours"], 20)
        self.assertEqual(cfg["kchat"]["base_url"],
                         "https://kchat.example.com/api/v4")
        self.assertEqual(cfg["plan"]["expire_hours"], 24)
        self.assertEqual(cfg["rules"], {"rules": [], "sensitive_senders": []})
        self.assertIn("_config_dir", cfg)

    def test_missing_kchat_base_url_raises(self) -> None:
        # L'instance kChat est une donnée privée : requise dans la config,
        # jamais un défaut en dur dans le code (fail-closed).
        cfg = base_config()
        cfg.pop("kchat")
        self.write(cfg)
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_enrichment_defaults_off(self) -> None:
        # V4.1 (ARCHITECTURE §10) : l'enrichissement est OPT-IN, off par défaut
        self.write(base_config())
        cfg = config_mod.load(self.dir)
        enr = cfg["digest"]["enrichment"]
        self.assertFalse(enr["enabled"])
        self.assertFalse(enr["gitlab_enrich"])
        self.assertEqual(enr["max_fetch_bytes"], 4096)
        self.assertEqual(enr["max_preview_chars"], 180)

    def test_enrichment_bad_values_rejected(self) -> None:
        self.write(base_config())
        (self.dir / "config.json").write_text(json.dumps(
            {**base_config(), "digest": {"enrichment": {"enabled": "oui"}}}), encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)
        (self.dir / "config.json").write_text(json.dumps(
            {**base_config(), "digest": {"enrichment": {"max_fetch_bytes": 10}}}), encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_empty_allowlist_raises(self) -> None:
        cfg = base_config()
        cfg["destinations"]["allowlist"] = []
        self.write(cfg)
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_forbidden_destination_raises(self) -> None:
        cfg = base_config()
        cfg["destinations"]["allowlist"] = ["INBOX/Trash/Sub"]
        self.write(cfg)
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_writes_bools_required(self) -> None:
        cfg = base_config()
        del cfg["writes"]["enabled"]
        self.write(cfg)
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_rules_duplicate_id_raises(self) -> None:
        self.write(base_config())
        rule = {"id": "r1", "priority": 10, "mode": "propose",
                "match": {"subject_any": ["x"]}, "folder": "INBOX/Auto/News"}
        (self.dir / "rules.json").write_text(
            json.dumps({"rules": [rule, dict(rule)]}), encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_rules_bad_mode_raises(self) -> None:
        self.write(base_config())
        rule = {"id": "r1", "priority": 10, "mode": "sometimes",
                "match": {"subject_any": ["x"]}, "folder": "INBOX/Auto/News"}
        (self.dir / "rules.json").write_text(json.dumps({"rules": [rule]}), encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_rules_auto_without_folder_raises(self) -> None:
        self.write(base_config())
        rule = {"id": "r1", "priority": 10, "mode": "auto", "match": {"subject_any": ["x"]}}
        (self.dir / "rules.json").write_text(json.dumps({"rules": [rule]}), encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_rules_forbidden_folder_raises(self) -> None:
        self.write(base_config())
        rule = {"id": "r1", "priority": 10, "mode": "propose",
                "match": {"subject_any": ["x"]}, "folder": "INBOX/Junk"}
        (self.dir / "rules.json").write_text(json.dumps({"rules": [rule]}), encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_rules_match_string_rejected(self) -> None:
        # une string serait itérée caractère par caractère → fausse positive massive
        self.write(base_config())
        rule = {"id": "r1", "priority": 10, "mode": "auto",
                "match": {"from_any": "spam"}, "folder": "INBOX/Auto/News"}
        (self.dir / "rules.json").write_text(json.dumps({"rules": [rule]}), encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_rules_unknown_match_key_rejected(self) -> None:
        self.write(base_config())
        rule = {"id": "r1", "priority": 10, "mode": "propose",
                "match": {"body_contains": ["x"]}, "folder": "INBOX/Auto/News"}
        (self.dir / "rules.json").write_text(json.dumps({"rules": [rule]}), encoding="utf-8")
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_non_ascii_destination_rejected(self) -> None:
        # les noms non-ASCII arrivent en mUTF-7 via IMAP : incomparables en V1
        cfg = base_config()
        cfg["destinations"]["allowlist"] = ["Dossiers/Privé"]
        self.write(cfg)
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_spaces_in_destination_accepted(self) -> None:
        # l'espace (0x20) est ASCII imprimable, non affecté par mUTF-7 :
        # les dossiers réels « JIRA - Trello - Redmine » doivent charger
        cfg = base_config()
        cfg["destinations"]["allowlist"] = ["JIRA - Trello - Redmine", "Infomaniak services"]
        self.write(cfg)
        loaded = config_mod.load(self.dir)
        self.assertEqual(loaded["destinations"]["allowlist"], ["JIRA - Trello - Redmine", "Infomaniak services"])

    def test_leading_trailing_space_rejected(self) -> None:
        cfg = base_config()
        cfg["destinations"]["allowlist"] = [" GitLab "]
        self.write(cfg)
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)

    def test_space_does_not_neutralize_forbidden(self) -> None:
        # un espace interne ne doit pas neutraliser les patterns interdits :
        # « Trash Sub » / « Spam 2 » restent des destinations Corbeille/Spam
        for bad in ("INBOX/Trash Sub", "Spam 2"):
            cfg = base_config()
            cfg["destinations"]["allowlist"] = [bad]
            self.write(cfg)
            with self.assertRaises(config_mod.ConfigError, msg=bad):
                config_mod.load(self.dir)

    def test_source_mailbox_pinned_to_inbox(self) -> None:
        # V1 fail-closed : UID context — seule INBOX est une source supportée
        cfg = base_config()
        cfg["source"]["mailbox"] = "INBOX/Sous-dossier"
        self.write(cfg)
        with self.assertRaises(config_mod.ConfigError):
            config_mod.load(self.dir)


class SecretsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._env_patcher = mock.patch.dict(os.environ)
        self._env_patcher.start()
        for key in ("MAIL_TRIAGE_IMAP_PASSWORD", "MAIL_TRIAGE_TEST_SECRET"):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        self._env_patcher.stop()
        self._tmp.cleanup()

    def test_env_precedence(self) -> None:
        os.environ["MAIL_TRIAGE_TEST_SECRET"] = "from-env"
        self.assertEqual(config_mod.get_secret("MAIL_TRIAGE_TEST_SECRET"), "from-env")

    def test_env_file_fallback(self) -> None:
        env_file = self.dir / ".env"
        env_file.write_text('# comment\nMAIL_TRIAGE_TEST_SECRET="from-file"\n', encoding="utf-8")
        self.assertEqual(
            config_mod.get_secret("MAIL_TRIAGE_TEST_SECRET", env_file=env_file), "from-file")

    def test_missing_secret_raises(self) -> None:
        with self.assertRaises(config_mod.SecretError):
            config_mod.get_secret("MAIL_TRIAGE_TEST_SECRET",
                                  env_file=self.dir / "absent.env")


class PrivateDirTestCase(unittest.TestCase):
    def test_ensure_private_dir_mode_0700(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "private"
            config_mod.ensure_private_dir(target)
            self.assertTrue(target.exists())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
