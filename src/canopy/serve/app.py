"""Builds the server's ASGI app: the guard, the API, and the single-page app, all under one path prefix."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from canopy.serve import api, mock
from canopy.serve.guard import Guard
from canopy.serve.spa import SinglePageApp

if TYPE_CHECKING:
    from canopy.serve.auth import Sessions
    from canopy.serve.backend import Backend
    from canopy.serve.options import ServeOptions


def create_app(options: ServeOptions, backend: Backend, sessions: Sessions) -> FastAPI:
    """Return the app for a server set up with `options`, over `backend`'s journal, signing in with `sessions`."""
    base = options.base_path

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Mock data changes now and then, so the stream has something to show (mock.py).
        task = asyncio.create_task(mock.changes(backend, options.mock_event_seconds)) if backend.mock else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    # No docs pages: they load scripts from a CDN. The schema is served only with mock data; `python -m canopy.serve
    # openapi` prints it without a server.
    app = FastAPI(
        title="canopy",
        docs_url=None,
        redoc_url=None,
        openapi_url=f"{base}/api/openapi.json" if backend.mock else None,
        lifespan=lifespan,
    )
    app.include_router(api.router(options, backend, sessions))
    if base:

        @app.get(base, include_in_schema=False)
        def to_base() -> RedirectResponse:
            return RedirectResponse(f"{base}/")

    # Last, so every API route, including an unknown one, is matched before it.
    spa = SinglePageApp(options.ui_dir, base_path=base)
    app.add_route(f"{base}/{{path:path}}", spa.respond, methods=["GET", "HEAD"], include_in_schema=False)
    app.add_middleware(Guard, api_prefix=f"{base}/api", hosts=options.hosts)
    return app
