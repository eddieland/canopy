"""What the routes are handed: the server's backend and its sessions, bound per app by `bind`.

The providers here are typed stubs. `create_app` binds each to its own object through the app's dependency overrides,
so a route declares what it uses in its signature, and nothing is kept at module level or on the untyped `app.state`.
A provider still unbound when a request comes in is a wiring bug, and fails that request loudly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request

from canopy.serve.auth import Sessions
from canopy.serve.backend import Backend


def bind(app: FastAPI, backend: Backend, sessions: Sessions) -> None:
    """Hand `app`'s routes `backend` and `sessions`."""
    app.dependency_overrides[provide_backend] = lambda: backend
    app.dependency_overrides[provide_sessions] = lambda: sessions


def provide_backend() -> Backend:
    """The backend the app was bound to (`bind`)."""
    raise NotImplementedError("create_app binds the backend")


def provide_sessions() -> Sessions:
    """The sessions the app was bound to (`bind`)."""
    raise NotImplementedError("create_app binds the sessions")


BackendDep = Annotated[Backend, Depends(provide_backend)]
SessionsDep = Annotated[Sessions, Depends(provide_sessions)]


def signed_in(request: Request, sessions: SessionsDep) -> None:
    """Refuse a request without a session, and a write without its token (`Sessions.require`)."""
    sessions.require(request)
