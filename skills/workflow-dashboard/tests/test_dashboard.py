"""Tests du Terminal Dashboard (J2 — renderer lecture-seule)."""

import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import wd_core  # noqa: E402
import wd_dashboard as dash  # noqa: E402
import wd_taskworkflow as twa  # noqa: E402

NOW = datetime.datetime(2026, 10, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)
RECENT = (NOW - datetime.timedelta(hours=2)).isoformat()
OLD = (NOW - datetime.timedelta(days=10)).isoformat()


def make_topic(title="Sujet de test", status=None, source="orchestrator-cli",
               session_id=None, updated=RECENT, steps=None, topic_id=None):
    if steps is None:
        steps = [
            {"id": "a", "label": "Un", "status": "DONE", "updatedAt": updated},
            {"id": "b", "label": "Deux", "status": status or "RUNNING",
             "updatedAt": updated},
        ]
    topic = {
        "schemaVersion": 1,
        "topicId": topic_id or "11111111-1111-4111-8111-111111111111",
        "title": title,
        "kind": "plan",
        "source": source,
        "scope": "global",
        "steps": steps,
        "createdAt": OLD,
        "updatedAt": updated,
        "revision": 3,
    }
    if session_id:
        topic["sessionId"] = session_id
    wd_core.validate_topic(topic)
    return topic


class DashTestCase(unittest.TestCase):
    """Isolation des deux sources (store + adaptateur)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {
            wd_core.ENV_PROGRESS_DIR: os.path.join(self._tmp.name, "progress"),
            twa.ENV_STATE_DIR: os.path.join(self._tmp.name, "tw"),
        })
        patcher.start()
        self._patcher = patcher

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def publish(self, **kwargs):
        # fixture : écrit le JSON du store directement (setup de test légitime ;
        # en production, l'écriture passe exclusivement par wd_publish.py)
        import uuid
        payload = make_topic(**kwargs)
        payload["topicId"] = str(uuid.uuid4())
        wd_core.validate_topic(payload)
        global_dir = os.path.join(os.environ[wd_core.ENV_PROGRESS_DIR], "global")
        os.makedirs(global_dir, exist_ok=True)
        path = os.path.join(global_dir, f"{payload['topicId']}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        return payload


class TestCategorize(unittest.TestCase):
    def test_running_or_pending_go_running(self):
        self.assertEqual(dash.categorize(make_topic(status="RUNNING")), "running")
        self.assertEqual(dash.categorize(make_topic(status="PENDING")), "running")

    def test_blocked_and_failed_go_action(self):
        self.assertEqual(dash.categorize(make_topic(status="BLOCKED")), "action")
        self.assertEqual(dash.categorize(make_topic(status="FAILED")), "action")

    def test_done_and_skipped_go_done(self):
        self.assertEqual(dash.categorize(make_topic(status="DONE")), "done")
        self.assertEqual(dash.categorize(make_topic(status="SKIPPED")), "done")


class TestAgeLabel(unittest.TestCase):
    def test_units(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.assertEqual(dash.age_label((now - datetime.timedelta(seconds=30)).isoformat(), now),
                         "à l'instant")
        self.assertEqual(dash.age_label((now - datetime.timedelta(minutes=5)).isoformat(), now), "5m")
        self.assertEqual(dash.age_label((now - datetime.timedelta(hours=3)).isoformat(), now), "3h")
        self.assertEqual(dash.age_label((now - datetime.timedelta(days=2)).isoformat(), now), "2j")

    def test_invalid_timestamp_returns_none(self):
        self.assertIsNone(dash.age_label("not-a-date", NOW))


class TestRender(DashTestCase):
    def test_empty_state_message(self):
        frame = dash.render(now=NOW)
        self.assertIn("Aucun suivi en cours", frame)

    def test_native_taskworkflow_topics_appear(self):
        # review J1 warning : les natifs ne sont JAMAIS dans le store
        tw_dir = os.path.join(self._tmp.name, "tw")
        os.makedirs(tw_dir)
        state = {
            "schemaVersion": 1, "workflowId": "tw-demo--dash0001",
            "taskUrls": [], "repository": "demo/repo",
            "baseBranch": "develop", "baseCommit": "a" * 40,
            "featureBranch": "feat/demo--dash",
            "worktreePath": "/tmp/wt-dash", "currentPhase": 2,
            "phaseStatuses": {"1": {"status": "PASSED", "at": RECENT},
                              "2": {"status": "RUNNING", "at": RECENT}},
            "createdAt": OLD, "updatedAt": RECENT,
            "plan": {"objective": "Objectif natif dashboard"},
        }
        with open(os.path.join(tw_dir, f"{state['workflowId']}.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(state, handle)
        frame = dash.render(now=NOW)
        self.assertIn("Objectif natif dashboard", frame)
        self.assertIn("[task-workflow]", frame)
        self.assertIn("EN COURS", frame)

    def test_categories_headers_and_archived_counter(self):
        self.publish(title="En cours", status="RUNNING", updated=RECENT)
        self.publish(title="Bloqué", status="BLOCKED", updated=RECENT)
        done_steps = [{"id": "a", "label": "Un", "status": "DONE",
                       "updatedAt": RECENT},
                      {"id": "b", "label": "Deux", "status": "DONE",
                       "updatedAt": RECENT}]
        self.publish(title="Terminé récent", steps=done_steps, updated=RECENT)
        self.publish(title="Terminé ancien", steps=done_steps, updated=OLD)
        frame = dash.render(now=NOW)
        self.assertIn("EN COURS", frame)
        self.assertIn("NÉCESSITE UNE ACTION", frame)
        self.assertIn("TERMINÉS RÉCEMMENT", frame)
        self.assertIn("En cours", frame)
        self.assertIn("Bloqué", frame)
        self.assertIn("Terminé récent", frame)
        self.assertNotIn("Terminé ancien\n", frame)  # archivé (jamais supprimé)
        self.assertIn("+ 1 sujet(s) terminé(s) antérieur(s)", frame)

    def test_source_always_displayed(self):
        self.publish(title="Sujet relais", source="todowrite-relay",
                     status="RUNNING")
        frame = dash.render(now=NOW)
        self.assertIn("[todowrite-relay]", frame)

    def test_age_indicator_displayed(self):
        self.publish(title="Vieux sujet", status="RUNNING",
                     updated=(NOW - datetime.timedelta(hours=5)).isoformat())
        frame = dash.render(now=NOW)
        self.assertIn("· 5h", frame)  # indicateur, pas une garantie

    def test_session_current_topic_sorted_first(self):
        # review J2 #2 : la priorité session doit battre la récence —
        # le sujet de la session courante est ici le PLUS VIEUX
        self.publish(title="Autre session", status="RUNNING",
                     session_id="ses-other", updated=RECENT)
        older = (NOW - datetime.timedelta(hours=5)).isoformat()
        self.publish(title="Ma session", status="RUNNING",
                     session_id="ses-mine", updated=older)
        frame = dash.render(now=NOW, session_id="ses-mine")
        running = frame.split("EN COURS", 1)[1]
        self.assertLess(running.index("Ma session"), running.index("Autre session"))

        # sans sessionId : aucun sujet priorisé, tri par récence seule
        frame = dash.render(now=NOW)
        running = frame.split("EN COURS", 1)[1]
        self.assertLess(running.index("Autre session"), running.index("Ma session"))

    def test_progress_bar_and_counts(self):
        self.publish(title="Sujet ratio", status="RUNNING")
        frame = dash.render(now=NOW, width=200)
        self.assertIn("▓", frame)
        self.assertIn("1/2", frame)

    def test_verbose_shows_steps(self):
        self.publish(title="Sujet verbose", status="RUNNING")
        frame = dash.render(now=NOW, verbose=True)
        self.assertIn("Un", frame)
        self.assertIn("Deux", frame)

    def test_line_width_respected(self):
        long_title = "Titre " + "très long " * 30
        self.publish(title=long_title, status="RUNNING",
                     updated=(NOW - datetime.timedelta(minutes=3)).isoformat())
        for width in (80, 40):
            frame = dash.render(now=NOW, width=width)
            self.assertIn("…", frame)  # troncature active
            for line in frame.splitlines():
                # couleurs désactivées ici : len(line) = largeur visuelle
                self.assertLessEqual(len(line), width,
                                     f"line exceeds width {width}: {line!r}")

    def test_naive_timestamp_does_not_crash(self):
        # review J2 #1 : timestamp naïf = valide au contrat, jamais de TypeError
        self.publish(title="Sujet naïf", status="RUNNING",
                     updated="2026-10-21T11:30:00")  # sans fuseau
        frame = dash.render(now=NOW)  # ne lève pas
        self.assertIn("Sujet naïf", frame)

    def test_corrupted_sources_are_signaled(self):
        # review J2 #5 : rien ne disparaît sans signal
        progress_root = os.environ[wd_core.ENV_PROGRESS_DIR]
        global_dir = os.path.join(progress_root, "global")
        os.makedirs(global_dir, exist_ok=True)
        with open(os.path.join(global_dir, "11111111-1111-4111-8111-999999999999.json"),
                  "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.publish(title="Sujet sain", status="RUNNING")
        frame = dash.render(now=NOW)
        self.assertIn("Sujet sain", frame)
        self.assertIn("1 source(s) illisible(s)/ignorée(s)", frame)

    def test_topic_without_steps_renders_running(self):
        self.publish(title="Sujet vide", steps=[], updated=RECENT)
        frame = dash.render(now=NOW, width=200)
        self.assertIn("Sujet vide", frame)
        self.assertIn("EN COURS", frame)
        self.assertIn("0/0", frame)

    def test_future_timestamp_clamped(self):
        self.publish(title="Sujet du futur", status="RUNNING",
                     updated=(NOW + datetime.timedelta(hours=2)).isoformat())
        frame = dash.render(now=NOW)
        self.assertIn("à l'instant", frame)  # clampé, jamais négatif

    def test_verbose_respects_width(self):
        # review J2 #4 : les steps ne débordent plus à width standard
        steps = [{"id": "a", "label": "Étape " + "longue " * 20,
                  "status": "RUNNING",
                  "detail": "Détail " + "explicatif " * 10}]
        self.publish(title="Sujet verbose", steps=steps, status="RUNNING")
        frame = dash.render(now=NOW, verbose=True, width=80)
        for line in frame.splitlines():
            self.assertLessEqual(len(line), 80)
        self.assertIn("Étape", frame)

    def test_no_write_side_effects(self):
        # invariant : le renderer n'écrit JAMAIS (aucun fichier ni mtime modifié,
        # sur les DEUX racines — review J2 hygiène)
        self.publish(title="Sujet", status="RUNNING")

        def snapshot():
            state = {}
            for base in (os.environ[wd_core.ENV_PROGRESS_DIR],
                         os.environ[twa.ENV_STATE_DIR]):
                for root, _dirs, files in os.walk(base):
                    for name in files:
                        path = os.path.join(root, name)
                        rel = os.path.relpath(path, base)
                        stat = os.stat(path)
                        state[(base, rel)] = (stat.st_mtime_ns, stat.st_size)
            return state

        before = snapshot()
        dash.render(now=NOW)
        self.assertEqual(snapshot(), before)


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patcher = mock.patch.dict(os.environ, {
            wd_core.ENV_PROGRESS_DIR: os.path.join(self._tmp.name, "progress"),
            twa.ENV_STATE_DIR: os.path.join(self._tmp.name, "tw"),
        })
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_main_single_frame_exit_0(self):
        stdout = __import__("io").StringIO()
        with mock.patch("sys.stdout", stdout):
            code = dash.main([])
        self.assertEqual(code, 0)
        self.assertIn("Aucun suivi en cours", stdout.getvalue())

    def test_main_watch_stops_on_keyboard_interrupt(self):
        calls = {"n": 0}

        def fake_sleep(_seconds):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise KeyboardInterrupt

        stdout = __import__("io").StringIO()
        with mock.patch("sys.stdout", stdout), \
             mock.patch("time.sleep", side_effect=fake_sleep), \
             mock.patch.object(dash, "_clear", lambda: None):
            code = dash.main(["--watch", "0.2"])
        self.assertEqual(code, 0)
        self.assertGreaterEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
