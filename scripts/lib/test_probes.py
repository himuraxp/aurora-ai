#!/usr/bin/env python3
"""Contractual probe tests (mocked HTTP) — no network, no keys.

Tour 13 improvement 4: every chat adapter must produce the IDENTICAL
ProbeResult semantics for 2xx / deterministic 4xx / auth / 429 / 5xx /
timeout / network error. We patch each adapter module's `http_json`
reference (adapters resolve it at call time via their module globals)
and drive Provider.probe() directly.

Run: python3 scripts/lib/test_probes.py   (exit 0 = all pass)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import providers.base as base  # noqa: E402
import providers.infomaniak as infomaniak  # noqa: E402
import providers.openai as openai  # noqa: E402
import providers.anthropic as anthropic  # noqa: E402
import providers.google as google  # noqa: E402
import providers.openrouter as openrouter  # noqa: E402
import providers.ollama as ollama  # noqa: E402

MODEL = "test-model"

CHAT_ADAPTERS = [
    (infomaniak, infomaniak.InfomaniakProvider),
    (openai, openai.OpenAIProvider),
    (anthropic, anthropic.AnthropicProvider),
    (google, google.GoogleProvider),
    (openrouter, openrouter.OpenRouterProvider),
    (ollama, ollama.OllamaProvider),
]


def ok(url, **kw):
    return (200, {"ok": True}, None)


def det400(url, **kw):
    return (400, {"error": "nope"}, None)


def nd400():
    """400 on first call, 200 on retry → non-deterministic 4xx."""
    state = {"n": 0}

    def send(url, **kw):
        state["n"] += 1
        return (400, {"error": "weird"}, None) if state["n"] % 2 else (200, {"ok": True}, None)
    return send


# (name, expected status, expected reason-or-None, http behaviour factory)
SCENARIOS = [
    ("2xx ok", base.VERIFIED, None, lambda: ok),
    ("deterministic 400", base.UNAVAILABLE, base.R_MODEL_REJECTED, lambda: det400),
    ("non-deterministic 400", base.TRANSIENT, base.R_PAYLOAD_INVALID, nd400),
    ("401 auth", base.AUTH_REQUIRED, base.R_AUTH_FAILED,
     lambda: (lambda url, **kw: (401, None, None))),
    ("403 not entitled", base.UNAVAILABLE, base.R_NOT_ENTITLED,
     lambda: (lambda url, **kw: (403, None, None))),
    ("429 rate limit", base.TRANSIENT, base.R_RATE_LIMITED,
     lambda: (lambda url, **kw: (429, None, None))),
    ("500 server", base.TRANSIENT, base.R_SERVER_ERROR,
     lambda: (lambda url, **kw: (500, None, None))),
    ("timeout", base.TRANSIENT, base.R_TIMEOUT,
     lambda: (lambda url, **kw: (None, None, "timeout"))),
    ("network error", base.TRANSIENT, base.R_NETWORK,
     lambda: (lambda url, **kw: (None, None, "network: refused"))),
]


def run_probe(module, cls, behaviour):
    calls = {"n": 0}

    def spy(url, **kw):
        calls["n"] += 1
        return behaviour(url, **kw)

    saved = module.http_json
    module.http_json = spy
    try:
        res = cls().probe(MODEL, {})
        return res.status, res.reason, calls["n"]
    finally:
        module.http_json = saved


def main() -> int:
    failures = []
    checks = 0
    for module, cls in CHAT_ADAPTERS:
        for name, want_status, want_reason, make in SCENARIOS:
            status, reason, _calls = run_probe(module, cls, make())
            checks += 1
            if status != want_status or reason != want_reason:
                failures.append(
                    f"{module.__name__}.{cls.__name__} [{name}]: "
                    f"got ({status}, {reason}) want ({want_status}, {want_reason})")
        # deterministic-4xx must always consume exactly 2 HTTP calls (re-check)
        _, _, calls = run_probe(module, cls, det400)
        checks += 1
        if calls != 2:
            failures.append(f"{module.__name__}: deterministic 400 used "
                            f"{calls} calls, want 2 (re-check invariant)")

    if failures:
        print(f"FAILED ({len(failures)}/{checks} checks):")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print(f"OK — {checks} contractual checks passed across "
          f"{len(CHAT_ADAPTERS)} adapters.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
