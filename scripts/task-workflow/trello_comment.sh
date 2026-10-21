#!/usr/bin/env bash
# trello_comment.sh — Post the MR link as a comment on the linked Trello card
# (task-workflow step 7 bis, deterministic API path).
#
# Contract:
#   bash trello_comment.sh --card-url <url> --mr-url <url> [--mr-title <s>] [--branch <s>] [--dry-run]
#   Prints ONE JSON line: {"outcome":"...","commentId"?: "...","reason"?: "...","channel":"api"}
#   Outcomes: posted | already | no-token | dry-run | failed
#   Exit codes: 0 posted|already|dry-run · 1 failed · 2 usage error · 3 no-token
#   Exit 3 = the orchestrator falls back to the browser-debug path (task-workflow
#   SKILL.md step 7 bis): the skill still works, the trace records the channel.
#
# Secrets (never echoed, never in argv — pattern ensure_glab_token.sh):
#   1. TRELLO_API_KEY / TRELLO_TOKEN environment variables
#   2. ${TRELLO_ENV_FILE:-$HOME/.config/opencode/.env}  (canonical store)
#   All curl credentials travel through the config read from stdin (-K -), so
#   `ps` never sees them. One-shot setup: https://trello.com/appkey.
#
# Idempotence (GET-before-POST): the card's existing comments are fetched
# first; if the MR URL is already in a comment body → outcome "already",
# no POST. Replay-safe by construction, not by convention.
#
# Zero network in tests: curl is stubbed via PATH (tests/test_all.sh).
set -euo pipefail

TRELLO_ENV_FILE="${TRELLO_ENV_FILE:-$HOME/.config/opencode/.env}"
TRELLO_API_BASE="https://api.trello.com/1"

usage() {
  echo "usage: trello_comment.sh --card-url <trello-card-url> --mr-url <mr-url> [--mr-title <title>] [--branch <branch>] [--dry-run]" >&2
  echo "  --card-url   Trello card URL (trello.com/c/<shortLink>[/<title>] or trello.com/<shortLink>)" >&2
  echo "  --mr-url     Merge request URL to post as the comment" >&2
  echo "  --dry-run    Print the comment body + outcome without any network call" >&2
  echo "Exit: 0 posted/already/dry-run · 1 failed · 2 usage · 3 no-token (browser-debug fallback)" >&2
}

_tc_emit() {
  # $1 outcome · $2 commentId ("" = omit) · $3 reason ("" = omit).
  # Reasons are script-controlled strings; quotes are escaped defensively.
  local out="{\"outcome\":\"$1\""
  if [[ -n "${2:-}" ]]; then out+=",\"commentId\":\"$(printf '%s' "$2" | sed 's/"/\\"/g')\""; fi
  if [[ -n "${3:-}" ]]; then out+=",\"reason\":\"$(printf '%s' "$3" | sed 's/"/\\"/g')\""; fi
  printf '%s\n' "${out},\"channel\":\"api\"}"
}

_tc_fail() {
  _tc_emit failed "" "$1"
  exit 1
}

# $1 = file, $2 = var name → prints the last VALUE (bare or double-quoted).
# Values are consumed internally only — callers never echo them.
_tc_env_value() {
  grep -E "^[[:space:]]*(export[[:space:]]+)?${2}=" "$1" 2>/dev/null |
    tail -1 |
    sed -E "s/^[[:space:]]*(export[[:space:]]+)?${2}=//; s/^\"//; s/\"[[:space:]]*\$//"
}

_tc_short_link() {
  printf '%s' "$1" | sed -E 's#https?://trello\.com/(c/)?##; s#[/?#].*$##'
}

card_url=""
mr_url=""
mr_title=""
branch=""
dry_run="no"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --card-url) [[ $# -ge 2 ]] || { usage; exit 2; }; card_url="$2"; shift 2 ;;
    --mr-url)   [[ $# -ge 2 ]] || { usage; exit 2; }; mr_url="$2"; shift 2 ;;
    --mr-title) [[ $# -ge 2 ]] || { usage; exit 2; }; mr_title="$2"; shift 2 ;;
    --branch)   [[ $# -ge 2 ]] || { usage; exit 2; }; branch="$2"; shift 2 ;;
    --dry-run)  dry_run="yes"; shift ;;
    -h|--help)  usage; exit 0 ;;
    *)          usage; exit 2 ;;
  esac
done
[[ -n "$card_url" && -n "$mr_url" ]] || { usage; exit 2; }

short_link="$(_tc_short_link "$card_url")"
if ! [[ "$short_link" =~ ^[a-zA-Z0-9]{8}$ ]]; then
  echo "ERROR: cannot extract a Trello shortLink (8 alnum chars) from: $card_url" >&2
  exit 2
fi
case "$mr_url" in
  https://*|http://*) : ;;
  *) echo "ERROR: --mr-url must be an absolute http(s) URL" >&2; exit 2 ;;
esac

# ── Comment body (deterministic, single source of truth for both paths) ──────
body="🔗 Merge request liée : ${mr_url}"
if [[ -n "$mr_title" ]]; then body="${body}
📝 ${mr_title}"; fi
if [[ -n "$branch" ]]; then body="${body}
🌿 Branche : ${branch}"; fi
body="${body}
✔️ Prête pour revue humaine — jamais de merge automatique (task-workflow)"

if [[ "$dry_run" == "yes" ]]; then
  printf '%s\n' "--- comment body ---"
  printf '%s\n' "$body"
  printf '%s\n' "--- end (no network call) ---"
  _tc_emit dry-run
  exit 0
fi

# ── Secrets: env first, then the canonical .env file ─────────────────────────
# Resolution is done OUTSIDE ${VAR:-$(cmd)} expansions: under set -euo pipefail
# a failing grep inside an expansion kills the script silently — and a missing
# .env or an absent key must yield the clean no-token outcome (exit 3), not an
# opaque death.
key="${TRELLO_API_KEY:-}"
if [[ -z "$key" ]]; then key="$(_tc_env_value "$TRELLO_ENV_FILE" TRELLO_API_KEY || true)"; fi
token="${TRELLO_TOKEN:-}"
if [[ -z "$token" ]]; then token="$(_tc_env_value "$TRELLO_ENV_FILE" TRELLO_TOKEN || true)"; fi
if [[ -z "$key" || -z "$token" ]]; then
  _tc_emit no-token "no TRELLO_API_KEY/TRELLO_TOKEN in env or ${TRELLO_ENV_FILE} — one-shot setup at https://trello.com/appkey, or use the browser-debug fallback (task-workflow step 7 bis)"
  exit 3
fi

tmp="$(mktemp)"
body_file="$(mktemp)"
trap 'rm -f "$tmp" "$body_file"' EXIT

# ── GET-before-POST: dedupe on the MR URL (natural key) ──────────────────────
# Route: GET /cards/{id}/actions?filter=commentCard — NOT /actions/comments
# (unrouted: 404 "Cannot GET" confirmed by live probe 2026-10-21). limit=1000
# keeps the dedupe window deterministic on heavily-commented cards.
http_code="$(printf 'url = "%s/cards/%s/actions?key=%s&token=%s&filter=commentCard&fields=data&limit=1000"\n' \
  "$TRELLO_API_BASE" "$short_link" "$key" "$token" |
  curl -sS -K - -o "$tmp" -w '%{http_code}' 2>/dev/null)" || _tc_fail "network error on GET comments"
if [[ "$http_code" != "200" ]]; then
  _tc_fail "GET comments returned HTTP ${http_code} (check TRELLO_API_KEY/TRELLO_TOKEN validity and card access)"
fi
# Boundary match: the MR URL must appear as a whole (not as a prefix of a
# longer MR number — MR 6 commented must not satisfy a MR 603 lookup).
mr_url_escaped="$(printf '%s' "$mr_url" | sed -e 's/[][\.*^$()+?{}|]/\\&/g')"
if grep -qE -- "${mr_url_escaped}([^0-9]|$)" "$tmp"; then
  _tc_emit already
  exit 0
fi

# ── POST the comment (body via @file: newline-safe, urlencoded) ──────────────
printf '%s' "$body" > "$body_file"
http_code="$(printf 'request = "POST"\nurl = "%s/cards/%s/actions/comments"\ndata-urlencode = "key=%s"\ndata-urlencode = "token=%s"\ndata-urlencode = "text@%s"\n' \
  "$TRELLO_API_BASE" "$short_link" "$key" "$token" "$body_file" |
  curl -sS -K - -o "$tmp" -w '%{http_code}' 2>/dev/null)" || _tc_fail "network error on POST comment"
if [[ "$http_code" != "200" ]]; then
  _tc_fail "POST comment returned HTTP ${http_code} ($(head -c 200 "$tmp" | tr -d '\n'))"
fi
# First 24-hex id in the action object = the comment id — memberCreator.id
# (also 24-hex, later in the payload) must NOT be captured: sed -n '1p' reads
# the whole stream, no SIGPIPE under pipefail.
comment_id="$(grep -o '"id":"[0-9a-fA-F]\{24\}' "$tmp" | sed -n '1p' | cut -d'"' -f4)"
_tc_emit posted "$comment_id"
exit 0
