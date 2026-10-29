"""The API's types for chores (DESIGN §19): the chores list, a chore's and a chore run's pages, tries, and dismissals.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from canopy.serve.schema import Message, Model, ModelsServed, RunState


class ChoreRun(Model):
    """One run of a chore (DESIGN §19)."""

    id: int
    """The run's id."""
    status: str
    """The journal's status: running, ok, failed, unknown, timeout, crashed."""
    state: RunState
    """`ok` is `done`; every other ending is `failed`, as it raises `chore_failed`."""
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""
    summary: str | None = None
    """The harness's note or the agent's summary, line breaks kept, cut at 300 characters."""
    findings: int = 0
    """How many findings an `ok` run reported."""
    more_findings: int = 0
    """How many more an `ok` run found than it listed, past its chore's `max_findings`."""
    session_id: str | None = None
    """The runtime's session, for opening its transcript with the runtime's own tools."""
    cost_usd: float | None = None
    """What the agent runtime reported it cost, in US dollars; None when it reported nothing."""
    new_tokens: int | None = None
    """The tokens the runtime reported its model took in or wrote anew, every kind but cache reads; None when it
    reported nothing."""
    peak_context: int | None = None
    """The most tokens one of its model calls was sent, from the cache or not; None when the runtime reported nothing,
    or recorded it before canopy kept it."""
    log_path: str
    """Where its log is: from the workspace root when under it."""
    served: list[str] = []
    """The models its session names as having served it, as `provider/model`, the most costly first; empty until
    canopy reads the session, and when none did. The runs page's `?model=` keeps the runs one served."""


class ChoreFinding(Model):
    """An open finding: one the chore's latest `ok` run reported (DESIGN §19)."""

    id: str
    """The finding's id, as the chore gave it: the same across runs that report it."""
    title: str
    """Its title, as the agent wrote it: untrusted text."""
    detail: str
    """Its detail, as the agent wrote it: untrusted text."""
    link: str | None = None
    """A URL the agent gave for it: untrusted."""
    since: datetime
    """When the unbroken run of `ok` runs reporting it began."""
    dismissed: bool = False
    """Whether the operator dismissed it since then: it is off the attention list until it clears."""


class ChoreSpendWindow(Model):
    """What one chore's runs that started in the last `hours` hours cost, as the agent runtime reported it (§13).

    No start time, unlike `SpendWindow`: that moves with the clock, and would change the chores list on every read.
    """

    hours: int
    """How long the window is, in hours."""
    runs: int
    """How many of its runs started in the window, a running one included."""
    priced: int
    """How many of those reported a cost."""
    cost_usd: float | None = None
    """What they cost, in US dollars; None when none reported a cost."""
    mean_usd: float | None = None
    """What a run cost on average, over those that reported a cost; None when none did."""
    p99_usd: float | None = None
    """The 99th percentile of what a run cost, by nearest rank over those that reported a cost: the dearest run when
    fewer than 100 did. None when none did."""
    max_usd: float | None = None
    """What the dearest run cost, of those that reported a cost; None when none did."""


class ChoreSpend(Model):
    """What one chore's runs cost in the last day and the last 30 days, read together."""

    day: ChoreSpendWindow
    """The last 24 hours."""
    month: ChoreSpendWindow
    """The last 30 days."""


class ChoreSummary(Model):
    """A configured chore as `canopy status` lists it: its window, its runs, when it is next due, its open findings."""

    name: str
    """The chore's name, as `chore:NAME` names it."""
    title: str | None = None
    """The heading its prompt opens with, `# Dependency advisories`, on one line; None when it opens with none."""
    every_minutes: int
    """The least time between the starts of two runs, in minutes."""
    days: list[str] = []
    """The days of the week a run may start, checked in code; empty for every day."""
    hours: str | None = None
    """The hours a run may start, as `HH:MM-HH:MM`, checked in code; None for any hour."""
    timezone: str | None = None
    """The IANA zone `days` and `hours` are in; None for the local time of the machine the loop runs on."""
    when: str | None = None
    """The operator's words to the overseer on when a run is worth it."""
    running: ChoreRun | None = None
    """Its run that is running now, if one is."""
    latest: ChoreRun | None = None
    """Its most recent run that has ended."""
    due_at: datetime | None = None
    """The earliest time the harness lets a new run start; None, or a time already past, means now."""
    findings: list[ChoreFinding] = []
    """Its open findings."""
    max_findings: int
    """The most findings a run of it lists; the rest it only counts."""
    more_findings: int = 0
    """How many more its latest `ok` run found than it listed, past its `max_findings`: only counted, never recorded."""
    latest_note_id: int | None = None
    """The newest of the operator's notes to it, so a new note changes the list the stream sends."""
    spend: ChoreSpend
    """What its runs cost in the last day and the last 30 days."""


class ChoreDetail(Model):
    """One chore: what `canopy show chore:NAME` prints."""

    chore: ChoreSummary
    """The chore, as the chores list shows it."""
    runs: list[ChoreRun]
    """Its latest 10 runs, newest first."""
    notes: list[Message]
    """The operator's notes its next run reads: the latest 10, oldest first."""


class ChoreRunFinding(Model):
    """A finding as one chore run reported it (DESIGN §19)."""

    id: str
    """The finding's id, as the chore gave it: the same across runs that report it."""
    title: str
    """Its title, as the agent wrote it: untrusted text."""
    detail: str
    """Its detail, as the agent wrote it: untrusted text."""
    link: str | None = None
    """A URL the agent gave for it: untrusted."""


class ChoreRunDetail(Model):
    """One chore run: its row as its chore's page lists it, and the whole of what it reported (DESIGN §19, §22)."""

    chore: str
    """The chore's name."""
    title: str | None = None
    """The chore's title, as its summary gives it; None when its prompt opens with no heading, or it is no longer
    defined."""
    run: ChoreRun
    """The run, as its chore's page lists it."""
    summary: str | None = None
    """The agent's summary, line breaks kept and not cut: its result bounded it at 2000 characters."""
    note: str | None = None
    """Why the harness decided the run's status, when it did: a timeout, a crash, a result that did not validate."""
    findings: list[ChoreRunFinding] = []
    """An `ok` run's findings, as it listed them."""
    models: ModelsServed
    """Which models served it."""


class ChoreTried(Model):
    """What trying a chore started: a recorded run, going on in the background (DESIGN §19)."""

    chore: str
    """The chore's name."""
    run_id: int
    """The chore run the try is, running until its agent ends or its timeout."""


class DismissRequest(Model):
    """A dismissal of one of a chore's open findings, by its id, or with `undo` the taking back of one (DESIGN §19)."""

    finding: Annotated[str, Field(max_length=200)]
    """The finding's id, as the chore reported it; checked again in code against the finding id's pattern."""
    undo: bool = False
    """Take the dismissal back, as `--undo` does: the finding is listed again."""


class Dismissed(Model):
    """What a dismissal left: the finding, and whether it is now dismissed."""

    chore: str
    """The chore's name."""
    finding: str
    """The finding's id."""
    dismissed: bool
    """Whether it is now dismissed: false after an `undo`."""
