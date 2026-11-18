"""OpenRouter adapter (aggregator — one key, many model families).

Discovery: GET /api/v1/models is a PUBLIC catalog (huge, 300+ IDs) — discovery
only, never entitlement. The engine probes only the role-relevant shortlist
(probe budget) because of rate limits.
Probe: POST /api/v1/chat/completions (OpenAI-compatible, max_tokens=1).
"""

from __future__ import annotations

from .base import Provider, ProbeResult, http_json

BASE = "https://openrouter.ai/api/v1"


class OpenRouterProvider(Provider):
    id = "openrouter"
    kind = "builtin"

    def auth_modes(self):
        return ["env", "opencode_auth"]

    def env_keys(self):
        return ["OPENROUTER_API_KEY"]

    def discover(self, env: dict, existing: list) -> list:
        ids: list = list(existing or [])
        headers = {"Authorization": f"Bearer {self._key(env)}"} if self._key(env) else {}
        code, body, _err = http_json(f"{BASE}/models", headers=headers)
        if code == 200 and isinstance(body, dict):
            for m in body.get("data", []):
                mid = m.get("id") or ""
                if mid and mid not in ids:
                    ids.append(mid)
        return ids

    def probe(self, model_id: str, env: dict) -> ProbeResult:
        headers = {"Authorization": f"Bearer {self._key(env)}"}

        def send():
            return http_json(
                f"{BASE}/chat/completions",
                method="POST",
                headers=headers,
                body={"model": model_id,
                      "messages": [{"role": "user", "content": "OK"}],
                      "max_tokens": 1},
            )

        return self._probe_with_recheck(send, model_id)
