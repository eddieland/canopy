"""What the routes are handed: the server's options, backend, sessions, and the app it serves, bound by `bind`.

The providers here are typed stubs. `create_app` binds each to its own object through the app's dependency overrides,
so a route declares what it uses in its signature, and nothing is kept at module level or on the untyped `app.state`.
A provider still unbound when a request comes in is a wiring bug, and fails that request loudly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request

from canopy.serve.auth import Sessions
from canopy.serve.backend import Backend
from canopy.serve.options import ServeOptions
from canopy.serve.spa import SinglePageApp


def bind(app: FastAPI, options: ServeOptions, backend: Backend, sessions: Sessions, spa: SinglePageApp) -> None:
    """Hand `app`'s routes `options`, `backend`, `sessions`, and `spa`."""
    app.dependency_overrides[provide_options] = lambda: options
    app.dependency_overrides[provide_backend] = lambda: backend
    app.dependency_overrides[provide_sessions] = lambda: sessions
    app.dependency_overrides[provide_spa] = lambda: spa


def provide_options() -> ServeOptions:
    """The options the app was set up with (`bind`)."""
    raise NotImplementedError("create_app binds the options")


def provide_backend() -> Backend:
    """The backend the app was bound to (`bind`)."""
    raise NotImplementedError("create_app binds the backend")


def provide_sessions() -> Sessions:
    """The sessions the app was bound to (`bind`)."""
    raise NotImplementedError("create_app binds the sessions")


def provide_spa() -> SinglePageApp:
    """The single-page app the app serves (`bind`)."""
    raise NotImplementedError("create_app binds the single-page app")


OptionsDep = Annotated[ServeOptions, Depends(provide_options)]
BackendDep = Annotated[Backend, Depends(provide_backend)]
SessionsDep = Annotated[Sessions, Depends(provide_sessions)]
SpaDep = Annotated[SinglePageApp, Depends(provide_spa)]


def signed_in(request: Request, sessions: SessionsDep) -> None:
    """Refuse a request without a session, and a write without its token (`Sessions.require`)."""
    sessions.require(request)
