"""Agent memory (DESIGN §28): every tier's memory, a ticket's notes, a run's, a memory's versions, and the verbs.

The verbs, promote, reject, renew, edit, and forget, are `canopy memory`'s, through `canopy.core.memory_manage`, so
with its refusals. Purging many at once stays the CLI's, in the operator's shell.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from canopy.core import conversation, db, memory, memory_manage
from canopy.infra import logs
from canopy.serve import memory_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, MemoryId, RefusedError, RunId, TicketKey, not_found, ticket_ref
from canopy.serve.schema import (
    LessonEditRequest,
    MemoryEdited,
    MemoryForgetRequest,
    MemoryForgotten,
    MemoryFound,
    MemoryHistory,
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


@router.get("/memory/search", operation_id="searchMemory", summary="Search agent memory")
def search(
    q: Annotated[str, Query(max_length=200, description="The words to find: any of them, or with every, all.")],
    backend: BackendDep,
    *,
    notes: Annotated[bool, Query(description="Only ticket notes in force, the 50 best of them.")] = False,
    every: Annotated[bool, Query(description="Only what holds every word, each a whole word, endings aside.")] = False,
) -> MemoryFound:
    """`canopy memory search Q` in the operator's shell: every memory that keeps its text, best match first, at most 50.

    It reads only, as the overview does.
    """
    with backend.open() as ctx:
        return memory_views.found(ctx, q, notes=notes, every=every)


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


@router.get(
    "/memory/{memory_id}/history",
    operation_id="getMemoryHistory",
    summary="Get a memory's versions",
    responses=not_found("memory"),
)
def history(memory_id: MemoryId, backend: BackendDep) -> MemoryHistory:
    """`canopy memory history ID`: every version of a lesson or a note, newest first, those out of force included."""
    with backend.open() as ctx:
        found = memory_views.history(ctx, memory_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no memory {memory_id}")
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


@router.post("/memory/{memory_id}/edit", operation_id="editMemory", summary="Edit a lesson", responses=REFUSED)
def edit(memory_id: MemoryId, body: LessonEditRequest, backend: BackendDep) -> MemoryEdited:
    """`canopy memory edit ID [--text TEXT] [--repo NAME | --every-repo]`: a new version of a lesson in force.

    The old version stays, superseded, as the lesson's history. Refused as the CLI refuses it: `off` while proposals
    are off, `unknown`, `unknown_repo`, `bad_text`, and `unchanged` for an edit that changes nothing; `bad_request`
    for `repo` with `every_repo`.
    """
    if body.repo is not None and body.every_repo:
        raise RefusedError(conversation.Refused("bad_request", "name one repository or every repository, not both"))
    with backend.open() as ctx:
        try:
            repos = [r.name for r in ctx.ws.repos]
            edited = memory_manage.edit(
                ctx.conn,
                ctx.config,
                memory_id,
                text=body.text,
                repo=body.repo,
                every_repo=body.every_repo,
                repos=repos,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
        lesson = edited.lesson
        _log.info("lesson edited", extra={"lesson": memory_id, "into": lesson.id, "channel": WEB})
        replaced = memory.get(ctx.conn, memory_id) or edited.replaced
        return MemoryEdited(
            lesson=memory_views.entry(ctx, lesson),
            replaced=memory_views.entry(ctx, replaced),
            served=edited.served,
        )


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
