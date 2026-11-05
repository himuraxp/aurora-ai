#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(pwd)"

# Parse arguments
DRY_RUN=false
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN=true
  fi
done

copy_if_missing() {
  local src="$1"
  local dest="$2"

  if [[ -e "$dest" ]]; then
    echo "skip existing: $dest"
  else
    if [[ "$DRY_RUN" == true ]]; then
      echo "would create: $dest"
    else
      mkdir -p "$(dirname "$dest")"
      cp "$src" "$dest"
      echo "created: $dest"
    fi
  fi
}

# Copier AGENTS.md racine du projet
copy_if_missing "$ROOT_DIR/templates/AGENTS.md" "$PROJECT_DIR/AGENTS.md"

# Auto-détection de la stack et ajout de la référence framework dans AGENTS.md
detect_stack() {
  local agents_file="$PROJECT_DIR/AGENTS.md"
  local framework_ref=""

  if [[ -f "$PROJECT_DIR/angular.json" ]] || [[ -f "$PROJECT_DIR/.angular-cli.json" ]]; then
    framework_ref="frameworks/angular-20.md"
  elif [[ -f "$PROJECT_DIR/nest-cli.json" ]]; then
    framework_ref="frameworks/nestjs.md"
  elif [[ -f "$PROJECT_DIR/astro.config.mjs" ]] || [[ -f "$PROJECT_DIR/astro.config.ts" ]] || [[ -f "$PROJECT_DIR/astro.config.js" ]]; then
    framework_ref="frameworks/astro.md"
  elif [[ -f "$PROJECT_DIR/wp-config.php" ]] || [[ -d "$PROJECT_DIR/wp-content" ]]; then
    framework_ref="frameworks/wordpress.md"
  elif [[ -f "$PROJECT_DIR/style.css" ]] && grep -qE "^[[:space:]]*Theme Name:" "$PROJECT_DIR/style.css" 2>/dev/null; then
    framework_ref="frameworks/wordpress.md"
  elif grep -qs "Plugin Name:" "$PROJECT_DIR"/*.php 2>/dev/null; then
    framework_ref="frameworks/wordpress.md"
  elif [[ -f "$PROJECT_DIR/package.json" ]]; then
    framework_ref="frameworks/nodejs.md"
  fi

  if [[ -n "$framework_ref" && -f "$agents_file" ]]; then
    # Idempotency: only an injected reference counts ("Apply `…`." / "Appliquer `…`.")
    # — the template's examples list also mentions every framework file.
    if ! grep -qF "Apply \`${framework_ref}\`." "$agents_file" 2>/dev/null \
       && ! grep -qF "Appliquer \`${framework_ref}\`." "$agents_file" 2>/dev/null; then
      if [[ "$DRY_RUN" == true ]]; then
        echo "would add framework reference: $framework_ref"
      else
        # Replace the placeholder section in AGENTS.md. The template is English
        # since the 2026-10-05 translation; keep the FR pattern for projects
        # initialized before it.
        if grep -q "Describe here the project-specific technical conventions" "$agents_file" 2>/dev/null; then
          sed -i.bak "s|Describe here the project-specific technical conventions, or reference a global standard in \`~/.config/opencode/frameworks/\`.|Apply \`$framework_ref\`.|" "$agents_file"
          rm -f "$agents_file.bak" 2>/dev/null || true
          echo "framework reference added: $framework_ref"
        elif grep -q "Décrire ici les conventions techniques" "$agents_file" 2>/dev/null; then
          sed -i.bak "s|Décrire ici les conventions techniques spécifiques au projet, ou référencer un standard global dans \`~/.config/opencode/frameworks/\`.|Appliquer \`$framework_ref\`.|" "$agents_file"
          rm -f "$agents_file.bak" 2>/dev/null || true
          echo "framework reference added: $framework_ref"
        fi
      fi
    fi
  fi
}

detect_stack

# Créer docs/ai/ et copier tous les templates de documentation IA
if [[ "$DRY_RUN" == true ]]; then
  echo "would create dir: $PROJECT_DIR/docs/ai"
else
  mkdir -p "$PROJECT_DIR/docs/ai"
fi

for file in "$ROOT_DIR/templates"/*.md; do
  name="$(basename "$file")"
  if [[ "$name" != "AGENTS.md" ]]; then
    copy_if_missing "$file" "$PROJECT_DIR/docs/ai/$name"
  fi
done

# Copier les templates depuis project-docs/ (BUFFER, INDEX, WARNINGS)
for file in "$ROOT_DIR/templates/project-docs"/*.md; do
  [[ -e "$file" ]] || continue
  copy_if_missing "$file" "$PROJECT_DIR/docs/ai/$(basename "$file")"
done

if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run complete. No files were modified."
else
  echo "Project initialized for OpenCode."
fi

echo ""
echo "Note : OpenCode ne lit jamais les fichiers .new automatiquement."
echo "En cas de divergence future, utilisez sync-project.sh et fusionnez les .new manuellement."
