#!/usr/bin/env python3
"""
merge-opencode-json.py — Security Gate S-01 follow-up (dette install.sh, WARNINGS 2026-10-06).

Deep-merges the repo reference opencode.json INTO the live one:
  base      = live  (preserves runtime-only keys: permissions granted on the fly, etc.)
  overrides = repo  (repo wins on conflicts: repo fixes propagate)

Rationale: install.sh used to blind-copy repo -> live, silently dropping
runtime-granted permissions on every `npm run update`. This helper keeps
live-only keys and applies repo changes on top. Generic JSON deep-merge,
repo-prevail semantics; arrays are replaced by the repo value (repo is the
reference); live-only object keys are preserved recursively.

Usage:
  merge-opencode-json.py --repo <repo.json> --live <live.json> [--write-live] [--report-only]

Exit codes: 0 = ok (unchanged or merged), 1 = error (live untouched).
With --write-live: writes the merge + backup file (timestamp-pid, mode preserved).
Without it: report only (dry-run).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime


def deep_merge(base: object, override: object) -> object:
    """Merge override into base. Repo (override) wins on conflicts; live-only keys survive."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = deep_merge(out[k], v) if k in out else v
        return out
    # Non-dict (scalar, list, null): repo replaces.
    return override


def walk_live_only(base: object, override: object, path: str = "") -> list[str]:
    """Report live-only keys (present in live, absent from repo) for the summary."""
    if isinstance(base, dict):
        only: list[str] = []
        for k, v in base.items():
            p = f"{path}.{k}" if path else k
            if isinstance(override, dict) and k in override:
                only.extend(walk_live_only(v, override[k], p))
            else:
                only.append(p)
        return only
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--live", required=True)
    ap.add_argument("--write-live", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    try:
        with open(args.repo, "r", encoding="utf-8") as f:
            repo = json.load(f)
        with open(args.live, "r", encoding="utf-8") as f:
            live = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"merge-opencode-json: cannot read inputs: {e}", file=sys.stderr)
        return 1

    merged = deep_merge(live, repo)

    if merged == live:
        print("merge-opencode-json: unchanged (live already consistent with repo)")
        return 0

    changed = [k for k in sorted(set(repo) | set(live))
               if k in repo and (k not in live or live[k] != repo[k])]
    live_only = walk_live_only(live, repo)

    print(f"merge-opencode-json: repo keys applied over live: {', '.join(changed) if changed else '(none)'}")
    if live_only:
        print(f"merge-opencode-json: live-only keys preserved ({len(live_only)}): "
              + ", ".join(live_only[:12]) + (" …" if len(live_only) > 12 else ""))

    if args.report_only or not args.write_live:
        print("merge-opencode-json: report-only (pass --write-live to apply)")
        return 0

    # Atomic write with backup (timestamp-pid, mode preserved — convention from configure-models).
    backup = f"{args.live}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    st = os.stat(args.live)
    try:
        with open(backup, "w", encoding="utf-8") as f:
            json.dump(live, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(backup, st.st_mode & 0o777)
        tmp = f"{args.live}.tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, st.st_mode & 0o777)
        os.replace(tmp, args.live)
    except OSError as e:
        print(f"merge-opencode-json: write failed, live left untouched: {e}", file=sys.stderr)
        return 1

    print(f"merge-opencode-json: merged → {args.live} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
