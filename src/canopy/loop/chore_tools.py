"""The overseer's chore verbs (DESIGN §6, §19, §27): start a run of one of the operator's chores, or hold one off.

Each is a request (`loop.tools.Request`) and a function, which the `canopy chore` commands and the MCP server
(`loop.mcp`) both call, as they do the overseer's other verbs. A chore with no `when` is the harness's, which runs it
when it is due (DESIGN §37): either verb about one is refused `decided`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from canopy.chores import start as chore_start
from canopy.core import chore_view, config, db
from canopy.infra import logs
from canopy.loop import attention, harness_dispatches
from canopy.loop.tools import DECIDED, Refused, Request, Text, matching, running_tick, truncate

if TYPE_CHECKING:
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


def chore_run(ctx: Context, request: ChoreRun) -> str:
    """Start a run of a chore, if its guards allow one now; in a dry run, check them and start nothing.

    Returns:
        What the command prints.

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
            started = None
        else:
            started = chore_start.start(ctx, tick_id=tick_id, name=name, context=context)
    except chore_start.Refusal as r:
        db.record_decision(ctx.conn, tick_id, None, f"refused:{r.guard}", r.reason, chore=name)
        log.info("chore run refused", extra={"chore": name, "guard": r.guard, "reason": r.reason})
        raise Refused(f"chore run refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    on_context = f"; context={context}" if context else ""
    if started is None:
        rationale = truncate(f"dry run: not dispatched{on_context}")
        db.record_decision(ctx.conn, tick_id, None, chore_start.DISPATCH_ACTION, rationale, chore=name)
        return f"dry run: recorded chore run {name}; nothing was started"
    rationale = truncate(f"chore run {started.run_id}{on_context}")
    db.record_decision(ctx.conn, tick_id, None, chore_start.DISPATCH_ACTION, rationale, chore=name)
    log.info("chore run started", extra={"chore": name, "chore_run_id": started.run_id, "pid": started.pid})
    return f"started chore {name}: run {started.run_id}"


class ChoreWait(Request):
    """That a chore is due but should not run now, and why."""

    #: The chore.
    name: Chore
    #: Why it should not run now.
    rationale: Annotated[Text, Field(description="Why it should not run now, in your own words.")]


def chore_wait(ctx: Context, request: ChoreWait) -> str:
    """Record that a chore is due but should not run now, and why.

    Returns:
        What the command prints.

    Raises:
        Refused: Outside a running tick, no chore of that name is configured here, or the chore is the harness's, which
            is recorded.
    """
    current = running_tick(ctx)
    if request.name not in chore_view.configured(ctx.config, ctx.workspace):
        raise Refused(f"no chore named {request.name!r} is configured for this workspace")
    _refuse_decided(ctx, current.id, request.name, "chore wait")
    db.record_decision(ctx.conn, current.id, None, "wait", request.rationale, chore=request.name)
    return f"recorded wait for {attention.CHORE_PREFIX}{request.name}"


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
