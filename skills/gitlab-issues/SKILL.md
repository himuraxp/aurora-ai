---
name: gitlab-issues
description: Use when creating, viewing, updating, or managing GitLab issues. Interact with GitLab issues using the glab CLI following team conventions.
---

# GitLab Issues

Create, view, update, and manage GitLab issues using the glab CLI.

**Requires**: GitLab CLI (`glab`) authenticated and available.

## Quick Reference

| Command | Description |
|---------|-------------|
| `glab issue list` | List issues in the current repository |
| `glab issue view <number>` | View issue details |
| `glab issue create` | Create a new issue |
| `glab issue update <number>` | Update an existing issue |
| `glab issue close <number>` | Close an issue |
| `glab issue reopen <number>` | Reopen a closed issue |
| `glab issue note <number>` | Add a comment to an issue |
| `glab issue subscribe <number>` | Subscribe to issue notifications |

## Listing Issues

```bash
# List open issues
glab issue list

# List all issues (open and closed)
glab issue list --all

# List issues with specific label
glab issue list --label "bug"

# List issues assigned to you
glab issue list --assignee "@me"

# Search issues by keyword
glab issue list --search "authentication"

# Output as JSON for parsing
glab issue list --output json
```

## Viewing Issues

```bash
# View issue details
glab issue view 123

# View issue in browser
glab issue view 123 --web

# View issue with comments
glab issue view 123 --comments

# Output as JSON
glab issue view 123 --output json
```

## Creating Issues

### Step 1: Check for Issue Templates

```bash
# List available issue templates
glab repo view --output json | jq -r '.issue_templates[]'
```

### Step 2: Create the Issue

```bash
# Create a simple issue
glab issue create --title "Fix authentication bug" --description "Users cannot log in with SSO"

# Create with labels and assignee
glab issue create \
  --title "feat: Add dark mode support" \
  --description "Implement dark mode toggle in settings" \
  --label "enhancement" \
  --label "frontend" \
  --assignee "@me"

# Create from a file
glab issue create --title "Bug report" --description "$(cat issue_description.md)"
```

### Issue Description Format

Follow this structure for issue descriptions:

```markdown
## Summary
Brief description of the issue or feature request.

## Details
- **Current behavior**: What happens now
- **Expected behavior**: What should happen
- **Steps to reproduce**: (for bugs) Numbered steps
- **Impact**: Who is affected and how

## Context
Additional information, links to related issues, or screenshots.

## Proposed Solution
(optional) Suggested approach if you have one.
```

## Updating Issues

```bash
# Update title
glab issue update 123 --title "New title"

# Update description
glab issue update 123 --description "Updated description"

# Add/remove labels
glab issue update 123 --label "urgent"
glab issue update 123 --unlabel "backlog"

# Change assignee
glab issue update 123 --assignee "username"
glab issue update 123 --unassign

# Set milestone
glab issue update 123 --milestone "v2.0"
```

## Issue States

```bash
# Close an issue
glab issue close 123

# Close with comment
glab issue close 123 --comment "Fixed in commit abc123"

# Reopen an issue
glab issue reopen 123

# Lock/unlock discussion
glab issue update 123 --lock-discussion
glab issue update 123 --unlock-discussion
```

## Comments and Notes

```bash
# Add a comment
glab issue note 123 --message "Working on this now"

# Add comment from file
glab issue note 123 --message "$(cat comment.md)"
```

## Cross-Referencing

Reference other issues and MRs in descriptions and comments:

| Syntax | Effect |
|--------|--------|
| `#123` | Links to issue 123 |
| `!456` | Links to MR 456 |
| `username#123` | Links to issue in another project |
| `group/project#123` | Links to issue in specific project |

## Bulk Operations

```bash
# Close multiple issues
glab issue close 123 124 125

# Update multiple issues with same label
glab issue update 123 --label "in-progress"
glab issue update 124 --label "in-progress"
```

## Guidelines

- **Use descriptive titles**: Clear titles help with search and scanning
- **Label consistently**: Use established labels for categorization
- **Reference related work**: Link to MRs, other issues, and documentation
- **Close with context**: When closing, explain why (fixed, duplicate, won't fix)
- **One issue per topic**: Don't bundle unrelated requests

## Common Patterns

### Bug Report

```bash
glab issue create \
  --title "fix(api): Handle null response in user endpoint" \
  --description "$(cat <<'EOF'
## Summary
The user endpoint returns null for soft-deleted accounts, causing crashes.

## Details
- **Current behavior**: Null pointer exception when accessing user.name
- **Expected behavior**: Return 404 or empty user object
- **Impact**: Dashboard crashes for deleted account lookups

## Steps to Reproduce
1. Create a user
2. Soft-delete the user
3. Query /api/users/{id}
4. Observe null response

## Related
Found while investigating SENTRY-5678.
EOF
)" \
  --label "bug" \
  --label "api"
```

### Feature Request

```bash
glab issue create \
  --title "feat(ui): Add export to CSV button" \
  --description "$(cat <<'EOF'
## Summary
Add ability to export filtered results to CSV format.

## Details
- **Use case**: Users need to share data with external tools
- **Expected behavior**: Export button downloads CSV of current view
- **Priority**: Medium

## Proposed Solution
Add export button to table toolbar using existing CSV utilities.
EOF
)" \
  --label "enhancement" \
  --label "frontend"
```
