"""Checks every request's Host header, and the Origin header of API requests, before anything else sees them.

Host stops DNS rebinding: a page on an attacker's name that resolves to 127.0.0.1 sends its own name as Host. Origin
stops a page on another site from calling the API, SSE included. Only the host name is compared, not the port, so an
SSH forward to another local port (`ssh -L 9000:127.0.0.1:8765`) still works. A request with no Origin is allowed:
browsers omit it on same-origin GETs, and non-browser clients never send one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

from canopy.serve.options import LOOPBACK_NAMES

# Sent on every response. No framing (clickjacking), no MIME sniffing, no Referer to anywhere.
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)


def host_name(host: str) -> str:
    """Return the name in a Host header value, without its port: `[::1]:8765` is `::1`."""
    if host.startswith("["):
        return host[1:].partition("]")[0]
    name, _, port = host.rpartition(":")
    return name if name and port.isdigit() else host


def allowed_origin(origin: str) -> bool:
    """Whether an Origin header value names a loopback page served over HTTP(S)."""
    parts = urlsplit(origin)
    return parts.scheme in {"http", "https"} and (parts.hostname or "") in LOOPBACK_NAMES


class Guard:
    """ASGI middleware: refuses a foreign Host anywhere and a foreign Origin under the API prefix."""

    def __init__(self, app: ASGIApp, *, api_prefix: str) -> None:
        """Wrap `app`; requests whose path starts with `api_prefix` get the Origin check too."""
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the request, then pass it on with the security headers added to the response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        refusal = self._refusal(scope["path"], headers)
        if refusal is not None:
            await JSONResponse({"detail": refusal}, status_code=403)(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw = message.get("headers")
                message["headers"] = [*(raw if isinstance(raw, list) else []), *SECURITY_HEADERS]
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _refusal(self, path: str, headers: Headers) -> str | None:
        if host_name(headers.get("host", "")) not in LOOPBACK_NAMES:
            return "host not allowed"
        api = path == self.api_prefix or path.startswith(self.api_prefix + "/")
        origin = headers.get("origin")
        if api and origin is not None and not allowed_origin(origin):
            return "origin not allowed"
        return None
