"""The operator's desk on a ticket (DESIGN §18): open it, as `canopy desk KEY` does, and close it, as `--close` does.

Each changes the pools, so it waits for a running tick to end and holds the dispatch lock while it works, as the CLI
does, and is refused inside canopy's own ticks and runs: a desk is the operator's.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from fastapi import APIRouter

from canopy.core import conversation, db
from canopy.infra import lock, logs
from canopy.runs import checkouts
from canopy.serve import desk_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, TicketKey, ticket_ref
from canopy.serve.schema.desk import DeskClosed, DeskCloseRequest, DeskOpened, DeskRequest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from canopy.core.context import Context

TAG = "desks"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.post("/tickets/{key}/desk", operation_id="openDesk", summary="Open a ticket's desk", responses=REFUSED)
def open_desk(key: TicketKey, body: DeskRequest, backend: BackendDep) -> DeskOpened:
    """`canopy desk KEY [--repo NAME]...`: check the ticket's branch out for the operator, a slot per repository.

    A desk already open is left as it is, `already`. Refused `desk_failed` when the ticket has no branch yet, or not in
    a repository named, or a pool or git could not give a slot the branch; what it leased is returned first.
    """
    ref = ticket_ref(key, "desk")
    _check_operator()
    with backend.open() as ctx, _between_ticks(ctx):
        missing = [name for name in body.repos if ctx.workspace.repo(name) is None]
        if missing:
            raise RefusedError(conversation.Refused("unknown_repo", f"the map lists no repository {missing[0]}"))
        already = backend.find_desk(ctx, ref.id)
        if already is None:
            try:
                desk = backend.open_desk(ctx, ref.id, body.repos)
            except checkouts.CheckoutError as e:
                raise RefusedError(conversation.Refused("desk_failed", str(e))) from None
        else:
            desk = already
        running = db.running_run_of(ctx.conn, ref.id)
        root = ctx.workspace.root
    _log.info(
        "desk opened",
        extra={"ticket": ref.id, "already": already is not None, "repos": list(desk.slots), "channel": WEB},
    )
    return DeskOpened(
        already=already is not None,
        desk=desk_views.open_desk(desk, root),
        running_run=running.id if running is not None else None,
        running_kind=str(running.kind) if running is not None else None,
    )


@router.post(
    "/tickets/{key}/desk/close",
    operation_id="closeDesk",
    summary="Close a ticket's desk",
    responses=REFUSED,
)
def close_desk(key: TicketKey, body: DeskCloseRequest, backend: BackendDep) -> DeskClosed:
    """`canopy desk KEY --close [--discard]`: return the desk's slots and remove it, its local branch with it.

    Refused `unpushed` while a slot holds uncommitted changes or commits origin lacks, unless `discard`, which must
    carry the ticket's key as the operator typed it or is refused `not_confirmed`; `desk_failed` when a pool could not
    return a slot, the rest returned. A ticket with no desk open returns nothing.
    """
    ref = ticket_ref(key, "desk")
    if body.discard and body.confirm != ref.id:
        raise RefusedError(conversation.Refused("not_confirmed", f"type {ref} to confirm losing its desk's work"))
    _check_operator()
    with backend.open() as ctx, _between_ticks(ctx):
        desk = backend.find_desk(ctx, ref.id)
        if desk is None:
            return DeskClosed(returned=[])
        try:
            unsafe = backend.close_desk(ctx, desk, body.discard)
        except checkouts.CheckoutError as e:
            raise RefusedError(conversation.Refused("desk_failed", str(e))) from None
    if unsafe:
        lost = "; ".join(str(u) for u in unsafe)
        raise RefusedError(
            conversation.Refused(
                "unpushed",
                f"{ref}'s desk has work origin lacks: {lost}. Commit and push it, or discard it; nothing was returned.",
            ),
        )
    _log.info("desk closed", extra={"ticket": ref.id, "discard": body.discard, "channel": WEB})
    return DeskClosed(returned=list(desk.slots))


def _check_operator() -> None:
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise RefusedError(r) from None


@contextlib.contextmanager
def _between_ticks(ctx: Context) -> Iterator[None]:
    # As the CLI's `between_ticks` with `dispatches`: a tick and a review or task leasing a slot both wait.
    with lock.hold(ctx.lock_path, wait=True), lock.hold(ctx.dispatch_lock_path, wait=True):
        yield
