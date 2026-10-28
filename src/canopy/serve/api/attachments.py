"""Files the operator attaches to a ticket or a task (DESIGN §22): what `canopy attach` and `canopy detach` do.

An upload is the file's bytes as the request's body, one file a request, which the guard bounds (guard.py) above the
largest attachment `policy` allows. Each write goes through `canopy.core.attachments`, with channel `web`, so its
guards are the CLI's: only UTF-8 text, within the limits, on a ticket canopy knows or a task not stopped (TRUST_MODEL
T1, T8). What a ticket's or a task's page shows of them comes with the page's own read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Final

from fastapi import APIRouter, Path, Request
from starlette.concurrency import run_in_threadpool

from canopy.core import attachments, conversation, plans
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError, TaskId, TicketKey
from canopy.serve.schema import Attached, Detached

if TYPE_CHECKING:
    from canopy.serve.backend import Backend

TAG: Final = "attachments"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)

AttachmentName = Annotated[
    str,
    Path(max_length=100, description="What its runs see it as: a plain file name, such as `design.md`."),
]
# The body is the file's bytes, not JSON: a text file escaped as a JSON string could outgrow the guard's bound.
_BODY: Final[dict[str, Any]] = {
    "requestBody": {
        "required": True,
        "description": "The file's text, UTF-8, as its bytes.",
        "content": {"text/plain": {"schema": {"type": "string"}}},
    },
}


@router.put(
    "/tickets/{key}/attachments/{name}",
    operation_id="attachTicket",
    summary="Attach a file to a ticket",
    responses=REFUSED,
    openapi_extra=_BODY,
)
async def attach_ticket(key: TicketKey, name: AttachmentName, request: Request, backend: BackendDep) -> Attached:
    """`canopy attach KEY FILE --name NAME`: keep the body's text as NAME, for the ticket's later runs to read.

    Refused as the CLI is: `unknown` for a ticket canopy has no record of, `bad_name`, `not_text`, `empty`,
    `too_large`, `too_many`, and `taken` for a name the ticket's attachments have.
    """
    ref = conversation.Ref(conversation.TICKET, key)
    return await run_in_threadpool(_attach, backend, ref, name, await request.body())


@router.delete(
    "/tickets/{key}/attachments/{name}",
    operation_id="detachTicket",
    summary="Remove a ticket's attachment",
    responses=REFUSED,
)
def detach_ticket(key: TicketKey, name: AttachmentName, backend: BackendDep) -> Detached:
    """`canopy detach KEY NAME`: its file is deleted, and later runs no longer get it. Refused `unknown` for none."""
    return _detach(backend, conversation.Ref(conversation.TICKET, key), name)


@router.put(
    "/tasks/{task_id}/attachments/{name}",
    operation_id="attachTask",
    summary="Attach a file to a task",
    responses=REFUSED,
    openapi_extra=_BODY,
)
async def attach_task(task_id: TaskId, name: AttachmentName, request: Request, backend: BackendDep) -> Attached:
    """`canopy attach task:N FILE --name NAME`: keep the body's text as NAME, for the task's later runs to read.

    Refused as the CLI is: `unknown` for a task canopy has no record of, `stopped` for one the operator stopped,
    `bad_name`, `not_text`, `empty`, `too_large`, `too_many`, and `taken`.
    """
    ref = conversation.Ref(conversation.TASK, str(task_id))
    return await run_in_threadpool(_attach, backend, ref, name, await request.body())


@router.delete(
    "/tasks/{task_id}/attachments/{name}",
    operation_id="detachTask",
    summary="Remove a task's attachment",
    responses=REFUSED,
)
def detach_task(task_id: TaskId, name: AttachmentName, backend: BackendDep) -> Detached:
    """`canopy detach task:N NAME`: its file is deleted, and later runs no longer get it. Refused `unknown` for none."""
    return _detach(backend, conversation.Ref(conversation.TASK, str(task_id)), name)


def _attach(backend: Backend, ref: conversation.Ref, name: str, data: bytes) -> Attached:
    """Attach `data` to `ref` as `name`, through the function `canopy attach` calls.

    Returns:
        The attachment.

    Raises:
        RefusedError: a guard refused it, or its file could not be kept (`not_kept`).
    """
    with backend.open() as ctx:
        limits = attachments.Limits.from_policy(ctx.config.policy)
        try:
            found = attachments.attach(ctx.conn, ctx.state_dir, ref, name, data, limits=limits, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        except plans.PlanFileError as e:
            raise RefusedError(conversation.Refused("not_kept", str(e))) from None
    fields = {"subject": str(ref), "attachment": found.id, "size": found.size, "channel": WEB}
    _log.info("operator attached a file", extra=fields)
    return Attached(attachment=views.attachment(found))


def _detach(backend: Backend, ref: conversation.Ref, name: str) -> Detached:
    """Remove the attachment `name` from `ref`, through the function `canopy detach` calls.

    Returns:
        What was removed.

    Raises:
        RefusedError: a guard refused it.
    """
    with backend.open() as ctx:
        try:
            removed = attachments.remove(ctx.conn, ctx.state_dir, ref, name, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("operator removed an attachment", extra={"subject": str(ref), "attachment": removed.id, "channel": WEB})
    return Detached(name=removed.name)
