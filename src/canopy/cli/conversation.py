"""The operator's verbs (DESIGN §22, D075): on tickets, chores, and runs, pausing and resuming the loop, and notices.

`pause` and `resume` act on the loop (§6), and `notice` tells every later run about a passing condition (§8). The rest
take a reference whose shape names its kind: a ticket key, `REPO#N` or a PR's URL, `chore:NAME`, `run:ID`,
`review:ID`, or `task:N`. A kind refuses a verb it does not take. `start`, `stop`, `reply`, `forget`, `dismiss`, and
`send` write through `canopy.core.conversation`, which every channel shares, or for a PR's review request (`start URL
--review`, `stop URL`) through `canopy.core.review_requests`, for a task (`stop task:N`) through `canopy.core.tasks`
(`cli/tasks.py`), `grant` through `canopy.runs.policy`, or `canopy.reviews.grants`
for a PR's reviews, `pause` and `resume` through `canopy.core.pause`, and `notice` through `canopy.core.notice`; all
ten refuse inside canopy's own ticks and runs, `notice` only when it sets or clears one.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli import tasks as tasks_cli
from canopy.cli.common import CliError, open_context
from canopy.cli.params import REPO
from canopy.cli.render import chore_line, named, phase_of, prs_of, result_of, spent
from canopy.core import (
    chore_result,
    chore_view,
    contract,
    conversation,
    db,
    notice,
    pause,
    personas,
    plan_threads,
    plans,
    prompts,
    review_requests,
    review_runs,
)
from canopy.core.vocab import PlanStatus, RunKind
from canopy.infra import logs
from canopy.infra.text import one_line
from canopy.loop import attention
from canopy.reviews import grants
from canopy.runs import halt, policy

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context
    from canopy.core.conversation import Ref

CLI = "cli"
# `canopy show` lists this many of a ticket's runs and messages.
SHOW_RUNS = 5
SHOW_MESSAGES = 100
# How much of a commented passage `canopy show --plans` quotes, as a change request does (DESIGN §25).
SHOW_QUOTE = 160


def _ref(text: str, verb: str) -> Ref:
    try:
        ref = conversation.parse_ref(text)
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise CliError(f"{verb} refused ({r.guard}): {r.reason}") from None
    return ref


def _operator(verb: str) -> None:
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"{verb} refused ({r.guard}): {r.reason}") from None


@click.command("pause")
@click.pass_context
def cmd_pause(click_ctx: click.Context) -> int:
    """Pause the loop: `canopy loop` starts no tick until you resume it. A tick already running finishes.

    Workers already dispatched keep going. `canopy tick` by hand, and t at the loop's terminal, still tick.
    """
    _operator("pause")
    ctx = open_context(click_ctx)
    already = pause.pause(ctx.conn, channel=CLI)
    if already:
        held = pause.paused(ctx.conn)
        since = f" {attention.age(held.since)} ago ({held.channel})" if held is not None else ""
        click.echo(f"The loop was already paused{since}.")
        return 0
    logs.for_tick(None).info("loop paused", extra={"channel": CLI})
    click.echo("Paused: the loop starts no tick until `canopy resume`.")
    return 0


@click.command("resume")
@click.pass_context
def cmd_resume(click_ctx: click.Context) -> int:
    """Resume a paused loop. If its wait has run out, it ticks at once."""
    _operator("resume")
    ctx = open_context(click_ctx)
    if pause.resume(ctx.conn):
        click.echo("The loop was not paused.")
        return 0
    logs.for_tick(None).info("loop resumed", extra={"channel": CLI})
    click.echo("Resumed: the loop ticks when its wait runs out.")
    return 0


@click.command("notice")
@click.argument("text", required=False, metavar="TEXT")
@click.option(
    "--for",
    "duration",
    metavar="DURATION",
    help=f"How long it lasts, such as 90m, 4h, or 2d; {notice.DEFAULT_MINUTES // 60}h without it, at most "
    f"{notice.MAX_MINUTES // (24 * 60)}d.",
)
@click.option("--clear", is_flag=True, help="Lift the notice in force before it lapses.")
@click.pass_context
def cmd_notice(click_ctx: click.Context, text: str | None, duration: str | None, *, clear: bool) -> int:
    """Tell every run from now on about a passing condition, such as a CI outage, until it lapses.

    Workers that build, fix CI, or resume, reviews, and chores hear it in their prompts, and the overseer holds a
    failed check it explains rather than spending a resume attempt on it. A run already running keeps the prompt it
    started with. Setting a notice replaces the one in force. Without TEXT or --clear, prints the one in force.
    """
    if clear and (text is not None or duration is not None):
        raise click.UsageError("--clear takes no TEXT or --for")
    if text is None and not clear:
        if duration is not None:
            raise click.UsageError("--for needs TEXT")
        ctx = open_context(click_ctx)
        held = notice.current(ctx.conn)
        click.echo("No notice to workers is in force." if held is None else notice.describe(held, datetime.now(UTC)))
        return 0
    _operator("notice")
    ctx = open_context(click_ctx)
    log = logs.for_tick(None)
    if clear:
        ended = notice.clear(ctx.conn, channel=CLI)
        if ended is None:
            click.echo("No notice to workers was in force.")
            return 0
        log.info("notice cleared", extra={"channel": CLI, "notice": ended.id})
        click.echo("Notice cleared: runs dispatched from now on hear none. The loop ticks soon.")
        return 0
    try:
        minutes = notice.parse_duration(duration) if duration is not None else None
        held = notice.set_notice(ctx.conn, text or "", minutes=minutes, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"notice refused ({r.guard}): {r.reason}") from None
    log.info("notice set", extra={"channel": CLI, "notice": held.id, "lapses_at": held.lapses_at})
    click.echo(notice.describe(held, datetime.now(UTC)))
    click.echo(f"Runs dispatched from now on hear it until {held.lapses_at}. The loop ticks soon.")
    for path, kinds in prompts.missing_notice(ctx.config):
        click.echo(
            f"Warning: your override {path} has no {{{{NOTICE}}}}: {', '.join(kinds)} runs refuse (bad_prompt) until "
            "it gains the placeholder or the notice ends.",
            err=True,
        )
    return 0


@click.command("start")
@click.argument("ref", metavar="REF")
@click.option("--review", is_flag=True, help="REF is a PR's URL: review it once, at its head.")
@click.option("--notes", metavar="TEXT", help="With --review: what the reviewer should know or look at closely.")
@click.option(
    "--persona",
    "chosen",
    metavar="NAME",
    multiple=True,
    help="The persona of the run this starts, alone: its first worker's, its planner's with --plan, or its review's. "
    "With --review, give it again for a review in each, side by side.",
)
@click.option("--plan", is_flag=True, help="Plan it first: its implement waits on a plan you approve.")
@click.pass_context
def cmd_start(
    click_ctx: click.Context,
    ref: str,
    *,
    review: bool,
    notes: str | None,
    chosen: tuple[str, ...],
    plan: bool,
) -> int:
    """Work a ticket privately, or with --review have canopy review someone else's PR.

    A ticket started here has no queue label, and nothing canopy writes reaches it. Its conversation, the workers'
    reports and questions and your replies, stays in canopy's journal: read it with `canopy show`, answer with
    `canopy reply`.

    With --plan, a planner writes down how the work will be done first, and nothing is implemented until you approve
    it with `canopy plan KEY --approve`, whatever `policy.plan` says.

    --persona NAME, one `canopy personas` lists, is the persona of the ticket's next worker run alone, or its planner's
    with --plan, as `canopy persona KEY NAME --next` sets it; the runs after it take the ticket's override or
    [personas] again.

    With --review, REF is a PR the loop does not own, by its URL. canopy reviews it once, at its head, in whichever of
    the workspace's repositories it is in; the review goes in the journal and nothing is posted on the PR. --notes
    hands its reviewer what you want it to know, such as what the author asked for or the part that worries you; on a
    PR already requested, they replace the request's notes. --persona NAME, one `canopy personas` lists, is the voice
    its review is written in; given more than once, canopy reviews the PR once in each, side by side, and each review
    keeps its own draft. On a PR already requested, they replace the request's personas.
    """
    _operator("start")
    subject = _ref(ref, "start")
    if notes is not None and not review:
        raise click.UsageError("--notes is for a PR's review, with --review")
    if review:
        if plan:
            raise click.UsageError("--plan is for a ticket; a PR's review has no plan")
        return _start_review(click_ctx, subject, notes, chosen)
    if len(chosen) > 1:
        raise click.UsageError("a ticket's run takes one --persona; several are for a PR's reviews, with --review")
    return _start_ticket(click_ctx, subject, chosen[0] if chosen else None, plan=plan)


def _start_ticket(click_ctx: click.Context, subject: Ref, persona: str | None, *, plan: bool) -> int:
    ctx = open_context(click_ctx)
    agent: personas.NextAgent = "planner" if plan else "worker"
    try:
        if persona is not None:
            # Checked first, so a persona no run could use starts nothing.
            personas.check(ctx.config, persona)
        plan_lock = ctx.dispatch_lock_path if plan else None
        started = conversation.start(ctx.conn, ctx.config, subject, repo=ctx.repo, channel=CLI, plan_lock=plan_lock)
        if persona is not None:
            personas.choose_next(ctx.conn, ctx.config, subject.id, agent, persona, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"start refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "ticket started",
        extra={"ticket": subject.id, "already": started.already, "persona": persona},
    )
    state = "was already started" if started.already else "is started"
    click.echo(f"{subject} {state}, privately: workers read it and write nothing to it; their reports stay in canopy.")
    if plan:
        click.echo(
            "It is planned first: nothing is implemented until you approve its plan with "
            f"`canopy plan {subject} --approve`.",
        )
    if persona is not None:
        click.echo(f"Its next {agent} run alone writes in {persona}.")
    if started.running is not None:
        run = started.running
        kind = "private" if run.private else "public, dispatched before this start, so it may write to the ticket"
        click.echo(f"Run {run.id} ({run.kind}, {kind}) is still working it.")
    else:
        click.echo("The next tick picks it up. Follow it with `canopy show`; answer questions with `canopy reply`.")
    return 0


def _start_review(click_ctx: click.Context, subject: Ref, notes: str | None, chosen: tuple[str, ...]) -> int:
    ctx = open_context(click_ctx)
    try:
        requested = review_requests.request(ctx.conn, ctx.config, subject, channel=CLI, notes=notes, chosen=chosen)
    except conversation.Refused as r:
        raise CliError(f"start refused ({r.guard}): {r.reason}") from None
    noted = requested.request.notes is not None
    logs.for_tick(None).info(
        "review requested",
        extra={"pr": subject.id, "already": requested.already, "notes": noted, "personas": chosen, "channel": CLI},
    )
    names = review_requests.personas_of(ctx.conn, requested.request.id)
    written = (
        f"Its review is written in {names[0]}."
        if len(names) == 1
        else f"It is reviewed once in each of {', '.join(names)}, side by side."
    )
    if requested.already:
        replaced = " Its notes are replaced." if (notes or "").strip() else ""
        replaced += f" {written}" if chosen else ""
        click.echo(f"{subject} was already requested for review.{replaced}")
        return 0
    click.echo(f"{subject} is requested for review. The next tick reviews its head, once. Nothing is posted on the PR.")
    if chosen:
        click.echo(written)
    return 0


@click.command("stop")
@click.argument("ref", metavar="REF")
@click.option("--now", is_flag=True, help="Also end the run working it now, instead of letting it finish.")
@click.pass_context
def cmd_stop(click_ctx: click.Context, ref: str, *, now: bool) -> int:
    """Stop working a started ticket or a task (`task:N`), or stop reviewing a PR you asked canopy to review.

    A ticket is not dispatched again until `canopy start`, and a task is not started again; one still queued is
    dropped. A running run finishes, unless --now ends it: its processes are killed, its slots returned, and it ends
    `stopped`. A PR's review request ends; a review of it already running finishes.
    """
    _operator("stop")
    subject = _ref(ref, "stop")
    if subject.kind == conversation.TASK:
        return tasks_cli.stop(open_context(click_ctx), int(subject.id), now=now)
    if subject.kind == conversation.PR:
        if now:
            raise click.UsageError("--now is for a ticket's run; a PR's running review finishes")
        return _stop_review(click_ctx, subject)
    ctx = open_context(click_ctx)
    try:
        stopped = conversation.stop(ctx.conn, subject, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"stop refused ({r.guard}): {r.reason}") from None
    log = logs.for_tick(None)
    log.info("ticket stopped", extra={"ticket": subject.id, "now": now})
    click.echo(f"{subject} {'was already stopped' if stopped.already else 'is stopped'}; nothing dispatches it now.")
    run = stopped.running
    if run is None:
        return 0
    if not now:
        click.echo(f"Run {run.id} ({run.kind}) is still working it and will finish; --now ends it.")
        return 0
    if halt.end(ctx, run, log):
        click.echo(f"Run {run.id} ({run.kind}) was ended and its slots returned.")
    else:
        click.echo(f"Run {run.id} ({run.kind}) had already ended.")
    return 0


def _stop_review(click_ctx: click.Context, subject: Ref) -> int:
    ctx = open_context(click_ctx)
    try:
        stopped = review_requests.stop(ctx.conn, subject)
    except conversation.Refused as r:
        raise CliError(f"stop refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("review request stopped", extra={"pr": subject.id, "channel": CLI})
    click.echo(f"{subject}'s review request is stopped; nothing reviews it now.")
    if stopped.running is not None:
        click.echo(f"Review run {stopped.running.id} of it is still running and will finish.")
    return 0


@click.command("reply")
@click.argument("ref", metavar="REF")
@click.argument("text", required=False)
@click.pass_context
def cmd_reply(click_ctx: click.Context, ref: str, text: str | None) -> int:
    """Answer a ticket, or note something to a chore, with TEXT or, without it, stdin.

    On a ticket the next tick reads it and a waiting loop wakes. On a public ticket it is your word to the loop, read as
    an authorized reply is, and how you say what to do about an untrusted reviewer's comments (`untrusted_review`). It
    never reaches the ticket. On `chore:NAME` it is a note the chore's next runs read, such as a finding to leave out
    until a date; the loop does not wake for it.
    """
    _operator("reply")
    subject = _ref(ref, "reply")
    body = text if text is not None else sys.stdin.read()
    ctx = open_context(click_ctx)
    try:
        chores = chore_view.defined(ctx.config, ctx.workspace)
        replied = conversation.reply(ctx.conn, subject, body, channel=CLI, chores=chores)
    except conversation.Refused as r:
        raise CliError(f"reply refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("operator replied", extra={"subject": str(subject), "message_id": replied.message_id})
    answered = f", answering message {replied.answers}" if replied.answers is not None else ""
    if replied.new:
        click.echo(f"Recorded message {replied.message_id} on {subject}{answered}.")
    else:
        click.echo(f"Message {replied.message_id} on {subject} already says this{answered}; nothing new recorded.")
    return 0


@click.command("forget")
@click.argument("ref", metavar="REF")
@click.pass_context
def cmd_forget(click_ctx: click.Context, ref: str) -> int:
    """Forget a ticket's branch and PRs, so its next implement starts over on a new branch.

    Its runs and conversation stay in the journal for `canopy show`, and its runs still count toward the attempt limits.
    A persona override from `canopy persona` stays too; `canopy persona KEY --clear` removes it. Close its PRs and
    delete its branch yourself: canopy never does.
    """
    _operator("forget")
    subject = _ref(ref, "forget")
    ctx = open_context(click_ctx)
    try:
        forgot = conversation.forget(ctx.conn, subject, channel=CLI, dispatch_lock=ctx.dispatch_lock_path)
    except conversation.Refused as r:
        raise CliError(f"forget refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "ticket forgotten",
        extra={"ticket": subject.id, "branch": forgot.branch, "prs": forgot.prs},
    )
    click.echo(f"{subject} is forgotten: its next implement starts over on a new branch.")
    if forgot.branch is not None or forgot.prs:
        untracked = [*([f"branch {forgot.branch}"] if forgot.branch is not None else []), *forgot.prs]
        click.echo(f"canopy no longer tracks {', '.join(untracked)}.")
        click.echo(
            "Close its PRs and delete its branch on origin yourself: until you do, the overseer still finds them and "
            "the ticket cannot start over.",
        )
    granted = policy.grants(ctx.conn)
    for (key, repo), counts in sorted(policy.attempts(ctx.conn).items(), key=str):
        limit = policy.unit_limits(ctx.config, granted.get((key, repo), {}))[RunKind.IMPLEMENT]
        if key == subject.id and counts[RunKind.IMPLEMENT] >= limit:
            where, flag = ("", "") if repo is None else (f" in {repo}", f" --repo {repo}")
            click.echo(
                f"It has had {counts['implement']} implement runs{where}, and its limit is {limit}: grant it "
                f"another with `canopy grant {subject} implement{flag}`.",
            )
    return 0


@click.command("grant")
@click.argument("ref", metavar="REF")
# `fix-ci` is taken only to be refused naming `resume`, whose limit its runs now count toward (DESIGN §8).
@click.argument(
    "kind",
    type=click.Choice(
        [*(str(k) for k in (*policy.UNIT_GRANT_KINDS, *policy.TICKET_GRANT_KINDS)), grants.KIND, str(policy.RETIRED)],
    ),
)
@click.option("--repo", type=REPO, help="The repository of the ticket's unit. Needed when it has had runs in several.")
@click.option("--runs", type=click.IntRange(min=1), default=1, show_default=True, help="How many more runs to allow.")
@click.pass_context
def cmd_grant(click_ctx: click.Context, ref: str, kind: str, repo: str | None, runs: int) -> int:
    """Allow a ticket more runs of KIND than `policy.max_<kind>_attempts`, in one repository, or a PR more reviews.

    For a ticket at its attempt limit that you want the loop to keep working, or, with REF a PR's URL and KIND
    `review`, a PR past `policy.max_reviews_per_pr` that you want reviewed again. A `plan` is the ticket's, in no one
    repository, so it takes no --repo. Every run still counts toward the limit; this raises that unit's, ticket's, or
    PR's limit, and only from your shell. The next tick decides whether to use it.
    """
    subject = _ref(ref, "grant")
    if (subject.kind == conversation.PR) != (kind == grants.KIND):
        raise CliError(f"grant refused (bad_kind): {_grant_mismatch(subject, kind)}")
    ctx = open_context(click_ctx)
    if kind == grants.KIND:
        return _grant_reviews(ctx, subject, repo=repo, runs=runs)
    if kind in policy.TICKET_GRANT_KINDS:
        return _grant_ticket(ctx, subject, kind, repo=repo, runs=runs)
    try:
        granted = policy.grant(ctx.conn, ctx.config, subject.id, kind, repo=repo, runs=runs)
    except conversation.Refused as r:
        raise CliError(f"grant refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "attempts granted",
        extra={"ticket": subject.id, "repo": granted.repo, "kind": kind, "runs": runs},
    )
    click.echo(
        f"{subject} in {granted.repo} has had {granted.runs} {kind} runs, and may now have {granted.limit}. "
        "The next tick decides whether to dispatch it.",
    )
    return 0


def _grant_mismatch(subject: Ref, kind: str) -> str:
    if kind == grants.KIND:
        return f"{subject} is a ticket; `review` takes the PR's URL: `canopy grant <URL> review`"
    return f"{subject} is a PR, which takes only `review`; {kind} takes a ticket key"


def _grant_ticket(ctx: Context, subject: Ref, kind: str, *, repo: str | None, runs: int) -> int:
    if repo is not None:
        raise CliError(f"grant refused (bad_repo): a {kind}'s limit is the ticket's own; leave out --repo")
    try:
        granted = policy.grant_ticket(ctx.conn, ctx.config, subject.id, kind, runs=runs)
    except conversation.Refused as r:
        raise CliError(f"grant refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("attempts granted", extra={"ticket": subject.id, "kind": kind, "runs": runs})
    click.echo(
        f"{subject} has had {granted.runs} {kind} runs, and may now have {granted.limit}. "
        "The next tick decides whether to dispatch it.",
    )
    return 0


def _grant_reviews(ctx: Context, subject: Ref, *, repo: str | None, runs: int) -> int:
    if repo is not None:
        raise CliError("grant refused (bad_repo): a PR's review limit is the PR's own; leave out --repo")
    try:
        granted = grants.grant(ctx.conn, ctx.config, subject, runs=runs)
    except conversation.Refused as r:
        raise CliError(f"grant refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("reviews granted", extra={"pr": subject.id, "runs": runs})
    click.echo(
        f"{subject} has had {granted.runs} review runs, and may now have {granted.limit}. "
        "The next tick decides whether to review it.",
    )
    return 0


@click.command("dismiss")
@click.argument("ref", metavar="REF")
@click.argument("findings", metavar="FINDING...", nargs=-1, required=True)
@click.option("--undo", is_flag=True, help="Take the dismissals back.")
@click.pass_context
def cmd_dismiss(click_ctx: click.Context, ref: str, findings: tuple[str, ...], *, undo: bool) -> int:
    """Dismiss a chore's open FINDINGs (`chore:NAME`, by their ids) or a review's (`review:ID`, by their numbers).

    A chore's finding is off the attention list until the chore stops reporting it: `canopy show chore:NAME` still
    lists it, marked dismissed, and if it comes back after a run leaves it out, it is listed again. To have the chore
    stop reporting it, write the chore a note with `canopy reply chore:NAME`.

    A review's finding stays in `canopy review show ID`, marked, and is left out of what a resume hands a worker and of
    what the overseer reads. It is one run's finding: a new commit's review starts fresh.

    The findings are dismissed together or not at all: one refused leaves every other as it was.
    """
    _operator("dismiss")
    subject = _ref(ref, "dismiss")
    ctx = open_context(click_ctx)
    try:
        conversation.dismiss(
            ctx.conn,
            subject,
            findings,
            channel=CLI,
            chores=chore_view.defined(ctx.config, ctx.workspace),
            undo=undo,
        )
    except conversation.Refused as r:
        raise CliError(f"dismiss refused ({r.guard}): {r.reason}") from None
    named = list(dict.fromkeys(findings))
    log = logs.for_tick(None)
    for finding in named:
        log.info(
            "finding dismissal taken back" if undo else "finding dismissed",
            extra={"subject": str(subject), "finding": finding, "channel": CLI},
        )
    listed = ", ".join(named)
    # One finding reads as before; several take the plural.
    is_, they, it = ("are", "they", "them") if len(named) > 1 else ("is", "it", "it")
    if subject.kind == conversation.REVIEW:
        noun = f"{subject} finding{'s' if len(named) > 1 else ''} {listed}"
        if undo:
            click.echo(f"{noun} {is_} no longer dismissed: a resume hands {it} to the worker again.")
        else:
            click.echo(f"{noun} {is_} dismissed: no worker or tick acts on {it}.")
        return 0
    attention.write(ctx, log)
    if undo:
        click.echo(f"{subject} {listed} {is_} listed again while the chore reports {it}.")
    else:
        click.echo(
            f"{subject} {listed} {is_} dismissed: "
            f"{they} {is_} off the attention list until the chore stops reporting {it}.",
        )
    return 0


@click.command("send")
@click.argument("ref", metavar="review:ID")
@click.argument("findings", metavar="N...", nargs=-1, required=True, type=int)
@click.pass_context
def cmd_send(click_ctx: click.Context, ref: str, findings: tuple[int, ...]) -> int:
    """Send findings N... of a review run (`review:ID`, by their numbers) to a worker.

    It replies on the review's ticket for you, naming the findings by number and the ones it leaves alone, as you would
    with `canopy reply KEY`: the next tick reads it as your go-ahead and resumes a worker with the review's findings,
    which addresses the ones it names, whether or not `trust.trusted_reviewers` lists `canopy:review`. A review of a PR
    with no ticket refuses, as does a dismissed finding.
    """
    _operator("send")
    subject = _ref(ref, "send")
    ctx = open_context(click_ctx)
    try:
        sent = conversation.send(ctx.conn, subject, findings, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"send refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "findings sent",
        extra={
            "subject": str(subject),
            "findings": sorted(set(findings)),
            "ticket": sent.ticket,
            "message_id": sent.replied.message_id,
            "channel": CLI,
        },
    )
    numbers = ", ".join(str(n) for n in sorted(set(findings)))
    if sent.replied.new:
        click.echo(
            f"{subject} findings {numbers} went to {sent.ticket} as message {sent.replied.message_id}: "
            "the next tick reads it as your go-ahead.",
        )
    else:
        click.echo(f"{subject} findings {numbers} already went to {sent.ticket} as message {sent.replied.message_id}.")
    return 0


@click.command("show")
@click.argument("ref", metavar="REF")
@click.option(
    "--plans",
    "every_plan",
    is_flag=True,
    help="For a ticket, every plan it has had, and your open comments.",
)
@click.pass_context
def cmd_show(click_ctx: click.Context, ref: str, *, every_plan: bool) -> int:
    """Show a ticket's phase, PRs, plan, recent runs, and conversation, a run (`run:ID`), a chore, a task, or a PR.

    A ticket's newest plan is printed as its file stands, with its status; --plans prints every plan, oldest first, and
    the open comments on the newest. A chore is `chore:NAME`. A task, `task:N`, shows its text and each run, with its
    branch and the head it left on origin. A PR, by its URL, shows your review request on it, if you made one, and
    canopy's reviews of it.
    """
    subject = _ref(ref, "show")
    if every_plan and subject.kind != conversation.TICKET:
        raise click.UsageError("--plans is for a ticket")
    ctx = open_context(click_ctx)
    if subject.kind == conversation.RUN:
        _show_run(ctx, int(subject.id))
    elif subject.kind == conversation.TASK:
        tasks_cli.show(ctx, int(subject.id))
    elif subject.kind == conversation.CHORE:
        _show_chore(ctx, subject.id)
    elif subject.kind == conversation.PR:
        _show_pr(ctx, subject.id)
    else:
        _show_ticket(ctx, subject.id, every_plan=every_plan)
    return 0


def _show_pr(ctx: Context, url: str) -> None:
    request = review_requests.latest_request(ctx.conn, url)
    runs = review_runs.review_runs_of(ctx.conn, url)
    if request is None and not runs:
        raise CliError(f"canopy has no review request or review of {url}")
    click.echo(url)
    if request is None:
        click.echo("  no review request: reviewed as one of the loop's own PRs or a review.query match")
    else:
        made = f"made {attention.age(request.created_at)} ago via {request.channel}"
        if request.ended_at is None:
            click.echo(f"  review request: {made}, open")
        else:
            click.echo(f"  review request: {made}, ended {attention.age(request.ended_at)} ago ({request.end_reason})")
        chosen = review_requests.personas_of(ctx.conn, request.id)
        if chosen:
            click.echo(f"  {'persona' if len(chosen) == 1 else 'personas'}: {', '.join(chosen)}")
        if request.notes is not None:
            click.echo("  notes:")
            for line in conversation.printable(request.notes).splitlines():
                click.echo(f"    {line}")
    click.echo(f"\nReviews ({len(runs)}):")
    for r in runs:
        when = f"started {attention.age(r.started_at)} ago"
        if r.ended_at:
            when = f"ended {attention.age(r.ended_at)} ago"
        click.echo(f"  review:{r.id}  {r.sha[:12]}  {r.status}  {when}{f'  in {r.persona}' if r.persona else ''}")
    if not runs:
        click.echo("  none yet")
    else:
        click.echo(f"\nRead one with `canopy review show {runs[0].id}`.")


def _show_ticket(ctx: Context, key: str, *, every_plan: bool) -> None:
    ticket = db.get_ticket(ctx.conn, key)
    record = conversation.start_of(ctx.conn, key)
    if ticket is None and record is None:
        raise CliError(f"canopy has no record of {key}")
    if record is None:
        how = "public: its queue label authorizes it; its conversation is on the ticket, and copied here"
    else:
        how = f"private, {record.status} {attention.age(record.stopped_at or record.started_at)} ago"
        # The channel is the latest start's or stop's; `label` is a first dispatch under `tracker.private` (§22).
        how += " by its first dispatch, on its queue label" if record.channel == conversation.LABEL else ""
    click.echo(f"{key}: {how}")
    if ticket is not None and ticket.title:
        click.echo(f"  title {one_line(ticket.title)}")
    if ticket is not None:
        done = ", done" if ticket.done else ""
        click.echo(f"  phase {phase_of(ctx.conn, ticket)}{done}; branch {ticket.branch or 'none yet'}")
        for forget in db.forgets_of(ctx.conn, key):
            click.echo(f"  {_forget_line(forget)}")
        if ticket.forgotten_at:
            click.echo("  the runs and messages before the latest forget are history: the loop reads only later ones")
        for unit in db.units(ctx.conn, key):
            click.echo(f"  {unit.repo}  PR {unit.pr_url or 'none recorded'}  phase {unit.phase or 'unknown'}")
        _show_plans(ctx, ticket, every=every_plan)
    _show_runs(ctx, key)
    _show_conversation(ctx, key, record)


def _forget_line(forget: records.Forget) -> str:
    """One forget as `show` prints it: when, from where, and the branch and PRs it dropped."""
    line = f"forgotten {attention.age(forget.at)} ago"
    if forget.channel is None or forget.prs is None:
        return f"{line}, before canopy recorded what a forget dropped"
    dropped = [*([f"branch {forget.branch}"] if forget.branch is not None else []), *json.loads(forget.prs)]
    return f"{line} via {forget.channel}, dropping {', '.join(dropped) if dropped else 'no branch or PR'}"


def _show_plans(ctx: Context, ticket: records.Ticket, *, every: bool) -> None:
    """Print the ticket's newest plan as its file stands, or with `every` each of its plans and its open comments.

    Nothing is printed for a ticket plans do not touch, as the state block carries nothing for one (DESIGN §25).
    """
    key = ticket.key
    found = plans.history(ctx.conn, key)
    policy_plan = ctx.config.policy.plan
    needed = plans.needed(policy_plan, ticket.plan_setting)
    if not found and not needed:
        return
    why = f"your word, `{ticket.plan_setting}`" if ticket.plan_setting is not None else f"policy.plan {policy_plan}"
    click.echo(f"\nPlan: {'needed' if needed else 'not needed'}, by {why}")
    if not found:
        click.echo("  none yet: the next tick dispatches a planner")
    for plan in found if every else found[-1:]:
        _show_plan(ctx, plan)
    if not every and len(found) > 1:
        click.echo(f"\n{len(found) - 1} earlier plans: canopy show {key} --plans")
    if every:
        _show_plan_threads(ctx, key)
    newest = found[-1] if found else None
    if newest is not None and newest.status is PlanStatus.PROPOSED:
        click.echo(f"\nApprove it with `canopy plan {key} --approve`, or ask for changes with `canopy reply {key}`.")


def _show_plan(ctx: Context, plan: records.Plan) -> None:
    path = plans.path_for(ctx.state_dir, plan.ticket_key, plan.run_id)
    reading = plans.read(path)
    click.echo(f"\n  plan:{plan.id}  {plan.status}, written {attention.age(plan.created_at)} ago by run:{plan.run_id}")
    if plan.effort is not None:
        click.echo(f"  effort: {plan.effort}, as its planner judged")
    if plan.approved_at is not None and plan.approved_channel == plans.PLANNER:
        reason = conversation.printable(plan.approved_reason or "")
        click.echo(f"  approved {attention.age(plan.approved_at)} ago by the planner: {reason}")
    elif plan.approved_at is not None:
        click.echo(f"  approved {attention.age(plan.approved_at)} ago via {plan.approved_channel}")
    state = f"its file is {reading.problem}" if reading.problem is not None else ""
    if not state and reading.sha256 != plan.sha256:
        state = "edited since the planner wrote it"
    if plan.status is PlanStatus.APPROVED and reading.sha256 != plan.approved_sha256:
        state = f"{state}; " if state else ""
        state += "changed since it was approved: approve it again before its implement"
    click.echo(f"  {path}" + (f": {state}" if state else ""))
    if reading.text is not None:
        click.echo("")
        for line in conversation.printable(reading.text).splitlines():
            click.echo(f"    {line}")


def _show_plan_threads(ctx: Context, key: str) -> None:
    open_threads = [t for t in plan_threads.threads(ctx.conn, key) if t.thread.resolved_at is None]
    click.echo(f"\nYour open comments ({len(open_threads)}):")
    for t in open_threads:
        quote = one_line(t.thread.quote)
        cut = quote if len(quote) <= SHOW_QUOTE else f"{quote[: SHOW_QUOTE - 3]}..."
        click.echo(f'  comment {t.thread.id}, {attention.age(t.thread.created_at)} ago, on "{cut}":')
        click.echo(f"    {one_line(t.thread.body)}")
        for r in t.replies:
            click.echo(f"    reply: {one_line(r.body)}")
    if not open_threads:
        click.echo("  none")


def _show_runs(ctx: Context, key: str) -> None:
    runs = db.runs_of(ctx.conn, key, SHOW_RUNS)
    click.echo(f"\nRecent runs ({len(runs)}):")
    for r in runs:
        when = f"started {attention.age(str(r['started_at']))} ago"
        if r["ended_at"]:
            when = f"ended {attention.age(str(r['ended_at']))} ago"
        click.echo(f"  run:{r['id']}  {r['kind']}  {r['status']}  {when}")
    if not runs:
        click.echo("  none")


def _show_conversation(ctx: Context, key: str, record: records.Start | None) -> None:
    messages = db.messages_of(ctx.conn, conversation.TICKET, key, SHOW_MESSAGES)
    click.echo(f"\nConversation ({len(messages)}):")
    for m in messages:
        _echo_message(m)
    if not messages:
        click.echo("  none")
    # A public ticket's questions are on the tracker, but for a planner's, which canopy holds (DESIGN §25).
    waiting = plans.question(ctx.conn, key) if record is None else conversation.latest_question(ctx.conn, key)
    if waiting is not None and (record is None or conversation.is_started(record)):
        click.echo(f"\nMessage {waiting.id} waits on your answer: canopy reply {key} 'your answer'")


def _echo_message(m: records.Message) -> None:
    click.echo(_message_head(m))
    for line in conversation.printable(m.body).splitlines():
        click.echo(f"    {line}")


def _message_head(m: records.Message) -> str:
    who = {"worker": "worker", "operator": "you", "tracker": "tracker"}.get(m.source, m.source)
    if m.comment_id is not None:
        # A tracker comment the overseer mirrored: a copy, which authorizes nothing (DESIGN §22).
        cut = ", truncated" if m.truncated else ""
        return (
            f"  #{m.id}  {attention.age(m.at)} ago  {who} comment {m.comment_id} by {m.author}, "
            f"written {m.commented_at}{cut}"
        )
    about = f" (run:{m.run_id})" if m.run_id else ""
    if m.answers:
        about += f" answering {m.answers}"
    via = f" via {m.channel}" if m.source == "operator" else ""
    return f"  #{m.id}  {attention.age(m.at)} ago  {who} {m.kind}{about}{via}"


def _show_run(ctx: Context, run_id: int) -> None:
    run = db.get_run(ctx.conn, run_id)
    if run is None:
        raise CliError(f"no run {run_id}")
    private = ", private" if run["private"] else ""
    click.echo(
        f"run:{run_id}: {run['kind']} of {named(run['ticket_key'], run['ticket_title'])}{private}, {run['status']}",
    )
    click.echo(f"  started {run['started_at']}" + (f", ended {run['ended_at']}" if run["ended_at"] else ""))
    if run["branch"]:
        click.echo(f"  branch {run['branch']}")
    for s in db.run_slots(ctx.conn, run_id):
        click.echo(f"  {s.repo}  slot {s.slot_path}, from {s.base_branch}")
    result = result_of(run)
    for pr in prs_of(result):
        click.echo(f"  PR {pr}")
    said = one_line(str(result.get("harness") or ""))
    if said:
        click.echo(f"  harness: {said}")
    session = f"session {run['session_id']}" if run["session_id"] else "no session reported"
    click.echo(f"  {session}{spent(run)}")
    click.echo(f"  log {run['log_path']}")
    messages = db.run_messages(ctx.conn, run_id)
    if messages:
        click.echo("\nMessages:")
    for m in messages:
        _echo_message(m)


def _show_chore(ctx: Context, name: str) -> None:
    found = [s for s in chore_view.states(ctx.conn, ctx.config, ctx.workspace) if s.name == name]
    if not found:
        raise CliError(f"no chore {name!r} is configured for this workspace")
    [state] = found
    click.echo(f"chore:{name}: {chore_line(state, datetime.now(UTC))}")
    latest = state.latest_ended
    if latest is not None:
        said = one_line(contract.stored_note(result_of(latest)))
        click.echo(f"  latest run {latest.id} {latest.status}" + (f": {said}" if said else ""))
        session = f"session {latest.session_id}" if latest.session_id else "no session reported"
        click.echo(f"  {session}{spent(latest)}")
        click.echo(f"  log {latest.log_path}")
    findings = state.findings()
    more = state.more_findings()
    click.echo(f"\nOpen findings ({len(findings)}):")
    for f in findings:
        title = one_line(f.finding.title)
        mark = "  (dismissed)" if f.dismissed else ""
        click.echo(
            f"  {f.finding.id}  {attention.age(f.since)}  {title}"
            + (f"  {f.finding.link}" if f.finding.link else "")
            + mark,
        )
    if more:
        click.echo(f"  {chore_result.more_text(more)}")
    elif not findings:
        click.echo("  none")
    notes = db.messages_of(ctx.conn, conversation.CHORE, name, conversation.CHORE_NOTES)
    if notes:
        click.echo(f"\nYour notes its next run reads ({len(notes)}):")
    for m in notes:
        _echo_message(m)
