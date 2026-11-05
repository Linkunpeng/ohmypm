"""Local-only protections for the Web API.

The server listens on 127.0.0.1, but that alone does not protect against:

* other local users  -> an access token (cookie or ``Authorization: Bearer``);
* DNS rebinding      -> the ``Host`` header must name a loopback host;
* cross-site writes  -> unsafe methods require a same-origin ``Origin``
                        (and are refused when ``Sec-Fetch-Site: cross-site``);
* huge requests      -> a request body size limit.
"""

from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode

from ohmypm.config import Settings, ensure_private_dir
from ohmypm.storage.files import atomic_write_text

COOKIE_NAME = "ohmypm_token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
OPEN_PATHS = {"/api/health"}

HTML_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def load_or_create_token(settings: Settings) -> str:
    path: Path = settings.web_token_file
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    ensure_private_dir(settings.data_dir)
    token = secrets.token_urlsafe(32)
    atomic_write_text(path, token + "\n", mode=0o600)
    return token


def _host_only(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


async def _send_json(send: Any, status: int, payload: dict[str, Any], headers: list | None = None) -> None:
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *(headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


class LocalSecurityMiddleware:
    """Pure ASGI middleware applying the protections described above."""

    def __init__(
        self,
        app: Any,
        *,
        token: str | None,
        allowed_hosts: Iterable[str] = (),
        allowed_origins: Iterable[str] = (),
        max_body_bytes: int,
        max_upload_bytes: int,
    ) -> None:
        self.app = app
        self.token = token
        self.allowed_hosts = {h.lower() for h in LOOPBACK_HOSTS | set(allowed_hosts)}
        self.allowed_origins = {o.rstrip("/").lower() for o in allowed_origins}
        self.max_body = max_body_bytes
        self.max_upload = max_upload_bytes

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        method = scope["method"].upper()
        path: str = scope.get("path", "/")

        host_header = headers.get("host", "")
        if "*" not in self.allowed_hosts and _host_only(host_header) not in self.allowed_hosts:
            await _send_json(send, 421, _error("bad_host", "Requests must use a loopback host name"))
            return

        origin = headers.get("origin")
        own_origins = {f"http://{host_header.lower()}", f"https://{host_header.lower()}"}
        if method in UNSAFE_METHODS:
            if origin and origin.rstrip("/").lower() not in own_origins | self.allowed_origins:
                await _send_json(
                    send, 403, _error("bad_origin", "Cross-origin write requests are not allowed")
                )
                return
            if headers.get("sec-fetch-site") == "cross-site" and not (
                origin and origin.rstrip("/").lower() in self.allowed_origins
            ):
                await _send_json(send, 403, _error("bad_origin", "Cross-site requests are not allowed"))
                return

        # ?token=... on a page load: set the cookie and redirect to a clean URL.
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        if self.token and method == "GET" and "token" in query and not path.startswith("/api/"):
            supplied = query.pop("token")[0]
            if hmac.compare_digest(supplied, self.token):
                location = path + ("?" + urlencode(query, doseq=True) if query else "")
                cookie = f"{COOKIE_NAME}={self.token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
                await send(
                    {
                        "type": "http.response.start",
                        "status": 303,
                        "headers": [
                            (b"location", location.encode()),
                            (b"set-cookie", cookie.encode()),
                            (b"content-length", b"0"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b""})
                return

        if (
            self.token
            and path.startswith("/api/")
            and path not in OPEN_PATHS
            and not self._authorized(headers)
        ):
            await _send_json(
                send, 401, _error("unauthorized", "Open the URL printed by `ohmypm web` to sign in")
            )
            return

        limit = self.max_upload if path.startswith("/api/assets") else self.max_body
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > limit:
            await _send_json(send, 413, _error("too_large", f"Request body exceeds {limit} bytes"))
            return

        received = 0

        async def limited_receive() -> dict:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge()
            return message

        sent_start = False

        async def guarded_send(message: dict) -> None:
            nonlocal sent_start
            if message["type"] == "http.response.start":
                sent_start = True
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                ]
                existing = {k.lower() for k, _ in message.get("headers", [])}
                if b"content-security-policy" not in existing:
                    extra.append((b"content-security-policy", HTML_CSP.encode()))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLarge:
            if not sent_start:
                await _send_json(send, 413, _error("too_large", f"Request body exceeds {limit} bytes"))

    def _authorized(self, headers: dict[str, str]) -> bool:
        assert self.token is not None
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and hmac.compare_digest(auth[7:].strip(), self.token):
            return True
        for part in headers.get("cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME and hmac.compare_digest(value, self.token):
                return True
        return False


class _TooLarge(Exception):
    pass
