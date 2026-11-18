#!/usr/bin/env bash
set -euo pipefail

# Cancel-message colors (ui.sh exposes a different palette; these are the only
# two the inline cancel handlers need — previously referenced but never defined,
# so set -u turned every cancellation into an unbound-variable crash).
RED='\033[0;31m'
NC='\033[0m'

# Read a secret: masked only when stdin is a real terminal (read -s misbehaves
# when stdin is a pipe/closed by a wrapper such as npm).
read_secret() {
  if [[ -t 0 ]]; then
    read -rs "$1"
  else
    read -r "$1"
  fi
}

# setup.sh — First-time installation or update of opencode-config on a machine.
#
# This script:
#   1. Checks prerequisites (Node.js, npm)
#   2. Installs or updates external dependencies (opencode-ai, rtk)
#   3. Optionally installs MCP servers (chrome-devtools, ios-simulator)
#   4. Runs install.sh (agents, standards, frameworks, config files)
#   5. Installs npm dependencies for plugins
#   6. Collects environment variables interactively (skips if already configured)
#   7. Writes ~/.config/opencode/.env + managed export block in the user's shell rc
#   8. Runs a final verification

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_BASE="${HOME}/.config/opencode"
ENV_FILE="${TARGET_BASE}/.env"
# Legacy secret file ({file:} era) — cleaned up automatically by this script
OVERLAY_DIR="${AURORA_PERSONAL_DIR:-$HOME/dev/aurora-personal}"
# The private overlay may declare the shell-rc variable holding the LLM
# provider API key (single copy in the managed block written below).
LLM_KEY_VAR=""
if [[ -f "$OVERLAY_DIR/config/llm-key-var.txt" ]]; then
  LLM_KEY_VAR="$(head -1 "$OVERLAY_DIR/config/llm-key-var.txt" | tr -d '[:space:]')"
fi
if [[ -n "$LLM_KEY_VAR" && ! "$LLM_KEY_VAR" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "setup.sh: invalid LLM key variable name in overlay llm-key-var.txt — ignoring" >&2
  LLM_KEY_VAR=""
fi
FORCE_ENV=false
IDB_VENV="${HOME}/.local/idb-venv"

# Source the Aurora UI library
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/ui.sh"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--force] [--no-animation]

Options:
  --force         Re-collect environment variables even if .env is complete.
  --no-animation   Disable animations (for CI/SSH non-interactive sessions).
  --help          Show this help.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --force)
      FORCE_ENV=true
      ;;
    --no-animation)
      UI_NO_ANIMATION=true
      UI_ANIMATE=false
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# ─── Step 1: Prerequisites ───────────────────────────────────────────────────

ui_logo

ui_section "System Check"

ui_info "Checking prerequisites..."

if ! command -v node &>/dev/null; then
  fail "Node.js not found. Install it first: https://nodejs.org/ (or use nvm)"
fi

if ! command -v npm &>/dev/null; then
  fail "npm not found. Install Node.js first."
fi

NODE_VERSION=$(node -v | sed 's/v//')
NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
ok "Node.js ${NODE_VERSION}"
ok "npm $(npm -v)"

if [[ "$NODE_MAJOR" -lt 18 ]]; then
  warn "Node.js 18+ is recommended. Current: ${NODE_VERSION}"
fi

# ─── Step 2: External dependencies ───────────────────────────────────────────

ui_section "External Dependencies"

# opencode-ai (global npm)
if command -v opencode &>/dev/null; then
  CURRENT_VER=$(opencode --version 2>/dev/null || echo "unknown")
  LATEST_VER=$(npm view opencode-ai version 2>/dev/null || echo "")
  if [[ -n "$LATEST_VER" && "$CURRENT_VER" != "$LATEST_VER" ]]; then
    warn "opencode-ai: ${CURRENT_VER} installed, ${LATEST_VER} available"
    printf "Update now? [Y/n] "
    read -r response || response="n"
    if [[ "$response" =~ ^[Yy]?$ ]]; then
      npm install -g opencode-ai
      ok "opencode-ai updated to ${LATEST_VER}"
    else
      ok "opencode-ai kept at ${CURRENT_VER}"
    fi
  else
    ok "opencode-ai up to date: ${CURRENT_VER}"
  fi
else
  # Pinned to the validated runtime (Security Gate 2026-10-07, S-07):
  # supply chain — never install an unverified latest. Bump deliberately
  # after a real smoke test (see skills/release-smoke-test), keep in sync
  # with the version referenced in aurora-core ADRs.
  TESTED_OPENCODE_VER="1.18.35"
  info "Installing opencode-ai@${TESTED_OPENCODE_VER} (validated version)..."
  npm install -g "opencode-ai@${TESTED_OPENCODE_VER}"
  ok "opencode-ai installed: $(opencode --version 2>/dev/null || echo 'unknown')"
fi

# rtk (Homebrew on macOS, manual on Linux)
if command -v rtk &>/dev/null; then
  CURRENT_VER=$(rtk --version 2>/dev/null || echo "unknown")
  if [[ "$(uname)" == "Darwin" ]] && command -v brew &>/dev/null; then
    if [[ "$(uname -m)" == "x86_64" ]]; then
      # Homebrew has no bottles for Intel and builds rtk from source — the build
      # always fails on this platform (clang: unsupported -march=westmere).
      # Never prompt: the brew failure would abort the whole setup (set -e).
      ok "rtk installed: ${CURRENT_VER} (update skipped: macOS Intel — Homebrew builds from source, unsupported)"
    elif brew outdated | grep -q "^rtk"; then
      warn "rtk: ${CURRENT_VER} installed, update available"
      printf "Update now? [Y/n] "
      read -r response || response="n"
      if [[ "$response" =~ ^[Yy]?$ ]]; then
        if brew upgrade rtk; then
          ok "rtk updated to $(rtk --version 2>/dev/null || echo 'unknown')"
        else
          warn "rtk update failed (kept at ${CURRENT_VER}) — non-blocking, continuing setup"
        fi
      else
        ok "rtk kept at ${CURRENT_VER}"
      fi
    else
      ok "rtk up to date: ${CURRENT_VER}"
    fi
  else
    ok "rtk installed: ${CURRENT_VER} (manual update)"
  fi
else
  if [[ "$(uname)" == "Darwin" ]]; then
    if command -v brew &>/dev/null; then
      info "Installing rtk via Homebrew..."
      if brew install rtk; then
        ok "rtk installed: $(rtk --version 2>/dev/null || echo 'unknown')"
      else
        warn "rtk install failed — non-blocking, continuing setup (install manually: https://github.com/nicholasgriffintn/rtk)"
      fi
    else
      warn "Homebrew not found. Install rtk manually: https://github.com/nicholasgriffintn/rtk"
    fi
  else
    warn "rtk not found. Install it manually: https://github.com/nicholasgriffintn/rtk"
    warn "On macOS: brew install rtk"
  fi
fi

# ─── Step 2.5: MCP Servers ──────────────────────────────────────────────────

ui_section "MCP Servers"

# chrome-devtools-mcp: auto-installed by npx, no manual setup needed
if npm list -g chrome-devtools-mcp &>/dev/null; then
  ok "chrome-devtools-mcp installed globally"
else
  ok "chrome-devtools-mcp: will auto-install via npx on first use"
fi

# ios-simulator-mcp: requires idb-companion (brew) + fb-idb (python venv) + UDID
# Detect if already installed
IOS_MCP_READY=false
if command -v idb_companion &>/dev/null && [[ -f "${IDB_VENV}/bin/idb" ]]; then
  IOS_MCP_READY=true
  ok "ios-simulator-mcp dependencies already installed (idb-companion + fb-idb)"
fi

if [[ "$IOS_MCP_READY" == false ]]; then
  if [[ "$(uname)" == "Darwin" ]]; then
    echo ""
    echo "The iOS Simulator MCP requires:"
    echo "  - idb-companion (Homebrew: facebook/fb tap)"
    echo "  - fb-idb (Python venv at ${IDB_VENV})"
    echo "  - Xcode (for iOS Simulator)"
    printf "Install iOS Simulator MCP dependencies? [y/N] "
    read -r install_ios_mcp || install_ios_mcp="n"

    if [[ "$install_ios_mcp" =~ ^[Yy]$ ]]; then
      # Check Xcode
      if ! xcrun simctl help &>/dev/null; then
        warn "Xcode or Command Line Tools not found."
        warn "Install Xcode from the App Store, then re-run setup.sh"
      else
        # Install idb-companion via Homebrew
        if command -v brew &>/dev/null; then
          if ! brew tap | grep -q "facebook/fb"; then
            info "Tapping facebook/fb..."
            brew tap facebook/fb
          fi
          if command -v idb_companion &>/dev/null; then
            ok "idb-companion already installed: $(idb_companion --version 2>/dev/null || echo 'unknown')"
          else
            info "Installing idb-companion..."
            brew install idb-companion
            ok "idb-companion installed"
          fi
        else
          warn "Homebrew not found — cannot install idb-companion automatically"
          warn "Install manually: brew tap facebook/fb && brew install idb-companion"
        fi

        # Install fb-idb via Python venv
        if command -v python3 &>/dev/null; then
          if [[ -f "${IDB_VENV}/bin/idb" ]]; then
            ok "fb-idb already installed in ${IDB_VENV}"
          else
            info "Creating Python venv at ${IDB_VENV}..."
            python3 -m venv "${IDB_VENV}"
            info "Installing fb-idb..."
            "${IDB_VENV}/bin/pip" install --quiet fb-idb
            ok "fb-idb installed in ${IDB_VENV}"
          fi
        else
          warn "python3 not found — cannot create venv for fb-idb"
          warn "Install manually: python3 -m venv ${IDB_VENV} && ${IDB_VENV}/bin/pip install fb-idb"
        fi
      fi

      # Verify
      if command -v idb_companion &>/dev/null && [[ -f "${IDB_VENV}/bin/idb" ]]; then
        IOS_MCP_READY=true
        ok "iOS Simulator MCP dependencies installed successfully"
      else
        warn "iOS Simulator MCP setup incomplete — check warnings above"
      fi
    else
      info "Skipping iOS Simulator MCP. You can install it later with: setup.sh"
      info "The ios-simulator MCP config will remain in opencode.json but may fail at runtime."
    fi
  else
    info "iOS Simulator MCP is only available on macOS — skipping"
    info "The ios-simulator MCP config will remain in opencode.json but is disabled on non-macOS."
  fi
fi

ui_section "Installing configuration files"

info "Running install.sh..."
if [[ -d "$TARGET_BASE" ]]; then
  # Existing installation: the freshness guard applies normally.
  bash "${ROOT_DIR}/scripts/install.sh" || fail "install.sh failed"
else
  # First deployment: the guard needs network; an offline first install is a
  # legitimate, explicit context — announced as UNVERIFIED, never as a pass.
  info "Premier déploiement (aucune config existante) — vérification de fraîcheur sautée"
  bash "${ROOT_DIR}/scripts/install.sh" --skip-freshness-check || fail "install.sh failed"
fi

# ─── Step 4: npm dependencies for plugins ────────────────────────────────────

ui_section "Plugin Dependencies"

if [[ -f "${TARGET_BASE}/package.json" ]]; then
  info "Installing npm dependencies in ${TARGET_BASE}..."
  if ! (cd "${TARGET_BASE}" && npm install); then
    warn "npm install failed — plugins may not work until resolved"
    warn "You can retry manually: cd ${TARGET_BASE} && npm install"
  else
    ok "npm dependencies installed"
  fi
else
  warn "No package.json found in ${TARGET_BASE} — skipping npm install"
fi

# ─── Step 4.5: Build MCP servers (public + private overlay) ─────────────────

ui_section "MCP Servers"

for mcp_root in "$ROOT_DIR/mcp" "$OVERLAY_DIR/mcp"; do
  [[ -d "$mcp_root" ]] || continue
  for pkg in "$mcp_root"/*/package.json; do
    [[ -f "$pkg" ]] || continue
    mcp_dir="$(dirname "$pkg")"
    mcp_name="$(basename "$mcp_dir")"
    if [[ -f "$mcp_dir/dist/index.js" || -f "$mcp_dir/dist/index.mjs" ]]; then
      ok "MCP $mcp_name already built"
    elif grep -q '"build"[[:space:]]*:' "$pkg"; then
      info "Building MCP $mcp_name..."
      if (cd "$mcp_dir" && npm install --silent && npm run build); then
        ok "MCP $mcp_name built successfully"
      else
        warn "MCP $mcp_name build failed — it will not be available"
        warn "You can retry manually: cd $mcp_dir && npm install && npm run build"
      fi
    else
      info "MCP $mcp_name has no build script — skipping"
    fi
  done
done

# ─── Step 5: Environment variables ───────────────────────────────────────────

# The LLM provider key (when the private overlay declares LLM_KEY_VAR) has a
# SINGLE copy: an export line in the user's shell rc (managed block written by
# this script). Provider configs read it via {env:...} because OpenCode never
# loads .env files into its process environment.

# Detect the user's shell rc (empty for unsupported shells — manual instructions)
detect_shell_rc() {
  case "${SHELL##*/}" in
    zsh)  echo "$HOME/.zshrc" ;;
    bash)
      if [[ "$(uname)" == "Darwin" ]]; then
        echo "$HOME/.bash_profile"
      else
        echo "$HOME/.bashrc"
      fi
      ;;
    *)    echo "" ;;
  esac
}

SHELL_RC="$(detect_shell_rc)"
MANAGED_BLOCK_BEGIN="# >>> opencode-config (managed by setup.sh) >>>"
MANAGED_BLOCK_END="# <<< opencode-config (managed by setup.sh) <<<"

# Extract the current literal value of a managed export line (last one wins).
# Used for the LLM key (variable declared by the private overlay), IDB_UDID and
# IDB_PATH (all exported in the managed block — see write_shell_block).
rc_var_value() {
  local var="$1"
  [[ -n "$SHELL_RC" && -f "$SHELL_RC" ]] || return 0
  sed -nE "s/^[[:space:]]*export[[:space:]]+${var}=(.+)/\1/p" "$SHELL_RC" 2>/dev/null \
    | tail -1 | sed -E "s/^'(.*)'$/\1/; s/^\"(.*)\"$/\1/" | tr -d '\r'
}

rc_key_value() { [[ -n "$LLM_KEY_VAR" ]] && rc_var_value "$LLM_KEY_VAR" || true; }

# Print one export line on stdout (caller redirects). A plain $VAR reference is
# preserved verbatim (resolves at runtime); a value identical to the one already
# stored in the rc is re-emitted verbatim too — the rc text is already in final
# shell form, so re-emitting it as-is prevents progressive %q double-escaping.
# Anything else is %q-escaped safely for bash and zsh.
_emit_export() {
  local var="$1" val="$2" prev="$3"
  if [[ "$val" == "$prev" || "$val" =~ ^\$[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    printf 'export %s=%s\n' "$var" "$val"
  else
    printf 'export %s=%q\n' "$var" "$val"
  fi
}

# Rewrite (or append) the managed export block in the shell rc. Idempotent.
# Also MOVES any existing free-standing export of the managed variables into
# the block, so nothing is ever duplicated: the managed block is the single
# copy of the LLM key (when the overlay declares one), IDB_UDID and IDB_PATH
# (read via {env:...}). OPENAI_API_KEY (often a stale alias of the LLM key) is
# moved into the block the same way.
write_shell_block() {
  local key_value="$1" idb_udid="${2:-}" idb_path="${3:-}"
  [[ -n "$SHELL_RC" ]] || return 1
  local tmp="${SHELL_RC}.opencode.tmp"
  local prev_key prev_udid prev_path prev_openai mode=""
  local managed_re="OPENAI_API_KEY|IDB_UDID|IDB_PATH"
  [[ -n "$LLM_KEY_VAR" ]] && managed_re="${LLM_KEY_VAR}|${managed_re}"
  prev_key="$(rc_key_value)"
  prev_openai="$(rc_var_value OPENAI_API_KEY)"
  prev_udid="$(rc_var_value IDB_UDID)"
  prev_path="$(rc_var_value IDB_PATH)"
  if [[ -f "$SHELL_RC" ]]; then
    cp -p "$SHELL_RC" "${SHELL_RC}.opencode.bak" || return 1
    mode=$(stat -f '%Lp' "$SHELL_RC" 2>/dev/null || stat -c '%a' "$SHELL_RC" 2>/dev/null || echo "")
    # Drop managed block, free-standing managed exports and trailing blank lines
    awk -v begin="$MANAGED_BLOCK_BEGIN" -v end="$MANAGED_BLOCK_END" -v vars="$managed_re" \
      'index($0, begin) == 1 { skip = 1; next }
       index($0, end) == 1   { skip = 0; next }
       skip == 1 { next }
       $0 ~ ("^[[:space:]]*export[[:space:]]+(" vars ")=") { next }
       { lines[NR] = $0 }
       END { n = NR; while (n > 0 && lines[n] ~ /^[[:space:]]*$/) n--;
             for (i = 1; i <= n; i++) print lines[i] }' \
      "$SHELL_RC" > "$tmp"
    if [[ -s "$tmp" ]]; then
      printf '\n%s\n' "$MANAGED_BLOCK_BEGIN" >> "$tmp"
    else
      printf '%s\n' "$MANAGED_BLOCK_BEGIN" > "$tmp"
    fi
  else
    printf '%s\n' "$MANAGED_BLOCK_BEGIN" > "$tmp"
  fi
  if [[ -n "$LLM_KEY_VAR" && -n "$key_value" ]]; then
    _emit_export "$LLM_KEY_VAR" "$key_value" "$prev_key" >> "$tmp"
  fi
  # move the free-standing OPENAI_API_KEY alias into the managed block
  # (Security Gate S-03: 2 copies = drift; empty = nothing to move)
  [[ -n "$prev_openai" ]] && _emit_export OPENAI_API_KEY "$prev_openai" "$prev_openai" >> "$tmp"
  [[ -n "$idb_udid" ]] && _emit_export IDB_UDID "$idb_udid" "$prev_udid" >> "$tmp"
  [[ -n "$idb_path" ]] && _emit_export IDB_PATH "$idb_path" "$prev_path" >> "$tmp"
  printf '%s\n' "$MANAGED_BLOCK_END" >> "$tmp"
  # Atomic replace, preserving the rc's original permissions (or 600 for fresh rc)
  if [[ -n "$mode" ]]; then chmod "$mode" "$tmp" 2>/dev/null; else chmod 600 "$tmp" 2>/dev/null; fi
  mv "$tmp" "$SHELL_RC"
  # Syntax check: restore the backup if the rewrite broke the rc structure
  if [[ -f "${SHELL_RC}.opencode.bak" ]] && ! "$SHELL" -n "$SHELL_RC" 2>/dev/null; then
    warn "Shell rc syntax broken after rewrite — restoring previous rc"
    mv "${SHELL_RC}.opencode.bak" "$SHELL_RC"
    return 1
  fi
  rm -f "${SHELL_RC}.opencode.bak"
}

# Environment is complete when .env exists and the LLM key (if declared) is
# exported somewhere in the shell rc
env_is_complete() {
  [[ -f "$ENV_FILE" ]] || return 1
  [[ -z "$LLM_KEY_VAR" || -n "$(rc_key_value)" ]] || return 1
  return 0
}

# ── LLM key discovery: shell rc > .env > prompt (overlay-declared only) ──────
# The rc-managed block is the source of truth: when it already exports the key,
# its value wins so Enter-keep never swaps the managed key for an older one.
# Values read from the rc are already in final shell form and are re-emitted
# verbatim by write_shell_block (no double-escaping).
LLM_KEY=""
LLM_KEY_SOURCE=""
RC_HAS_KEY=false
[[ -n "$(rc_key_value)" ]] && RC_HAS_KEY=true

if [[ -n "$LLM_KEY_VAR" ]]; then
  if [[ "$RC_HAS_KEY" == true ]]; then
    LLM_KEY="$(rc_key_value)"
    LLM_KEY_SOURCE="shell rc (${SHELL_RC})"
  elif [[ -f "$ENV_FILE" ]]; then
    LLM_KEY=$(grep "^${LLM_KEY_VAR}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
    LLM_KEY="${LLM_KEY%$'\r'}"
    [[ -n "$LLM_KEY" ]] && LLM_KEY_SOURCE="$ENV_FILE"
  fi

  if [[ -n "$LLM_KEY" ]]; then
    ok "LLM provider key found (${LLM_KEY_SOURCE})"
  elif [[ "$RC_HAS_KEY" == true ]]; then
    ok "LLM provider key already exported in ${SHELL_RC} (shell reference — kept as is)"
  else
    info "No LLM provider key found yet (checked shell rc and .env)"
  fi
else
  info "No LLM key variable declared (private overlay absent) — skipping provider key setup"
fi

if [[ "$FORCE_ENV" == false ]] && env_is_complete; then
  ui_section "Environment Configuration"
  ok "Environment already configured (shell rc managed block in place)."
  ok "Use --force to reconfigure environment variables."
  info "Skipping environment configuration."
else
  ui_section "Environment Configuration"
  if [[ "$FORCE_ENV" == true && -f "$ENV_FILE" ]]; then
    warn "Reconfiguring environment (--force)"
  fi
  echo "You will now be asked for your configuration values."
  echo "Secrets will be stored in ${ENV_FILE} (never committed to git)."
  echo "Press Enter to keep existing/current values."
  echo ""

  # Function: prompt with default, store in variable
  # Usage: prompt_var VAR_NAME "Prompt text" "default value" true|false (is_secret)
  prompt_var() {
    local var_name="$1"
    local prompt_text="$2"
    local default_val="$3"
    local is_secret="$4"

    local current=""
    # Check if value already exists in .env
    if [[ -f "${ENV_FILE}" ]]; then
      current=$(grep "^${var_name}=" "${ENV_FILE}" 2>/dev/null | cut -d'=' -f2- || echo "")
    fi

    local display_default="${default_val}"
    if [[ -n "${current}" ]]; then
      display_default="${current}"
    fi

    local prompt_display="${prompt_text}"
    if [[ -n "${display_default}" ]]; then
      if [[ "${is_secret}" == "true" && -n "${current}" ]]; then
        prompt_display="${prompt_text} [current: ******]"
      else
        prompt_display="${prompt_text} [default: ${display_default}]"
      fi
    fi

    printf "%s: " "${prompt_display}"
    if [[ "${is_secret}" == "true" ]]; then
      read_secret input_value || { echo -e "\n${RED}Cancelled.${NC}"; exit 1; }
      echo ""
    else
      read -r input_value || { echo -e "\n${RED}Cancelled.${NC}"; exit 1; }
    fi

    # Use default/current if user pressed Enter
    if [[ -z "${input_value}" ]]; then
      if [[ -n "${current}" ]]; then
        printf -v "${var_name}" '%s' "${current}"
      else
        printf -v "${var_name}" '%s' "${display_default}"
      fi
    else
      printf -v "${var_name}" '%s' "${input_value}"
    fi
  }

  # --- Required variables ---

  # IDB values are exported in the managed shell rc block (read by opencode.json
  # via {env:IDB_*}; the ios-simulator MCP has no .env fallback). Seed from the
  # rc first, then from an old .env, so a re-run keeps existing values on Enter.
  IDB_UDID=""
  IDB_PATH=""
  IDB_UDID="$(rc_var_value IDB_UDID)"
  IDB_PATH="$(rc_var_value IDB_PATH)"
  if [[ -z "$IDB_UDID" || -z "$IDB_PATH" ]]; then
    if [[ -f "$ENV_FILE" ]]; then
      [[ -z "$IDB_UDID" ]] && IDB_UDID="$(grep '^IDB_UDID=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | head -1 | sed 's/\r$//')"
      [[ -z "$IDB_PATH" ]] && IDB_PATH="$(grep '^IDB_PATH=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | head -1 | sed 's/\r$//')"
    fi
  fi

  if [[ -n "$LLM_KEY_VAR" ]]; then
    # The LLM provider key has a single copy: the managed export block in the
    # shell rc. Seed from earlier discovery (rc > .env); an old OPENAI_API_KEY
    # line in .env is migrated here as well.
    if [[ -z "$LLM_KEY" && -f "$ENV_FILE" ]]; then
      LEGACY_OPENAI_KEY=$(grep '^OPENAI_API_KEY=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
      LEGACY_OPENAI_KEY="${LEGACY_OPENAI_KEY%$'\r'}"
      if [[ -n "$LEGACY_OPENAI_KEY" ]]; then
        LLM_KEY="$LEGACY_OPENAI_KEY"
        LLM_KEY_SOURCE="legacy OPENAI_API_KEY line in .env"
        warn "Migrating legacy OPENAI_API_KEY (.env) → shell rc export (value hidden)"
      fi
    fi

    if [[ -n "$LLM_KEY" ]]; then
      printf "%s: " "Enter your LLM provider API key (${LLM_KEY_VAR}) [Enter to keep current]"
    elif [[ "$RC_HAS_KEY" == true ]]; then
      printf "%s: " "Enter your LLM provider API key (${LLM_KEY_VAR}) [Enter to keep existing shell export]"
    else
      printf "%s: " "Enter your LLM provider API key (${LLM_KEY_VAR})"
    fi
    read_secret KEY_INPUT || { echo -e "\n${RED}Cancelled.${NC}"; exit 1; }
    echo ""
    if [[ -n "$KEY_INPUT" ]]; then
      LLM_KEY="$KEY_INPUT"
    elif [[ -z "$LLM_KEY" && "$RC_HAS_KEY" == true ]]; then
      LLM_KEY="$(rc_key_value)"
    fi

    if [[ -z "$LLM_KEY" ]]; then
      fail "The LLM provider API key (${LLM_KEY_VAR}) is required while the overlay declares it. See the overlay's env documentation."
    fi
  fi

  # --- Optional variables ---

  # iOS Simulator — only ask if MCP dependencies are installed
  if [[ "$IOS_MCP_READY" == true ]]; then
    if [[ "$(uname)" == "Darwin" ]]; then
      AUTO_UDID=$(xcrun simctl list devices available 2>/dev/null | grep -m1 "Booted\|(" | grep -o '[0-9A-F-]\{36\}' | head -1)
      if [[ -z "${AUTO_UDID}" ]]; then
        AUTO_UDID=$(xcrun simctl list devices available 2>/dev/null | grep -o '[0-9A-F-]\{36\}' | head -1)
      fi
      prompt_var IDB_UDID \
        "Enter iOS Simulator UDID (auto-detected, press Enter to skip)" \
        "${IDB_UDID:-${AUTO_UDID}}" false
    else
      prompt_var IDB_UDID \
        "Enter iOS Simulator UDID (skip if not on macOS)" "${IDB_UDID}" false
    fi

    prompt_var IDB_PATH \
      "Enter PATH for idb binaries" \
      "${IDB_PATH:-${IDB_VENV}/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}" false
  else
    info "Skipping iOS Simulator variables (MCP not installed)"
    IDB_UDID=""
    IDB_PATH=""
  fi

  # ─── Step 6: Write .env file ─────────────────────────────────────────────────

  ui_section "Writing environment file"

  # Expand $HOME in IDB_PATH (safe: only $HOME is expanded, no arbitrary eval)
  IDB_PATH_EXPANDED="${IDB_PATH/\$HOME/${HOME}}"

  # Preserve user-managed variables not collected by setup.sh (e.g. GITLAB_TOKEN,
  # FIGMA_TOKEN, provider tokens): keep non-empty KEY=VALUE lines whose key is
  # not written by the heredoc below, so a re-run never loses custom secrets.
  # OPENAI_API_KEY / LLM key (overlay-declared) / IDB_* lines are dropped on
  # purpose: those values now live in the shell rc (single copy), never in .env.
  MANAGED_KEYS_PATTERN='^(OPENAI_API_KEY|IDB_UDID|IDB_PATH)='
  [[ -n "$LLM_KEY_VAR" ]] && MANAGED_KEYS_PATTERN="^(OPENAI_API_KEY|${LLM_KEY_VAR}|IDB_UDID|IDB_PATH)="
  EXTRA_ENV_LINES=""
  if [[ -f "$ENV_FILE" ]]; then
    EXTRA_ENV_LINES=$(
      grep -vE '^[[:space:]]*(#|$)' "$ENV_FILE" 2>/dev/null \
        | grep -E '^[A-Za-z_][A-Za-z0-9_]*=.+' \
        | grep -vE "$MANAGED_KEYS_PATTERN" || true
    )
    if [[ -n "$EXTRA_ENV_LINES" ]]; then
      EXTRA_ENV_KEYS=$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' <<<"$EXTRA_ENV_LINES" | sed 's/=$//' | tr '\n' ' ')
      info "Preserving user-managed variables: ${EXTRA_ENV_KEYS%% }"
    fi
  fi

  cat > "${ENV_FILE}" <<EOF
# OpenCode environment variables — generated by setup.sh
# DO NOT commit this file. It contains secrets.
#
# NOTE: LLM provider keys (when declared by the private overlay) and the IDB
# values are NOT stored here. They are exported in the user's shell rc
# (${SHELL_RC:-manual}) inside the managed block: OpenCode never loads .env
# files, and {env:...} in configs only reads the process environment.
# Update with: setup.sh --force
EOF

  # Append preserved user-managed variables (kept verbatim)
  if [[ -n "$EXTRA_ENV_LINES" ]]; then
    {
      echo ""
      echo "# Preserved — managed manually (not collected by setup.sh)"
      printf '%s\n' "$EXTRA_ENV_LINES"
    } >> "$ENV_FILE"
  fi

  chmod 600 "${ENV_FILE}"
  ok "Environment file written to ${ENV_FILE} (permissions: 600)"

  # Write the managed export block in the shell rc (single copy of the LLM key
  # + IDB values read via {env:...})
  if write_shell_block "$LLM_KEY" "$IDB_UDID" "$IDB_PATH_EXPANDED"; then
    ok "Shell rc managed block written to ${SHELL_RC}"
    ok "Open a new terminal or run: source ${SHELL_RC}"
  else
    fail "Unsupported shell (${SHELL:-unknown}). Export the required variables in your shell config manually."
  fi
fi

# ─── Step 6b: Model configuration (optional, non-breaking, re-runnable) ──────

ui_section "Model Configuration"
echo "Aurora can detect which models your API keys can actually use"
echo "(real probes) and map them to agent roles — Claude, GPT, Gemini,"
echo "OpenRouter, local Ollama or a custom OpenAI-compatible provider. Existing"
echo "are preserved as-is."
echo ""
printf "Configure models now? [y/N]: "
read -r configure_models_answer || configure_models_answer=""
if [[ "$configure_models_answer" =~ ^[Yy] ]]; then
  if "$ROOT_DIR/scripts/configure-models.sh"; then
    ok "Model configuration applied"
  else
    warn "Model configuration skipped (you can re-run: scripts/configure-models.sh)"
  fi
else
  info "Skipped — run scripts/configure-models.sh anytime"
fi

# ─── Step 7: Verification ────────────────────────────────────────────────────

ui_section "Verification"

ERRORS=0

# Check installed files
check_file() {
  if [[ -f "$1" ]]; then
    ok "$2"
  else
    warn "Missing: $1"
    ERRORS=$((ERRORS + 1))
  fi
}

check_file "${TARGET_BASE}/opencode.json" "opencode.json"
check_file "${TARGET_BASE}/oh-my-opencode-slim.json" "oh-my-opencode-slim.json"
check_file "${TARGET_BASE}/package.json" "package.json (plugins)"
check_file "${TARGET_BASE}/plugins/rtk.ts" "plugins/rtk.ts"
check_file "${TARGET_BASE}/.env" ".env (secrets)"

# Check the LLM key export in the shell rc (read via {env:...})
if [[ -z "$LLM_KEY_VAR" ]]; then
  info "LLM key: no variable declared by the private overlay (skipped)"
elif [[ -n "$(rc_key_value)" ]]; then
  ok "LLM provider key exported in ${SHELL_RC} (managed block)"
else
  warn "LLM provider key NOT exported in ${SHELL_RC} — add it or re-run setup.sh"
  ERRORS=$((ERRORS + 1))
fi

# Check agents
for agent in aurora aurora-heavy reviewer tester security cybersec architect spark vision atlas crawler sage scribe pulse echo beacon designer mobile; do
  check_file "${TARGET_BASE}/agents/${agent}.md" "agents/${agent}.md"
done

# Check that opencode is available
if command -v opencode &>/dev/null; then
  ok "opencode CLI available"
else
  warn "opencode CLI not in PATH — you may need to restart your terminal"
  ERRORS=$((ERRORS + 1))
fi

# Check rtk
if command -v rtk &>/dev/null; then
  ok "rtk available"
else
  warn "rtk not in PATH — plugin will be disabled until installed"
fi

# Check MCP servers
ok "chrome-devtools-mcp: auto-installed via npx"

if [[ "$IOS_MCP_READY" == true ]]; then
  if command -v idb_companion &>/dev/null; then
    ok "ios-simulator-mcp: idb-companion available"
  else
    warn "ios-simulator-mcp: idb-companion not in PATH"
    ERRORS=$((ERRORS + 1))
  fi
  if [[ -f "${IDB_VENV}/bin/idb" ]]; then
    ok "ios-simulator-mcp: fb-idb available"
  else
    warn "ios-simulator-mcp: fb-idb not found in ${IDB_VENV}"
    ERRORS=$((ERRORS + 1))
  fi
else
  info "ios-simulator-mcp: not installed (skipped by user or non-macOS)"
fi

# Check MCP servers (sources may live in the private overlay)
for mcp_root in "$ROOT_DIR/mcp" "${AURORA_PERSONAL_DIR:-$HOME/dev/aurora-personal}/mcp"; do
  [[ -d "$mcp_root" ]] || continue
  for pkg in "$mcp_root"/*/package.json; do
    [[ -f "$pkg" ]] || continue
    mcp_dir="$(dirname "$pkg")"
    mcp_name="$(basename "$mcp_dir")"
    if [[ -f "$mcp_dir/dist/index.js" || -f "$mcp_dir/dist/index.mjs" ]]; then
      ok "mcp-$mcp_name: built and ready"
    elif grep -q '"build"[[:space:]]*:' "$pkg"; then
      warn "mcp-$mcp_name: not built — run: cd $mcp_dir && npm install && npm run build"
      ERRORS=$((ERRORS + 1))
    else
      info "mcp-$mcp_name: no build script (prebuilt expected)"
    fi
  done
done

# Duplicate-secret detection (Security Gate S-03, 2026-10-07): the same token
# value must never live in both the shell rc AND .env — guaranteed rotation
# drift. Values are compared silently (never printed).
if [[ -f "$SHELL_RC" && -f "$ENV_FILE" ]]; then
  dup_found=0
  while IFS= read -r rc_val; do
    [[ -n "$rc_val" ]] || continue
    while IFS= read -r env_val; do
      [[ -n "$env_val" ]] || continue
      if [[ "$rc_val" == "$env_val" && ${#rc_val} -ge 12 ]]; then
        warn "Duplicate secret detected: the same token value exists in both $SHELL_RC and $ENV_FILE"
        warn "  → rotate one of them and keep a single copy (S-03)"
        dup_found=$((dup_found + 1))
      fi
    done < <(grep -Eo '=(sk-|glpat-|figd_|pk\.|Bearer |gh[pu]_)[A-Za-z0-9._-]{10,}' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
  done < <(grep -Eo '=(sk-|glpat-|figd_|pk\.|Bearer |gh[pu]_)[A-Za-z0-9._-]{10,}' "$SHELL_RC" 2>/dev/null | cut -d= -f2-)
  [[ $dup_found -eq 0 ]] && ok "No duplicate secrets between shell rc and .env"
fi

# Summary
ui_section "Summary"

if [[ ${ERRORS} -eq 0 ]]; then
  ok "Setup complete! Run 'opencode' to start."
  echo ""
  echo "  Next steps:"
  echo "    1. Restart your terminal (to pick up PATH changes)"
  echo "    2. Run: opencode"
  echo "    3. The oh-my-opencode-slim plugin will auto-install on first run"
  echo ""
  echo "  To reconfigure environment variables later:"
  echo "    ~/.config/opencode-config/scripts/setup.sh --force"
  if [[ "$UI_ANIMATE" == true ]]; then
    echo ""
    ui_typewriter "Aurora is ready to deploy." 0.04
  fi
else
  warn "Setup completed with ${ERRORS} warning(s). Check the output above."
fi
