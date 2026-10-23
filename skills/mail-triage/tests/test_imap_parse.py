#!/usr/bin/env python3
"""Tests du parsing IMAP (LIST, en-têtes, dates, capabilities) — sans connexion."""
from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import imap_client  # noqa: E402


class ParseListTestCase(unittest.TestCase):
    def test_quoted_with_delimiter(self) -> None:
        parsed = imap_client.parse_list_line(
            b'(\\HasNoChildren) "/" "INBOX/Auto/News"')
        self.assertEqual(parsed, ("/", "INBOX/Auto/News"))

    def test_nil_delimiter(self) -> None:
        parsed = imap_client.parse_list_line(b'(\\HasNoChildren) NIL "weird"')
        self.assertEqual(parsed, (None, "weird"))

    def test_garbage(self) -> None:
        self.assertIsNone(imap_client.parse_list_line(b""))
        self.assertIsNone(imap_client.parse_list_line(b"n'importe quoi"))


class QuoteMailboxTestCase(unittest.TestCase):
    def test_spaces_kept_inside_quotes(self) -> None:
        # dossiers réels avec espaces : le nom est encadré, l'espace préservé
        self.assertEqual(
            imap_client.quote_mailbox("JIRA - Trello - Redmine"),
            '"JIRA - Trello - Redmine"')

    def test_backslash_and_quote_escaped(self) -> None:
        self.assertEqual(imap_client.quote_mailbox('a"b\\c'), '"a\\"b\\\\c"')


class DecodeHeaderTestCase(unittest.TestCase):
    def test_encoded_word(self) -> None:
        self.assertEqual(
            imap_client._decode_header_value("=?utf-8?q?Caf=C3=A9?="), "Café")

    def test_none(self) -> None:
        self.assertEqual(imap_client._decode_header_value(None), "")

    def test_newlines_collapsed(self) -> None:
        self.assertEqual(imap_client._decode_header_value("a\r\n b"), "a b")
        self.assertEqual(imap_client._decode_header_value("a\nb"), "a b")


class InternalDateTestCase(unittest.TestCase):
    def test_utc_conversion(self) -> None:
        dt = imap_client._parse_internaldate(b"23-Oct-2026 08:15:00 +0200")
        self.assertEqual(dt, datetime(2026, 10, 23, 6, 15, 0, tzinfo=timezone.utc))

    def test_invalid(self) -> None:
        self.assertIsNone(imap_client._parse_internaldate(b"garbage"))
        self.assertIsNone(imap_client._parse_internaldate(None))


class CapabilityTestCase(unittest.TestCase):
    def test_move_present_cached(self) -> None:
        conn = types.SimpleNamespace(capabilities=("IMAP4REV1", "MOVE"))
        self.assertTrue(imap_client.has_move_capability(conn))

    def test_move_absent_cached(self) -> None:
        conn = types.SimpleNamespace(capabilities=("IMAP4REV1",))
        self.assertFalse(imap_client.has_move_capability(conn))
        with self.assertRaises(imap_client.ImcpableError):
            imap_client.ensure_move_capability(conn)

    def test_move_case_insensitive(self) -> None:
        conn = types.SimpleNamespace(capabilities=("move",))
        self.assertTrue(imap_client.has_move_capability(conn))

    def test_move_via_explicit_capability_post_auth(self) -> None:
        """Le greeting pré-auth omet MOVE ; CAPABILITY explicite le révèle (bug réel)."""
        conn = types.SimpleNamespace(
            capabilities=("IMAP4REV1", "UIDPLUS"),
            capability=lambda: ("OK", [b"IMAP4rev1 UIDPLUS MOVE QUOTA"]),
        )
        self.assertTrue(imap_client.has_move_capability(conn))

    def test_explicit_capability_failure_falls_back_to_cached(self) -> None:
        def boom():
            raise imap_client.ImapError("cap fail")
        conn = types.SimpleNamespace(capabilities=("IMAP4REV1", "MOVE"), capability=boom)
        self.assertTrue(imap_client.has_move_capability(conn))


if __name__ == "__main__":
    unittest.main()
