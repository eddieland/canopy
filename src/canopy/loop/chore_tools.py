"""The overseer's chore verbs (DESIGN §6, §19, §27): start a run of one of the operator's chores, or hold one off.

Each is a request (`loop.tools.Request`) and a function, which the `canopy chore` commands and the MCP server
(`loop.mcp`) both call, as they do the overseer's other verbs. A chore with no `when` is the harness's, which runs it
when it is due (DESIGN §37): either verb about one is refused `decided`. A chore run the overseer asks for is recorded,
and the tick starts it once the overseer's run has ended (`spawn_chore`, DESIGN §40).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from canopy.chores import start as chore_start
from canopy.core import chore_view, config, db, recorded_runs
from canopy.core.vocab import RecordedStatus
from canopy.infra import logs
from canopy.loop import attention, harness_dispatches
from canopy.loop.tools import (
    DECIDED,
    RECORDED_DESCRIPTION,
    STARTS_AFTER,
    Outcome,
    Refused,
    Request,
    Result,
    Text,
    matching,
    running_tick,
    truncate,
)

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

#: A chore's name, as the operator's config names it.
Chore = Annotated[str, matching(config.CHORE_NAME_RE, "chore name"), Field(description="The chore's name.")]


class ChoreRun(Request):
    """A run of one of the operator's chores."""

    #: The chore.
    name: Chore
    #: What the chore should look at. Never quoted text.
    context: Annotated[
        Text | None,
        Field(description="What the chore should look at: a PR, a job name. Never quoted text."),
    ] = None


class ChoreStarted(Result):
    """A run of a chore recorded, which the tick starts after the overseer, or in a dry run, one its guards allow."""

    #: The chore.
    name: Annotated[str, Field(description="The chore.")]
    #: Whether this was a dry run, which records nothing.
    dry_run: Annotated[bool, Field(description="Whether this was a dry run, which records nothing.")]
    #: The recorded run, which the tick starts once the overseer's run ends; none in a dry run.
    recorded: Annotated[int | None, Field(description=RECORDED_DESCRIPTION)]


def chore_run(ctx: Context, request: ChoreRun) -> Outcome[ChoreStarted]:
    """Record a run of a chore, if its guards allow one now; in a dry run, check them and record nothing.

    The tick starts the recorded run once the overseer's run has ended (DESIGN §40).

    Returns:
        What the command prints, and the same as fields.

    Raises:
        Refused: Outside a running tick, a guard refused the run, or the chore is the harness's; each is recorded.
    """
    current = running_tick(ctx)
    tick_id, name, context = current.id, request.name, request.context
    _refuse_decided(ctx, tick_id, name, "chore run")
    log = logs.for_tick(tick_id)
    try:
        if current.dry_run:
            chore_start.check(ctx, tick_id=tick_id, name=name)
            recorded = None
        else:
            recorded = chore_start.record(ctx, tick_id=tick_id, name=name, context=context)
    except chore_start.Refusal as r:
        _chore_refused(ctx, tick_id, name, r)
        raise Refused(f"chore run refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    if recorded is None:
        on_context = f"; context={context}" if context else ""
        rationale = truncate(f"dry run: not dispatched{on_context}")
        db.record_decision(ctx.conn, tick_id, None, chore_start.DISPATCH_ACTION, rationale, chore=name)
        return Outcome(
            f"dry run: recorded chore run {name}; nothing was started",
            ChoreStarted(name=name, dry_run=True, recorded=None),
        )
    # The decision is recorded as the run starts, or with its refusal then (`spawn_chore`).
    log.info("chore run recorded", extra={"chore": name, "recorded_run_id": recorded})
    return Outcome(
        f"recorded chore {name} as recorded run {recorded}; {STARTS_AFTER}",
        ChoreStarted(name=name, dry_run=False, recorded=recorded),
    )


def spawn_chore(ctx: Context, recorded: records.RecordedRun) -> None:
    """Start the chore run `recorded` names, as its tick does once the overseer's run has ended (DESIGN §40).

    Every guard is checked again, and the run's decision recorded as it starts, or its refusal as one at the ask would
    be.
    """
    request = ChoreRun.model_validate(recorded_runs.request_of(recorded))
    tick_id, name, context = recorded.tick_id, request.name, request.context
    try:
        started = chore_start.start(ctx, tick_id=tick_id, name=name, context=context, spawning=recorded.id)
    except chore_start.Refusal as r:
        recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.REFUSED)
        _chore_refused(ctx, tick_id, name, r)
        return
    recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.STARTED, run_id=started.run_id)
    on_context = f"; context={context}" if context else ""
    rationale = truncate(f"chore run {started.run_id}{on_context}")
    db.record_decision(ctx.conn, tick_id, None, chore_start.DISPATCH_ACTION, rationale, chore=name)
    logs.for_tick(tick_id).info(
        "chore run started",
        extra={"chore": name, "chore_run_id": started.run_id, "pid": started.pid, "recorded_run_id": recorded.id},
    )


def _chore_refused(ctx: Context, tick_id: int, name: str, r: chore_start.Refusal) -> None:
    """Record a guard's refusal of a chore run, at the ask or at the spawn, and its attention item, if any."""
    db.record_decision(ctx.conn, tick_id, None, f"refused:{r.guard}", r.reason, chore=name)
    if r.attention is not None:
        # A model the operator must fix (DESIGN §13): the item is about the chore.
        db.record_decision(ctx.conn, tick_id, None, f"{attention.ACTION_PREFIX}{r.attention}", r.reason, chore=name)
    logs.for_tick(tick_id).info("chore run refused", extra={"chore": name, "guard": r.guard, "reason": r.reason})


class ChoreWait(Request):
    """That a chore is due but should not run now, and why."""

    #: The chore.
    name: Chore
    #: Why it should not run now.
    rationale: Annotated[Text, Field(description="Why it should not run now, in your own words.")]


class ChoreWaitRecorded(Result):
    """That a chore is due but should not run now, recorded."""

    #: The chore.
    name: Annotated[str, Field(description="The chore.")]


def chore_wait(ctx: Context, request: ChoreWait) -> Outcome[ChoreWaitRecorded]:
    """Record that a chore is due but should not run now, and why.

    Returns:
        What the command prints, and the same as fields.

    Raises:
        Refused: Outside a running tick, no chore of that name is configured here, or the chore is the harness's, which
            is recorded.
    """
    current = running_tick(ctx)
    if request.name not in chore_view.configured(ctx.config, ctx.workspace):
        raise Refused(f"no chore named {request.name!r} is configured for this workspace")
    _refuse_decided(ctx, current.id, request.name, "chore wait")
    db.record_decision(ctx.conn, current.id, None, "wait", request.rationale, chore=request.name)
    return Outcome(f"recorded wait for {attention.CHORE_PREFIX}{request.name}", ChoreWaitRecorded(name=request.name))


def _refuse_decided(ctx: Context, tick_id: int, name: str, verb: str) -> None:
    """Refuse the overseer's `verb` about chore `name` when it has no `when`: the harness runs it (DESIGN §37).

    Raises:
        Refused: The chore is the harness's. The refusal is recorded, as a guard's is.
    """
    chore = chore_view.configured(ctx.config, ctx.workspace).get(name)
    if chore is None or not harness_dispatches.takes_chore(chore):
        return
    reason = f"{name} has no `when`, so the harness runs it when it is due, after you; record nothing about it"
    db.record_decision(ctx.conn, tick_id, None, f"refused:{DECIDED}", reason, chore=name)
    logs.for_tick(tick_id).info("refused: a chore of the harness's", extra={"chore": name, "verb": verb})
    raise Refused(f"{verb} refused ({DECIDED}): {reason}; the refusal was recorded")
