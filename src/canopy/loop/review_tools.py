"""The overseer's review verbs (DESIGN §6, §21, §27, §34): start, hold off, or end a review, or revise its draft.

A revision is of a review's draft, which the operator's note asks for. Each verb is a request (`loop.tools.Request`) and
a function, which the `canopy review` commands and the MCP server (`loop.mcp`) both call, as they do the overseer's
other verbs. A review or a revision the overseer asks for is recorded, and the tick starts it once the overseer's run
has ended (`spawn_review`, `spawn_revision`, DESIGN §40).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import ConfigDict, Field, StrictInt, WithJsonSchema

from canopy.core import conversation, db, recorded_runs, review_revisions, review_runs
from canopy.core.vocab import RecordedStatus
from canopy.infra import logs
from canopy.loop import attention
from canopy.loop.tools import (
    RECORDED_DESCRIPTION,
    STARTS_AFTER,
    Key,
    Outcome,
    PrUrl,
    Refused,
    Repo,
    Request,
    Result,
    Text,
    one_of,
    required,
    running_tick,
    truncate,
)
from canopy.reviews import grants, review_requests, revise
from canopy.reviews import start as review_start

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

#: The decision `review end` records: the overseer ended a review request no review of could answer.
END_ACTION = "review:end"


class ReviewRun(Request):
    """A review of a PR at a commit."""

    # `repo` left out is the review guard's refusal, which the decisions record, so the request takes it.
    model_config = ConfigDict(json_schema_extra=required("repo"))

    #: The PR's URL, as an opaque string: the review's guards check it, and a refusal records it.
    pr: Annotated[str, Field(description="The PR's https:// URL.")]
    #: The full head commit read on the PR just now.
    sha: Annotated[str, Field(description="The full head commit you read on the PR just now.")]
    #: The ticket of one of the loop's own PRs.
    ticket: Annotated[Key | None, Field(description="The ticket of one of the loop's own PRs.")] = None
    #: The PR's repository, by its name in the map.
    repo: Annotated[
        Repo | None,
        WithJsonSchema({"type": "string"}),
        Field(description="The PR's repository, by its name in the map. Required."),
    ] = None
    #: What the reviewer should look at first. Never quoted text.
    context: Annotated[Text | None, Field(description="What the reviewer should look at first. Never quoted text.")] = (
        None
    )


class StartedReview(Result):
    """One review recorded, which the tick starts after the overseer, or in a dry run, one its guards would start."""

    #: The persona it is written in; none for the reviewer's own.
    persona: Annotated[str | None, Field(description="The persona it is written in; none for the reviewer's own.")]
    #: The recorded review, which the tick starts once the overseer's run ends; none in a dry run.
    recorded: Annotated[int | None, Field(description=RECORDED_DESCRIPTION)]


class WaitingReview(Result):
    """A review a guard held off after others of the PR started, which waits on a later tick with the rest."""

    #: The persona it is written in.
    persona: Annotated[str | None, Field(description="The persona it is written in.")]
    #: The guard that held it off.
    guard: Annotated[str, Field(description="The guard that held it off.")]


class ReviewsStarted(Result):
    """The reviews of a PR recorded, one in each persona still owed one, or in a dry run, those its guards allow."""

    #: The PR.
    pr: Annotated[str, Field(description="The PR.")]
    #: Whether this was a dry run, which records nothing.
    dry_run: Annotated[bool, Field(description="Whether this was a dry run, which records nothing.")]
    #: Each review recorded, in order.
    reviews: Annotated[tuple[StartedReview, ...], Field(description="Each review recorded, in order.")]
    #: The first review held off, if one was; it and those after it wait on a later tick.
    waits: Annotated[
        WaitingReview | None,
        Field(description="The first review held off, if one was; it and those after it wait on a later tick."),
    ]


def review_run(ctx: Context, request: ReviewRun) -> Outcome[ReviewsStarted]:
    """Record a review of a PR at a commit, if its guards allow one now; in a dry run, check them and record nothing.

    A PR the operator chose several personas for gets a review in each still owed one, side by side (DESIGN §31): a
    guard that refuses one after the first leaves it and the rest to a later tick. The tick starts each recorded one
    once the overseer's run has ended (DESIGN §40).

    Returns:
        The tool's text, and the same as fields.

    Raises:
        Refused: Outside a running tick, or a guard refused the review, which is recorded.
    """
    current = running_tick(ctx)
    asked = review_start.Request(pr=request.pr, sha=request.sha, ticket=request.ticket, repo=request.repo)
    try:
        due = review_start.due(ctx, asked)
    except review_start.Refusal as r:
        _record_refused(ctx, current, asked, r)
        raise Refused(f"review refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    said: list[str] = []
    started: list[StartedReview] = []
    waits: WaitingReview | None = None
    for i, one in enumerate(due):
        try:
            outcome = _review_one(ctx, current, one, request.context)
        except review_start.Refusal as r:
            if i == 0:
                _record_refused(ctx, current, one, r)
                raise Refused(f"review refused ({r.guard}): {r.reason}; the refusal was recorded") from None
            # The reviews started stand; this one and the rest wait on a tick with room for them.
            db.record_decision(ctx.conn, current.id, one.ticket, f"refused:{r.guard}", r.reason, pr=one.pr)
            said.append(f"{one.persona}'s review waits ({r.guard}): {r.reason}")
            waits = WaitingReview(persona=one.persona, guard=r.guard)
            break
        said.append(outcome.text)
        started.append(outcome.result)
    return Outcome(
        "\n".join(said),
        ReviewsStarted(pr=request.pr, dry_run=current.dry_run, reviews=tuple(started), waits=waits),
    )


def _review_one(
    ctx: Context,
    current: records.Tick,
    one: review_start.Request,
    context: str | None,
) -> Outcome[StartedReview]:
    """Record one review for the tick to start, or in a dry run check its guards and record the decision.

    Returns:
        The tool's text of it, and the same as fields.

    Raises:
        Refusal: a guard refused it.
    """
    tick_id = current.id
    in_persona = f" in {one.persona}" if one.persona is not None else ""
    on_context = f"; context={context}" if context else ""
    if current.dry_run:
        review_start.check(ctx, tick_id=tick_id, request=one)
        rationale = truncate(f"dry run: not dispatched; would review {one.sha}{in_persona}{on_context}")
        db.record_decision(ctx.conn, tick_id, one.ticket, review_start.DISPATCH_ACTION, rationale, pr=one.pr)
        return Outcome(
            f"dry run: recorded review of {one.pr}{in_persona}; nothing was started",
            StartedReview(persona=one.persona, recorded=None),
        )
    # The decision is recorded as the review starts, or with its refusal then (`spawn_review`).
    recorded = review_start.record(ctx, tick_id=tick_id, request=one, context=context)
    logs.for_tick(tick_id).info(
        "review recorded",
        extra={"pr": one.pr, "recorded_run_id": recorded, "persona": one.persona},
    )
    return Outcome(
        f"recorded review of {one.pr}{in_persona} as recorded run {recorded}; {STARTS_AFTER}",
        StartedReview(persona=one.persona, recorded=recorded),
    )


def spawn_review(ctx: Context, recorded: records.RecordedRun) -> None:
    """Start the review `recorded` names, as its tick does once the overseer's run has ended (DESIGN §40).

    Every guard is checked again, and the review's decision recorded as it starts, or its refusal as one at the ask
    would be.
    """
    one, context = review_start.recorded_request(recorded)
    tick_id = recorded.tick_id
    in_persona = f" in {one.persona}" if one.persona is not None else ""
    on_context = f"; context={context}" if context else ""
    try:
        started = review_start.start(ctx, tick_id=tick_id, request=one, context=context, spawning=recorded.id)
    except review_start.Refusal as r:
        recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.REFUSED)
        tick = db.get_tick(ctx.conn, tick_id)
        if tick is not None:
            _record_refused(ctx, tick, one, r)
        return
    recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.STARTED, run_id=started.run_id)
    rationale = truncate(f"review run {started.run_id}: {one.sha} in {started.slot}{in_persona}{on_context}")
    db.record_decision(ctx.conn, tick_id, one.ticket, review_start.DISPATCH_ACTION, rationale, pr=one.pr)
    logs.for_tick(tick_id).info(
        "review started",
        extra={"pr": one.pr, "review_run_id": started.run_id, "pid": started.pid, "persona": one.persona},
    )


def _record_refused(
    ctx: Context,
    current: records.Tick,
    asked: review_start.Request,
    r: review_start.Refusal,
) -> None:
    """Record a refused review, and what it leaves for the operator: an answered request, or an attention item."""
    tick_id, pr, ticket = current.id, asked.pr, asked.ticket
    log = logs.for_tick(tick_id)
    # A malformed URL is recorded cut short; the refusal says what was wrong with it.
    pr_key = pr if len(pr) <= review_start.MAX_PR_URL else pr[: review_start.MAX_PR_URL]
    db.record_decision(ctx.conn, tick_id, ticket, f"refused:{r.guard}", r.reason, pr=pr_key)
    if r.guard == "reviewed" and not current.dry_run and review_requests.answered(ctx.conn, pr):
        # The head already has a `done` review: that answers a `once` request, which no new review would end.
        log.info("review request answered", extra={"pr": pr_key})
    if r.guard == "review_limit":
        # The overseer wants a review the limit forbids: a human has to look (DESIGN §21).
        action = f"{attention.ACTION_PREFIX}review_limit"
        db.record_decision(ctx.conn, tick_id, ticket, action, f"{r.reason}; {grants.hint(pr_key)}", pr=pr_key)
    if r.attention is not None:
        # A persona the operator must fix (DESIGN §31): the item is about the PR, or its ticket.
        db.record_decision(ctx.conn, tick_id, ticket, f"{attention.ACTION_PREFIX}{r.attention}", r.reason, pr=pr_key)
    log.info("review refused", extra={"pr": pr_key, "guard": r.guard, "reason": r.reason})


class ReviewWait(Request):
    """That a PR is not to be reviewed now, and why."""

    #: The PR.
    pr: PrUrl
    #: The ticket of one of the loop's own PRs.
    ticket: Annotated[Key | None, Field(description="The ticket of one of the loop's own PRs.")] = None
    #: Why not now.
    rationale: Annotated[Text, Field(description="Why not now, such as checks still running, or a draft.")]


class ReviewWaitRecorded(Result):
    """That a PR is not to be reviewed now, recorded."""

    #: The PR.
    pr: Annotated[str, Field(description="The PR.")]
    #: The ticket of one of the loop's own PRs, if the call named one.
    ticket: Annotated[str | None, Field(description="The ticket of one of the loop's own PRs, if the call named one.")]


def review_wait(ctx: Context, request: ReviewWait) -> Outcome[ReviewWaitRecorded]:
    """Record that a PR is not to be reviewed now, and why.

    Returns:
        The tool's text, and the same as fields.

    Raises:
        Refused: Outside a running tick, or reviews are off.
    """
    current = running_tick(ctx)
    if not review_requests.reviews_on(ctx.conn, ctx.config):
        raise Refused("reviews are off: no [review] agent_prs or query, and no open review request")
    db.record_decision(ctx.conn, current.id, request.ticket, "wait", request.rationale, pr=request.pr)
    return Outcome(f"recorded wait for {request.pr}", ReviewWaitRecorded(pr=request.pr, ticket=request.ticket))


class ReviewEnd(Request):
    """The end of the operator's review request on a PR, which no review of could answer."""

    #: The requested PR.
    pr: PrUrl
    #: What the overseer read: the PR merged or closed first, or is in no repository here.
    reason: Annotated[
        str,
        one_of("reason", review_requests.OVERSEER_REASONS),
        WithJsonSchema({"type": "string", "enum": list(review_requests.OVERSEER_REASONS)}),
        Field(description="What you read: it merged or closed first, or is in no repository here."),
    ]


class ReviewEnded(Result):
    """The operator's review request on a PR ended, or in a dry run, recorded as one that would end."""

    #: The requested PR.
    pr: Annotated[str, Field(description="The requested PR.")]
    #: Why it ended.
    reason: Annotated[str, Field(description="Why it ended.")]
    #: Whether this was a dry run, which ended nothing.
    dry_run: Annotated[bool, Field(description="Whether this was a dry run, which ended nothing.")]


def review_end(ctx: Context, request: ReviewEnd) -> Outcome[ReviewEnded]:
    """End the operator's review request on a PR; in a dry run, record it and end nothing.

    Returns:
        The tool's text, and the same as fields.

    Raises:
        Refused: Outside a running tick, or there is no open request to end, which is recorded.
    """
    current = running_tick(ctx)
    tick_id, dry_run, pr, reason = current.id, current.dry_run, request.pr, request.reason
    try:
        review_requests.end(ctx.conn, pr, reason, dry_run=dry_run)
    except conversation.Refused as r:
        db.record_decision(ctx.conn, tick_id, None, f"refused:{r.guard}", r.reason, pr=pr)
        raise Refused(f"review end refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    result = ReviewEnded(pr=pr, reason=reason, dry_run=dry_run)
    if dry_run:
        db.record_decision(ctx.conn, tick_id, None, END_ACTION, f"dry run: not ended; {reason}", pr=pr)
        return Outcome(f"dry run: recorded the end of {pr}'s review request; nothing was ended", result)
    db.record_decision(ctx.conn, tick_id, None, END_ACTION, reason, pr=pr)
    logs.for_tick(tick_id).info("review request ended", extra={"pr": pr, "reason": reason})
    return Outcome(f"ended the review request on {pr}: {reason}", result)


class ReviewRevise(Request):
    """A revision of a review's draft, which the operator's note asks for."""

    #: The review whose draft to revise, as `reviews.revisions` names it.
    run: Annotated[StrictInt, Field(ge=1, description="The review run whose draft to revise, from reviews.revisions.")]


class RevisionStarted(Result):
    """A revision of a review's draft recorded, which the tick starts after the overseer, or in a dry run, allowed."""

    #: The review run whose draft it revises.
    review_run: Annotated[int, Field(description="The review run whose draft it revises.")]
    #: Whether this was a dry run, which records nothing.
    dry_run: Annotated[bool, Field(description="Whether this was a dry run, which records nothing.")]
    #: The recorded revision, which the tick starts once the overseer's run ends; none in a dry run.
    recorded: Annotated[int | None, Field(description=RECORDED_DESCRIPTION)]


def review_revise(ctx: Context, request: ReviewRevise) -> Outcome[RevisionStarted]:
    """Record a revision of a review's draft, if its guards allow one now; in a dry run, check them and record none.

    The tick starts the recorded one once the overseer's run has ended (DESIGN §40).

    Returns:
        The tool's text, and the same as fields.

    Raises:
        Refused: Outside a running tick, or a guard refused the revision, which is recorded.
    """
    current = running_tick(ctx)
    tick_id, run_id = current.id, request.run
    review = review_runs.get_review_run(ctx.conn, run_id)
    pr = review.pr_url if review is not None else None
    try:
        if current.dry_run:
            target = revise.check(ctx, tick_id=tick_id, run_id=run_id)
            said = f"dry run: not dispatched; would revise review run {run_id}'s version {target.version.number}"
            db.record_decision(ctx.conn, tick_id, None, review_start.DISPATCH_ACTION, truncate(said), pr=pr)
            return Outcome(
                f"dry run: recorded a revision of review run {run_id}'s draft; nothing was started",
                RevisionStarted(review_run=run_id, dry_run=True, recorded=None),
            )
        recorded = revise.record(ctx, tick_id=tick_id, run_id=run_id)
    except review_start.Refusal as r:
        _revision_refused(ctx, tick_id, run_id, pr, r)
        raise Refused(f"revision refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    logs.for_tick(tick_id).info(
        "revision recorded",
        extra={"pr": pr, "review_run_id": run_id, "recorded_run_id": recorded},
    )
    return Outcome(
        f"recorded a revision of review run {run_id}'s draft as recorded run {recorded}; {STARTS_AFTER}",
        RevisionStarted(review_run=run_id, dry_run=False, recorded=recorded),
    )


def spawn_revision(ctx: Context, recorded: records.RecordedRun) -> None:
    """Start the revision `recorded` names, as its tick does once the overseer's run has ended (DESIGN §40).

    Every guard is checked again, and the revision's decision recorded as it starts, or its refusal as one at the ask
    would be.
    """
    request = ReviewRevise.model_validate(recorded_runs.request_of(recorded))
    tick_id, run_id, pr = recorded.tick_id, request.run, recorded.pr_url
    try:
        started = revise.begin(ctx, tick_id=tick_id, run_id=run_id, spawning=recorded.id)
    except review_start.Refusal as r:
        recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.REFUSED)
        _revision_refused(ctx, tick_id, run_id, pr, r)
        return
    recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.STARTED, run_id=started.run_id)
    rationale = truncate(f"revision run {started.run_id} of review run {run_id}'s draft in {started.slot}")
    db.record_decision(ctx.conn, tick_id, None, review_start.DISPATCH_ACTION, rationale, pr=pr)
    logs.for_tick(tick_id).info(
        "revision started",
        extra={"pr": pr, "review_run_id": run_id, "revision_run_id": started.run_id, "pid": started.pid},
    )


def _revision_refused(ctx: Context, tick_id: int, run_id: int, pr: str | None, r: review_start.Refusal) -> None:
    """Record a guard's refusal of a revision, at the ask or at the spawn, and the attention items it raises."""
    db.record_decision(ctx.conn, tick_id, None, f"refused:{r.guard}", r.reason, pr=pr)
    if r.guard == "revision_limit" and pr is not None:
        # The operator's note asks for what the limit forbids: a human has to look (DESIGN §34).
        hint = review_revisions.hint(run_id)
        action = f"{attention.ACTION_PREFIX}review_limit"
        db.record_decision(ctx.conn, tick_id, None, action, f"{r.reason}; {hint}", pr=pr)
    if r.attention is not None:
        db.record_decision(ctx.conn, tick_id, None, f"{attention.ACTION_PREFIX}{r.attention}", r.reason, pr=pr)
    logs.for_tick(tick_id).info("revision refused", extra={"review_run_id": run_id, "guard": r.guard})
