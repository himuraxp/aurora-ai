"""E2E tests for clean_worktrees.py — real temporary git repos, offline."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "clean_worktrees.py"
GIT_IDENTITY = ["-c", "user.email=test@example.com", "-c", "user.name=test"]


def g(path, *args, check=True):
    proc = subprocess.run(["git", *GIT_IDENTITY, *args], cwd=str(path),
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError("git {} failed in {}: {}".format(
            " ".join(args), path, proc.stderr.strip()))
    return proc


def run_skill(cwd, *flags):
    return subprocess.run([sys.executable, str(SCRIPT), *flags], cwd=str(cwd),
                          capture_output=True, text=True)


def make_repo(tmp, name="repo", with_remote=True, base="develop"):
    """Clone-like repo with origin/HEAD -> <base>. Returns (repo, origin) paths."""
    seed = tmp / "seed"
    g(tmp, "init", "-b", base, str(seed))
    (seed / "README.md").write_text("# seed\n")
    g(seed, "add", "-A")
    g(seed, "commit", "-m", "initial commit")
    origin = tmp / "origin.git"
    repo = tmp / name
    if with_remote:
        g(tmp, "init", "--bare", "-b", base, str(origin))
        g(seed, "remote", "add", "origin", str(origin))
        g(seed, "push", "-u", "origin", base)
        g(tmp, "clone", str(origin), str(repo))
    else:
        g(tmp, "init", "-b", base, str(repo))
    if not with_remote:
        (repo / "README.md").write_text("# seed\n")
        g(repo, "add", "-A")
        g(repo, "commit", "-m", "initial commit")
    g(repo, "config", "user.email", "test@example.com")
    g(repo, "config", "user.name", "test")
    shutil.rmtree(seed)
    return repo, origin


def commit_all(path, msg, fname="file.txt", content=None):
    (Path(path) / fname).write_text(content or (msg + "\n"))
    g(path, "add", "-A")
    g(path, "commit", "-m", msg)


def add_wt(tmp, repo, name, branch=None, base="develop", detach=False):
    path = tmp / "wts" / name
    if detach:
        g(repo, "worktree", "add", str(path), "--detach", base)
    elif branch:
        g(repo, "worktree", "add", str(path), "-b", branch, base)
    else:
        g(repo, "worktree", "add", str(path), base)  # checkout an existing branch
    return path


def wt_exists(repo, path):
    out = g(repo, "worktree", "list", "--porcelain").stdout
    real = os.path.realpath(str(path))
    return any(line.startswith("worktree ") and os.path.realpath(line[len("worktree "):]) == real
               for line in out.splitlines())


def branch_exists(repo, branch):
    return g(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch,
             check=False).returncode == 0


class CleanWorktrees(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="clean-wt-test-"))
        self.repo, self.origin = make_repo(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- classification -------------------------------------------------

    def test_merged_local_only_base(self):
        """Merged locally (origin/base stale) is still merged — local base ref counts."""
        wt = add_wt(self.tmp, self.repo, "wt-merged", "feat/merged")
        commit_all(wt, "feature work")
        g(self.repo, "merge", "feat/merged", "-m", "merge feature")  # no push
        r = run_skill(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("merged", r.stdout)
        self.assertIn("DELETE", r.stdout)

    def test_merged_deleted_on_apply(self):
        wt = add_wt(self.tmp, self.repo, "wt-merged", "feat/merged")
        commit_all(wt, "feature work")
        g(self.repo, "merge", "feat/merged", "-m", "merge feature")
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("APPLIED (1)", r.stdout)
        self.assertFalse(wt_exists(self.repo, wt))
        self.assertFalse(branch_exists(self.repo, "feat/merged"))

    def test_gone_on_origin_squash_case(self):
        """Branch deleted on origin after (squash) merge -> gone-on-origin -> DELETE."""
        wt = add_wt(self.tmp, self.repo, "wt-squash", "feat/squash")
        commit_all(wt, "feature work")
        g(wt, "push", "-u", "origin", "feat/squash")
        sha = g(self.repo, "rev-parse", "feat/squash").stdout.strip()
        # Simulate a server-side squash: same changes, different commit
        # (different message -> different sha, never an ancestor of the branch).
        g(self.repo, "cherry-pick", "--no-commit", sha)
        g(self.repo, "commit", "-m", "chore: merge PR #123 (squash)")
        g(self.repo, "push", "origin", "develop")
        # Server-side branch deletion, as GitLab does: the bare remote loses the
        # ref while the local tracking ref lingers until the skill's fetch --prune
        # observes the deletion in-run. (A local `push --delete` would prune the
        # tracking ref too — then the skill cannot observe anything and keeps,
        # see test_pruned_ref_offline_stays_kept.)
        g(self.origin, "update-ref", "-d", "refs/heads/feat/squash")
        r = run_skill(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("gone-on-origin", r.stdout)
        self.assertIn("DELETE", r.stdout)
        r2 = run_skill(self.repo, "--apply")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertFalse(wt_exists(self.repo, wt))
        self.assertFalse(branch_exists(self.repo, "feat/squash"))

    def test_gone_on_origin_blocked_by_unpushed_commit(self):
        """Origin branch deleted but local tip has unpushed commits -> keep (unverified)."""
        wt = add_wt(self.tmp, self.repo, "wt-wip", "feat/wip")
        commit_all(wt, "feature work")
        g(wt, "push", "-u", "origin", "feat/wip")
        pushed = g(self.repo, "rev-parse", "feat/wip").stdout.strip()
        commit_all(wt, "late WIP never pushed")  # local tip moves past the pushed sha
        g(self.repo, "cherry-pick", "--no-commit", pushed)
        g(self.repo, "commit", "-m", "chore: merge PR #456 (squash)")
        g(self.origin, "update-ref", "-d", "refs/heads/feat/wip")
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("unverified-origin", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/wip"))

    def test_offline_fetch_failure_failsafe(self):
        """Remote unreachable -> warning, nothing deleted (fail-safe direction)."""
        wt = add_wt(self.tmp, self.repo, "wt-off", "feat/off")
        commit_all(wt, "feature work")
        g(wt, "push", "-u", "origin", "feat/off")
        g(self.repo, "remote", "set-url", "origin", str(self.tmp / "unreachable.git"))
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning:", r.stderr)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/off"))

    def test_pruned_ref_offline_stays_kept(self):
        """Ref pruned by an earlier fetch + fetch now failing -> unverified-origin, keep."""
        wt = add_wt(self.tmp, self.repo, "wt-stale", "feat/stale-ref")
        commit_all(wt, "feature work")
        g(wt, "push", "-u", "origin", "feat/stale-ref")
        g(self.origin, "update-ref", "-d", "refs/heads/feat/stale-ref")
        g(self.repo, "fetch", "origin", "--prune")  # earlier successful fetch prunes the ref
        g(self.repo, "remote", "set-url", "origin", str(self.tmp / "unreachable.git"))
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("unverified-origin", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/stale-ref"))

    def test_active_on_origin_kept(self):
        wt = add_wt(self.tmp, self.repo, "wt-active", "feat/active")
        commit_all(wt, "feature work")
        g(wt, "push", "-u", "origin", "feat/active")
        r = run_skill(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("active-on-origin", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/active"))

    def test_local_only_skipped_by_default_then_included(self):
        wt = add_wt(self.tmp, self.repo, "wt-local", "feat/local")
        commit_all(wt, "unpushed work")
        r = run_skill(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("local-only", r.stdout)
        r1 = run_skill(self.repo, "--apply")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertTrue(wt_exists(self.repo, wt))
        r2 = run_skill(self.repo, "--apply", "--include-local-only")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertFalse(wt_exists(self.repo, wt))
        self.assertFalse(branch_exists(self.repo, "feat/local"))

    def test_dirty_skipped(self):
        wt = add_wt(self.tmp, self.repo, "wt-dirty", "feat/dirty")
        commit_all(wt, "committed")
        (wt / "file.txt").write_text("uncommitted\n")
        g(self.repo, "merge", "feat/dirty", "-m", "merge")  # merged but dirty wt
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dirty", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/dirty"))

    def test_untracked_only_dirty_by_default_ignored_with_flag(self):
        wt = add_wt(self.tmp, self.repo, "wt-untracked", "feat/untracked")
        commit_all(wt, "committed")
        (wt / "node_modules.txt").write_text("junk\n")  # untracked
        g(self.repo, "merge", "feat/untracked", "-m", "merge")
        r = run_skill(self.repo)
        self.assertIn("dirty", r.stdout)
        r2 = run_skill(self.repo, "--apply", "--ignore-untracked")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertFalse(wt_exists(self.repo, wt))

    def test_protected_branch_worktree_kept(self):
        g(self.repo, "checkout", "-b", "wip-main")
        wt = add_wt(self.tmp, self.repo, "wt-develop", branch=None, base="develop")
        # develop (protected) is now checked out in a secondary worktree
        r = run_skill(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("protected", r.stdout)
        r2 = run_skill(self.repo, "--apply")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue(wt_exists(self.repo, wt))

    def test_current_worktree_skipped(self):
        wt = add_wt(self.tmp, self.repo, "wt-current", "feat/current")
        commit_all(wt, "feature work")
        g(self.repo, "merge", "feat/current", "-m", "merge")
        r = run_skill(wt, "--repo", str(self.repo), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("current", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))

    def test_locked_and_detached_skipped(self):
        locked = add_wt(self.tmp, self.repo, "wt-locked", "feat/locked")
        detached = add_wt(self.tmp, self.repo, "wt-detached", base="develop", detach=True)
        g(self.repo, "worktree", "lock", str(locked))
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("locked", r.stdout)
        self.assertIn("detached", r.stdout)
        self.assertTrue(wt_exists(self.repo, locked))
        self.assertTrue(wt_exists(self.repo, detached))

    def test_stale_pruned_only_with_flag_and_branch_kept(self):
        wt = add_wt(self.tmp, self.repo, "wt-stale", "feat/stale")
        shutil.rmtree(wt)
        r = run_skill(self.repo)
        self.assertIn("stale", r.stdout)
        r1 = run_skill(self.repo, "--apply")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertTrue(wt_exists(self.repo, wt))  # prune not requested
        r2 = run_skill(self.repo, "--apply", "--prune")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("stale entries pruned", r2.stdout)
        self.assertFalse(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/stale"))  # prune never deletes branches

    # --- plan guarantees & errors ---------------------------------------

    def test_plan_makes_no_mutation(self):
        wt = add_wt(self.tmp, self.repo, "wt-merged", "feat/merged")
        commit_all(wt, "feature work")
        g(self.repo, "merge", "feat/merged", "-m", "merge feature")
        r = run_skill(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Dry-run (no changes)", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/merged"))

    def test_no_remote_repo(self):
        tmp2 = self.tmp / "noremote"
        tmp2.mkdir()
        repo, _ = make_repo(tmp2, name="repo2", with_remote=False)
        wt_a = add_wt(tmp2, repo, "wt-a", "feat/merged-a")
        commit_all(wt_a, "work")
        g(repo, "merge", "feat/merged-a", "-m", "merge a")
        wt_b = add_wt(tmp2, repo, "wt-b", "feat/local-b")
        commit_all(wt_b, "work b")
        r = run_skill(repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(wt_exists(repo, wt_a))
        self.assertFalse(branch_exists(repo, "feat/merged-a"))
        self.assertTrue(wt_exists(repo, wt_b))
        self.assertTrue(branch_exists(repo, "feat/local-b"))

    def test_fatal_not_a_repo(self):
        r = run_skill(self.tmp)  # tmp dir contains repos but is not one
        self.assertEqual(r.returncode, 2)
        self.assertIn("error:", r.stderr)

    # --- hardening (review round) ----------------------------------------

    def test_protected_precedence_over_merged(self):
        """A protected branch (main) whose tip is the base tip stays protected, not merged."""
        g(self.repo, "checkout", "-b", "wip-main")  # move main wt off develop
        g(self.repo, "branch", "main", "develop")  # protected branch == base tip
        wt = add_wt(self.tmp, self.repo, "wt-prot", branch=None, base="main")
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("protected", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "main"))

    def test_locked_precedence_over_merged(self):
        """A locked worktree on a merged branch is locked (keep), never merged (delete)."""
        wt = add_wt(self.tmp, self.repo, "wt-ml", "feat/ml")
        commit_all(wt, "feature work")
        g(self.repo, "merge", "feat/ml", "-m", "merge ml")
        g(self.repo, "worktree", "lock", str(wt))
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("locked", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/ml"))

    def test_main_worktree_branch_never_deleted(self):
        """The main worktree's branch (base) survives --apply even though trivially merged."""
        wt = add_wt(self.tmp, self.repo, "wt-x", "feat/x")
        commit_all(wt, "feature work")
        g(self.repo, "merge", "feat/x", "-m", "merge x")
        r = run_skill(self.repo, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(branch_exists(self.repo, "develop"))  # base == main wt branch
        self.assertFalse(branch_exists(self.repo, "feat/x"))

    def test_base_detection_without_origin_head(self):
        """Base falls back to the local protected branch (path 3), then to HEAD (path 4)."""
        tmp3 = self.tmp / "base3"
        tmp3.mkdir()
        repo3, _ = make_repo(tmp3, name="r3", with_remote=False, base="develop")
        r3 = run_skill(repo3)
        self.assertEqual(r3.returncode, 0, r3.stderr)
        self.assertIn("Base:   develop", r3.stdout)
        tmp4 = self.tmp / "base4"
        tmp4.mkdir()
        repo4, _ = make_repo(tmp4, name="r4", with_remote=False, base="trunk")
        r4 = run_skill(repo4)
        self.assertEqual(r4.returncode, 0, r4.stderr)
        self.assertIn("Base:   trunk", r4.stdout)

    def test_current_from_subdirectory(self):
        """Running from a subfolder of a worktree still marks it current."""
        wt = add_wt(self.tmp, self.repo, "wt-cur", "feat/cur")
        commit_all(wt, "feature work")
        g(self.repo, "merge", "feat/cur", "-m", "merge cur")
        sub = wt / "sub"
        sub.mkdir()
        r = run_skill(sub, "--repo", str(self.repo), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("current", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))

    def test_branch_on_other_remote_kept(self):
        """Branch pushed to a non-selected remote -> on-other-remote, kept (not local-only)."""
        fork = self.tmp / "fork.git"
        g(self.tmp, "init", "--bare", "-b", "develop", str(fork))
        wt = add_wt(self.tmp, self.repo, "wt-fork", "feat/fork")
        commit_all(wt, "work on fork")
        g(self.repo, "remote", "add", "fork", str(fork))
        g(wt, "push", "-u", "fork", "feat/fork")
        r = run_skill(self.repo, "--apply", "--include-local-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("on-other-remote", r.stdout)
        self.assertNotIn("local-only", r.stdout)
        self.assertTrue(wt_exists(self.repo, wt))
        self.assertTrue(branch_exists(self.repo, "feat/fork"))


if __name__ == "__main__":
    unittest.main()
