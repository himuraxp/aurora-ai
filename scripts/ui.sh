#!/usr/bin/env bash
# ui.sh — Aurora UI library for console scripts
#
# Shared animations, colors, and styling for setup.sh and install.sh.
# 100% bash, zero external dependencies.
# Compatible macOS (bash 3.2+) and Linux (bash 4+).
#
# Usage:
#   source "$(dirname "${BASH_SOURCE[0]}")/ui.sh"
#   ui_logo
#   ui_section "System Check"
#   ui_info "Checking prerequisites..."
#   ui_run "Installing opencode-ai" npm install -g opencode-ai
#   ui_ok "Done"

# ─── Initialization ────────────────────────────────────────────────────────────

# Disable animations if not a TTY or if --no-animation was passed
if [[ ! -t 1 ]] || [[ "${UI_NO_ANIMATION:-false}" == true ]]; then
  UI_ANIMATE=false
else
  UI_ANIMATE=true
fi

# Terminal width (fallback to 80)
UI_TERM_WIDTH=80
if [[ -t 1 ]]; then
  UI_TERM_WIDTH=$(tput cols 2>/dev/null || echo 80)
fi

# ─── Color palette (256 ANSI) ────────────────────────────────────────────────

if [[ -t 1 ]]; then
  C_PRIMARY=51       # Aurora Blue (turquoise bright)
  C_SECONDARY=129    # Purple
  C_ACCENT=45        # Light Blue
  C_TEXT=250         # Light Gray
  C_DIM=240          # Dim Gray
  C_HEADER=220       # Gold
  C_INFO=45          # Cyan
  C_OK=46            # Green
  C_FAIL=196         # Red
  C_WARN=226         # Yellow
  C_PROGRESS_BG=240  # Dim Gray
  C_PROGRESS_FILL=87 # Turquoise
  C_SPINNER=201      # Bright Purple
  ANSI_RESET="\033[0m"
  ANSI_BOLD="\033[1m"
  ANSI_DIM="\033[2m"
else
  C_PRIMARY=""
  C_SECONDARY=""
  C_ACCENT=""
  C_TEXT=""
  C_DIM=""
  C_HEADER=""
  C_INFO=""
  C_OK=""
  C_FAIL=""
  C_WARN=""
  C_PROGRESS_BG=""
  C_PROGRESS_FILL=""
  C_SPINNER=""
  ANSI_RESET=""
  ANSI_BOLD=""
  ANSI_DIM=""
fi

# ─── Helpers ─────────────────────────────────────────────────────────────────

# Safe fractional sleep (works even if system sleep doesn't support decimals)
_ui_delay() {
  sleep "$1" 2>/dev/null || true
}

# Repeat a character N times
_ui_repeat() {
  local char="$1"
  local n="$2"
  local result=""
  local i=0
  while [[ $i -lt $n ]]; do
    result+="$char"
    i=$((i + 1))
  done
  printf '%s' "$result"
}

# ─── Logo ────────────────────────────────────────────────────────────────────

AURORA_LOGO=(
  "      .o.                                                         "
  "     .888.                                                        "
  '    .8"888.     oooo  oooo  oooo d8b  .ooooo.  oooo d8b  .oooo.   '
  "   .8' \`888.    \`888  \`888  \`888\"\"8P d88' \`88b \`888\"\"8P \`P  )88b  "
  '  .88ooo8888.    888   888   888     888   888  888      .oP"888  '
  " .8'     \`888.   888   888   888     888   888  888     d8(  888  "
  'o88o     o8888o  `V88V"V8P'"'"' d888b    `Y8bod8P'"'"' d888b    `Y888""8o '
)

ui_logo() {
  local logo_width=61

  if [[ "$UI_ANIMATE" == true ]]; then
    # Fade-in: dim lines appear first, then light up to full color
    local dim_colors=(238 242 246 248 250 251 252)
    for i in 0 1 2 3 4 5 6; do
      printf "\033[38;5;%dm%s\033[0m\n" "${dim_colors[$i]}" "${AURORA_LOGO[$i]}"
      _ui_delay 0.06
    done
    # Redraw at full color
    printf "\033[7A"
    for i in 0 1 2 3 4 5 6; do
      printf "\033[38;5;%dm%s\033[0m\n" "$C_PRIMARY" "${AURORA_LOGO[$i]}"
    done
  else
    for i in 0 1 2 3 4 5 6; do
      if [[ -n "$C_PRIMARY" ]]; then
        printf "\033[38;5;%dm%s\033[0m\n" "$C_PRIMARY" "${AURORA_LOGO[$i]}"
      else
        printf '%s\n' "${AURORA_LOGO[$i]}"
      fi
    done
  fi

  # Blank lines for spacing before next output
  printf '\n\n'
}

# ─── Section headers ──────────────────────────────────────────────────────────

ui_section() {
  local title="$1"
  local width="${2:-60}"
  [[ $width -gt $UI_TERM_WIDTH ]] && width=$UI_TERM_WIDTH
  [[ $width -lt 20 ]] && width=20

  # Clear any active progress bar on the current line (TTY only)
  if [[ -t 1 ]]; then
    printf '\r\033[K'
  fi

  local inner=$((width - 2))
  local display_title="--- $title ---"
  local title_len=${#display_title}
  local pad_total=$((inner - title_len))
  [[ $pad_total -lt 0 ]] && pad_total=0
  local pad_left=$((pad_total / 2))
  local pad_right=$((pad_total - pad_left))

  local border=$(_ui_repeat "─" "$inner")
  local pad_l=$(_ui_repeat " " "$pad_left")
  local pad_r=$(_ui_repeat " " "$pad_right")

  printf '\n'
  if [[ -n "$C_DIM" ]]; then
    printf "\033[38;5;%dm╭%s╮\033[0m\n" "$C_DIM" "$border"
    printf "\033[38;5;%dm│\033[0m%s\033[38;5;%dm%s\033[0m%s\033[38;5;%dm│\033[0m\n" \
      "$C_DIM" "$pad_l" "$C_HEADER" "$display_title" "$pad_r" "$C_DIM"
    printf "\033[38;5;%dm╰%s╯\033[0m\n\n" "$C_DIM" "$border"
  else
    printf '╭%s╮\n' "$border"
    printf '│%s%s%s│\n' "$pad_l" "$display_title" "$pad_r"
    printf '╰%s╯\n\n' "$border"
  fi
}

ui_divider() {
  local width="${1:-50}"
  [[ $width -gt $UI_TERM_WIDTH ]] && width=$UI_TERM_WIDTH
  local line=$(_ui_repeat "─" "$width")
  if [[ -n "$C_DIM" ]]; then
    printf '\n\033[38;5;%dm%s\033[0m\n\n' "$C_DIM" "$line"
  else
    printf '\n%s\n\n' "$line"
  fi
}

# ─── Messages ────────────────────────────────────────────────────────────────

ui_info() {
  if [[ -n "$C_INFO" ]]; then
    printf " \033[38;5;%dmℹ\033[0m \033[38;5;%dm%s\033[0m\n" "$C_INFO" "$C_TEXT" "$*"
  else
    printf '[INFO] %s\n' "$*"
  fi
}

ui_ok() {
  if [[ -n "$C_OK" ]]; then
    printf " \033[38;5;%dm✓\033[0m \033[38;5;%dm%s\033[0m\n" "$C_OK" "$C_TEXT" "$*"
  else
    printf '[OK] %s\n' "$*"
  fi
}

ui_warn() {
  if [[ -n "$C_WARN" ]]; then
    printf " \033[38;5;%dm⚠\033[0m \033[38;5;%dm%s\033[0m\n" "$C_WARN" "$C_TEXT" "$*"
  else
    printf '[WARN] %s\n' "$*"
  fi
}

ui_fail() {
  if [[ -n "$C_FAIL" ]]; then
    printf " \033[38;5;%dm✗\033[0m \033[38;5;%dm%s\033[0m\n" "$C_FAIL" "$C_TEXT" "$*"
  else
    printf '[FAIL] %s\n' "$*"
  fi
  exit 1
}

# ─── Spinner ─────────────────────────────────────────────────────────────────

_UI_SPINNER_PID=""
_UI_SPINNER_MSG=""

ui_spinner_start() {
  _UI_SPINNER_MSG="$1"
  if [[ "$UI_ANIMATE" != true ]]; then
    printf '%s... ' "$1"
    return
  fi

  local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
  local i=0
  while true; do
    printf "\r \033[38;5;%dm%s\033[0m \033[38;5;%dm%s\033[0m" \
      "$C_SPINNER" "${frames[$((i % 10))]}" "$C_TEXT" "$_UI_SPINNER_MSG"
    _ui_delay 0.1
    i=$((i + 1))
  done &
  _UI_SPINNER_PID=$!
}

ui_spinner_stop() {
  local exit_code="${1:-0}"
  local msg="${2:-$_UI_SPINNER_MSG}"

  if [[ "$UI_ANIMATE" != true ]]; then
    if [[ $exit_code -eq 0 ]]; then
      printf 'OK\n'
    else
      printf 'FAILED\n'
    fi
    return "$exit_code"
  fi

  if [[ -n "$_UI_SPINNER_PID" ]]; then
    kill "$_UI_SPINNER_PID" 2>/dev/null
    wait "$_UI_SPINNER_PID" 2>/dev/null
    _UI_SPINNER_PID=""
  fi
  printf '\r\033[K'  # Clear spinner line

  if [[ $exit_code -eq 0 ]]; then
    printf " \033[38;5;%dm✓\033[0m \033[38;5;%dm%s\033[0m\n" "$C_OK" "$C_TEXT" "$msg"
  else
    printf " \033[38;5;%dm✗\033[0m \033[38;5;%dm%s\033[0m\n" "$C_FAIL" "$C_TEXT" "$msg"
  fi
  return "$exit_code"
}

# Run a command with a spinner
# Usage: ui_run "Message..." command args...
ui_run() {
  local msg="$1"
  shift
  local log_file="/tmp/aurora-ui-${$}.log"
  local exit_code=0

  ui_spinner_start "$msg"
  "$@" > "$log_file" 2>&1 || exit_code=$?
  ui_spinner_stop "$exit_code" "$msg" || true

  if [[ $exit_code -ne 0 ]] && [[ -f "$log_file" ]]; then
    cat "$log_file" >&2
  fi
  rm -f "$log_file" 2>/dev/null || true
  return "$exit_code"
}

# ─── Progress bar (fixed-line) ────────────────────────────────────────────────
#
# When ui_progress_init is called, the progress bar is placed on a fixed line
# (typically right under the logo).  Step lines are printed below it.
# ui_progress() redraws the bar in place using cursor save/restore, so it
# never descends even as steps accumulate underneath.
#
# State variables
_UI_PROGRESS_ACTIVE=false
_UI_PROGRESS_OFFSET=0   # lines between the progress bar and the cursor

# Print the progress bar on the current line (no newline).
_ui_progress_draw() {
  local current="$1"
  local total="$2"
  local label="${3:-}"
  local bar_width=30

  printf '\r\033[K'           # clear current line

  if [[ $total -eq 0 ]]; then
    if [[ -n "$C_TEXT" ]]; then
      printf '  \033[38;5;%dm%s\033[0m' "$C_TEXT" "$label"
    else
      printf '  %s' "$label"
    fi
    return
  fi

  local filled=$(( current * bar_width / total ))
  [[ $filled -gt $bar_width ]] && filled=$bar_width
  local empty=$(( bar_width - filled ))
  local bar=$(_ui_repeat "█" "$filled")$(_ui_repeat "░" "$empty")

  if [[ -n "$C_PROGRESS_FILL" ]]; then
    printf '  \033[38;5;%dm[%s]\033[0m %d/%d \033[38;5;%dm%s\033[0m' \
      "$C_PROGRESS_FILL" "$bar" "$current" "$total" "$C_TEXT" "$label"
  else
    printf '  [%s] %d/%d %s' "$bar" "$current" "$total" "$label"
  fi
}

# Initialise the fixed-line progress bar.
ui_progress_init() {
  local total="${1:-0}"
  local label="${2:-}"
  _UI_PROGRESS_ACTIVE=true
  _UI_PROGRESS_OFFSET=1        # cursor will be 1 line below the bar
  _ui_progress_draw 0 "$total" "$label"
  printf '\n'                  # move to next line; bar stays above
}

# Redraw the progress bar in place (fixed-line mode) or inline (legacy mode).
ui_progress() {
  local current="$1"
  local total="$2"
  local label="${3:-}"

  if [[ "$_UI_PROGRESS_ACTIVE" == true && -t 1 ]]; then
    # Save cursor → move up to bar line → redraw → restore cursor
    printf '\0337'
    if [[ $_UI_PROGRESS_OFFSET -gt 0 ]]; then
      printf '\033[%dA' "$_UI_PROGRESS_OFFSET"
    fi
    _ui_progress_draw "$current" "$total" "$label"
    printf '\0338'
  else
    _ui_progress_draw "$current" "$total" "$label"
    if [[ $current -eq $total ]]; then
      printf '\n'
    fi
  fi
}

# Finalise the progress bar (add a blank line after the last step).
ui_progress_finish() {
  _UI_PROGRESS_ACTIVE=false
  _UI_PROGRESS_OFFSET=0
  printf '\n'
}

# Clear the progress bar line (call before displaying a new section)
ui_progress_clear() {
  printf '\r\033[K'
}

# ─── Step status (one line per step) ──────────────────────────────────────────
#
# Each step prints on its own line below the progress bar.  When the step
# finishes, the line is updated in place with the appropriate icon.
#
# Icons:
#   →  in progress   (dim)
#   ✓  done          (green)
#   ⚠  warning       (yellow)
#   ✗  failure       (red)
#   ⊘  skipped       (dim)
#   ℹ  info          (cyan)

_ui_step_print() {
  local icon="$1"
  local color="$2"
  local label="$3"
  if [[ -n "$color" ]]; then
    printf ' \033[38;5;%dm%s\033[0m \033[38;5;%dm%s\033[0m\n' "$color" "$icon" "$C_TEXT" "$label"
  else
    printf ' %s %s\n' "$icon" "$label"
  fi
}

# Update the current step line in place (TTY + fixed progress bar only).
_ui_step_update() {
  local icon="$1"
  local color="$2"
  local label="$3"
  if [[ -t 1 ]]; then
    printf '\033[1A\033[K'   # up 1, clear line
  else
    printf '\r\033[K'        # clear current line
  fi
  _ui_step_print "$icon" "$color" "$label"
}

ui_step_start() {
  local label="$1"
  if [[ -t 1 ]]; then
    # TTY — print start line, will update in place
    _ui_step_print "→" "$C_DIM" "$label"
    _UI_PROGRESS_OFFSET=$((_UI_PROGRESS_OFFSET + 1))
  else
    # Non-TTY — compact format
    printf '%s... ' "$label"
  fi
}

ui_step_done() {
  local label="$1"
  if [[ -t 1 ]]; then
    _ui_step_update "✓" "$C_OK" "$label"
  else
    printf 'OK\n'
  fi
}

ui_step_warn() {
  local label="$1"
  if [[ -t 1 ]]; then
    _ui_step_update "⚠" "$C_WARN" "$label"
  else
    printf 'WARN\n'
  fi
}

ui_step_fail() {
  local label="$1"
  if [[ -t 1 ]]; then
    _ui_step_update "✗" "$C_FAIL" "$label"
  else
    printf 'FAIL\n'
  fi
}

ui_step_skip() {
  local label="$1"
  if [[ -t 1 ]]; then
    _ui_step_update "⊘" "$C_DIM" "$label"
  else
    printf 'SKIP\n'
  fi
}

ui_step_info() {
  local label="$1"
  if [[ -t 1 ]]; then
    _ui_step_update "ℹ" "$C_INFO" "$label"
  else
    printf 'INFO\n'
  fi
}

# ─── Typewriter ──────────────────────────────────────────────────────────────

ui_typewriter() {
  local text="$1"
  local speed="${2:-0.03}"
  local i=0
  local len=${#text}

  while [[ $i -lt $len ]]; do
    local char="${text:$i:1}"
    if [[ -n "$C_TEXT" ]]; then
      printf '\033[38;5;%dm%s\033[0m' "$C_TEXT" "$char"
    else
      printf '%s' "$char"
    fi
    _ui_delay "$speed"
    i=$((i + 1))
  done
  printf '\n'
}

# ─── Cleanup ─────────────────────────────────────────────────────────────────

# Kill any orphaned spinner on exit
_ui_cleanup() {
  if [[ -n "$_UI_SPINNER_PID" ]]; then
    kill "$_UI_SPINNER_PID" 2>/dev/null
    wait "$_UI_SPINNER_PID" 2>/dev/null
    _UI_SPINNER_PID=""
  fi
}
trap _ui_cleanup EXIT

# ─── Backward-compatible aliases ─────────────────────────────────────────────
# These allow setup.sh and install.sh to use existing info/ok/warn/fail calls
# without modification, but with improved styling.

info() { ui_info "$@"; }
ok()   { ui_ok "$@"; }
warn() { ui_warn "$@"; }
fail() { ui_fail "$@"; }
