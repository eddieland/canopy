"""The API's types for spend (DESIGN §13): what the last day, 30 days, and all time cost, and a window's breakdown.

The breakdown is what `canopy spend` prints. Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model, Tick


class SpendWindow(Model):
    """What the agent runtime reported spending in the last `hours` hours (DESIGN §13).

    Worker, split, chore, review, and task runs and each tick's overseer, by when they started.
    """

    since: datetime
    """When the window starts."""
    hours: int
    """How long the window is, in hours."""
    cost_usd: float | None = None
    """What it cost, in US dollars; None when nothing in the window reported a cost."""


class Spend(Model):
    """What the last day, 30 days, and all time cost, read together, so a month never shows less than its day."""

    day: SpendWindow
    """The last 24 hours."""
    month: SpendWindow
    """The last 30 days."""
    total_usd: float | None = None
    """What every run in the journal cost, whenever it started, in US dollars; None when none reported a cost."""


type SpendGroup = Annotated[
    Literal["idle", "busy", "hand_run", "not_ok", "dry_run"],
    Field(
        description="What a tick that ended bought (DESIGN §6, Idle pacing; §11): `idle` and `busy` are the loop's "
        "word on an `ok` tick, `hand_run` an `ok` tick no loop ran, `not_ok` a live one that closed otherwise, and "
        "`dry_run` a dry run, whatever the loop said of it.",
    ),
]
type SpendKind = Annotated[
    Literal["overseer", "workers", "plans", "chores", "reviews", "tasks"],
    Field(
        description="A kind of agent run: each tick's overseer, worker runs, plan runs (`plan`, DESIGN §25, old "
        "`needs-plan` triage runs among them), chore runs, review runs, the operator's one-off tasks' runs (§36).",
    ),
]


class SpendCosts(Model):
    """What each kind of agent run cost, in US dollars, as the runtime reported it (§13); None where none reported."""

    overseer: float | None = None
    """The live ticks' overseers."""
    idle: float | None = None
    """The part of `overseer` idle ticks spent."""
    dry_run: float | None = None
    """Dry runs' overseers, apart from `overseer`."""
    workers: float | None = None
    """Worker and split runs."""
    plans: float | None = None
    """Plan runs, which write a ticket's plan (`plan`, DESIGN §25), old triage runs before a plan (`needs-plan`)
    among them."""
    chores: float | None = None
    """Chore runs, the operator's tries included."""
    reviews: float | None = None
    """Review runs."""
    tasks: float | None = None
    """The operator's one-off tasks' runs (DESIGN §36)."""
    total: float | None = None
    """Everything, dry runs included, as the 24 hour and 30 day counters count it."""


class SpendDay(Model):
    """One local day's costs, or one local hour's in a window in hours."""

    day: str
    """The day, `YYYY-MM-DD`, or the hour, `YYYY-MM-DDTHH`, in the local time of the machine canopy runs on."""
    start: datetime
    """When it starts: the day's local midnight, or the hour's start, so a page can write it in its own zone."""
    costs: SpendCosts
    """What the runs that started in it cost."""
    done: int = 0
    """How many tickets the loop marked done on it."""


class SpendTicket(Model):
    """What one ticket's own runs that started in the window cost, and whether it was marked done in the window."""

    key: str
    """The ticket."""
    title: str | None = None
    """Its title, as the overseer named it; None before it did."""
    runs: int
    """How many of its worker runs started in the window, a running one included."""
    reviews: int
    """How many review runs naming it started in the window."""
    cost_usd: float | None = None
    """What those cost, in US dollars; None when none reported a cost. Not the overseer's, which is no ticket's."""
    done: Literal["merged", "closed"] | None = None
    """How the loop marked it done in the window (DESIGN §7): its PRs merged, or the tracker closed it, which a
    tracker may do when its PR merges. None when it was not marked done in the window."""
    done_at: datetime | None = None
    """When it was marked done; None when it was not, in the window."""


class SpendPullRequest(Model):
    """What the runs that pushed to one PR and the review runs of it, started in the window, cost."""

    url: str
    """The PR."""
    ticket_key: str | None = None
    """The ticket that owns it: its unit's, else one a run or review named; None for a PR canopy only reviewed."""
    phase: str | None = None
    """Its unit's phase (DESIGN §7), `merged` once it merged; None for a PR no unit of the loop's has."""
    runs: int
    """How many runs that pushed to it started in the window: a run that pushed to two PRs counts on each."""
    reviews: int
    """How many review runs of it started in the window."""
    cost_usd: float | None = None
    """What those cost, in US dollars; None when none reported a cost."""


class SpendTool(Model):
    """What one tool's calls in one kind's runs that started in the window put into their context (DESIGN §13)."""

    kind: SpendKind
    """The kind of run that called it; the overseer's include dry runs."""
    tool: str
    """The tool's name as the runtime gives it, an MCP server's prefixed with the server's: untrusted text."""
    runs: int
    """How many of those runs called it."""
    calls: int
    """How many of its calls ended."""
    errors: int
    """How many of those ended in an error."""
    result_chars: int
    """The characters they returned, output or error, which each later model call of the run reads again."""
    est_tokens: int
    """`result_chars` over 4: an estimate of their tokens, since the runtime does not say which of a call's tokens a
    tool's result was."""


class SpendModel(Model):
    """What one kind's runs that started in the window spent on one model, as each run's session says (DESIGN §13)."""

    kind: SpendKind
    """The kind of run; the overseer's include dry runs."""
    model: str | None = None
    """As `provider/model`, as the runtime names it; None for the kind's runs no session named a model for: not read
    yet, no longer kept, failed to read, or making no model call."""
    runs: int
    """How many of those runs it wrote a reply of: a run on two models counts under each."""
    replies: int
    """How many replies it wrote; 0 for the runs no session named a model for."""
    cost_usd: float | None = None
    """What the sessions priced those replies at, in US dollars; for the runs no session named a model for, what the
    runs reported, None when none did."""


class SpendTicks(Model):
    """How many ended ticks of the window are in a group, and what their overseers cost."""

    group: SpendGroup
    """The group."""
    ticks: int
    """How many ticks."""
    cost_usd: float | None = None
    """What their overseers cost; None when none reported a cost."""


class SpendWoken(Model):
    """How many of the loop's live ticks one cause woke (`ticks.woken_by`, DESIGN §6), and what they cost."""

    by: str
    """What ended the wait before them: start | timer | gate | message | starts | grant | run | key"""
    ticks: int
    """How many ticks."""
    cost_usd: float | None = None
    """What their overseers cost; None when none reported a cost."""


class SpendUnpriced(Model):
    """How many of a kind's ended runs in the window reported no cost, of how many."""

    kind: SpendKind
    """The kind of run."""
    runs: int
    """How many ended in the window."""
    unpriced: int
    """How many of them reported no cost."""


class SpendMonth(Model):
    """The local calendar month so far against the operator's monthly budget (`spend.monthly_budget_usd`)."""

    month: str
    """The month, `YYYY-MM`, in the local time of the machine canopy runs on."""
    since: datetime
    """When it starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight on the next month's first day."""
    budget_usd: int
    """The budget, in whole US dollars. Nothing enforces it."""
    spent_usd: float | None = None
    """What every run that started in the month so far cost, dry runs included, in US dollars; None when none reported
    a cost."""
    elapsed: float
    """How much of the month has gone by, from 0 to 1."""
    projected_usd: float | None = None
    """What the month will cost if the rest of it spends as it has so far, in US dollars; None in its first day, or
    when nothing reported a cost."""
    alerts: list[int]
    """The percentages of the budget a sink that takes `loop` hears the month reach, lowest first: 100, always, and
    `spend.budget_alerts`."""


class SpendBreakdown(Model):
    """What a window of whole local days cost, today's so far included, as `canopy spend` prints it (ROADMAP M33).

    Or of whole clock hours, the current one's so far included, by the hour.
    """

    since: datetime
    """When the window starts: local midnight on its first day, or the start of its first hour."""
    days: int | None
    """How many days it spans; None for a window in hours."""
    hours: int | None = None
    """How many hours it spans; None for a window in days."""
    per_day: list[SpendDay]
    """Every day in it, or every hour, oldest first, those with nothing spent included."""
    totals: SpendCosts
    """The whole window's costs."""
    ticks: list[SpendTicks]
    """The ticks that ended in it, a row per group, in a fixed order: idle, busy, hand_run, not_ok, dry_run."""
    woken: list[SpendWoken]
    """The loop's live ticks by what woke them, the most common first."""
    unpriced: list[SpendUnpriced]
    """A row per kind of run, in a fixed order: overseer, workers, plans, chores, reviews, tasks."""
    idle_share: float | None = None
    """Idle ticks' share of what the live ticks that ended cost, from 0 to 1; None when they cost nothing, or reported
    no cost, so there is nothing to share."""
    idle_ticks: list[Tick]
    """The newest live idle ticks in the window, at most 20, newest first: what idle spend bought."""
    done: int = 0
    """How many tickets the loop marked done in the window, merged or closed."""
    per_done: float | None = None
    """The window's whole spend, the overseer's and chores' included, over the tickets marked done in it, in US
    dollars; None when none was, or nothing reported a cost."""
    tickets: list[SpendTicket] = []
    """Each ticket with a run or review run that started in the window, or marked done in it, the costliest first."""
    pull_requests: list[SpendPullRequest] = []
    """Each PR a run that started in the window pushed to, or a review run of it started in it, the costliest first."""
    tools: list[SpendTool] = []
    """What each kind's tool calls returned, by tool, the most characters first: a row per kind and tool."""
    models: list[SpendModel] = []
    """What each kind spent on each model, a row per kind and model: the kinds in a fixed order, overseer, workers,
    plans, chores, reviews, tasks, each kind's models the most costly first, and its runs no session named a model for
    last."""
    month: SpendMonth | None = None
    """The local calendar month so far against the operator's monthly budget, whatever the window; None when no budget
    is set."""
