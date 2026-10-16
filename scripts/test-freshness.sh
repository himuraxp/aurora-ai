#!/usr/bin/env bash
set -uo pipefail

# test-freshness.sh — end-to-end validation of check-freshness.sh + install.sh
# guard (2026-10-16, cowork tour 1/2).
#
# All fixtures are local throwaway git repos (bare remote + clones): no
# network, no touch of the real repo. EVERY git call uses -C <path> — a test
# git call without explicit cwd already clobbered a real origin once
# (2026-09-18 incident, never again).
#
# Invariants under test (cowork agreement):
#   1. The check never mutates the source worktree (fetch-only).
#   2. BLOCK stops install BEFORE any live write.
#   3. A derogation is never a pass (UNVERIFIED announced, distinct exit).
#   4. No false PASS: missing/unusable upstream, network failure, detached
#      HEAD, non-git source.
#   5. dry-run never fetches (non-mutating diagnostic).

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$SCRIPTS_DIR/check-freshness.sh"
INSTALL="$SCRIPTS_DIR/install.sh"

PASS_COUNT=0
FAIL_COUNT=0
SANDBOX=""
HOME_ISO=""

cleanup() {
  [[ -n "$SANDBOX" ]] && rm -rf "$SANDBOX"
  [[ -n "$HOME_ISO" ]] && rm -rf "$HOME_ISO"
}
trap cleanup EXIT

new_sandbox() {
  SANDBOX="$(mktemp -d)"
  HOME_ISO="$(mktemp -d)"
  git -C "$SANDBOX" init -q --bare --initial-branch=main origin.git
  git clone -q "$SANDBOX/origin.git" "$SANDBOX/local" 2>/dev/null
  git -C "$SANDBOX/local" config user.email freshness-test@example.com
  git -C "$SANDBOX/local" config user.name "Freshness Fixture Test"
  git -C "$SANDBOX/local" commit -q --allow-empty -m "seed"
  git -C "$SANDBOX/local" branch -M main
  git -C "$SANDBOX/local" push -q -u origin main
}

# push_remote_commit <label> — adds one commit on origin ONLY (local stays behind)
push_remote_commit() {
  local label="$1"
  if [[ ! -d "$SANDBOX/pusher" ]]; then
    git clone -q "$SANDBOX/origin.git" "$SANDBOX/pusher" 2>/dev/null
    git -C "$SANDBOX/pusher" config user.email t@t
    git -C "$SANDBOX/pusher" config user.name t
  fi
  git -C "$SANDBOX/pusher" commit -q --allow-empty -m "$label"
  git -C "$SANDBOX/pusher" branch -M main 2>/dev/null || true
  git -C "$SANDBOX/pusher" push -q origin main
}

assert_exit() { # <expected-rc> <label> <cmd...>
  local expected="$1" label="$2"
  shift 2
  "$@" >/dev/null 2>&1
  local rc=$?
  if [[ "$rc" == "$expected" ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "  ok: $label (exit $rc)"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "  FAIL: $label — expected exit $expected, got $rc"
  fi
}

assert_output() { # <pattern> <label> <cmd...>
  local pattern="$1" label="$2"
  shift 2
  local out
  out="$("$@" 2>&1)"
  if echo "$out" | grep -q "$pattern"; then
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "  ok: $label"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "  FAIL: $label — '$pattern' not found in:"
    echo "$out" | sed 's/^/      /' | head -6
  fi
}

check_worktree_untouched() { # invariant 1
  local repo="$1" before after
  before="$(git -C "$repo" rev-parse HEAD)|$(git -C "$repo" status --porcelain)"
  "$CHECK" "$repo" >/dev/null 2>&1 || true
  after="$(git -C "$repo" rev-parse HEAD)|$(git -C "$repo" status --porcelain)"
  if [[ "$before" == "$after" ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "  ok: source worktree untouched by the check (fetch-only)"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "  FAIL: check mutated the source worktree"
  fi
}

echo "── check-freshness.sh — verdict matrix"

new_sandbox
assert_exit 0 "PASS: up to date" "$CHECK" "$SANDBOX/local"
assert_output "^✓ À jour" "PASS announces the verdict" "$CHECK" "$SANDBOX/local"
check_worktree_untouched "$SANDBOX/local"

# behind: remote-only commit
new_sandbox
push_remote_commit "remote-only work"
assert_exit 1 "BLOCK: local behind upstream" "$CHECK" "$SANDBOX/local"
assert_output "en retard" "BLOCK names the delay" "$CHECK" "$SANDBOX/local"
assert_output "pull --ff-only" "BLOCK suggests the exact catch-up command" "$CHECK" "$SANDBOX/local"
check_worktree_untouched "$SANDBOX/local"

# ahead-only: local work not pushed → legitimate PASS
new_sandbox
git -C "$SANDBOX/local" commit -q --allow-empty -m "local-only work"
assert_exit 0 "PASS: ahead-only local work" "$CHECK" "$SANDBOX/local"
assert_output "en avance" "PASS announces local lead" "$CHECK" "$SANDBOX/local"

# diverged: remote-only + local-only commits
new_sandbox
push_remote_commit "remote-side"
git -C "$SANDBOX/local" commit -q --allow-empty -m "local-side"
assert_exit 1 "BLOCK: diverged history" "$CHECK" "$SANDBOX/local"
assert_output "divergé" "BLOCK names the divergence" "$CHECK" "$SANDBOX/local"
assert_output "décision manuelle" "BLOCK refuses any automatic merge" "$CHECK" "$SANDBOX/local"

# dirty tree: PASS but announced (freshness covers HEAD, not uncommitted work)
new_sandbox
echo dirty > "$SANDBOX/local/UNCOMMITTED.txt"
git -C "$SANDBOX/local" add UNCOMMITTED.txt
assert_exit 0 "PASS: dirty tree is not a freshness block" "$CHECK" "$SANDBOX/local"
assert_output "arbre de travail sale" "dirty tree announced (will be deployed too)" "$CHECK" "$SANDBOX/local"

# non-git source
new_sandbox
assert_exit 3 "UNVERIFIED: non-git source" "$CHECK" "$SANDBOX"
assert_output "NON VÉRIFIÉE" "UNVERIFIED announced" "$CHECK" "$SANDBOX"

# detached HEAD: BLOCK by default (cowork tour 2) — a detached deploy may be
# intentional OR accidental (diagnostic, temporary checkout); it must never
# happen silently. The explicit derogation remains the only silent path.
new_sandbox
git -C "$SANDBOX/local" checkout -q --detach HEAD
assert_exit 1 "BLOCK: detached HEAD without derogation" "$CHECK" "$SANDBOX/local"
assert_output "à confirmer explicitement" "BLOCK names the derogation path" "$CHECK" "$SANDBOX/local"
assert_exit 3 "UNVERIFIED: detached HEAD WITH explicit --skip" "$CHECK" --skip "$SANDBOX/local"

# missing upstream (local branch without tracking)
new_sandbox
git -C "$SANDBOX/local" checkout -q -b feature/untracked
assert_exit 1 "BLOCK: branch without upstream" "$CHECK" "$SANDBOX/local"

# unusable upstream (tracks a local branch, not a remote)
new_sandbox
git -C "$SANDBOX/local" update-ref refs/heads/local-upstream "$(git -C "$SANDBOX/local" rev-parse HEAD)"
git -C "$SANDBOX/local" branch -q -u local-upstream
assert_exit 1 "BLOCK: upstream is not a remote" "$CHECK" "$SANDBOX/local"

# network failure: origin rewritten to an unreachable path
new_sandbox
git -C "$SANDBOX/local" remote set-url origin "$SANDBOX/does-not-exist.git"
assert_exit 1 "BLOCK: fetch failure (fail-closed)" "$CHECK" "$SANDBOX/local"

# explicit skip: allowed, announced, never a pass
new_sandbox
assert_exit 3 "UNVERIFIED: explicit --skip" "$CHECK" --skip "$SANDBOX/local"
assert_output "dérogation explicite" "skip names the derogation" "$CHECK" --skip "$SANDBOX/local"

# usage error
assert_exit 2 "usage error on unknown flag" "$CHECK" --nope

echo "── install.sh guard integration (isolated HOME, fixture repo)"

# Fixture repo carrying the real scripts, 1 commit behind origin.
new_sandbox
STALE="$SANDBOX/stale"
git clone -q "$SANDBOX/origin.git" "$STALE" 2>/dev/null
# CI runners have no global git identity — every fixture commit configures its own.
git -C "$STALE" config user.email t@t
git -C "$STALE" config user.name t
mkdir -p "$STALE/scripts"
cp "$CHECK" "$STALE/scripts/"
cp "$INSTALL" "$STALE/scripts/"
cp "$SCRIPTS_DIR/ui.sh" "$STALE/scripts/"
git -C "$STALE" add scripts/
git -C "$STALE" commit -q -m "carry install scripts"
git -C "$STALE" push -q origin main
push_remote_commit "remote-only after stale clone"  # STALE is now 1 behind

# A dry-run must NOT fetch and must announce it (invariant 5).
assert_output "fraîcheur distante non vérifiée" "dry-run: no fetch, announced" \
  env HOME="$HOME_ISO" bash -c "cd '$STALE' && bash scripts/install.sh --dry-run"
check_worktree_untouched "$STALE"

# A stale repo must be refused BEFORE any live write (invariant 2).
assert_exit 1 "install.sh BLOCKs a stale repo" \
  env HOME="$HOME_ISO" bash -c "cd '$STALE' && bash scripts/install.sh"
if [[ -e "$HOME_ISO/.config/opencode" ]]; then
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "  FAIL: live target created despite BLOCK"
else
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "  ok: live target untouched on BLOCK"
fi

# The derogation deploys and is announced as UNVERIFIED (invariant 3).
assert_output "NON VÉRIFIÉE" "derogation announced in the install summary" \
  env HOME="$HOME_ISO" bash -c "cd '$STALE' && bash scripts/install.sh --skip-freshness-check"
if [[ -e "$HOME_ISO/.config/opencode" ]]; then
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "  ok: derogation deployed the live config"
else
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "  FAIL: derogation did not deploy"
fi

# Caught-up repo deploys cleanly (real PASS path).
git -C "$STALE" fetch -q origin
git -C "$STALE" reset -q --hard FETCH_HEAD
HOME_ISO="$HOME_ISO" assert_exit 0 "install.sh deploys an up-to-date repo" \
  env HOME="$HOME_ISO" bash -c "cd '$STALE' && bash scripts/install.sh"

echo "── setup.sh derogation reachability (cowork tour 2, P1)"
# The first-deploy derogation (--skip-freshness-check when TARGET_BASE is
# absent) must be REACHABLE: if setup.sh created TARGET_BASE before calling
# install.sh, the condition would always be true and the derogation dead code.
setup_sh="$SCRIPTS_DIR/setup.sh"
install_call_line="$(grep -n 'scripts/install.sh' "$setup_sh" | head -1 | cut -d: -f1)"
if [[ -z "$install_call_line" ]]; then
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "  FAIL: install.sh call not found in setup.sh"
elif head -n "$install_call_line" "$setup_sh" | grep -q 'mkdir.*TARGET_BASE'; then
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "  FAIL: setup.sh creates TARGET_BASE before calling install.sh — derogation is dead code"
else
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "  ok: TARGET_BASE not created before the install.sh call — first-deploy derogation reachable"
fi

echo ""
echo "freshness suite: $PASS_COUNT passed, $FAIL_COUNT failed"
[[ "$FAIL_COUNT" -eq 0 ]]