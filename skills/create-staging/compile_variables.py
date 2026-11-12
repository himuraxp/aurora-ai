#!/usr/bin/env python3
"""create-staging — pure variable compiler (stdlib only, zero network).

Compiles the staging variable plan from the PRIVATE config plus the tool
display name. Pure function: no browser, no git, no tool access — fully
testable without any staging tool.

Contract:
  - managedKeys = fixed + derived + empty (exact partition, no overlap)
  - derived values are templates containing "{name}" (tool display name)
  - output: sorted key/value pairs + canonical SHA-256 digest (the same
    canonicalization the UI pre-submit gate and the detail-page re-read use:
    json.dumps(sorted, separators=(',',':'), ensure_ascii=False))

Usage:
  compile_variables.py --config <config.json> --name <tool-name> [--out <plan.json>]
  compile_variables.py --self-test

--self-test compiles against the fictional config.example.json shipped next
to this script and asserts the contract end to end.
"""

import argparse
import hashlib
import json
import pathlib
import re
import sys


def slugify(branch: str, config: dict) -> str:
    name = branch.strip()
    for prefix in config.get("naming", {}).get("stripBranchPrefixes", []):
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-")
    max_len = config.get("naming", {}).get("maxLength")
    if max_len and len(name) > max_len:
        cut = name[:max_len]
        if name[max_len] != "-" and "-" in cut:
            cut = cut[:cut.rfind("-")]
        name = cut
    return name


def compile_variables(name: str, config: dict) -> dict:
    env = config["environment"]
    managed = env["managedKeys"]
    fixed, derived, empty = env.get("fixed", {}), env.get("derived", {}), env.get("empty", [])

    families = {"fixed": sorted(fixed), "derived": sorted(derived), "empty": sorted(empty)}
    union = [k for f in families.values() for k in f]
    if sorted(managed) != sorted(union):
        raise SystemExit(f"[FAIL] managedKeys != union(fixed, derived, empty): diff {sorted(set(managed) ^ set(union))}")
    overlaps = [k for k in fixed if k in derived or k in empty] + [k for k in derived if k in empty]
    if overlaps:
        raise SystemExit(f"[FAIL] families overlap on keys: {overlaps}")

    pairs = []
    for key in managed:
        if key in fixed:
            pairs.append({"key": key, "value": fixed[key], "family": "fixed"})
        elif key in derived:
            pairs.append({"key": key, "value": derived[key].replace("{name}", name), "family": "derived"})
        else:
            pairs.append({"key": key, "value": "", "family": "empty"})
    pairs.sort(key=lambda p: p["key"])
    payload = {p["key"]: p["value"] for p in pairs}
    digest = hashlib.sha256(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:16]
    return {
        "toolName": name,
        "resourceName": _resource_name(name, config),
        "variables": pairs,
        "digest": digest,
        "expected": {
            "keys": len(pairs),
            "families": {"fixed": len(fixed), "derived": len(derived), "empty": len(empty)},
        },
    }


def _resource_name(tool_name: str, config: dict) -> str:
    prefix = config.get("naming", {}).get("resourcePrefix", "")
    if prefix and not tool_name.startswith(prefix):
        return prefix + tool_name
    return tool_name


def _self_test() -> int:
    here = pathlib.Path(__file__).parent
    config = json.loads((here / "config.example.json").read_text())

    # 1. slug derivation: strip + trims on dash boundary, never over maxLength
    assert slugify("feat/some-really-long-feature-branch-name-here", config) == "some-really-long-feature", slugify(
        "feat/some-really-long-feature-branch-name-here", config
    )
    assert slugify("fix/small-fix", config) == "small-fix"

    # 2. compilation contract
    plan = compile_variables("some-feature", config)
    assert plan["resourceName"] == config["naming"]["resourcePrefix"] + "some-feature"
    assert plan["expected"]["keys"] == len(config["environment"]["managedKeys"])
    assert len({p["key"] for p in plan["variables"]}) == plan["expected"]["keys"]
    for p in plan["variables"]:
        if p["family"] == "derived":
            assert config["naming"]["resourcePrefix"] + "some-feature" in p["value"] or "some-feature" in p["value"], p
        if p["family"] == "empty":
            assert p["value"] == "", p

    # 3. digest stability: same inputs -> same digest, different name -> different digest
    assert compile_variables("some-feature", config)["digest"] == plan["digest"]
    assert compile_variables("other-feature", config)["digest"] != plan["digest"]

    # 4. digest matches the canonical form used by the UI gates
    payload = {p["key"]: p["value"] for p in plan["variables"]}
    canonical = json.dumps(dict(sorted(payload.items())), separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canonical.encode()).hexdigest()[:16] == plan["digest"]

    print(f"[OK] self-test passed — {plan['expected']['keys']} variables, digest {plan['digest']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="create-staging variable compiler (pure, stdlib)")
    parser.add_argument("--config", help="path to the private config.json")
    parser.add_argument("--name", help="tool display name (no resource prefix)")
    parser.add_argument("--out", help="write the compiled plan to this path")
    parser.add_argument("--self-test", action="store_true", help="run the built-in tests against config.example.json")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()

    if not (args.config and args.name):
        parser.error("--config and --name are required (or use --self-test)")
    config = json.loads(pathlib.Path(args.config).read_text())
    plan = compile_variables(args.name, config)
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
