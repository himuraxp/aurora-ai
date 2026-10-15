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
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tw_orca  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
