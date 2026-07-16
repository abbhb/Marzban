"""Regression tests for dashboard compression and browser cache policy."""

from __future__ import annotations

import asyncio
import gzip
import tempfile
import unittest
from pathlib import Path

from app import EventStreamSafeGZipMiddleware
from app.dashboard import DashboardStaticFiles


def _http_scope(*, accept_encoding: str = "") -> dict:
    headers = []
    if accept_encoding:
        headers.append((b"accept-encoding", accept_encoding.encode()))
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


async def _run_asgi(application, scope: dict) -> list[dict]:
    messages = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await application(scope, receive, send)
    return messages


def _response_headers(messages: list[dict]) -> dict[str, str]:
    response_start = next(message for message in messages if message["type"] == "http.response.start")
    return {
        key.decode().lower(): value.decode()
        for key, value in response_start["headers"]
    }


class DashboardStaticCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        (root / "locales").mkdir()
        (root / "index.html").write_text("<main>dashboard</main>")
        (root / "404.html").write_text("<main>missing</main>")
        (root / "index.69b30b9c.js").write_text("console.log('dashboard')")
        (root / "locales" / "zh.json").write_text('{"loading":"loading"}')
        (root / "favicon.ico").write_bytes(b"favicon")
        self.static = DashboardStaticFiles(directory=root, html=True)

    def response(self, path: str, *, headers=None):
        scope = _http_scope()
        scope["path"] = f"/{path}" if path else "/"
        scope["raw_path"] = scope["path"].encode()
        scope["headers"] = headers or []
        return asyncio.run(self.static.get_response(path, scope))

    def test_cache_policy_matches_asset_mutability(self) -> None:
        self.assertEqual(
            "no-cache, max-age=0, must-revalidate",
            self.response("index.html").headers["cache-control"],
        )
        self.assertEqual(
            "public, max-age=31536000, immutable",
            self.response("index.69b30b9c.js").headers["cache-control"],
        )
        self.assertEqual(
            "public, max-age=3600, must-revalidate",
            self.response("locales/zh.json").headers["cache-control"],
        )
        self.assertEqual(
            "public, max-age=86400, must-revalidate",
            self.response("favicon.ico").headers["cache-control"],
        )

    def test_html_fallback_is_never_immutable(self) -> None:
        response = self.response("missing-route")

        self.assertEqual(404, response.status_code)
        self.assertEqual(
            "no-cache, max-age=0, must-revalidate",
            response.headers["cache-control"],
        )

    def test_revalidation_response_keeps_cache_policy(self) -> None:
        initial = self.response("index.69b30b9c.js")
        response = self.response(
            "index.69b30b9c.js",
            headers=[(b"if-none-match", initial.headers["etag"].encode())],
        )

        self.assertEqual(304, response.status_code)
        self.assertEqual(
            "public, max-age=31536000, immutable",
            response.headers["cache-control"],
        )

        html_initial = self.response("index.html")
        html_response = self.response(
            "index.html",
            headers=[(b"if-none-match", html_initial.headers["etag"].encode())],
        )
        self.assertEqual(304, html_response.status_code)
        self.assertEqual(
            "no-cache, max-age=0, must-revalidate",
            html_response.headers["cache-control"],
        )


class DashboardGZipTests(unittest.TestCase):
    def test_large_http_response_is_compressed(self) -> None:
        body = b"dashboard-static-resource" * 200

        async def application(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/javascript"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})

        middleware = EventStreamSafeGZipMiddleware(
            application,
            minimum_size=1024,
            compresslevel=6,
        )
        messages = asyncio.run(
            _run_asgi(middleware, _http_scope(accept_encoding="br, gzip"))
        )
        headers = _response_headers(messages)
        compressed_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )

        self.assertEqual("gzip", headers["content-encoding"])
        self.assertEqual("Accept-Encoding", headers["vary"])
        self.assertEqual(body, gzip.decompress(compressed_body))

    def test_event_stream_is_not_compressed_or_buffered(self) -> None:
        chunks = [b"data: first\n\n", b"data: second\n\n"]

        async def application(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream; charset=utf-8")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": chunks[0],
                    "more_body": True,
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": chunks[1],
                    "more_body": False,
                }
            )

        middleware = EventStreamSafeGZipMiddleware(
            application,
            minimum_size=1,
            compresslevel=6,
        )
        messages = asyncio.run(
            _run_asgi(middleware, _http_scope(accept_encoding="gzip"))
        )
        headers = _response_headers(messages)
        bodies = [
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        ]

        self.assertNotIn("content-encoding", headers)
        self.assertEqual(chunks, bodies)

    def test_websocket_scope_bypasses_compression(self) -> None:
        sent = [
            {"type": "websocket.accept"},
            {"type": "websocket.send", "text": "core log"},
        ]

        async def application(scope, receive, send):
            self.assertEqual("websocket", scope["type"])
            for message in sent:
                await send(message)

        middleware = EventStreamSafeGZipMiddleware(
            application,
            minimum_size=1,
            compresslevel=6,
        )
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "path": "/api/core/logs",
            "raw_path": b"/api/core/logs",
            "query_string": b"",
            "headers": [(b"accept-encoding", b"gzip")],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "scheme": "ws",
            "subprotocols": [],
        }
        messages = asyncio.run(_run_asgi(middleware, scope))

        self.assertEqual(sent, messages)
