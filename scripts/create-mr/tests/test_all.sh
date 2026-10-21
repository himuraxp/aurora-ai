#!/usr/bin/env bash
# test_all.sh — Tests for create-mr scripts.
#
# Usage: bash test_all.sh
#
# Creates temporary Git repositories to test each script in isolation.
# Never calls a real GitLab project or glab.
# All assertions are local.

set -euo pipefail

# Resolve paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Test counters
PASS=0
FAIL=0
TOTAL_ASSERTIONS=0
FAILED_ASSERTIONS=0

# Temp directory for test repos
TMP_BASE="/tmp/create-mr-tests-$$"
mkdir -p "$TMP_BASE"
trap 'rm -rf "$TMP_BASE"' EXIT

# ─── Helpers ─────────────────────────────────────────────────────────────────

assert_eq() {
  local desc="$1"
  local expected="$2"
  local actual="$3"
  TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
  if [ "$expected" = "$actual" ]; then
    PASS=$((PASS + 1))
    echo "  PASS: $desc"
  else
    FAIL=$((FAIL + 1))
    FAILED_ASSERTIONS=$((FAILED_ASSERTIONS + 1))
    echo "  FAIL: $desc"
    echo "    expected: '$expected'"
    echo "    actual:   '$actual'"
  fi
}

assert_contains() {
  local desc="$1"
  local needle="$2"
  local haystack="$3"
  TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
  if echo "$haystack" | grep -qF -- "$needle"; then
    PASS=$((PASS + 1))
    echo "  PASS: $desc"
  else
    FAIL=$((FAIL + 1))
    FAILED_ASSERTIONS=$((FAILED_ASSERTIONS + 1))
    echo "  FAIL: $desc"
    echo "    needle: '$needle' not found in:"
    echo "    $haystack"
  fi
}

assert_exit_code() {
  local desc="$1"
  local expected_code="$2"
  local actual_code="$3"
  TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
  if [ "$expected_code" = "$actual_code" ]; then
    PASS=$((PASS + 1))
    echo "  PASS: $desc"
  else
    FAIL=$((FAIL + 1))
    FAILED_ASSERTIONS=$((FAILED_ASSERTIONS + 1))
    echo "  FAIL: $desc"
    echo "    expected exit code: $expected_code"
    echo "    actual exit code:   $actual_code"
  fi
}

# Create a minimal Git repo in a temp directory
# Usage: create_test_repo <dir_name> [--with-template <file> <content>]
create_test_repo() {
  local repo_dir="$TMP_BASE/$1"
  shift
  mkdir -p "$repo_dir"
  cd "$repo_dir"
  git init --quiet
  git config user.email "test@test.com"
  git config user.name "Test"
  echo "# Test" > README.md
  git add README.md
  git commit --quiet -m "init"
  # Create and checkout a feature branch
  git checkout --quiet -b feat/test-feature

  # Process optional template args
  while [ $# -gt 0 ]; do
    case "$1" in
      --with-template)
        local template_file="$2"
        local template_content="$3"
        mkdir -p "$(dirname "$template_file")"
        echo "$template_content" > "$template_file"
        shift 3
        ;;
      --with-file)
        local fpath="$2"
        local fcontent="$3"
        mkdir -p "$(dirname "$fpath")"
        echo "$fcontent" > "$fpath"
        shift 3
        ;;
    esac
  done

  echo "$repo_dir"
}

# Shared test upload snippets (used by build_body + build_comparison_table tests)
BEFORE_MD='![avant](/uploads/hash1/before.png)'
AFTER_MD='![apres](/uploads/hash2/after.png)'

# ─── Tests: validate_title.sh ─────────────────────────────────────────────────

echo ""
echo "=== validate_title.sh ==="

test_title_valid() {
  local result
  result=$(bash "$SCRIPTS_DIR/validate_title.sh" "feat(auth): add OAuth2 login" 2>&1)
  assert_exit_code "valid feat title exits 0" 0 $?
  assert_eq "valid feat title output" "OK" "$result"
}
test_title_valid

test_title_valid_no_scope() {
  local result
  result=$(bash "$SCRIPTS_DIR/validate_title.sh" "refactor: extract validation logic" 2>&1)
  assert_exit_code "valid refactor title exits 0" 0 $?
  assert_eq "valid refactor title output" "OK" "$result"
}
test_title_valid_no_scope

test_title_valid_with_breaking() {
  local result
  result=$(bash "$SCRIPTS_DIR/validate_title.sh" "feat(api)!: remove deprecated v1 endpoints" 2>&1)
  assert_exit_code "valid breaking change title exits 0" 0 $?
  assert_eq "valid breaking change title output" "OK" "$result"
}
test_title_valid_with_breaking

test_title_invalid_no_type() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/validate_title.sh" "add something" 2>&1)
  code=$?
  set -e
  assert_exit_code "invalid title (no type) exits 1" 1 "$code"
  assert_contains "invalid title mentions format" "Conventional Commit" "$result"
}
test_title_invalid_no_type

test_title_invalid_no_colon() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/validate_title.sh" "feat add something" 2>&1)
  code=$?
  set -e
  assert_exit_code "invalid title (no colon) exits 1" 1 "$code"
}
test_title_invalid_no_colon

test_title_empty() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/validate_title.sh" "" 2>&1)
  code=$?
  set -e
  assert_exit_code "empty title exits 1" 1 "$code"
}
test_title_empty

test_title_no_arg() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/validate_title.sh" 2>&1)
  code=$?
  set -e
  assert_exit_code "no arg exits 1" 1 "$code"
}
test_title_no_arg

test_title_too_long() {
  local long_title="feat: $(printf 'a%.0s' {1..95})"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/validate_title.sh" "$long_title" 2>&1)
  code=$?
  set -e
  assert_exit_code "title over 100 chars exits 1" 1 "$code"
  assert_contains "too long mentions length" "too long" "$result"
}
test_title_too_long

# ─── Tests: detect_template.sh ────────────────────────────────────────────────

echo ""
echo "=== detect_template.sh ==="

test_template_found_gitlab_dir() {
  local repo
  repo=$(create_test_repo "with-template-1" \
    --with-template ".gitlab/merge_request_templates/default.md" \
    "## Contexte\n\n{{CONTEXT}}\n\n## Solution\n\n{{SOLUTION}}")
  cd "$repo"
  local result
  result=$(bash "$SCRIPTS_DIR/detect_template.sh" 2>/dev/null || true)
  assert_exit_code "template in .gitlab/merge_request_templates/ exits 0" 0 $?
  assert_contains "template contains placeholder" "{{CONTEXT}}" "$result"
}
test_template_found_gitlab_dir

test_template_found_root() {
  local repo
  repo=$(create_test_repo "with-template-2" \
    --with-template "MERGE_REQUEST_TEMPLATE.md" \
    "# MR Template\n\n{{CONTEXT}}")
  cd "$repo"
  local result
  result=$(bash "$SCRIPTS_DIR/detect_template.sh" 2>/dev/null || true)
  assert_exit_code "template at root exits 0" 0 $?
  assert_contains "root template has placeholder" "{{CONTEXT}}" "$result"
}
test_template_found_root

test_template_not_found() {
  local repo
  repo=$(create_test_repo "no-template")
  cd "$repo"
  local result
  result=$(bash "$SCRIPTS_DIR/detect_template.sh" 2>/dev/null || true)
  assert_exit_code "no template exits 0" 0 $?
  assert_eq "no template outputs nothing" "" "$result"
}
test_template_not_found

test_template_priority_gitlab_dir() {
  local repo
  repo=$(create_test_repo "with-template-3" \
    --with-template ".gitlab/merge_request_templates/default.md" "GITLAB_DIR_TEMPLATE" \
    --with-template "MERGE_REQUEST_TEMPLATE.md" "ROOT_TEMPLATE")
  cd "$repo"
  local result
  result=$(bash "$SCRIPTS_DIR/detect_template.sh" 2>/dev/null || true)
  assert_contains "gitlab dir template takes priority" "GITLAB_DIR_TEMPLATE" "$result"
}
test_template_priority_gitlab_dir

# ─── Tests: check_workspace.sh ────────────────────────────────────────────────

echo ""
echo "=== check_workspace.sh ==="

test_workspace_clean() {
  local repo
  repo=$(create_test_repo "clean-repo")
  cd "$repo"
  local result
  result=$(bash "$SCRIPTS_DIR/check_workspace.sh" 2>&1)
  assert_exit_code "clean workspace exits 0" 0 $?
  assert_contains "clean workspace mentions branch" "feat/test-feature" "$result"
}
test_workspace_clean

test_workspace_dirty() {
  local repo
  repo=$(create_test_repo "dirty-repo")
  cd "$repo"
  echo "dirty" >> README.md
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/check_workspace.sh" 2>&1)
  code=$?
  set -e
  assert_exit_code "dirty workspace exits 1" 1 "$code"
  assert_contains "dirty workspace mentions dirty" "dirty" "$result"
}
test_workspace_dirty

test_workspace_on_main() {
  local repo
  repo=$(create_test_repo "main-repo")
  cd "$repo"
  git checkout --quiet main 2>/dev/null || git checkout --quiet master 2>/dev/null
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/check_workspace.sh" 2>&1)
  code=$?
  set -e
  assert_exit_code "on main exits 1" 1 "$code"
  assert_contains "on main mentions feature branch" "feature branch" "$result"
}
test_workspace_on_main

# ─── Tests: build_body.sh ──────────────────────────────────────────────────────

echo ""
echo "=== build_body.sh ==="

test_build_body_default() {
  local result
  result=$(bash "$SCRIPTS_DIR/build_body.sh" \
    --context "Fix a bug" \
    --solution "Added null check" 2>&1)
  assert_exit_code "build body default exits 0" 0 $?
  assert_contains "body has Contexte" "## Contexte" "$result"
  assert_contains "body has Solution" "## Solution" "$result"
  assert_contains "body has Ressources" "## Ressources" "$result"
  assert_contains "body contains context text" "Fix a bug" "$result"
  assert_contains "body contains solution text" "Added null check" "$result"
}
test_build_body_default

test_build_body_with_template() {
  local repo
  repo=$(create_test_repo "template-body")
  cd "$repo"
  echo "## Contexte

{{CONTEXT}}

## Solution

{{SOLUTION}}

## Ressources

{{RESOURCES}}" > "$TMP_BASE/template.md"

  local result
  result=$(bash "$SCRIPTS_DIR/build_body.sh" \
    --context "Mon contexte" \
    --solution "Ma solution" \
    --resources "- [JIRA-123](url)" \
    --template-file "$TMP_BASE/template.md" 2>&1)
  assert_exit_code "build body with template exits 0" 0 $?
  assert_contains "template body has context replaced" "Mon contexte" "$result"
  assert_contains "template body has solution replaced" "Ma solution" "$result"
  assert_contains "template body has resources replaced" "[JIRA-123](url)" "$result"
}
test_build_body_with_template

test_build_body_with_media() {
  local result
  result=$(bash "$SCRIPTS_DIR/build_body.sh" \
    --context "Feature" \
    --solution "Implementation" \
    --media "![screenshot](upload.png)" 2>&1)
  assert_exit_code "build body with media exits 0" 0 $?
  assert_contains "body has Media section" "## Media" "$result"
  assert_contains "body has media content" "screenshot" "$result"
}
test_build_body_with_media

test_build_body_no_context() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_body.sh" \
    --solution "Just solution" 2>&1)
  code=$?
  set -e
  assert_exit_code "build body without context exits 1" 1 "$code"
}
test_build_body_no_context

test_build_body_no_solution() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_body.sh" \
    --context "Just context" 2>&1)
  code=$?
  set -e
  assert_exit_code "build body without solution exits 1" 1 "$code"
}
test_build_body_no_solution

test_build_body_default_resources() {
  local result
  result=$(bash "$SCRIPTS_DIR/build_body.sh" \
    --context "C" \
    --solution "S" 2>&1)
  assert_contains "default resources when none provided" "(none)" "$result"
}
test_build_body_default_resources

test_build_body_template_multiline_solution() {
  # Regression pin: a multi-line solution (e.g. a Before/After comparison
  # table appended to it) must be injected into a project template without
  # silently falling back to the raw template (placeholders visible).
  local repo
  repo=$(create_test_repo "template-body-multiline")
  cd "$repo"
  printf '%s\n' \
    '### Contexte' \
    '' \
    'Description de l'"'"'incrément ou du fix à insérer ici' \
    '' \
    '### Solution' \
    '' \
    'Description détaillée' > "$TMP_BASE/template-multiline.md"

  local comparison solution result
  comparison=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" \
    --before "$BEFORE_MD" --after "$AFTER_MD" --caption "Formulaire de qualité")
  solution="Texte de la solution.

${comparison}"

  result=$(bash "$SCRIPTS_DIR/build_body.sh" \
    --context "Contexte du fix" \
    --solution "$solution" \
    --template-file "$TMP_BASE/template-multiline.md" 2>&1)
  assert_exit_code "multiline solution with template exits 0" 0 $?
  assert_contains "placeholders fully replaced (context injected)" "Contexte du fix" "$result"
  assert_contains "table injected into template" "**Formulaire de qualité :**" "$result"
  assert_contains "table header present" "| Avant | Après |" "$result"
  assert_contains "table row present" "| ${BEFORE_MD} | ${AFTER_MD} |" "$result"
  local raw_left
  raw_left=$(echo "$result" | grep -F 'Description détaillée' || true)
  assert_eq "no raw template phrase left" "" "$raw_left"
}
test_build_body_template_multiline_solution

# ─── Tests: push_branch.sh ─────────────────────────────────────────────────────

echo ""
echo "=== push_branch.sh ==="

test_push_branch_no_remote() {
  local repo
  repo=$(create_test_repo "push-no-remote")
  cd "$repo"
  # Add a commit on the feature branch so there's something to push
  echo "new file" > newfile.txt
  git add newfile.txt
  git commit --quiet -m "feat: add new file"
  # No remote set up; push should fail
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/push_branch.sh" 2>&1)
  code=$?
  set -e
  # Should fail since there's no remote
  assert_exit_code "push without remote exits 1" 1 "$code"
}
test_push_branch_no_remote

# ─── Tests: create_mr.sh ──────────────────────────────────────────────────────

echo ""
echo "=== create_mr.sh ==="

test_create_mr_dry_run() {
  local repo
  repo=$(create_test_repo "dry-run-repo")
  cd "$repo"
  echo "## Test body" > "$TMP_BASE/body.md"
  local result
  result=$(bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body.md" \
    --dry-run 2>&1)
  assert_exit_code "dry run exits 0" 0 $?
  assert_contains "dry run shows target" "main" "$result"
  assert_contains "dry run shows title" "feat(test): add test" "$result"
  assert_contains "dry run shows body preview" "Test body" "$result"
}
test_create_mr_dry_run

test_create_mr_missing_target() {
  local repo
  repo=$(create_test_repo "missing-target")
  cd "$repo"
  echo "body" > "$TMP_BASE/body2.md"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/create_mr.sh" \
    --title "feat: test" \
    --body-file "$TMP_BASE/body2.md" 2>&1)
  code=$?
  set -e
  assert_exit_code "missing target-branch exits 1" 1 "$code"
}
test_create_mr_missing_target

test_create_mr_missing_title() {
  local repo
  repo=$(create_test_repo "missing-title")
  cd "$repo"
  echo "body" > "$TMP_BASE/body3.md"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --body-file "$TMP_BASE/body3.md" 2>&1)
  code=$?
  set -e
  assert_exit_code "missing title exits 1" 1 "$code"
}
test_create_mr_missing_title

test_create_mr_missing_body_file() {
  local repo
  repo=$(create_test_repo "missing-body")
  cd "$repo"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat: test" \
    --body-file "$TMP_BASE/nonexistent.md" 2>&1)
  code=$?
  set -e
  assert_exit_code "missing body file exits 1" 1 "$code"
}
test_create_mr_missing_body_file

# ─── Tests: detect_target_branch.sh ───────────────────────────────────────────

echo ""
echo "=== detect_target_branch.sh ==="

test_detect_branch_explicit_exists() {
  local repo
  repo=$(create_test_repo "explicit-branch")
  cd "$repo"
  # main branch exists (created by git init default)
  local main_branch
  main_branch=$(git branch --show-current 2>/dev/null || echo "")
  # The repo has main or master from init, then we're on feat/test-feature
  # Let's create a known branch
  git branch staging 2>/dev/null || true
  local result
  result=$(bash "$SCRIPTS_DIR/detect_target_branch.sh" --branch staging 2>&1)
  assert_exit_code "explicit existing branch exits 0" 0 $?
  assert_eq "returns correct branch" "staging" "$result"
}
test_detect_branch_explicit_exists

test_detect_branch_explicit_not_found() {
  local repo
  repo=$(create_test_repo "bad-branch")
  cd "$repo"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/detect_target_branch.sh" --branch nonexistent-branch 2>&1)
  code=$?
  set -e
  assert_exit_code "nonexistent branch exits 1" 1 "$code"
  assert_contains "error mentions not found" "not found" "$result"
}
test_detect_branch_explicit_not_found

# ─── Tests: upload_media.sh ───────────────────────────────────────────────────

echo ""
echo "=== upload_media.sh ==="

test_upload_no_args() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/upload_media.sh" 2>&1)
  code=$?
  set -e
  assert_exit_code "no args exits 1" 1 "$code"
}
test_upload_no_args

test_upload_nonexistent_file() {
  local repo
  repo=$(create_test_repo "upload-nonexist")
  cd "$repo"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/upload_media.sh" "/tmp/nonexistent-file-12345.png" 2>&1)
  code=$?
  set -e
  # In test env, glab is not available → script exits 1 with "glab CLI not found"
  # OR if glab is available but not authed, it will error on project ID
  assert_exit_code "upload without glab exits 1" 1 "$code"
  assert_contains "error mentions glab" "glab" "$result"
}
test_upload_nonexistent_file

# ─── Tests: build_multipart.py (binary-safe multipart body) ──────────────────

echo ""
echo "=== build_multipart.py ==="

MPART_PY="$SCRIPTS_DIR/build_multipart.py"

# 1x1 transparent PNG fixture, assembled at runtime (byte-exact, no binary literal).
PNG_1X1="$TMP_BASE/1x1.png"
python3 - "$PNG_1X1" <<'PY'
import struct, sys, zlib


def chunk(tag, data):
    c = tag + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)


png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
    + chunk(b"IEND", b"")
)
open(sys.argv[1], "wb").write(png)
PY

validate_multipart() {
  # $1 = body file, $2 = boundary, $3 = expected payload file (optional)
  python3 - "$1" "$2" "${3:-}" <<'PY'
import sys

body_path, boundary, orig_path = sys.argv[1], sys.argv[2], sys.argv[3]
raw = open(body_path, "rb").read()
opening = ("--" + boundary).encode()
closing = ("\r\n--" + boundary + "--\r\n").encode()
assert raw.startswith(opening + b"\r\n"), f"body must open with the boundary, got {raw[:40]!r}"
assert raw.endswith(closing), "body must close with --boundary--"
assert b'Content-Disposition: form-data; name="file";' in raw, "missing form-data disposition"
assert b"Content-Type: image/png" in raw, "missing image/png part header"
if orig_path:
    orig = open(orig_path, "rb").read()
    head, _, rest = raw.partition(b"\r\n\r\n")
    payload = rest[: -len(closing)]
    assert payload == orig, f"payload not byte-exact: {payload!r} vs {orig!r}"
PY
}

test_multipart_structure() {
  local body="$TMP_BASE/body1.multipart"
  local boundary
  boundary=$(python3 "$MPART_PY" --file "$PNG_1X1" --out "$body")
  assert_contains "boundary printed on stdout" "aurora" "$boundary"
  validate_multipart "$body" "$boundary" "$PNG_1X1"
  assert_contains "disposition names the file" 'filename="1x1.png"' "$(cat "$body")"
}
test_multipart_structure

test_multipart_binary_roundtrip() {
  # NUL bytes + CR/LF inside the payload must survive byte-exact (the reason
  # the body is built in Python, not shell).
  local binfile="$TMP_BASE/binary.dat"
  local body="$TMP_BASE/body2.multipart"
  printf 'a\x00b\r\n\x00\xff\xfe' > "$binfile"
  local boundary
  boundary=$(python3 "$MPART_PY" --file "$binfile" --out "$body")
  python3 - "$body" "$boundary" "$binfile" <<'PY'
import sys

body_path, boundary, orig_path = sys.argv[1], sys.argv[2], sys.argv[3]
raw = open(body_path, "rb").read()
orig = open(orig_path, "rb").read()
closing = ("\r\n--" + boundary + "--\r\n").encode()
head, _, rest = raw.partition(b"\r\n\r\n")
payload = rest[: -len(closing)]
assert payload == orig, f"binary payload altered: {payload!r} vs {orig!r}"
PY
}
test_multipart_binary_roundtrip

test_multipart_content_types() {
  local txt="$TMP_BASE/note.txt"
  local body="$TMP_BASE/body5.multipart"
  printf 'hello' > "$txt"
  python3 "$MPART_PY" --file "$txt" --out "$body" >/dev/null
  assert_contains "txt maps to text/plain" "Content-Type: text/plain" "$(cat "$body")"
  local unk="$TMP_BASE/blob.xyz123"
  printf 'x' > "$unk"
  python3 "$MPART_PY" --file "$unk" --out "$body" >/dev/null
  assert_contains "unknown extension maps to octet-stream" "Content-Type: application/octet-stream" "$(cat "$body")"
}
test_multipart_content_types

test_multipart_filename_sanitized() {
  # A quote in the filename must not break the quoted Content-Disposition.
  local weird="$TMP_BASE/say \"hi\".png"
  local body="$TMP_BASE/body3.multipart"
  printf 'x' > "$weird"
  python3 "$MPART_PY" --file "$weird" --out "$body" >/dev/null
  assert_contains "quotes stripped from filename" 'filename="say hi.png"' "$(cat "$body")"
  # Backslash = quoted-string escape (RFC 2183), CR/LF = header injection —
  # all three must be stripped from the disposition filename.
  local hostile="$TMP_BASE/bad\\slash"$'\r\n'"crlf.png"
  printf 'x' > "$hostile"
  python3 "$MPART_PY" --file "$hostile" --out "$body" >/dev/null
  assert_contains "backslash + CRLF stripped from filename" 'filename="badslashcrlf.png"' "$(cat "$body")"
}
test_multipart_filename_sanitized

test_multipart_missing_file() {
  local result code
  set +e
  result=$(python3 "$MPART_PY" --file "$TMP_BASE/does-not-exist.png" --out "$TMP_BASE/body4.multipart" 2>&1)
  code=$?
  set -e
  assert_exit_code "missing file exits 1" 1 "$code"
  assert_contains "error mentions not found" "not found" "$result"
}
test_multipart_missing_file

test_upload_no_gh_flag() {
  # Regression guard: gh CLI syntax `-F file=@...` is NOT glab syntax (glab
  # --field/--raw-field produce JSON-encoded fields) — it caused systematic
  # HTTP 400 on every upload.
  local content
  content=$(cat "$SCRIPTS_DIR/upload_media.sh")
  if grep -qF -- '-F "file=@' "$SCRIPTS_DIR/upload_media.sh"; then
    TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
    FAIL=$((FAIL + 1))
    FAILED_ASSERTIONS=$((FAILED_ASSERTIONS + 1))
    echo "  FAIL: upload_media.sh uses the gh-style -F flag (glab has no multipart -F)"
  else
    TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
    PASS=$((PASS + 1))
    echo "  PASS: upload_media.sh no longer uses the gh-style -F flag"
  fi
  assert_contains "upload sends body via glab --input" "--input" "$content"
  assert_contains "upload builds body via build_multipart.py" "build_multipart.py" "$content"
}
test_upload_no_gh_flag

# ─── Tests: build_comparison_table.sh ────────────────────────────────────────

echo ""
echo "=== build_comparison_table.sh ==="

test_table_basic() {
  local result
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$BEFORE_MD" --after "$AFTER_MD")
  assert_exit_code "basic table exits 0" 0 $?
  assert_contains "header has default labels" "| Avant | Après |" "$result"
  assert_contains "separator row present" "| ------ | ------ |" "$result"
  assert_contains "row contains before snippet" "$BEFORE_MD" "$result"
  assert_contains "row contains after snippet" "$AFTER_MD" "$result"
  assert_contains "before and after on the same row" "| ${BEFORE_MD} | ${AFTER_MD} |" "$result"
  local first_line
  first_line=$(echo "$result" | head -1)
  assert_eq "first line is the table header (no caption)" "| Avant | Après |" "$first_line"
}
test_table_basic

test_table_with_caption() {
  local result
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$BEFORE_MD" --after "$AFTER_MD" --caption "Formulaire de qualité")
  assert_exit_code "table with caption exits 0" 0 $?
  assert_contains "caption line present" "**Formulaire de qualité :**" "$result"
  assert_contains "table still present after caption" "| Avant | Après |" "$result"
}
test_table_with_caption

test_table_custom_labels() {
  local result
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$BEFORE_MD" --after "$AFTER_MD" --before-label "Before" --after-label "After")
  assert_exit_code "custom labels exit 0" 0 $?
  assert_contains "custom before label" "| Before | After |" "$result"
}
test_table_custom_labels

test_table_missing_after() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$BEFORE_MD" 2>&1)
  code=$?
  set -e
  assert_exit_code "missing --after exits 1" 1 "$code"
  assert_contains "error mentions after required" "--after is required" "$result"
}
test_table_missing_after

test_table_visual_only() {
  # New component: no previous state to show — single-column "Visuel" table.
  local result
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --after "$AFTER_MD" --caption "Nouveau composant")
  assert_exit_code "visual-only table exits 0" 0 $?
  assert_contains "visual-only caption present" "**Nouveau composant :**" "$result"
  local first_line
  first_line=$(echo "$result" | grep -F '|' | head -1)
  assert_eq "visual-only header is Visuel" "| Visuel |" "$first_line"
  assert_contains "visual-only row contains after snippet" "| ${AFTER_MD} |" "$result"
  local avant_left
  avant_left=$(echo "$result" | grep -F '| Avant' || true)
  assert_eq "no Avant column in visual-only mode" "" "$avant_left"
}
test_table_visual_only

test_table_visual_only_custom_label() {
  local result
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --after "$AFTER_MD" --after-label "Rendu final")
  assert_exit_code "visual-only custom label exits 0" 0 $?
  assert_contains "visual-only custom header" "| Rendu final |" "$result"
}
test_table_visual_only_custom_label

test_table_empty_before() {
  # Contract: empty --before == absent (new component) → single-column Visuel.
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "" --after "$AFTER_MD" 2>&1)
  code=$?
  set -e
  assert_exit_code "empty --before treated as absent (visual-only) exits 0" 0 "$code"
  local first_line
  first_line=$(echo "$result" | grep -F '|' | head -1)
  assert_eq "empty --before yields Visuel header" "| Visuel |" "$first_line"
}
test_table_empty_before

test_table_invalid_snippet() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "not a markdown snippet" --after "$AFTER_MD" 2>&1)
  code=$?
  set -e
  assert_exit_code "non-upload snippet exits 1" 1 "$code"
  assert_contains "error mentions snippet shape" "upload Markdown snippet" "$result"
}
test_table_invalid_snippet

test_table_pipe_in_caption() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$BEFORE_MD" --after "$AFTER_MD" --caption "bad | caption" 2>&1)
  code=$?
  set -e
  assert_exit_code "pipe in caption exits 1" 1 "$code"
  assert_contains "error mentions pipe" "pipe" "$result"
}
test_table_pipe_in_caption

test_table_pipe_in_snippet() {
  # GitLab alt-text derives from the file name: "avant|apres.png" is real.
  local bad_before="![avant|apres](/uploads/hash/before.png)"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$bad_before" --after "$AFTER_MD" 2>&1)
  code=$?
  set -e
  assert_exit_code "pipe in snippet exits 1" 1 "$code"
  assert_contains "error mentions table breaker" "pipe or a newline" "$result"
}
test_table_pipe_in_snippet

test_table_newline_in_snippet() {
  local bad_before=$'![avant](/uploads/hash/before.png)\nextra line'
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$bad_before" --after "$AFTER_MD" 2>&1)
  code=$?
  set -e
  assert_exit_code "newline in snippet exits 1" 1 "$code"
}
test_table_newline_in_snippet

test_table_local_path_rejected() {
  # Only GitLab upload snippets are accepted: a local path would render
  # as a broken image in the MR.
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "![avant](local-before.png)" --after "$AFTER_MD" 2>&1)
  code=$?
  set -e
  assert_exit_code "local path snippet exits 1" 1 "$code"
  assert_contains "error mentions upload snippet shape" "GitLab upload Markdown snippet" "$result"
}
test_table_local_path_rejected

test_table_invalid_after() {
  # Mono-column mode: the AFTER snippet is the only one — its fail-closed
  # validation must be exercised too.
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --after "not a markdown snippet" 2>&1)
  code=$?
  set -e
  assert_exit_code "invalid --after (visual-only) exits 1" 1 "$code"
  assert_contains "error mentions after snippet shape" "--after does not look like a GitLab upload Markdown snippet" "$result"
}
test_table_invalid_after

test_table_local_path_after_rejected() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --after "![apres](local-after.png)" 2>&1)
  code=$?
  set -e
  assert_exit_code "local path --after (visual-only) exits 1" 1 "$code"
}
test_table_local_path_after_rejected

test_table_pipe_in_after() {
  local bad_after="![avant|apres](/uploads/hash/after.png)"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --after "$bad_after" 2>&1)
  code=$?
  set -e
  assert_exit_code "pipe in --after exits 1" 1 "$code"
  assert_contains "error mentions table breaker" "pipe or a newline" "$result"
}
test_table_pipe_in_after

test_table_truncated_option() {
  # An option without its value (last argument) must fail closed with the
  # script's own message, not a cryptic bash "shift count out of range".
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$BEFORE_MD" --after "$AFTER_MD" --caption 2>&1)
  code=$?
  set -e
  assert_exit_code "truncated option exits 1" 1 "$code"
  assert_contains "error mentions missing value" "Missing value" "$result"
}
test_table_truncated_option

test_table_no_args() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" 2>&1)
  code=$?
  set -e
  assert_exit_code "no args exits 1" 1 "$code"
}
test_table_no_args

test_table_unknown_arg() {
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --unknown x --before "$BEFORE_MD" --after "$AFTER_MD" 2>&1)
  code=$?
  set -e
  assert_exit_code "unknown arg exits 1" 1 "$code"
  assert_contains "error mentions unknown argument" "Unknown argument" "$result"
}
test_table_unknown_arg

test_table_no_network_calls() {
  # The assembler must never call glab: it must work in a non-Git directory.
  local result code
  cd "$TMP_BASE"
  set +e
  result=$(bash "$SCRIPTS_DIR/build_comparison_table.sh" --before "$BEFORE_MD" --after "$AFTER_MD" 2>&1)
  code=$?
  set -e
  assert_exit_code "works outside a Git repo (no glab/network dependency)" 0 "$code"
  assert_contains "table assembled outside a Git repo" "| Avant | Après |" "$result"
}
test_table_no_network_calls

# ─── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  Tests:        $((PASS + FAIL))"
echo "  Passed:       $PASS"
echo "  Failed:       $FAIL"
echo "  Assertions:   $TOTAL_ASSERTIONS"
echo "  Failed assertions: $FAILED_ASSERTIONS"
echo "============================================"

if [ $FAIL -gt 0 ]; then
  exit 1
fi

exit 0
