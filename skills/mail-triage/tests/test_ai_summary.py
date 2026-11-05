#!/usr/bin/env python3
"""Tests V4.2 — résumés IA (ARCHITECTURE §10.3). Zéro réseau (client mocké),
zéro contenu réel : les fixtures sont des extraits factices. La fixture
build_built reproduit la GÉOMÉTRIE RÉELLE du pipeline V4.1 (attach_previews) :
aperçu attaché sur le DICT CONVERSATION (jamais l'item) pour conversations,
sur l'ITEM pour always_inbox — un test d'intégration exerce en outre la
vraie fonction attach_previews pour verrouiller la géométrie."""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import ai_summary as ai_mod  # noqa: E402
import digest as digest_mod  # noqa: E402

TOKEN = "token-test"
BASE = "https://api.example.invalid/1/ai/pid123/openai/v1"

VALID_ACTION = json.dumps({"summary": "Rappel de revue demain", "tag": "action_probable",
                           "action_reason": "Demande de retour explicite"})
VALID_INFO = json.dumps({"summary": "Newsletter hebdo", "tag": "info", "action_reason": None})


def env_getter(name: str):
    return {"MAIL_TRIAGE_AI_TOKEN": TOKEN}.get(name)


def fake_config(**overrides) -> dict:
    cfg = {"enabled": True, "base_url": BASE, "model": "model-x",
           "token_env": "MAIL_TRIAGE_AI_TOKEN"}
    cfg.update(overrides)
    return cfg


def target_uid(target: dict):
    """UID de la cible quel que soit le niveau (conv → dernier item / inbox)."""
    entry = target["entry"]
    return entry["items"][-1]["uid"] if "items" in entry else entry["uid"]


def build_built(previews: list, inbox_previews: list = None) -> dict:
    """built minimal FIDÈLE à la géométrie V4.1 : aperçu sur la conversation
    (conversations) / sur l'item (always_inbox) + champs de garde V4.1
    (body_readable / subject_masked) présents sur les items."""
    conversations = []
    for index, preview in enumerate(previews):
        conv = {"subject": f"Sujet {index}",
                "items": [{"uid": 100 + index, "subject": f"Sujet {index}",
                           "body_readable": True, "subject_masked": False}]}
        if preview is not None:
            conv["preview"] = preview
        conversations.append(conv)
    inbox = []
    for index, preview in enumerate(inbox_previews or []):
        entry = {"uid": 500 + index, "subject": f"Inbox {index}",
                 "body_readable": True, "subject_masked": False}
        if preview is not None:
            entry["preview"] = preview
        inbox.append(entry)
    return {"conversations": conversations, "always_inbox": inbox}


class FakeClient:
    def __init__(self, responses=None, error=None):
        self.calls: list = []
        self.responses = list(responses or [])
        self.error = error

    def build_user_payload(self, subject: str, preview: str) -> str:
        return f"Sujet : {subject}\n{preview}"

    def complete(self, payload: str) -> str:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class ValidateTestCase(unittest.TestCase):
    def test_valid_action_probable(self):
        out = ai_mod.validate_ai_response(VALID_ACTION)
        self.assertEqual(out["tag"], "action_probable")
        self.assertEqual(out["action_reason"], "Demande de retour explicite")

    def test_valid_info_null_reason(self):
        out = ai_mod.validate_ai_response(VALID_INFO)
        self.assertEqual(out["tag"], "info")
        self.assertIsNone(out["action_reason"])

    def test_valid_uncertain(self):
        out = ai_mod.validate_ai_response(json.dumps(
            {"summary": "Peu clair", "tag": "uncertain", "action_reason": None}))
        self.assertEqual(out["tag"], "uncertain")

    def test_reject_not_json(self):
        self.assertIsNone(ai_mod.validate_ai_response("pas du json"))

    def test_reject_non_object(self):
        self.assertIsNone(ai_mod.validate_ai_response("[1, 2]"))

    def test_reject_unknown_tag(self):
        content = json.dumps({"summary": "x", "tag": "urgent", "action_reason": None})
        self.assertIsNone(ai_mod.validate_ai_response(content))

    def test_reject_summary_over_160(self):
        content = json.dumps({"summary": "a" * 161, "tag": "info", "action_reason": None})
        self.assertIsNone(ai_mod.validate_ai_response(content))

    def test_reject_empty_summary(self):
        content = json.dumps({"summary": "   ", "tag": "info", "action_reason": None})
        self.assertIsNone(ai_mod.validate_ai_response(content))

    def test_reject_action_without_reason(self):
        content = json.dumps({"summary": "x", "tag": "action_probable", "action_reason": None})
        self.assertIsNone(ai_mod.validate_ai_response(content))

    def test_reject_action_reason_over_120(self):
        content = json.dumps({"summary": "x", "tag": "action_probable",
                              "action_reason": "r" * 121})
        self.assertIsNone(ai_mod.validate_ai_response(content))

    def test_reject_info_with_reason(self):
        content = json.dumps({"summary": "x", "tag": "info", "action_reason": "parce que"})
        self.assertIsNone(ai_mod.validate_ai_response(content))

    def test_normalizes_whitespace_no_newline(self):
        content = json.dumps({"summary": "  ligne1\nligne2  ", "tag": "info",
                              "action_reason": None})
        out = ai_mod.validate_ai_response(content)
        self.assertEqual(out["summary"], "ligne1 ligne2")
        self.assertNotIn("\n", out["summary"])


class SanitizeTestCase(unittest.TestCase):
    """Neutralisation markdown/URL/marqueur du texte non fiable (modèle +
    sujet email) — aucun rendu actif ne doit sortir vers kChat."""

    def test_summary_links_and_images_neutralized(self):
        content = json.dumps({
            "summary": "[cliquez](https://evil.example) et ![pixel](https://evil.example/p)",
            "tag": "info", "action_reason": None})
        out = ai_mod.validate_ai_response(content)
        self.assertIsNotNone(out)
        self.assertNotIn("https://", out["summary"])
        self.assertNotIn("[cliquez](", out["summary"])
        self.assertNotIn("![", out["summary"])
        self.assertNotIn("]", out["summary"].replace("\\]", ""))

    def test_summary_digest_marker_neutralized(self):
        content = json.dumps({"summary": "voir mail-triage-digest:FAKE-id 123",
                              "tag": "info", "action_reason": None})
        out = ai_mod.validate_ai_response(content)
        self.assertNotIn(ai_mod._MARKER_PREFIX, out["summary"])

    def test_summary_no_active_markdown_vectors(self):
        # promesse alignée sur la neutralisation V4.1 : pas de lien cliquable,
        # pas d'image/pixel, pas d'URL, pas de marqueur (gras/italique =
        # cosmétique, même exposition que l'extrait V4.1 rendu en italique)
        content = json.dumps({"summary": "**gras** et _it_ et [l](https://evil.example) et `c`",
                              "tag": "info", "action_reason": None})
        out = ai_mod.validate_ai_response(content)
        self.assertNotIn("[l](", out["summary"])
        self.assertNotIn("https://", out["summary"])
        self.assertNotIn("`", out["summary"])

    def test_borne_applies_after_neutralization(self):
        # "[" * 160 → "\[" * 160 (320 chars) après neutralisation → rejet
        content = json.dumps({"summary": "[" * 160, "tag": "info", "action_reason": None})
        self.assertIsNone(ai_mod.validate_ai_response(content))

    def test_action_reason_neutralized(self):
        content = json.dumps({"summary": "s", "tag": "action_probable",
                              "action_reason": "demande (https://evil.example)"})
        out = ai_mod.validate_ai_response(content)
        self.assertNotIn("https://", out["action_reason"])

    def test_clean_text_unchanged(self):
        self.assertEqual(ai_mod._sanitize_ai_text("texte simple sûr"),
                         "texte simple sûr")


class PayloadTestCase(unittest.TestCase):
    def test_subject_neutralized_in_payload(self):
        client = ai_mod.AIClient(BASE, "model-x", TOKEN)
        payload = client.build_user_payload("[clique](https://evil.example)", "extrait sûr")
        self.assertNotIn("https://", payload)
        self.assertNotIn("[clique](", payload)

    def test_payload_bounded_3000_chars(self):
        client = ai_mod.AIClient(BASE, "model-x", TOKEN)
        payload = client.build_user_payload("sujet", "x" * 4000)
        self.assertLessEqual(len(payload), 3000)
        payload = client.build_user_payload("sujet", "ligne\x07controle")
        self.assertNotIn("\x07", payload)


class ResolveConfigTestCase(unittest.TestCase):
    def test_absent_block_disabled(self):
        resolved, reason = ai_mod.resolve_config({}, env_getter)
        self.assertIsNone(resolved)
        self.assertEqual(reason, "disabled")

    def test_empty_block_disabled(self):
        resolved, reason = ai_mod.resolve_config({"ai": {}}, env_getter)
        self.assertEqual(reason, "disabled")

    def test_explicit_false_disabled(self):
        resolved, reason = ai_mod.resolve_config(
            {"ai": {"enabled": False, "base_url": BASE}}, env_getter)
        self.assertEqual(reason, "disabled")

    def test_enabled_non_boolean_rejected(self):
        for wrong in ("true", 1, "yes", None):
            resolved, reason = ai_mod.resolve_config(
                {"ai": fake_config(enabled=wrong)}, env_getter)
            self.assertIsNone(resolved)
            self.assertEqual(reason, "disabled")

    def test_missing_base_url_fail_closed(self):
        resolved, reason = ai_mod.resolve_config(
            {"ai": fake_config(base_url="")}, env_getter)
        self.assertEqual(reason, "missing_base_url")

    def test_missing_model_fail_closed(self):
        resolved, reason = ai_mod.resolve_config(
            {"ai": fake_config(model="")}, env_getter)
        self.assertEqual(reason, "missing_model")

    def test_missing_token_fail_closed(self):
        resolved, reason = ai_mod.resolve_config(
            {"ai": fake_config()}, lambda name: None)
        self.assertEqual(reason, "missing_token")

    def test_resolved_ok_defaults(self):
        resolved, reason = ai_mod.resolve_config({"ai": fake_config()}, env_getter)
        self.assertIsNone(reason)
        self.assertEqual(resolved["token_env"], "MAIL_TRIAGE_AI_TOKEN")
        self.assertEqual(resolved["model"], "model-x")

    def test_budgets_not_configurable(self):
        cfg = fake_config(timeout_seconds=99, budget_seconds=999, max_conversations=99)
        resolved, _ = ai_mod.resolve_config({"ai": cfg}, env_getter)
        self.assertNotIn("timeout_seconds", resolved)
        self.assertNotIn("budget_seconds", resolved)
        self.assertNotIn("max_conversations", resolved)


class TargetsTestCase(unittest.TestCase):
    def test_only_preview_conversations_are_targets(self):
        built = build_built(previews=["extrait 1", None, "extrait 3"])
        targets = ai_mod._ai_targets(built)
        self.assertEqual(len(targets), 2)
        self.assertEqual([target_uid(t) for t in targets], [100, 102])
        # entry = dict conversation (niveau lu par _preview_lines)
        self.assertEqual(targets[0]["entry"]["preview"], "extrait 1")
        self.assertIn("items", targets[0]["entry"])

    def test_conversation_item_level_preview_is_ignored(self):
        # géométrie inversée (preview sur l'item) ne doit JAMAIS créer de cible
        built = build_built(previews=[None])
        built["conversations"][0]["items"][-1]["preview"] = "fuite géométrie"
        self.assertEqual(ai_mod._ai_targets(built), [])

    def test_sensible_without_preview_never_targeted(self):
        built = build_built(previews=[None])
        self.assertEqual(ai_mod._ai_targets(built), [])

    def test_always_inbox_included_after_conversations(self):
        built = build_built(previews=["extrait"], inbox_previews=["extrait inbox"])
        targets = ai_mod._ai_targets(built)
        self.assertEqual([target_uid(t) for t in targets], [100, 500])

    def test_dedup_by_uid(self):
        built = build_built(previews=["a"])
        built["always_inbox"].append({"uid": 100, "preview": "b", "subject": "dup",
                                      "body_readable": True, "subject_masked": False})
        targets = ai_mod._ai_targets(built)
        self.assertEqual(len(targets), 1)

    def test_masked_last_item_skipped(self):
        built = build_built(previews=["extrait"])
        built["conversations"][0]["items"][-1]["subject_masked"] = True
        self.assertEqual(ai_mod._ai_targets(built), [])

    def test_body_unreadable_last_item_skipped(self):
        built = build_built(previews=["extrait"])
        built["conversations"][0]["items"][-1]["body_readable"] = False
        self.assertEqual(ai_mod._ai_targets(built), [])

    def test_masked_inbox_item_skipped(self):
        built = build_built(previews=[], inbox_previews=["extrait"])
        built["always_inbox"][0]["subject_masked"] = True
        self.assertEqual(ai_mod._ai_targets(built), [])


class EnrichTestCase(unittest.TestCase):
    def test_no_targets(self):
        built = build_built(previews=[])
        stats = ai_mod.enrich_ai(built, FakeClient())
        self.assertEqual(stats["status"], "no_targets")

    def test_analyzed_one_attaches_on_conversation(self):
        built = build_built(previews=["extrait factice"])
        client = FakeClient(responses=[VALID_ACTION])
        stats = ai_mod.enrich_ai(built, client)
        self.assertEqual(stats["analyzed"], 1)
        conv = built["conversations"][0]
        self.assertEqual(conv["ai"]["tag"], "action_probable")
        self.assertIn("revue demain", conv["ai"]["summary"])
        self.assertIn("extrait factice", client.calls[0])

    def test_invalid_response_marks_unavailable(self):
        built = build_built(previews=["extrait factice"])
        stats = ai_mod.enrich_ai(built, FakeClient(responses=["reponse non json"]))
        conv = built["conversations"][0]
        self.assertTrue(conv["ai_unavailable"])
        self.assertNotIn("ai", conv)
        self.assertEqual(stats["unavailable"], 1)

    def test_call_error_never_raises(self):
        built = build_built(previews=["extrait factice"])
        stats = ai_mod.enrich_ai(built, FakeClient(error=ai_mod.AICallError("ai_http_500")))
        self.assertEqual(stats["unavailable"], 1)
        self.assertTrue(built["conversations"][0]["ai_unavailable"])

    def test_cap_10_conversations(self):
        built = build_built(previews=[f"extrait {i}" for i in range(12)])
        client = FakeClient(responses=[VALID_INFO] * 12)
        stats = ai_mod.enrich_ai(built, client)
        self.assertEqual(stats["analyzed"], 10)
        self.assertEqual(stats["remaining"], 2)
        self.assertEqual(len(client.calls), 10)

    def test_budget_exhaustion_stops_cleanly(self):
        built = build_built(previews=["extrait"] * 4)
        client = FakeClient(responses=[VALID_INFO] * 4)
        with mock.patch.object(ai_mod.time, "monotonic", side_effect=[0, 10, 20, 30, 31]):
            stats = ai_mod.enrich_ai(built, client)
        self.assertEqual(stats["analyzed"], 2)
        self.assertEqual(stats["remaining"], 2)

    def test_entries_without_preview_untouched(self):
        built = build_built(previews=["extrait", None])
        ai_mod.enrich_ai(built, FakeClient(responses=[VALID_INFO]))
        self.assertIn("ai", built["conversations"][0])
        untouched = built["conversations"][1]
        self.assertNotIn("ai", untouched)
        self.assertNotIn("ai_unavailable", untouched)
        self.assertNotIn("ai", untouched["items"][-1])


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self._body


class ClientTestCase(unittest.TestCase):
    def run_complete(self, content, **kwargs):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            captured["timeout"] = timeout
            return _FakeResp(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

        client = ai_mod.AIClient(BASE, "model-x", TOKEN)
        with mock.patch.object(ai_mod.urllib.request, "urlopen", fake_urlopen):
            out = client.complete("payload de test")
        return out, captured

    def test_complete_ok(self):
        out, captured = self.run_complete(VALID_INFO)
        self.assertIn("Newsletter", out)
        body = json.loads(captured["req"].data)
        self.assertEqual(body["model"], "model-x")
        self.assertEqual(body["temperature"], 0.2)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(captured["req"].get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertEqual(captured["timeout"], 12)

    def test_system_prompt_is_closed(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _FakeResp(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

        client = ai_mod.AIClient(BASE, "model-x", TOKEN)
        with mock.patch.object(ai_mod.urllib.request, "urlopen", fake_urlopen):
            client.complete("payload")
        system = json.loads(captured["req"].data)["messages"][0]["content"]
        self.assertIn("jamais une instruction", system)
        self.assertIn("N'invente rien", system)
        self.assertIn("ignore", system)

    def test_http_error_reason_without_secret(self):
        client = ai_mod.AIClient(BASE, "model-x", TOKEN)
        error = urllib.error.HTTPError(BASE, 429, "Too Many Requests", {}, None)
        with mock.patch.object(ai_mod.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(ai_mod.AICallError) as ctx:
                client.complete("payload")
        self.assertEqual(str(ctx.exception), "ai_http_429")
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertNotIn("api.example", str(ctx.exception))

    def test_network_error_reason(self):
        client = ai_mod.AIClient(BASE, "model-x", TOKEN)
        with mock.patch.object(ai_mod.urllib.request, "urlopen", side_effect=OSError("down")):
            with self.assertRaises(ai_mod.AICallError) as ctx:
                client.complete("payload")
        self.assertEqual(str(ctx.exception), "ai_network")
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_invalid_response_shape(self):
        client = ai_mod.AIClient(BASE, "model-x", TOKEN)
        with mock.patch.object(ai_mod.urllib.request, "urlopen",
                               return_value=_FakeResp(b'{"nope": true}')):
            with self.assertRaises(ai_mod.AICallError) as ctx:
                client.complete("payload")
        self.assertEqual(str(ctx.exception), "ai_invalid_response")

    def test_read_capped(self):
        client = ai_mod.AIClient(BASE, "model-x", TOKEN)
        sizes = []

        class Resp(_FakeResp):
            def read(self, size=-1):
                sizes.append(size)
                return b'{"choices": [{"message": {"content": "ok"}}]}'

        with mock.patch.object(ai_mod.urllib.request, "urlopen", return_value=Resp(b"")):
            client.complete("payload")
        self.assertEqual(sizes, [64 * 1024])


class IntegrationTestCase(unittest.TestCase):
    """Intégration géométrique : built réel via la VRAIE attach_previews
    (frontière exacte du bug), enrich mocké, rendu — verrouille la chaîne
    conversation → cible → ai au bon niveau → ligne « Analyse IA »."""

    def _built(self) -> dict:
        return {
            "conversations": [{"subject": "Revue de MR", "items": [
                {"uid": 1, "subject": "Revue de MR",
                 "body_readable": True, "subject_masked": False}]}],
            "always_inbox": [{"uid": 2, "subject": "Alerte serveur",
                              "body_readable": True, "subject_masked": False}],
        }

    def _previews(self) -> dict:
        return {1: {"preview": "extrait conv publiable", "suppressed": None},
                2: {"preview": "extrait inbox publiable", "suppressed": None}}

    def test_conversation_and_inbox_targeted_at_correct_geometry(self):
        built = self._built()
        digest_mod.attach_previews(built, self._previews())
        # géométrie V4.1 réelle : conv["preview"], item["preview"]
        self.assertIn("preview", built["conversations"][0])
        self.assertIn("preview", built["always_inbox"][0])
        cfg = {"digest": {"ai": fake_config()}}
        with mock.patch.object(ai_mod.AIClient, "complete", return_value=VALID_ACTION):
            stats = digest_mod.enrich_ai_summaries(built, cfg, env_getter=env_getter)
        self.assertEqual(stats["analyzed"], 2)
        self.assertIn("ai", built["conversations"][0])
        self.assertIn("ai", built["always_inbox"][0])
        conv_lines = "\n".join(digest_mod._preview_lines(built["conversations"][0]))
        self.assertIn("Analyse IA · action probable", conv_lines)

    def test_sensitive_conversation_never_targeted(self):
        built = self._built()
        previews = {1: {"preview": None, "suppressed": "sensitive"},
                    2: {"preview": "extrait inbox publiable", "suppressed": None}}
        digest_mod.attach_previews(built, previews)
        cfg = {"digest": {"ai": fake_config()}}
        with mock.patch.object(ai_mod.AIClient, "complete", return_value=VALID_INFO):
            stats = digest_mod.enrich_ai_summaries(built, cfg, env_getter=env_getter)
        # sensible : aucun aperçu attaché → aucune trace, aucune cible conv
        self.assertNotIn("preview", built["conversations"][0])
        self.assertNotIn("ai", built["conversations"][0])
        self.assertNotIn("ai_unavailable", built["conversations"][0])
        self.assertEqual(stats["analyzed"], 1)  # only inbox


class DigestWiringTestCase(unittest.TestCase):
    def test_gate_off_built_unchanged(self):
        built = build_built(previews=["extrait factice"])
        stats = digest_mod.enrich_ai_summaries(built, {"digest": {}})
        self.assertEqual(stats["status"], "disabled")
        conv = built["conversations"][0]
        self.assertNotIn("ai", conv)
        self.assertNotIn("ai_unavailable", conv)

    def test_enabled_missing_token_never_calls_network(self):
        built = build_built(previews=["extrait factice"])
        cfg = {"digest": {"ai": fake_config()}}
        with mock.patch.object(ai_mod.urllib.request, "urlopen") as fake_open:
            stats = digest_mod.enrich_ai_summaries(built, cfg, env_getter=lambda name: None)
        self.assertEqual(stats["status"], "missing_token")
        fake_open.assert_not_called()
        self.assertNotIn("ai", built["conversations"][0])

    def test_enabled_with_config_runs_and_attaches(self):
        built = build_built(previews=["extrait factice"])
        cfg = {"digest": {"ai": fake_config()}}
        with mock.patch.object(ai_mod.AIClient, "complete", return_value=VALID_INFO):
            stats = digest_mod.enrich_ai_summaries(built, cfg, env_getter=env_getter)
        self.assertEqual(stats["analyzed"], 1)
        self.assertEqual(built["conversations"][0]["ai"]["tag"], "info")


class PreviewLinesTestCase(unittest.TestCase):
    def test_preview_plus_ai_action(self):
        entry = {"preview": "extrait", "ai": {"summary": "Rappel demain",
                                              "tag": "action_probable",
                                              "action_reason": "demande explicite"}}
        lines = digest_mod._preview_lines(entry)
        self.assertEqual(lines[0], "> _extrait_")
        self.assertIn("Analyse IA · action probable : Rappel demain", lines[1])

    def test_labels_exact(self):
        for tag, label in (("info", "info"), ("action_probable", "action probable"),
                           ("uncertain", "incertain")):
            entry = {"ai": {"summary": "s", "tag": tag, "action_reason": None}}
            lines = digest_mod._preview_lines(entry)
            self.assertIn(f"Analyse IA · {label} : s", lines[0])

    def test_never_action_required_wording(self):
        entry = {"ai": {"summary": "s", "tag": "action_probable", "action_reason": "r"}}
        self.assertNotIn("Action requise", "\n".join(digest_mod._preview_lines(entry)))

    def test_unavailable_mention(self):
        lines = digest_mod._preview_lines({"ai_unavailable": True})
        self.assertEqual(lines, ["> _(Analyse indisponible)_"])

    def test_nothing_unchanged(self):
        self.assertEqual(digest_mod._preview_lines({}), [])


if __name__ == "__main__":
    unittest.main()
