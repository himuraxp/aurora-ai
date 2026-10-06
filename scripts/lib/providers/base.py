"""Provider contract and shared helpers for the Aurora model configuration engine.

Every provider adapter implements the same small contract (ChatGPT cowork tour 12,
condition 2): the common engine never knows about Anthropic, OpenAI, Infomaniak, etc.

Design invariants (tours 11-12, APPROVED):
- A catalog listing (models.dev, provider /models, public catalog) is DISCOVERY only —
  never proof of entitlement. Only a successful probe produces VERIFIED.
- 4xx classification is conservative: a 400/404/422 is UNAVAILABLE only when a control
  model succeeded with the same canonical payload and the candidate deterministically
  fails on re-probe. 429/5xx/timeout are always UNKNOWN_TRANSIENT, never UNAVAILABLE.
- Structured reasons (NOT_ENTITLED, MODEL_REJECTED, RATE_LIMITED, ...) for clear UX.
- No secret is ever written to disk by this code; keys are read from the environment.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

# Probe classification (tour 11b + tour 12 conditions 1-3; tour 13 improvement 1)
VERIFIED = "VERIFIED"
CATALOG_AVAILABLE = "CATALOG_AVAILABLE"  # listed by a catalog, never probed with user credentials
UNAVAILABLE = "UNAVAILABLE"
TRANSIENT = "UNKNOWN_TRANSIENT"
AUTH_REQUIRED = "AUTH_REQUIRED"

# Reason codes (structured, for UX)
R_OK = None
R_NOT_ENTITLED = "NOT_ENTITLED"
R_MODEL_REJECTED = "MODEL_REJECTED"
R_RATE_LIMITED = "RATE_LIMITED"
R_SERVER_ERROR = "SERVER_ERROR"
R_TIMEOUT = "TIMEOUT"
R_NETWORK = "NETWORK_ERROR"
R_AUTH_FAILED = "AUTH_FAILED"
R_PAYLOAD_INVALID = "PAYLOAD_INVALID"
R_OFFLINE = "OFFLINE"

HTTP_TIMEOUT = 20  # seconds, per request
PROBE_BUDGET_DEFAULT = 15  # max candidate probes per provider per run


@dataclass
class ProbeResult:
    status: str  # VERIFIED | UNAVAILABLE | UNKNOWN_TRANSIENT | AUTH_REQUIRED
    reason: Optional[str] = None
    http_status: Optional[int] = None
    latency_ms: Optional[int] = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == VERIFIED


@dataclass
class ModelMeta:
    """Best-effort metadata; every field may be unknown (None)."""

    context: Optional[int] = None
    input_cost: Optional[float] = None
    output_cost: Optional[float] = None
    modalities: list = field(default_factory=list)
    source: str = ""  # "provider", "models.dev", "existing-config"


def http_json(url: str, method: str = "GET", headers: Optional[dict] = None,
              body: Optional[dict] = None, timeout: int = HTTP_TIMEOUT):
    """Perform an HTTP request, return (status_code, parsed_json_or_None, error_or_None)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw), None
            except json.JSONDecodeError:
                return resp.status, None, None
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        try:
            return e.code, json.loads(raw), None
        except (json.JSONDecodeError, ValueError):
            return e.code, None, raw[:200] or None
    except urllib.error.URLError as e:
        return None, None, f"network: {getattr(e, 'reason', e)}"
    except TimeoutError:
        return None, None, "timeout"
    except Exception as e:  # noqa: BLE001 - defensive boundary
        return None, None, f"error: {e}"


def classify_status(code: Optional[int], err: Optional[str]) -> ProbeResult:
    """Map an HTTP status to a conservative ProbeResult (no payload inspection)."""
    if code is None:
        if err and "timeout" in str(err):
            return ProbeResult(TRANSIENT, R_TIMEOUT, detail=str(err))
        return ProbeResult(TRANSIENT, R_NETWORK, detail=str(err or "unknown"))
    if 200 <= code < 300:
        return ProbeResult(VERIFIED, None, code)
    if code == 401:
        return ProbeResult(AUTH_REQUIRED, R_AUTH_FAILED, code)
    if code == 403:
        return ProbeResult(UNAVAILABLE, R_NOT_ENTITLED, code)
    if code == 429:
        return ProbeResult(TRANSIENT, R_RATE_LIMITED, code)
    if 500 <= code < 600:
        return ProbeResult(TRANSIENT, R_SERVER_ERROR, code)
    # 400 / 404 / 422 and other 4xx: ambiguous — caller decides after control/re-probe.
    return ProbeResult(UNAVAILABLE, R_MODEL_REJECTED, code)


class Provider:
    """Base contract. Subclasses override the specifics; never the invariants.

    Auth-note (tour 13 improvement 5): the presence of an auth env var does NOT
    make a provider configured when an endpoint override (e.g. OPENAI_BASE_URL)
    redirects that identity to a third-party OpenAI-compatible service — the
    built-in adapters guard against this in is_configured().
    """

    id = "base"
    kind = "custom"  # custom | builtin | local

    def __init__(self, meta_loader=None):
        self._meta_loader = meta_loader  # callable(model_id) -> ModelMeta | None

    # --- contract ---
    def auth_modes(self) -> list:
        """Return subset of ['env', 'opencode_auth', 'none']."""
        return ["env"]

    def env_keys(self) -> list:
        """Env var names that may hold this provider's key (first present wins)."""
        return []

    def is_configured(self, env: dict) -> bool:
        """True if this provider can be probed right now."""
        if self.kind == "local":
            return self.reachable(env)
        return any(env.get(k) for k in self.env_keys())

    def discover(self, env: dict, existing: list) -> list:
        """Return candidate model IDs (discovery only, unverified)."""
        raise NotImplementedError

    def probe(self, model_id: str, env: dict) -> ProbeResult:
        """Minimal functional probe. Must be cheap (~1 token)."""
        raise NotImplementedError

    def metadata(self, model_id: str) -> Optional[ModelMeta]:
        if self._meta_loader:
            return self._meta_loader(model_id)
        return None

    def reachable(self, env: dict) -> bool:
        return True

    # --- helpers ---
    def _key(self, env: dict) -> str:
        for k in self.env_keys():
            if env.get(k):
                return env[k]
        return ""

    def _probe_with_recheck(self, send, model_id: str) -> ProbeResult:
        """Canonical probe with one deterministic re-check for ambiguous 4xx
        (tour 11b improvement 1: never classify a generic 4xx as UNAVAILABLE on
        a single observation)."""
        t0 = time.monotonic()
        code, body, err = send()
        res = classify_status(code, err)
        res.latency_ms = int((time.monotonic() - t0) * 1000)
        if res.status == UNAVAILABLE and res.reason == R_MODEL_REJECTED and code is not None:
            # Ambiguous 4xx: re-probe once; deterministic failure => UNAVAILABLE.
            code2, _body2, err2 = send()
            res2 = classify_status(code2, err2)
            if res2.status != UNAVAILABLE:
                return ProbeResult(TRANSIENT, R_PAYLOAD_INVALID, code,
                                   detail=f"non-deterministic 4xx ({code} then {code2})")
        return res
