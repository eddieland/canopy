"""Review replies (DESIGN §29): a PR's threads on its diff, and editing, dropping, and sending its drafts.

The verbs are `canopy draft`'s, through `canopy.core.drafts_manage`, so with its refusals. A send posts the text the
page showed, named by its hash, as the operator's own words: the drafts for one PR as one comment review. A PR is named
by its URL, an opaque string with slashes in it, so it is a query parameter, never a path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from canopy.core import contract, conversation, drafts_manage
from canopy.infra import logs
from canopy.serve import threads
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, RunId, not_found
from canopy.serve.schema import (
    Draft,
    DraftDropRequest,
    DraftEditRequest,
    DraftSendRequest,
    DraftsSent,
    ErrorResponse,
    PullRequestThreads,
)

TAG = "review replies"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)

PrUrl = Annotated[
    str,
    Query(
        min_length=1,
        max_length=conversation.MAX_PR_URL,
        description=f"The PR's plain https:// URL, at most {conversation.MAX_PR_URL} characters.",
    ),
]
DraftNumber = Annotated[int, Path(ge=1, le=30, description="The draft's number in its run's drafts, from 1.")]


@router.get(
    "/pull-request/threads",
    operation_id="getPullRequestThreads",
    summary="Get a PR's threads and drafts",
    responses={
        **not_found("PR"),
        422: {"model": ErrorResponse, "description": "Not a plain https:// URL of at most 300 characters."},
    },
)
def pull_request_threads(url: PrUrl, backend: BackendDep) -> PullRequestThreads:
    """The PR's review threads, as canopy's reader last read them, on the diff the latest run kept, with every draft.

    Raises:
        HTTPException: 422 when `url` is not a plain https:// URL, 404 when the journal has no read and no draft of it.
    """
    if not contract.plain_url(url, conversation.MAX_PR_URL):
        raise HTTPException(status_code=422, detail="url must be a PR's plain https:// URL")
    with backend.open() as ctx:
        found = threads.threads(ctx, url)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has read no threads of {url} and holds no draft for it")
    return found


@router.post(
    "/runs/{run_id}/drafts/{number}/edit",
    operation_id="editDraft",
    summary="Edit a draft",
    responses=REFUSED,
)
def edit(run_id: RunId, number: DraftNumber, body: DraftEditRequest, backend: BackendDep) -> Draft:
    """`canopy draft edit run:ID N --text TEXT`: the operator's text, as a new version beside the run's own.

    Refused as the CLI refuses it: `unknown`, a status that takes no edit (`sent`, `superseded`, ...), and `bad_text`.
    """
    with backend.open() as ctx:
        try:
            drafts_manage.edit(ctx.conn, run_id, number, body.text, channel=WEB)
            found = drafts_manage.find(ctx.conn, run_id, number)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info("draft edited", extra={"run_id": run_id, "number": number, "channel": WEB})
        return threads.draft(ctx.conn, found)


@router.post(
    "/runs/{run_id}/drafts/{number}/drop",
    operation_id="dropDraft",
    summary="Drop a draft",
    responses=REFUSED,
)
def drop(run_id: RunId, number: DraftNumber, body: DraftDropRequest, backend: BackendDep) -> Draft:
    """`canopy draft drop run:ID N [--undo]`: nobody sends it, or with `undo` it waits again.

    Refused as the CLI refuses it: `unknown`, and a status that cannot be dropped or taken back.
    """
    with backend.open() as ctx:
        try:
            [found] = drafts_manage.drop(ctx.conn, run_id, [number], undo=body.undo)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        backend.write_attention(ctx)
        _log.info("draft dropped", extra={"run_id": run_id, "number": number, "undo": body.undo, "channel": WEB})
        return threads.draft(ctx.conn, found)


@router.post("/drafts/send", operation_id="sendDrafts", summary="Send drafts", responses=REFUSED)
def send(body: DraftSendRequest, backend: BackendDep) -> DraftsSent:
    """`canopy draft send`: the drafts as the operator's own words, each exactly as the page showed it.

    One PR's drafts go as one comment review, which approves nothing and resolves no thread. Every check runs before
    anything posts, and any refusal posts nothing: `unchecked`, `superseded`, `dropped`, `refused`, `unconfirmed`,
    `stale` for a text that changed since the page showed it, `thread_changed` for a comment that arrived on its thread,
    and `no_post`.
    """
    wanted = [drafts_manage.Wanted(d.run, d.number, d.hash) for d in body.drafts]
    with backend.open() as ctx:
        try:
            outcome = drafts_manage.send(ctx.conn, ctx.config, ctx.runner, wanted, channel=WEB, log=_log)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        backend.write_attention(ctx)
        _log.info(
            "drafts sent",
            extra={"posted": len(outcome.posted), "failed": len(outcome.failed), "channel": WEB},
        )
        return threads.sent(ctx.conn, outcome)
