#!/usr/bin/env python3
"""Tests du digest : fenêtre temporelle, contenu, masquage, rendu, publication."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import digest as digest_mod  # noqa: E402
import state as state_mod  # noqa: E402

NOW = datetime(2026, 10, 23, 8, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def config(**digest_overrides) -> dict:
    digest_cfg = {"enabled": True, "lookback_hours": 18, "always_inbox_cap": 10,
                  "min_interval_hours": 20, "sensitive_subject_patterns": []}
    digest_cfg.update(digest_overrides)
    return {"digest": digest_cfg, "source": {"mailbox": "INBOX"}}


class FakeKChat:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def ensure_direct_channel(self, bot_id: str, user_id: str) -> str:
        return "chan1"

    def post_message(self, channel_id: str, message: str) -> dict:
        self.posts.append(message)
        return {"id": f"post{len(self.posts)}"}


class WindowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_window_uses_lookback(self) -> None:
        window = digest_mod.compute_window(self.state, config(), NOW)
        self.assertIsNone(window["previous_id"])
        self.assertAlmostEqual((NOW - window["start"]).total_seconds(), 18 * 3600, delta=5)
        self.assertAlmostEqual((window["end"] - NOW).total_seconds(), 0, delta=5)

    def test_window_continues_from_last_confirmed(self) -> None:
        prev_end = NOW - timedelta(hours=16)
        self.state.create_digest("d0", iso(prev_end - timedelta(hours=2)), iso(prev_end),
                                 "[m:d0]", iso(NOW))
        self.state.set_digest_state("d0", "sent", post_id="p0", resolved_at=iso(NOW))
        window = digest_mod.compute_window(self.state, config(), NOW)
        self.assertEqual(window["previous_id"], "d0")
        self.assertEqual(window["start"], prev_end)


class BuildDigestTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state = state_mod.State(Path(self._tmp.name) / "state.sqlite")
        self.window = {"start": NOW - timedelta(hours=2), "end": NOW, "previous_id": None}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def messages(self) -> list[dict]:
        return [
            {"uid": 10, "from": "a@news.example.com", "subject": "Nouveautés",
             "internaldate": iso(NOW - timedelta(minutes=30)), "seen": False},
            {"uid": 11, "from": "b@example.com", "subject": "Déjà digesté",
             "internaldate": iso(NOW - timedelta(minutes=20)), "seen": False},
            {"uid": 12, "from": "c@example.com", "subject": "Vieux non lu",
             "internaldate": iso(NOW - timedelta(hours=10)), "seen": False},
            {"uid": 13, "from": "d@example.com", "subject": "Vieux lu",
             "internaldate": iso(NOW - timedelta(hours=10)), "seen": True},
        ]

    def test_new_vs_always_inbox(self) -> None:
        self.state.mark_digest_msg("INBOX", 1, 11, None, "d-old")
        built = digest_mod.build_digest(self.state, self.messages(), config(),
                                        self.window, "d1", mailbox="INBOX", uidvalidity=1)
        self.assertEqual([m["uid"] for m in built["new"]], [10])
        self.assertEqual([m["uid"] for m in built["always_inbox"]], [12])
        self.assertEqual(built["marker"], "[mail-triage-digest:d1]")

    def test_sensitive_subject_masked(self) -> None:
        messages = [{"uid": 20, "from": "hr@example.com",
                     "subject": "Votre mot de passe expire",
                     "internaldate": iso(NOW - timedelta(minutes=5)), "seen": False}]
        built = digest_mod.build_digest(
            self.state, messages, config(sensitive_subject_patterns=["(?i)mot de passe"]),
            self.window, "d2", uidvalidity=1)
        self.assertTrue(built["new"][0]["subject_masked"])
        self.assertEqual(built["new"][0]["subject"], "[sujet masqué]")

    def test_always_inbox_capped(self) -> None:
        messages = [{"uid": 100 + i, "from": f"x{i}@example.com", "subject": f"s{i}",
                     "internaldate": iso(NOW - timedelta(hours=10)), "seen": False}
                    for i in range(15)]
        built = digest_mod.build_digest(self.state, messages, config(),
                                        self.window, "d3", uidvalidity=1)
        self.assertEqual(len(built["always_inbox"]), 10)

    def test_bad_internaldate_excluded(self) -> None:
        messages = [{"uid": 30, "from": "x@example.com", "subject": "s",
                     "internaldate": "not-a-date", "seen": False}]
        built = digest_mod.build_digest(self.state, messages, config(),
                                        self.window, "d4", uidvalidity=1)
        # Date illisible = jamais classé « nouveau » ; non lu de date inconnue
        # reste visible dans « toujours dans l'Inbox » (plafonné).
        self.assertEqual(built["new"], [])
        self.assertEqual([m["uid"] for m in built["always_inbox"]], [30])


class AggregationTestCase(unittest.TestCase):
    """Pipeline V2 : dédup Message-ID, regroupement conversations, compteurs séparés."""

    @staticmethod
    def _msg(uid: int, subject: str, *, mid: str | None = None, refs: str = "",
             mode: str = "never", action: str = "keep",
             minutes_ago: int = 10) -> dict:
        return {
            "uid": uid, "from": "gitlab@infomaniak.com", "subject": subject,
            "message_id": mid or f"<m{uid}@x>", "references": refs,
            "internaldate": iso(NOW - timedelta(minutes=minutes_ago)),
            "seen": False, "mode": mode, "rule_id": None, "decision_action": action,
        }

    def test_dedupe_by_message_id(self) -> None:
        items = [self._msg(1, "s", mid="<same@x>"), self._msg(2, "s", mid="<same@x>"),
                 self._msg(3, "s", mid="<other@x>")]
        unique, dupes = digest_mod._dedupe_by_message_id(items)
        self.assertEqual(len(unique), 2)
        self.assertEqual(dupes, 1)

    def test_gitlab_thread_grouped_with_counter(self) -> None:
        # 12 notifications de la même MR (Message-IDs distincts) = 1 conversation
        subject = "Re: Player | chore(podcast): refactor chromecast init (!89)"
        items = [self._msg(10 + i, subject, mid=f"<n{i}@x>") for i in range(12)]
        convs = digest_mod.group_conversations(items)
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["count"], 12)
        self.assertEqual(convs[0]["label"], "Player !89")  # casse d'origine préservée
        self.assertIn("refactor chromecast", convs[0]["title"])
        self.assertNotIn("Re:", convs[0]["title"])

    def test_gitlab_two_mrs_stay_distinct(self) -> None:
        items = [self._msg(1, "Player | fix A (!89)", mid="<a@x>"),
                 self._msg(2, "Player | fix B (!90)", mid="<b@x>")]
        convs = digest_mod.group_conversations(items)
        self.assertEqual(len(convs), 2)

    def test_references_chain_grouped(self) -> None:
        # thread réel : B référence le Message-ID de A
        items = [self._msg(1, "Discussion design", mid="<root@x>"),
                 self._msg(2, "Re: Discussion design", mid="<reply@x>", refs="<root@x>")]
        convs = digest_mod.group_conversations(items)
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["count"], 2)

    def test_plain_same_subject_never_merged(self) -> None:
        # deux mails DISTINCTS (pas de Message-ID commun, pas de refs, pas
        # d'identifiant structurel) ne fusionnent JAMAIS sur le seul sujet
        items = [self._msg(1, "Réunion projet", mid="<r1@x>"),
                 self._msg(2, "Réunion projet", mid="<r2@x>")]
        convs = digest_mod.group_conversations(items)
        self.assertEqual(len(convs), 2)

    def test_category_review_beats_auto(self) -> None:
        mixed = [self._msg(1, "Player | x (!89)", mid="<a@x>", mode="propose"),
                 self._msg(2, "Player | x (!89)", mid="<b@x>", mode="auto", action="move")]
        self.assertEqual(digest_mod.conversation_category(mixed), "review")
        pure_auto = [self._msg(3, "Player | y (!90)", mid="<c@x>", mode="auto", action="move")]
        self.assertEqual(digest_mod.conversation_category(pure_auto), "auto")
        unknown = [self._msg(4, "email inconnu", mid="<d@x>")]
        self.assertEqual(digest_mod.conversation_category(unknown), "unknown")

    def test_counter_separation(self) -> None:
        # reçu ≠ unique ; éligible au tri ≠ déplacé confirmé ; proposé ≠ déplacé
        items = [
            self._msg(1, "GitLab MR A (!1)", mid="<a@x>", mode="auto", action="move"),
            self._msg(2, "GitLab MR A (!1)", mid="<b@x>", mode="auto", action="move"),
            self._msg(3, "GitLab MR B (!2)", mid="<c@x>", mode="propose"),
            self._msg(4, "mail inconnu", mid="<d@x>"),
        ]
        convs = digest_mod.group_conversations(items)
        counters = digest_mod._counters(items, items, convs, {"INBOX/Auto/News": 5})
        self.assertEqual(counters["messages_received"], 4)
        self.assertEqual(counters["unique_messages"], 4)
        self.assertEqual(counters["duplicate_messages"], 0)
        self.assertEqual(counters["conversations"], 3)  # MR A regroupée + MR B + inconnu
        self.assertEqual(counters["auto_eligible"], 2)
        self.assertEqual(counters["proposed"], 1)
        self.assertEqual(counters["auto_moved"], 5)

    def test_window_label_in_business_timezone(self) -> None:
        # 06:00→08:00 UTC affiché 08:00→10:00 Europe/Paris (fix P0 ChatGPT)
        label = digest_mod._window_local_label(
            "2026-10-23T06:00:00+00:00", "2026-10-23T08:00:00+00:00", "Europe/Paris")
        self.assertIn("ven. 23 oct.", label)
        self.assertIn("08:00 → 10:00", label)


class RenderPublishTestCase(unittest.TestCase):
    @staticmethod
    def _conv(uid: int, frm: str, subject: str, internaldate: str | None, *,
              masked: bool = False, count: int = 1, label: str | None = None,
              mode: str | None = None, action: str = "keep",
              rule_id: str | None = None) -> dict:
        items = [{"uid": uid + i, "from": frm, "subject": subject, "subject_masked": masked,
                  "message_id": f"<m{uid+i}@x>", "references": "",
                  "internaldate": internaldate, "seen": False,
                  "mode": mode, "rule_id": rule_id, "decision_action": action}
                 for i in range(count)]
        return {"items": items, "count": count, "title": subject,
                "label": label, "last_time": internaldate}

    def _digest(self, conversations: list[dict], counters: dict) -> dict:
        return {
            "id": "d1", "marker": "[mail-triage-digest:d1]",
            "window_start": iso(NOW - timedelta(hours=2)),
            "window_end": iso(NOW),
            "timezone": "Europe/Paris",
            "conversations": conversations,
            "counters": counters,
            "always_inbox": [{"uid": 12, "from": "c@x.com", "subject": "[sujet masqué]",
                              "subject_masked": True, "internaldate": None, "seen": False}],
            "moved_counts": {"INBOX/Auto/News": 3},
        }

    def test_render_v2_contains_marker_and_brief(self) -> None:
        digest_data = self._digest(
            [self._conv(10, "a@x.com", "Nouveautés", iso(NOW - timedelta(minutes=30)))],
            {"messages_received": 1, "unique_messages": 1, "duplicate_messages": 0,
             "conversations": 1, "auto_eligible": 0, "proposed": 0, "auto_moved": 3})
        text = digest_mod.render_markdown(digest_data)
        self.assertIn("[mail-triage-digest:d1]", text)
        self.assertIn("En bref", text)
        self.assertIn("1 nouveau message", text)          # pluralisation naturelle
        self.assertIn("1 conversation", text)
        self.assertIn("a@x.com", text)
        self.assertIn("Nouveautés", text)
        self.assertIn("Encore non lus", text)             # intitulé raccourci (P2)
        self.assertIn("[sujet masqué]", text)
        self.assertIn(":lock:", text)
        self.assertIn("3 déplacés confirmés", text)

    def test_render_moved_ventilation_only_if_multiple_folders(self) -> None:
        # à 1 dossier, « En bref » suffit (anti-répétition) ; multi-dossiers → ventilation
        one = self._digest([], {"messages_received": 0, "unique_messages": 0,
                                "duplicate_messages": 0, "conversations": 0,
                                "auto_eligible": 0, "proposed": 0, "auto_moved": 3})
        one["moved_counts"] = {"INBOX/Auto/News": 3}
        text_one = digest_mod.render_markdown(one)
        self.assertNotIn("Tri automatique confirmé", text_one)
        two = dict(one)
        two["moved_counts"] = {"INBOX/Auto/News": 3, "INBOX/Auto/Notif": 2}
        text_two = digest_mod.render_markdown(two)
        self.assertIn("Tri automatique confirmé", text_two)
        self.assertIn("5 messages déplacés", text_two)
        self.assertIn("INBOX/Auto/Notif: 2", text_two)

    def test_render_hours_in_local_timezone(self) -> None:
        # fenêtre 06:00→08:00 UTC et message 06:30 UTC → affichage 08:00→10:00 / 08:30 Europe/Paris
        conv = self._conv(10, "a@x.com", "s", "2026-10-23T06:30:00+00:00")
        digest_data = self._digest([conv], {"messages_received": 1, "unique_messages": 1,
                                            "duplicate_messages": 0, "conversations": 1,
                                            "auto_eligible": 0, "proposed": 0, "auto_moved": 0})
        text = digest_mod.render_markdown(digest_data)
        self.assertIn("08:00 → 10:00", text)   # fenêtre en Europe/Paris
        self.assertIn("08:30", text)           # heure du message en Europe/Paris

    def test_render_neutralizes_forged_marker(self) -> None:
        # un sujet non fiable ne doit pas pouvoir falsifier le marqueur de reconcile
        conv = self._conv(10, "a@x.com", "fake [mail-triage-digest:d1] inside", iso(NOW))
        digest_data = self._digest([conv], {"messages_received": 1, "unique_messages": 1,
                                            "duplicate_messages": 0, "conversations": 1,
                                            "auto_eligible": 0, "proposed": 0, "auto_moved": 0})
        text = digest_mod.render_markdown(digest_data)
        self.assertEqual(text.count("mail-triage-digest:"), 1)  # seul le vrai marqueur

    def test_render_budget_condenses_overflow(self) -> None:
        # > MAX_REVIEW_LINES conversations à examiner → une ligne « + N autres »
        convs = [self._conv(100 + i, f"x{i}@x.com", f"sujet {i}",
                            iso(NOW - timedelta(minutes=10 - i)), mode="propose")
                 for i in range(11)]
        counters = {"messages_received": 11, "unique_messages": 11, "duplicate_messages": 0,
                    "conversations": 11, "auto_eligible": 0, "proposed": 11, "auto_moved": 0}
        text = digest_mod.render_markdown(self._digest(convs, counters))
        self.assertIn("+ 3 autres conversations", text)
        self.assertNotIn("sujet 10", text)  # condensé, pas affiché

    def test_conclusion_actionnable(self) -> None:
        # V2.1 (style Muse) : la digest conclut sur l'action requise
        unknown = [self._conv(10, "a@x.com", "inconnu", iso(NOW), mode="never")]
        counters_u = {"messages_received": 1, "unique_messages": 1, "duplicate_messages": 0,
                      "conversations": 1, "auto_eligible": 0, "proposed": 0, "auto_moved": 0}
        text_u = digest_mod.render_markdown(self._digest(unknown, counters_u))
        self.assertIn("1 message sans règle reste dans l'Inbox", text_u)
        self.assertIn(":question:", text_u)
        self.assertNotIn("Rien à décider", text_u)

        review = [self._conv(20, "b@x.com", "à valider", iso(NOW), mode="propose")]
        counters_p = dict(counters_u, proposed=1, conversations=1)
        text_p = digest_mod.render_markdown(self._digest(review, counters_p))
        self.assertIn("1 message attend ta décision", text_p)
        self.assertIn(":warning:", text_p)

        covered = [self._conv(30, "c@x.com", "Player | x (!89)", iso(NOW), mode="auto", action="move")]
        counters_c = dict(counters_u, auto_eligible=1)
        text_c = digest_mod.render_markdown(self._digest(covered, counters_c))
        self.assertIn(":thumbsup: Rien à décider", text_c)
        self.assertIn("couverts par les règles de tri", text_c)
        self.assertNotIn("apply --confirm-apply", text_c)  # pas de commandes techniques dans le recap

    def test_publish_returns_post_id(self) -> None:
        fake = FakeKChat()
        result = digest_mod.publish(fake, "bot1", "user1", "# digest")
        self.assertEqual(result, {"channel_id": "chan1", "post_id": "post1"})
        self.assertEqual(fake.posts, ["# digest"])

    def test_marker_format(self) -> None:
        self.assertTrue(digest_mod.new_marker("abc123")
                        .startswith("[mail-triage-digest:"))


class PreviewTestCase(unittest.TestCase):
    """V4.1 — aperçus bornés (ARCHITECTURE §10) : nettoyage, neutralisation,
    gate opt-in, cibles autorisées, rendu."""

    def test_decode_quoted_printable(self) -> None:
        raw = b"Bonjour,=20\nvoici le compte rendu de la r=C3=A9union."
        text = digest_mod._decode_section(raw, "quoted-printable")
        self.assertIn("voici le compte rendu de la réunion", text)

    def test_decode_base64(self) -> None:
        import base64
        raw = base64.b64encode("Rapport hebdomadaire : tout est vert.".encode("utf-8"))
        text = digest_mod._decode_section(raw, "base64")
        self.assertEqual(text, "Rapport hebdomadaire : tout est vert.")

    def test_clean_strips_quotes_and_signature(self) -> None:
        body = ("Bonjour,\n\nPeux-tu valider la PR avant vendredi ?\n"
                "\n> Le 22 oct., Alice a écrit :\n> merci d'avance\n"
                "-- \nAlice Martin\nIngénieure\n\nSuite après la signature.")
        cleaned = digest_mod._clean_preview(body.encode("utf-8"), "7bit")
        self.assertIn("Peux-tu valider la PR avant vendredi ?", cleaned)
        self.assertNotIn("Alice a écrit", cleaned)   # citations retirées
        self.assertNotIn("Ingénieure", cleaned)      # signature → arrêt
        self.assertNotIn("Suite après la signature", cleaned)

    def test_clean_html_only_renounces(self) -> None:
        html = "<html><body><div>Facture n°42 : 150 € TTC</div></body></html>"
        self.assertIsNone(digest_mod._clean_preview(html.encode("utf-8"), "7bit"))

    def test_clean_drops_control_characters(self) -> None:
        body = "Ligne un\x00 avec octet nul\x07 et tab\tsauvegardé."
        cleaned = digest_mod._clean_preview(body.encode("utf-8"), "7bit")
        self.assertNotIn("\x00", cleaned)
        self.assertNotIn("\x07", cleaned)
        self.assertIn("tab sauvegardé", cleaned)  # tabulation → espace

    def test_sanitize_forged_marker_neutralized(self) -> None:
        result = digest_mod._sanitize_preview(
            "voir [mail-triage-digest:d1] ci-dessous", [], 180)
        self.assertNotIn("mail-triage-digest:d1", result["preview"])
        self.assertIn("[marqueur-neutralisé:", result["preview"])

    def test_sanitize_urls_masked(self) -> None:
        result = digest_mod._sanitize_preview(
            "clé : https://example.com/reset?token=SECRET123 merci", [], 180)
        self.assertNotIn("SECRET123", result["preview"])
        self.assertIn("(url masquée)", result["preview"])

    def test_sanitize_sensitive_pattern_suppresses(self) -> None:
        result = digest_mod._sanitize_preview(
            "Contrat : salaire brut annuel 85 000 €", ["contrat", "salaire"], 180)
        self.assertIsNone(result["preview"])
        self.assertEqual(result["suppressed"], "sensitive")

    def test_sanitize_truncates_to_max_chars(self) -> None:
        long_text = ("Première ligne assez longue pour dépasser la limite." * 3
                     + "\nDeuxième ligne.\nTroisième ligne.")
        result = digest_mod._sanitize_preview(long_text, [], 180)
        self.assertLessEqual(len(result["preview"]), 180)
        self.assertNotIn("Troisième ligne", result["preview"])

    def test_targets_exclude_sensibles_but_include_unknown(self) -> None:
        # V4.1 : garde sensible (rule_id présent + never) et sujet masqué → JAMAIS ;
        # inconnu sans règle (mode never, rule_id None) → cible d'aperçu valide
        masked_conv = RenderPublishTestCase._conv(10, "a@x.com", "contrat", iso(NOW),
                                                  masked=True, mode="propose")
        garde = RenderPublishTestCase._conv(20, "b@x.com", "confidentiel", iso(NOW),
                                            mode="never", rule_id="sensitive_sender")
        inconnu = RenderPublishTestCase._conv(30, "c@x.com", "normal", iso(NOW), mode="never")
        built = {"conversations": [masked_conv, garde, inconnu], "always_inbox": [
            {"uid": 12, "subject_masked": True, "mode": "keep"},
            {"uid": 13, "subject_masked": False, "mode": "never", "rule_id": None}]}
        self.assertEqual(digest_mod.preview_targets(built), [30, 13])

    def test_targets_auto_only_with_gitlab_enrich(self) -> None:
        auto_conv = RenderPublishTestCase._conv(40, "gl@x.com", "MR !89", iso(NOW),
                                                mode="auto", action="move")
        built = {"conversations": [auto_conv], "always_inbox": []}
        self.assertEqual(digest_mod.preview_targets(built, gitlab_enrich=False), [])
        self.assertEqual(digest_mod.preview_targets(built, gitlab_enrich=True), [40])

    def test_enrich_gate_off_means_no_fetch(self) -> None:
        conv = RenderPublishTestCase._conv(10, "a@x.com", "s", iso(NOW), mode="propose")
        built = {"conversations": [conv], "always_inbox": []}
        calls = []

        def fetch_fn(uid, max_bytes):
            calls.append(uid)
            return {"raw": b"contenu", "encoding": "7bit"}

        cfg = {"digest": {"enrichment": {"enabled": False}}}
        previews = digest_mod.enrich_previews(built, cfg, fetch_fn)
        self.assertEqual(calls, [])            # gate off : AUCUN fetch
        self.assertEqual(previews, {})

    def test_enrich_gate_on_fetches_and_attaches(self) -> None:
        conv = RenderPublishTestCase._conv(10, "a@x.com", "s", iso(NOW), mode="propose")
        built = {"conversations": [conv], "always_inbox": []}
        cfg = {"digest": {"enrichment": {"enabled": True, "max_fetch_bytes": 4096,
                                         "max_preview_chars": 180},
                          "sensitive_subject_patterns": []}}

        def fetch_fn(uid, max_bytes):
            return {"raw": b"Peux-tu relire la spec avant jeudi ? Merci.",
                    "encoding": "7bit"}

        previews = digest_mod.enrich_previews(built, cfg, fetch_fn)
        self.assertIn(10, previews)
        self.assertIn("relire la spec", previews[10]["preview"])
        digest_mod.attach_previews(built, previews)
        self.assertIn("relire la spec", conv["preview"])
        text = digest_mod.render_markdown(self._render_digest([conv]))
        self.assertIn("> _", text)             # ligne d'aperçu rendue

    def test_enrich_fetch_exception_is_fail_closed(self) -> None:
        conv = RenderPublishTestCase._conv(10, "a@x.com", "s", iso(NOW), mode="propose")
        built = {"conversations": [conv], "always_inbox": []}
        cfg = {"digest": {"enrichment": {"enabled": True}}}

        def fetch_fn(uid, max_bytes):
            raise RuntimeError("imap down")

        previews = digest_mod.enrich_previews(built, cfg, fetch_fn)
        digest_mod.attach_previews(built, previews)
        self.assertTrue(conv["preview_unavailable"])
        text = digest_mod.render_markdown(self._render_digest([conv]))
        self.assertIn("(aperçu indisponible)", text)

    def test_sensitive_target_gets_no_trace_at_all(self) -> None:
        # aperçu sensible → ni extrait, ni mention (fail-silent volontaire)
        conv = RenderPublishTestCase._conv(10, "a@x.com", "s", iso(NOW), mode="propose")
        built = {"conversations": [conv], "always_inbox": []}
        digest_mod.attach_previews(built, {10: {"preview": None, "suppressed": "sensitive"}})
        self.assertNotIn("preview", conv)
        self.assertNotIn("preview_unavailable", conv)
        text = digest_mod.render_markdown(self._render_digest([conv]))
        self.assertNotIn("aperçu", text)

    def _render_digest(self, conversations: list[dict]) -> dict:
        return {
            "id": "d1", "marker": "[mail-triage-digest:d1]",
            "window_start": iso(NOW - timedelta(hours=2)),
            "window_end": iso(NOW),
            "timezone": "Europe/Paris",
            "conversations": conversations,
            "counters": {"messages_received": 1, "unique_messages": 1,
                         "duplicate_messages": 0, "conversations": 1,
                         "auto_eligible": 0, "proposed": 1, "auto_moved": 0},
            "always_inbox": [],
            "moved_counts": {},
        }

    def test_preview_always_inbox_rendered(self) -> None:
        digest_data = self._render_digest([])
        digest_data["always_inbox"] = [{"uid": 12, "from": "c@x.com",
                                        "subject": "Relance devis", "subject_masked": False,
                                        "internaldate": None, "seen": False,
                                        "preview": "Le devis expire fin octobre."}]
        text = digest_mod.render_markdown(digest_data)
        self.assertIn("Le devis expire fin octobre.", text)


if __name__ == "__main__":
    unittest.main()
