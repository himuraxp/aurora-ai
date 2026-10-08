#!/usr/bin/env bash
# ensure_glab_token.sh — Resolve a working GITLAB_TOKEN before any glab API call.
#
# Root cause this script fixes:
#   The opencode process environment is frozen at session start (inherited from
#   the launching shell, typically ~/.zshrc). If the GitLab token was rotated on
#   disk afterwards (canonical source: ~/.config/opencode/.env), every
#   conversation of the session keeps using the stale token and every glab API
#   call fails with 401 "Token is expired" — even though a fresh token exists.
#
# Behavior:
#   1. If the current environment token authenticates → do nothing, exit 0.
#   2. Otherwise, try candidate token sources on disk, in order:
#      - ~/.config/opencode/.env   (canonical token store)
#      - ~/.zshrc                  (managed block fallback)
#      The first source whose token authenticates is exported as GITLAB_TOKEN
#      (other GitLab token env vars are unset to avoid precedence surprises).
#   3. If nothing works → exit 1 with the rotation procedure. Never print secrets.
#
# Usage (sourcing is REQUIRED so the export survives in the caller's shell):
#   source "${SCRIPTS_DIR}/ensure_glab_token.sh" || exit 1
#   bash "${SCRIPTS_DIR}/create_mr.sh" ...
#
# Optional first argument: GitLab hostname (default: gitlab.infomaniak.ch).
# Optional env: ENSURE_GLAB_TOKEN_HOST overrides the default hostname.

ensure_glab_token_host="${1:-${ENSURE_GLAB_TOKEN_HOST:-gitlab.infomaniak.ch}}"

_egt_token_works() {
  glab auth status --hostname "$ensure_glab_token_host" >/dev/null 2>&1
}

_egt_extract_token() {
  # $1 = file. Prints the last GITLAB_TOKEN=... value (double-quoted or bare).
  # Values are never echoed by callers — only consumed internally.
  grep -E '^[[:space:]]*(export[[:space:]]+)?GITLAB_TOKEN=' "$1" 2>/dev/null |
    tail -1 |
    sed -E 's/^[[:space:]]*(export[[:space:]]+)?GITLAB_TOKEN=//; s/^"//; s/"[[:space:]]*$//'
}

_egt_sources=(
  "$HOME/.config/opencode/.env"
  "$HOME/.zshrc"
)

if _egt_token_works; then
  echo "OK: GITLAB_TOKEN in environment is valid for ${ensure_glab_token_host}"
  unset -f _egt_token_works _egt_extract_token 2>/dev/null
  unset _egt_sources ensure_glab_token_host 2>/dev/null
  return 0 2>/dev/null || exit 0
fi

for _egt_src in "${_egt_sources[@]}"; do
  [ -f "$_egt_src" ] || continue
  _egt_candidate="$(_egt_extract_token "$_egt_src")"
  [ -n "$_egt_candidate" ] || continue
  export GITLAB_TOKEN="$_egt_candidate"
  unset GITLAB_ACCESS_TOKEN OAUTH_TOKEN 2>/dev/null
  if _egt_token_works; then
    echo "OK: refreshed GITLAB_TOKEN from ${_egt_src} (stale process token replaced in this shell)"
    unset -f _egt_token_works _egt_extract_token 2>/dev/null
    unset _egt_candidate _egt_src _egt_sources ensure_glab_token_host 2>/dev/null
    return 0 2>/dev/null || exit 0
  fi
  unset GITLAB_TOKEN
done

_egt_failed_sources="${_egt_sources[*]}"
_egt_failed_host="$ensure_glab_token_host"
unset GITLAB_TOKEN 2>/dev/null
unset -f _egt_token_works _egt_extract_token 2>/dev/null
unset _egt_candidate _egt_src _egt_sources ensure_glab_token_host 2>/dev/null

echo "ERROR: no working GITLAB_TOKEN found (environment + ${_egt_failed_sources}) for ${_egt_failed_host}." >&2
echo "Rotate the token, update ~/.config/opencode/.env (canonical source), then mirror into ~/.zshrc." >&2
echo "Never paste the token in chat or logs." >&2
return 1 2>/dev/null || exit 1
