#!/usr/bin/env python3
"""Tests du client kChat contre un serveur HTTP local — aucun appel réseau externe."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from kchat import KChatClient, KChatError  # noqa: E402


class FakeKChatHandler(BaseHTTPRequestHandler):
    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/users/me":
            self._reply(200, {"id": "bot1"})
        elif self.path == "/users/username/ghost":
            self._reply(404, {"message": "not found"})
        elif self.path == "/users/username/yohann":
            self._reply(200, {"id": "u1"})
        elif self.path.startswith("/channels/") and "/posts" in self.path:
            self._reply(200, {"posts": {"p1": {"id": "p1",
                                               "message": "hello [mail-triage-digest:abc]"}}})
        elif self.path.startswith("/posts/"):
            self._reply(200, {"id": "post1"})
        else:
            self._reply(404, {"message": "unknown"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/channels/direct":
            self._reply(201, {"id": "chan1"})
        elif self.path == "/posts":
            self._reply(201, {"id": "post1", "message": payload.get("message")})
        else:
            self._reply(404, {"message": "unknown"})

    def log_message(self, *args) -> None:  # silence
        pass


class KChatClientTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Isolation proxy : un http_proxy d'environnement intercepterait 127.0.0.1
        cls._proxy_patcher = mock.patch.dict(os.environ)
        cls._proxy_patcher.start()
        for key in ("http_proxy", "https_proxy", "all_proxy",
                    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            os.environ.pop(key, None)
        cls.server = HTTPServer(("127.0.0.1", 0), FakeKChatHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls._proxy_patcher.stop()

    def client(self) -> KChatClient:
        return KChatClient(self.base, "token-test", timeout_seconds=5)

    def test_me(self) -> None:
        self.assertEqual(self.client().me()["id"], "bot1")

    def test_user_by_username(self) -> None:
        self.assertEqual(self.client().user_by_username("yohann")["id"], "u1")

    def test_ensure_direct_channel(self) -> None:
        self.assertEqual(
            self.client().ensure_direct_channel("bot1", "u1"), "chan1")

    def test_post_message(self) -> None:
        post = self.client().post_message("chan1", "# digest")
        self.assertEqual(post["id"], "post1")

    def test_find_marker(self) -> None:
        found = self.client().find_marker_in_channel("chan1", "[mail-triage-digest:abc]")
        self.assertEqual(found, "p1")

    def test_marker_not_found(self) -> None:
        self.assertIsNone(self.client().find_marker_in_channel("chan1", "[absent]"))

    def test_http_error_raises(self) -> None:
        with self.assertRaises(KChatError) as ctx:
            self.client().user_by_username("ghost")
        self.assertEqual(ctx.exception.status, 404)

    def test_connection_error_status_zero(self) -> None:
        # Port libre garanti (bind puis fermeture) → connexion refusée → status 0.
        # Un proxy système macOS intercepterait l'appel : opener SANS proxy.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]
        sock.close()
        no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        dead = KChatClient(f"http://127.0.0.1:{free_port}", "token-test", timeout_seconds=3)
        with mock.patch.object(urllib.request, "urlopen", no_proxy_opener.open):
            with self.assertRaises(KChatError) as ctx:
                dead.me()
        self.assertEqual(ctx.exception.status, 0)


if __name__ == "__main__":
    unittest.main()
