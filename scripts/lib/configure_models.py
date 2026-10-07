#!/usr/bin/env python3
"""Aurora model configuration engine — resolves versioned role policy against
models actually usable with the user's API keys, and generates the LIVE
OpenCode config. The repository is never modified.

Design: ChatGPT cowork tours 11-12 (APPROVED) — discovery ≠ entitlement
(probe-only VERIFIED), canonical probes with control model, live-only
generation, preservation of existing working selections (no breaking change).

THREE INDEPENDENT MODEL STATES (tour 15, formalized after the OpenAI
acceptance gate — eligibility requires all three to converge):

  1. RUNTIME RESOLVABILITY — can the installed OpenCode resolve this ID?
     Source: `opencode models` (inventory of the pinned binary; fallback
     models.dev with a User-Agent — the site 403s bare urllib).
     Established empirically: runtime 1.18.34 refuses gpt-5/gpt-5-mini
     although models.dev lists them and the account probes them 200.
  2. PROVIDER ENTITLEMENT — can the user's key actually call this model?
     Source: canonical probe only (VERIFIED). Catalogs are never proof.
  3. METADATA — context/cost/capabilities. Source: models.dev / provider
     catalogs. Used for ranking only.

    eligible model = resolvable AND entitled AND role-requirements met

CREDENTIAL PRECEDENCE WARNING (tour 15): OpenCode runtime credentials
(~/.local/share/opencode/auth.json, written by /connect — e.g. a stale
OAuth entry) OVERRIDE environment variables. A successful API probe does
NOT guarantee `opencode run` uses the same identity: an expired OAuth
entry yields "Token refresh failed: 401" even with a valid env key.
Diagnostic guidance when API probe = VERIFIED but runtime probe fails:
"OpenCode OAuth credentials may override environment authentication —
run /connect or remove/refresh the stale connection."

ACCEPTANCE ORACLE (tour 16, final review): discovery, runtime inventory
and provider probes are PARTIAL evidence. The only complete validation of
the chain (credentials → discovery → probes → generation → resolution →
execution) is a final `opencode run` against the generated config with
the real key — mandatory for any NEW provider integration. Both live
gates (OpenAI 2026-10-07, Anthropic 2026-10-07) were closed this way.

Usage (usually via scripts/configure-models.sh):
  python3 configure_models.py [--yes] [--dry-run] [--providers a,b] [--force]
"""

from __future__ import annotations

import argparse
import json
import math
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
    ModelMeta, ProbeResult, http_json,
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
                   quiet: bool, allowed_ids=None) -> dict:
    """Discover + control probe + candidate probes.
    Returns {'pool', 'results': {id: ProbeResult}, 'auth': 'env'|'none',
             'meta': {id: ModelMeta}, 'error': str|None}.
    allowed_ids (built-ins only): restrict discovery to IDs the OpenCode
    runtime can actually resolve (models.dev — see load_modelsdev_ids)."""
    out = {"pool": [], "results": {}, "meta": {}, "auth": "none", "error": None}
    if not provider.is_configured(env):
        return out

    out["auth"] = "env"
    pool = provider.discover(env, existing)
    # dedup, discovery-first: existing refs seed discovery but must never
    # dominate the shortlist (Anthropic gate 2026-10-07: an existing config
    # with 12 agents on the same model produced 12 duplicate pool entries —
    # the 15-slot shortlist filled with duplicates and starved the real
    # candidates; control probes were wasted on them)
    seen: set = set()
    pool = [m for m in pool if not (m in seen or seen.add(m))]
    if allowed_ids is not None:
        pool = [m for m in pool if m in allowed_ids]
    out["pool"] = pool
    if not pool:
        out["error"] = "discovery returned no candidates"
        return out

    short = shortlist_for(provider, pool, roles_policy,
                          max_probes=15)
    if not short:
        out["error"] = "no probeable candidate matching any role family"
        return out

    # control probe: the FIRST successful probe validates the provider.
    # Real-world findings (2026-10-07, acceptance gate OpenAI):
    # - a valid, funded account can lack ONE shortlisted model (gpt-5.2-codex
    #   → 404 model_not_found);
    # - shortlist order follows preferred families (gpt-5.x first) and can
    #   stack several non-entitled models. Control candidates are therefore
    #   ordered cheap-model-first (mini/flash/small/nano/tiny/lite — nearly
    #   universally entitled), then the rest of the shortlist. Up to 5
    #   attempts; individual 4xx results stay recorded per model. Skip the
    #   provider only if none verifies.
    def _control_order() -> list:
        cheap = [m for m in pool
                 if re.search(r"(mini|flash|small|nano|tiny|lite)", m, re.I)]
        ordered = [m for m in short if m in cheap]
        ordered += [m for m in cheap if m not in ordered]
        ordered += [m for m in short if m not in ordered]
        return ordered

    control = None
    probed = 0
    for mid in _control_order()[:5]:
        cres = provider.probe(mid, env)
        out["results"][mid] = cres
        probed += 1
        if cres.ok:
            control = mid
            break
    if control is None:
        first_tried = next(iter(out["results"]))
        res0 = out["results"][first_tried]
        out["error"] = (f"control probe failed on {probed} candidate(s) "
                        f"(first tried: '{first_tried}', {res0.status}/"
                        f"{res0.reason}) — provider skipped, "
                        "live config untouched")
        return out

    for mid in short:
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


def load_runtime_ids() -> "dict | None":
    """IDs the INSTALLED OpenCode runtime can actually resolve, per provider
    (from `opencode models`).

    Source of truth for built-in recommendation filtering — stronger than
    models.dev: it reflects the catalog embedded in the pinned binary.
    Established 2026-10-07 at the acceptance gate: runtime 1.18.34 refuses
    gpt-5 and gpt-5-mini (ProviderModelNotFoundError) even though both are
    listed by the live models.dev site and probe-verified on the account.

    INVARIANT (tour 16): PRESENCE in this inventory is positive evidence of
    resolvability; ABSENCE is UNKNOWN, never unavailable. The inventory is
    incomplete (it lists openai/* without any provider configured, but no
    anthropic/* although the runtime resolves claude-* perfectly once the
    key is in the env). The filter therefore only applies when the provider
    appears in the inventory; the final `opencode run` is the oracle."""
    exe = shutil.which("opencode")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "models"], capture_output=True, text=True,
                           timeout=30)
    except Exception:  # noqa: BLE001 - runtime inventory is best-effort
        return None
    if r.returncode != 0:
        return None
    out: dict = {}
    for line in (r.stdout or "").splitlines():
        ref = line.strip()
        if ref and "/" in ref:
            pid, _, mid = ref.partition("/")
            out.setdefault(pid, set()).add(mid)
    return out or None


def load_modelsdev_ids() -> "dict | None":
    """models.dev catalog: {provider_id: set(model_ids)} — fallback source
    when the runtime inventory is unavailable.

    models.dev is a RESOLUTION filter for built-in recommendations and still
    NEVER an entitlement proof (the probe remains the only entitlement
    source). Requires a User-Agent (models.dev blocks bare urllib — 403)."""
    code, body, _err = http_json("https://models.dev/api.json", timeout=20)
    if code != 200 or not isinstance(body, dict):
        return None
    out = {}
    for pid, pdata in body.items():
        if isinstance(pdata, dict) and isinstance(pdata.get("models"), dict):
            out[pid] = set(pdata["models"].keys())
    return out


def rank_role(models: dict, role_def: dict) -> list:
    """Order VERIFIED models for a role: requirements (hard when known),
    then preferredFamilies order, then light-suffix penalty, then context
    desc, then id asc (deterministic).

    Version-desc is a TIE-BREAKER ONLY (tour 16, improvement 4): it fixes
    alphabetical order picking the oldest model within a family
    (claude-opus-4-5 over claude-opus-4-8 — Anthropic gate 2026-10-07).
    It is never a general quality measure; curated role preferences
    (preferredFamilies, requirements) always win."""
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
        # light-suffix penalty: a "-mini/-nano/-tiny/-lite" model must never
        # win an expert/multimodal role by alphabetical tie-break alone
        # (acceptance gate 2026-10-07: gpt-5-mini ranked first with unknown
        # context metadata). The penalty is voided when the role explicitly
        # prefers that suffix family.
        light = re.search(r"-(mini|nano|tiny|lite|small)([-_.]|$)", low)
        light_rank = len(fams) + 100 if (light and not any(light.group(1) in f for f in fams)) else 0
        # version-desc (acceptance gate 2026-10-07, Anthropic): within the
        # same family and unknown context, alphabetical order picked the
        # OLDEST model (claude-opus-4-5 over claude-opus-4-8). Providers
        # name models with increasing versions — prefer the numerically
        # newest; the dated-suffix variant wins over the undated twin.
        vtuple = tuple(int(x) for x in re.findall(r"\d+", mid.rsplit("/", 1)[-1]))
        # desc order with a +inf pad: (-5,)* < (-5,-5) in Python (shorter
        # prefix sorts first) — the pad makes the LONGER version tuple
        # (claude-opus-5-5) rank before its shorter twin (claude-opus-5)
        vkey = tuple(-v for v in vtuple) + (math.inf,)
        scored.append((fam_rank + light_rank, -ctx, vkey, mid))
    scored.sort()
    return [m for *_rest, m in scored]


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
        if force:
            # --force: re-rank even when the current selection verifies
            # (found un-wired during the Anthropic acceptance gate — the
            # flag was documented but never consulted by _resolve_one)
            new = best_for(role_name)
            if not new:
                issues.append(f"no VERIFIED model for role '{role_name}' "
                              f"(needed by {name}) — keeping current")
                entry["reason"] = f"kept (forced, nothing better: {status}: {reason or 'n/a'})"
                entry["fallbacks"] = None
                return entry
            if new == current:
                entry["reason"] = "kept (forced — still best-ranked)"
                entry["fallbacks"] = fallbacks_for(role_name, new) or None
                return entry
            entry["reason"] = f"forced re-resolution (was {status}: {reason or 'n/a'})"
            entry["new"] = new
            entry["fallbacks"] = fallbacks_for(role_name, new)
            return entry
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
    # resolution filter: what the INSTALLED runtime can resolve wins;
    # models.dev is the fallback inventory
    modelsdev = load_runtime_ids() or load_modelsdev_ids()
    if modelsdev is None:
        print("  ! runtime inventory AND models.dev unavailable — built-in IDs "
              "will NOT be checked against the resolution catalog (risk: "
              "recommending an ID OpenCode cannot resolve)")
    states = {}
    for pid, provider in registry.items():
        if only and pid not in only:
            continue
        if not provider.is_configured(env):
            states[pid] = {"auth": "none", "pool": [], "results": {}, "meta": {}}
            continue
        allowed = modelsdev.get(pid) if (provider.kind == "builtin" and modelsdev) else None
        try:
            states[pid] = probe_provider(provider, env,
                                         existing_by_provider.get(pid, []), policy,
                                         quiet=args.quiet, allowed_ids=allowed)
        except Exception as e:  # noqa: BLE001 - provider errors are diagnoses, not crashes
            states[pid] = {"auth": "env", "pool": [], "results": {},
                           "meta": {}, "error": str(e)}
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
