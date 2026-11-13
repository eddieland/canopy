"""Every session the agent runtime keeps (DESIGN §13), listed and found by its title, as `canopy sessions` lists them.

Reads only, and only what the loop's read of the runtime's record kept while the private `sessions.search` is
`titles`: at `off`, the default, it serves no session. A title is untrusted text.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.exceptions import RequestValidationError

from canopy.core import session_list
from canopy.serve import search, session_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.sessions import SessionList, SessionsWhose

TAG = "sessions"
#: The longest directory a list is narrowed to: Linux's longest path.
MAX_DIRECTORY = 4096
router = APIRouter(tags=[TAG])


@router.get("/sessions", operation_id="getSessions", summary="List the runtime's sessions")
def sessions(
    backend: BackendDep,
    *,
    whose: Annotated[
        SessionsWhose,
        Query(description="Whose sessions: those outside canopy, the operator's own, or canopy's runs'."),
    ] = "outside",
    q: Annotated[
        str | None,
        Query(
            min_length=search.MIN_QUERY,
            max_length=search.MAX_QUERY,
            description="The words every title holds, as the search of the journal takes them; none lists every one.",
        ),
    ] = None,
    archived: Annotated[bool, Query(description="List the sessions the runtime archived too.")] = False,
    directory: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=MAX_DIRECTORY,
            description="List only the sessions that ran in this directory, exactly, not one below it.",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=session_list.MAX_LISTED, description="How many sessions to list at most, newest first."),
    ] = session_list.LISTED,
) -> SessionList:
    """The sessions `whose` names, newest first, a subagent's under the one it ran for, as `canopy sessions` lists them.

    With `q`, the newest whose title holds every word, subagents' among them. With `directory`, only those that ran in
    it; one `sessions.exclude` names lists none. Each outside canopy carries the command that reopens it in the runtime,
    and each of canopy's the run that made it. While `sessions.search` is `off` it lists none. A query of too many words
    is a 422, as the search's is.
    """
    with backend.open() as ctx:
        try:
            return session_views.listed(
                ctx,
                whose=whose,
                query=q,
                archived=archived,
                directory=directory,
                limit=limit,
            )
        except search.BadQueryError as e:
            error = {"type": "value_error", "loc": ("query", "q"), "msg": str(e), "input": q}
            raise RequestValidationError([error]) from None
