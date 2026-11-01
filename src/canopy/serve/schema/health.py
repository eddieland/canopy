"""The API's types for the health report (DESIGN §11): how the last days' runs ended, and what the guards refused.

What `canopy health` prints, with each day's ended and failed runs beside it for the page's chart, the failures by
their cause, and each guard's refusals by what was asked. Built on
`schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime

from canopy.serve.schema import Model
from canopy.serve.schema.spend import SpendKind, SpendUnpriced


class HealthOutcome(Model):
    """How many of one kind's runs, of one sort, ended in one status in the window, and what they cost."""

    kind: SpendKind
    """The kind of run."""
    what: str
    """Its sort: `live`, `dry run`, or `no overseer` for a tick, the run's kind for a worker or a plan, the chore's
    name, `review`, or `task`."""
    status: str
    """How they ended, as the journal records it."""
    failed: bool
    """Whether the status is one a run of the kind ends in when it did not do what it was started for."""
    runs: int
    """How many ended so."""
    cost_usd: float | None = None
    """What they cost, in US dollars; None when none reported a cost."""


class HealthFailure(Model):
    """One run of the window that ended in a failed status, the newest first."""

    kind: SpendKind
    """The kind of run."""
    id: int
    """The tick's id for the overseer, and the run's otherwise: a chore's, a review's, or a task's run's own."""
    what: str
    """Its sort, as `HealthOutcome.what`."""
    status: str
    """How it ended."""
    started_at: datetime
    """When it started."""
    ticket: str | None = None
    """The ticket a worker's or a plan's run was on; None for the other kinds."""
    pr_url: str | None = None
    """The PR a review read; None for the other kinds."""
    chore: str | None = None
    """The chore a chore's run ran; None for the other kinds."""
    task_id: int | None = None
    """The task a task's run was of; None for the other kinds."""
    note: str
    """The tick's summary, or the run's harness note or else its summary, on one line and cut: an agent wrote some of
    it, so it is text, never markup."""
    cost_usd: float | None = None
    """What it cost, in US dollars; None when it reported none."""


class HealthCause(Model):
    """The window's failures the harness explained alike, or `other`: those an agent's own words explained."""

    note: str | None
    """The harness's note, as `HealthFailure.note`; None for `other`, the failures whose note is an agent's summary,
    which never repeats, or that have none."""
    runs: int
    """How many failed so."""
    kinds: list[SpendKind]
    """The kinds of run among them, in the report's order of kinds."""
    latest: HealthFailure
    """The newest of them, to open."""


class HealthAsk(Model):
    """One thing a guard refused in the window, and how often: the ticket, chore, or PR it named, and the run's kind."""

    ticket: str | None = None
    """The ticket it named; None for a chore's run, or a review of a PR no ticket of the loop's holds."""
    chore: str | None = None
    """The chore it would have run; None for the rest."""
    pr: str | None = None
    """The PR it named, for a review; None for the rest."""
    kind: str | None = None
    """The kind of run a dispatch asked for: `implement`, `resume`, `plan`, `feedback-plan`; None for any other ask,
    and for a refusal recorded before the journal kept it."""
    decisions: int
    """How many of the guard's decisions refused it."""
    last_tick: int
    """The latest tick that asked for it."""


class HealthRefusal(Model):
    """How often a guard refused what a tick asked for in the window."""

    guard: str
    """The guard, as the decision names it: `capacity`, `cooldown`."""
    decisions: int
    """How many decisions it refused."""
    ticks: int
    """In how many ticks."""
    last_tick: int
    """The latest of them."""
    asks: list[HealthAsk]
    """What it refused most often, at most five, the most often first, then the latest: one ask refused tick after
    tick is the overseer stuck on it."""


class HealthCounts(Model):
    """A count of runs by kind, 0 for a kind with none."""

    overseer: int
    """Ticks."""
    workers: int
    """Worker runs."""
    plans: int
    """Plan runs, old triage runs before a plan among them."""
    chores: int
    """Chore runs."""
    reviews: int
    """Review runs."""
    tasks: int
    """The operator's one-off tasks' runs."""


class HealthDay(Model):
    """One local day of the window: the runs that started in it and ended, and the failed among them."""

    day: str
    """The day, `YYYY-MM-DD`, in the local time of the machine canopy runs on."""
    start: datetime
    """When it starts: its local midnight, so a page can write it in its own zone."""
    ended: HealthCounts
    """The runs that ended, by kind."""
    failed: HealthCounts
    """The runs that ended in a failed status, by kind."""


class HealthReport(Model):
    """How the last days' runs ended, the newest failures, what the guards refused, and each day's counts."""

    days: int
    """How many local days the window holds, today's so far included."""
    since: datetime
    """When the window starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight after today."""
    outcomes: list[HealthOutcome]
    """By kind in a fixed order, overseer, workers, plans, chores, reviews, tasks, then by sort and status."""
    failures: list[HealthFailure]
    """The newest first, at most twenty."""
    refusals: list[HealthRefusal]
    """The most frequent first."""
    causes: list[HealthCause]
    """Every failure of the window by its cause: the harness's notes, the most runs first, then the newest, and
    `other` last."""
    per_day: list[HealthDay]
    """Every day of the window, oldest first."""
    unpriced: list[SpendUnpriced]
    """How many of each kind's ended runs reported no cost, as the spend page counts them: a tick that ran no overseer
    cost nothing, and is never among them."""
