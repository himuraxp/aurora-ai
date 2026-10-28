#!/usr/bin/env python3
"""Publication kChat DM du briefing daily-brief — urllib stdlib, DM uniquement.

Réutilise le bot mail-triage (mêmes variables d'environnement, même base kChat)
sans dépendre du moteur : la frontière de write reste ici, limitée à un message
DM idempotent par jour (marqueur du jour).

Contrat :
  - message depuis --file (ou "-" = stdin) ;
  - dédup par marqueur « Daily Brief YYYY-MM-DD » parmi les derniers posts du DM ;
  - sortie JSON garantie (sent | dry_run | already_sent | skipped | failed), exit 0/1/2 ;
  - le token n'apparaît JAMAIS dans une sortie ; pas de retry automatique.

Limites assumées (usage mono-agent quotidien) :
  - dédup = page 1 des posts récents (60) + check-then-post non atomique — deux
    invocations concurrentes le même jour peuvent publier deux fois ; `--force`
    court-circuite la dédup ;
  - le jour du marqueur vient de --day (défaut : date locale du système) — la
    timezone de la config n'est pas résolue ici.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

DEFAULT_BASE_URL = "https://infomaniak.kchat.infomaniak.com/api/v4"
DEFAULT_ENV_PATH = Path.home() / ".config/opencode/.env"
DEFAULT_CONFIG_PATH = Path.home() / ".config/opencode/daily-brief/config.json"
DEFAULT_TOKEN_ENV = "MAIL_TRIAGE_KCHAT_TOKEN"
DEFAULT_DM_USERNAME_ENV = "MAIL_TRIAGE_KCHAT_DM_USERNAME"
DEFAULT_TIMEOUT_SECONDS = 15
MARKER_TEMPLATE = "Daily Brief {day}"
RECENT_POSTS_PER_PAGE = 60


class KChatError(Exception):
    def __init__(self, status: int, path: str, detail: str = ""):
        super().__init__(
            f"kChat {status} sur {path}" + (f": {detail[:200]}" if detail else "")
        )
        self.status = status
        self.path = path


def emit(payload: dict[str, Any], exit_code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return exit_code


def read_env_vars(path: Path, keys: list[str]) -> dict[str, str]:
    """Lit les clés demandées dans un fichier KEY=VALUE. N'imprime jamais les valeurs."""
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in keys:
            value = value.strip().strip('"').strip("'")
            if value:
                found[key] = value
    return found


def load_config(path: Path) -> dict[str, Any]:
    """Config privée optionnelle — absence = défauts sensibles, JSON invalide = erreur."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RuntimeError(f"config invalide ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"config invalide ({path}): objet JSON attendu")
    return data


class MinimalKChat:
    """Client DM minimal (même API que le moteur mail-triage, stdlib uniquement)."""

    def __init__(self, base_url: str, token: str, timeout_seconds: int):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout_seconds

    def _request(self, path: str, method: str = "GET", body: Any = None) -> Any:
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

    def direct_channel_id(self, dm_username: str) -> str:
        me = self._request("/users/me")
        bot_user_id = me.get("id") if isinstance(me, dict) else None
        if not bot_user_id:
            raise KChatError(0, "/users/me", "réponse sans id")
        target = self._request(f"/users/username/{quote(dm_username, safe='')}")
        target_user_id = target.get("id") if isinstance(target, dict) else None
        if not target_user_id:
            raise KChatError(0, "/users/username", "utilisateur DM introuvable")
        channel = self._request(
            "/channels/direct", method="POST", body=[bot_user_id, target_user_id]
        )
        channel_id = channel.get("id") if isinstance(channel, dict) else None
        if not channel_id:
            raise KChatError(0, "/channels/direct", "réponse sans id")
        return channel_id

    def recent_posts(self, channel_id: str) -> list[dict[str, Any]]:
        data = self._request(
            f"/channels/{quote(channel_id, safe='')}/posts"
            f"?per_page={RECENT_POSTS_PER_PAGE}"
        )
        posts = data.get("posts", {}) if isinstance(data, dict) else {}
        return list(posts.values()) if isinstance(posts, dict) else []

    def post_message(self, channel_id: str, message: str) -> dict[str, Any]:
        return self._request(
            "/posts", method="POST", body={"channel_id": channel_id, "message": message}
        )


def main() -> int:
    """Wrapper JSON-garanti : toute exception non prévue reste une sortie JSON."""
    try:
        return _main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover — filet ultime (contrat JSON)
        return emit({"status": "failed", "reason": "internal_error",
                     "detail": str(exc)[:200]}, 2)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Publie le briefing daily-brief en DM kChat.")
    parser.add_argument("--file", required=True,
                        help="chemin du briefing markdown ('-' = stdin)")
    parser.add_argument("--force", action="store_true",
                        help="publication même si le marqueur du jour existe déjà")
    parser.add_argument("--dry-run", action="store_true",
                        help="construit la requête sans toucher au réseau")
    parser.add_argument("--day", default=None,
                        help="jour du marqueur de dédup (défaut : date locale du système)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                        help=f"config privée (défaut {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH),
                        help=f"fichier .env (défaut {DEFAULT_ENV_PATH})")
    args = parser.parse_args()

    marker = MARKER_TEMPLATE.format(day=args.day or date.today().isoformat())

    # 1. Message (fail-closed sur la source du contenu)
    if args.file == "-":
        message = sys.stdin.read()
    else:
        message_path = Path(args.file).expanduser()
        if not message_path.is_file():
            return emit({"status": "failed", "reason": "file_not_found",
                         "file": str(message_path)}, 2)
        message = message_path.read_text(encoding="utf-8", errors="replace")
    if not message.strip():
        return emit({"status": "failed", "reason": "empty_message"}, 2)
    if marker not in message:
        message = message.rstrip("\n") + f"\n\n{marker}\n"

    # 2. Config privée (défauts si absente, erreur explicite si invalide)
    try:
        config = load_config(Path(args.config).expanduser())
    except RuntimeError as exc:
        return emit({"status": "failed", "reason": "invalid_config",
                     "detail": str(exc)[:200]}, 2)
    kchat_cfg = config.get("kchat", {})
    if not isinstance(kchat_cfg, dict):
        kchat_cfg = {}
    if kchat_cfg.get("enabled") is False:
        return emit({"status": "skipped", "reason": "kchat_disabled"}, 0)

    # 3. Credentials (présence vérifiée, valeur jamais exposée)
    token_env = str(kchat_cfg.get("token_env") or DEFAULT_TOKEN_ENV)
    dm_username_env = str(kchat_cfg.get("dm_username_env") or DEFAULT_DM_USERNAME_ENV)
    env_vars = read_env_vars(Path(args.env_file).expanduser(), [token_env, dm_username_env])
    token = env_vars.get(token_env, "")
    dm_username = env_vars.get(dm_username_env, "")
    missing = [name for name, value in
               ((token_env, token), (dm_username_env, dm_username)) if not value]
    if missing:
        return emit({"status": "failed", "reason": "missing_env", "variables": missing}, 2)

    if args.dry_run:
        return emit({"status": "dry_run", "marker": marker}, 0)

    # 4. Publication (dédup par marqueur du jour, pas de retry automatique)
    try:
        timeout_seconds = int(kchat_cfg.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return emit({"status": "failed", "reason": "invalid_config",
                     "detail": "kchat.timeout_seconds doit être un entier"}, 2)
    client = MinimalKChat(
        str(kchat_cfg.get("base_url") or DEFAULT_BASE_URL),
        token,
        timeout_seconds,
    )
    try:
        channel_id = client.direct_channel_id(dm_username)
        if not args.force:
            for post in client.recent_posts(channel_id):
                if marker in (post.get("message") or ""):
                    return emit({"status": "already_sent", "marker": marker,
                                 "channel_id": channel_id}, 0)
        created = client.post_message(channel_id, message)
        post_id = created.get("id") if isinstance(created, dict) else None
        return emit({"status": "sent", "marker": marker,
                     "channel_id": channel_id, "post_id": post_id}, 0)
    except KChatError as exc:
        return emit({"status": "failed", "reason": "kchat_error",
                     "status_code": exc.status, "path": exc.path,
                     "detail": str(exc)[:200]}, 1)


if __name__ == "__main__":
    sys.exit(main())
