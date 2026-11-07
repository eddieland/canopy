"""The API's types for epics (DESIGN §43): the list, an epic's page with its breakdown, its plans, and their approval.

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
    Literal["queued", "planning", "proposed", "approved", "unplanned", "stopped"],
    Field(
        description="Where an epic stands (DESIGN §43): `planning` while a plan run of it works; else `stopped` once "
        "the operator stopped it, and no plan run of it starts again; else its current "
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
    stopped_at: datetime | None = None
    """When the operator stopped it; None while it is not stopped."""
    standing: EpicStanding
    """Where it stands now."""
    members: int
    """How many tickets are its members now."""
    planned: bool = False
    """Whether it has a plan, proposed or approved, whether or not its outline can be read: what tells a breakdown
    canopy cannot read from none at all, whatever the epic's standing."""
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
    changes_asked: datetime | None = None
    """When the operator last replied, asking for changes, while the next tick starts a plan run that reads it; None
    while no run is due for a reply: none was sent, a run took it, or the epic has had `policy.max_plan_attempts`."""


class EpicPlanApproval(Model):
    """The operator's approval of an epic's waiting plan, with its file's hash as the page read it."""

    read_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    """The plan file's SHA-256 when the page read it: a file changed since is refused, never approved unseen."""


class EpicPlanChange(Model):
    """What an approval changed from the plan approved before it, as `canopy plan epic:N --approve` lists it."""

    added: list[str]
    """The ids the new plan adds, by kind and number."""
    removed: list[str]
    """The ids it removes, never used again."""
    changed: list[str]
    """The ids whose text it changed."""


class EpicPlanApproved(Model):
    """What approving an epic's plan did: the plan approved, and what it changed from the one approved before."""

    plan: int
    """The plan approved."""
    run_id: int
    """The plan run that wrote it."""
    change: EpicPlanChange | None = None
    """What it changed from the plan approved before it; None for the epic's first approved plan."""


class EpicReplied(Model):
    """What a reply to an epic recorded, as `canopy reply epic:N` says: the message, and what starts its next plan."""

    message_id: int
    """The message the reply is."""
    new: bool
    """Whether it was recorded now, rather than by an earlier submission with the same id."""
    running_run: int | None = None
    """A plan run of the epic still working: the first tick after it ends starts the next. None: the next tick does."""
    plan_runs: int
    """How many plan runs the epic has had."""
    max_plan_attempts: int
    """`policy.max_plan_attempts`: once it has had that many, no plan run starts again, for this reply or any."""


class EpicStopped(Model):
    """What a stop did, as `canopy stop epic:N` says: no plan run of it starts again, and its members are left alone."""

    already: bool
    """Whether the epic was already stopped."""
    running_run: int | None = None
    """A plan run of it still working, if one is: it finishes unless `now` ended it."""
    ended: bool = False
    """Whether `now` ended that run."""
    kept: bool = False
    """Whether that run, ended, left a slot it held leased: it could not be tidied or returned."""


class EpicMemberAdd(Model):
    """A ticket the operator makes a member of an epic, or registers again, with the entries it fulfils."""

    key: str
    """The ticket's key, as the tracker names it: `PROJ-1`."""
    entries: Annotated[list[Annotated[str, Field(max_length=16)]], Field(max_length=200)]
    """The approved plan's breakdown entries it fulfils, `B1`, in place of any it had; none for a ticket the breakdown
    did not foresee, the only choice before a plan is approved."""


class EpicMemberAdded(Model):
    """What adding a ticket to an epic did, as `canopy epic add` says it."""

    key: str
    """The ticket."""
    added: bool
    """Whether it was made a member now, rather than being one already, its entries replaced."""
    entries: list[str]
    """The entries it is now registered against, by number; none for a member of no entry."""


class EpicMemberRemoved(Model):
    """What removing a ticket from an epic did, as `canopy epic remove` says it: the ticket and its work stay as is."""

    key: str
    """The ticket whose membership ended."""


class EpicSubmitRequest(Model):
    """An epic's goal, in the operator's words, and where its plan reads, as `canopy epic submit` takes them."""

    text: Annotated[str, Field(max_length=20_000)]
    """The epic's goal. Bounded again in code at 4000 characters, after stripping (DESIGN §43)."""
    repos: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=200)]
    """The repositories its plan reads, as each `--repo` names one. None only in a workspace of one repository."""
    project: Annotated[str, Field(max_length=200)] | None = None
    """The tracker project its tickets are filed in, as `--project` names it. None: it files no tickets."""
    tracker_epic: Annotated[str, Field(max_length=200)] | None = None
    """A tracker epic whose tickets are put to the operator as suggestions, as `--tracker-epic` names it; none is a
    member until the operator adds it."""


class EpicSubmitted(Model):
    """What a submission recorded: the epic, whose plan run the next tick starts, and the repositories it reads."""

    id: int
    """The epic's id, as `epic:N` names it."""
    repos: list[str]
    """The repositories its plan reads, as the map names them."""
