"""The JSON and SSE API (DESIGN §6, §19, §22), one router per resource, mounted under `{base_path}/api`.

Every route but `/session` needs a signed-in session: the cookie `POST /session` sets with the listener secret. A write
(any method but GET and HEAD) also carries the session's token, from `GET /session`, as `X-Canopy-Token`, and an
`Origin` naming this server. Writes go through the functions the CLI's verbs call, with channel `web`, so the guards
are the same ones, or, for what no command would do (marking reviews seen), a core function of their own; a guard's
refusal is a 409 naming it, and a write that waited out another writer's hold on the journal a 503 saying so. A forget
also carries the ticket's key as the operator typed it. A reload asks the loop to read its config again, as SIGHUP
does; it writes nothing.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from canopy.serve.api import (
    chores,
    deps,
    docs,
    drafts,
    events,
    loop,
    memory,
    overview,
    plans,
    pull_requests,
    refs,
    reviews,
    runs,
    search,
    seen,
    session,
    tickets,
    ticks,
    worktrees,
)

# The docstring above is the schema's description. A route is handed the backend and the sessions it uses by deps.py;
# what the routes share, the errors they answer among it, is in refs.py.

# A new resource's module goes here, so it needs a session like the rest and its tag is described; its router has
# that tag, and each route a summary, a docstring, and every error it answers (test_serve.py checks).
_RESOURCES = (
    overview,
    tickets,
    plans,
    runs,
    ticks,
    chores,
    loop,
    worktrees,
    events,
    search,
    reviews,
    seen,
    pull_requests,
    drafts,
    memory,
)

# Each resource's tag, described by its module's docstring, in the order the schema lists them.
TAGS: list[dict[str, Any]] = [{"name": m.TAG, "description": m.__doc__} for m in (session, *_RESOURCES)]

_signed_in = APIRouter(dependencies=[Depends(deps.signed_in)], responses=refs.SIGNED_IN)
for _resource in _RESOURCES:
    # The stream only reads, which never waits on the write lock, and could not answer a 503 once its 200 had begun.
    _signed_in.include_router(_resource.router, responses=None if _resource is events else refs.BUSY)
# The schema and its Swagger UI page, which are not in the schema.
_signed_in.include_router(docs.router)

router = APIRouter(responses=refs.GUARDED)
router.include_router(session.router)
router.include_router(_signed_in)
