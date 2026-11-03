"""Traces each request the web UI's server answers, as a server span of its own, while traces are on (D132).

A request is a trace of its own, named for its method and its route as canopy's code spells it, `GET
/api/tickets/{key}`, under OpenTelemetry's HTTP conventions: the method, the route, and the status it was answered
with. Nothing the client sent beyond a method HTTP names: never the path's values, the query, a header, the cookie, or
the body, which may hold the operator's words or credentials; a `traceparent` it sent is not read, so no client starts
or joins a trace of canopy's. A request no route matched, such as one the guard refused, is named for its method alone.
One answered with a 5xx is failed, as the conventions have a server's span. A span lasts until the answer's last byte,
so one of a stream the page holds open is as long as the page kept it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.infra import tracing

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: The methods HTTP names; any other a client sends is recorded as `_OTHER`, as the convention has it.
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"})
#: The least status that fails a server's span: a 4xx is the client's error, not the server's.
SERVER_ERROR = 500


class Traced:
    """ASGI middleware, outermost: a span for each HTTP request, from its arrival to its answer's end."""

    def __init__(self, app: ASGIApp, *, api_prefix: str) -> None:
        """Wrap `app`, whose API's routes are mounted under `api_prefix`, `{base_path}/api`."""
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer the request inside its span, then name the span for the route it took and set its status."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope["method"]) if scope["method"] in METHODS else "_OTHER"
        code: int | None = None

        async def watching(message: Message) -> None:
            nonlocal code
            if message["type"] == "http.response.start":
                code = int(message["status"])
            await send(message)

        with tracing.span(method, new_trace=True, server=True) as traced:
            try:
                await self.app(scope, receive, watching)
            finally:
                route = self._route(scope)
                if route is not None:
                    traced.rename(f"{method} {route}")
                traced.set_standard(
                    {"http.request.method": method, "http.route": route, "http.response.status_code": code},
                )
                if code is not None and code >= SERVER_ERROR:
                    traced.fail(str(code))

    def _route(self, scope: Scope) -> str | None:
        """The template of the route the request took, as canopy's code spells it, its mount's prefix included.

        Returns:
            The template, or None when no route matched.
        """
        # The router left the route it matched in the scope; its path is canopy's template, never the client's, but an
        # API route's is under the prefix the API is mounted at, which the scope does not keep.
        route = getattr(scope.get("route"), "path", None)
        if not isinstance(route, str):
            return None
        prefixed = route == self.api_prefix or route.startswith(f"{self.api_prefix}/")
        under_api = str(scope["path"]).startswith(f"{self.api_prefix}/") and not prefixed
        return f"{self.api_prefix}{route}" if under_api else route
