"""Anthropic adapter (built-in for OpenCode).

Discovery: GET /v1/models (x-api-key) — lists models visible to the key.
Probe: POST /v1/messages with max_tokens=1.
OAuth (Claude Pro/Max) credentials live in OpenCode's auth store: the engine
probes those through the OpenCode runtime (`opencode run --model`), never by
parsing auth.json (tour 12, condition 3).

Workspace scoping (2026-10-07, acceptance gate): an org-scoped API key
(Console → Scope: Organisation) is REJECTED by /v1/models and /v1/messages
with 400 "must include the anthropic-workspace-id header". Admin API
(/v1/organizations/workspaces) requires admin keys — user keys cannot
discover their workspace ID. Set ANTHROPIC_WORKSPACE_ID to use an org key,
or (recommended) create a workspace-scoped key: Scope = default workspace.
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

    def _headers(self, env: dict) -> dict:
        h = {"x-api-key": self._key(env), "anthropic-version": VERSION}
        ws = env.get("ANTHROPIC_WORKSPACE_ID")
        if ws:
            h["anthropic-workspace-id"] = ws
        return h

    def discover(self, env: dict, existing: list) -> list:
        ids: list = list(existing or [])
        code, body, _err = http_json(
            f"{BASE}/models?limit=100",
            headers=self._headers(env),
        )
        if code == 400 and isinstance(body, dict):
            msg = (body.get("error") or {}).get("message", "")
            if "workspace" in msg.lower():
                raise RuntimeError(
                    "org-scoped API key rejected: Anthropic requires "
                    "anthropic-workspace-id for workspace-unscoped keys, and "
                    "user keys cannot list workspaces (admin only). Fix: "
                    "create a workspace-scoped key (Scope = default "
                    "workspace) or set ANTHROPIC_WORKSPACE_ID.")
        if code == 200 and isinstance(body, dict):
            for m in body.get("data", []):
                mid = m.get("id") or ""
                if mid and mid not in ids:
                    ids.append(mid)
        return ids

    def probe(self, model_id: str, env: dict) -> ProbeResult:
        headers = self._headers(env)

        def send():
            return http_json(
                f"{BASE}/messages",
                method="POST",
                headers=headers,
                body={"model": model_id, "max_tokens": 1,
                      "messages": [{"role": "user", "content": "OK"}]},
            )

        return self._probe_with_recheck(send, model_id)
