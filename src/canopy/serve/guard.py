"""Checks every request's Host header, its body's size, and the Origin header of API requests, before anything else.

Allowed hosts are the loopback names and the address the server binds (`ServeOptions.hosts`). Host stops DNS
rebinding: a page on an attacker's name that resolves to 127.0.0.1 sends its own name as Host. Origin stops a page on
another site from calling the API, SSE included. Only the host name is compared, not the port, so an
SSH forward to another local port (`ssh -L 9000:127.0.0.1:8765`) still works. A request with no Origin is allowed:
browsers omit it on same-origin GETs, and non-browser clients never send one.

FastAPI reads and parses a route's body before any dependency runs, the session check included, so the size is checked
here, where a client that has not signed in reaches too. uvicorn frames an HTTP/1.1 body by its Content-Length, so the
header bounds what the app can read; a chunked body has none, and is refused, as no page of canopy's sends one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Sent on every response. No framing (clickjacking), no MIME sniffing, no Referer to anywhere.
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)
# The largest body a request may carry. The largest the API takes is a reply's 20,000 characters, at most 120,000 bytes
# of JSON when every one is escaped as `\u0001`.
MAX_BODY_BYTES = 256 * 1024


def host_name(host: str) -> str:
    """Return the name in a Host header value, without its port: `[::1]:8765` is `::1`."""
    if host.startswith("["):
        return host[1:].partition("]")[0]
    name, _, port = host.rpartition(":")
    return name if name and port.isdigit() else host


def allowed_origin(origin: str, hosts: frozenset[str]) -> bool:
    """Whether an Origin header value names a page on one of `hosts`, served over HTTP(S).

    Returns:
        True if its scheme is http or https and its host name is in `hosts`.
    """
    parts = urlsplit(origin)
    return parts.scheme in {"http", "https"} and (parts.hostname or "") in hosts


class Guard:
    """ASGI middleware: refuses a foreign Host anywhere and a foreign Origin under the API prefix."""

    def __init__(self, app: ASGIApp, *, api_prefix: str, hosts: frozenset[str]) -> None:
        """Wrap `app`, allowing `hosts`; requests whose path starts with `api_prefix` get the Origin check too."""
        self.app = app
        self.api_prefix = api_prefix
        self.hosts = hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the request, then pass it on with the security headers added to the response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        refusal = self._refusal(scope["path"], headers)
        if refusal is not None:
            status, detail = refusal
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw = message.get("headers")
                message["headers"] = [*(raw if isinstance(raw, list) else []), *SECURITY_HEADERS]
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _refusal(self, path: str, headers: Headers) -> tuple[int, str] | None:
        if host_name(headers.get("host", "")) not in self.hosts:
            return 403, "host not allowed"
        api = path == self.api_prefix or path.startswith(self.api_prefix + "/")
        origin = headers.get("origin")
        if api and origin is not None and not allowed_origin(origin, self.hosts):
            return 403, "origin not allowed"
        if "transfer-encoding" in headers:
            return 411, "a request body needs a Content-Length"
        # uvicorn refuses a Content-Length that is not a number before the app sees the request.
        length = headers.get("content-length", "0")
        if length.isascii() and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return 413, f"a request body may be at most {MAX_BODY_BYTES} bytes"
        return None
