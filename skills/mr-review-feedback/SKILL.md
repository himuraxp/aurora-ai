---
name: mr-review-feedback
description: Automatically read and apply unresolved MR review comments. Detects GitLab suggestions, applies code changes, and creates commits via the 'commit' skill following Infomaniak conventions. After pushing, runs an avoidability gap analysis (review-gap-analyzer) on the applied feedback and, at human GO, can deliver AGENTS.md improvements as a dedicated MR.
---

# MR Review Feedback

Apply unresolved review feedback from MR comments automatically.

**Requires**: GitLab CLI (`glab`) authenticated and current branch with an open MR.

## Process

### Step 1: Detect Active MR

```bash
CURRENT_BRANCH=$(git branch --show-current)
MR_INFO=$(glab mr list --source-branch="$CURRENT_BRANCH" --output json | jq '.[0] // empty')

if [[ -z "$MR_INFO" || "$MR_INFO" == "null" ]]; then
  echo "❌ No open MR found for branch: $CURRENT_BRANCH"
  echo "Create an MR first with the 'create-mr' skill"
  exit 1
fi

MR_IID=$(echo "$MR_INFO" | jq -r '.iid')
MR_TITLE=$(echo "$MR_INFO" | jq -r '.title')
PROJECT_PATH=$(glab repo view --output json | jq -r '.path_with_namespace')

echo "Found MR !${MR_IID}: ${MR_TITLE}"
```

### Step 2: Fetch Unresolved Discussions

```bash
DISCUSSIONS=$(glab api "/projects/${PROJECT_PATH}/merge_requests/${MR_IID}/discussions" | jq '[.[] | select(.notes[0].resolvable and .notes[0].resolved == false)]')
COUNT=$(echo "$DISCUSSIONS" | jq 'length')

if [[ "$COUNT" -eq 0 ]]; then
  echo "✅ No unresolved comments found"
  exit 0
fi

echo "Found ${COUNT} unresolved discussion(s)"
```

### Step 3: Apply Suggestions and Fixes

**Apply code suggestions:**

````bash
echo "$DISCUSSIONS" | jq -c '[.[] | select(.notes[0].body | contains("```suggestion"))]' | jq -c '.[]' | while read -r item; do
  NOTE=$(echo "$item" | jq -r '.notes[0]')
  FILE=$(echo "$NOTE" | jq -r '.position.new_path')
  LINE=$(echo "$NOTE" | jq -r '.position.new_line')
  ID=$(echo "$item" | jq -r '.id')
  BODY=$(echo "$NOTE" | jq -r '.body')

  # Extract code between ```suggestion and ```
  CODE=$(echo "$BODY" | sed -n '/^```suggestion$/,/^```$/p' | sed '1d;$d')

  if [[ -n "$CODE" && -f "$FILE" ]]; then
    [[ "$OSTYPE" == "darwin"* ]] && sed -i "" "${LINE}s/.*/$CODE/" "$FILE" || sed -i "${LINE}s/.*/$CODE/" "$FILE"
    glab api --method PUT "/projects/${PROJECT_PATH}/merge_requests/${MR_IID}/discussions/${ID}" -F "resolved=true" > /dev/null 2>&1
    echo "✅ Applied + resolved: ${FILE}:${LINE}"
  fi
done
````

**Auto-fix lint/format issues:**

```bash
if echo "$DISCUSSIONS" | jq -r '.[].notes[0].body' | grep -qiE "(lint|format|import|order|style)"; then
  [[ -f "package.json" ]] && grep -q '"lint:fix"' package.json 2>/dev/null && yarn lint:fix && echo "✅ Fixed lint issues"
  [[ -f "package.json" ]] && grep -q '"format:write"' package.json 2>/dev/null && yarn format:write && echo "✅ Fixed formatting"
fi

# Track if tests were requested
TEST_REQUIRED=false
if echo "$DISCUSSIONS" | jq -r '.[].notes[0].body' | grep -qiE "(test.*missing|add.*test|test.*coverage)"; then
  TEST_REQUIRED=true
fi
```

### Step 4: Stage and Commit

```bash
if git diff --quiet HEAD; then
  echo "❌ No changes made"
  exit 0
fi

git add -A
echo ""
echo "=== Changes ==="
git diff --cached --stat
echo ""

# Auto-detect commit type
if echo "$DISCUSSIONS" | jq -r '.[].notes[0].body' | grep -qiE "(naming|rename|extract|refactor)"; then
  TYPE="ref"
elif echo "$DISCUSSIONS" | jq -r '.[].notes[0].body' | grep -qiE "(fix|bug|error|broken)"; then
  TYPE="fix"
elif echo "$DISCUSSIONS" | jq -r '.[].notes[0].body' | grep -qiE "(test)"; then
  TYPE="test"
else
  TYPE="style"
fi

echo "Detected type: ${TYPE}"
echo "Invoking commit skill..."
echo ""

invoke skill commit

echo ""
echo "Next: yarn test && git push"
[[ "$TEST_REQUIRED" == "true" ]] && echo "⚠️  Tests requested - add them manually"
```

### Step 5: Reply to Review Threads Individually

**CRITICAL**: Never use `glab mr note` to reply to review comments. It creates a global note at the bottom of the MR instead of replying in the discussion thread. Always reply within each thread using the GitLab discussions API.

For each unresolved discussion, post a reply **in that specific thread** — not a global MR note. This applies to both:
- Comments that were fixed (reply with what was done + commit hash)
- Comments that were rejected (reply with the justification)

```bash
COMMIT_HASH=$(git rev-parse --short HEAD)

echo "$DISCUSSIONS" | jq -c '.[]' | while read -r item; do
  DISCUSSION_ID=$(echo "$item" | jq -r '.id')
  NOTE=$(echo "$item" | jq -r '.notes[0]')
  BODY=$(echo "$NOTE" | jq -r '.body')
  AUTHOR=$(echo "$NOTE" | jq -r '.author.username')

  # Skip system notes (commit notifications, label changes, etc.)
  if echo "$BODY" | jq -r '.' | grep -qiE "^(added|changed|marked|assigned|requested|merged)"; then
    continue
  fi

  # Check if this comment was addressed in the changes
  FILE=$(echo "$NOTE" | jq -r '.position.new_path // empty')
  LINE=$(echo "$NOTE" | jq -r '.position.new_line // empty')

  if [[ -n "$FILE" && -n "$LINE" ]]; then
    # Code comment — check if the line was changed
    if git diff HEAD~1 HEAD -- "$FILE" 2>/dev/null | grep -q "^[+-].*${LINE}"; then
      REPLY="✅ Fixed in commit ${COMMIT_HASH}."
    else
      REPLY="❌ Not a bug. See discussion above."
    fi
  else
    # General comment — acknowledge
    REPLY="✅ Addressed in commit ${COMMIT_HASH}."
  fi

  # Post reply IN the discussion thread (not as a global MR note)
  glab api --method POST \
    "/projects/${PROJECT_PATH}/merge_requests/${MR_IID}/discussions/${DISCUSSION_ID}/notes" \
    -f "body=${REPLY}" > /dev/null 2>&1

  echo "✅ Replied to thread ${DISCUSSION_ID:0:8}"
done
```

**For comments that require a detailed response** (e.g., rejecting a reviewer's claim), the agent should compose a specific reply instead of the generic template above. The key rule is: always use `glab api --method POST .../discussions/{id}/notes` to reply in the thread, never `glab mr note`.

**Resolving discussions**: After replying, optionally mark the discussion as resolved if the comment was addressed:

```bash
glab api --method PUT \
  "/projects/${PROJECT_PATH}/merge_requests/${MR_IID}/discussions/${DISCUSSION_ID}" \
  -F "resolved=true" > /dev/null 2>&1
```

### Step 6: Push

```bash
git push
echo ""
echo "✅ Review feedback applied and pushed"
```

### Step 7: Gap analysis — could this feedback have been avoided? (conditional, read-only)

After pushing the fixes, run an avoidability analysis on the feedback you just
handled, following the `review-gap-analyzer` skill as the protocol. Goal:
determine which reviewer comments are **symptoms of a missing project rule** —
they would never have been necessary if this project had a better `AGENTS.md`
(or a versioned mechanical guard).

Trigger: run when at least one reviewer comment was handled in Step 3 (fix)
or Step 5 (reply or rejection) — continue into this step even when Step 4
committed nothing (a rejection-only turn still yields a gap report). Skip
only if this project has no `AGENTS.md`: report "gap analysis skipped: no
AGENTS.md in this project" and mention to the user that creating one is a
separate initiative.

Process:

1. Load `~/.config/opencode/skills/review-gap-analyzer/SKILL.md` and follow
   its process (programmatic mode) with:
   - **Feedback source**: the reviewer comments handled above (author = the
     reviewer, file, line, text) — never the replies we posted in Step 5.
   - **AGENTS.md reference**: this project's `AGENTS.md`.
   - **Target repo for improvements**: this repository.
2. Produce the gap report in the analyzer's format. Comments whose pattern was
   already covered by an explicit AGENTS.md rule are process issues, not gaps.

Delivery gate:

- Gaps targeting versionable files of this repo (`AGENTS.md`, versioned
  project guards) are delivered as a **separate branch and a dedicated MR** —
  never mixed into the review-feedback commit of Step 4. Follow the analyzer's
  delivery protocol (its Étape 8).
- **Never create the branch or the MR without an explicit human GO.**
- **Anti-recursion**: never run this gap analysis on an MR created by the
  analyzer's delivery protocol (its dedicated improvement branch, e.g.
  `chore/agents-md-review-gaps`) or on an MR that edits this project's
  `AGENTS.md`.

## Limitations

**✅ Handled:** Code suggestions, lint/format auto-fix, import ordering, thread replies via discussions API  
**❌ Requires manual action:** Complex logic, new files, breaking changes, security fixes, database migrations

## Safety

- Never modifies `.env` or secrets
- Stages changes before commit (review with `git diff --cached`)
- Test generation requires manual action
- **Never use `glab mr note` to reply to review comments** — always use `glab api --method POST .../discussions/{id}/notes` to reply in the thread

## Example

```bash
$ opencode /mr-review-feedback
Found MR !123: feat(auth): Add user profile
Found 3 unresolved discussion(s)
✅ Applied + resolved: src/user.service.ts:42
✅ Fixed lint issues

=== Changes ===
 src/services/user.service.ts | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)

Detected type: ref
Invoking commit skill...

<commit skill takes over>

[main abc1234] ref(services): Apply review feedback from MR !123

✅ Replied to thread 9c0fc72a
✅ Replied to thread 6cc883fc
✅ Replied to thread 70a56b88
✅ Review feedback applied and pushed

Step 7 — gap analysis: 1 avoidable gap found (AGENTS.md missing rule on X)
→ report shown; dedicated AGENTS.md MR awaits human GO.
```
