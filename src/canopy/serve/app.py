"""Builds the server's ASGI app: the guard, the API, and the single-page app, all under one path prefix."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from canopy.serve import api
from canopy.serve.guard import Guard
from canopy.serve.spa import SinglePageApp

if TYPE_CHECKING:
    from canopy.serve.options import ServeOptions


def create_app(options: ServeOptions) -> FastAPI:
    """Return the app for a server set up with `options`."""
    base = options.base_path
    # No docs pages: they load scripts from a CDN. The schema stays, for `python -m canopy.serve openapi`.
    app = FastAPI(title="canopy", docs_url=None, redoc_url=None, openapi_url=f"{base}/api/openapi.json")
    app.include_router(api.router(options))
    if base:

        @app.get(base, include_in_schema=False)
        def to_base() -> RedirectResponse:
            return RedirectResponse(f"{base}/")

    # Last, so every API route, including an unknown one, is matched before it.
    spa = SinglePageApp(options.ui_dir, base_path=base)
    app.add_route(f"{base}/{{path:path}}", spa.respond, methods=["GET", "HEAD"], include_in_schema=False)
    app.add_middleware(Guard, api_prefix=f"{base}/api")
    return app
