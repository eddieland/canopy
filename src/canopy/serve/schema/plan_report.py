"""The API's types for the Plans report (DESIGN §11, §25): how the window's plans were approved, and what followed.

Read from the plans, their comments, and the runs on their tickets, split by the level of `policy.planner_may_approve`
each plan run's prompt offered. Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type PlanLevel = Annotated[
    Literal["off", "strict", "normal", "lenient"],
    Field(
        description="A level of `policy.planner_may_approve` (DESIGN §25): `off` where the planner was asked nothing.",
    ),
]
type PlanOutcome = Annotated[
    Literal["planner", "as_written", "revised", "replaced", "dropped", "waiting"],
    Field(
        description="How a plan went: approved by its `planner`, by the operator `as_written` or `revised` (edited, "
        "commented on, or after an earlier plan was sent back), `replaced` by a newer plan, `dropped` with none after, "
        "or `waiting` on the operator.",
    ),
]


class PlanMetrics(Model):
    """How long a plan is, measured from its file as its planner wrote it, and how much of it is not prose."""

    words: int
    """Its words outside code blocks and diagrams, tables' cells included."""
    lines: int
    """How many of the plan editor's lines it fills, estimated: what the operator scrolls through."""
    code_blocks: int
    """Its fenced code blocks, diagrams aside."""
    tables: int
    """Its tables."""
    diagrams: int
    """Its Mermaid diagrams."""


class PlansRow(Model):
    """A ticket plan written in the window: how it went, how long approving it took, and what its ticket needed."""

    plan_id: int
    """The plan."""
    ticket_key: str
    """Its ticket."""
    run_id: int
    """The plan run that wrote it."""
    created_at: datetime
    """When it was written."""
    size: int
    """Its file's size as its planner wrote it, in bytes."""
    metrics: PlanMetrics | None = None
    """How long it is; None when its file as its planner wrote it could not be read."""
    effort: str | None = None
    """How much work its planner judged it, `small`, `medium`, or `large`; None when it gave no estimate."""
    level: PlanLevel | None = None
    """The level its plan run's prompt offered its planner; None for a run from before canopy kept it."""
    outcome: PlanOutcome
    """How it went."""
    approved_at: datetime | None = None
    """When it was approved; None when it was not."""
    hours_to_approve: float | None = None
    """From when it was written to its approval, in hours; None when it was not approved."""
    edited: bool
    """Whether its file was edited before its approval."""
    comments: int
    """The operator's comments and replies on its ticket's plan while it was the ticket's plan."""
    earlier: int
    """Its ticket's plans before it, which it replaced."""
    implemented: bool
    """Whether an `implement` followed it."""
    resumes: int
    """The `resume` runs its ticket started once it was approved."""
    reasons: dict[str, int]
    """How many of those named each reason, `ci`, `review`, `reply`, `conflict`, `no_pr`, or `retarget`; a resume may
    name several."""
    done: bool
    """Whether the loop has marked its ticket done, so its resumes are all in."""
    cost_usd: float | None = None
    """What its own run cost, in US dollars; None when it reported none."""


class PlansGroup(Model):
    """The window's approved plans of one level and one outcome, and what their tickets needed after."""

    level: PlanLevel | None = None
    """The level their plan runs were offered; None for the runs that kept none."""
    outcome: Literal["planner", "as_written", "revised"]
    """How they were approved."""
    plans: int
    """How many."""
    median_hours_to_approve: float | None = None
    """The median of their times to approval, in hours; None with none."""
    median_lines: int | None = None
    """The median of their lengths in the plan editor's lines, of those measured; None with none."""
    median_words: int | None = None
    """The median of their words, of those measured; None with none."""
    implemented: int
    """Those an `implement` followed."""
    with_resume: int
    """Of those, the ones whose ticket needed at least one `resume`."""
    resumes: int
    """The `resume` runs their tickets started once they were approved."""
    done: int
    """Those whose ticket the loop marked done, so their count is final."""


class PlansLength(Model):
    """The window's plans the operator approved, of one length, and how long approving them took."""

    low: int
    """The shortest length it holds, in the plan editor's lines."""
    high: int | None = None
    """The length it holds up to, not included, in the plan editor's lines; None for the longest."""
    plans: int
    """How many."""
    median_hours_to_approve: float | None = None
    """The median of their times to approval, in hours."""
    as_written: int
    """Of those, the ones approved as written."""


class PlansReport(Model):
    """How the window's plans were approved, by the level their planners were offered, and what their PRs needed."""

    days: int
    """How many local days the window holds, today's so far included."""
    since: datetime
    """When the window starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight after today."""
    level: PlanLevel
    """The level `policy.planner_may_approve` is at now, for the page to say beside the levels the plans were at."""
    plans: list[PlansRow]
    """The newest first."""
    groups: list[PlansGroup]
    """By level, `off` to `lenient`, then none kept; within each, the planner's, as written, then revised."""
    lengths: list[PlansLength]
    """The shortest first; only those with a plan. A plan that could not be measured is in none."""
    page_lines: int
    """How many of the plan editor's lines the page counts as a page, which the lengths are cut at multiples of."""
    outcomes: dict[str, int]
    """How many of the window's plans went each way, every outcome named, 0 for none."""
