"""The API's types for the Connectors report (DESIGN §11, §30): how each source's runs ended, and how fresh it reads.

Read from `connector_runs`, a tick's runs and the loop's polls between ticks: each source now, as `canopy status` names
it, then its runs over the window by how they ended and how long they took, each day's that read less than asked, the
newest of those, and the lines canopy refused. Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type ConnectorKind = Annotated[
    Literal["tracker", "vcs", "artifacts", "slack"],
    Field(description="What a source reads (DESIGN §30): a tracker, a VCS host, an artifact store's feed, or Slack."),
]
type ConnectorStatus = Annotated[
    Literal["ok", "partial", "failed"],
    Field(
        description="How a run of a source ended: `ok` read everything it was asked, `partial` ended with its `end` "
        "line but read less, and `failed` recorded nothing: it did not start, timed out, or ended without its `end` "
        "line.",
    ),
]


class ConnectorsSource(Model):
    """A source that reads, as `canopy status` names it: its latest run, and how old its observations are."""

    name: str
    """The source's name, its `[connect.sources]` table's."""
    kind: ConnectorKind
    """What it reads."""
    run_id: int | None = None
    """Its latest run; None when it never ran."""
    tick_id: int | None = None
    """The tick that made its latest run; None for a poll between ticks, or when it never ran."""
    status: ConnectorStatus | None = None
    """How its latest run ended; None when it never ran."""
    ended_at: datetime | None = None
    """When its latest run ended; None when it never ran."""
    missed: str | None = None
    """The harness's words for what its latest run did not read; None for an `ok` run."""
    oldest_at: datetime | None = None
    """When the oldest observation of a subject its latest run asked about was made, or, for an `artifacts` source,
    when a run last read its feed to the end; None when there is none."""
    never: int
    """How many subjects its latest run asked about were never observed."""
    stale: bool
    """Whether an observation is older than `connect.max_age_minutes`, or a subject was never observed."""
    through: int | None = None
    """For an `artifacts` source, the change its feed has been read through; None for the others."""


class ConnectorsSourceRuns(Model):
    """One source's runs that started in the window: how they ended, how long they took, and the lines they read."""

    source: str
    """The source's name."""
    kind: ConnectorKind
    """What its newest run in the window read."""
    runs: int
    """Its runs."""
    ticks: int
    """Of those, the ones a tick made."""
    polls: int
    """Of those, the ones the loop's polls between ticks made, which raise nothing on the attention list."""
    ok: int
    """The ones that read everything they were asked."""
    partial: int
    """The ones that read less than asked, ending with their `end` line."""
    failed: int
    """The ones that recorded nothing."""
    median_minutes: float
    """Their median length, in minutes."""
    p90_minutes: float
    """The length nine in ten came in at or under, in minutes."""
    longest_minutes: float
    """The longest, in minutes."""
    limit_minutes: int | None = None
    """The source's `timeout_minutes` as configured now; None for a source no longer configured."""
    recorded: dict[str, int]
    """The lines its runs recorded, by kind of line."""
    refused: dict[str, int]
    """The lines canopy refused of its runs, by kind of line."""


class ConnectorsDay(Model):
    """One local day of the window: each source's runs that started in it and read less than they were asked."""

    day: str
    """The day, `YYYY-MM-DD`, in the local time of the machine canopy runs on."""
    start: datetime
    """When it starts: its local midnight, so a page can write it in its own zone."""
    short: list[int]
    """Each source's runs that ended `partial` or `failed`, in `ConnectorsReport.runs` order."""


class ConnectorsRun(Model):
    """A run that read less than it was asked."""

    id: int
    """The run's id."""
    source: str
    """The source it ran."""
    kind: ConnectorKind
    """What it read."""
    tick_id: int | None = None
    """The tick that made it; None for the loop's poll between ticks."""
    started_at: datetime
    """When it started."""
    minutes: float
    """How long it ran, in minutes."""
    status: ConnectorStatus
    """How it ended: `partial` or `failed`."""
    missed: str
    """The harness's words for what it did not read."""
    stderr: str
    """The last of what the connector wrote to stderr: its own words, so text, never markup; empty for none."""


class ConnectorsRefusal(Model):
    """One kind of line canopy refused of a source's runs in the window."""

    source: str
    """The source."""
    line: str
    """The kind of line, as the connectors' contract names it."""
    lines: int
    """How many lines of it were refused."""
    runs: int
    """In how many runs."""
    last_at: datetime
    """When the latest of those runs started."""


class ConnectorsPrevious(Model):
    """The window before a report's, as many days and ending where it starts: its headline figures alone."""

    since: datetime
    """When it starts: local midnight on its first day."""
    until: datetime
    """When it ends: where the report's window starts."""
    runs: int
    """The runs of every source that started in it."""
    short: int
    """Of those, the ones that read less than they were asked."""
    refused: int
    """The lines canopy refused of them."""


class ConnectorsReport(Model):
    """How each source's runs ended over the window, how long they took, and how fresh each source reads now."""

    days: int
    """How many local days the window holds, today's so far included."""
    since: datetime
    """When the window starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight after today."""
    max_age_minutes: int
    """`connect.max_age_minutes`: how old an observation may be before it is stale."""
    journal_days: int
    """`retention.journal_days`: how many days the journal keeps a run, each source's newest whatever its age; 0 keeps
    every run."""
    sources: list[ConnectorsSource]
    """Each source that reads, in the order a tick runs them."""
    runs: list[ConnectorsSourceRuns]
    """Each source that ran in the window, in the order a tick runs them, then any no longer configured, by name."""
    per_day: list[ConnectorsDay]
    """Every day of the window, oldest first."""
    newest: list[ConnectorsRun]
    """The newest runs that read less than asked, at most twenty, the newest first."""
    refusals: list[ConnectorsRefusal]
    """The kinds of line canopy refused, by source in `runs` order, then the most lines first."""
    previous: ConnectorsPrevious
    """The window before this one, as many days, for a page to say how this one compares."""
