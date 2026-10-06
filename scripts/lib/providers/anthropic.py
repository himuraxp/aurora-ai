"""Anthropic adapter (built-in for OpenCode).

Discovery: GET /v1/models (x-api-key) — lists models visible to the key.
Probe: POST /v1/messages with max_tokens=1.
OAuth (Claude Pro/Max) credentials live in OpenCode's auth store: the engine
probes those through the OpenCode runtime (`opencode run --model`), never by
parsing auth.json (tour 12, condition 3).
"""

from __future__ import annotations

from .base import Provider, ProbeResult, http_json

BASE = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"


class AnthropicProvider(Provider):
    id = "anthropic"
    kind = "builtin"

    def auth_modes(self):
        return ["env", "opencode_auth"]

    def env_keys(self):
        return ["ANTHROPIC_API_KEY"]

    def discover(self, env: dict, existing: list) -> list:
        ids: list = list(existing or [])
        code, body, _err = http_json(
            f"{BASE}/models?limit=100",
            headers={"x-api-key": self._key(env), "anthropic-version": VERSION},
        )
        if code == 200 and isinstance(body, dict):
            for m in body.get("data", []):
                mid = m.get("id") or ""
                if mid and mid not in ids:
                    ids.append(mid)
        return ids

    def probe(self, model_id: str, env: dict) -> ProbeResult:
        headers = {"x-api-key": self._key(env), "anthropic-version": VERSION}

        def send():
            return http_json(
                f"{BASE}/messages",
                method="POST",
                headers=headers,
                body={"model": model_id, "max_tokens": 1,
                      "messages": [{"role": "user", "content": "OK"}]},
            )

        return self._probe_with_recheck(send, model_id)
