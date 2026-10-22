"""`canopy plan`: the operator asks for a ticket's plan, approves it or its feedback plan, or skips it (§25, §32).

Each writes through `canopy.core.plans`, which every channel shares, and refuses inside canopy's own ticks and runs.
`canopy archive` exports every plan into a directory of the operator's, and refuses there too.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, feedback_plans, personas, plan_export, plans
from canopy.infra import logs

if TYPE_CHECKING:
    from canopy.core.context import Context

CLI = "cli"


@click.command("plan")
@click.argument("ref", metavar="KEY")
@click.option(
    "--approve",
    is_flag=True,
    help="Approve its newest plan as its file stands now, your edits included: its feedback plan, whole, when one "
    "waits.",
)
@click.option("--skip", is_flag=True, help="Waive its plan: its implement goes ahead without one.")
@click.option("--persona", metavar="NAME", help="The persona of the planner this asks for, that run alone.")
@click.pass_context
def cmd_plan(click_ctx: click.Context, ref: str, *, approve: bool, skip: bool, persona: str | None) -> int:
    """Ask for a plan for a ticket, approve its plan, or skip it, whatever `policy.plan` says.

    Without a flag, the next tick dispatches a planner, which writes down how the work will be done; nothing is
    implemented until you approve the plan. Asking again supersedes the plan it has. Read a plan with
    `canopy show KEY`, edit its file if you like, then approve it, or ask for changes with `canopy reply KEY`.

    Under `policy.feedback_plan = "approve"`, a ticket's PR feedback is planned before its resume: while its feedback
    plan waits, `--approve` approves that plan, whole, and its next resume goes ahead on it once.

    --persona NAME, one `canopy personas` lists, is the persona of the planner this asks for alone, as
    `canopy persona KEY NAME --agent planner --next` sets it.
    """
    if approve and skip:
        raise click.UsageError("--approve and --skip are each a decision of their own; pass one")
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
            _approve(ctx, subject.id)
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
    file stands now under a front matter of its status, hashes, and approval, and beside it the prompt its planner was
    given, as RUN-PROMPT.md. A file is rewritten only when its plan changed, and removed only when it moved to a
    new name, so DIR can be a clone of a repository of yours that you commit and push. Plans hold what the planners
    read of your tickets, and prompts your messages and standing instructions: keep that repository private.

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
        exported = plan_export.export(ctx.conn, ctx.state_dir, dest, conversations=conversations)
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
    names = [Path(name).name for name in exported.written]
    prompts = sum(map(plan_export.is_prompt, names))
    exported_conversations = sum(map(plan_export.is_conversation, names))
    counted = [(len(names) - prompts - exported_conversations, "plan"), (prompts, "prompt")]
    if conversations:
        counted.append((exported_conversations, "conversation"))
    written = ", ".join(f"{n} {noun}{'s' if n != 1 else ''}" for n, noun in counted[:-1])
    last, noun = counted[-1]
    click.echo(
        f"Exported {written} and {last} {noun}{'s' if last != 1 else ''} to {dest}; {exported.unchanged} unchanged, "
        f"{len(exported.skipped)} skipped.",
    )
    return 0


def _approve(ctx: Context, key: str) -> None:
    if feedback_plans.waiting(ctx.conn, key):
        _approve_feedback(ctx, key)
        return
    plan = plans.approve(ctx.conn, ctx.state_dir, key, channel=CLI, dispatch_lock=ctx.dispatch_lock_path)
    logs.for_tick(None).info("plan approved", extra={"ticket": key, "plan": plan.id, "channel": CLI})
    path = plans.path_for(ctx.state_dir, key, plan.run_id)
    click.echo(f"Plan {plan.id} of {key} is approved as {path} stands now. The next tick can implement it.")
    click.echo("Its implement refuses (plan_changed) if the file changes before then; approve it again if it does.")


def _approve_feedback(ctx: Context, key: str) -> None:
    plan = feedback_plans.approve(ctx.conn, ctx.state_dir, key, channel=CLI, dispatch_lock=ctx.dispatch_lock_path)
    logs.for_tick(None).info("feedback plan approved", extra={"ticket": key, "feedback_plan": plan.id, "channel": CLI})
    path = plans.path_for(ctx.state_dir, key, plan.run_id)
    covered = len(feedback_plans.items(ctx.conn, plan.id))
    click.echo(
        f"Feedback plan {plan.id} of {key}, covering {covered} item{'s' if covered != 1 else ''}, is approved whole as "
        f"{path} stands now. The next tick can resume {key} on it, once.",
    )
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
