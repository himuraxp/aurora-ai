"""Ollama / local adapter (OpenAI-compatible local server).

Discovery + probe against http://localhost:11434/v1 (Ollama default).
The provider is only considered configured when the server answers; anything
else is OFFLINE and silently skipped (locals come and go).
"""

from __future__ import annotations

from .base import Provider, ProbeResult, R_OFFLINE, http_json

BASE = "http://localhost:11434/v1"


class OllamaProvider(Provider):
    id = "ollama"
    kind = "local"

    def auth_modes(self):
        return ["none"]

    def env_keys(self):
        return []

    def reachable(self, env: dict) -> bool:
        code, _body, _err = http_json(f"{BASE}/models", timeout=3)
        return code == 200

    def discover(self, env: dict, existing: list) -> list:
        ids: list = list(existing or [])
        code, body, _err = http_json(f"{BASE}/models", timeout=5)
        if code == 200 and isinstance(body, dict):
            for m in body.get("data", []):
                mid = m.get("id") or ""
                if mid and mid not in ids:
                    ids.append(mid)
        return ids

    def probe(self, model_id: str, env: dict) -> ProbeResult:
        def send():
            code, body, err = http_json(
                f"{BASE}/chat/completions",
                method="POST",
                body={"model": model_id,
                      "messages": [{"role": "user", "content": "OK"}],
                      "max_tokens": 1},
                timeout=8,
            )
            if code is None and err:
                return code, body, err
            return code, body, err

        res = self._probe_with_recheck(send, model_id)
        if res.status == "UNKNOWN_TRANSIENT" and res.reason == R_OFFLINE:
            return res
        return res
