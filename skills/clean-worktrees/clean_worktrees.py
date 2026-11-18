#!/usr/bin/env python3
"""clean-worktrees — remove worktrees and branches that are merged or provably gone from origin.

Deterministic, stdlib-only, plan-by-default. Only --apply mutates the repository
(worktree removal + branch deletion), and only for entries the classifier proved
safe — merged into a base ref, or the upstream ref existed pre-fetch at the exact
local tip and fetch --prune removed it in this run — or that --include-local-only
explicitly opts in.

Exit codes: 0 ok (plan or apply without failures) · 1 apply failures · 2 fatal.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

PROTECTED_DEFAULTS = ("main", "master", "develop")

# Statuses eligible for deletion. "local-only" is conditional (opt-in), see will_delete.
DELETE_STATUSES = ("merged", "gone-on-origin")

# Proof persistence (gone-on-origin): the plan run's fetch --prune consumes the
# observation (it prunes the tracking ref), so the apply run reloads it from
# here. TTL-bounded; a missing/stale file only ever means "keep" (fail-safe).
STATE_FILE = "clean-worktrees-state.json"
STATE_MAX_AGE = 3600  # seconds — the plan → GO → apply loop is minutes, not hours


class GitError(RuntimeError):
    pass


def git(args, cwd=None, check=False):
    """Run git, return (rc, stdout, stderr)."""
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError("git {} failed: {}".format(" ".join(args), proc.stderr.strip()))
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


class Ctx:
    def __init__(self, repo, remote, base, base_refs, ignore_untracked, include_local_only):
        self.repo = repo
        self.remote = remote
        self.base = base
        self.base_refs = base_refs
        self.ignore_untracked = ignore_untracked
        self.include_local_only = include_local_only
        self.upstream_snapshot = {}
        self.fetch_ok = False
        self.cwd_real = os.path.realpath(os.getcwd())
        self.protected = set(PROTECTED_DEFAULTS) | {base}


def resolve_main_worktree(cwd):
    """Return the main worktree path (or the bare repo itself)."""
    rc, out, _ = git(["rev-parse", "--show-toplevel"], cwd=cwd)
    if rc != 0:
        raise GitError("not a git repository: {}".format(cwd or os.getcwd()))
    rc, entries_out, _ = git(["worktree", "list", "--porcelain"], cwd=cwd, check=True)
    first = entries_out.splitlines()[0] if entries_out else ""
    if first.startswith("worktree "):
        return first[len("worktree "):].strip()
    raise GitError("could not resolve the main worktree")


def resolve_remote(cwd, wanted):
    """Return the remote name to use, or None if the repo has no remote."""
    if wanted:
        return wanted
    rc, out, _ = git(["remote"], cwd=cwd)
    names = out.split()
    if not names:
        return None
    if "origin" in names:
        return "origin"
    return names[0]


def detect_base(cwd, remote, explicit):
    """Detect the integration base branch (offline-first, never hardcoded to one name)."""
    if explicit:
        return explicit
    if remote:
        rc, out, _ = git(
            ["symbolic-ref", "--short", "refs/remotes/{}/HEAD".format(remote)], cwd=cwd
        )
        if rc == 0 and out.startswith(remote + "/"):
            return out[len(remote) + 1:]
    for cand in PROTECTED_DEFAULTS:
        rc, _, _ = git(["show-ref", "--verify", "--quiet", "refs/heads/" + cand], cwd=cwd)
        if rc == 0:
            return cand
    rc, out, _ = git(["symbolic-ref", "--short", "HEAD"], cwd=cwd)
    if rc == 0:
        return out
    raise GitError("no base branch detected — pass --base <name>")


def resolve_base_refs(cwd, remote, base):
    """Return the candidate refs proving a merge: origin/<base> first (fresher), then local <base>."""
    refs = []
    if remote:
        ref = "refs/remotes/{}/{}".format(remote, base)
        rc, _, _ = git(["show-ref", "--verify", "--quiet", ref], cwd=cwd)
        if rc == 0:
            refs.append(ref)
    rc, _, _ = git(["show-ref", "--verify", "--quiet", "refs/heads/" + base], cwd=cwd)
    if rc == 0:
        refs.append("refs/heads/" + base)
    if not refs:
        raise GitError("base branch '{}' not found (local or {}/{})".format(base, remote, base))
    return tuple(refs)


def fetch_prune(cwd, remote):
    """Best-effort fetch --prune; failure is not fatal (fail-safe direction)."""
    rc, _, err = git(["fetch", remote, "--prune", "--quiet"], cwd=cwd)
    if rc != 0:
        print("warning: fetch --prune failed (offline?) — origin state may be stale: {}".format(err), file=sys.stderr)
    return rc == 0


def snapshot_upstreams(cwd, remote):
    """Pre-fetch snapshot of the selected remote's tracking refs: remote_branch -> sha.

    Captured BEFORE fetch --prune: gone-on-origin is provable only against the
    upstream state this run actually observed — a ref pruned by an earlier fetch
    leaves no trace here, and an empty dict (git failure) keeps everything.
    """
    rc, out, _ = git(["for-each-ref", "--format=%(objectname)|%(refname)",
                      "refs/remotes/{}/".format(remote)], cwd=cwd)
    snap = {}
    if rc != 0:
        return snap
    prefix = "refs/remotes/{}/".format(remote)
    for line in out.splitlines():
        sha, sep, ref = line.partition("|")
        if sep and ref.startswith(prefix):
            snap[ref[len(prefix):]] = sha
    return snap


def git_common_dir(cwd):
    """Absolute path of the shared .git dir (identical for every worktree)."""
    rc, out, _ = git(["rev-parse", "--git-common-dir"], cwd=cwd)
    if rc != 0 or not out:
        return None
    return out if os.path.isabs(out) else os.path.normpath(os.path.join(cwd, out))


def load_state(gitdir, remote, now):
    """Cached pre-fetch snapshot (remote branch -> sha) from a previous run.

    The plan run's fetch --prune consumes its own observation — it prunes the
    tracking ref — so the apply run reloads it from here. A missing, stale or
    mismatched file yields {} which only ever means "keep" (fail-safe).
    """
    if not gitdir:
        return {}
    try:
        with open(os.path.join(gitdir, STATE_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if data.get("version") != 1 or data.get("remote") != remote:
        return {}
    age = now - data.get("ts", 0)
    if age < 0 or age > STATE_MAX_AGE:
        return {}
    snap = data.get("upstream")
    return snap if isinstance(snap, dict) else {}


def save_state(gitdir, remote, snapshot, now):
    """Persist the pre-fetch observation after a successful fetch (best-effort)."""
    if not gitdir:
        return
    try:
        with open(os.path.join(gitdir, STATE_FILE), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "ts": now, "remote": remote,
                       "upstream": snapshot}, fh)
    except OSError:
        pass


def list_worktrees(cwd):
    """Parse `git worktree list --porcelain` into ordered dicts (main worktree first)."""
    _, out, _ = git(["worktree", "list", "--porcelain"], cwd=cwd, check=True)
    entries = []
    cur = None
    for line in out.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            cur = {"path": value, "head": None, "branch": None, "bare": False,
                   "detached": False, "locked": False, "prunable": False}
        elif key == "HEAD":
            cur["head"] = value
        elif key == "branch":
            cur["branch"] = value
        elif key in ("bare", "detached", "locked", "prunable"):
            cur[key] = True
        elif cur is None:
            raise GitError("malformed 'git worktree list --porcelain' output")
    if cur:
        entries.append(cur)
    return entries


def ref_exists(cwd, ref):
    rc, _, _ = git(["show-ref", "--verify", "--quiet", ref], cwd=cwd)
    return rc == 0


def is_merged_anywhere(ctx, full_branch):
    """True when the branch tip is an ancestor of any base ref — no commits lost."""
    for ref in ctx.base_refs:
        rc, _, _ = git(["merge-base", "--is-ancestor", full_branch, ref], cwd=ctx.repo)
        if rc == 0:
            return True
    return False


def branch_tip(cwd, full_branch):
    """Return the current sha of a branch ref, or None when it cannot be resolved."""
    rc, out, _ = git(["rev-parse", "--verify", "--quiet", full_branch], cwd=cwd)
    return out if rc == 0 and out else None


def upstream_remote_branch(cwd, remote, branch):
    """Return <remote-branch> when <branch> tracks <remote>/<name>, else None."""
    rc, merge, _ = git(["config", "--get", "branch.{}.merge".format(branch)], cwd=cwd)
    rc2, up_remote, _ = git(["config", "--get", "branch.{}.remote".format(branch)], cwd=cwd)
    if rc != 0 or rc2 != 0 or up_remote != remote:
        return None
    prefix = "refs/heads/"
    if merge.startswith(prefix):
        return merge[len(prefix):]
    return None


def on_other_remote(cwd, selected, branch):
    """Return a non-selected remote holding a same-named branch ref, else None.

    Name equality (not tip equality) is a conservative heuristic: it can only
    turn a would-be 'local-only' into a KEEP, never the other way around.
    """
    rc, out, _ = git(["for-each-ref", "--format=%(refname)", "refs/remotes/"], cwd=cwd)
    if rc != 0:
        return None
    found = None
    for line in out.splitlines():
        parts = line.split("/")
        if len(parts) < 4 or parts[2] == selected:
            continue
        if "/".join(parts[3:]) == branch:
            found = parts[2]
    return found


def classify(ctx, entry, is_main):
    """Return (status, reason, branch_short, tip) for one worktree entry.

    tip pins the branch sha at classification time; apply_changes re-verifies it
    right before deleting, so -D can never carry commits the classifier never saw.
    """
    if is_main or entry["bare"]:
        return "main", "main worktree — never removed", None, None
    if entry["locked"]:
        return "locked", "locked worktree — unlock manually first", None, None
    if entry["detached"] or not entry["branch"]:
        return "detached", "no branch attached", None, None
    branch = entry["branch"][len("refs/heads/"):]
    if branch in ctx.protected:
        return "protected", "'{}' is a protected branch".format(branch), branch, None
    path_real = os.path.realpath(entry["path"])
    if path_real == ctx.cwd_real or ctx.cwd_real.startswith(path_real + os.sep):
        return "current", "script running inside this worktree", branch, None
    if not os.path.isdir(entry["path"]) or entry["prunable"]:
        return "stale", "directory missing on disk — clean with --prune", branch, None
    status_args = ["status", "--porcelain"]
    if ctx.ignore_untracked:
        status_args.append("--untracked-files=no")
    rc, out, err = git(status_args, cwd=entry["path"])
    if rc != 0:
        return "error", err or "git status failed", branch, None
    if out.strip():
        return "dirty", "uncommitted changes", branch, None
    tip = branch_tip(ctx.repo, entry["branch"])
    if is_merged_anywhere(ctx, entry["branch"]):
        return "merged", "merged into {}".format(ctx.base), branch, tip
    rb = upstream_remote_branch(ctx.repo, ctx.remote, branch)
    origin_branch = rb if rb is not None else branch
    on_origin = bool(ctx.remote) and ref_exists(
        ctx.repo, "refs/remotes/{}/{}".format(ctx.remote, origin_branch))
    if on_origin:
        return "active-on-origin", "'{}/{}' still exists".format(ctx.remote, origin_branch), branch, tip
    if rb is not None:
        pre_sha = ctx.upstream_snapshot.get(rb)
        # Deletion requires an in-run observation: the ref existed pre-fetch at
        # exactly the local tip (nothing unpushed), fetch succeeded, and the ref
        # is gone post-fetch. Anything less keeps the branch (fail-safe).
        if ctx.fetch_ok and pre_sha and tip and pre_sha == tip:
            return "gone-on-origin", "'{}/{}' deleted — tip was fully pushed".format(ctx.remote, rb), branch, tip
        return "unverified-origin", "'{}/{}' deleted — unpushed commits cannot be ruled out".format(ctx.remote, rb), branch, tip
    other = on_other_remote(ctx.repo, ctx.remote, branch)
    if other:
        return "on-other-remote", "'{}/{}' exists on remote '{}' — not selected".format(other, branch, other), branch, tip
    return "local-only", "never pushed — potential WIP (opt-in with --include-local-only)", branch, tip


def will_delete(ctx, status):
    if status == "local-only":
        return ctx.include_local_only
    return status in DELETE_STATUSES


def build_report(ctx, entries):
    report = []
    for idx, e in enumerate(entries):
        status, reason, branch, tip = classify(ctx, e, idx == 0)
        e.update(status=status, reason=reason, branch_short=branch, tip=tip,
                 delete=will_delete(ctx, status))
        report.append(e)
    return report


def short(path):
    return path.replace(os.path.expanduser("~"), "~")


def print_plan(ctx, report):
    deletes = [e for e in report if e["delete"]]
    keeps = [e for e in report if not e["delete"]]
    base_label = "{}/{}".format(ctx.remote, ctx.base) if ctx.remote else ctx.base
    print("Repo:   {}".format(short(ctx.repo)))
    print("Remote: {}".format(ctx.remote or "(none)"))
    print("Base:   {} ({})".format(base_label, ", ".join(ctx.base_refs)))
    print("Worktrees: {} total (main excluded)".format(len(report) - 1))
    print("")
    print("DELETE ({})".format(len(deletes)))
    for e in deletes:
        print("  {:<16} {}".format(e["status"], e["branch_short"]))
        print("  {:<16} {}".format("", e["path"]))
    print("")
    print("KEEP ({})".format(len(keeps)))
    for e in keeps:
        label = e["branch_short"] or e["status"]
        print("  {:<16} {}".format(e["status"], label))
        print("  {:<16} {}".format("", e["reason"]))
    print("")
    print("Summary: delete {} · keep {}".format(len(deletes), len(keeps)))
    if not ctx.apply:
        print("Dry-run (no changes). Re-run with --apply to delete the DELETE entries.")
    return deletes, keeps


def print_apply(report, applied, failed, pruned):
    print("")
    print("APPLIED ({})".format(len(applied)))
    for e in applied:
        print("  ok  {:<16} {} — worktree removed · branch removed".format(e["status"], e["branch_short"]))
    print("FAILED ({})".format(len(failed)))
    for e, step, err in failed:
        print("  {:<16} {} — {} failed: {}".format(e["status"], e["path"], step, err or "exit code != 0"))
    print("")
    print("Done: {} deleted, {} failed{}.".format(
        len(applied), len(failed), ", stale entries pruned" if pruned else ""))
    return len(failed) == 0


def apply_changes(ctx, report):
    applied, failed = [], []
    pruned = False
    if ctx.prune:
        git(["worktree", "prune"], cwd=ctx.repo, check=True)
        pruned = True
    for e in report:
        if not e["delete"]:
            continue
        # Re-verify the tip is the exact sha the classifier proved: a concurrent
        # commit between classification and now would otherwise be destroyed by
        # -D carrying unproven work. Divergence is always a FAILED, never a delete.
        rc, out, _ = git(["rev-parse", "--verify", "--quiet",
                          "refs/heads/" + e["branch_short"]], cwd=ctx.repo)
        if rc != 0 or out != e["tip"]:
            failed.append((e, "tip check",
                           "branch tip moved since classification — re-run the plan"))
            continue
        rc, _, err = git(["worktree", "remove", e["path"]], cwd=ctx.repo)
        if rc != 0 and ctx.ignore_untracked:
            # Untracked files make git refuse a remove; --force only ever applies
            # when tracked files are verified clean at this exact moment.
            rc2, out2, _ = git(["status", "--porcelain", "--untracked-files=no"],
                               cwd=e["path"])
            if rc2 == 0 and not out2.strip():
                rc, _, err = git(["worktree", "remove", "--force", e["path"]], cwd=ctx.repo)
        if rc != 0:
            failed.append((e, "worktree remove", err))
            continue
        # -D is justified: -d's weaker check (relative to the current HEAD) refuses
        # valid deletions (e.g. origin/base ahead of local base, squash merges).
        # Every -D here carries its proof: ancestry to a base ref, an origin state
        # observed in this run (pre-fetch upstream snapshot == local tip, ref then
        # pruned by fetch), or the explicit --include-local-only opt-in — with the
        # tip re-verified one step above.
        rc, _, err = git(["branch", "-D", e["branch_short"]], cwd=ctx.repo)
        if rc != 0:
            failed.append((e, "branch delete", err))
            continue
        applied.append(e)
    return applied, failed, pruned


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Plan (default) or apply cleanup of merged / origin-gone worktrees and branches.")
    parser.add_argument("--repo", help="path inside the repository (default: cwd)")
    parser.add_argument("--remote", help="remote name (default: origin, else first)")
    parser.add_argument("--base", help="integration base branch (default: origin/HEAD, else develop/main/master)")
    parser.add_argument("--apply", action="store_true",
                        help="perform the deletions shown by the plan (default: dry-run)")
    parser.add_argument("--ignore-untracked", action="store_true",
                        help="untracked files (build artifacts…) do not mark a worktree dirty")
    parser.add_argument("--include-local-only", action="store_true",
                        help="also delete clean branches never pushed to origin (potential WIP — ask the user first)")
    parser.add_argument("--prune", action="store_true",
                        help="with --apply: also run `git worktree prune` (stale entries)")
    args = parser.parse_args(argv)

    try:
        repo = os.path.abspath(args.repo or os.getcwd())
        # Validation only (not a repo / malformed porcelain -> GitError, exit 2).
        resolve_main_worktree(repo)
        remote = resolve_remote(repo, args.remote)
        # Pre-fetch snapshot MUST precede fetch --prune: gone-on-origin is only
        # provable against the upstream state this run actually observed.
        upstream_snapshot = snapshot_upstreams(repo, remote) if remote else {}
        fetch_ok = fetch_prune(repo, remote) if remote else False
        gitdir = git_common_dir(repo)
        cached = load_state(gitdir, remote, time.time()) if remote else {}
        # Live pre-fetch state wins over the cached one; the cache only fills
        # refs this run never saw (pruned by an earlier run's fetch).
        merged = dict(cached)
        merged.update(upstream_snapshot)
        if remote and fetch_ok:
            save_state(gitdir, remote, merged, time.time())
        base = detect_base(repo, remote, args.base)
        base_refs = resolve_base_refs(repo, remote, base)
        ctx = Ctx(repo, remote, base, base_refs, args.ignore_untracked, args.include_local_only)
        ctx.upstream_snapshot = merged
        ctx.fetch_ok = fetch_ok
        ctx.prune = args.prune
        ctx.apply = args.apply
        entries = list_worktrees(repo)
        report = build_report(ctx, entries)
        deletes, keeps = print_plan(ctx, report)
        if not args.apply:
            return 0
        applied, failed, pruned = apply_changes(ctx, report)
        ok = print_apply(report, applied, failed, pruned)
        return 0 if ok else 1
    except GitError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
