"""Infomaniak adapter (custom, OpenAI-compatible private endpoint).

Spike-validated facts (2026-10-06):
- GET /2/ai/private/openai/v1/models -> 200, lists routable IDs for the key
  (private aliases like euria-code + full catalog names) but is NOT exhaustive
  (nvidia/Nemotron probes OK while absent from the list).
- Probes: POST chat/completions with max_completion_tokens=1.
- GET /1/ai/models (management token) gives the public catalog with type +
  info_status (ready|coming_soon) — discovery enrichment only, not entitlement.
"""

from __future__ import annotations

import urllib.request

from .base import Provider, ProbeResult, http_json

PRIVATE_BASE = "https://api.infomaniak.com/2/ai/private/openai/v1"
CATALOG_URL = "https://api.infomaniak.com/1/ai/models"

# ID prefixes in the private endpoint that are not chat models
_EMBED_HINTS = ("embed", "bge", "mini_lm", "minilm")
_STT_HINTS = ("whisper",)


class InfomaniakProvider(Provider):
    id = "infomaniak"
    kind = "custom"

    def auth_modes(self):
        return ["env"]

    def env_keys(self):
        return ["OPENAI_API_KEY_INFOMANIAK", "INFOMANIAK_API_TOKEN"]

    def discover(self, env: dict, existing: list) -> list:
        ids: list = []
        # 1. Private /models (routable for this key — primary source)
        code, body, _err = http_json(
            f"{PRIVATE_BASE}/models",
            headers={"Authorization": f"Bearer {self._key(env)}"},
        )
        if code == 200 and isinstance(body, dict):
            ids.extend(m.get("id") for m in body.get("data", []) if m.get("id"))
        # 2. Existing config models (historical aliases, e.g. mistral24b)
        ids.extend(existing or [])
        # 3. Public catalog names with a chat endpoint, status ready (enrichment)
        tok = env.get("INFOMANIAK_API_TOKEN") or env.get("OPENAI_API_KEY_INFOMANIAK")
        if tok:
            code, body, _err = http_json(CATALOG_URL, headers={"Authorization": f"Bearer {tok}"})
            if code == 200 and isinstance(body, dict):
                for m in body.get("data", []):
                    if m.get("info_status") == "ready" and m.get("type") == "llm":
                        name = m.get("name") or ""
                        if name and name not in ids:
                            ids.append(name)
        # dedupe preserving order
        seen, out = set(), []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                out.append(i)
        return out

    def probe(self, model_id: str, env: dict) -> "ProbeResult":
        headers = {"Authorization": f"Bearer {self._key(env)}"}

        def send():
            return http_json(
                f"{PRIVATE_BASE}/chat/completions",
                method="POST",
                headers=headers,
                body={"model": model_id,
                      "messages": [{"role": "user", "content": "OK"}],
                      "max_completion_tokens": 1},
            )

        return self._probe_with_recheck(send, model_id)

    def is_stt_or_embedding(self, model_id: str) -> str:
        low = model_id.lower()
        if any(h in low for h in _STT_HINTS):
            return "stt"
        if any(h in low for h in _EMBED_HINTS):
            return "embedding"
        return "chat"
