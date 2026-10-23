#!/usr/bin/env python3
"""Tests du moteur de règles : déterminisme, gardes, invariants de destination."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import policy  # noqa: E402

ALLOWLIST = ["INBOX/Auto/News", "INBOX/Auto/Notifications"]


def rule(**overrides) -> dict:
    base = {"id": "r-news", "priority": 50, "mode": "propose",
            "match": {"from_domain_any": ["news.example.com"]},
            "folder": "INBOX/Auto/News"}
    base.update(overrides)
    return base


def mail(**overrides) -> dict:
    base = {"uid": 42, "from": "bulletin@news.example.com", "to": "me@example.com",
            "subject": "Newsletter hebdo", "seen": False}
    base.update(overrides)
    return base


class PseudonymizeTestCase(unittest.TestCase):
    def test_deterministic_and_truncated(self) -> None:
        a = policy.pseudonymize("User@Example.com")
        b = policy.pseudonymize("user@example.com")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 12)

    def test_none(self) -> None:
        self.assertEqual(policy.pseudonymize(None), "none")


class DestinationTestCase(unittest.TestCase):
    def test_allowed(self) -> None:
        self.assertTrue(policy.destination_is_allowed("INBOX/Auto/News", ALLOWLIST))

    def test_not_in_allowlist(self) -> None:
        self.assertFalse(policy.destination_is_allowed("INBOX/Elsewhere", ALLOWLIST))

    def test_forbidden_segments(self) -> None:
        for folder in ("INBOX/Trash/Sub", "INBOX/Junk", "INBOX/Spam2/News",
                       "INBOX/Corbeille", "INBOX/Poubelle", "INBOX/Sent Mail"):
            self.assertFalse(policy.destination_is_allowed(folder, ALLOWLIST),
                             f"{folder} doit être interdit")

    def test_sentry_not_confused_with_sent(self) -> None:
        # Bug réel : "sent" ⊂ "sentry" interdisait le dossier Sentry.
        self.assertTrue(policy.destination_is_allowed("Sentry", ["Sentry"]))

    def test_empty(self) -> None:
        self.assertFalse(policy.destination_is_allowed("", ALLOWLIST))


class MatchTestCase(unittest.TestCase):
    def test_from_domain(self) -> None:
        self.assertTrue(policy.rule_matches(rule(), mail()))
        self.assertFalse(
            policy.rule_matches(rule(), mail(**{"from": "a@other.example"})))

    def test_subject_case_insensitive(self) -> None:
        r = rule(match={"subject_any": ["NEWSLETTER"]})
        self.assertTrue(policy.rule_matches(r, mail()))

    def test_multiple_keys_are_and(self) -> None:
        r = rule(match={"from_domain_any": ["news.example.com"],
                        "subject_any": ["inexistant"]})
        self.assertFalse(policy.rule_matches(r, mail()))

    def test_empty_match_never(self) -> None:
        self.assertFalse(policy.rule_matches(rule(match={}), mail()))


class EvaluateTestCase(unittest.TestCase):
    def test_no_rules_keeps(self) -> None:
        out = policy.evaluate(mail(), {"rules": [], "sensitive_senders": []}, ALLOWLIST)
        self.assertEqual(out["action"], "keep")
        self.assertIsNone(out["rule_id"])

    def test_sensitive_sender_absolute_guard(self) -> None:
        doc = {"rules": [rule(mode="auto", priority=1)],
               "sensitive_senders": ["news.example.com"]}
        out = policy.evaluate(mail(), doc, ALLOWLIST)
        self.assertEqual(out["action"], "keep")
        self.assertEqual(out["rule_id"], "sensitive_sender")
        self.assertEqual(out["mode"], "never")

    def test_priority_lower_wins(self) -> None:
        doc = {"rules": [rule(id="high-num", priority=90, mode="propose"),
                         rule(id="low-num", priority=5, mode="propose")],
               "sensitive_senders": []}
        out = policy.evaluate(mail(), doc, ALLOWLIST)
        self.assertEqual(out["rule_id"], "low-num")

    def test_never_mode_keeps(self) -> None:
        doc = {"rules": [rule(mode="never")], "sensitive_senders": []}
        out = policy.evaluate(mail(), doc, ALLOWLIST)
        self.assertEqual(out["action"], "keep")
        self.assertEqual(out["mode"], "never")

    def test_propose_keeps_with_folder(self) -> None:
        doc = {"rules": [rule(mode="propose")], "sensitive_senders": []}
        out = policy.evaluate(mail(), doc, ALLOWLIST)
        self.assertEqual(out["action"], "keep")
        self.assertEqual(out["folder"], "INBOX/Auto/News")

    def test_auto_moves(self) -> None:
        doc = {"rules": [rule(mode="auto")], "sensitive_senders": []}
        out = policy.evaluate(mail(), doc, ALLOWLIST)
        self.assertEqual(out["action"], "move")
        self.assertEqual(out["folder"], "INBOX/Auto/News")

    def test_auto_outside_allowlist_fails_closed(self) -> None:
        doc = {"rules": [rule(mode="auto", folder="INBOX/Hors-Allowlist")],
               "sensitive_senders": []}
        with self.assertRaises(policy.PolicyError):
            policy.evaluate(mail(), doc, ALLOWLIST)


class MaskSubjectTestCase(unittest.TestCase):
    def test_masked(self) -> None:
        subject, masked = policy.mask_subject(
            "Votre mot de passe expire", ["(?i)mot de passe"])
        self.assertTrue(masked)
        self.assertEqual(subject, "[sujet masqué]")

    def test_not_masked(self) -> None:
        subject, masked = policy.mask_subject("Newsletter hebdo", ["(?i)mot de passe"])
        self.assertFalse(masked)
        self.assertEqual(subject, "Newsletter hebdo")

    def test_invalid_pattern_skipped(self) -> None:
        subject, masked = policy.mask_subject("Sujet", ["[invalide"])
        self.assertFalse(masked)
        self.assertEqual(subject, "Sujet")

    def test_empty_subject_placeholder(self) -> None:
        subject, masked = policy.mask_subject("", [])
        self.assertEqual(subject, "(sans sujet)")


if __name__ == "__main__":
    unittest.main()
