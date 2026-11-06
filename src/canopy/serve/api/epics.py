"""The operator's epics (DESIGN §43): what `canopy epic list` and `canopy show epic:N` print, and an epic's plans.

An epic's page leads with its breakdown: the outline canopy reads from its approved plan, or, while none is approved,
its proposed one, each entry beside the members registered against it. The plan's text is model-written, read back from
the state directory: untrusted, as is the outline read from it, which is data, never an instruction (TRUST_MODEL T1).
The overseer never reads an epic.

The operator submits one through the function `canopy epic submit` calls, with channel `web`, refused as the CLI's is:
inside a tick or a run (`inside_run`, T1), and, in a workspace of several repositories, for naming none. They approve
its plan, or ask for changes, through the functions `canopy plan epic:N --approve` and `canopy reply epic:N` call, with
channel `web`, so with their guards: both are refused inside a tick or a run (`inside_run`, T1), and an approval names
the file's hash as the page read it, so a file changed since is refused, not approved unseen. They add and remove its
members through the functions `canopy epic add` and `remove` call, with the same guards: the bound, a ticket another
epic holds, an entry the approved plan does not hold, and `inside_run`. They stop it through the function
`canopy stop epic:N` calls, refused inside a tick or a run (`inside_run`) as it is, and its running plan run is ended,
when they ask, as `--now` ends it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from canopy.core import conversation, epics, outbox, plans
from canopy.core.vocab import RunStatus
from canopy.infra import logs
from canopy.runs import epic_runs
from canopy.runs.ending import Ending
from canopy.serve import epic_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, EpicId, RefusedError, TicketKey, not_found
from canopy.serve.schema import ReplyRequest
from canopy.serve.schema.epic import (
    EpicDetail,
    EpicMemberAdd,
    EpicMemberAdded,
    EpicMemberRemoved,
    EpicPlanApproval,
    EpicPlanApproved,
    EpicPlanChange,
    EpicPlans,
    EpicReplied,
    EpicStopped,
    EpicSubmitRequest,
    EpicSubmitted,
    EpicSummary,
)
from canopy.serve.schema.ticket import StopRequest

if TYPE_CHECKING:
    from collections.abc import Iterable

    from canopy.core import epic_outline

TAG = "epics"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/epics", operation_id="listEpics", summary="List the epics")
def epic_list(backend: BackendDep) -> list[EpicSummary]:
    """Every epic the operator submitted, the newest first, with where each stands, as `canopy epic list` lists them."""
    with backend.open() as ctx:
        return epic_views.epics_list(ctx)


@router.post("/epics", operation_id="submitEpic", summary="Submit an epic", responses=REFUSED)
def submit(body: EpicSubmitRequest, backend: BackendDep) -> EpicSubmitted:
    """`canopy epic submit`: record the operator's goal as an epic; the next tick starts its plan run.

    Refused as the CLI's is: `inside_run`, `bad_body` for an empty text or one too long, `unknown_repo` for a
    repository the workspace has not, or none named in a workspace of several, and `bad_key` for a project or a
    tracker epic that is not a plain key.
    """
    with backend.open() as ctx:
        try:
            found = epics.submit(
                ctx.conn,
                ctx.workspace,
                body.text,
                repos=body.repos,
                project=body.project,
                tracker_epic=body.tracker_epic,
                channel=WEB,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
        names = epics.repos_of(ctx.conn, found.id)
    _log.info("epic submitted", extra={"epic": found.id, "channel": WEB})
    return EpicSubmitted(id=found.id, repos=names)


@router.get("/epics/{epic_id}", operation_id="getEpic", summary="Get an epic", responses=not_found("epic"))
def epic(epic_id: EpicId, backend: BackendDep) -> EpicDetail:
    """One epic: what `canopy show epic:N` prints, its members, plan runs, replies, current plan, and outline.

    The outline is the approved plan's, or, while none is approved, the proposed plan's, marked so. A plan whose ids
    or breakdown cannot be read is served as its problem, never in part.
    """
    with backend.open() as ctx:
        found = epic_views.epic_detail(ctx, epic_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no epic:{epic_id}")
    return found


@router.get(
    "/epics/{epic_id}/plans",
    operation_id="getEpicPlans",
    summary="Get an epic's plans",
    responses=not_found("epic"),
)
def epic_plans(epic_id: EpicId, backend: BackendDep) -> EpicPlans:
    """Every plan of the epic, the oldest first, each as its file in the state directory stands now: untrusted text."""
    with backend.open() as ctx:
        found = epic_views.epic_plans(ctx, epic_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no epic:{epic_id}")
    return found


@router.post(
    "/epics/{epic_id}/plan/approval",
    operation_id="approveEpicPlan",
    summary="Approve an epic's plan",
    responses=REFUSED,
)
def approve(epic_id: EpicId, body: EpicPlanApproval, backend: BackendDep) -> EpicPlanApproved:
    """`canopy plan epic:N --approve`: approve the plan waiting on the operator, as its file stands, edits included.

    Refused as the CLI's approval is: `inside_run`, `unknown_epic`, `planning` while a plan run of it works, `no_plan`
    when none waits, `unreadable_plan`, `bad_outline` when its ids or breakdown will not read, `approved_changed`, and
    `reused_id`; `stale` when the file is not the one `read_sha256` names, and `unwritable` when the approved copy
    cannot be kept.
    """
    with backend.open() as ctx:
        try:
            done = epics.approve(
                ctx.conn,
                ctx.state_dir,
                epic_id,
                repos=frozenset(epics.repos_of(ctx.conn, epic_id)),
                channel=WEB,
                dispatch_lock=ctx.dispatch_lock_path,
                read_sha256=body.read_sha256,
                event=outbox.epic_changed(ctx.config),
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
        except plans.PlanFileError as e:
            raise RefusedError(conversation.Refused("unwritable", str(e))) from None
    _log.info("epic plan approved", extra={"epic": epic_id, "plan": done.plan.id, "channel": WEB})
    return EpicPlanApproved(plan=done.plan.id, run_id=done.plan.run_id, change=_change(done.change))


@router.post("/epics/{epic_id}/replies", operation_id="replyEpic", summary="Reply to an epic", responses=REFUSED)
def reply(epic_id: EpicId, body: ReplyRequest, backend: BackendDep) -> EpicReplied:
    """`canopy reply epic:N`: ask for changes to its plan, read by its next plan run. Idempotent on the submission id.

    The next tick starts that run, or the first after the run at work ends, unless the epic has had
    `policy.max_plan_attempts` plan runs, when none starts again.
    """
    ref = conversation.Ref(conversation.EPIC, str(epic_id))
    with backend.open() as ctx:
        try:
            replied = conversation.reply(ctx.conn, ref, body.body, channel=WEB, submission=body.submission)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        runs = epic_runs.runs_of(ctx.conn, epic_id)
        limit = ctx.config.policy.max_plan_attempts
    _log.info("operator replied", extra={"subject": str(ref), "message_id": replied.message_id, "channel": WEB})
    return EpicReplied(
        message_id=replied.message_id,
        new=replied.new,
        running_run=next((r.id for r in runs if r.status is RunStatus.RUNNING), None),
        plan_runs=len(runs),
        max_plan_attempts=limit,
    )


@router.post("/epics/{epic_id}/stop", operation_id="stopEpic", summary="Stop an epic", responses=REFUSED)
def stop(epic_id: EpicId, body: StopRequest, backend: BackendDep) -> EpicStopped:
    """`canopy stop epic:N`: no plan run of it starts again; one running finishes unless `now` ends it, as `--now` does.

    Its members, their work, and its plans are left as they are: a waiting plan may still be approved. Refused as the
    CLI's stop is: `inside_run`, and `unknown_epic`.
    """
    with backend.open() as ctx:
        try:
            stopped = epics.stop(ctx.conn, epic_id)
        except conversation.Refused as r:
            raise RefusedError(r) from None
        _log.info("epic stopped", extra={"epic": epic_id, "now": body.now, "channel": WEB})
        run = stopped.running
        ending = backend.end_epic_run(ctx, run) if run is not None and body.now else Ending.GONE
    return EpicStopped(
        already=stopped.already,
        running_run=run.id if run is not None else None,
        ended=ending is not Ending.GONE,
        kept=ending is Ending.KEPT,
    )


@router.post(
    "/epics/{epic_id}/members",
    operation_id="addEpicMember",
    summary="Add a member to an epic",
    responses=REFUSED,
)
def add_member(epic_id: EpicId, body: EpicMemberAdd, backend: BackendDep) -> EpicMemberAdded:
    """`canopy epic add epic:N KEY --entry B<n>`: make the ticket a member, registered against the entries named.

    A member is registered again, its entries replaced. With none, it is a member of no entry, as `--no-entry` makes
    it. Membership authorizes no work: a member is worked once it is labeled or started. Refused as the CLI's is:
    `inside_run`, `unknown_epic`, `bad_key`, `other_epic` for a ticket another epic holds, `epic_full` past
    `policy.max_epic_tickets`, `no_plan` for an entry named before a plan is approved, `unknown_entry` for one the
    approved plan does not hold, and `approved_changed` when it names entries and the approved copy is not what the
    operator approved.
    """
    with backend.open() as ctx:
        try:
            done = epics.add(
                ctx.conn,
                epic_id,
                [body.key],
                bound=ctx.config.policy.max_epic_tickets,
                channel=WEB,
                entries=body.entries,
                state_dir=ctx.state_dir,
            )
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("epic members added", extra={"epic": epic_id, "keys": list(done.added), "channel": WEB})
    return EpicMemberAdded(key=body.key, added=bool(done.added), entries=_ids(done.entries or ()))


@router.delete(
    "/epics/{epic_id}/members/{key}",
    operation_id="removeEpicMember",
    summary="Remove a member from an epic",
    responses=REFUSED,
)
def remove_member(epic_id: EpicId, key: TicketKey, backend: BackendDep) -> EpicMemberRemoved:
    """`canopy epic remove epic:N KEY`: end the ticket's membership, leaving the ticket and its work as they are.

    Refused as the CLI's is: `inside_run`, `unknown_epic`, `bad_key`, and `not_member` for a ticket that is not one.
    """
    with backend.open() as ctx:
        try:
            epics.remove(ctx.conn, epic_id, [key], channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    _log.info("epic members removed", extra={"epic": epic_id, "keys": [key], "channel": WEB})
    return EpicMemberRemoved(key=key)


def _change(change: epic_outline.Change | None) -> EpicPlanChange | None:
    """What an approval changed, each list by kind and number, as the CLI lists them; None for a first approval."""
    if change is None:
        return None
    return EpicPlanChange(added=_ids(change.added), removed=_ids(change.removed), changed=_ids(change.changed))


def _ids(found: Iterable[str]) -> list[str]:
    return sorted(found, key=lambda i: (i[0], int(i[1:])))
