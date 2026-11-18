#!/usr/bin/env python3
"""
setup-mcp-lock.py — Security Gate S-01 follow-up (chantier 7a, WARNINGS 2026-10-07).

Locks npx-based MCP servers locally:
  1. Reads the repo opencode.json (source of truth), extracts `npx -y pkg@version` commands.
  2. Installs the exact pinned packages into ~/.config/opencode/mcp-npm (npm lockfile + node_modules).
  3. Rewrites the commands to local binaries (repo AND live configs, live-only keys preserved).
  4. Verifies every referenced local path exists.

Why: `npx -y pkg@ver` still resolves through the npm registry on every launch —
a registry compromise can swap binaries despite the pinned version. Local
node_modules + package-lock.json (integrity hashes) remove the runtime registry
dependency. Idempotent: rerunning verifies and does nothing when already locked.

Usage: setup-mcp-lock.py [--lockdir DIR] [--repo PATH] [--live PATH]
Exit: 0 = ok, 1 = error (configs left untouched on error).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_REPO = Path.home() / ".config/opencode-config/config/opencode.json"
DEFAULT_LIVE = Path.home() / ".config/opencode/opencode.json"
DEFAULT_LOCKDIR = Path.home() / ".config/opencode/mcp-npm"


def load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path: Path, data: dict) -> None:
    backup = f"{path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    with open(backup, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(backup, os.stat(path).st_mode & 0o777)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, os.stat(path).st_mode & 0o777)
    os.replace(tmp, path)


def split_pkg(token: str) -> tuple[str, str | None]:
    """'@a/b@1.2' -> ('@a/b','1.2'); 'b@1.2' -> ('b','1.2'); 'b' -> ('b', None)."""
    if token.startswith("@"):
        if token.count("@") > 1:
            name, version = token.rsplit("@", 1)
            return name, version
        return token, None
    if "@" in token:
        name, version = token.rsplit("@", 1)
        return name, version
    return token, None


def extract_npx(cfg: dict) -> dict[str, tuple[str, list[str]]]:
    """name -> (pkg@version, args after the package token). Only pinned versions accepted."""
    out: dict[str, tuple[str, list[str]]] = {}
    for name, m in cfg.get("mcp", {}).items():
        cmd = m.get("command", [])
        if len(cmd) >= 3 and cmd[0] == "npx" and cmd[1] == "-y":
            pkg, version = split_pkg(cmd[2])
            if version is None:
                print(f"ERROR: mcp '{name}' uses npx with an unpinned version ({cmd[2]}) — "
                      f"pin it in opencode.json first", file=sys.stderr)
                sys.exit(1)
            out[name] = (cmd[2], list(cmd[3:]))
    return out


def bin_path(lockdir: Path, pkg: str) -> str | None:
    """Resolve the executable path for pkg inside lockdir/node_modules."""
    pj = lockdir / "node_modules" / pkg / "package.json"
    if not pj.is_file():
        return None
    try:
        meta = json.loads(pj.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    binf = meta.get("bin")
    if isinstance(binf, str):
        rel = binf
    elif isinstance(binf, dict) and binf:
        base = pkg.split("/")[-1]
        rel = binf.get(base) or (next(iter(binf.values())) if len(binf) == 1 else None)
        if rel is None:
            return None
    else:
        return None
    candidate = lockdir / "node_modules" / pkg / rel
    return str(candidate) if candidate.is_file() else None


def rewrite_commands(cfg: dict, resolved: dict[str, tuple[str, list[str]]]) -> int:
    """Replace npx commands with local node commands. Returns count of changes."""
    changed = 0
    home_token = "{env:HOME}/.config/opencode/mcp-npm"
    for name, m in cfg.get("mcp", {}).items():
        if name not in resolved:
            continue
        pkg_token, args = resolved[name]
        pkg, _ = split_pkg(pkg_token)
        # resolved_bins[pkg] is already relative to the lockdir (node_modules/<pkg>/<bin>)
        local = f"{home_token}/{resolved_bins[pkg]}"
        new_cmd = ["node", local, *args]
        if m.get("command") != new_cmd:
            m["command"] = new_cmd
            changed += 1
    return changed


resolved_bins: dict[str, str] = {}


def verify_configs(*configs: tuple[str, dict | None]) -> list[str]:
    """Every node-based mcp command must point at an existing file; npx = not locked."""
    failures = []
    for cfg_label, cfg in configs:
        if cfg is None:
            continue
        for name, m in cfg.get("mcp", {}).items():
            cmd = m.get("command", [])
            if cmd and cmd[0] == "node":
                path = cmd[1].replace("{env:HOME}", str(Path.home()))
                if not Path(path).is_file():
                    failures.append(f"{cfg_label}: mcp '{name}' → missing {path}")
            elif cmd and cmd[0] == "npx":
                failures.append(f"{cfg_label}: mcp '{name}' still npx-based (not locked)")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--live", type=Path, default=DEFAULT_LIVE)
    ap.add_argument("--lockdir", type=Path, default=DEFAULT_LOCKDIR)
    ap.add_argument("--skip-npm", action="store_true", help="verify/rewrite only (no npm install)")
    ap.add_argument("--check-only", action="store_true", help="health-check mode: fail on any npx-based or missing MCP, never write")
    args = ap.parse_args()

    repo = load(args.repo)
    targets = extract_npx(repo)
    failures = verify_configs(("repo", repo), ("live", load(args.live) if args.live.is_file() else None))
    if args.check_only:
        # In check-only mode any remaining npx entry is a failure (redundant with verify_configs,
        # kept explicit for the case where extract_npx had to bail out on an unpinned version).
        if targets:
            failures.append(f"repo: {len(targets)} npx-based MCP not locked: "
                            + ", ".join(sorted(targets)))
        if failures:
            print("MCP-LOCK CHECK FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
            return 1
        print("setup-mcp-lock: check OK — all MCP binaries local and present")
        return 0
    if not targets:
        print("setup-mcp-lock: no npx-based MCP in repo config (already locked)")
        if failures:
            print("VERIFY FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
            return 1
        print("setup-mcp-lock: verify OK — all MCP binaries local and present")
        return 0

    pkgs = sorted({split_pkg(token)[0] for token, _ in targets.values()})
    print(f"setup-mcp-lock: locking {len(pkgs)} package(s): {', '.join(pkgs)}")

    if not args.skip_npm:
        args.lockdir.mkdir(parents=True, exist_ok=True)
        pj = args.lockdir / "package.json"
        deps_match = False
        if pj.is_file():
            try:
                current = json.loads(pj.read_text(encoding="utf-8")).get("dependencies", {})
                wanted = {split_pkg(t)[0]: split_pkg(t)[1] for t, _ in targets.values()}
                deps_match = all(current.get(name) == ver for name, ver in wanted.items())
            except json.JSONDecodeError:
                pass
        if deps_match and all((args.lockdir / "node_modules" / pkg).is_dir() for pkg in pkgs):
            print(f"setup-mcp-lock: node_modules up to date ({args.lockdir})")
        else:
            cmd = ["npm", "install", "--prefix", str(args.lockdir),
                   "--save-exact", "--no-fund", "--no-audit",
                   *sorted({token for token, _ in targets.values()})]
            print(f"setup-mcp-lock: npm install {' '.join(cmd[6:])}")
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR: npm install failed:\n{r.stderr[-800:]}", file=sys.stderr)
                return 1

    # Resolve bins, verify
    for pkg in pkgs:
        rel = bin_path(args.lockdir, pkg)
        if not rel:
            print(f"ERROR: cannot resolve bin for {pkg} in {args.lockdir}", file=sys.stderr)
            return 1
        resolved_bins[pkg] = str(Path(rel).relative_to(args.lockdir))

    changed_repo = rewrite_commands(repo, targets)
    if changed_repo:
        save(args.repo, repo)
        print(f"setup-mcp-lock: repo config rewritten ({changed_repo} command(s)) — backup created")
    else:
        print("setup-mcp-lock: repo config already locked (unchanged)")

    live = None
    if args.live.is_file():
        live = load(args.live)
        if rewrite_commands(live, targets):
            save(args.live, live)
            print(f"setup-mcp-lock: live config rewritten — backup created")
        else:
            print("setup-mcp-lock: live config already locked (unchanged)")
    else:
        print("setup-mcp-lock: live config not found (fresh machine — setup.sh will deploy it)")

    # Final verification: reuse the same check
    failures = verify_configs(("repo", repo), ("live", live))
    if failures:
        print("VERIFY FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print(f"setup-mcp-lock: verify OK — all MCP binaries local and present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
