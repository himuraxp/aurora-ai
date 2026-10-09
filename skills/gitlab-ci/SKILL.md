---
name: gitlab-ci
description: Use when interacting with GitLab CI/CD pipelines and jobs using the glab CLI. Covers listing, viewing, running, tracing, retrying, and managing pipelines.
---

# GitLab CI/CD (glab ci)

Interact with GitLab CI/CD pipelines and jobs using the glab CLI.

**Requires**: GitLab CLI (`glab`) authenticated and available.

## Quick Reference

| Command | Description |
|---------|-------------|
| `glab ci list` | List pipelines in the current repository |
| `glab ci view [branch]` | Interactive pipeline viewer with job logs |
| `glab ci status` | View pipeline status for a branch |
| `glab ci get` | Get pipeline details as JSON |
| `glab ci retry <job>` | Retry a failed or completed job |
| `glab ci trace <job>` | Stream job logs in real-time |

## Listing Pipelines

```bash
# List recent pipelines
glab ci list

# List pipelines with specific status
glab ci list --status=failed
glab ci list --status=running
glab ci list --status=success

# List pipelines for a specific branch
glab ci list --ref=main

# List pipelines triggered by a user
glab ci list --username=john.doe

# List pipelines with YAML errors
glab ci list --yaml-errors

# List pipelines updated after a date
glab ci list --updated-after=2024-01-01T00:00:00Z

# Output as JSON
glab ci list --output=json

# Paginate results
glab ci list --per-page=50 --page=2
```

**Filter Options:**
- `--status`: running, pending, success, failed, canceled, skipped, created, manual, waiting_for_resource, preparing, scheduled
- `--scope`: running, pending, finished, branches, tags
- `--source`: push, merge_request_event, trigger, pipeline, web, schedule, api
- `--order`: id, status, ref, updated_at, user_id
- `--sort`: asc, desc

## Viewing Pipelines (Interactive)

The `ci view` command provides an interactive TUI for viewing pipelines:

```bash
# View pipeline for current branch (interactive)
glab ci view

# View pipeline for specific branch
glab ci view main
glab ci view --branch=feature-branch

# View specific pipeline by ID
glab ci view --pipelineid=12345

# Open pipeline in browser
glab ci view --web

# View pipeline for different repository
glab ci view main -R owner/repo
```

**Interactive Controls:**
- `Enter` - Toggle job logs / view child pipeline
- `Esc` or `q` - Close logs / return to parent
- `Ctrl+R` / `Ctrl+P` - Run/retry/play a job
- `Ctrl+D` - Cancel a job
- `Ctrl+Q` - Quit the viewer
- `Ctrl+Space` - Suspend and view logs (like trace)
- Arrow keys / vi bindings - Navigate jobs

## Pipeline Status

```bash
# Check status of current branch pipeline
glab ci status

# Check status for specific branch
glab ci status --branch=main

# Live status updates until completion
glab ci status --live

# Compact status view
glab ci status --compact
```

## Getting Pipeline Details

```bash
# Get pipeline details as text
glab ci get

# Get pipeline details as JSON
glab ci get --output=json

# Get specific pipeline by ID
glab ci get --pipeline-id=12345

# Include job details
glab ci get --with-job-details

# Include variables (requires Maintainer role)
glab ci get --with-variables
```

## Tracing Job Logs

```bash
# Interactively select a job to trace
glab ci trace

# Trace specific job by ID
glab ci trace 224356863

# Trace specific job by name
glab ci trace lint
glab ci trace "build:docker"

# Trace job on specific branch
glab ci trace lint --branch=main

# Trace job from specific pipeline
glab ci trace lint --pipeline-id=12345
```

## Retrying Jobs

```bash
# Interactively select a job to retry
glab ci retry

# Retry specific job by ID
glab ci retry 224356863

# Retry job by name
glab ci retry lint

# Retry job on specific branch
glab ci retry lint --branch=main

# Retry job from specific pipeline
glab ci retry lint --pipeline-id=12345
```

## Common Workflows

### Check Recent Failed Pipelines

```bash
glab ci list --status=failed --per-page=10
```

### Monitor Pipeline Until Complete

```bash
glab ci status --live
```

### Debug Failed Job

```bash
# View the failed job logs
glab ci trace <job-name>

# Or use interactive viewer
glab ci view
# Then navigate to failed job and press Enter
```

### Retry Failed Jobs

```bash
# Get failed jobs from current pipeline
glab ci get --with-job-details --output=json | jq '.jobs[] | select(.status=="failed") | .name'

# Retry a specific failed job
glab ci retry <job-name>
```

## Global Options

All `glab ci` commands support:

- `-R, --repo OWNER/REPO` - Target a different repository
- `-h, --help` - Show help for the command

**Repository Formats:**
- `OWNER/REPO` - Short format
- `GROUP/NAMESPACE/REPO` - Full namespace
- Full URL: `https://gitlab.example.com/owner/repo`
- Git URL: `git@gitlab.example.com:owner/repo.git`

## Tips

- Use `--web` flag to open pipelines in browser for detailed viewing
- Combine filters for precise pipeline queries (e.g., `--status=failed --ref=main`)
- Use JSON output for scripting: `--output=json | jq ...`
- The interactive viewer (`ci view`) is the fastest way to debug pipeline failures
