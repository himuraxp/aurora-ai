#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_BASE="${HOME}/.config/opencode"
PRUNE=false
DRY_RUN=false
NO_CONFIG=false

# Source the Aurora UI library
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/ui.sh"

# Counters
NEW_COUNT=0
UPDATED_COUNT=0
UNCHANGED_COUNT=0
PRUNED_COUNT=0

# Progress tracking
_UI_FILE_DONE=0
_UI_FILE_TOTAL=0
_UI_NPM_NEEDED=false

# Pre-count all files to be installed
_ui_count_files() {
  local count=0
  local f

  # agents, standards, frameworks (.md files)
  for dir in agents standards frameworks; do
    [[ -d "$ROOT_DIR/$dir" ]] || continue
    for f in "$ROOT_DIR/$dir"/*.md; do
      [[ -e "$f" ]] && count=$((count + 1))
    done
  done

  # root AGENTS.md (global OpenCode instructions)
  [[ -f "$ROOT_DIR/AGENTS.md" ]] && count=$((count + 1))

  # skills (recursive)
  if [[ -d "$ROOT_DIR/skills" ]]; then
    while IFS= read -r -d '' f; do
      count=$((count + 1))
    done < <(find "$ROOT_DIR/skills" -type f -print0)
  fi

  # scripts (recursive, excluding self)
  if [[ -d "$ROOT_DIR/scripts" ]]; then
    while IFS= read -r -d '' f; do
      count=$((count + 1))
    done < <(find "$ROOT_DIR/scripts" -type f \
      -not -name "install.sh" -not -name "setup.sh" \
      -not -name "init-project.sh" -not -name "sync-project.sh" \
      -print0)
  fi

  # config files
  for f in opencode.json oh-my-opencode-slim.json package.json .env.example; do
    [[ -f "$ROOT_DIR/config/$f" ]] && count=$((count + 1))
  done
  if [[ -d "$ROOT_DIR/config/plugins" ]]; then
    for f in "$ROOT_DIR/config/plugins"/*; do
      [[ -e "$f" ]] && count=$((count + 1))
    done
  fi

  _UI_FILE_TOTAL=$count
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [--prune] [--dry-run] [--no-config] [--no-animation]

Options:
  --prune          Remove installed .md files that no longer exist in this repo.
  --dry-run        Show what would be installed or removed.
  --no-config      Skip copying config/ files (opencode.json, plugins, etc.)
  --no-animation   Disable animations (for CI/SSH non-interactive sessions).
EOF
}

for arg in "$@"; do
  case "$arg" in
    --prune)
      PRUNE=true
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    --no-config)
      NO_CONFIG=true
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

# copy_file <src> <dest> — copies a file, tracking new/updated/unchanged
copy_file() {
  local src="$1"
  local dest="$2"

  if [[ "$DRY_RUN" == true ]]; then
    if [[ ! -f "$dest" ]]; then
      echo "  new:     $dest"
    elif ! diff -q "$src" "$dest" &>/dev/null; then
      echo "  updated: $dest"
    else
      echo "  unchanged: $dest"
    fi
    return
  fi

  if [[ ! -f "$dest" ]]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
    NEW_COUNT=$((NEW_COUNT + 1))
  elif ! diff -q "$src" "$dest" &>/dev/null; then
    cp "$src" "$dest"
    UPDATED_COUNT=$((UPDATED_COUNT + 1))
  else
    UNCHANGED_COUNT=$((UNCHANGED_COUNT + 1))
  fi

  _UI_FILE_DONE=$((_UI_FILE_DONE + 1))
  if [[ "$_UI_PROGRESS_ACTIVE" == true && $_UI_FILE_TOTAL -gt 0 ]]; then
    ui_progress "$_UI_FILE_DONE" "$_UI_FILE_TOTAL" "Installing files"
  fi
}

install_dir() {
  local src="$1"
  local dest="$2"

  if [[ ! -d "$src" ]]; then
    echo "skip (nonexistent): $src"
    return
  fi

  if [[ "$DRY_RUN" == false ]]; then
    mkdir -p "$dest"
  fi

  for file in "$src"/*.md; do
    [[ -e "$file" ]] || continue
    name="$(basename "$file")"
    # Skip README.md — documentation only, not an agent/standard/framework file
    [[ "$name" == "README.md" ]] && continue
    copy_file "$file" "$dest/$name"
  done

  if [[ "$PRUNE" == true && -d "$dest" ]]; then
    for installed in "$dest"/*.md; do
      [[ -e "$installed" ]] || continue
      name="$(basename "$installed")"
      # Don't prune README.md — it's not managed by install.sh
      [[ "$name" == "README.md" ]] && continue
      if [[ ! -e "$src/$name" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
          echo "  would prune: $installed"
        else
          rm "$installed"
          echo "  pruned:  $installed"
          PRUNED_COUNT=$((PRUNED_COUNT + 1))
        fi
      fi
    done
  elif [[ -d "$dest" ]]; then
    for installed in "$dest"/*.md; do
      [[ -e "$installed" ]] || continue
      name="$(basename "$installed")"
      if [[ ! -e "$src/$name" ]]; then
        echo "  orphan:  $installed (run with --prune to remove)"
      fi
    done
  fi
}

# ─── Skills (recursive: includes SKILL.md, README.md, and any sub-files) ────

install_skills() {
  local src="$ROOT_DIR/skills"
  local dest="$TARGET_BASE/skills"

  if [[ ! -d "$src" ]]; then
    echo "skip (nonexistent): $src"
    return 1
  fi

  if [[ "$DRY_RUN" == false ]]; then
    mkdir -p "$dest"
  fi

  # Walk each skill directory
  for skill_dir in "$src"/*/; do
    [[ -d "$skill_dir" ]] || continue
    local skill_name
    skill_name="$(basename "$skill_dir")"
    local skill_dest="$dest/$skill_name"

    if [[ "$DRY_RUN" == false ]]; then
      mkdir -p "$skill_dest"
    fi

    # Copy all files recursively (includes SKILL.md, README.md, and sub-files like scripts/)
    while IFS= read -r -d '' file; do
      local rel_path="${file#$skill_dir}"
      local dest_file="$skill_dest/$rel_path"
      if [[ "$DRY_RUN" == true ]]; then
        if [[ ! -f "$dest_file" ]]; then
          echo "  new:     $dest_file"
        elif ! diff -q "$file" "$dest_file" &>/dev/null; then
          echo "  updated: $dest_file"
        else
          echo "  unchanged: $dest_file"
        fi
      else
        mkdir -p "$(dirname "$dest_file")"
        copy_file "$file" "$dest_file"
      fi
    done < <(find "$skill_dir" -type f -print0)
  done
}

# ─── Scripts (recursive: includes .sh files and tests) ────────────────────────

install_scripts() {
  local src="$ROOT_DIR/scripts"
  local dest="$TARGET_BASE/scripts"

  if [[ ! -d "$src" ]]; then
    echo "skip (nonexistent): $src"
    return 1
  fi

  if [[ "$DRY_RUN" == false ]]; then
    mkdir -p "$dest"
  fi

  # Find all files recursively (excluding the install/setup scripts at root level)
  while IFS= read -r -d '' file; do
    local rel_path
    rel_path="${file#$src/}"
    local dest_file="$dest/$rel_path"

    if [[ "$DRY_RUN" == true ]]; then
      if [[ ! -f "$dest_file" ]]; then
        echo "  new:     $dest_file"
      elif ! diff -q "$file" "$dest_file" &>/dev/null; then
        echo "  updated: $dest_file"
      else
        echo "  unchanged: $dest_file"
      fi
    else
      mkdir -p "$(dirname "$dest_file")"
      copy_file "$file" "$dest_file"
      # Preserve executable bit for .sh files
      if [[ "$file" == *.sh ]]; then
        chmod +x "$dest_file" 2>/dev/null || true
      fi
    fi
  done < <(find "$src" -type f -not -name "install.sh" -not -name "setup.sh" -not -name "init-project.sh" -not -name "sync-project.sh" -print0)
}

install_hooks() {
  # Enable the pre-commit secret scanner on this repo via core.hooksPath.
  if [[ ! -f "$ROOT_DIR/scripts/hooks/pre-commit-secrets.sh" ]]; then
    echo "skip (nonexistent): scripts/hooks/pre-commit-secrets.sh"
    return 1
  fi
  if [[ "$DRY_RUN" == true ]]; then
    echo "  enable:  git config core.hooksPath scripts/hooks"
    return 0
  fi
  if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    chmod +x "$ROOT_DIR/scripts/hooks/"*.sh 2>/dev/null || true
    git -C "$ROOT_DIR" config core.hooksPath scripts/hooks
    echo "  hooks:   core.hooksPath=scripts/hooks (pre-commit secret scan enabled)"
  else
    echo "skip (not a git repo): $ROOT_DIR"
  fi
}

install_config() {
  local src="$ROOT_DIR/config"
  local dest="$TARGET_BASE"

  if [[ ! -d "$src" ]]; then
    echo "skip (nonexistent): $src"
    return 1
  fi

  # opencode.json
  if [[ -f "$src/opencode.json" ]]; then
    copy_file "$src/opencode.json" "$dest/opencode.json"
  fi

  # oh-my-opencode-slim.json
  if [[ -f "$src/oh-my-opencode-slim.json" ]]; then
    copy_file "$src/oh-my-opencode-slim.json" "$dest/oh-my-opencode-slim.json"
  fi

  # package.json (for plugin dependencies)
  if [[ -f "$src/package.json" ]]; then
    copy_file "$src/package.json" "$dest/package.json"
  fi

  # .env.example (template — user copies to .env manually or via setup.sh)
  if [[ -f "$src/.env.example" ]]; then
    copy_file "$src/.env.example" "$dest/.env.example"
  fi

  # plugins/ directory
  if [[ -d "$src/plugins" ]]; then
    mkdir -p "$dest/plugins"
    for pfile in "$src/plugins"/*; do
      [[ -e "$pfile" ]] || continue
      pname="$(basename "$pfile")"
      copy_file "$pfile" "$dest/plugins/$pname"
    done
  fi

  # npm install is handled by setup.sh to avoid double-install and give better error output
  if [[ "$DRY_RUN" == false && -f "$dest/package.json" ]]; then
    _UI_NPM_NEEDED=true
  fi
}

# Show logo
if [[ "$DRY_RUN" == false ]]; then
  ui_logo
fi

# Pre-count files for progress bar
_ui_count_files

# Initialise fixed-line progress bar (stays under the logo)
if [[ "$DRY_RUN" == false && "$UI_ANIMATE" == true ]]; then
  ui_progress_init "$_UI_FILE_TOTAL" "Installing files"
fi

# ─── Step wrapper ────────────────────────────────────────────────────────────
# Runs a step: prints start icon, executes callback, prints end icon.

_step_run() {
  local label="$1"
  local fn="$2"
  local rc=0

  if [[ "$DRY_RUN" == true ]]; then
    echo "  $label:"
    "$fn" || true
    return
  fi

  ui_step_start "$label"
  "$fn" || rc=$?
  if [[ $rc -eq 0 ]]; then
    ui_step_done "$label"
  else
    ui_step_fail "$label"
  fi
}

# ─── Step callbacks ──────────────────────────────────────────────────────────

_step_agents()    { install_dir "$ROOT_DIR/agents"     "$TARGET_BASE/agents"; }
_step_standards() { install_dir "$ROOT_DIR/standards"  "$TARGET_BASE/standards"; }
_step_frameworks(){ install_dir "$ROOT_DIR/frameworks" "$TARGET_BASE/frameworks"; }
_step_agentsmd()  { copy_file "$ROOT_DIR/AGENTS.md"    "$TARGET_BASE/AGENTS.md"; }

# ─── Install steps ───────────────────────────────────────────────────────────

_step_run "Installing Agents"        _step_agents
_step_run "Installing Standards"     _step_standards
_step_run "Installing Frameworks"    _step_frameworks
_step_run "Installing AGENTS.md"     _step_agentsmd
_step_run "Installing Skills"        install_skills
_step_run "Installing Scripts"       install_scripts
_step_run "Enabling Git hooks"       install_hooks

if [[ "$NO_CONFIG" == false ]]; then
  _step_run "Installing Configuration" install_config
  # The Infomaniak AI key is exported in the user's shell rc (single copy,
  # managed block written by setup.sh) and read via {env:...}. A missing key
  # only breaks the Infomaniak provider (401), not OpenCode itself.
  if [[ "$DRY_RUN" != true ]]; then
    KEY_FOUND=false
    for rc in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bashrc"; do
      if grep -qsE '^[[:space:]]*export[[:space:]]+OPENAI_API_KEY_INFOMANIAK=' "$rc"; then
        KEY_FOUND=true
        break
      fi
    done
    if [[ "$KEY_FOUND" == true ]]; then
      ok "Infomaniak AI key found in shell rc"
    else
      warn "Infomaniak AI key not found in shell rc (~/.zshrc, ...)"
      warn "The Infomaniak provider will return 401 until you run:"
      warn "  ${ROOT_DIR}/scripts/setup.sh"
    fi
  fi
fi

if [[ "$DRY_RUN" == true ]]; then
  echo ""
  echo "Dry run complete. No files were modified."
else
  # Finalise progress bar
  if [[ "$_UI_PROGRESS_ACTIVE" == true ]]; then
    ui_progress "$_UI_FILE_TOTAL" "$_UI_FILE_TOTAL" "Installing files"
    ui_progress_finish
  fi
  echo ""
  ok "${NEW_COUNT} new, ${UPDATED_COUNT} updated, ${UNCHANGED_COUNT} unchanged"
  if [[ ${PRUNED_COUNT} -gt 0 ]]; then
    warn "${PRUNED_COUNT} pruned"
  fi
  ok "OpenCode configuration installed in $TARGET_BASE"
  echo ""
  echo "  Next steps:"
  if [[ "${_UI_NPM_NEEDED:-false}" == true ]]; then
    echo "    1. Run: cd $TARGET_BASE && npm install"
    echo "    2. Run: $ROOT_DIR/scripts/setup.sh  (for first-time setup with secrets)"
  else
    echo "    1. Run: $ROOT_DIR/scripts/setup.sh  (for first-time setup with secrets)"
  fi
  echo ""
  if [[ "$UI_ANIMATE" == true ]]; then
    ui_typewriter "Aurora is ready." 0.04
  fi
fi
