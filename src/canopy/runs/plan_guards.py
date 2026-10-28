"""What a dispatch does for the ticket's plan and its feedback plans (DESIGN §25, §32).

The guards a `plan`, a `feedback-plan`, and the work an approved plan governs pass, and what a run's prompt says of the
plan it writes or follows. A guard here returns the guard and reason that refuse the dispatch, or None, as
`policy.blocked` does; `dispatch` raises them as its `Refusal`.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.core import db, feedback_plans, plans, prompts, sql
from canopy.core.vocab import PlanStatus, ReplyMode, RunKind
from canopy.runs import policy

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.context import Context


def plan_refusal(ctx: Context, key: str, *, slug: str | None, base: str | None) -> tuple[str, str] | None:
    """Refuse a plan that would describe work already started or handed on, or that could not read its ticket (§25).

    Returns:
        The guard and reason that refuse it, or None: a slug (`bad_slug`) or a base (`bad_base`) is given; the ticket
        (`bad_plan`) already has a branch; or (`no_read_tools`) no tracker read tools are known for the planner.
    """
    if slug is not None:
        return "bad_slug", "a plan writes down the work and names no branch; leave out slug (--slug)"
    if base is not None:
        return "bad_base", "a plan writes down the work and starts from no branch; leave out base (--base)"
    ticket = db.get_ticket(ctx.conn, key)
    if ticket is not None and ticket.branch:
        # Its first implement recorded the branch: a plan now would describe work already started (DESIGN §25, Open).
        return "bad_plan", f"{key} already has work on {ticket.branch}; a started ticket is not planned"
    if ctx.config.tracker.tools() is None:
        return "no_read_tools", "no tracker read tools are known for the planner; set tracker.mcp_server and read_tools"
    return None


def feedback_plan_refusal(ctx: Context, key: str, *, base: str | None) -> tuple[str, str] | None:
    """Refuse a feedback plan that is not due (DESIGN §32), before its branch is read.

    Returns:
        The guard and reason that refuse it, or None: a base is given (`bad_base`); feedback plans are off
        (`feedback_plan_off`); the ticket's feedback plan waits on the operator with nothing changed, or its approval
        waits for its resume (`bad_plan`); or it is stale, but inside the quiet period on its PRs (`quiet`).
    """
    if base is not None:
        return (
            "bad_base",
            "a feedback plan reads the PR's head and starts from no other branch; leave out base (--base)",
        )
    return feedback_plans.dispatch_refusal(ctx.conn, ctx.config, ctx.workspace, key, now=datetime.now(UTC))


def feedback_prs_refusal(
    ctx: Context,
    key: str,
    repos: Sequence[str],
    prs: Mapping[str, str],
) -> tuple[str, str] | None:
    """Refuse a feedback plan that could not read its ticket and PRs (DESIGN §32), once its branch is read.

    It reads each unit's PR at its head, the ticket's branch, so every unit it names must have a PR, among the ones the
    journal recorded, `prs`.

    Returns:
        The guard and reason that refuse it, or None: a unit has no PR (`bad_plan`); or (`no_read_tools`) no tracker
        read tools are known for the planner.
    """
    for repo in repos:
        if repo not in prs:
            return "bad_plan", f"{key} has no PR recorded in {repo}: a feedback plan plans what came back to a PR"
    if ctx.config.tracker.tools() is None:
        return "no_read_tools", "no tracker read tools are known for the planner; set tracker.mcp_server and read_tools"
    return None


def planned_refusal(
    ctx: Context,
    key: str,
    kind: str,
    repos: Sequence[str] = (),
    reasons: Collection[str] = (),
) -> tuple[str, str] | None:
    """Refuse work a plan the operator approved should govern, but does not (DESIGN §25, §32).

    A guard in code, whatever the overseer asks for: an `implement` waits on an approved plan when the ticket needs
    one, and an `implement` or `resume` never follows a plan whose file is no longer the text the operator approved.
    Under `policy.feedback_plan = "approve"`, a `resume` but one for `no_pr` alone waits on an approved feedback plan no
    `resume` has spent, and follows it in place of the ticket's plan.

    Returns:
        The guard and reason that refuse it, or None: an `implement` for a ticket that needs a plan and has none
        approved, or a `resume` that needs a feedback plan and has none approved and unspent over its repositories
        (`unplanned`); an `implement` or `resume` whose approved plan's file is missing, unreadable, or no longer has
        its approved hash (`plan_changed`).
    """
    if kind not in (RunKind.IMPLEMENT, RunKind.RESUME):
        return None
    if kind == RunKind.RESUME and feedback_plans.needed(ctx.config.policy, reasons):
        # It follows its feedback plan, not the ticket's: the ticket's plan is not its to check.
        return feedback_plans.resume_refusal(
            ctx.conn,
            ctx.state_dir,
            ctx.config.policy,
            key,
            repos_named=repos,
            reasons=reasons,
        )
    ticket = db.get_ticket(ctx.conn, key)
    plan = plans.current(ctx.conn, key)
    approved = plan is not None and plan.status is PlanStatus.APPROVED
    setting = ticket.plan_setting if ticket is not None else None
    if kind == RunKind.IMPLEMENT and not approved and plans.needed(ctx.config.policy.plan, setting):
        waiting = "its plan waits on the operator's approval" if plan is not None else "it has no plan approved"
        return "unplanned", f"{key} needs a plan before its implement, and {waiting}; dispatch `plan` or wait for it"
    if plan is not None and approved and plans.approved_text(ctx.state_dir, plan) is None:
        path = plans.path_for(ctx.state_dir, key, plan.run_id)
        return "plan_changed", (
            f"plan {plan.id} of {key}, {path}, is no longer the text the operator approved; they approve it again, "
            f"or ask for a new one or skip it"
        )
    return None


@dataclass(frozen=True)
class Followed:
    """The approved plan an `implement` or a `resume` follows: the ticket's, or a feedback plan, and its `{{PLAN}}`."""

    note: str
    plan_id: int | None = None
    feedback_plan_id: int | None = None
    #: The model canopy chose for the run that wrote the plan, which the worker's commits credit beside its own
    #: (`prompts.planner_trailer`); None when it chose none.
    planner_model: str | None = None


def plan_note(ctx: Context, key: str, kind: str, copy: Path, reasons: Collection[str]) -> Followed | None:
    """Return the approved plan an `implement` or a `resume` follows, and its `{{PLAN}}`, if the ticket has one.

    A `resume` that needs a feedback plan follows it, which `planned_refusal` let through, with the items it covers;
    any other follows the ticket's approved plan. The run records the plan's id, so `_run` writes the copy of the plan
    this prompt names, and no other (DESIGN §25, §32).

    Returns:
        The plan's id, and where the run's copy will be with the plan's outline; or None for another kind, or a ticket
        with no approved plan.
    """
    if kind not in (RunKind.IMPLEMENT, RunKind.RESUME):
        return None
    if kind == RunKind.RESUME:
        feedback = feedback_plans.follows(ctx.conn, ctx.config.policy, key, reasons)
        text = feedback_plans.approved_text(ctx.state_dir, feedback) if feedback is not None else None
        if feedback is not None and text is not None:
            covered = feedback_plans.items(ctx.conn, feedback.id)
            # Its drafts start from the plan's replies; a worker that posts its own (`post`) is given none (§32).
            drafting = ctx.config.trust.review_replies is ReplyMode.APPROVE
            note = prompts.feedback_plan_note(
                copy,
                plans.outline(text),
                [(i.number, i.pr_url, i.item, i.item_id, str(i.proposal)) for i in covered if not i.left_out],
                left_out=[(i.number, i.item_id) for i in covered if i.left_out],
                message_id=feedback.approved_message_id,
                by_planner=feedback.approved_channel == plans.PLANNER,
                proposed={i.number: i.reply for i in covered if drafting and not i.left_out and i.reply is not None},
            )
            return Followed(note=note, feedback_plan_id=feedback.id, planner_model=_model_of(ctx, feedback.run_id))
    approved = plans.approved_of(ctx.conn, key)
    text = plans.approved_text(ctx.state_dir, approved) if approved is not None else None
    if approved is None or text is None:
        return None
    note = prompts.plan_note(copy, plans.outline(text), by_planner=approved.approved_channel == plans.PLANNER)
    return Followed(note=note, plan_id=approved.id, planner_model=_model_of(ctx, approved.run_id))


def planner_model(ctx: Context, plan_id: int | None, feedback_plan_id: int | None) -> str | None:
    """Return the model of the planner whose plan a run follows, from the plan it recorded, as `plan_note` found it.

    Returns:
        The model canopy chose for the planner's run, or None when the run follows no plan or canopy chose none.
    """
    if feedback_plan_id is not None:
        feedback = feedback_plans.get(ctx.conn, feedback_plan_id)
        return _model_of(ctx, feedback.run_id) if feedback is not None else None
    if plan_id is None:
        return None
    row = sql.execute(ctx.conn, sql.select("run_id").from_("plans").where("id = ?", plan_id)).fetchone()
    return None if row is None else _model_of(ctx, int(row[0]))


def _model_of(ctx: Context, run_id: int) -> str | None:
    # The model a run asked for (`runs.model`), not the ones its session says served it, which canopy reads later.
    row = sql.execute(ctx.conn, sql.select("model").from_("runs").where("id = ?", run_id)).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def planner_may_approve(ctx: Context, key: str, kind: str) -> bool:
    """Whether the plan this run writes could be approved on its planner's word, so its prompt says how (DESIGN §25).

    Returns:
        What `record` will decide for the plan's kind, as the journal stands at dispatch.
    """
    if kind == policy.FEEDBACK_PLAN:
        return feedback_plans.planner_may_approve(ctx.conn, key)
    return plans.planner_may_approve(ctx.conn, key)


def feedback_repositories_note(
    ctx: Context,
    branch: str,
    slots: Sequence[db.RunSlot],
    prs: Mapping[str, str],
    desk: Path | None,
) -> str:
    """Return a feedback plan's `{{REPOSITORIES}}` section: each repository it reads, at its PR's head (DESIGN §32)."""
    lines = [
        (
            f"`{desk}` is a desk, a directory holding one link per repository's worktree, each checked out at "
            f"`{branch}` as its PR's head was pushed. Read each repository through its link. Nothing you leave in the "
            "desk or the worktrees survives."
        ),
        "",
    ]
    for s in slots:
        name = s.repo or ""
        found = ctx.workspace.repo(name)
        summary = f" {found.summary}" if found is not None and found.summary else ""
        where = desk / name if desk is not None else s.slot_path
        lines.append(f"- `{name}` at `{where}`: PR {prs.get(name, 'not recorded')}, from `{s.base_branch}`.{summary}")
    return "\n".join(lines)


def plan_repositories_note(ctx: Context, slots: Sequence[db.RunSlot], desk: Path | None) -> str:
    """Return a plan's `{{REPOSITORIES}}` section: each repository it reads, checked out at its base."""
    lines = [
        (
            f"`{desk}` is a desk, a directory holding one link per repository's worktree, each checked out at its base "
            "branch. Read each repository through its link. Nothing you leave in the desk or the worktrees survives."
        ),
        "",
    ]
    for s in slots:
        name = s.repo or ""
        found = ctx.workspace.repo(name)
        summary = f" {found.summary}" if found is not None and found.summary else ""
        where = desk / name if desk is not None else s.slot_path
        lines.append(f"- `{name}` at `{where}`, at `{s.base_branch}`.{summary}")
    return "\n".join(lines)
