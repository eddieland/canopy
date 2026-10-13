"""The JSON and SSE API (DESIGN §6, §19, §22), one router per resource, mounted under `{base_path}/api`.

Every route but `/session` needs a signed-in session, and a write its token too (auth.py). Writes go through the
functions the CLI's verbs call (`canopy.core.conversation`, and `canopy.core.pause` for the loop's pause), with channel
`web`, so the guards are the same ones; a guard's refusal is a 409 naming it (refs.py). A forget also carries the
ticket's key as the operator typed it. A reload asks the loop to read its config again, as SIGHUP does; it writes
nothing. A route is handed the backend and the sessions it uses by deps.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from canopy.serve.api import (
    chores,
    deps,
    events,
    loop,
    overview,
    reviews,
    runs,
    search,
    session,
    tickets,
    ticks,
    worktrees,
)

# A new resource's router goes on `_signed_in`, so it needs a session like the rest.
_signed_in = APIRouter(dependencies=[Depends(deps.signed_in)])
for _resource in (overview, tickets, runs, ticks, chores, loop, worktrees, events, search, reviews):
    _signed_in.include_router(_resource.router)

router = APIRouter()
router.include_router(session.router)
router.include_router(_signed_in)
