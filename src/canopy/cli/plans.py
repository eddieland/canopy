"""`canopy plan`: the operator asks for a ticket's plan, approves it or its feedback plan, or skips it (§25, §32).

Each writes through `canopy.core.plans`, which every channel shares, and refuses inside canopy's own ticks and runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, feedback_plans, plans
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
@click.pass_context
def cmd_plan(click_ctx: click.Context, ref: str, *, approve: bool, skip: bool) -> int:
    """Ask for a plan for a ticket, approve its plan, or skip it, whatever `policy.plan` says.

    Without a flag, the next tick dispatches a planner, which writes down how the work will be done; nothing is
    implemented until you approve the plan. Asking again supersedes the plan it has. Read a plan with
    `canopy show KEY`, edit its file if you like, then approve it, or ask for changes with `canopy reply KEY`.

    Under `policy.feedback_plan = "approve"`, a ticket's PR feedback is planned before its resume: while its feedback
    plan waits, `--approve` approves that plan, whole, and its next resume goes ahead on it once.
    """
    if approve and skip:
        raise click.UsageError("--approve and --skip are each a decision of their own; pass one")
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
        else:
            _ask(ctx, subject.id, skip=skip)
    except conversation.Refused as r:
        raise CliError(f"plan refused ({r.guard}): {r.reason}") from None
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
        f"{path} stands now. The next tick can resume {key} on it, once."
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
            f"its plan with `canopy plan {key} --approve`."
        )
