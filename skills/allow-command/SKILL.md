---
name: allow-command
description: Pre-approve shell commands in opencode.json permissions. Paste a "Permission required" block from OpenCode and the skill parses the commands, extracts patterns, and adds them as "allow" rules in the target agent's bash permissions. Eliminates manual validation for recurring commands.
---

# Allow Command — Pre-approve Shell Commands

## When to use

The user pastes a block that OpenCode flagged with "Permission required". The block contains shell commands that triggered a permission prompt. This skill parses those commands and adds them to `config/opencode.json` so they auto-approve next time.

## Input format

The user pastes one or more blocks that look like:

```
△Permission required
#Shell command
$ COMMAND_HERE
```

or simply pastes raw shell commands.

## Procedure

### 1. Parse the input

Extract all shell commands from the pasted block. Commands may be:

- Prefixed with `$ ` (shell prompt)
- Part of a `FILES=( ... )` bash array
- Part of a multi-line script
- Plain commands without prefix

For each command, identify the **executable prefix** (the first word or compound command) that maps to an opencode.json permission key.

### 2. Map commands to permission patterns

For each extracted command, derive a permission pattern:

| Command form | Permission key | Example |
|---|---|---|
| `git push origin ...` | `"git push *"` | `git push origin feat/branch` |
| `git checkout -b ...` | `"git checkout *"` | `git checkout -b feat/test` |
| `yarn build app` | `"yarn build *"` | `yarn build app-name` |
| `npm run test:unit` | `"npm run *"` | `npm run test:unit` |
| `npx eslint ...` | `"npx *"` | `npx eslint --fix src/` |
| `rg ...` | `"rg *"` | `rg "pattern" src/` |
| `python script.py` | `"python *"` | `python migrate.py` |
| `docker build ...` | `"docker *"` | `docker build -t app .` |
| `kubectl get pods` | `"kubectl *"` | `kubectl get pods` |
| `PROJECT_ENCODED="..."` | (skip — variable assignment) | |
| `HEAD_SHA="..."` | (skip — variable assignment) | |
| `FILES=( ... )` | (skip — array literal) | |

**Rules:**

- Variable assignments (`FOO="bar"`) are skipped — they are not commands
- Array literals (`FILES=( ... )`) are skipped
- Compound commands (`A=b cmd`) → extract the command after the assignment
- Piped commands (`cmd1 | cmd2`) → add both commands separately
- Commands with `&&` or `;` → split and add each separately
- For `git`, use specific sub-command patterns (`git push *`, `git checkout *`) not `git *` unless the user's config already uses `git *`

### 3. Determine the target agent

Default target: the agent the user is currently using (usually `build` or `aurora`).

If the user specifies an agent explicitly (e.g. "add to agent spark"), use that agent.

If the agent's config is not found in `opencode.json`, create a minimal entry.

### 4. Read the current config

Read `config/opencode.json` from this repo (`~/.config/opencode-config/config/opencode.json`).

Navigate to `agent.<agent_name>.permission.bash`.

Two cases:

**Case A: bash is an object** (has `"*": "ask"` or `"*": "deny"` etc.):

```json
"bash": {
  "*": "ask",
  "echo *": "allow",
  ...
}
```

Simply add the new patterns as `"allow"` entries. If a pattern already exists with a different value, keep the existing value (do not override).

**Case B: bash is a scalar** (e.g. `"bash": "ask"`):

```json
"bash": "ask"
```

Convert to an object:

```json
"bash": {
  "*": "ask",
  "new-pattern *": "allow"
}
```

The scalar value becomes the `"*"` default, and new patterns are added as `"allow"`.

### 5. Apply changes

Use the `edit` tool to modify `config/opencode.json`. Insert the new patterns in the bash block for the target agent, maintaining alphabetical order within the keys.

**Security guardrails — NEVER allow:**

- `"sudo *"` — always `deny`
- `"su *"` — always `deny`
- `"doas *"` — always `deny`
- `"rm -rf /"` — always `deny`
- `"rm -rf /*"` — always `deny`
- `"mkfs *"` — always `deny`
- `"dd *of=/dev/*"` — always `deny`
- `"chmod 777 *"` — do not allow
- Anything that writes to `/dev/` — do not allow

If the user pastes a command that matches a denied pattern, do NOT add it. Report it as skipped.

### 6. Deduplicate

Before adding, check if the pattern already exists in the target agent's bash config. If it does, skip it (report as already present).

### 7. Report

After applying changes, show the user:

```
### allow-command — Result

**Agent**: build
**Config file**: config/opencode.json

| # | Pattern | Status |
|---|---------|--------|
| 1 | `git push *` | added |
| 2 | `yarn build *` | already present |
| 3 | `sudo *` | skipped (security) |

Changes will take effect after running `install.sh` or on next OpenCode restart.
```

### 8. Deploy (optional)

If the user asks to deploy, run:

```bash
npm run update -- --no-config
# ou: ~/.config/opencode-config/scripts/install.sh --no-config
```

This copies the updated `opencode.json` to `~/.config/opencode/opencode.json`.

Note: `install.sh --no-config` skips config files. To deploy config, the user should run `install.sh` without `--no-config` or manually copy `config/opencode.json` to `~/.config/opencode/opencode.json`.

Actually, since the config IS in `config/opencode.json`, a full `install.sh` run is needed to deploy it. Alternatively, the user can just restart OpenCode if the config is symlinked.

## Examples

### Example 1: Simple git command

**Input:**
```
△Permission required
#Shell command
$ git push origin feat/add-astro-framework
```

**Action:** Add `"git push *": "allow"` to the target agent's bash permissions (if not already present and not already `"ask"` or `"allow"`).

### Example 2: Multi-command block

**Input:**
```
△Permission required
#Shell command
$ PROJECT_ENCODED="acme-group%2Fexample-project"
$ HEAD_SHA="abc123def456"
$ FILES=(
  "apps/example/src/app/modules/products/.../android-integration.component.ts"
  "apps/example/src/app/modules/products/.../laptop-integration.component.html"
)
$ curl -s --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ENCODED/repository/files/$file_path/raw?ref=$HEAD_SHA"
```

**Action:**

1. `PROJECT_ENCODED=...` → skip (variable assignment)
2. `HEAD_SHA=...` → skip (variable assignment)
3. `FILES=( ... )` → skip (array literal)
4. `curl -s --header ...` → add `"curl *": "allow"`

**Result:** Only `"curl *"` is added (likely already present).

### Example 3: Build command

**Input:**
```
$ yarn build --configuration production
```

**Action:** Add `"yarn build *": "allow"` if not present.
