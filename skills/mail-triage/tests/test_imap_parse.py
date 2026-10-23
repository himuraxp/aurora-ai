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


class BodystructureTestCase(unittest.TestCase):
    """V4.1 — parse BODYSTRUCTURE → section text/plain ciblée (structures
    synthétiques, sans connexion)."""

    def _pick(self, structure: str):
        tokens = imap_client._tokenize_bodystructure(structure)
        node, _ = imap_client._parse_bodystructure(tokens, 0, [])
        return imap_client._pick_text_plain(node)

    def test_simple_text_plain(self) -> None:
        result = self._pick('("text" "plain" ("charset" "utf-8") NIL NIL '
                            '"quoted-printable" 1234 56 NIL NIL NIL NIL)')
        self.assertEqual(result["section"], "1")
        self.assertEqual(result["encoding"], "quoted-printable")
        self.assertEqual(result["size"], 1234)

    def test_multipart_alternative_first_part(self) -> None:
        structure = ('(("text" "plain" NIL NIL NIL "7bit" 100 5 NIL NIL NIL NIL)'
                     '("text" "html" NIL NIL NIL "7bit" 200 10 NIL NIL NIL NIL) '
                     '"ALTERNATIVE" ("boundary" "xyz") NIL NIL NIL)')
        result = self._pick(structure)
        self.assertEqual(result["section"], "1")
        self.assertEqual(result["encoding"], "7bit")

    def test_attachment_first_plain_second(self) -> None:
        structure = ('(("application" "pdf" ("name" "doc.pdf") NIL NIL "base64" 5000 20 '
                     'NIL ("ATTACHMENT" ("FILENAME" "doc.pdf")) NIL NIL)'
                     '("text" "plain" NIL NIL NIL "8bit" 300 4 NIL NIL NIL NIL) '
                     '"MIXED" ("boundary" "b1") NIL NIL NIL)')
        result = self._pick(structure)
        self.assertEqual(result["section"], "2")  # la pièce jointe n'est jamais choisie
        self.assertEqual(result["encoding"], "8bit")

    def test_nested_multipart_path(self) -> None:
        # part 1 = multipart/related (html + image), part 2 = text/plain → section 2
        structure = ('((("text" "html" NIL NIL NIL "7bit" 400 9 NIL NIL NIL NIL)'
                     '("image" "png" ("name" "img.png") NIL NIL "base64" 900 3 '
                     'NIL ("INLINE" ("FILENAME" "img.png")) NIL NIL) '
                     '"RELATED" ("boundary" "r1") NIL NIL NIL)'
                     '("text" "plain" NIL NIL NIL "7bit" 120 2 NIL NIL NIL NIL) '
                     '"MIXED" ("boundary" "m1") NIL NIL NIL)')
        result = self._pick(structure)
        self.assertEqual(result["section"], "2")

    def test_html_only_no_candidate(self) -> None:
        structure = ('(("text" "html" NIL NIL NIL "7bit" 200 10 NIL NIL NIL NIL) '
                     '"ALTERNATIVE" ("boundary" "xyz") NIL NIL NIL)')
        self.assertIsNone(self._pick(structure))

    def test_escaped_quote_in_params(self) -> None:
        structure = '("text" "plain" ("name" "a\\"b.txt") NIL NIL "7bit" 10 1 NIL NIL NIL)'
        result = self._pick(structure)
        self.assertEqual(result["section"], "1")

    def test_message_rfc822_fail_closed(self) -> None:
        # un email transféré imbriqué → renonciation (fail-closed), jamais un guess
        structure = '("message" "rfc822" NIL NIL NIL "7bit" 500 3 NIL NIL NIL)'
        with self.assertRaises(ValueError):
            tokens = imap_client._tokenize_bodystructure(structure)
            imap_client._parse_bodystructure(tokens, 0, [])

    def test_garbage_structure_raises(self) -> None:
        with self.assertRaises(ValueError):
            tokens = imap_client._tokenize_bodystructure("((incomplet")
            imap_client._parse_bodystructure(tokens, 0, [])


class FakeStructureConn:
    """Connexion factice : responses consommées dans l'ordre."""

    def __init__(self, responses):
        self._responses = list(responses)

    def uid(self, cmd, *args):
        return "OK", self._responses.pop(0)


class FetchPreviewTestCase(unittest.TestCase):
    def test_fetch_body_structure_parses_response(self) -> None:
        resp = [b'3 (UID 3 BODYSTRUCTURE ("text" "plain" ("charset" "utf-8") '
                b'NIL NIL "quoted-printable" 1234 56 NIL NIL NIL NIL))']
        conn = FakeStructureConn([resp])
        result = imap_client.fetch_body_structure(conn, 3)
        self.assertEqual(result["section"], "1")
        self.assertEqual(result["encoding"], "quoted-printable")

    def test_fetch_body_structure_garbage_returns_none(self) -> None:
        conn = FakeStructureConn([[b'3 (UID 3 BODYSTRUCTURE ((desordre incomplet)']])
        self.assertIsNone(imap_client.fetch_body_structure(conn, 3))

    def test_fetch_body_structure_missing_keyword_returns_none(self) -> None:
        conn = FakeStructureConn([[b'3 (UID 3 FLAGS (\\Seen))']])
        self.assertIsNone(imap_client.fetch_body_structure(conn, 3))

    def test_fetch_body_preview_uses_peek_and_section(self) -> None:
        structure = [b'3 (UID 3 BODYSTRUCTURE ("text" "plain" NIL NIL NIL "7bit" 800 9 NIL NIL NIL NIL))']
        # la réponse PEEK : tuple (meta, literal) puis b')'
        peek_response = [(b'3 (UID 3 BODY[1]<0> {4096}', b"Bonjour,\n\nPeux-tu relire la spec ?"), b')']
        conn = FakeStructureConn([structure, peek_response])
        result = imap_client.fetch_body_preview(conn, 3, 4096)
        self.assertEqual(result["encoding"], "7bit")
        self.assertIn(b"relire la spec", result["raw"])

    def test_fetch_body_preview_no_plain_section_returns_none(self) -> None:
        structure = [b'3 (UID 3 BODYSTRUCTURE ("text" "html" NIL NIL NIL "7bit" 800 9 NIL NIL NIL NIL))']
        conn = FakeStructureConn([structure])
        self.assertIsNone(imap_client.fetch_body_preview(conn, 3, 4096))


if __name__ == "__main__":
    unittest.main()
