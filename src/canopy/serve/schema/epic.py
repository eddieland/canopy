"""The API's types for epics (DESIGN §43): the list, an epic's page with its breakdown, and its plans.

Built on `schema.Model`, as every API type is (schema/__init__.py). An epic's text and replies are the operator's; its
plan, the outline read from it, and what its plan runs said are an agent's: untrusted text, which the UI renders as
text. The ids and the breakdown are data canopy reads from the plan, never an instruction (TRUST_MODEL T1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Message, Model, RunState

type EpicStanding = Annotated[
    Literal["queued", "planning", "proposed", "approved", "unplanned"],
    Field(
        description="Where an epic stands (DESIGN §43): `planning` while a plan run of it works; else its current "
        "plan's status, `proposed` while it waits on the operator, `approved` once they approved it; with neither, "
        "`queued` when the next tick starts a plan run, after its submission or a reply, and `unplanned` when its "
        "runs ended without a plan canopy kept and none starts until the operator replies, or ever, once it has had "
        "`policy.max_plan_attempts`.",
    ),
]
type OutlineSource = Annotated[
    Literal["approved", "proposed"],
    Field(
        description="Which plan an outline is read from: the latest the operator approved, or, while none is, the one "
        "waiting on them.",
    ),
]


class EpicSummary(Model):
    """An epic as the epics list shows it: its goal, where its plan reads, where it stands, and its breakdown."""

    id: int
    """The epic's id, as `epic:N` names it."""
    text: str
    """The operator's words, its goal: control characters dropped and line breaks kept."""
    repos: list[str]
    """The repositories its plan reads, by their names in the map, in the order the operator gave them."""
    project: str | None = None
    """The tracker project its breakdown's tickets are filed in; None for none."""
    tracker_epic: str | None = None
    """A tracker epic whose children are put to the operator as suggestions; None for none."""
    channel: str
    """Where the operator submitted it: cli or web."""
    submitted_at: datetime
    """When the operator submitted it."""
    standing: EpicStanding
    """Where it stands now."""
    members: int
    """How many tickets are its members now."""
    entries: int | None = None
    """How many entries its outline's breakdown holds; None when it has no plan, or its outline cannot be read."""
    entries_with_members: int = 0
    """How many of those entries have a member registered against them: the rest are left to file."""


class EpicRunLatest(Model):
    """A member ticket's newest worker run, as its row on the epic's page shows it."""

    id: int
    """The run's id, as `run:ID` names it."""
    kind: str
    """What it was dispatched to do: implement, resume, plan, and the like."""
    status: str
    """The journal's status."""
    state: RunState
    """What the UI colors it as."""


class EpicMember(Model):
    """A ticket the operator made a member of the epic (DESIGN §43), with what it fulfils and where its work stands."""

    key: str
    """The ticket's key."""
    title: str | None = None
    """The ticket's title as the overseer named it, on one line; None until it has, or for a ticket canopy has not
    seen."""
    entries: list[str]
    """The breakdown's entries it fulfils that the approved plan holds, `B<n>`, by number; empty for a member of no
    entry. While no approved plan can be read, every entry it was registered against."""
    dropped: list[str] = []
    """Entries it was registered against that the approved plan no longer holds: a later approval dropped them. It
    stays a member, of the entries left, until the operator registers it again or removes it."""
    added_at: datetime
    """When the operator made it a member."""
    added_channel: str
    """How they did: cli or web."""
    phase: str | None = None
    """Its ticket's phase, as the overseer last derived it, for display; None for a ticket canopy has not seen."""
    prs: list[str] = []
    """Its ticket's PRs, one per repository it has one in."""
    latest_run: EpicRunLatest | None = None
    """Its ticket's newest worker run; None before its first."""


class EpicId(Model):
    """A requirement or a contract of the plan's outline, with its text."""

    id: str
    """`R<n>` or `C<n>`: an id that never changes, nor is used again once an approved plan drops it."""
    text: str
    """What the plan says of it, whitespace collapsed: model text, untrusted."""


class EpicEntry(Model):
    """One entry of the plan's breakdown: a ticket the plan proposes, and the members that fulfil it."""

    id: str
    """`B<n>`, an id that never changes."""
    title: str
    """Its heading's title, on one line: model text, untrusted."""
    covers: list[str]
    """The requirements it covers, by number."""
    provides: list[str]
    """The contracts it provides, by number."""
    uses: list[str]
    """The contracts it uses, by number."""
    repos: list[str]
    """The repositories it works in, by name."""
    after: list[str]
    """The entries it comes after, by number."""
    trivial: str | None = None
    """Why the plan marks it trivial, which skips a member's own plan (DESIGN §43); None when it does not."""
    members: list[str] = []
    """The members registered against it, by when each was added; empty while it is left to file."""


class EpicOutline(Model):
    """What canopy reads of an epic's plan, its ids and breakdown (DESIGN §43): all of it, or why none of it reads."""

    source: OutlineSource
    """The plan it is read from."""
    plan_id: int
    """That plan's id."""
    run_id: int
    """The plan run that wrote it."""
    problem: str | None = None
    """Why its ids or breakdown cannot be read, or its file, or the approved copy, is not the plan: a repeated or
    malformed id, a missing section or field, a file gone. When set, the lists below are empty: a plan that does
    not read is never served as part of a map."""
    requirements: list[EpicId] = []
    """Its requirements, in the plan's order."""
    contracts: list[EpicId] = []
    """Its contracts, in the plan's order."""
    entries: list[EpicEntry] = []
    """Its breakdown's entries, in the plan's order."""


class EpicPlanSummary(Model):
    """One of an epic's plans (DESIGN §43): its status and approval, never its text."""

    id: int
    """The plan's id."""
    run_id: int
    """The plan run that wrote it, whose id names its file."""
    status: Literal["proposed", "approved", "superseded"]
    """Waiting on the operator, approved, or replaced by a newer plan."""
    created_at: datetime
    """When the planner wrote it."""
    approved_at: datetime | None = None
    """When the operator approved it; None if never."""
    approved_channel: str | None = None
    """How they approved it: cli or web."""


class EpicPlanRun(Model):
    """One run of the epic's planner (DESIGN §43): how it ended, what it said, and the plan it recorded."""

    id: int
    """The plan run's id."""
    status: str
    """The journal's status: running, done, blocked, failed, unknown, crashed, timeout, or stopped."""
    state: RunState
    """What the UI colors it as, as a ticket's run."""
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""
    summary: str | None = None
    """The harness's note, or else the planner's summary, line breaks kept, cut at 2000 characters: untrusted."""
    question: str | None = None
    """The question a `blocked` run asked the operator, line breaks kept: untrusted."""
    plan_id: int | None = None
    """The plan it recorded; None when it recorded none."""
    model: str | None = None
    """The model canopy asked the runtime for, as `provider/model[@variant]`; None for the runtime's default."""
    cost_usd: float | None = None
    """What the agent runtime reported it cost, in US dollars; None when it reported nothing."""


class EpicDetail(Model):
    """One epic: what `canopy show epic:N` prints, its breakdown read as data beside its members."""

    epic: EpicSummary
    """The epic, as the epics list shows it."""
    members: list[EpicMember]
    """Its members, by when each was added."""
    bound: int
    """`policy.max_epic_tickets`: the most members it may hold."""
    max_plan_attempts: int
    """`policy.max_plan_attempts`: the most plan runs it may have, a bound never reset."""
    runs: list[EpicPlanRun]
    """Every plan run of it, the oldest first."""
    messages: list[Message]
    """The operator's replies to it, the oldest first: each its next plan run's to read."""
    plan: EpicPlanSummary | None = None
    """Its current plan, the one waiting on the operator or approved; None while it has neither."""
    outline: EpicOutline | None = None
    """The approved plan's outline, or, while none is approved, the proposed plan's; None while it has neither."""


class EpicPlanFile(Model):
    """One of an epic's plans as its file stands now, read bounded and never through a link (DESIGN §43)."""

    plan: EpicPlanSummary
    """The plan the file is."""
    path: str
    """The file, under the state directory: the operator reads and edits it with their own tools too."""
    text: str | None = None
    """Its Markdown, or none when the file is not a plan any more: `problem` says why. Model text, untrusted."""
    problem: str | None = None
    """Why it is not: missing, not a regular file, unreadable, not UTF-8, empty, or over the bound."""
    sha256: str | None = None
    """The file's SHA-256 now, whenever it could be read."""
    edited: bool
    """Whether it differs from what the planner wrote."""
    changed_since_approval: bool
    """For an approved plan, whether the file differs from the text the operator approved, which stays the plan
    canopy reads, from its kept copy."""


class EpicPlans(Model):
    """An epic's plans, each as its file stands, as a ticket's plans are served."""

    epic_id: int
    """The epic they are plans of."""
    planning: int | None = None
    """The plan run writing its next plan now; None when none runs."""
    plans: list[EpicPlanFile]
    """Every plan it has had, the oldest first."""
