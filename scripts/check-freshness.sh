#!/usr/bin/env bash
set -euo pipefail

# check-freshness.sh — pre-flight freshness guard for install.sh (2026-10-16).
#
# Verifies the SOURCE repo is not behind its upstream BEFORE any live file is
# touched — a stale local repo must never be deployed to ~/.config/opencode.
#
# Contract:
#   - fetch-only: never mutates the source worktree (no pull/merge/rebase/
#     checkout/reset/stash). The targeted fetch updates FETCH_HEAD only.
#   - Three issues, never conflated:
#       PASS        — upstream has no commit missing from HEAD (ahead-only is
#                     PASS: local work ahead is a legitimate deployment)
#       BLOCK       — behind, diverged, unusable upstream, or fetch failure
#                     (fail-closed: install must stop, live untouched)
#       UNVERIFIED  — freshness could not be verified honestly: non-git
#                     source, detached HEAD, or explicit --skip. Allowed but
#                     ALWAYS announced — never presented as a PASS.
#
# Exit codes: 0 PASS · 1 BLOCK · 2 usage · 3 UNVERIFIED (continue, announced)
#
# Usage: check-freshness.sh [--skip] [repo-path]
#   --skip       explicit caller derogation → UNVERIFIED (never a PASS)
#   repo-path    source repo (default: the repo this script lives in)
#
# Off-line deployments must be a conscious choice: the only skip paths are
# --skip here (wired to --skip-freshness-check in install.sh) — network
# failures BLOCK with that exact escape hatch in the message.

usage() {
  cat <<'EOF'
Usage: check-freshness.sh [--skip] [repo-path]

Exit codes: 0 PASS · 1 BLOCK · 2 usage · 3 UNVERIFIED (allowed, announced)
EOF
}

REPO=""
SKIP=false
for arg in "$@"; do
  case "$arg" in
    --skip)
      SKIP=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
    *)
      REPO="$arg"
      ;;
  esac
done

if [[ -z "$REPO" ]]; then
  REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

block() {
  echo "✗ FRESHNESS: $1"
  echo ""
  echo "Aucun fichier live modifié — l'installation est stoppée avant toute écriture."
  echo "Contournement explicite (hors ligne / volontaire) :"
  echo "  ./scripts/install.sh --skip-freshness-check"
  exit 1
}

unverified() {
  echo "⚠ FRESHNESS: NON VÉRIFIÉE — $1"
  echo "  L'installation continue, mais ce n'est PAS un contrôle réussi."
  exit 3
}

# ─── Explicit derogation ─────────────────────────────────────────────────────
if [[ "$SKIP" == true ]]; then
  unverified "dérogation explicite de l'appelant (--skip-freshness-check)"
fi

# ─── Source must be a git repo ───────────────────────────────────────────────
if ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  unverified "la source n'est pas un dépôt git (archive téléchargée ?)"
fi

# ─── Branch context ──────────────────────────────────────────────────────────
branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
head_sha="$(git -C "$REPO" rev-parse --short HEAD)"

if [[ "$branch" == "HEAD" ]]; then
  unverified "HEAD détaché ($head_sha) — déploiement volontaire d'une référence précise, fraîcheur invérifiable"
fi

upstream="$(git -C "$REPO" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
if [[ -z "$upstream" ]]; then
  block "la branche $branch ($head_sha) n'a pas d'upstream — fraîcheur invérifiable"
fi

# The upstream must be a real remote-tracking ref (not a local branch): an
# upstream pointing at a local branch is not evidence of freshness.
remote="${upstream%%/*}"
if ! git -C "$REPO" remote get-url "$remote" >/dev/null 2>&1; then
  block "l'upstream $upstream ne pointe pas vers un remote connu — corrige la config (git branch --set-upstream-to)"
fi

remote_url="$(git -C "$REPO" remote get-url "$remote")"

echo "[freshness] Vérification de $upstream ($remote_url)..."

# ─── Targeted fetch (network fail-closed, no prompt, bounded connect) ───────
# Updates FETCH_HEAD only — remote-tracking refs and the worktree stay put.
if ! GIT_TERMINAL_PROMPT=0 \
     GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10" \
     git -C "$REPO" -c http.connectTimeout=10 -c http.lowSpeedLimit=1 -c http.lowSpeedTime=15 \
     fetch --quiet "$remote" "$branch"; then
  block "fetch impossible depuis $remote — vérifie le réseau (aucune vérification ≠ à jour)"
fi

remote_tip="$(git -C "$REPO" rev-parse --short FETCH_HEAD)"

# ─── Ahead/behind verdict ────────────────────────────────────────────────────
# left = commits only in HEAD (ahead), right = commits only upstream (behind).
counts="$(git -C "$REPO" rev-list --left-right --count "HEAD...FETCH_HEAD")"
ahead="$(echo "$counts" | awk '{print $1}')"
behind="$(echo "$counts" | awk '{print $2}')"

if [[ "$behind" -gt 0 && "$ahead" -gt 0 ]]; then
  echo "✗ FRESHNESS: historique divergé — $ahead commit(s) en avance, $behind en retard."
  echo "  Local   : $head_sha ($branch)"
  echo "  Distant : $remote_tip ($upstream)"
  block "la divergence nécessite une décision manuelle (jamais de merge/rebase automatique)"
fi

if [[ "$behind" -gt 0 ]]; then
  echo "✗ FRESHNESS: dépôt local en retard de $behind commit(s)."
  echo "  Local   : $head_sha ($branch)"
  echo "  Distant : $remote_tip ($upstream)"
  echo ""
  echo "Action :"
  echo "  git -C \"$REPO\" pull --ff-only"
  echo "  npm run update"
  block "déployer un dépôt en retard interdit"
fi

# ─── PASS (dirty tree is announced, not hidden) ──────────────────────────────
if [[ -n "$(git -C "$REPO" status --porcelain)" ]]; then
  echo "⚠ FRESHNESS: arbre de travail sale — la fraîcheur porte sur HEAD ($head_sha) ;"
  echo "  des modifications non commitées SERONT déployées aussi."
fi

if [[ "$ahead" -gt 0 ]]; then
  echo "✓ À jour — $ahead commit(s) en avance sur $upstream (HEAD $head_sha)"
else
  echo "✓ À jour — HEAD $head_sha == $upstream"
fi
exit 0
