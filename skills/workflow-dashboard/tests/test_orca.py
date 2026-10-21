"""Tests de l'intégration Orca (J3) — idempotence, isolation, persistance.

Le CLI orca est mocké (_run) : aucun pane réel n'est créé dans les tests —
le pane réel est validé par les critères E2E (J3 final)."""

import json
import os
import shlex
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import wd_orca  # noqa: E402


class OrcaTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patcher = mock.patch.dict(os.environ, {
            wd_orca.ENV_PANES_STATE: os.path.join(self._tmp.name, "panes.json"),
            "ORCA_WORKTREE_ID": "wt-test-1234",  # session hébergée simulée
            # neutralisé : les tests passent par la voie fallback (terminal
            # list) — la priorité ORCA_TERMINAL_HANDLE a son test dédié
            "ORCA_TERMINAL_HANDLE": "",
        })
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()


class TestPaneState(OrcaTestCase):
    def test_read_missing_state_is_empty(self):
        self.assertEqual(wd_orca.read_panes_state(), {})

    def test_read_corrupt_state_is_empty(self):
        path = wd_orca.panes_state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.assertEqual(wd_orca.read_panes_state(), {})

    def test_write_state_atomic_roundtrip(self):
        state = {"panes": {"/tmp/wt": {"handle": "term-1"}}}
        wd_orca.write_panes_state(state)
        self.assertEqual(wd_orca.read_panes_state(), state)
        state_dir = os.path.dirname(wd_orca.panes_state_path())
        leftovers = [f for f in os.listdir(state_dir)
                     if f.startswith(".wd-orca-")]
        self.assertEqual(leftovers, [])  # tmp nettoyé


class TestPaneKey(OrcaTestCase):
    def test_realpath_isolation(self):
        self.assertEqual(wd_orca.pane_key("/tmp/wt-a"), os.path.realpath("/tmp/wt-a"))
        self.assertNotEqual(wd_orca.pane_key("/tmp/wt-a"), wd_orca.pane_key("/tmp/wt-b"))
        self.assertEqual(wd_orca.pane_key(None), "global")


class TestEnsure(OrcaTestCase):
    def _fake_run(self, calls):
        created = {"n": 0}

        def fake_run(args, timeout=wd_orca.DEFAULT_TIMEOUT):
            calls.append(args)
            if args[:1] == ["status"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"runtimeReachable": True}}), "rc": 0, "why": None}
            if args[:2] == ["terminal", "list"]:
                # shell-1 est le plus récent MAIS pas opencode : le filtre
                # agentIdentity doit l'écarter (jamais splitter un shell)
                return {"ok": True, "stdout": json.dumps({
                    "result": {"terminals": [
                        {"handle": "host-demo", "agentIdentity": "opencode",
                         "worktreePath": "/tmp/wt-demo", "lastOutputAt": 10},
                        {"handle": "host-other", "agentIdentity": "opencode",
                         "worktreePath": "/tmp/wt-other", "lastOutputAt": 20},
                        {"handle": "shell-1", "agentIdentity": None,
                         "worktreePath": "/tmp/wt-demo", "lastOutputAt": 30},
                    ]}}), "rc": 0, "why": None}
            if args[:2] == ["terminal", "split"]:
                created["n"] += 1  # un vrai orca rend un handle unique par pane
                return {"ok": True, "stdout": json.dumps({
                    "result": {"split": {"handle": f"term-{created['n']}",
                                         "tabId": "tab-1"}}}),
                    "rc": 0, "why": None}
            if args[:2] == ["terminal", "close"]:
                return {"ok": True, "stdout": "", "rc": 0, "why": None}
            return {"ok": True, "stdout": "", "rc": 0, "why": None}
        return fake_run

    def test_ensure_splits_once_then_reuses(self):
        # critère E2E : pane relançable SANS duplication — et JAMAIS un onglet
        calls: list = []
        with mock.patch.object(wd_orca, "_run", self._fake_run(calls)):
            first = wd_orca.ensure("/tmp/wt-demo")
            self.assertTrue(first["ok"])
            self.assertFalse(first["reused"])
            self.assertEqual(first["handle"], "term-1")
            splits = [c for c in calls if c[:2] == ["terminal", "split"]]
            self.assertEqual(len(splits), 1)
            # le host splitté est le terminal OpenCode du worktree (jamais
            # le shell plus récent, jamais un create d'onglet)
            self.assertEqual(splits[0][3], "host-demo")
            self.assertEqual([c for c in calls
                              if c[:2] == ["terminal", "create"]], [])
            state = wd_orca.read_panes_state()
            entry = state["panes"][os.path.realpath("/tmp/wt-demo")]
            self.assertEqual(entry["parentHandle"], "host-demo")
            # 2e appel : handle enregistré -> réutilisation, aucun split
            calls.clear()
            second = wd_orca.ensure("/tmp/wt-demo")
            self.assertTrue(second["ok"])
            self.assertTrue(second["reused"])
            self.assertEqual(second["handle"], "term-1")
            self.assertEqual([c for c in calls
                              if c[:2] == ["terminal", "split"]], [])

    def test_orca_terminal_handle_takes_priority(self):
        # ORCA_TERMINAL_HANDLE (injecté par Orca) = voie déterministe :
        # terminal list jamais consulté, split sur ce handle exact
        calls: list = []
        with mock.patch.object(wd_orca, "_run", self._fake_run(calls)), \
             mock.patch.dict(os.environ,
                             {"ORCA_TERMINAL_HANDLE": "host-explicit"}):
            res = wd_orca.ensure("/tmp/wt-demo")
        self.assertTrue(res["ok"])
        self.assertEqual([c for c in calls if c[:2] == ["terminal", "list"]], [])
        splits = [c for c in calls if c[:2] == ["terminal", "split"]]
        self.assertEqual(len(splits), 1)
        self.assertEqual(splits[0][3], "host-explicit")

    def test_ensure_two_worktrees_isolated(self):
        # critère E2E : isolation multi-worktrees sans collision
        calls: list = []
        with mock.patch.object(wd_orca, "_run", self._fake_run(calls)):
            one = wd_orca.ensure("/tmp/wt-demo")
            other = wd_orca.ensure("/tmp/wt-other")
            self.assertTrue(one["ok"] and other["ok"])
            self.assertNotEqual(one["handle"], other["handle"])
            state = wd_orca.read_panes_state()
            self.assertEqual(len(state["panes"]), 2)
            self.assertIn(os.path.realpath("/tmp/wt-demo"), state["panes"])
            self.assertIn(os.path.realpath("/tmp/wt-other"), state["panes"])

    def test_ensure_survives_state_reload(self):
        # critère E2E : reprise sans réinitialisation (persistance du handle)
        calls: list = []
        with mock.patch.object(wd_orca, "_run", self._fake_run(calls)):
            wd_orca.ensure("/tmp/wt-demo")
        # simulate un nouveau process : lecture de l'état sur disque uniquement
        self.assertIn(os.path.realpath("/tmp/wt-demo"),
                      wd_orca.read_panes_state()["panes"])

    def test_ensure_outside_orca_session_refused(self):
        # jamais de création hors Orca — skipped, pas de panne
        calls: list = []
        with mock.patch.object(wd_orca, "_run", self._fake_run(calls)), \
             mock.patch.dict(os.environ, {"ORCA_WORKTREE_ID": ""}):
            res = wd_orca.ensure("/tmp/wt-demo")
        self.assertFalse(res["ok"])
        self.assertTrue(res["skipped"])
        self.assertEqual(res["why"], "session non hébergée par Orca (ORCA_WORKTREE_ID absent)")
        self.assertEqual([c for c in calls if c[:2] == ["terminal", "split"]], [])

    def test_ensure_no_opencode_terminal_refused(self):
        calls: list = []

        def fake_run(args, timeout=wd_orca.DEFAULT_TIMEOUT):
            if args[:1] == ["status"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"runtimeReachable": True}}), "rc": 0, "why": None}
            if args[:2] == ["terminal", "list"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"terminals": [{"handle": "host-demo",
                                              "agentIdentity": "opencode",
                                              "worktreePath": "/tmp/wt-demo"}]}}),
                    "rc": 0, "why": None}
            return {"ok": True, "stdout": "", "rc": 0, "why": None}

        with mock.patch.object(wd_orca, "_run", fake_run):
            res = wd_orca.ensure("/tmp/unknown-wt")
        self.assertFalse(res["ok"])
        self.assertIn("aucun terminal OpenCode", res["why"])

    def test_ensure_watch_out_of_range_refused_before_any_create(self):
        # review J3 : refuser --watch hors plage AVANT le split orca
        calls: list = []
        with mock.patch.object(wd_orca, "_run", self._fake_run(calls)):
            res = wd_orca.ensure("/tmp/wt-demo", watch=0.1)
        self.assertFalse(res["ok"])
        self.assertTrue(res["skipped"])
        self.assertEqual([c for c in calls if c[:2] == ["terminal", "split"]], [])

    def test_ensure_runtime_unreachable_skips(self):
        # leçon tw_orca : orca --version réussit même app fermée ; le check
        # fiable = status/runtimeReachable (review J3 #2)
        calls: list = []

        def fake_run(args, timeout=wd_orca.DEFAULT_TIMEOUT):
            if args[:1] == ["status"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"runtimeReachable": False}}), "rc": 0, "why": None}
            return {"ok": True, "stdout": "", "rc": 0, "why": None}

        with mock.patch.object(wd_orca, "_run", fake_run):
            res = wd_orca.ensure("/tmp/wt-demo")
        self.assertFalse(res["ok"])
        self.assertTrue(res["skipped"])
        self.assertIn("runtime", res["why"])

    def test_panes_state_concurrent_writers_preserve_both(self):
        # review J3 HIGH : deux sessions réelles (forks) sur worktrees
        # distincts — le RMW sous FileLock fait survivre les deux handles
        import multiprocessing as mp
        root = os.environ[wd_orca.ENV_PANES_STATE]

        def _run_child(path):
            import wd_core as _wc  # noqa: F401 (fork : modules hérités)
            os.environ[wd_orca.ENV_PANES_STATE] = root

            def fake_run(args, timeout=wd_orca.DEFAULT_TIMEOUT):
                if args[:1] == ["status"]:
                    return {"ok": True, "stdout": json.dumps({
                        "result": {"runtimeReachable": True}}),
                        "rc": 0, "why": None}
                if args[:2] == ["terminal", "list"]:
                    return {"ok": True, "stdout": json.dumps({
                        "result": {"terminals": [{"handle": f"host-{path}",
                                                  "agentIdentity": "opencode",
                                                  "worktreePath": path}]}}),
                        "rc": 0, "why": None}
                if args[:2] == ["terminal", "split"]:
                    return {"ok": True, "stdout": json.dumps({
                        "result": {"split": {"handle": f"term-{path}",
                                             "tabId": "t"}}}),
                        "rc": 0, "why": None}
                return {"ok": True, "stdout": "", "rc": 0, "why": None}

            with mock.patch.object(wd_orca, "_run", fake_run):
                res = wd_orca.ensure(path)
                assert res["ok"], res

        ctx = mp.get_context("fork")
        procs = [ctx.Process(target=_run_child, args=(f"/tmp/wt-{i}",))
                 for i in range(2)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=60)
            self.assertEqual(proc.exitcode, 0)
        state = wd_orca.read_panes_state()
        self.assertEqual(len(state["panes"]), 2)  # aucun handle perdu

    def test_close_failed_keeps_handle(self):
        # review J3 : close échoué => l'entrée reste (jamais d'orphelin muet)
        calls: list = []

        def fake_run(args, timeout=wd_orca.DEFAULT_TIMEOUT):
            if args[:1] == ["status"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"runtimeReachable": True}}), "rc": 0, "why": None}
            if args[:2] == ["terminal", "list"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"terminals": [{"handle": "host-demo",
                                              "agentIdentity": "opencode",
                                              "worktreePath": "/tmp/wt-demo"}]}}),
                    "rc": 0, "why": None}
            if args[:2] == ["terminal", "split"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"split": {"handle": "term-1",
                                         "tabId": "t"}}}),
                    "rc": 0, "why": None}
            if args[:2] == ["terminal", "close"]:
                return {"ok": False, "stdout": "", "rc": 1, "why": "timeout"}
            return {"ok": True, "stdout": "", "rc": 0, "why": None}

        with mock.patch.object(wd_orca, "_run", fake_run):
            wd_orca.ensure("/tmp/wt-demo")
            res = wd_orca.close("/tmp/wt-demo")
        self.assertFalse(res["ok"])
        state = wd_orca.read_panes_state()
        self.assertIn(os.path.realpath("/tmp/wt-demo"), state["panes"])

    def test_force_without_existing_pane_splits_without_close(self):
        calls: list = []
        with mock.patch.object(wd_orca, "_run", self._fake_run(calls)):
            res = wd_orca.ensure("/tmp/wt-demo", force=True)
        self.assertTrue(res["ok"])
        self.assertFalse(res["reused"])
        self.assertEqual([c for c in calls if c[:2] == ["terminal", "close"]], [])
        self.assertEqual(len([c for c in calls if c[:2] == ["terminal", "split"]]), 1)

    def test_ensure_without_handle_is_uncertain_and_unrecorded(self):
        # sagesse tw_orca : handle manquant = jamais un succès enregistré
        def fake_run(args, timeout=wd_orca.DEFAULT_TIMEOUT):
            if args[:1] == ["status"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"runtimeReachable": True}}), "rc": 0, "why": None}
            if args[:2] == ["terminal", "list"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"terminals": [{"handle": "host-demo",
                                              "agentIdentity": "opencode",
                                              "worktreePath": "/tmp/wt-demo"}]}}),
                    "rc": 0, "why": None}
            if args[:2] == ["terminal", "split"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"split": {}}}), "rc": 0, "why": None}
            return {"ok": True, "stdout": "", "rc": 0, "why": None}

        with mock.patch.object(wd_orca, "_run", fake_run):
            res = wd_orca.ensure("/tmp/wt-demo")
        self.assertFalse(res["ok"])
        self.assertTrue(res["uncertain"])
        self.assertEqual(wd_orca.read_panes_state(), {})  # rien d'enregistré

    def test_force_restart_closes_then_recreates(self):
        calls: list = []
        with mock.patch.object(wd_orca, "_run", self._fake_run(calls)):
            wd_orca.ensure("/tmp/wt-demo")
            calls.clear()
            res = wd_orca.ensure("/tmp/wt-demo", force=True)
            self.assertTrue(res["ok"])
            self.assertFalse(res["reused"])
            closes = [c for c in calls if c[:2] == ["terminal", "close"]]
            splits = [c for c in calls if c[:2] == ["terminal", "split"]]
            self.assertEqual(len(closes), 1)
            self.assertEqual(len(splits), 1)

    def test_renderer_command_is_absolute_and_quoted(self):
        command = wd_orca.renderer_command(watch=0.5, session_id="ses-1")
        self.assertIn("wd_dashboard.py", command)
        self.assertIn("--watch", command)
        self.assertIn("0.5", command)
        self.assertIn("--session-id", command)
        first = shlex.split(command)[0]  # review J3 : shlex.split gère les espaces
        self.assertTrue(os.path.isabs(first))
        self.assertIn("python", os.path.basename(first))


class TestClose(OrcaTestCase):
    def test_close_removes_state(self):
        calls: list = []

        def fake_run(args, timeout=wd_orca.DEFAULT_TIMEOUT):
            if args[:1] == ["status"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"runtimeReachable": True}}), "rc": 0, "why": None}
            if args[:2] == ["terminal", "list"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"terminals": [{"handle": "host-demo",
                                              "agentIdentity": "opencode",
                                              "worktreePath": "/tmp/wt-demo"}]}}),
                    "rc": 0, "why": None}
            if args[:2] == ["terminal", "split"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"split": {"handle": "term-1"}}}),
                    "rc": 0, "why": None}
            return {"ok": True, "stdout": "", "rc": 0, "why": None}

        with mock.patch.object(wd_orca, "_run", fake_run):
            wd_orca.ensure("/tmp/wt-demo")
            res = wd_orca.close("/tmp/wt-demo")
        self.assertTrue(res["ok"])
        self.assertEqual(wd_orca.read_panes_state(), {"panes": {}})

    def test_close_without_pane_is_ok_noop(self):
        res = wd_orca.close("/tmp/never-created")
        self.assertTrue(res["ok"])


class TestRendererCommandContract(unittest.TestCase):
    def test_renderer_never_imports_orca_writes(self):
        # invariant : le renderer reste un lecteur strict — wd_orca est le
        # seul module d'écriture d'état de gestion des panes (l'invariant
        # porte sur les IMPORTS et les appels, pas les commentaires)
        import wd_dashboard  # noqa: F401
        source = open(os.path.join(PARENT, "wd_dashboard.py"),
                      encoding="utf-8").read()
        self.assertNotIn("import wd_orca", source)  # pas de dépendance inverse
        self.assertNotIn("write_panes_state", source)
        self.assertNotIn("close_terminal", source)


class TestCliE2E(OrcaTestCase):
    def test_cli_ensure_json_guaranteed(self):
        # review J3 : le CLI sort toujours du JSON parsable + exit code cohérent,
        # et le why porte le message orca (_why_from_output, pas juste "rc 1")
        import contextlib
        import io
        stdout = io.StringIO()

        def fake_run(args, timeout=wd_orca.DEFAULT_TIMEOUT):
            if args[:1] == ["status"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"runtimeReachable": True}}), "rc": 0, "why": None}
            if args[:2] == ["terminal", "list"]:
                return {"ok": True, "stdout": json.dumps({
                    "result": {"terminals": [{"handle": "host-x",
                                              "agentIdentity": "opencode",
                                              "worktreePath": "/tmp/wt-x"}]}}),
                    "rc": 0, "why": None}
            return {"ok": False, "rc": 1,
                    "stdout": json.dumps({"error": "app closed mid-create"}),
                    "why": "orca terminal split failed: app closed mid-create"}

        with mock.patch.object(wd_orca, "_run", fake_run):
            with mock.patch("sys.stdout", stdout), \
                 contextlib.redirect_stderr(io.StringIO()):
                code = wd_orca.main(["ensure", "--worktree-path", "/tmp/wt-x"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())  # parsable, jamais un traceback
        self.assertFalse(payload["ok"])
        self.assertIn("app closed mid-create", payload["why"])

    def test_cli_status_ok(self):
        import contextlib
        import io
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            code = wd_orca.main(["status"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["panes"], {})


if __name__ == "__main__":
    unittest.main()
