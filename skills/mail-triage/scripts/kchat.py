"""Client kChat minimal (fork Mattermost) — urllib stdlib, DM uniquement.

Frontière de write séparée du moteur IMAP (invariant 9) : les publications kChat
ont leur propre kill switch. Jamais de retry automatique : une publication dont
le résultat est inconnu passe en 'uncertain' et est réconciliée par le CLI.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class KChatError(Exception):
    def __init__(self, status: int, path: str, detail: str = ""):
        super().__init__(f"kChat {status} sur {path}" + (f": {detail[:200]}" if detail else ""))
        self.status = status
        self.path = path


class KChatClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: int = 15):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout_seconds

    def _request(self, path: str, method: str = "GET", body: dict | None = None) -> dict | list:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                **({} if body is None else {"Content-Type": "application/json"}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise KChatError(exc.code, path, detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise KChatError(0, path, str(type(exc).__name__)) from exc

    def me(self) -> dict:
        return self._request("/users/me")

    def user_by_username(self, username: str) -> dict:
        return self._request(f"/users/username/{urllib.request.quote(username, safe='')}")

    def ensure_direct_channel(self, bot_user_id: str, recipient_user_id: str) -> str:
        """Canal DM (idempotent côté serveur : même paire → même canal)."""
        channel = self._request(
            "/channels/direct", method="POST", body=[bot_user_id, recipient_user_id]
        )
        channel_id = channel.get("id") if isinstance(channel, dict) else None
        if not channel_id:
            raise KChatError(0, "/channels/direct", "réponse sans id")
        return channel_id

    def post_message(self, channel_id: str, message: str, props: dict | None = None) -> dict:
        return self._request(
            "/posts",
            method="POST",
            body={"channel_id": channel_id, "message": message, "props": props or {}},
        )

    def get_post(self, post_id: str) -> dict:
        return self._request(f"/posts/{urllib.request.quote(post_id, safe='')}")

    def recent_channel_posts(self, channel_id: str, per_page: int = 30) -> list[dict]:
        data = self._request(f"/channels/{urllib.request.quote(channel_id, safe='')}/posts"
                             f"?per_page={int(per_page)}")
        posts = data.get("posts", {}) if isinstance(data, dict) else {}
        return list(posts.values()) if isinstance(posts, dict) else []

    def find_marker_in_channel(self, channel_id: str, marker: str, per_page: int = 60) -> str | None:
        """Retrouve un post contenant le marqueur (réconciliation des publications incertaines)."""
        for post in self.recent_channel_posts(channel_id, per_page=per_page):
            if marker in (post.get("message") or ""):
                return post.get("id")
        return None
