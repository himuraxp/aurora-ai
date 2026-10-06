"""OpenAI adapter (built-in for OpenCode — models auto-populated from models.dev).

Discovery: GET /v1/models with the API key (lists what this key can see).
Probe: POST /v1/chat/completions with max_completion_tokens=1.
No provider.models map is generated for this provider (OpenCode native resolution).
"""

from __future__ import annotations

from .base import Provider, ProbeResult, http_json

BASE = "https://api.openai.com/v1"

# Non-chat model families exposed by /v1/models — excluded from chat candidates
_NON_CHAT_PREFIXES = ("dall-e", "whisper", "tts", "davinci", "babbage",
                      "text-embedding", "text-search", "text-similarity", "ada")


class OpenAIProvider(Provider):
    id = "openai"
    kind = "builtin"

    def auth_modes(self):
        return ["env", "opencode_auth"]

    def env_keys(self):
        return ["OPENAI_API_KEY"]

    def is_configured(self, env: dict) -> bool:
        # A common pattern reuses OPENAI_API_KEY with OPENAI_BASE_URL pointing
        # at another OpenAI-compatible service (e.g. Infomaniak). Probing
        # api.openai.com with such a key is wrong — treat as not-OpenAI.
        base = env.get("OPENAI_BASE_URL", "")
        if base and "api.openai.com" not in base:
            return False
        return bool(self._key(env))

    def discover(self, env: dict, existing: list) -> list:
        ids: list = list(existing or [])
        code, body, _err = http_json(f"{BASE}/models",
                                     headers={"Authorization": f"Bearer {self._key(env)}"})
        if code == 200 and isinstance(body, dict):
            for m in body.get("data", []):
                mid = m.get("id") or ""
                if mid and not mid.lower().startswith(_NON_CHAT_PREFIXES) and mid not in ids:
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
                      "max_completion_tokens": 1},
            )

        return self._probe_with_recheck(send, model_id)
