"""The API's types for the reports (DESIGN §11): what each local calendar month cost and got done.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime

from canopy.serve.schema import Model
from canopy.serve.schema.spend import SpendKind


class ReportTokens(Model):
    """The tokens a month's runs reported, by kind, summed over their model calls; 0 where none reported any."""

    input: int
    """Sent to a model and not read from the cache."""
    output: int
    """Written by a model, its reasoning apart."""
    reasoning: int
    """A model's reasoning."""
    cache_read: int
    """Sent to a model and read from the cache."""
    cache_write: int
    """Sent to a model and written to the cache."""
    cache_hit: float | None = None
    """The share of what was sent, input and the cache's both, that was read from the cache, from 0 to 1; None when
    nothing was sent."""


class ReportKind(Model):
    """What one kind of run cost in a month."""

    kind: SpendKind
    """The kind of run; the overseer's include dry runs."""
    runs: int
    """How many of its runs started in the month: for the overseer, its ticks."""
    cost_usd: float | None = None
    """What they cost, in US dollars; None when none reported a cost."""
    tokens: ReportTokens
    """Their tokens."""


class ReportOutside(Model):
    """What the runtime's sessions outside canopy cost in a month: the operator's own, and other workspaces' runs."""

    sessions: int
    """How many started in the month."""
    cost_usd: float | None = None
    """What they cost, in US dollars; None when none started."""
    tokens: ReportTokens
    """Their tokens."""


class ReportModel(Model):
    """What one model's replies cost in a month, over every kind of run, as each run's session says (DESIGN §13)."""

    model: str | None = None
    """As `provider/model`, as the runtime names it; None for the runs no session named a model for, in two rows by
    `unread`."""
    runs: int
    """How many runs it wrote a reply of: a run on two models counts under each."""
    replies: int
    """How many replies it wrote; 0 for the runs no session named a model for."""
    cost_usd: float | None = None
    """What the sessions priced those replies at, in US dollars; for the runs no session named a model for, what the
    runs reported, None when none did."""
    unread: bool = False
    """For a row of no model, whether canopy has yet to read its runs' sessions: running, not read yet, or a read that
    failed. False for the rest, read that named none, and for a model's row."""


class ReportTicket(Model):
    """A ticket the loop marked done as merged in a month, and what getting there took."""

    key: str
    """The ticket."""
    title: str | None = None
    """Its title, as the overseer named it; None before it did."""
    landed_at: datetime
    """When the loop marked it done, which the month it counts in goes by."""
    started_at: datetime | None = None
    """When its first worker run started; None for a ticket that landed with none."""
    iterations: int
    """Its worker runs, implement and resume, that started before it landed."""
    pr_comments: int
    """The comments on its PRs from people other than each PR's author, bots' apart: canopy posts as the author."""
    reviews: int
    """The reviews of its PRs from people other than each PR's author, bots' apart."""
    changes_requested: int
    """How many of those asked for changes."""
    cost_usd: float | None = None
    """What its runs and review runs that started before it landed cost, in US dollars; None when none reported."""
    hours_to_land: float | None = None
    """From its first worker run's start to its PRs' merge, `merged_at`, or to `landed_at` without it, in hours; None
    with no worker run."""
    review_wait_hours: float | None = None
    """From when its PR began waiting on a review, `awaiting_review_at`, or without it the end of its first worker run
    that ended `done`, to the first review after it, in hours; None with no start or no such review."""
    merged_at: datetime | None = None
    """When its PRs merged, as GitHub says, the latest of them; None where the reader kept no merge time, and its hours
    to land end at `landed_at` instead."""
    awaiting_review_at: datetime | None = None
    """When its PR began waiting on a review, as GitHub says: the first review asked for once it was ready, or when it
    was ready; None where the reader kept neither, and its review wait starts at its first worker run that ended
    `done` instead."""
    pull_requests: list[str]
    """Its PRs, by URL, in order: those its units hold and those its runs named."""


class ReportMonth(Model):
    """One local calendar month: what each kind of run cost, by model, and the tickets it landed."""

    month: str
    """The month, `YYYY-MM`, in the local time of the machine canopy runs on."""
    since: datetime
    """When it starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight on the next month's first day."""
    runs: int
    """How many runs of every kind started in it, a tick each for the overseer."""
    cost_usd: float | None = None
    """What every kind and the sessions outside canopy cost, dry runs included, as the budget counts a month, in US
    dollars; None when none reported."""
    tokens: ReportTokens
    """Every kind's tokens and the sessions outside canopy's, summed."""
    kinds: list[ReportKind]
    """A row per kind of run, in a fixed order: overseer, workers, plans, chores, reviews, tasks."""
    outside: ReportOutside
    """The runtime's sessions outside canopy, as the last read of them found."""
    models: list[ReportModel]
    """The costliest first, the runs no session named a model for last."""
    landed: list[ReportTicket]
    """The tickets the loop marked done as merged in it, the latest first."""
    closed: int
    """How many tickets the loop marked done as closed in it, without a merge."""
    pull_requests: int
    """How many PRs a run first named in it."""
    per_landed_usd: float | None = None
    """What canopy's runs cost over the tickets it landed, the sessions outside canopy left out, in US dollars; None
    with none landed, or no cost."""
    median_iterations: float | None = None
    """The median of its landed tickets' iterations; None with none landed."""
    median_pr_comments: float | None = None
    """The median of its landed tickets' PR comments; None with none landed."""
    median_hours_to_land: float | None = None
    """The median of its landed tickets' hours to land; None with none known."""
    median_review_wait_hours: float | None = None
    """The median of its landed tickets' waits for a first review, in hours; None with none known."""
    runs_ended: int
    """How many runs of every kind that started in it ended, as `canopy health` and the Health page count them."""
    failed: int
    """Of those, the ones that ended in a failed status."""
    failed_cost_usd: float | None = None
    """What the failed ones cost, in US dollars; None when none of them reported a cost."""
    heads: int
    """The PR heads first checked in it, as the CI page counts them."""
    green_first: int
    """Of those, the heads whose first run of every check was not red."""
    first_reviews: int
    """The first reviews that arrived in it on a PR with a start, timed on GitHub's clock, as the Reviews page counts
    them."""
    median_first_review_hours: float | None = None
    """Their median wait, in hours; None with none."""


class MonthlyReport(Model):
    """The last months, the current one so far included, as the reports page shows them."""

    months: list[ReportMonth]
    """Every month, oldest first, those with nothing in them included."""
    sessions_read_at: datetime | None = None
    """When `canopy loop` last read the runtime's sessions, which each month counts outside canopy; None when it never
    did, and they count none."""
