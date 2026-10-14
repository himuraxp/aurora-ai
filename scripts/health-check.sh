#!/usr/bin/env bash
set -euo pipefail

# health-check.sh — Verify opencode-config consistency.
#
# Checks:
#   1. JSON files are valid (opencode.json, oh-my-opencode-slim.json)
#   2. All agent frontmatter is valid (model, mode, permission)
#   3. All models referenced in agents exist in opencode.json
#   4. Plugin custom agents have a model (oh-my-opencode-slim.json)
#   5. No orphan files in installed config vs repo source
#   6. No broken standard references in agent files
#   7. Git hooks enabled (pre-commit secret scan)
#   8. Technical Council agents (council-* read-only) + council skill
#   9. Cross-Functional Meeting skill (/meeting + agents cibles du catalogue)
#
# Usage: ./scripts/health-check.sh [--installed] [--quiet]
#   --installed  Also check ~/.config/opencode/ for orphans
#   --quiet      Only show errors

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_BASE="${HOME}/.config/opencode"
CHECK_INSTALLED=false
QUIET=false
ERRORS=0
WARNINGS=0

for arg in "$@"; do
  case "$arg" in
    --installed) CHECK_INSTALLED=true ;;
    --quiet)     QUIET=true ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--installed] [--quiet]"
      echo ""
      echo "Options:"
      echo "  --installed  Also check ~/.config/opencode/ for orphan files"
      echo "  --quiet      Only show errors and warnings"
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

ok()   { [[ "$QUIET" == false ]] && echo "  OK   $1" || true; }
warn() { echo "  WARN $1"; WARNINGS=$((WARNINGS + 1)); }
fail() { echo "  FAIL $1"; ERRORS=$((ERRORS + 1)); }

echo "=== Health Check ==="
echo ""

# ─── 1. JSON validity ────────────────────────────────────────────────────────

echo "--- JSON files ---"

for json_file in "config/opencode.json" "config/oh-my-opencode-slim.json" "config/package.json"; do
  if [[ -f "$ROOT_DIR/$json_file" ]]; then
    if jq empty "$ROOT_DIR/$json_file" 2>/dev/null; then
      ok "$json_file"
    else
      fail "$json_file — invalid JSON"
    fi
  fi
done

# ─── 2. Agent frontmatter ─────────────────────────────────────────────────────

echo ""
echo "--- Agent frontmatter ---"

for agent_file in "$ROOT_DIR"/agents/*.md; do
  [[ -f "$agent_file" ]] || continue
  name="$(basename "$agent_file")"

  # Skip README.md — not an agent file
  [[ "$name" == "README.md" ]] && continue

  # Check frontmatter exists
  if ! head -1 "$agent_file" | grep -q "^---$"; then
    fail "$name — missing frontmatter"
    continue
  fi

  # Check required fields
  has_mode=$(grep -c "^mode:" "$agent_file" || true)
  has_model=$(grep -c "^model:" "$agent_file" || true)
  has_perm=$(grep -c "^permission:" "$agent_file" || true)

  # Some agents (like aurora.md) don't have model in frontmatter (inherited
  # from opencode.json "model" default) — all SUBAGENTS must declare one.
  # A file agent without "model" is skipped by the oh-my-opencode-slim plugin
  # with: [oh-my-opencode] Custom agent 'X' skipped: 'model' is required
  if [[ "$has_mode" -eq 0 ]]; then
    fail "$name — missing 'mode' in frontmatter"
  fi
  if [[ "$has_model" -eq 0 && "$name" != "aurora.md" ]]; then
    fail "$name — missing 'model' in frontmatter (plugin skips it: Custom agent '${name%.md}' skipped: 'model' is required)"
  fi
  if [[ "$has_perm" -eq 0 && "$name" != "aurora.md" ]]; then
    warn "$name — missing 'permission' in frontmatter"
  fi

  ok "$name"
done

# ─── 3. Models referenced in agents exist in opencode.json ──────────────────

echo ""
echo "--- Agent models vs opencode.json ---"

# Extract all valid model IDs from opencode.json
# Format: provider/model_name
VALID_MODELS=$(
  jq -r '
    .provider as $p
    | $p | to_entries[]
    | .key as $provider
    | .value.models | to_entries[]
    | .key as $model
    | "\($provider)/\($model)"
  ' "$ROOT_DIR/config/opencode.json" 2>/dev/null || echo ""
)

if [[ -z "$VALID_MODELS" ]]; then
  warn "Could not extract models from opencode.json"
else
  for agent_file in "$ROOT_DIR"/agents/*.md; do
    [[ -f "$agent_file" ]] || continue
    name="$(basename "$agent_file")"
    [[ "$name" == "README.md" ]] && continue

    # Extract model from frontmatter
    model=$(grep "^model:" "$agent_file" 2>/dev/null | head -1 | sed 's/^model:[[:space:]]*//' || true)
    [[ -z "$model" ]] && continue

    # Check if model is in the valid list
    if echo "$VALID_MODELS" | grep -qxF "$model"; then
      ok "$name — model '$model'"
    else
      fail "$name — model '$model' not found in opencode.json providers"
    fi
  done
fi

# ─── 4. Plugin custom agents (oh-my-opencode-slim.json) ─────────────────────

echo ""
echo "--- Plugin custom agents ---"

# Custom agent = any key under top-level "agents" that is neither a plugin
# built-in agent nor an alias. The plugin SKIPS any custom agent without a
# non-empty "model" at startup, with this warning on every session:
#   [oh-my-opencode] Custom agent 'X' skipped: 'model' is required
# Built-ins (oh-my-opencode-slim): orchestrator, oracle, librarian, explorer,
# designer, fixer, observer, council, councillor. Aliases: explore,
# frontend-ui-ux-engineer.
SLIM_CONFIG="$ROOT_DIR/config/oh-my-opencode-slim.json"
SLIM_BUILTINS='["orchestrator","oracle","librarian","explorer","designer","fixer","observer","council","councillor","explore","frontend-ui-ux-engineer"]'

if [[ -f "$SLIM_CONFIG" ]]; then
  # A custom agent present in disabled_agents is filtered by the plugin BEFORE
  # the model check — no warning is emitted for it, so we exclude it too.
  CUSTOM_AGENT_LINES=$(
    jq -r --argjson builtins "$SLIM_BUILTINS" '
      (.disabled_agents // []) as $disabled
      | (.agents // {}) | to_entries[]
      | .key as $k
      | select(($builtins | index($k)) == null)
      | select(($disabled | index($k)) == null)
      | (.value | if type == "object" then (.model // null) else null end) as $m
      | if $m == null or $m == false then "\($k)\tmissing"
        elif ($m | type) == "array" then
          (if ($m | length) > 0 then "\($k)\tok" else "\($k)\tempty" end)
        elif ($m | type) == "string" then
          (if ($m | length) > 0 then "\($k)\tok" else "\($k)\tempty" end)
        else "\($k)\tempty"
        end
    ' "$SLIM_CONFIG" 2>/dev/null || true
  )

  if [[ -z "$CUSTOM_AGENT_LINES" ]]; then
    ok "No custom agents defined"
  else
    while IFS=$'\t' read -r agent status; do
      [[ -z "$agent" ]] && continue
      case "$status" in
        ok) ok "$agent — model set" ;;
        empty) fail "$agent — empty 'model' (plugin will skip it: Custom agent '$agent' skipped: 'model' is required)" ;;
        *) fail "$agent — missing 'model' (plugin will skip it: Custom agent '$agent' skipped: 'model' is required)" ;;
      esac
    done <<< "$CUSTOM_AGENT_LINES"

    # Referenced models must exist in opencode.json providers.
    # model entries may be strings or objects ({id, variant}) — extract ids.
    if [[ -n "$VALID_MODELS" ]]; then
      while IFS= read -r m; do
        [[ -z "$m" ]] && continue
        if echo "$VALID_MODELS" | grep -qxF "$m"; then
          ok "custom agent model '$m'"
        else
          fail "custom agent model '$m' not found in opencode.json providers"
        fi
      done < <(
        jq -r --argjson builtins "$SLIM_BUILTINS" '
          (.disabled_agents // []) as $disabled
          | (.agents // {}) | to_entries[]
          | .key as $k
          | select(($builtins | index($k)) == null)
          | select(($disabled | index($k)) == null)
          | .value | if type == "object" then (.model? // empty) else empty end
          | if type == "array" then .[] else . end
          | if type == "object" then (.id // empty) else . end
          | select(type == "string" and length > 0)
        ' "$SLIM_CONFIG" 2>/dev/null || true
      )
    fi
  fi

  if [[ -f "$ROOT_DIR/config/oh-my-opencode-slim.jsonc" ]]; then
    warn "config/oh-my-opencode-slim.jsonc — exists but not validated by this check (JSONC not supported here)"
  fi
else
  warn "config/oh-my-opencode-slim.json — not found"
fi

# ─── 5. S-05 invariant — bash ruleset order (empirically validated 2026-10-07) ─

if [[ -f "$ROOT_DIR/scripts/check-bash-ruleset-order.py" ]]; then
  echo ""
  echo "--- S-05 invariant (bash ruleset order) ---"
  if python3 "$ROOT_DIR/scripts/check-bash-ruleset-order.py" "$ROOT_DIR/config/opencode.json"; then
    ok "S-05 invariant respected (catch-all deny first)"
  else
    warn "S-05 invariant violated — terminal catch-all deny removes the bash tool (see script output)"
  fi
fi

# ─── 6. S-02 invariant — Infomaniak MCP write gate (2026-10-07) ─────────────

if [[ -f "$ROOT_DIR/scripts/check-infomaniak-write-gate.mjs" ]]; then
  echo ""
  echo "--- S-02 invariant (Infomaniak MCP write gate) ---"
  if node "$ROOT_DIR/scripts/check-infomaniak-write-gate.mjs"; then
    ok "S-02 write gate enforced (global MCP read-only, writes behind orchestrator bridge)"
  else
    warn "S-02 write gate violated — global Infomaniak MCP must stay read-only (see script output)"
  fi
fi

# ─── 7. MCP local lock — no npx at runtime (chantier 7a, 2026-10-07) ────────

if [[ -f "$ROOT_DIR/scripts/setup-mcp-lock.py" ]]; then
  echo ""
  echo "--- MCP local lock (no runtime registry dependency) ---"
  if python3 "$ROOT_DIR/scripts/setup-mcp-lock.py" --check-only; then
    ok "MCP binaries locally locked and present"
  else
    warn "MCP lock violated — run 'npm run mcp-lock' to install/lock npx-based MCPs"
  fi
fi

# ─── 8. Orphan detection (installed config) ────────────────────────────────

if [[ "$CHECK_INSTALLED" == true ]]; then
  echo ""
  echo "--- Orphan detection (~/.config/opencode/) ---"

  for dir in agents standards frameworks; do
    if [[ ! -d "$TARGET_BASE/$dir" ]]; then
      warn "$TARGET_BASE/$dir — not installed"
      continue
    fi

    for installed_file in "$TARGET_BASE/$dir"/*.md; do
      [[ -f "$installed_file" ]] || continue
      installed_name="$(basename "$installed_file")"
      if [[ ! -f "$ROOT_DIR/$dir/$installed_name" ]]; then
        warn "$dir/$installed_name — orphan (not in repo source)"
      fi
      # Deployed file agents must also declare a model (same plugin rule)
      if [[ "$dir" == "agents" && "$installed_name" != "README.md" && "$installed_name" != "aurora.md" ]]; then
        if ! grep -q "^model:" "$installed_file"; then
          fail "agents/$installed_name (installed) — missing 'model' in frontmatter (plugin skips it)"
        fi
      fi
    done
  done

  ok "Orphan check complete"
fi

# ─── 6. Broken standard references ─────────────────────────────────────────

echo ""
echo "--- Standard references ---"

# Check that standards referenced in any agent file exist
for agent_file in "$ROOT_DIR"/agents/*.md; do
  [[ -f "$agent_file" ]] || continue
  agent_name=$(basename "$agent_file")
  [[ "$agent_name" == "README.md" ]] && continue
  for ref in $(grep -oE 'standards/[a-z-]+\.md' "$agent_file" 2>/dev/null | sort -u || true); do
    ref_path="$ROOT_DIR/$ref"
    if [[ ! -f "$ref_path" ]]; then
      fail "$agent_name references '$ref' — file not found"
    fi
  done
done

ok "Standard references checked"

# ─── 7. Git hooks (pre-commit secret scan) ──────────────────────────────────

echo ""
echo "--- Git hooks ---"

HOOKS_PATH="$(git -C "$ROOT_DIR" config core.hooksPath 2>/dev/null || true)"
if [[ "$HOOKS_PATH" == "scripts/hooks" ]]; then
  ok "core.hooksPath=scripts/hooks"
else
  warn "pre-commit secret scan not enabled — run: git config core.hooksPath scripts/hooks"
  WARNINGS=$((WARNINGS + 1))
fi
if [[ -x "$ROOT_DIR/scripts/hooks/pre-commit-secrets.sh" ]]; then
  ok "pre-commit-secrets.sh executable"
else
  warn "pre-commit-secrets.sh not executable — run: chmod +x scripts/hooks/*.sh"
  WARNINGS=$((WARNINGS + 1))
fi

# Fixture suite: end-to-end validation of the hook patterns (regex layer;
# gitleaks skipped via HOOK_SKIP_GITLEAKS=1 for determinism).
if [[ -x "$ROOT_DIR/scripts/hooks/test-pre-commit-patterns.sh" ]]; then
  if HOOK_SKIP_GITLEAKS=1 "$ROOT_DIR/scripts/hooks/test-pre-commit-patterns.sh" > /tmp/hook-fixture-suite.log 2>&1; then
    ok "pre-commit pattern fixture suite passed"
  else
    fail "pre-commit pattern fixture suite FAILED — see /tmp/hook-fixture-suite.log"
  fi
else
  warn "test-pre-commit-patterns.sh missing — hook patterns unvalidated"
  WARNINGS=$((WARNINGS + 1))
fi

# ─── 6. Technical Council agents ─────────────────────────────────────────────
# 3 seats read-only + synthesizer: file must exist, YAML-valid frontmatter, a
# model, and deny edit/write/bash/ast_grep_replace (read-only structurel) —
# skill skills/council depends on them.

COUNCIL_AGENTS=(council-architect council-skeptic council-guardian council-synthesizer)
COUNCIL_MODELS=(
  "infomaniak/euria-code"
  "infomaniak/moonshotai/Kimi-K2.6"
  "infomaniak/Qwen/Qwen3.5-397B-A17B-FP8"
  "infomaniak/euria-code-tiny"
)

# YAML validation of ALL agent frontmatters (catches the unquoted-colon trap —
# sage.md 2026-10-06, council-synthesizer.md 2026-10-13 — that grep checks miss).
YAML_ERRORS=0
for f in "$ROOT_DIR"/agents/*.md; do
  [[ "$(basename "$f")" == "README.md" ]] && continue
  if ! ruby -ryaml -e "YAML.safe_load(File.read(ARGV[0]).split(/^---\n/)[1], permitted_classes: [], aliases: false)" "$f" 2>/dev/null; then
    fail "agent frontmatter YAML invalid: $(basename "$f") (unquoted ':' trap?)"
    YAML_ERRORS=$((YAML_ERRORS + 1))
  fi
done
if [[ $YAML_ERRORS -eq 0 ]]; then
  ok "all agents/*.md frontmatter YAML valid"
fi

for i in "${!COUNCIL_AGENTS[@]}"; do
  AG="${COUNCIL_AGENTS[$i]}"
  AGF="$ROOT_DIR/agents/${AG}.md"
  if [[ ! -f "$AGF" ]]; then
    fail "council agent $AG missing (skills/council broken)"
    continue
  fi
  if ! grep -Eq "^model: ${COUNCIL_MODELS[$i]}\$" "$AGF"; then
    fail "council agent $AG: model '${COUNCIL_MODELS[$i]}' not found in frontmatter (plugin skips agents without valid model)"
  fi
  for KEY in edit write bash ast_grep_replace; do
    if ! grep -Eq "^  ${KEY}: deny\$" "$AGF"; then
      fail "council agent $AG: read-only invariant broken (${KEY}: deny missing)"
    fi
  done
  ok "council agent $AG present, model + read-only verified"
done
# Synthesizer contract: NO tool at all (pure synthesis)
SYNF="$ROOT_DIR/agents/council-synthesizer.md"
if [[ -f "$SYNF" ]]; then
  for KEY in read glob grep; do
    if ! grep -Eq "^  ${KEY}: deny\$" "$SYNF"; then
      fail "council-synthesizer: no-tools contract broken (${KEY}: deny missing)"
    fi
  done
  ok "council-synthesizer no-tools contract verified"
fi
if [[ -f "$ROOT_DIR/skills/council/SKILL.md" ]]; then
  grep -q '^name: council' "$ROOT_DIR/skills/council/SKILL.md" \
    && ok "council skill present" \
    || fail "council skill frontmatter invalid (name: council missing)"
else
  fail "skills/council/SKILL.md missing"
fi

# ─── 7. Cross-Functional Meeting skill ───────────────────────────────────────
# /meeting dispatch sur des agents existants (architect, security, reviewer :
# denies préexistants) et des variantes read-only dédiées (meeting-designer,
# meeting-tester, meeting-mobile : miroirs des originaux, deny runtime complet
# — protection structurelle) + clause de framing obligatoire (défense en
# profondeur) + check git status (couche de détection).
# Vérifier le skill, la présence des agents cibles, les variantes et l'anti-drift.

MEETING_TARGETS=(architect security reviewer meeting-designer meeting-tester meeting-mobile product-owner)
if [[ -f "$ROOT_DIR/skills/meeting/SKILL.md" ]]; then
  if grep -q '^name: meeting' "$ROOT_DIR/skills/meeting/SKILL.md"; then
    ok "meeting skill present"
    for AG in "${MEETING_TARGETS[@]}"; do
      [[ -f "$ROOT_DIR/agents/${AG}.md" ]] \
        && ok "meeting target agent $AG present" \
        || fail "meeting target agent $AG missing (skills/meeting catalogue broken)"
    done
    for AG in designer tester mobile; do
      [[ -f "$ROOT_DIR/agents/${AG}.md" ]] \
        || fail "meeting mirror source agent $AG missing (anti-drift impossible for meeting-${AG})"
    done
    grep -q 'schema_version: meeting-handoff.v1' "$ROOT_DIR/skills/meeting/SKILL.md" \
      && ok "meeting handoff contract versioned (meeting-handoff.v1)" \
      || fail "meeting handoff contract missing (schema_version: meeting-handoff.v1)"
    # Read-only du meeting = clause de framing OBLIGATOIRE dans les 2 templates
    # (dispatch Round 0 + re-prompt Round 1) — pas une garantie de permissions.
    [[ $(grep -c 'MODE MEETING READ-ONLY' "$ROOT_DIR/skills/meeting/SKILL.md") -ge 2 ]] \
      && ok "meeting read-only framing clause present in both dispatch templates" \
      || fail "meeting read-only framing clause missing (dispatch templates must carry 'MODE MEETING READ-ONLY')"
    ruby -ryaml -e "YAML.safe_load(File.read('$ROOT_DIR/skills/meeting/SKILL.md').split(/^---\n/)[1], permitted_classes: [], aliases: false)" \
      && ok "meeting skill frontmatter valid YAML" \
      || fail "meeting skill frontmatter invalid YAML"
  else
    fail "meeting skill frontmatter invalid (name: meeting missing)"
  fi
else
  fail "skills/meeting/SKILL.md missing"
fi

# Variantes read-only du meeting : miroirs de designer/tester/mobile.
# Read-only STRUCTUREL — deny set complet dans le frontmatter, aucune entrée
# dans la section agent de opencode.json (le frontmatter seul décide, pattern
# council prouvé e2e). Anti-drift : les headings du corps du miroir doivent
# rester identiques à ceux de l'original (toute évolution d'un original doit
# être répercutée dans son miroir).
for AG in designer tester mobile; do
  MF="$ROOT_DIR/agents/meeting-${AG}.md"
  OF="$ROOT_DIR/agents/${AG}.md"
  if [[ ! -f "$MF" ]]; then
    fail "meeting read-only variant meeting-${AG} missing (skills/meeting catalogue points to it)"
    continue
  fi
  _VAR_FAIL=0
  for KEY in edit write bash webfetch task question ast_grep_replace skill; do
    if ! grep -Eq "^  ${KEY}: deny\$" "$MF"; then
      fail "meeting variant meeting-${AG}: read-only invariant broken (${KEY}: deny missing)"
      _VAR_FAIL=1
    fi
  done
  if [[ -f "$OF" ]]; then
    # Anti-drift STRICT : corps complet hors frontmatter (identité JSON de sortie
    # exemptée — seule divergence contractuelle du miroir). Compteur frontmatter
    # borné : un '---' thématique en corps ne tronque pas la collecte.
    DIFF_OUT=$(diff <(awk 'c==2{print} /^---$/{if(c<2)c++}' "$OF" | grep -v '"agent":') <(awk 'c==2{print} /^---$/{if(c<2)c++}' "$MF" | grep -v '"agent":') || true)
    if [[ -n "$DIFF_OUT" ]]; then
      fail "meeting variant meeting-${AG}: anti-drift broken (body differs from agents/${AG}.md — resync the mirror)"
      _VAR_FAIL=1
    fi
  fi
  [[ $_VAR_FAIL -eq 0 ]] && ok "meeting variant meeting-${AG} present, deny set + anti-drift verified"
done

# ─── 10. Product Authority (Standard v1.1 — Étape 3 MVP) ─────────────────────
# Agent PO read-only structurel + skill orchestrator + plugin contrôleur +
# registre privé + intégration meeting (profil + handoff additif) + standard.

PA_STANDARD="$ROOT_DIR/standards/product-authority.md"
PA_AGENT="$ROOT_DIR/agents/product-owner.md"
PA_SKILL="$ROOT_DIR/skills/product-authority/SKILL.md"
PA_PLUGIN="$ROOT_DIR/config/plugins/product-authority.ts"
LIVE_DIR="$HOME/.config/opencode"

[[ -f "$PA_STANDARD" ]] && ok "product-authority standard present (v1.1 source of truth)" \
  || fail "standards/product-authority.md missing (Product Authority contracts ungrounded)"

if [[ -f "$PA_AGENT" ]]; then
  _PA_FAIL=0
  for KEY in edit write bash webfetch task question ast_grep_replace skill; do
    grep -Eq "^  ${KEY}: deny\$" "$PA_AGENT" || {
      fail "product-owner: read-only invariant broken (${KEY}: deny missing)"
      _PA_FAIL=1
    }
  done
  grep -Eq "^model: " "$PA_AGENT" || { fail "product-owner: model missing (plugin skips agents without valid model)"; _PA_FAIL=1; }
  grep -q 'product-authority.md' "$PA_AGENT" || { fail "product-owner: standard reference missing"; _PA_FAIL=1; }
  # Le PO ne référence jamais le chemin du registre (il ne lit JAMAIS la politique — §10.6)
  grep -q 'aurora-product-authority.json' "$PA_AGENT" && {
    fail "product-owner: mentions the policy registry path (must never know it — §10.6)"
    _PA_FAIL=1
  }
  [[ $_PA_FAIL -eq 0 ]] && ok "product-owner agent present, deny set + model + blind-policy verified"
else
  fail "agents/product-owner.md missing (Product Authority MVP incomplete)"
fi

if [[ -f "$PA_SKILL" ]]; then
  grep -q '^name: product-authority' "$PA_SKILL" \
    && ok "product-authority skill present" \
    || fail "product-authority skill frontmatter invalid (name missing)"
  for ACT in show set revoke defer reconcile; do
    grep -q "action: \"${ACT}\"\|action: \`${ACT}\`\|### \`${ACT}\`" "$PA_SKILL" \
      || fail "product-authority skill: action '${ACT}' not documented"
  done
else
  fail "skills/product-authority/SKILL.md missing"
fi

if [[ -f "$PA_PLUGIN" ]]; then
  for TOOL in authorizeProductDecision verifyAuthorization productAuthorityPolicy; do
    grep -q "name: \"${TOOL}\"" "$PA_PLUGIN" \
      || fail "product-authority plugin: tool '${TOOL}' missing"
  done
  grep -q 'ORCHESTRATOR_AGENTS' "$PA_PLUGIN" \
    && ok "product-authority plugin present (3 tools, orchestrator gate)" \
    || fail "product-authority plugin: orchestrator gate missing (pattern ADR-021 broken)"
  # Déploiement live : le plugin doit être copié pour exécuter
  [[ -f "$LIVE_DIR/plugins/product-authority.ts" ]] \
    && ok "product-authority plugin deployed to live config" \
    || warn "product-authority plugin NOT deployed to ~/.config/opencode/plugins/ (tools inert until deployed)"
else
  fail "config/plugins/product-authority.ts missing (controller absent)"
fi

if [[ -f "$LIVE_DIR/aurora-product-authority.json" ]]; then
  python3 -c "import json,sys; r=json.load(open('$HOME/.config/opencode/aurora-product-authority.json')); assert r.get('schema_version')==1 and 'projects' in r" 2>/dev/null \
    && ok "live product-authority registry valid (schema_version 1)" \
    || fail "live product-authority registry invalid (schema drift or corrupt JSON)"
else
  warn "live registry absent — onboarding will create it at first real product-decision need (expected on fresh installs)"
fi

if [[ -f "$ROOT_DIR/skills/meeting/SKILL.md" ]]; then
  grep -q 'product-owner' "$ROOT_DIR/skills/meeting/SKILL.md" \
    && grep -q 'decisions: \[\]' "$ROOT_DIR/skills/meeting/SKILL.md" \
    && ok "meeting skill integrates Product Authority (profile + handoff decisions[])" \
    || fail "meeting skill missing Product Authority integration (profile product-owner / handoff decisions[])"
fi

# Product-authority reception suite — behavioral invariants the static greps
# above cannot cover (gate, fail-closed, v2 return shape, lifecycle).
if [[ -f "$ROOT_DIR/scripts/test-product-authority.mjs" ]]; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  PA_FLAGS=""
  if (( NODE_MAJOR >= 23 )); then
    PA_FLAGS=""
  elif (( NODE_MAJOR == 22 )); then
    PA_FLAGS="--experimental-strip-types"
  fi
  if (( NODE_MAJOR >= 22 )); then
    # shellcheck disable=SC2086
    if node $PA_FLAGS "$ROOT_DIR/scripts/test-product-authority.mjs" >/dev/null 2>&1; then
      ok "product-authority reception suite passed (behavioral invariants)"
    else
      fail "product-authority reception suite FAILED — controller regression"
    fi
  else
    warn "product-authority reception suite skipped (node >= 22 required for TS type-stripping)"
  fi
fi

# ─── 11. Task-workflow skill (orchestrateur Trello/GitLab) ──────────────────

if [[ -f "$ROOT_DIR/skills/task-workflow/SKILL.md" ]]; then
  grep -q '^name: task-workflow' "$ROOT_DIR/skills/task-workflow/SKILL.md" \
    && ok "task-workflow skill present (frontmatter)" \
    || fail "task-workflow frontmatter name missing or renamed"
  grep -qi 'non fiable' "$ROOT_DIR/skills/task-workflow/SKILL.md" \
    && ok "task-workflow untrusted task-content framing present" \
    || fail "task-workflow missing the untrusted task-content framing rule"
  grep -q 'pre-mr-review' "$ROOT_DIR/skills/task-workflow/SKILL.md" \
    && grep -q 'create-mr' "$ROOT_DIR/skills/task-workflow/SKILL.md" \
    && grep -q 'new-worktree' "$ROOT_DIR/skills/task-workflow/SKILL.md" \
    && ok "task-workflow reuses new-worktree + pre-mr-review + create-mr" \
    || fail "task-workflow must reference the reused skills (new-worktree, pre-mr-review, create-mr)"
  grep -qi 'jamais de merge automatique\|jamais.*merge automatique' "$ROOT_DIR/skills/task-workflow/SKILL.md" \
    && ok "task-workflow forbids automatic merge" \
    || fail "task-workflow must explicitly forbid automatic merge"
fi

if [[ -f "$ROOT_DIR/skills/task-workflow/tw_state.py" ]]; then
  ok "task-workflow state contract present (tw_state.py)"
  if python3 -m unittest discover -s "$ROOT_DIR/skills/task-workflow/tests" >/dev/null 2>&1; then
    ok "task-workflow state contract tests passed"
  else
    fail "task-workflow state contract tests FAILED"
  fi
fi

# ─── 12. Design-qa skill (conformité interface ↔ design de référence) ───────

if [[ -f "$ROOT_DIR/skills/design-qa/SKILL.md" ]]; then
  grep -q '^name: design-qa' "$ROOT_DIR/skills/design-qa/SKILL.md" \
    && ok "design-qa skill present (frontmatter)" \
    || fail "design-qa frontmatter name missing or renamed"
  grep -qi 'jamais inventer une mesure figma\|jamais inventer des valeurs figma' "$ROOT_DIR/skills/design-qa/SKILL.md" \
    && ok "design-qa no-invented-figma-measurements rule present" \
    || fail "design-qa must forbid invented Figma measurements"
  grep -qi "score.*similarité\|similarité.*preuve" "$ROOT_DIR/skills/design-qa/SKILL.md" \
    && ok "design-qa pixel-score-is-not-proof rule present" \
    || fail "design-qa must state that a similarity score is never sufficient proof"
  grep -q 'tw_state\|task-workflow' "$ROOT_DIR/skills/design-qa/SKILL.md" \
    && grep -q 'angular-elements' "$ROOT_DIR/skills/design-qa/SKILL.md" \
    && grep -q 'figma-ds' "$ROOT_DIR/skills/design-qa/SKILL.md" \
    && ok "design-qa reuses task-workflow + angular-elements + figma-ds" \
    || fail "design-qa must reference the reused capabilities (task-workflow, angular-elements, figma-ds)"
fi

if [[ -f "$ROOT_DIR/skills/design-qa/dq_contract.py" ]]; then
  ok "design-qa deterministic contract present (dq_contract.py)"
  if python3 -m unittest discover -s "$ROOT_DIR/skills/design-qa/tests" >/dev/null 2>&1; then
    ok "design-qa contract tests passed"
  else
    fail "design-qa contract tests FAILED"
  fi
  # No new dependency allowed: the visual diff uses ImageMagick (system), not
  # a package.json addition (pixelmatch/playwright forbidden without review).
  if grep -q "pixelmatch\|playwright" "$ROOT_DIR/skills/design-qa/dq_contract.py" \
      "$ROOT_DIR/skills/design-qa/SKILL.md"; then
    fail "design-qa must not depend on pixelmatch/playwright (ImageMagick compare is the sanctioned tool)"
  else
    ok "design-qa introduces no new visual-diff dependency (ImageMagick)"
  fi
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "=== Summary ==="
if [[ $ERRORS -eq 0 && $WARNINGS -eq 0 ]]; then
  echo "All checks passed."
elif [[ $ERRORS -eq 0 ]]; then
  echo "Passed with $WARNINGS warning(s)."
else
  echo "$ERRORS error(s), $WARNINGS warning(s)."
fi

exit $((ERRORS > 0 ? 1 : 0))
