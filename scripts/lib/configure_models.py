#!/usr/bin/env python3
"""Aurora model configuration engine — resolves versioned role policy against
models actually usable with the user's API keys, and generates the LIVE
OpenCode config. The repository is never modified.

Design: ChatGPT cowork tours 11-12 (APPROVED) — discovery ≠ entitlement
(probe-only VERIFIED), canonical probes with control model, live-only
generation, preservation of existing working selections (no breaking change).

Usage (usually via scripts/configure-models.sh):
  python3 configure_models.py [--yes] [--dry-run] [--providers a,b] [--force]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OPENCODE_DIR = os.environ.get("OPENCODE_DIR") or os.path.expanduser("~/.config/opencode")
LIVE_CONFIG = os.path.join(OPENCODE_DIR, "opencode.json")
LIVE_AGENTS = os.path.join(OPENCODE_DIR, "agents")
STATE_FILE = os.path.join(OPENCODE_DIR, "aurora-models.json")
BACKUP_DIR = os.path.join(OPENCODE_DIR, ".models-backup")
PROVIDERS_PKG = os.path.join(HERE, "providers")

sys.path.insert(0, HERE)

from providers import anthropic, google, infomaniak, ollama, openai, openrouter  # noqa: E402
from providers.base import (  # noqa: E402
    AUTH_REQUIRED, CATALOG_AVAILABLE, TRANSIENT, UNAVAILABLE, VERIFIED,
    ModelMeta, ProbeResult,
)


# --------------------------------------------------------------------------
# loading helpers
# --------------------------------------------------------------------------

def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_env() -> dict:
    """os.environ wins; ~/.config/opencode/.env fills the gaps (never printed)."""
    env = dict(os.environ)
    env_path = os.path.join(OPENCODE_DIR, ".env")
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v and k not in env:
                    env[k] = v
    return env


def provider_registry():
    reg = {
        "infomaniak": infomaniak.InfomaniakProvider(),
        "openai": openai.OpenAIProvider(),
        "anthropic": anthropic.AnthropicProvider(),
        "google": google.GoogleProvider(),
        "openrouter": openrouter.OpenRouterProvider(),
        "ollama": ollama.OllamaProvider(),
    }
    # enrich infomaniak metadata from the public catalog (fetched during discover)
    return reg


# --------------------------------------------------------------------------
# provider phase: discover + probe
# --------------------------------------------------------------------------

def shortlist_for(provider, pool: list, roles_policy: dict, max_probes: int) -> list:
    """Candidates worth probing: family matches first; cap to budget.
    Non-probeable models (stt/embedding) are excluded from probing."""
    families = []
    for role in roles_policy.get("roles", {}).values():
        families.extend(role.get("preferredFamilies", []))
        families.extend(role.get("fallbackFamilies", []))
    fams_low = [f.lower() for f in families]

    probeable = [c for c in pool if _is_probeable(provider, c)]
    matched = [c for c in probeable if any(f in c.lower() for f in fams_low)]
    rest = [c for c in probeable if c not in matched]
    out = matched + rest[: max(0, max_probes - len(matched))]
    return out[:max_probes]


def _is_probeable(provider, model_id: str) -> bool:
    if hasattr(provider, "is_stt_or_embedding"):
        return provider.is_stt_or_embedding(model_id) == "chat"
    return True


def probe_provider(provider, env: dict, existing: list, roles_policy: dict,
                   quiet: bool) -> dict:
    """Discover + control probe + candidate probes.
    Returns {'pool', 'results': {id: ProbeResult}, 'auth': 'env'|'none',
             'meta': {id: ModelMeta}, 'error': str|None}."""
    out = {"pool": [], "results": {}, "meta": {}, "auth": "none", "error": None}
    if not provider.is_configured(env):
        return out

    out["auth"] = "env"
    pool = provider.discover(env, existing)
    out["pool"] = pool
    if not pool:
        out["error"] = "discovery returned no candidates"
        return out

    short = shortlist_for(provider, pool, roles_policy,
                          max_probes=15)
    if not short:
        out["error"] = "no probeable candidate matching any role family"
        return out

    # control probe: canonical payload must succeed once before any candidate
    # is classified UNAVAILABLE (tour 11b improvement 1)
    control = short[0]
    cres = provider.probe(control, env)
    out["results"][control] = cres
    if not cres.ok:
        out["error"] = (f"control probe failed on '{control}' "
                        f"({cres.status}/{cres.reason}) — provider skipped, "
                        "live config untouched")
        return out

    for mid in short[1:]:
        if mid in out["results"]:
            continue
        out["results"][mid] = provider.probe(mid, env)
        time.sleep(0.2)  # gentle on rate limits
    if not quiet:
        ok = sum(1 for r in out["results"].values() if r.ok)
        print(f"  [{provider.id}] {len(pool)} candidates · {ok} verified "
              f"(probed {len(out['results'])})")
    return out


# --------------------------------------------------------------------------
# ranking + resolution
# --------------------------------------------------------------------------

def _context_of(meta: ModelMeta) -> int:
    return meta.context or 0


def rank_role(models: dict, role_def: dict) -> list:
    """Order VERIFIED models for a role: requirements (hard when known),
    then preferredFamilies order, then context desc, then id asc (deterministic)."""
    req = role_def.get("requires", {})
    fams = [f.lower() for f in role_def.get("preferredFamilies", [])]
    scored = []
    for mid, res in models.items():
        if not res.ok:
            continue
        meta = ModelMeta()
        low = mid.lower()
        fam_rank = next((i for i, f in enumerate(fams) if f in low), len(fams) + 100)
        ctx = _context_of(meta)
        if req.get("minContext") and ctx and ctx < req["minContext"]:
            continue  # hard requirement only when context is actually known
        scored.append((fam_rank, -ctx, mid))
    scored.sort()
    return [m for _f, _c, m in scored]


def resolve_all(policy: dict, states: dict, live_cfg: dict, force: bool,
                yes: bool, dry: bool):
    """Compute final assignments. Returns (plan, issues).

    plan = {
      'default': {'current': ref, 'new': ref|None, 'fallbacks': [...], 'reason': str},
      'agents': {name: {'current', 'new', 'fallbacks', 'reason'}},
      'strip_providers': [...], 'provider_blocks': {id: {...}},
      'custom_models': {provider: {id: entry-or-None-to-prune}},
    }
    Preservation rules (generator invariants, tour 13):
    - existing selection VERIFIED (provider enabled)  -> keep as-is
    - existing selection UNKNOWN_TRANSIENT            -> keep + warn
      (INVARIANT: a transient outage NEVER causes a durable reconfiguration)
    - existing selection CATALOG_AVAILABLE            -> keep + warn
      (listed in a catalog, never probed — never upgraded to VERIFIED)
    - existing selection UNAVAILABLE                  -> replace (recommendation)
    - provider disabled/stripped                      -> resolve from role ranking
    - empty current model                             -> untouched (plugin agents)
    """
    plan = {"default": None, "agents": {}, "strip_providers": [],
            "provider_blocks": {}, "custom_models": {}}
    issues = []
    agent_section = live_cfg.get("agent", {}) or {}
    top_model = live_cfg.get("model", "")

    def probe_state(ref: str):
        """(status, reason) for a 'provider/model' ref against this run's results."""
        if not ref or "/" not in ref:
            return None, None
        pid, _, mid = ref.partition("/")
        st = states.get(pid)
        if not st or st.get("auth") != "env":
            return None, None
        if mid in st["results"]:
            r = st["results"][mid]
            return r.status, r.reason
        if mid in st["pool"]:
            # discovered by a catalog but never probed with the user's
            # credentials — honest status: CATALOG_AVAILABLE ≠ VERIFIED
            # (tour 13 improvement 1)
            return CATALOG_AVAILABLE, "listed by catalog, not probed"
        return None, None

    def best_for(role_name: str, exclude: str = "") -> str:
        """Best VERIFIED model across all enabled providers for a role
        (families order wins across providers; deterministic tie-breaks)."""
        role_def = policy["roles"].get(role_name)
        if not role_def:
            return ""
        all_models = {}
        for pid, st in states.items():
            if st.get("auth") != "env":
                continue
            for mid, res in st["results"].items():
                all_models[f"{pid}/{mid}"] = res
        ranked = rank_role(all_models, role_def)
        ranked = [r for r in ranked if r != exclude]
        return ranked[0] if ranked else ""

    def fallbacks_for(role_name: str, primary_ref: str) -> list:
        role_def = policy["roles"].get(role_name, {})
        fams = [f.lower() for f in role_def.get("fallbackFamilies", [])]
        if not fams:
            return []
        ppid = primary_ref.partition("/")[0]
        same, cross = [], []
        for pid, st in states.items():
            if st.get("auth") != "env":
                continue
            for mid, res in st["results"].items():
                ref = f"{pid}/{mid}"
                if ref == primary_ref or not res.ok:
                    continue
                if any(f in mid.lower() for f in fams):
                    (same if pid == ppid else cross).append(ref)
        # v1: same-provider only (cross-provider fallback needs a runtime spike)
        return same[:2]

    def _resolve_one(name: str, current: str, role_name: str) -> dict:
        entry = {"current": current, "new": None, "fallbacks": [],
                 "reason": "", "role": role_name}
        if not current:
            entry["reason"] = "empty (plugin-provided) — untouched"
            return entry
        status, reason = probe_state(current)
        if status == VERIFIED:
            entry["reason"] = "kept (verified)"
            entry["fallbacks"] = None  # None = preserve existing chain
            return entry
        if status == TRANSIENT:
            entry["reason"] = f"kept (unverified: {reason})"
            entry["fallbacks"] = None
            return entry
        if status == CATALOG_AVAILABLE:
            # listed by a catalog, never probed with user credentials —
            # kept for existing selections, NEVER silently upgraded to
            # VERIFIED and never auto-recommended (tour 13 improvement 1)
            entry["reason"] = f"kept (catalog available — not probed: {reason})"
            entry["fallbacks"] = None
            return entry
        new = best_for(role_name, exclude=current)
        if not new:
            issues.append(f"no VERIFIED model for role '{role_name}' "
                          f"(needed by {name}) — configure a provider key")
            return entry
        if status == UNAVAILABLE:
            entry["reason"] = f"replaced (current unavailable: {reason})"
        else:
            entry["reason"] = "resolved (provider not configured)"
        entry["new"] = new
        entry["fallbacks"] = fallbacks_for(role_name, new)
        return entry

    # --- default model (top-level, covers the main orchestrator) ---
    default_role = policy.get("defaultRole", "expert")
    plan["default"] = _resolve_one("default", top_model, default_role)

    # --- agents ---
    for name, role_name in policy.get("agents", {}).items():
        cur = (agent_section.get(name) or {}).get("model", "")
        plan["agents"][name] = _resolve_one(name, cur, role_name)

    # --- provider blocks: strip unconfigured customs, keep/write customs ---
    prov_policy = policy.get("providers", {})
    for pid, pdef in prov_policy.items():
        st = states.get(pid, {})
        configured = st.get("auth") == "env"
        if pdef.get("kind") == "custom":
            block = live_cfg.get("provider", {}).get(pid)
            if configured:
                plan["provider_blocks"][pid] = block or _default_custom_block(pid, pdef, states)
            elif block:
                plan["strip_providers"].append(pid)
    # local providers (ollama): only write when reachable
    if states.get("ollama", {}).get("pool"):
        plan["provider_blocks"]["ollama"] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Ollama (local)",
            "options": {"baseURL": "http://localhost:11434/v1"},
        }

    # --- custom provider models map: preserve, prune UNAVAILABLE, add new ---
    for pid, pdef in prov_policy.items():
        if pdef.get("kind") != "custom":
            continue
        st = states.get(pid, {})
        if st.get("auth") != "env":
            continue
        existing_map = (live_cfg.get("provider", {}).get(pid) or {}).get("models", {}) or {}
        kept_refs = set()
        for e in [plan["default"]] + list(plan["agents"].values()):
            ref = (e or {}).get("new") or (e or {}).get("current") or ""
            if ref.startswith(f"{pid}/"):
                kept_refs.add(ref.partition("/")[2])
        new_map = {}
        for mid, entry in existing_map.items():
            res = st["results"].get(mid)
            if res and res.status == UNAVAILABLE and mid not in kept_refs:
                continue  # prune dead, unreferenced models (notice printed later)
            new_map[mid] = entry  # preserved verbatim (incl. fallbacks)
        for e in [plan["default"]] + list(plan["agents"].values()):
            if not e or not e.get("new"):
                continue
            mid = e["new"].partition("/")[2]
            if e["new"].startswith(f"{pid}/") and mid not in new_map:
                meta = st["meta"].get(mid) or ModelMeta()
                new_map[mid] = _model_entry(mid, meta, e.get("fallbacks") or [])
        plan["custom_models"][pid] = new_map
    return plan, issues


def _default_custom_block(pid: str, pdef: dict, states: dict) -> dict:
    if pid == "infomaniak":
        return {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Infomaniak AI",
            "options": {"baseURL": "https://api.infomaniak.com/2/ai/private/openai/v1",
                        "apiKey": "{env:OPENAI_API_KEY_INFOMANIAK}"},
        }
    return {}


def _model_entry(mid: str, meta: ModelMeta, fallbacks: list) -> dict:
    entry: dict = {"name": mid.split("/")[-1]}
    if meta.context:
        entry["limit"] = {"context": meta.context, "output": min(meta.context, 32000)}
    if fallbacks:
        entry["fallback"] = fallbacks
    return entry


# --------------------------------------------------------------------------
# generation (live only, with backup)
# --------------------------------------------------------------------------

def write_frontmatter(path: str, new_model: str) -> str:
    """Replace the single `model:` line of the frontmatter. Fail-closed."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return "skip: no frontmatter"
    fm = m.group(1)
    hits = [i for i, line in enumerate(fm.split("\n")) if re.match(r"^model:\s*\S", line)]
    if len(hits) != 1:
        return f"skip: {len(hits)} model lines (fail-closed)"
    lines = fm.split("\n")
    lines[hits[0]] = f"model: {new_model}"
    new_text = text.replace(fm, "\n".join(lines), 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    return "updated"


def apply_plan(plan: dict, policy: dict, live_cfg: dict, dry: bool) -> dict:
    """Mutate and write. Returns {'written': [...], 'backup': path|None}."""
    report = {"written": [], "backup": None}
    changes = _compute_changes(plan, live_cfg)
    if not changes["any"]:
        print("Nothing to change — live config already matches the role policy.")
        return report
    if dry:
        print("DRY RUN — no file written. Changes that would apply:")
        for line in changes["lines"]:
            print(f"  {line}")
        return report

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    # unique even for two runs in the same second (tour 13 improvement 6)
    bdir = os.path.join(BACKUP_DIR, f"{ts}-{os.getpid()}")
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(LIVE_CONFIG, os.path.join(bdir, "opencode.json"))
    report["backup"] = bdir

    # 1. opencode.json
    cfg = json.loads(json.dumps(live_cfg))  # deep copy
    for pid in plan["strip_providers"]:
        cfg.get("provider", {}).pop(pid, None)
    for pid, block in plan["provider_blocks"].items():
        if block:
            cfg.setdefault("provider", {})[pid] = block
    for pid, models in plan["custom_models"].items():
        if pid in cfg.get("provider", {}) and models is not None:
            cfg["provider"][pid]["models"] = models
    if plan["default"] and plan["default"].get("new"):
        cfg["model"] = plan["default"]["new"]
        if plan["default"].get("fallbacks"):
            # top-level fallback lives on the provider model entry (handled below)
            pass
    for name, e in plan["agents"].items():
        if e and e.get("new"):
            cfg.setdefault("agent", {}).setdefault(name, {})["model"] = e["new"]
    with open(LIVE_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    report["written"].append(LIVE_CONFIG)

    # 2. agent frontmatters (live agents dir)
    for name, e in plan["agents"].items():
        if not (e and e.get("new")):
            continue
        path = os.path.join(LIVE_AGENTS, f"{name}.md")
        if not os.path.isfile(path):
            continue
        shutil.copy2(path, os.path.join(bdir, f"{name}.md"))
        status = write_frontmatter(path, e["new"])
        if status == "updated":
            report["written"].append(path)
        else:
            print(f"  ! {name}.md: {status}")
    return report


def _compute_changes(plan: dict, live_cfg: dict) -> dict:
    lines, any_change = [], False
    d = plan.get("default") or {}
    if d.get("new"):
        any_change = True
        lines.append(f"model (default): {d['current']!r} -> {d['new']!r} ({d['reason']})")
    for name, e in (plan.get("agents") or {}).items():
        if e and e.get("new"):
            any_change = True
            lines.append(f"agent {name}: {e['current']!r} -> {e['new']!r} ({e['reason']})")
    for pid in plan.get("strip_providers", []):
        any_change = True
        lines.append(f"provider '{pid}': stripped (not configured)")
    for pid, block in (plan.get("provider_blocks") or {}).items():
        if block and pid not in (live_cfg.get("provider") or {}):
            any_change = True
            lines.append(f"provider '{pid}': added")
    for pid, models in (plan.get("custom_models") or {}).items():
        cur = (live_cfg.get("provider", {}).get(pid) or {}).get("models", {}) or {}
        for mid in cur:
            if mid not in (models or {}):
                any_change = True
                lines.append(f"{pid}/models/{mid}: pruned (unavailable, unreferenced)")
    return {"any": any_change, "lines": lines}


# --------------------------------------------------------------------------
# state persistence + UX
# --------------------------------------------------------------------------

def save_state(plan: dict, states: dict, policy: dict, dry: bool) -> None:
    if dry:
        return
    providers_state = {}
    for pid, st in states.items():
        if st.get("auth") == "env":
            providers_state[pid] = {"auth": "env", "status": "ok",
                                    "verified": sum(1 for r in st["results"].values() if r.ok)}
        elif st.get("error"):
            providers_state[pid] = {"auth": "none", "status": "error",
                                    "error": st["error"]}
    roles = {}
    d = plan.get("default") or {}
    roles["default"] = {"role": d.get("role"), "primary": d.get("new") or d.get("current"),
                        "fallbacks": d.get("fallbacks") or []}
    for name, e in (plan.get("agents") or {}).items():
        if not e:
            continue
        roles[name] = {"role": e.get("role"), "primary": e.get("new") or e.get("current")}
    state = {"schemaVersion": 2,
             "configuredAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "providers": providers_state, "roles": roles}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def print_summary(plan: dict, states: dict, policy: dict) -> None:
    print("\n=== Aurora model configuration ===")
    for pid, st in states.items():
        if st.get("auth") == "env":
            ok = sum(1 for r in st["results"].values() if r.ok)
            print(f"  provider {pid:12s} env key found · {ok} models verified"
                  + (f" · {st['error']}" if st.get("error") else ""))
        elif st.get("error"):
            print(f"  provider {pid:12s} not configured"
                  + (f" ({st['error']})" if st.get("error") else ""))
        else:
            print(f"  provider {pid:12s} not configured (no key)")
    d = plan.get("default") or {}
    print(f"\n  default ({d.get('role')}): {d.get('new') or d.get('current')}"
          f"  [{d.get('reason', '')}]")
    for name, e in (plan.get("agents") or {}).items():
        if not e:
            continue
        ref = e.get("new") or e.get("current")
        mark = "*" if e.get("new") else " "
        print(f"  {mark} {name:14s} ({e.get('role'):12s}) {ref}  [{e.get('reason', '')}]")
    print("\n  (* = will change)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Configure Aurora models from verified providers")
    ap.add_argument("--yes", action="store_true", help="accept recommendations non-interactively")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="re-resolve all roles even when current selections verify")
    ap.add_argument("--providers", default="",
                    help="comma-separated provider ids to consider (default: all)")
    ap.add_argument("--quiet", action="store_true", help="less output")
    args = ap.parse_args()

    policy_path = os.path.join(REPO_ROOT, "config", "model-roles.json")
    if not os.path.isfile(policy_path):
        print(f"error: {policy_path} not found", file=sys.stderr)
        return 1
    policy = load_json(policy_path)
    if not os.path.isfile(LIVE_CONFIG):
        print(f"error: {LIVE_CONFIG} not found — run install.sh first "
              "(the generator works on the live config, never the repo)", file=sys.stderr)
        return 1
    live_cfg = load_json(LIVE_CONFIG)

    env = load_env()
    registry = provider_registry()
    only = [p.strip() for p in args.providers.split(",") if p.strip()] if args.providers else None

    # existing refs per provider (feed discovery union)
    existing_by_provider: dict = {}
    refs = [live_cfg.get("model", "")]
    for a in (live_cfg.get("agent") or {}).values():
        if isinstance(a, dict) and a.get("model"):
            refs.append(a["model"])
    for ref in refs:
        if ref and "/" in ref:
            pid, _, mid = ref.partition("/")
            existing_by_provider.setdefault(pid, []).append(mid)
    for pid, block in (live_cfg.get("provider") or {}).items():
        if isinstance(block, dict) and isinstance(block.get("models"), dict):
            existing_by_provider.setdefault(pid, []).extend(block["models"].keys())

    print("Discovering and verifying models (catalogs are NOT entitlement — probing)…")
    states = {}
    for pid, provider in registry.items():
        if only and pid not in only:
            continue
        if not provider.is_configured(env):
            states[pid] = {"auth": "none", "pool": [], "results": {}, "meta": {}}
            continue
        states[pid] = probe_provider(provider, env,
                                     existing_by_provider.get(pid, []), policy,
                                     quiet=args.quiet)
        if states[pid].get("error") and not args.quiet:
            print(f"  ! {pid}: {states[pid]['error']}")

    plan, issues = resolve_all(policy, states, live_cfg, args.force, args.yes, args.dry_run)
    print_summary(plan, states, policy)
    for i in issues:
        print(f"  ! {i}")

    if args.dry_run:
        apply_plan(plan, policy, live_cfg, dry=True)
        return 0

    if issues:
        print("\nBlocking issues above — nothing written. Fix providers/keys and re-run.")
        return 1

    if not args.yes:
        try:
            ans = input("\nApply this configuration? [A]ccept / [C]ancel: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "c"
        if ans not in ("a", "y", ""):
            print("Cancelled — live config untouched.")
            return 0

    report = apply_plan(plan, policy, live_cfg, dry=False)
    save_state(plan, states, policy, dry=False)
    print(f"\nBackup: {report['backup']}")
    print(f"Written: {len(report['written'])} file(s)")
    pending = [pid for pid, st in states.items() if st.get("auth") == "none"
               and st.get("error")]
    if pending:
        print("Note: providers not configured this run: " + ", ".join(pending))
        print("For OAuth/subscription providers (Claude Pro/Max, ChatGPT Plus): "
              "run `opencode` then /connect, then re-run configure-models.sh.")
    print("Done. Restart OpenCode sessions to pick up the new config.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
