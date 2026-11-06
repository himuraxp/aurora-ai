#!/usr/bin/env python3
"""Tests digest V5 — matrice de non-régression (conception cowork ChatGPT).

Chaque cas de la table §6 de la conception V5 correspond à un test :
silence utile, compteur d'échecs factuel, hiérarchie humain/automatique,
échappement, budgets, conservation des compteurs, reproductibilité.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import digest_v5  # noqa: E402

NOW = datetime(2026, 11, 4, 8, 0, 0, tzinfo=timezone.utc)
MARKER = "[mail-triage-digest:test-id]"


def iso(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def config(**overrides) -> dict:
    v5 = {
        "automation_sources": [{
            "id": "gitlab", "sender": "gitlab@infomaniak.com",
            "failure_patterns": ["\\bfailed pipeline\\b"],
            "recovery_patterns": ["\\bfixed pipeline\\b"],
        }],
        "vip_senders": ["boss@company.com"],
        "client_domains": ["clientcorp.ch"],
        "hr_senders": ["rh@company.com"],
        "action_patterns": [{"id": "invoice", "pattern": "\\bfacture à régler\\b"}],
    }
    v5.update(overrides)
    return {"digest_v5": v5}


def item(sender: str, subject: str, *, action: str = "keep", mode: str = "never",
         minutes_ago: int = 10, uid: int = 1) -> dict:
    return {"uid": uid, "from": sender, "subject": subject, "subject_masked": False,
            "message_id": f"<{uid}@x>", "references": "", "internaldate": iso(minutes_ago),
            "seen": False, "mode": mode, "rule_id": None, "decision_action": action,
            "body_readable": False}


def conversation(items: list) -> dict:
    return {"items": items, "count": len(items),
            "title": items[-1]["subject"], "label": None,
            "last_time": items[-1]["internaldate"]}


def built_of(conversations: list, *, unique: list | None = None, auto_eligible: int = 0) -> dict:
    unique_items = unique if unique is not None else [m for c in conversations for m in c["items"]]
    return {
        "conversations": conversations,
        "unique": unique_items,
        "counters": {"messages_received": len(unique_items), "unique_messages": len(unique_items),
                     "conversations": len(conversations), "auto_eligible": auto_eligible,
                     "proposed": 0, "auto_moved": 0},
        "marker": MARKER,
    }


def gitlab_subjects(count: int, *, failures: int = 0) -> list:
    subjects = []
    for n in range(count):
        if n < failures:
            subjects.append(f"infomaniak-agent | Failed pipeline for main | sha{n:02x}")
        else:
            subjects.append(f"infomaniak-agent | Pipeline has passed | sha{n:02x}")
    return subjects


class CalmBoxTest(unittest.TestCase):
    def test_normal_notifications_only_are_silent(self) -> None:
        """25 notifications GitLab sans anomalie → 1 ligne bilan, pas de liste."""
        convs = [conversation([item("GitLab <gitlab@infomaniak.com>", subject, action="move", uid=n)])
                 for n, subject in enumerate(gitlab_subjects(25))]
        text = digest_v5.render_digest_v5(built_of(convs, auto_eligible=25), config())
        self.assertNotIn("Automatiques", text)
        self.assertNotIn("Failed", text)
        self.assertIn("Aucune action humaine identifiée · 25/25 couverts par le tri automatique", text)
        self.assertLessEqual(len(text.splitlines()), 4)
        self.assertIn(MARKER, text)

    def test_failures_counter_visible_with_capped_examples(self) -> None:
        """25 GitLab dont 3 échecs → compteur d'échec visible, max 2 exemples."""
        subjects = gitlab_subjects(25, failures=3)
        convs = [conversation([item("GitLab <gitlab@infomaniak.com>", s, action="move", uid=n)])
                 for n, s in enumerate(subjects)]
        text = digest_v5.render_digest_v5(built_of(convs, auto_eligible=25), config())
        self.assertIn("Automatiques", text)
        self.assertIn("3 échecs", text)
        self.assertEqual(text.count("↳"), 1)  # 3 échecs → 2 exemples max, 1 ligne
        self.assertNotIn("3 pipelines en échec", text)  # jamais un état courant affirmé

    def test_failure_wording_is_event_not_state(self) -> None:
        subjects = gitlab_subjects(4, failures=1)
        convs = [conversation([item("GitLab <gitlab@infomaniak.com>", s, action="move", uid=n)])
                 for n, s in enumerate(subjects)]
        text = digest_v5.render_digest_v5(built_of(convs), config())
        self.assertIn("1 échec", text)
        self.assertNotIn("1 échec de pipeline en cours", text)


class HierarchyTest(unittest.TestCase):
    def test_client_rises_above_thirty_gitlab_notifications(self) -> None:
        subjects = gitlab_subjects(30, failures=2)
        convs = [conversation([item("GitLab <gitlab@infomaniak.com>", s, action="move", uid=n)])
                 for n, s in enumerate(subjects)]
        client_conv = conversation([item("Marie Client <marie@clientcorp.ch>",
                                         "Validation du devis avant vendredi", uid=999)])
        text = digest_v5.render_digest_v5(built_of([client_conv] + convs), config())
        self.assertIn("À lire (1)", text)
        self.assertLess(text.index("À lire"), text.index("Automatiques"))
        self.assertIn("Validation du devis", text)

    def test_hr_email_is_review_not_action(self) -> None:
        conv = conversation([item("Service RH <rh@company.com>", "Mise à jour du règlement", uid=1)])
        text = digest_v5.render_digest_v5(built_of([conv]), config())
        self.assertIn("À lire (1)", text)
        self.assertNotIn("À traiter", text)

    def test_vip_without_action_keyword_is_review(self) -> None:
        conv = conversation([item("PDG <boss@company.com>", "Point hebdomadaire", uid=1)])
        text = digest_v5.render_digest_v5(built_of([conv]), config())
        self.assertIn("À lire (1)", text)
        self.assertNotIn("À traiter", text)

    def test_explicit_action_pattern_is_required(self) -> None:
        conv = conversation([item("Compta <compta@clientcorp.ch>",
                                  "Facture à régler — acompte novembre", uid=1)])
        text = digest_v5.render_digest_v5(built_of([conv]), config())
        self.assertIn("À traiter (1)", text)

    def test_proposed_message_is_required(self) -> None:
        conv = conversation([item("Inconnu <x@y.z>", "Nouveau dossier", uid=1, mode="propose")])
        text = digest_v5.render_digest_v5(built_of([conv]), config())
        self.assertIn("À traiter (1)", text)

    def test_automated_unknown_sender_never_joins_a_known_source(self) -> None:
        convs = [conversation([item("GitLab <gitlab@infomaniak.com>", s, action="move", uid=n)])
                 for n, s in enumerate(gitlab_subjects(3, failures=2))]
        alien = conversation([item("CI <ci@unknown.io>", "Build broken", action="move", uid=9)])
        text = digest_v5.render_digest_v5(built_of([alien] + convs), config())
        self.assertIn("gitlab", text)  # source canonique avec échecs, sans icône
        self.assertIn("ci@unknown.io", text)     # automate inconnu sous sa propre adresse
        self.assertNotIn("ci@unknown.io — .* échec", text)


class BudgetTest(unittest.TestCase):
    def test_human_budget_with_hidden_count(self) -> None:
        convs = [conversation([item(f"Client {n} <c{n}@clientcorp.ch>",
                                    f"Retour prestation {n}", uid=n)])
                 for n in range(10)]
        text = digest_v5.render_digest_v5(built_of(convs), config())
        self.assertIn("À lire (10)", text)
        self.assertIn("+ 6 autre(s)", text)
        self.assertEqual(text.count("- **"), 4)

    def test_automated_sources_budget(self) -> None:
        convs = []
        convs += [conversation([item("GitLab <gitlab@infomaniak.com>",
                                     "agent | Failed pipeline for main | sha0", uid=0)])]
        convs += [conversation([item(f"bot{n}@svc.io", f"Tâche planifiée {n} terminée",
                                     action="move", uid=n + 1)])
                  for n in range(5)]
        text = digest_v5.render_digest_v5(built_of(convs), config())
        self.assertIn("gitlab", text)
        self.assertIn("+ 3 autre(s) source(s)", text)


class ConservationAndDeterminismTest(unittest.TestCase):
    def test_counter_conservation(self) -> None:
        """N messages = N humains + N automatisés canoniques + N non classés."""
        convs = [conversation([item("GitLab <gitlab@infomaniak.com>", s, action="move", uid=n)])
                 for n, s in enumerate(gitlab_subjects(4))]
        human = conversation([item("Marie <m@clientcorp.ch>", "Bonjour", uid=50)])
        moved = conversation([item("bot@unknown.io", "Rapport quotidien", action="move", uid=60)])
        built = built_of(convs + [human, moved])
        cfg = digest_v5.load_config(config())
        categories = digest_v5._budget(built, cfg)["categories"]
        total = sum(categories.values())
        self.assertEqual(total, built["counters"]["unique_messages"])

    def test_same_snapshot_renders_byte_identical_output(self) -> None:
        subjects = gitlab_subjects(6, failures=1)
        convs = [conversation([item("GitLab <gitlab@infomaniak.com>", s, action="move", uid=n)])
                 for n, s in enumerate(subjects)]
        client = conversation([item("Marie <marie@clientcorp.ch>", "Devis", uid=99)])
        built = built_of(convs + [client])
        cfg = config()
        self.assertEqual(digest_v5.render_digest_v5(built, cfg),
                         digest_v5.render_digest_v5(built, cfg))

    def test_malicious_subject_is_neutralized(self) -> None:
        evil = "Sujet **[grave]** `code` *x* mail-triage-digest:FAUX"
        conv = conversation([item("X <x@clientcorp.ch>", evil, uid=1)])
        text = digest_v5.render_digest_v5(built_of([conv]), config())
        self.assertIn("marqueur-neutralisé:FAUX", text)
        self.assertNotIn("mail-triage-digest:FAUX", text)
        self.assertNotIn("**[grave]**", text)

    def test_long_subject_is_truncated(self) -> None:
        conv = conversation([item("X <x@clientcorp.ch>", "a" * 200, uid=1)])
        text = digest_v5.render_digest_v5(built_of([conv]), config())
        subject_line = [l for l in text.splitlines() if "aaa" in l][0]
        self.assertLessEqual(len(subject_line), 120)

    def test_marker_is_always_present(self) -> None:
        conv = conversation([item("A <a@b.c>", "Sujet", uid=1)])
        text = digest_v5.render_digest_v5(built_of([conv]), config())
        self.assertTrue(text.rstrip().endswith(MARKER))


class BacklogTest(unittest.TestCase):
    """Rattrapage = non lus plus anciens que la fenêtre, JAMAIS digestés
    (parité V4 « Encore non lus »). Le filtre seen/fenêtre/cap est fait par
    build_digest en amont : V5 rend le backlog fourni dans le built."""

    def _built_with_backlog(self, backlog_items) -> dict:
        built = built_of([])
        built["always_inbox"] = backlog_items
        return built

    def test_unread_human_backlog_is_listed(self) -> None:
        old = item("Marie <marie@clientcorp.ch>", "Devis 2027 à valider", uid=90)
        old["seen"] = False
        text = digest_v5.render_digest_v5(self._built_with_backlog([old]), config())
        self.assertIn("À lire — rattrapage (1)", text)
        self.assertIn("Devis 2027", text)

    def test_automated_backlog_is_silent_but_counted(self) -> None:
        old_items = [item("GitLab <gitlab@infomaniak.com>",
                          f"agent | Pipeline has passed | sha{n:02x}", action="move", uid=90 + n)
                     for n in range(3)]
        for it in old_items:
            it["seen"] = False
        text = digest_v5.render_digest_v5(self._built_with_backlog(old_items), config())
        self.assertNotIn("rattrapage", text)
        self.assertNotIn("Pipeline has passed", text)
        self.assertIn("3 notifications automatiques plus anciennes non lues", text)

    def test_backlog_budget_with_hidden_count(self) -> None:
        old_items = [item(f"Client {n} <c{n}@clientcorp.ch>", f"Retour {n}", uid=90 + n)
                     for n in range(6)]
        for it in old_items:
            it["seen"] = False
        text = digest_v5.render_digest_v5(self._built_with_backlog(old_items), config())
        self.assertIn("rattrapage (6)", text)
        self.assertIn("+ 2 autre(s)", text)

    def test_human_backlog_rises_in_review_not_required(self) -> None:
        """Un backlog humain sans signal d'action = lecture, pas fausse tâche."""
        old = item("PDG <boss@company.com>", "Ancien compte rendu", uid=90)
        old["seen"] = False
        text = digest_v5.render_digest_v5(self._built_with_backlog([old]), config())
        self.assertIn("rattrapage (1)", text)
        self.assertNotIn("À traiter", text)


class ConfigValidationTest(unittest.TestCase):
    def test_defaults_without_block(self) -> None:
        cfg = digest_v5.load_config({})
        self.assertEqual(cfg["max_human_items"], 4)
        self.assertEqual(cfg["automation_sources"], [])

    def test_invalid_regex_is_refused(self) -> None:
        with self.assertRaisesRegex(digest_v5.DigestV5Error, "regex"):
            digest_v5.load_config({"digest_v5": {"action_patterns": [{"id": "x", "pattern": "("}]}})

    def test_unknown_key_is_refused(self) -> None:
        with self.assertRaisesRegex(digest_v5.DigestV5Error, "inconnues"):
            digest_v5.load_config({"digest_v5": {"score_vip": 30}})

    def test_budget_out_of_bounds_is_refused(self) -> None:
        with self.assertRaisesRegex(digest_v5.DigestV5Error, "hors bornes"):
            digest_v5.load_config({"digest_v5": {"max_human_items": 50}})


if __name__ == "__main__":
    unittest.main()
