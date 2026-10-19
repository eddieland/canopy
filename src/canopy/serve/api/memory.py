"""Agent memory (DESIGN §28): every tier's memory, a ticket's notes, a run's, and promote, reject, renew, and forget.

The verbs are `canopy memory`'s, through `canopy.core.memory_manage`, so with its refusals. Purging many at once stays
the CLI's, in the operator's shell.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from canopy.core import conversation, db, memory_manage
from canopy.infra import logs
from canopy.serve import memory_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, MemoryId, RefusedError, RunId, TicketKey, not_found, ticket_ref
from canopy.serve.schema import (
    MemoryForgetRequest,
    MemoryForgotten,
    MemoryOverview,
    MemoryPromoted,
    MemoryRejected,
    MemoryRenewed,
    PromoteRequest,
    RunMemory,
    TicketMemory,
)

TAG = "memory"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/memory", operation_id="getMemory", summary="Get agent memory")
def overview(
    backend: BackendDep,
    *,
    history: Annotated[
        bool, Query(description="Also send the latest proposals and lessons no longer pending or in force.")
    ] = False,
) -> MemoryOverview:
    """Each tier's mode, every ticket's notes in force, the proposals waiting, and the lessons and what they serve.

    With `history`, the latest proposals and lessons no longer pending or in force too, as `past_proposals` and
    `past_lessons`.
    """
    with backend.open() as ctx:
        return memory_views.overview(ctx, history=history)


@router.get(
    "/tickets/{key}/memory",
    operation_id="getTicketMemory",
    summary="Get a ticket's notes",
    responses={**REFUSED, **not_found("ticket")},
)
def ticket_memory(key: TicketKey, backend: BackendDep) -> TicketMemory:
    """Every note the ticket's runs wrote, and what its next run would be served.

    A key that is not a ticket's is refused `bad_ref` or `unsupported`; one canopy has no record of is a 404.
    """
    ref = ticket_ref(key, "show")
    with backend.open() as ctx:
        found = memory_views.ticket_memory(ctx, ref.id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no record of {ref}")
    return found


@router.get(
    "/runs/{run_id}/memory", operation_id="getRunMemory", summary="Get a run's memory", responses=not_found("run")
)
def run_memory(run_id: RunId, backend: BackendDep) -> RunMemory:
    """The modes the run's prompt was rendered under, what it wrote and read of memory, and what it had refused."""
    with backend.open() as ctx:
        found = memory_views.run_memory(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return found


@router.post(
    "/memory/{memory_id}/promote",
    operation_id="promoteMemory",
    summary="Promote a memory to a lesson",
    responses=REFUSED,
)
def promote(memory_id: MemoryId, body: PromoteRequest, backend: BackendDep) -> MemoryPromoted:
    """`canopy memory promote ID [--text TEXT] [--repo NAME]`: a pending proposal, or a ticket's note, as a lesson.

    It supersedes the lesson in force under the same key. Refused as the CLI refuses it: `off` while proposals are off,
    `unknown`, `not_pending`, `forgotten`, `unknown_repo`, and `bad_text`.
    """
    with backend.open() as ctx:
        try:
            repos = [r.name for r in ctx.ws.repos]
            promoted = memory_manage.promote(
                ctx.conn, ctx.config, memory_id, text=body.text, repo=body.repo, repos=repos
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
        source, lesson = promoted.source, promoted.lesson
        _log.info(
            "lesson promoted",
            extra={"memory": memory_id, "scope": source.scope, "lesson": lesson.id, "channel": WEB},
        )
        return MemoryPromoted(
            lesson=memory_views.entry(ctx, lesson),
            source=memory_views.entry(ctx, source),
            superseded=promoted.superseded,
            served=promoted.served,
            private=promoted.private,
        )


@router.post("/memory/{memory_id}/reject", operation_id="rejectMemory", summary="Reject a proposal", responses=REFUSED)
def reject(memory_id: MemoryId, backend: BackendDep) -> MemoryRejected:
    """`canopy memory reject ID`: the proposal ends, and no lesson is made of it.

    Refused `off`, `unknown`, or `not_pending`, as the CLI refuses it.
    """
    with backend.open() as ctx:
        try:
            memory_manage.reject(ctx.conn, ctx.config, memory_id)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("proposal rejected", extra={"proposal": memory_id, "channel": WEB})
    return MemoryRejected(id=memory_id)


@router.post("/memory/{memory_id}/renew", operation_id="renewMemory", summary="Renew a lesson", responses=REFUSED)
def renew(memory_id: MemoryId, backend: BackendDep) -> MemoryRenewed:
    """`canopy memory renew ID`: the lesson comes up for review again later, and a run's report it is wrong is cleared.

    Refused `off`, or `unknown` for an id no lesson in force has, as the CLI refuses it.
    """
    with backend.open() as ctx:
        try:
            due = memory_manage.renew(ctx.conn, ctx.config, memory_id)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("lesson renewed", extra={"lesson": memory_id, "channel": WEB})
    return MemoryRenewed(id=memory_id, review_at=db.parse_time(due))


# Forgetting cannot be undone, so the request carries the memory's ref as the operator typed it, and a mismatch is
# refused before anything is read, as a ticket's forget is (DESIGN §22).
@router.post("/memory/{memory_id}/forget", operation_id="forgetMemory", summary="Forget a memory", responses=REFUSED)
def forget(memory_id: MemoryId, body: MemoryForgetRequest, backend: BackendDep) -> MemoryForgotten:
    """`canopy memory forget ID`: delete a note's, a proposal's, or a lesson's text, leaving its row. A lesson retires.

    Cannot be undone: `confirm` must be the memory's ref, `memory:ID`, or it is refused `not_confirmed` before anything
    is read. Else refused `unknown`, or `forgotten` for one whose text is already gone, as the CLI refuses it.
    """
    ref = f"memory:{memory_id}"
    if body.confirm != ref:
        raise RefusedError(conversation.Refused("not_confirmed", f"type {ref} to confirm forgetting its text"))
    with backend.open() as ctx:
        try:
            found, scrubbed = memory_manage.forget(ctx.conn, memory_id)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("memory forgotten", extra={"memory": memory_id, "scope": found.scope, "channel": WEB})
    return MemoryForgotten(id=memory_id, scope=found.scope.value, key=found.key, checkpointed=scrubbed.checkpointed)
