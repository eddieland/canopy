"""The JSON and SSE API under `{base_path}/api` (DESIGN §6, §19, §22), one router per resource.

Every route but `/session` needs a signed-in session, and a write its token too (auth.py). Writes go through the
functions the CLI's verbs call (`canopy.core.conversation`, and `canopy.core.pause` for the loop's pause), with channel
`web`, so the guards are the same ones; a guard's refusal is a 409 naming it (refs.py). A forget also carries the
ticket's key as the operator typed it. A reload asks the loop to read its config again, as SIGHUP does; it writes
nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from canopy.serve.api import chores, events, loop, overview, reviews, runs, search, session, tickets, ticks, worktrees

if TYPE_CHECKING:
    from canopy.serve.auth import Sessions
    from canopy.serve.backend import Backend
    from canopy.serve.options import ServeOptions


def router(options: ServeOptions, backend: Backend, sessions: Sessions) -> APIRouter:
    """Return the API's routes for a server set up with `options`, reading and writing through `backend`.

    A new resource's router goes on `signed_in`, so it needs a session like the rest.
    """
    api = APIRouter(prefix=f"{options.base_path}/api")
    api.include_router(session.router(sessions))
    signed_in = APIRouter(dependencies=[Depends(sessions.require)])
    for resource in (overview, tickets, runs, ticks, chores, loop, worktrees, events, search, reviews):
        signed_in.include_router(resource.router(backend))
    api.include_router(signed_in)
    return api
