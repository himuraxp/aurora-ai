"""tw_orca adapter — fake-Orca driven tests (stdlib only, no mock library).

The fake CLI (tests/fixtures/fake_orca.sh) emulates the real commands
verified live on Orca 1.4.224: status, worktree list (--json), terminal
create (--json, --focus), terminal close. Contract under test: every entry
point returns {"ok": ...} and never raises — Orca is an enhancement, the
workflow must degrade to its historical behaviour.
"""

import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tw_orca  # noqa: E402
import tw_state  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

WORKTREE_PATH = "/tmp/repo.worktrees/feat-trello-abc--do-something"
WT_JSON = json.dumps({"result": {"worktrees": [
    {"id": "repo-1::/tmp/repo", "path": "/tmp/repo", "branch": "develop"},
    {"id": "repo-1::" + WORKTREE_PATH, "path": WORKTREE_PATH,
     "branch": "feat/trello-abc--do-something"},
]}})


class OrcaEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fake = os.path.join(self.tmp, "fake_orca")
        with open(fake, "w", encoding="utf-8") as handle:
            with open(os.path.join(FIXTURES, "fake_orca.sh"), "r", encoding="utf-8") as source:
                handle.write(source.read())
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        self.env_patch = {"TW_ORCA_BIN": fake, "TW_FAKE_DIR": self.tmp}
        self._old = {key: os.environ.get(key) for key in self.env_patch}
        os.environ.update(self.env_patch)
        importlib.reload(tw_orca)

    def tearDown(self):
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(tw_orca)

    def args_log(self):
        path = os.path.join(self.tmp, "args.log")
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            return [line.strip() for line in handle]


class TestRuntimeReady(OrcaEnv):
    def test_ready(self):
        self.assertEqual(tw_orca.runtime_ready(), {"ok": True, "why": None})

    def test_runtime_down_is_ok_false_never_raises(self):
        open(os.path.join(self.tmp, "runtime-down"), "w").close()
        result = tw_orca.runtime_ready()
        self.assertFalse(result["ok"])
        self.assertIn("not reachable", result["why"])

    def test_missing_binary_degrades(self):
        os.environ["TW_ORCA_BIN"] = "/nonexistent/orca-bin"
        importlib.reload(tw_orca)
        result = tw_orca.runtime_ready()
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["why"])

    def test_timeout_degrades(self):
        with tempfile.TemporaryDirectory() as other:
            fake = os.path.join(other, "fake_orca")
            with open(os.path.join(FIXTURES, "fake_orca.sh")) as source, \
                    open(fake, "w") as sink:
                sink.write(source.read())
            os.chmod(fake, 0o755)
            os.environ["TW_ORCA_BIN"] = fake
            os.environ["TW_FAKE_DIR"] = other
            importlib.reload(tw_orca)
            result = tw_orca._run(["slow", "status"], timeout=1)
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["why"])


class TestWorktreeSelector(OrcaEnv):
    def test_finds_new_worktree_worktree_by_path(self):
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        result = tw_orca.find_worktree_selector(WORKTREE_PATH)
        self.assertTrue(result["ok"])
        self.assertEqual(result["selector"], "repo-1::" + WORKTREE_PATH)

    def test_normalizes_trailing_slash(self):
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        result = tw_orca.find_worktree_selector(WORKTREE_PATH + "/")
        self.assertTrue(result["ok"])

    def test_unknown_path_reports_why(self):
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        result = tw_orca.find_worktree_selector("/tmp/repo.worktrees/other--task")
        self.assertFalse(result["ok"])
        self.assertIn("not indexed", result["why"])

    def test_unparsable_output_degrades(self):
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write("not json at all")
        result = tw_orca.find_worktree_selector(WORKTREE_PATH)
        self.assertFalse(result["ok"])
        self.assertIn("unparsable", result["why"])


class TestHandoffTerminal(OrcaEnv):
    def test_create_returns_handle_and_passes_focus(self):
        result = tw_orca.create_handoff_terminal("repo-1::/tmp/wt", "feat/x", "opencode --prompt hi")
        self.assertTrue(result["ok"])
        self.assertEqual(result["handle"], "term_fake_1")
        self.assertEqual(result["paneKey"], "tab1:pane1")
        self.assertIn("--focus", self.args_log()[-1])

    def test_create_without_focus_omits_flag(self):
        tw_orca.create_handoff_terminal("repo-1::/tmp/wt", "feat/x", "true", focus=False)
        self.assertNotIn("--focus", self.args_log()[-1])

    def test_create_without_handle_is_uncertain_never_success(self):
        open(os.path.join(self.tmp, "uncertain-create"), "w").close()
        result = tw_orca.create_handoff_terminal("repo-1::/tmp/wt", "feat/x", "true")
        self.assertFalse(result["ok"])
        self.assertTrue(result["uncertain"])
        self.assertIn("uncertain", result["why"])

    def test_close_is_clean(self):
        result = tw_orca.close_terminal("term_fake_1")
        self.assertTrue(result["ok"])


def handoff_state():
    return {
        "schemaVersion": 1,
        "workflowId": "tw-fake--1a2b3c4d",
        "taskUrls": [{"source": "trello", "url": "https://trello.com/c/abc123"}],
        "repository": "/tmp/repo",
        "baseBranch": "develop",
        "baseCommit": "88c12ba",
        "featureBranch": "feat/trello-abc--do-something",
        "worktreePath": WORKTREE_PATH,
        "currentPhase": 1,
        "phaseStatuses": {},
        "createdAt": "2026-10-15T10:00:00Z",
        "updatedAt": "2026-10-15T10:00:00Z",
    }


class TestHandoffRun(OrcaEnv):
    """The single deterministic Phase 2 entry: every outcome is recorded in
    the state (never silent) and the verdict is one JSON-able dict."""

    def setUp(self):
        super().setUp()
        self.saved = {key: os.environ.get(key)
                      for key in ("TW_STATE_STATE_DIR", "ORCA_WORKTREE_ID")}
        self.state_dir = tempfile.mkdtemp()
        os.environ["TW_STATE_STATE_DIR"] = self.state_dir
        os.environ.pop("ORCA_WORKTREE_ID", None)
        self.state_path = os.path.join(self.state_dir, "tw-fake--1a2b3c4d.json")
        tw_state.save_state(self.state_path, handoff_state())

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        super().tearDown()

    def saved_handoff(self):
        return tw_state.load_state(self.state_path).get("handoff") or {}

    def _state_bytes(self):
        with open(self.state_path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_outside_orca_records_skipped(self):
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH)
        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(self.saved_handoff()["status"], "skipped")
        self.assertIn("why", self.saved_handoff())

    def test_runtime_down_records_skipped(self):
        os.environ["ORCA_WORKTREE_ID"] = "wt1"
        open(os.path.join(self.tmp, "runtime-down"), "w").close()
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH)
        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertIn("runtime", self.saved_handoff()["why"])

    def test_success_records_pending_with_handle(self):
        os.environ["ORCA_WORKTREE_ID"] = "wt1"
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["handle"], "term_fake_1")
        handoff = self.saved_handoff()
        self.assertEqual(handoff["status"], "pending")
        self.assertEqual(handoff["terminalHandle"], "term_fake_1")
        logged = self.args_log()[-1]
        self.assertIn("--focus", logged)
        self.assertIn("claim", logged)  # resume prompt carries the claim step

    def test_unknown_worktree_records_failed(self):
        os.environ["ORCA_WORKTREE_ID"] = "wt1"
        result = tw_orca.handoff_run(self.state_path, "/tmp/repo.worktrees/other--task")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("not indexed", self.saved_handoff()["why"])

    def test_uncertain_create_records_uncertain(self):
        os.environ["ORCA_WORKTREE_ID"] = "wt1"
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        open(os.path.join(self.tmp, "uncertain-create"), "w").close()
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH)
        self.assertFalse(result["ok"])
        self.assertTrue(result["uncertain"])
        self.assertEqual(self.saved_handoff()["status"], "uncertain")

    def test_relaunch_refused_on_pending(self):
        os.environ["ORCA_WORKTREE_ID"] = "wt1"
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        self.assertTrue(tw_orca.handoff_run(self.state_path, WORKTREE_PATH)["ok"])
        before = self._state_bytes()
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH)
        self.assertFalse(result["ok"])
        self.assertTrue(result["idempotent"])
        self.assertEqual(self._state_bytes(), before)

    def test_relaunch_refused_on_accepted(self):
        state = tw_state.load_state(self.state_path)
        tw_state.set_handoff(state, "pending")
        tw_state.claim_handoff(state, "pane:t1")
        tw_state.save_state(self.state_path, state)
        before = self._state_bytes()
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH)
        self.assertFalse(result["ok"])
        self.assertTrue(result["idempotent"])
        self.assertEqual(self._state_bytes(), before)

    def test_guard_refuses_outside_canonical_dir(self):
        os.environ.pop("TW_STATE_STATE_DIR", None)
        outside = os.path.join(tempfile.mkdtemp(), "tw-fake--1a2b3c4d.json")
        tw_state.save_state(outside, handoff_state())
        result = tw_orca.handoff_run(outside, WORKTREE_PATH)
        self.assertFalse(result["ok"])
        self.assertIn("canonical", result["why"])

    def test_every_outcome_is_journaled(self):
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH)
        events = tw_state.read_events(self.state_path)
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(any("handoff skipped" in event.get("summary", "")
                            for event in events))

    def test_cmd_handoff_exit_codes(self):
        # Outside Orca → skipped → exit 1, JSON verdict on stdout, clean stderr.
        result = self._cli("handoff", self.state_path,
                           "--worktree-path", WORKTREE_PATH)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "skipped")
        self.assertEqual(result.stderr, "")  # verdict on stdout, never a traceback

    def test_cmd_handoff_uncertain_verdict(self):
        os.environ["ORCA_WORKTREE_ID"] = "wt1"
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        open(os.path.join(self.tmp, "uncertain-create"), "w").close()
        result = self._cli("handoff", self.state_path,
                           "--worktree-path", WORKTREE_PATH)
        self.assertEqual(result.returncode, 1)
        verdict = json.loads(result.stdout)
        self.assertEqual(verdict["status"], "uncertain")
        self.assertTrue(verdict["uncertain"])
        self.assertTrue(verdict["written"])

    def test_cmd_handoff_usage_exit_2(self):
        self.assertEqual(self._cli("handoff").returncode, 2)
        self.assertEqual(self._cli("handoff", self.state_path).returncode, 2)  # no path

    def test_custom_command_and_no_focus_passthrough(self):
        os.environ["ORCA_WORKTREE_ID"] = "wt1"
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH,
                                     command="echo custom", focus=False)
        self.assertTrue(result["ok"])
        logged = self.args_log()[-1]
        self.assertNotIn("--focus", logged)
        self.assertIn("echo custom", logged)

    def test_default_resume_command_embeds_current_signature(self):
        repo = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "--allow-empty", "-q", "-m", "init"],
                       check=True, capture_output=True)
        cmd = tw_orca.default_resume_command(handoff_state(), self.state_path,
                                             worktree_path=repo)
        self.assertIn(f"--signature {tw_state.compute_code_signature(repo)}", cmd)
        self.assertIn("claim", cmd)

    def test_default_resume_command_degrades_without_signature_source(self):
        cmd = tw_orca.default_resume_command(handoff_state(), self.state_path)
        self.assertNotIn("--signature", cmd)  # unmeasurable → omitted, never invented
        self.assertIn("claim", cmd)

    def test_relaunch_allowed_on_pending_without_handle(self):
        state = tw_state.load_state(self.state_path)
        tw_state.set_handoff(state, "pending", worktree_path=WORKTREE_PATH,
                             why="preparing takeover terminal")
        tw_state.save_state(self.state_path, state)
        os.environ["ORCA_WORKTREE_ID"] = "wt1"
        with open(os.path.join(self.tmp, "worktrees.json"), "w") as handle:
            handle.write(WT_JSON)
        result = tw_orca.handoff_run(self.state_path, WORKTREE_PATH)
        self.assertTrue(result["ok"], "crashed preparation must be relaunchable")
        self.assertEqual(self.saved_handoff()["terminalHandle"], "term_fake_1")

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "tw_orca.py"), *args],
            capture_output=True, text=True, check=False,
            env={**os.environ, "TW_ORCA_BIN": os.environ["TW_ORCA_BIN"],
                 "TW_FAKE_DIR": self.tmp,
                 "TW_STATE_STATE_DIR": self.state_dir})


if __name__ == "__main__":
    unittest.main()
