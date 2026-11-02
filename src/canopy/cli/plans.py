"""`canopy plan`: the operator asks for a ticket's plan, approves it or its feedback plan, or skips it (§25, §32).

Each writes through `canopy.core.plans`, which every channel shares, and refuses inside canopy's own ticks and runs.
`canopy archive` exports every plan into a directory of the operator's, and refuses there too.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, personas, plan_export, plans, prompts
from canopy.infra import logs
from canopy.runs import feedback_plans

if TYPE_CHECKING:
    from collections.abc import Collection

    from canopy.core.context import Context

CLI = "cli"


@click.command("plan")
@click.argument("ref", metavar="KEY")
@click.option(
    "--approve",
    is_flag=True,
    help="Approve its newest plan as its file stands now, your edits included: its feedback plan, when one waits, "
    "whole, or by --item or --leave.",
)
@click.option(
    "--item",
    "chosen",
    type=click.IntRange(min=1),
    multiple=True,
    metavar="N",
    help="With --approve, on a feedback plan: approve its item N, by the number `canopy show KEY` gives it; repeat for "
    "each. Its other items are left out: its resume does not act on them, and the next plan gets them.",
)
@click.option(
    "--leave",
    "leave",
    type=click.IntRange(min=1),
    multiple=True,
    metavar="N",
    help="With --approve, on a feedback plan: approve every item but item N, which is left out; repeat for each.",
)
@click.option(
    "--message",
    "-m",
    "words",
    metavar="TEXT",
    help="With --approve: your own words, written on the ticket with the approval. A plan's implement reads them "
    "beside the plan, for small points that need no new plan; a feedback plan's resume reads them after the message "
    "naming its items.",
)
@click.option("--skip", is_flag=True, help="Waive its plan: its implement goes ahead without one.")
@click.option("--persona", metavar="NAME", help="The persona of the planner this asks for, that run alone.")
@click.pass_context
def cmd_plan(
    click_ctx: click.Context,
    ref: str,
    *,
    approve: bool,
    chosen: tuple[int, ...],
    leave: tuple[int, ...],
    words: str | None,
    skip: bool,
    persona: str | None,
) -> int:
    """Ask for a plan for a ticket, approve its plan, or skip it, whatever `policy.plan` says.

    Without a flag, the next tick dispatches a planner, which writes down how the work will be done; nothing is
    implemented until you approve the plan. Asking again supersedes the plan it has. Read a plan with
    `canopy show KEY`, edit its file if you like, then approve it, or ask for changes with `canopy reply KEY`.
    `--approve --message TEXT` approves it with a note its implement reads beside it, for a point too small to plan
    again for.

    Under `policy.feedback_plan = "approve"`, a ticket's PR feedback is planned before its resume: while its feedback
    plan waits, `--approve` approves that plan, whole, or only the items you name by number with `--item`, or all but
    those you name with `--leave`, and its next resume goes ahead on it once. `canopy show KEY` lists its items. The
    approval writes a message on the ticket naming the items to address and to leave, with your `--message` after it.

    --persona NAME, one `canopy personas` lists, is the persona of the planner this asks for alone, as
    `canopy persona KEY NAME --agent planner --next` sets it.
    """
    if approve and skip:
        raise click.UsageError("--approve and --skip are each a decision of their own; pass one")
    if (chosen or leave or words is not None) and not approve:
        raise click.UsageError("--item, --leave, and --message go with --approve")
    if chosen and leave:
        raise click.UsageError("--item names the items to approve and --leave those to leave out; pass one")
    if persona is not None and (approve or skip):
        raise click.UsageError("--persona is for the planner a plan is asked of; --approve and --skip start none")
    try:
        conversation.check_operator()
        subject = conversation.parse_ref(ref)
        conversation.check_verb(subject, "plan")
    except conversation.Refused as r:
        raise CliError(f"plan refused ({r.guard}): {r.reason}") from None
    ctx = open_context(click_ctx)
    try:
        if approve:
            _approve(ctx, subject.id, chosen=chosen, leave=leave, words=words)
        elif persona is not None:
            # Checked first, so a persona no run could use asks for nothing.
            personas.check(ctx.config, persona)
            _ask(ctx, subject.id, skip=False)
            personas.choose_next(ctx.conn, ctx.config, subject.id, "planner", persona, channel=CLI)
            click.echo(f"Its next planner run alone writes in {persona}.")
        else:
            _ask(ctx, subject.id, skip=skip)
    except conversation.Refused as r:
        raise CliError(f"plan refused ({r.guard}): {r.reason}") from None
    return 0


@click.command("archive")
@click.argument("dest", metavar="DIR", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--conversations",
    is_flag=True,
    help="Export each planned ticket's conversation beside its plans too, as KEY/CONVERSATION.md.",
)
@click.pass_context
def cmd_archive(click_ctx: click.Context, dest: Path, *, conversations: bool) -> int:
    """Export every plan into DIR, superseded and feedback plans included, each with what the journal records of it.

    Each plan goes to DIR/KEY/, named for its run, status, and title, as RUN-APPROVED-export-reports-as-csv.md, as its
    file stands now under a front matter of its status, hashes, approval, and its planner's persona, and beside it the
    prompt its planner was given, as RUN-PROMPT.md, and, when you edited it, the plan as its planner wrote it, as
    RUN-ORIGINAL.md. Your comments on a ticket's plans go to DIR/KEY/COMMENTS.md. Each ticket's DIR/KEY/README.md lists
    its plans and the runs and PRs that followed them, and DIR/README.md every ticket, unless one there is your own:
    canopy rewrites only a README.md its first line says canopy wrote. A file is rewritten only when what it holds
    changed, and removed only when it moved to a new name, so DIR can be a clone of a repository of yours that you
    commit and push. Plans hold what the planners read of your tickets, and prompts and comments your own words: keep
    that repository private.

    --conversations adds each planned ticket's conversation, every message canopy records on it, as
    DIR/KEY/CONVERSATION.md: workers' reports and questions, your replies, and mirrored tracker comments, a private
    ticket's too.

    Raises:
        CliError: it runs inside one of canopy's ticks or runs, or DIR cannot be written.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"archive refused ({r.guard}): {r.reason}") from None
    ctx = open_context(click_ctx)
    try:
        exported = plan_export.export(
            ctx.conn,
            ctx.state_dir,
            dest,
            conversations=conversations,
            comments=True,
            indexes=True,
        )
    except plan_export.ExportError as e:
        raise CliError(f"archive failed: {e}") from None
    logs.for_tick(None).info(
        "plans exported",
        extra={"dest": str(dest), "written": len(exported.written), "skipped": len(exported.skipped)},
    )
    for name in exported.written:
        click.echo(f"wrote {name}")
    for name in exported.removed:
        click.echo(f"removed {name}, now under another name")
    for s in exported.skipped:
        click.echo(f"skipped {s.ticket_key}'s {s.kind} of run {s.run_id}: its file is {s.problem}")
    always = {"plan", "prompt", "README", *(("conversation",) if conversations else ())}
    written = plan_export.counted((Path(name).name for name in exported.written), always=always)
    click.echo(f"Exported {written} to {dest}; {exported.unchanged} unchanged, {len(exported.skipped)} skipped.")
    return 0


def _approve(ctx: Context, key: str, *, chosen: Collection[int], leave: Collection[int], words: str | None) -> None:
    if feedback_plans.waiting(ctx.conn, key):
        _approve_feedback(ctx, key, chosen=chosen, leave=leave, words=words)
        return
    if chosen or leave:
        raise conversation.Refused(
            "bad_plan",
            f"--item and --leave approve a feedback plan by item, and none of {key}'s waits",
        )
    plan = plans.approve(ctx.conn, ctx.state_dir, key, channel=CLI, dispatch_lock=ctx.dispatch_lock_path, note=words)
    logs.for_tick(None).info(
        "plan approved",
        extra={"ticket": key, "plan": plan.id, "noted": words is not None, "channel": CLI},
    )
    path = plans.path_for(ctx.state_dir, key, plan.run_id)
    click.echo(f"Plan {plan.id} of {key} is approved as {path} stands now. The next tick can implement it.")
    if words is not None:
        click.echo(f"Your note is a message on {key}, which its implement reads beside the plan: `canopy show {key}`.")
    click.echo("Its implement refuses (plan_changed) if the file changes before then; approve it again if it does.")


def _approve_feedback(
    ctx: Context,
    key: str,
    *,
    chosen: Collection[int],
    leave: Collection[int],
    words: str | None,
) -> None:
    plan = feedback_plans.approve(
        ctx.conn,
        ctx.state_dir,
        key,
        trust=ctx.config.trust,
        ws=ctx.workspace,
        channel=CLI,
        dispatch_lock=ctx.dispatch_lock_path,
        chosen=chosen,
        leave=leave,
        words=words,
    )
    covered = feedback_plans.items(ctx.conn, plan.id)
    left = [i for i in covered if i.left_out]
    logs.for_tick(None).info(
        "feedback plan approved",
        extra={"ticket": key, "feedback_plan": plan.id, "left_out": [i.item_id for i in left], "channel": CLI},
    )
    path = plans.path_for(ctx.state_dir, key, plan.run_id)
    if left:
        kept = [(i.number, i.item_id) for i in covered if not i.left_out]
        click.echo(
            f"Feedback plan {plan.id} of {key} is approved as {path} stands now, for {len(kept)} of its "
            f"{len(covered)} items: {prompts.item_names(kept)}. The next tick can resume {key} on it, once.",
        )
        click.echo(f"Left out, for the next plan: {prompts.item_names([(i.number, i.item_id) for i in left])}.")
    else:
        click.echo(
            f"Feedback plan {plan.id} of {key}, covering {len(covered)} item{'s' if len(covered) != 1 else ''}, is "
            f"approved whole as {path} stands now. The next tick can resume {key} on it, once.",
        )
    click.echo(f"Message {plan.approved_message_id} on {key} names the items for its resume: `canopy show {key}`.")
    click.echo("Its resume refuses (plan_changed) if the file changes before then; approve it again if it does.")


def _ask(ctx: Context, key: str, *, skip: bool) -> None:
    verb = plans.skip if skip else plans.ask
    asked = verb(ctx.conn, key, dispatch_lock=ctx.dispatch_lock_path)
    logs.for_tick(None).info(
        "plan skipped" if skip else "plan asked for",
        extra={"ticket": key, "superseded": asked.superseded, "channel": CLI},
    )
    if asked.superseded is not None:
        click.echo(f"Plan {asked.superseded} of {key} is superseded; its file stays.")
    if skip:
        state = "was already skipped" if asked.already else "is skipped"
        click.echo(f"{key}'s plan {state}: its implement goes ahead without one.")
    elif asked.already:
        click.echo(f"{key} already waits on a plan: the next tick dispatches a planner if none is running.")
    else:
        click.echo(
            f"{key} is planned first: the next tick dispatches a planner, and nothing is implemented until you approve "
            f"its plan with `canopy plan {key} --approve`.",
        )
