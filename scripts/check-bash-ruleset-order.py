#!/usr/bin/env python3
"""check-bash-ruleset-order.py — S-05 invariant (empirically validated 2026-10-07).

OpenCode bash permission semantics (opencode 1.18.35, verified in lab /tmp/oc-permlab):
  1. Execution  = last matching rule wins (findLast, insertion order).
  2. Tool visibility = action of the LAST DECLARED rule: a catch-all "*": "deny"
     in terminal position removes the bash tool ENTIRELY — specific allows do
     NOT restore it (« Invalid Tool »).
  3. NO parent -> subagent bash permission propagation via task (R6:
     deny-all parent + allowed subagent = executed). Bash-only finding; do NOT
     generalize to external_directory or other permission families.

INVARIANT: for any agent ruleset designed as an allowlist that contains a
catch-all "*": "deny", the catch-all MUST be the FIRST declared key. A
catch-all deny in any later position silently disables the toolset.

Exit codes: 0 = all rulesets conform, 1 = violation found, 2 = usage error.
Usage: check-bash-ruleset-order.py [config.json ...]   (default: config/opencode.json)
"""
import json
import sys


def check_ruleset(agent_name: str, source: str, bash: dict) -> list:
    problems = []
    if "*" not in bash:
        return problems  # explicit allowlist without catch-all: no invariant
    keys = list(bash.keys())
    pos = keys.index("*")
    if bash["*"] == "deny" and pos != 0:
        problems.append(
            f"{source}: agent '{agent_name}': catch-all deny declared at position {pos}/{len(keys) - 1} "
            f"(keys start: {keys[:3]}). Bash tool visibility = LAST declared rule -> "
            f"terminal catch-all deny REMOVES the bash tool. Move \"*\": \"deny\" first, "
            f"specific allows after (S-05 invariant, validated empirically)."
        )
    return problems


def check_config_file(path: str) -> list:
    problems = []
    with open(path) as f:
        cfg = json.load(f)
    for name, ag in cfg.get("agent", {}).items():
        if not isinstance(ag, dict):
            continue
        perm = ag.get("permission", {})
        if isinstance(perm, str) or not isinstance(perm, dict):
            continue
        bash = perm.get("bash")
        if isinstance(bash, dict):
            problems += check_ruleset(name, path, bash)
    return problems


def main() -> int:
    paths = sys.argv[1:] or ["config/opencode.json"]
    problems = []
    for p in paths:
        try:
            problems += check_config_file(p)
        except FileNotFoundError:
            print(f"WARN: {p} not found, skipped")
        except json.JSONDecodeError as e:
            print(f"ERROR: {p} is not valid JSON: {e}")
            return 1
    if problems:
        for pr in problems:
            print(f"VIOLATION: {pr}")
        return 1
    print("OK: all bash rulesets conform to the S-05 invariant (catch-all deny first).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
