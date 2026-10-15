#!/bin/bash
# Fake Orca CLI for task-workflow tests (tw_orca adapter).
# Behaviour is driven by TW_FAKE_DIR fixtures; every invocation's args are
# logged to $TW_FAKE_DIR/args.log so tests can assert the exact flags passed.
set -u
FAKE_DIR="${TW_FAKE_DIR:?TW_FAKE_DIR must be set}"
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
  "worktree list")
    if [ -f "$FAKE_DIR/worktrees.json" ]; then
      cat "$FAKE_DIR/worktrees.json"
    else
      echo '{"result": {"worktrees": []}}'
    fi
    ;;
  "terminal create")
    if [ -f "$FAKE_DIR/uncertain-create" ]; then
      # Simulated real-world quirk: exit 0 but no machine-readable handle.
      echo '{"ok": true, "result": {}}'
    else
      echo '{"ok": true, "result": {"terminal": {"handle": "term_fake_1", "paneKey": "tab1:pane1"}}}'
    fi
    ;;
  "terminal close")
    echo "Closed terminal $3. PTY killed."
    ;;
  "slow status")
    sleep 5
    echo "runtimeReachable: true"
    ;;
  *)
    echo "fake-orca: unknown command: $*" >&2
    exit 9
    ;;
esac
