"""What the routes share: the channel their writes go through, the refs a path names, and the errors they answer.

Every error a route can answer is in its `responses`, with the model of its body, so the schema names it: a refusal is
a 409, anything else that is not a validation error an `ErrorResponse`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import HTTPException, Path, Request
from fastapi.responses import JSONResponse

from canopy.core import conversation, db
from canopy.infra import logs
from canopy.serve.guard import MAX_BODY_BYTES
from canopy.serve.schema import ErrorResponse, RefusalResponse

if TYPE_CHECKING:
    from canopy.core.conversation import Ref

type Responses = dict[int | str, dict[str, Any]]

WEB = "web"
_log = logs.for_tick(None)
# The largest id SQLite stores; a larger one in a path is a 422, not an overflow.
_MAX_ID = 2**63 - 1

TicketKey = Annotated[str, Path(description="The ticket's key, as the tracker names it: `PROJ-1`.")]
ChoreName = Annotated[str, Path(description="The chore's name, as `chore:NAME` names it.")]
RunId = Annotated[int, Path(ge=1, le=_MAX_ID, description="The run's id, as `run:ID` names it.")]
ChoreRunId = Annotated[int, Path(ge=1, le=_MAX_ID, description="The chore run's id.")]
ReviewId = Annotated[int, Path(ge=1, le=_MAX_ID, description="The review run's id.")]
TickId = Annotated[int, Path(ge=1, le=_MAX_ID, description="The tick's id.")]
PlanId = Annotated[int, Path(ge=1, le=_MAX_ID, description="The plan's id, as `plan:ID` names it.")]
ThreadId = Annotated[int, Path(ge=1, le=_MAX_ID, description="The comment thread's id.")]
MemoryId = Annotated[int, Path(ge=1, le=_MAX_ID, description="The memory's id, as `memory:ID` names it.")]

# Every API route's: the guard answers 403, 411, or 413 before any route does (guard.py), and a session's check on a
# write answers 403.
GUARDED: Responses = {
    403: {
        "model": ErrorResponse,
        "description": "Refused before the route ran: a Host or Origin header naming another host, or a write "
        "without the session's token or an Origin naming this server.",
    },
    411: {
        "model": ErrorResponse,
        "description": "Refused before the route ran: a chunked body, with no Content-Length.",
    },
    413: {
        "model": ErrorResponse,
        "description": f"Refused before the route ran: a body over {MAX_BODY_BYTES // 1024} KiB.",
    },
}
# Every route's but the session's own (deps.signed_in).
SIGNED_IN: Responses = {
    401: {"model": ErrorResponse, "description": "No valid session: sign in with the listener secret."},
}
# Every route's but the stream's that reads or writes the journal: another connection held its write lock past
# db.BUSY_SECONDS.
BUSY: Responses = {
    503: {
        "model": ErrorResponse,
        "description": "The journal is busy: another writer, such as the loop, held it past the busy timeout. Try "
        "again.",
    },
}
# A route's whose guards can refuse: a write, or a path naming a ticket or a chore by a reference that is not one.
REFUSED: Responses = {
    409: {"model": RefusalResponse, "description": "A guard refused it: `detail` names the guard and its reason."},
}


def not_found(what: str) -> Responses:
    """The 404 a route answers when the journal has no `what` its path names.

    Returns:
        The route's `responses` entry for it.
    """
    return {404: {"model": ErrorResponse, "description": f"No such {what}."}}


class RefusedError(HTTPException):
    """A guard's refusal as the 409 the UI shows, its detail the guard and its reason."""

    def __init__(self, r: conversation.Refused) -> None:
        """Carry refusal `r`."""
        super().__init__(status_code=409, detail={"guard": r.guard, "reason": r.reason})


def journal_busy(request: Request, exc: Exception) -> JSONResponse:
    """Answer a write that waited out the journal's busy timeout as the 503 `BUSY` describes, not a bare 500.

    Returns:
        The 503, its detail saying why.

    Raises:
        Exception: `exc` is anything but SQLite's busy timeout, which stays the 500 it was.
    """
    # The app hands this sqlite3.OperationalError alone. SQLite names the error it raises, one raised in Python has no
    # name, and a busy timeout is SQLITE_BUSY or an extended code of it.
    if not getattr(exc, "sqlite_errorname", "").startswith("SQLITE_BUSY"):
        raise exc
    _log.warning("journal busy: %s %s waited %gs for the write lock", request.method, request.url.path, db.BUSY_SECONDS)
    detail = f"the journal is busy: another writer held it for over {db.BUSY_SECONDS:g}s; try again"
    return JSONResponse({"detail": detail}, status_code=503)


def ticket_ref(key: str, verb: str) -> Ref:
    """The ticket `key` names, refused as the CLI refuses it: `bad_ref`, or `unsupported` for another kind.

    Returns:
        The ticket's reference.

    Raises:
        RefusedError: `key` is not a reference, `verb` does not apply to it, or it is not a ticket.
    """
    try:
        ref = conversation.parse_ref(key)
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise RefusedError(r) from None
    if ref.kind != conversation.TICKET:
        raise RefusedError(conversation.Refused("unsupported", f"{ref} is not a ticket"))
    return ref


def chore_ref(name: str, verb: str) -> Ref:
    """The chore `name` names, refused as `canopy reply chore:NAME` refuses it: `bad_ref` for a name no chore has.

    Returns:
        The chore's reference.

    Raises:
        RefusedError: `name` is not a chore name, or `verb` does not apply to a chore.
    """
    try:
        ref = conversation.parse_ref(f"{conversation.CHORE}:{name}")
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise RefusedError(r) from None
    return ref
