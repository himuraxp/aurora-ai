#!/bin/bash
# Fake Orca CLI for new-worktree tests — driven by NW_FAKE_DIR.
# Every invocation's args are appended to $NW_FAKE_DIR/args.log so tests
# can assert the exact flags passed (same pattern as task-workflow's fixture).
set -u
FAKE_DIR="${NW_FAKE_DIR:?NW_FAKE_DIR must be set}"
printf '%s\n' "$*" >> "$FAKE_DIR/args.log"

sub="$(printf '%s %s' "${1:-}" "${2:-}" | xargs)"

case "$sub" in
  "status")
    if [ -f "$FAKE_DIR/runtime-down" ]; then
      echo "appRunning: false"
      echo "runtimeReachable: false"
    else
      echo "appRunning: true"
      echo "runtimeReachable: true"
    fi
    ;;
  "worktree create")
    if [ -f "$FAKE_DIR/create-then-fail" ]; then
      branch=""
      prev=""
      for a in "$@"; do
        if [ "$prev" = "--branch" ]; then branch="$a"; fi
        prev="$a"
      done
      git branch "$branch" >/dev/null 2>&1
      echo '{"error": {"code": "internal", "message": "failed after creating the branch"}}' >&2
      exit 1
    fi
    if [ -f "$FAKE_DIR/create-fails" ]; then
      echo '{"error": {"code": "selector_not_found", "message": "selector_not_found"}}' >&2
      exit 1
    fi
    if [ -f "$FAKE_DIR/create-json-null" ]; then
      echo "null"
      exit 0
    fi
    if [ -f "$FAKE_DIR/create-json-array" ]; then
      echo "[]"
      exit 0
    fi
    if [ -f "$FAKE_DIR/create-json-result-string" ]; then
      echo '{"ok": true, "result": "x"}'
      exit 0
    fi
    if [ -f "$FAKE_DIR/create-json-worktree-string" ]; then
      echo '{"ok": true, "result": {"worktree": "/p", "launch": "chat"}}'
      exit 0
    fi
    if [ -f "$FAKE_DIR/create-badjson" ]; then
      echo "not json at all"
      exit 0
    fi
    if [ -f "$FAKE_DIR/create-no-path" ]; then
      echo '{"ok": true, "result": {}}'
      exit 0
    fi
    if [ -f "$FAKE_DIR/create-ghost-path" ]; then
      echo '{"ok": true, "result": {"worktree": {"path": "/nw-fake-ghost-wt-does-not-exist"}, "launch": {"outcome": {"kind": "structured chat"}}}}'
      exit 0
    fi
    name=""
    prev=""
    for a in "$@"; do
      if [ "$prev" = "--name" ]; then name="$a"; fi
      prev="$a"
    done
    mkdir -p "$FAKE_DIR/orca-ws/$name"
    printf '{"ok": true, "result": {"worktree": {"path": "%s/orca-ws/%s"}, "launch": {"outcome": {"kind": "structured chat"}, "receipt": {"detail": "opened as chat"}}}}\n' \
      "$FAKE_DIR" "$name"
    ;;
  *)
    echo "unexpected fake-orca call: $*" >&2
    exit 3
    ;;
esac
