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

The template is a skeleton, not a license for walls of text — every section must pass the [Readability Rules](#readability-rules-write-for-humans) below. For multi-page or migration work, use the [Feature / Migration Issue](#feature--migration-issue) pattern instead of the Summary/Details skeleton.

## Readability Rules (write for humans)

Issues are read by humans scanning a page, not reading every word. The **30-second test**: a reader must capture scope, delivery plan and risks without reading the full body. If a section requires full reading, restructure it.

1. **One bullet = one idea, max 2 rendered lines.** A bullet that packs several endpoints, guards, or problems into one flowing sentence is a wall of text — split it into sub-bullets or a table. A tight enumeration of closely related facets (an MR title listing its deliverables) is fine; a sentence is not.
2. **Never put tabular data in prose.** Route mappings (source → target), API endpoints, config flags, UI columns, before/after paths → Markdown table. Prose hides structure; tables expose it.
3. **Sub-sections (`###`) when a section covers 3+ distinct axes** (e.g. routing, API, store, UI are four axes — four sub-sections, not four giant bullets).
4. **Checklists (`- [ ]`) for anything actionable** — GitLab renders native progress ("3 of 8"), which is the point of a scope section. Plain bullets for informative content only. Validation conditions (acceptance criteria) also stay plain bullets — progress belongs to work items, not validation conditions. Suggestions (e.g. optional MR groupings) are never checkboxes.
5. **`<details><summary>` for exhaustive content** — full route dumps, code excerpts, diagnostics. The body stays scannable; the noise is collapsed but still there.
6. **Bold as an anchor, at the start**: `**Guard behavior**: redirect when …` — one anchor per bullet, never bold sprinkled through flowing sentences.
7. **Inverted pyramid**: each section states what and why in its first line, details after. The reader who stops at line 1 of each section still gets the picture.

### Before / After

❌ Before — the anti-pattern: one bullet hiding a table (five endpoints invisible), a bug buried mid-sentence (the simulated delete), and an unrelated concern mixed in (the upload):

```markdown
2. **Service layer** (`HttpService` + params): `GET items/{id}` (details), `GET collections/{id}/views`, `GET/POST/DELETE items/{id}/shares` (bulk DELETE with body `{shares: ids}`), `GET/PUT/DELETE shares/{shareId}`; thumbnail upload (`POST items/{id}`) — and the bulk delete only simulates removal with a 5s timeout, needs backend confirmation.
```

✅ After — table for the endpoints, one idea per line:

```markdown
### Service layer

Proxy endpoints:

| Endpoint | Usage |
|----------|-------|
| `GET items/{id}` | Item details |
| `GET collections/{id}/views` | Available views |
| `GET/POST/DELETE items/{id}/shares` | Shares (bulk DELETE, body `{shares: ids}`) |
| `GET/PUT/DELETE shares/{shareId}` | Single share |
| `POST items/{id}` | Thumbnail upload |

Points of attention:
- Bulk delete simulates removal with a 5s timeout — needs backend confirmation
```

### Pre-creation checklist

Run before `glab issue create` / `glab issue update`:

- [ ] Every bullet ≤ 2 rendered lines, one idea each
- [ ] All structured data (endpoints, routes, flags, columns) in tables
- [ ] Sections spanning 3+ axes split into `###` sub-sections
- [ ] Actionable scope as checklist; informative notes as plain bullets
- [ ] Exhaustive dumps wrapped in `<details>`
- [ ] Bold anchors at bullet start only, never mid-sentence
- [ ] First line of each section carries the message

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

- **Write for scanning**: short bullets, tables for structured data, sub-sections for multi-axis sections, checklists for actionable work (see Readability Rules)
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

### Feature / Migration Issue

Multi-page or migration work: routes in a table, delivery as checklists, risks as one-idea bullets. This shape is for **hand-authored** issues — issues produced by `gitlab-feature-planner` keep the planner draft format. Match the project's issue language (headings below are English; many projects write their issues in French).

```bash
glab issue create \
  --title "feat(shop): Migrate product and catalog pages from the legacy app" \
  --description "$(cat <<'EOF'
## Context

Migration of the catalog pages from the legacy manager: 3 pages share most of
their components and will be rebuilt around one **reusable** component.

| Route (source) | Route (target) |
|----------------|----------------|
| `/legacy/catalog/list` | `/catalog/list` |
| `/legacy/catalog/product[/{id}]` | `/catalog/product[/{id}]` |
| `/legacy/catalog/share[/{id}]` | `/catalog/share[/{id}]` |

## Scope

What this issue covers, by axis:

### Routing & guards
- [ ] Routes under `catalog/` + guard redirecting to the catalog when the product is missing
- [ ] Breadcrumbs: catalog → product → page

### Service API
- [ ] Proxy endpoints:

| Endpoint | Usage |
|----------|-------|
| `GET items/{id}` | Item details |
| `GET/POST/DELETE items/{id}/shares` | Shares (bulk DELETE, body `{shares: ids}`) |
| `GET/PUT/DELETE shares/{shareId}` | Single share |

- [ ] Thumbnail upload

### Pages
- [ ] List page: modern table with server-side pagination
- [ ] List page: bulk selection and actions
- [ ] Edit page: reusable component, mode driven by share type

## Delivery plan

Shipped as stacked MR batches, merged in order 1 → 2:

- [ ] **MR 1 — Scaffolding + list page**: routing, guards, service, models
- [ ] **MR 2 — Edit page**: reusable component + dialogs

## Watch-outs

- Legacy endpoints have no v3 equivalent yet — keep the proxy
- Entity named `album` in legacy URLs, `gallery` in the target app — same ID
- The dashboard still points to the legacy pages — coordinate the switch at release

## References

- Legacy sources: `apps/legacy/src/modules/gallery/`
- Reference MR of a similar migration: !123
EOF
)" \
  --label "enhancement"
```
