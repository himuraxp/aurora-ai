#!/usr/bin/env bash
# upload_media.sh — Upload media files to a GitLab project and return Markdown.
#
# Usage: upload_media.sh <file_path> [<file_path> ...]
#
# Requires: glab CLI authenticated and available.
#
# For each file, uploads to the GitLab project and outputs the returned
# Markdown snippet on stdout, one per line.
#
# If a file does not exist or upload fails, prints a warning to stderr
# and continues with the next file.
#
# This script does NOT commit, push, or modify any tracked files.

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "ERROR: No file paths provided." >&2
  echo "Usage: upload_media.sh <file_path> [<file_path> ...]" >&2
  exit 1
fi

# Ensure glab is available
if ! command -v glab &>/dev/null; then
  echo "ERROR: glab CLI not found." >&2
  exit 1
fi

# Ensure python3 is available (multipart body construction — see build_multipart.py)
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found (required to build the multipart body)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure we are in a Git repository
if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "ERROR: Not in a Git repository." >&2
  exit 1
fi

TOPLEVEL="$(git rev-parse --show-toplevel)"
cd "$TOPLEVEL"

# Get project ID
PROJECT_ID=""
if ! PROJECT_ID=$(glab repo view --output json 2>/dev/null | jq -r '.id // empty' 2>/dev/null); then
  echo "ERROR: Could not retrieve project ID via glab." >&2
  exit 1
fi

if [ -z "$PROJECT_ID" ]; then
  echo "ERROR: glab returned empty project ID." >&2
  exit 1
fi

# Multipart body file (contains only media content, never secrets) — cleaned on exit.
BODY_FILE="$(mktemp "${TMPDIR:-/tmp}/upload-media.XXXXXX")"
trap 'rm -f "$BODY_FILE" "$BODY_FILE.err"' EXIT

# Upload each file. `glab api` has NO gh-style `-F file=@...` multipart flag
# (gh CLI syntax; glab --field/--raw-field produce JSON-encoded fields). The
# validated path (glab 1.86, proven in site-manager MR !604) builds the
# multipart body with build_multipart.py and sends it via `glab api --input`.
for file_path in "$@"; do
  if [ ! -f "$file_path" ]; then
    echo "WARN: File not found, skipping: $file_path" >&2
    continue
  fi

  # Check file size (max 10 MB for GitLab uploads)
  file_size=$(wc -c < "$file_path" | tr -d ' ')
  if [ "$file_size" -gt 10485760 ]; then
    echo "WARN: File too large (${file_size} bytes, max 10 MB), skipping: $file_path" >&2
    continue
  fi

  # Build the binary-safe multipart body; stdout = boundary (single line)
  if ! BOUNDARY=$(python3 "$SCRIPT_DIR/build_multipart.py" --file "$file_path" --out "$BODY_FILE"); then
    echo "WARN: Could not build multipart body for: $file_path" >&2
    continue
  fi

  # Upload via glab api (raw body from file, multipart boundary kept in sync)
  uploaded_markdown=""
  glab_error=""
  if ! uploaded_markdown=$(glab api \
    --method POST \
    --input "$BODY_FILE" \
    -H "Content-Type: multipart/form-data; boundary=${BOUNDARY}" \
    "/projects/${PROJECT_ID}/uploads" \
    2>"$BODY_FILE.err" | jq -r '.markdown // empty' 2>/dev/null); then
    glab_error=$(head -n 1 "$BODY_FILE.err" 2>/dev/null || true)
    rm -f "$BODY_FILE.err"
    echo "WARN: Upload failed for: $file_path${glab_error:+ (glab: ${glab_error})}" >&2
    continue
  fi
  rm -f "$BODY_FILE.err"

  if [ -n "$uploaded_markdown" ]; then
    echo "$uploaded_markdown"
  else
    echo "WARN: Upload returned empty markdown for: $file_path" >&2
  fi
done
