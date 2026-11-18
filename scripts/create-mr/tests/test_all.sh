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

# ─── Tests: check_missing_translations.sh ─────────────────────────────────────

echo ""
echo "=== check_missing_translations.sh ==="

CHECK_SCRIPT="$SCRIPTS_DIR/check_missing_translations.sh"

set_test_base_branch() {
  if git rev-parse --verify --quiet refs/heads/main &>/dev/null; then
    TRANSLATIONS_BASE="main"
  else
    TRANSLATIONS_BASE="master"
  fi
}

create_translation_repo() {
  local repo
  repo=$(create_test_repo "$1")
  cd "$repo"
  mkdir -p src/translations
  cat >src/translations/fr_FR.json <<'EOF'
{
  "Bienvenue sur la page d’accueil": "Bienvenue sur la page d’accueil",
  "$count$ élément sélectionné": "$count$ élément sélectionné",
  "$count$ {count, plural, one{entrée} other{entrées}}": "$count$ {count, plural, one{entrée} other{entrées}}",
  "L'école est fermée": "L'école est fermée"
}
EOF
  git add src/translations/fr_FR.json
  git commit --quiet -m "chore: seed translations"
  echo "$repo"
}

json_field() {
  echo "$1" | python3 -c "import json,sys; print(json.load(sys.stdin)['$2'])"
}

test_translations_missing_detected() {
  local repo
  repo=$(create_translation_repo "trans-missing")
  cd "$repo"
  set_test_base_branch
  mkdir -p src/app
  cat >src/app/home.component.html <<'EOF'
<h1>{{ 'Titre totalement inconnu du JSON' | transloco }}</h1>
EOF
  cat >src/app/home.component.ts <<'EOF'
export class HomeComponent {
  label = translate('Autre chaîne inconnue du JSON');
}
EOF
  git add src/app
  git commit --quiet -m "feat: add home component"
  local result action count
  result=$(bash "$CHECK_SCRIPT" --target-branch "$TRANSLATIONS_BASE" 2>&1)
  assert_exit_code "missing strings exits 0" 0 $?
  action=$(json_field "$result" action)
  count=$(json_field "$result" missingCount)
  assert_eq "missing strings action is label" "label" "$action"
  assert_eq "missing strings count is 2" "2" "$count"
  assert_contains "html literal reported" "Titre totalement inconnu du JSON" "$result"
  assert_contains "ts literal reported" "Autre chaîne inconnue du JSON" "$result"
}
test_translations_missing_detected

test_translations_known_strings_not_flagged() {
  local repo
  repo=$(create_translation_repo "trans-known")
  cd "$repo"
  set_test_base_branch
  mkdir -p src/app
  cat >src/app/known.component.ts <<'EOF'
export class KnownComponent {
  title = translate('Bienvenue sur la page d’accueil');
  countLabel = translate('$count$ élément sélectionné', { count: 2 });
  entries = translate('$count$ {count, plural, one{entrée} other{entrées}}', {
    count: total(),
  });
}
EOF
  git add src/app
  git commit --quiet -m "feat: add known component"
  local result action count extracted
  result=$(bash "$CHECK_SCRIPT" --target-branch "$TRANSLATIONS_BASE" 2>&1)
  action=$(json_field "$result" action)
  count=$(json_field "$result" missingCount)
  extracted=$(json_field "$result" extractedCount)
  assert_eq "known strings action is none" "none" "$action"
  assert_eq "known strings missingCount is 0" "0" "$count"
  assert_eq "known strings extractedCount is 3" "3" "$extracted"
}
test_translations_known_strings_not_flagged

test_translations_escaped_apostrophe_unescaped() {
  local repo
  repo=$(create_translation_repo "trans-escaped")
  cd "$repo"
  set_test_base_branch
  mkdir -p src/app
  cat >src/app/school.component.ts <<'EOF'
export class SchoolComponent {
  label = translate('L\'école est fermée');
}
EOF
  git add src/app
  git commit --quiet -m "feat: add school component"
  local result action count
  result=$(bash "$CHECK_SCRIPT" --target-branch "$TRANSLATIONS_BASE" 2>&1)
  action=$(json_field "$result" action)
  count=$(json_field "$result" missingCount)
  assert_eq "escaped apostrophe unescaped and found in keys" "none" "$action"
  assert_eq "escaped apostrophe missingCount is 0" "0" "$count"
}
test_translations_escaped_apostrophe_unescaped

test_translations_removed_lines_not_flagged() {
  local repo
  repo=$(create_translation_repo "trans-removed")
  cd "$repo"
  set_test_base_branch
  mkdir -p src/app
  cat >src/app/legacy.component.ts <<'EOF'
export class LegacyComponent {
  label = translate('Chaîne retirée absente du JSON');
}
EOF
  git add src/app
  git commit --quiet -m "feat: add legacy component"
  cat >src/app/legacy.component.ts <<'EOF'
export class LegacyComponent {
}
EOF
  git add src/app
  git commit --quiet -m "refactor: drop translated label"
  local result action count
  result=$(bash "$CHECK_SCRIPT" --target-branch "$TRANSLATIONS_BASE" 2>&1)
  action=$(json_field "$result" action)
  count=$(json_field "$result" missingCount)
  assert_eq "removed lines action is none" "none" "$action"
  assert_eq "removed lines missingCount is 0" "0" "$count"
}
test_translations_removed_lines_not_flagged

test_translations_specs_excluded() {
  local repo
  repo=$(create_translation_repo "trans-specs")
  cd "$repo"
  set_test_base_branch
  mkdir -p src/app
  cat >src/app/widget.component.spec.ts <<'EOF'
export const SPEC_LABEL = translate('Chaîne uniquement dans les specs');
EOF
  git add src/app
  git commit --quiet -m "test: add spec"
  local result action count
  result=$(bash "$CHECK_SCRIPT" --target-branch "$TRANSLATIONS_BASE" 2>&1)
  action=$(json_field "$result" action)
  count=$(json_field "$result" missingCount)
  assert_eq "spec files excluded action" "skipped-no-changed-files" "$action"
  assert_eq "spec files excluded missingCount is 0" "0" "$count"
}
test_translations_specs_excluded

test_translations_no_translations_file() {
  local repo
  repo=$(create_test_repo "trans-no-file")
  cd "$repo"
  set_test_base_branch
  mkdir -p src/app
  echo "export const X = translate('N importe quoi');" >src/app/x.component.ts
  git add src/app
  git commit --quiet -m "feat: add component without translations"
  local result action
  result=$(bash "$CHECK_SCRIPT" --target-branch "$TRANSLATIONS_BASE" 2>&1)
  assert_exit_code "no translations file exits 0" 0 $?
  action=$(json_field "$result" action)
  assert_eq "no translations file action" "skipped-no-translations-file" "$action"
}
test_translations_no_translations_file

test_translations_no_changed_files() {
  local repo
  repo=$(create_translation_repo "trans-no-changes")
  cd "$repo"
  set_test_base_branch
  echo "readme update" >>README.md
  git add README.md
  git commit --quiet -m "docs: update readme"
  local result action
  result=$(bash "$CHECK_SCRIPT" --target-branch "$TRANSLATIONS_BASE" 2>&1)
  assert_exit_code "no changed source files exits 0" 0 $?
  action=$(json_field "$result" action)
  assert_eq "no changed source files action" "skipped-no-changed-files" "$action"
}
test_translations_no_changed_files

test_translations_override_file() {
  local repo
  repo=$(create_test_repo "trans-override")
  cd "$repo"
  set_test_base_branch
  mkdir -p i18n
  cat >i18n/custom_fr.json <<'EOF'
{
  "Chaîne custom présente": "Chaîne custom présente"
}
EOF
  mkdir -p src/app
  echo "export const Y = translate('Chaîne custom présente');" >src/app/y.component.ts
  git add i18n src
  git commit --quiet -m "feat: custom i18n layout"
  local result action count
  result=$(bash "$CHECK_SCRIPT" \
    --target-branch "$TRANSLATIONS_BASE" \
    --translations-file i18n/custom_fr.json 2>&1)
  action=$(json_field "$result" action)
  count=$(json_field "$result" missingCount)
  assert_eq "override file action is none" "none" "$action"
  assert_eq "override file missingCount is 0" "0" "$count"
  assert_contains "override file path reported" "i18n/custom_fr.json" "$result"
}
test_translations_override_file

test_translations_max_examples() {
  local repo
  repo=$(create_translation_repo "trans-max")
  cd "$repo"
  set_test_base_branch
  mkdir -p src/app
  cat >src/app/bulk.component.ts <<'EOF'
export const A = translate('Manquante une');
export const B = translate('Manquante deux');
export const C = translate('Manquante trois');
export const D = translate('Manquante quatre');
export const E = translate('Manquante cinq');
EOF
  git add src/app
  git commit --quiet -m "feat: bulk strings"
  local result count truncated example_count
  result=$(bash "$CHECK_SCRIPT" \
    --target-branch "$TRANSLATIONS_BASE" \
    --max-examples 2 2>&1)
  count=$(json_field "$result" missingCount)
  truncated=$(json_field "$result" missingTruncated)
  example_count=$(echo "$result" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['missing']))")
  assert_eq "max examples full count kept" "5" "$count"
  assert_eq "max examples flag set" "True" "$truncated"
  assert_eq "examples truncated to 2" "2" "$example_count"
}
test_translations_max_examples

test_translations_unknown_branch() {
  local repo
  repo=$(create_translation_repo "trans-bad-branch")
  cd "$repo"
  set_test_base_branch
  local result code
  set +e
  result=$(bash "$CHECK_SCRIPT" --target-branch nonexistent-base-branch 2>&1)
  code=$?
  set -e
  assert_exit_code "unknown base branch exits 1" 1 "$code"
  assert_contains "unknown branch mentions fetch" "git fetch" "$result"
}
test_translations_unknown_branch

test_translations_missing_target_arg() {
  local result code
  set +e
  result=$(bash "$CHECK_SCRIPT" 2>&1)
  code=$?
  set -e
  assert_exit_code "missing --target-branch exits 1" 1 "$code"
  assert_contains "missing target mentions required" "required" "$result"
}
test_translations_missing_target_arg

test_translations_unknown_arg() {
  local result code
  set +e
  result=$(bash "$CHECK_SCRIPT" --unknown x 2>&1)
  code=$?
  set -e
  assert_exit_code "unknown arg exits 1" 1 "$code"
  assert_contains "unknown arg mentioned" "Unknown argument" "$result"
}
test_translations_unknown_arg

test_translations_base_removed_not_flagged() {
  # Regression net for the added-lines filter: a string present on the BASE
  # branch and REMOVED by the feature branch must never produce a label —
  # the diff shows it as '-' lines only, and '-' lines are not scanned.
  local repo
  repo=$(create_translation_repo "trans-base-removed")
  cd "$repo"
  set_test_base_branch
  mkdir -p src/app
  cat >src/app/old.component.ts <<'EOF'
export class OldComponent {
  label = translate('Chaîne héritée jamais synchronisée');
}
EOF
  git add src/app
  git commit --quiet -m "feat: old component with unsynced string"
  git checkout --quiet -b feat/remove-legacy
  cat >src/app/old.component.ts <<'EOF'
export class OldComponent {
}
EOF
  git add src/app
  git commit --quiet -m "refactor: drop unsynced label"
  local result action count
  result=$(bash "$CHECK_SCRIPT" --target-branch feat/test-feature 2>&1)
  action=$(json_field "$result" action)
  count=$(json_field "$result" missingCount)
  assert_eq "base-present removed action is none" "none" "$action"
  assert_eq "base-present removed missingCount is 0" "0" "$count"
}
test_translations_base_removed_not_flagged

test_translations_override_file_at_root() {
  # A root-level --translations-file yields TRANS_DIR="." — the exclusion
  # pathspec must be skipped, not built as ':!./**' (which would exclude
  # everything and silently return skipped-no-changed-files).
  local repo
  repo=$(create_test_repo "trans-root-override")
  cd "$repo"
  set_test_base_branch
  cat >fr.json <<'EOF'
{
  "Chaîne racine présente": "Chaîne racine présente"
}
EOF
  mkdir -p src/app
  echo "export const Z = translate('Chaîne racine présente');" >src/app/z.component.ts
  git add fr.json src
  git commit --quiet -m "feat: root-level translations"
  local result action count
  result=$(bash "$CHECK_SCRIPT" \
    --target-branch "$TRANSLATIONS_BASE" \
    --translations-file fr.json 2>&1)
  action=$(json_field "$result" action)
  count=$(json_field "$result" missingCount)
  assert_eq "root override action is none" "none" "$action"
  assert_eq "root override missingCount is 0" "0" "$count"
}
test_translations_override_file_at_root

test_translations_invalid_max_examples() {
  local repo
  repo=$(create_translation_repo "trans-bad-max")
  cd "$repo"
  set_test_base_branch
  local result code
  set +e
  result=$(bash "$CHECK_SCRIPT" --target-branch "$TRANSLATIONS_BASE" --max-examples abc 2>&1)
  code=$?
  set -e
  assert_exit_code "non-numeric max-examples exits 1" 1 "$code"
  assert_contains "invalid max-examples mentioned" "positive integer" "$result"
}
test_translations_invalid_max_examples

test_translations_never_calls_glab() {
  if grep -qE '(^|[^a-z])glab([^a-z]|$)' "$CHECK_SCRIPT"; then
    TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
    FAIL=$((FAIL + 1))
    FAILED_ASSERTIONS=$((FAILED_ASSERTIONS + 1))
    echo "  FAIL: check_missing_translations.sh must never call glab (local check only)"
  else
    TOTAL_ASSERTIONS=$((TOTAL_ASSERTIONS + 1))
    PASS=$((PASS + 1))
    echo "  PASS: check_missing_translations.sh never calls glab"
  fi
}
test_translations_never_calls_glab

# ─── Tests: create_mr.sh --label ─────────────────────────────────────────────

echo ""
echo "=== create_mr.sh --label ==="

test_create_mr_label_dry_run() {
  local repo
  repo=$(create_test_repo "label-dry-run")
  cd "$repo"
  echo "## Test body" >"$TMP_BASE/body-label.md"
  local result
  result=$(bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body-label.md" \
    --label "Translations::in-progress" \
    --dry-run 2>&1)
  assert_exit_code "label dry run exits 0" 0 $?
  assert_contains "label dry run shows label" "Translations::in-progress" "$result"
  assert_contains "label dry run mentions verification" "verified" "$result"
}
test_create_mr_label_dry_run

test_create_mr_no_label_dry_run() {
  local repo
  repo=$(create_test_repo "no-label-dry-run")
  cd "$repo"
  echo "## Test body" >"$TMP_BASE/body-nolabel.md"
  local result
  result=$(bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body-nolabel.md" \
    --dry-run 2>&1)
  assert_exit_code "no label dry run exits 0" 0 $?
  local label_line
  label_line=$(echo "$result" | grep -F 'Label:' || true)
  assert_eq "no label line without --label" "" "$label_line"
}
test_create_mr_no_label_dry_run

test_create_mr_label_missing_value() {
  local repo
  repo=$(create_test_repo "label-missing-value")
  cd "$repo"
  echo "body" >"$TMP_BASE/body-lm.md"
  local result code
  set +e
  result=$(bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body-lm.md" \
    --label 2>&1)
  code=$?
  set -e
  assert_exit_code "truncated --label exits 1" 1 "$code"
  assert_contains "truncated label mentioned" "Missing value" "$result"
}
test_create_mr_label_missing_value

make_glab_stub() {
  local stub_dir="$1" mode="$2"
  mkdir -p "$stub_dir"
  cat >"$stub_dir/glab" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$stub_dir/glab.log"
if [ "\$1" = "api" ]; then
  case "$mode" in
    found) echo '[{"name":"Translations::in-progress"}]' ;;
    empty) echo '[]' ;;
    errorbody) echo '{"message":"401 Unauthorized"}' ;;
    apifail) exit 1 ;;
  esac
  exit 0
fi
exit 0
EOF
  chmod +x "$stub_dir/glab"
}

test_create_mr_label_real_run_applied() {
  local repo stub_dir
  repo=$(create_test_repo "label-real-applied")
  cd "$repo"
  echo "## Test body" >"$TMP_BASE/body-real1.md"
  stub_dir="$TMP_BASE/stub-applied"
  make_glab_stub "$stub_dir" found
  local result log
  result=$(PATH="$stub_dir:$PATH" bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body-real1.md" \
    --label "Translations::in-progress" 2>&1)
  assert_exit_code "label applied real run exits 0" 0 $?
  assert_contains "label applied reported" "LABEL: applied" "$result"
  log="$(cat "$stub_dir/glab.log")"
  assert_contains "mr create invoked" "mr create" "$log"
  assert_contains "label flag passed to mr create" "-l Translations::in-progress" "$log"
}
test_create_mr_label_real_run_applied

test_create_mr_label_real_run_not_found() {
  local repo stub_dir
  repo=$(create_test_repo "label-real-notfound")
  cd "$repo"
  echo "## Test body" >"$TMP_BASE/body-real2.md"
  stub_dir="$TMP_BASE/stub-notfound"
  make_glab_stub "$stub_dir" empty
  local result log create_line
  result=$(PATH="$stub_dir:$PATH" bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body-real2.md" \
    --label "Translations::in-progress" 2>&1)
  assert_exit_code "label not-found real run exits 0 (never blocking)" 0 $?
  assert_contains "label not-found reported" "LABEL: skipped-label-not-found" "$result"
  log="$(cat "$stub_dir/glab.log")"
  create_line=$(grep -F 'mr create' "$stub_dir/glab.log")
  assert_contains "mr create still invoked" "mr create" "$log"
  assert_eq "no label flag passed to mr create" "" "$(echo "$create_line" | grep -oF -- '-l' || true)"
}
test_create_mr_label_real_run_not_found

test_create_mr_label_real_run_api_error_body() {
  # A JSON error body ({"message":"401 …"}) must be traced as api-error,
  # NOT as label-not-found (wrong follow-up: creating the label would not help).
  local repo stub_dir
  repo=$(create_test_repo "label-real-errorbody")
  cd "$repo"
  echo "## Test body" >"$TMP_BASE/body-real3.md"
  stub_dir="$TMP_BASE/stub-errorbody"
  make_glab_stub "$stub_dir" errorbody
  local result
  result=$(PATH="$stub_dir:$PATH" bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body-real3.md" \
    --label "Translations::in-progress" 2>&1)
  assert_exit_code "label error-body real run exits 0" 0 $?
  assert_contains "json error body traced as api error" "LABEL: skipped-api-error" "$result"
}
test_create_mr_label_real_run_api_error_body

test_create_mr_label_real_run_api_fail() {
  local repo stub_dir
  repo=$(create_test_repo "label-real-apifail")
  cd "$repo"
  echo "## Test body" >"$TMP_BASE/body-real4.md"
  stub_dir="$TMP_BASE/stub-apifail"
  make_glab_stub "$stub_dir" apifail
  local result
  result=$(PATH="$stub_dir:$PATH" bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body-real4.md" \
    --label "Translations::in-progress" 2>&1)
  assert_exit_code "api failure real run exits 0 (never blocking)" 0 $?
  assert_contains "api failure reported" "LABEL: skipped-api-error" "$result"
}
test_create_mr_label_real_run_api_fail

test_create_mr_real_run_no_label() {
  # Covers the bash 3.2 empty-array expansion ${LABEL_ARGS[@]+"..."} under
  # set -u on the real (non-dry-run) path.
  local repo stub_dir
  repo=$(create_test_repo "label-real-nolabel")
  cd "$repo"
  echo "## Test body" >"$TMP_BASE/body-real5.md"
  stub_dir="$TMP_BASE/stub-nolabel"
  make_glab_stub "$stub_dir" found
  local result
  result=$(PATH="$stub_dir:$PATH" bash "$SCRIPTS_DIR/create_mr.sh" \
    --target-branch main \
    --title "feat(test): add test" \
    --body-file "$TMP_BASE/body-real5.md" 2>&1)
  assert_exit_code "no-label real run exits 0" 0 $?
  assert_contains "no label reported" "LABEL: none" "$result"
}
test_create_mr_real_run_no_label

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
