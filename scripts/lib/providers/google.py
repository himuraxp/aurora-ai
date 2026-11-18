"""Google Gemini adapter (built-in for OpenCode).

Discovery: GET /v1beta/models (API key) — names look like "models/gemini-…";
the "models/" prefix is stripped so IDs match OpenCode references (gemini-…).
Probe: POST /v1beta/models/{id}:generateContent with maxOutputTokens=1.
"""

from __future__ import annotations

from .base import Provider, ProbeResult, http_json

BASE = "https://generativelanguage.googleapis.com/v1beta"

_NON_CHAT_HINTS = ("embedding", "aqa", "imagen", "veo", "tts")


class GoogleProvider(Provider):
    id = "google"
    kind = "builtin"

    def auth_modes(self):
        return ["env"]

    def env_keys(self):
        return ["GEMINI_API_KEY", "GOOGLE_API_KEY"]

    def discover(self, env: dict, existing: list) -> list:
        ids: list = list(existing or [])
        code, body, _err = http_json(f"{BASE}/models?pageSize=200&key={self._key(env)}")
        if code == 200 and isinstance(body, dict):
            for m in body.get("models", []):
                name = (m.get("name") or "").removeprefix("models/")
                low = name.lower()
                if not name or name in ids:
                    continue
                if any(h in low for h in _NON_CHAT_HINTS):
                    continue
                methods = m.get("supportedGenerationMethods") or []
                if methods and "generateContent" not in methods:
                    continue
                ids.append(name)
        return ids

    def probe(self, model_id: str, env: dict) -> ProbeResult:
        key = self._key(env)
        url = f"{BASE}/models/{model_id}:generateContent?key={key}"

        def send():
            return http_json(
                url,
                method="POST",
                body={"contents": [{"parts": [{"text": "OK"}]}],
                      "generationConfig": {"maxOutputTokens": 1}},
            )

        return self._probe_with_recheck(send, model_id)
