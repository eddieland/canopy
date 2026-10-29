"""Builds the server's ASGI app: the guard, the API, and the single-page app, all under one path prefix."""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from canopy.serve import api, host, mock
from canopy.serve.api import deps, refs
from canopy.serve.audit import Audit
from canopy.serve.guard import Guard
from canopy.serve.spa import SinglePageApp
from canopy.serve.sse import QuietLeaving

if TYPE_CHECKING:
    from canopy.serve.auth import Sessions
    from canopy.serve.backend import Backend
    from canopy.serve.options import ServeOptions


def create_app(options: ServeOptions, backend: Backend, sessions: Sessions) -> FastAPI:
    """Return the app for a server set up with `options`, over `backend`'s journal, signing in with `sessions`."""
    base = options.base_path

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Mock data changes now and then, so the stream has something to show (mock/).
        tasks = [asyncio.create_task(mock.changes(backend, options.mock_event_seconds))] if backend.mock else []
        # The system resources page's graphs: the machine read every few seconds from now, into memory (host.py).
        if backend.sampling:
            tasks.append(asyncio.create_task(host.sampling(backend.read_host, backend.samples)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    # FastAPI's own schema and docs routes are off: api/docs.py serves both behind the session, its page with no CDN.
    # `python -m canopy.serve openapi` prints the schema without a server.
    app = FastAPI(
        title="canopy",
        summary="The web UI's API: what canopy's journal holds, and the operator's verbs on it.",
        description=api.__doc__,
        version=version("canopy"),
        openapi_tags=api.TAGS,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.include_router(api.router, prefix=f"{base}/api")
    app.add_exception_handler(sqlite3.OperationalError, refs.journal_busy)
    spa = SinglePageApp(options.ui_dir, base_path=base)
    deps.bind(app, options, backend, sessions, spa)
    if base:

        @app.get(base, include_in_schema=False)
        def to_base() -> RedirectResponse:
            return RedirectResponse(f"{base}/")

    # Where FastAPI puts its docs page by default.
    @app.get(f"{base}/docs", include_in_schema=False)
    def to_docs() -> RedirectResponse:
        return RedirectResponse(f"{base}/api/docs")

    # Last, so every API route, including an unknown one, is matched before it.
    app.add_route(f"{base}/{{path:path}}", spa.respond, methods=["GET", "HEAD"], include_in_schema=False)
    app.add_middleware(QuietLeaving)
    # Inside the guard: what it refuses is never recorded.
    app.add_middleware(Audit, backend=backend)
    app.add_middleware(Guard, api_prefix=f"{base}/api", hosts=options.hosts)
    return app
