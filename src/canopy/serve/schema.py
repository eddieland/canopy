"""The API's types. The UI's TypeScript types are generated from the OpenAPI schema these produce (ui/AGENTS.md).

Change them here, then regenerate the UI's types with `npm run gen:api` in ui/. Every text field that comes from the
journal is untrusted: the UI renders it as text, never as HTML (DESIGN §22).

A model's docstring is its description in the schema, and so is each field's: the string below it. Every model and
field has one, and so does every named type; a test checks (test_serve.py). They reach the UI as JSDoc comments on
the generated types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

type RunState = Annotated[
    Literal["running", "blocked", "done", "failed", "stopped"],
    Field(
        description="A run's status, in five groups the UI colors (DESIGN §22). `blocked` asked a question; `failed` "
        "is every ending a human must look at (failed, crashed, unpushed, unknown, timeout); `stopped` is the "
        "operator's."
    ),
]
type MessageSource = Annotated[
    Literal["worker", "operator", "tracker", "canopy"],
    Field(description="Who wrote a message (DESIGN §22): `canopy` for a tick's note on the operator's messages."),
]
type MessageKind = Annotated[
    Literal["report", "question", "reply", "comment", "note"],
    Field(description="What a message is (DESIGN §22): a `note` is canopy's word on what a tick did."),
]
type GrantKind = Annotated[
    Literal["implement", "resume"],
    Field(description="A kind of run a ticket's unit is limited in, which `canopy grant` raises (DESIGN §8, §22)."),
]
type LimitKind = Annotated[
    Literal["implement", "resume", "review"],
    Field(description="What a limit counts: a unit's runs of one kind, or with `review` a PR's review runs."),
]
type StartStatus = Annotated[
    Literal["started", "stopped"],
    Field(description="Whether the operator's start of a ticket in canopy stands, or was stopped (DESIGN §22)."),
]
type WorktreeState = Annotated[
    Literal["working", "held", "dirty", "idle", "broken"],
    Field(
        description="A worktree's state, in five groups the UI colors (DESIGN §22). `working` is held by a run or "
        "review the journal shows running; `held` is leased or in use by anything else; `dirty` is unleased with "
        "uncommitted changes; `broken` is damaged, unverified, or a status canopy does not know."
    ),
]


class _Model(BaseModel):
    # Fields with defaults are still always sent, so the generated TypeScript types mark them required. A field's
    # docstring is its description in the schema.
    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True, use_attribute_docstrings=True
    )


class Meta(_Model):
    """The server itself: what it runs and whether its data is real."""

    version: str
    """canopy's version, as the installed package reports it."""
    build: str | None
    """The id of the UI build the server serves now, which index.html carries too; None when the UI is not built. A page
    whose own id differs was loaded from an older build, and reloading it fetches this one."""
    mock: bool
    """Whether the journal is seeded from fixtures (`python -m canopy.serve --mock`), not the operator's."""
    ticket_url: str | None = None
    """`tracker.ticket_url`: a ticket's page in the tracker, with `{key}` where its key goes; None when unset."""
    branch_urls: dict[str, str] = {}
    """Each repository's branch link template, by name: a branch's page on its host, with `{branch}` where its name
    goes, from `branch_url` or a GitHub `url`. A repository without one is left out."""
    workspace_root: str
    """The workspace's root, absolute: a path a page shows from it is joined to it to copy it whole."""


class Session(_Model):
    """Whether this browser is signed in, and if so the token its writes must carry."""

    signed_in: bool
    """Whether the request carried a valid session cookie, or the server signs nobody in (mock data only)."""
    token: str | None = None
    """The token every write sends as `X-Canopy-Token`; None when signed out."""


class SignIn(_Model):
    """The listener secret, as the operator gave it to the sign-in page."""

    secret: Annotated[str, Field(min_length=1, max_length=1000)]
    """The listener secret, from the file `canopy secret` wrote."""


class ErrorResponse(_Model):
    """The body of an error that is not a guard's refusal or a validation error: a 401, a 403, a 404, or a 503."""

    detail: str
    """What went wrong, in words."""


class Refusal(_Model):
    """A guard refused the operator's action: which guard, and why, as the CLI says it."""

    guard: str
    """The guard's name, as the CLI prints it: `bad_ref`, `not_confirmed`, `config_invalid`, ..."""
    reason: str
    """Why it refused, in the CLI's words."""


class RefusalResponse(_Model):
    """A 409's body."""

    detail: Refusal
    """The guard that refused, and its reason."""


class AttentionItem(_Model):
    """One item on the attention list (DESIGN §14): what needs the operator, and since when."""

    id: str
    """Stable across ticks and rewordings: the item's fingerprint."""
    subject: str
    """How the CLI names it: `PROJ-1`, `api`, `PROJ-1 (api)`, `chore:deps`."""
    ticket_key: str | None = None
    """The ticket it is about, when it is about one; a chore's and a repository's items have none."""
    ticket_title: str | None = None
    """That ticket's title, as the overseer named it (DESIGN §13); None until it does, or when it is about none."""
    chore: str | None = None
    """The chore it is about, when it is about one."""
    repo: str | None = None
    """The repository it is about, when it is about one."""
    reason: str
    """Why: `awaiting_reply`, `worker_failed`, ..., or a chore finding's id."""
    detail: str
    """What the operator should know, in the CLI's words: untrusted text."""
    since: datetime
    """When the unbroken run of ticks that recorded it began."""
    finding: bool = False
    """A chore's finding rather than a ticket's item."""
    pr: str | None = None
    """The PR it is about when no ticket owns it, such as a `review_limit` on a PR `review.query` found."""


class RunsSince(_Model):
    """What the runs did since a moment: the page's note on returning to a tab left hidden (ui/DESIGN.md)."""

    ended: int
    """How many runs ended since then, whatever their status."""
    prs_opened: int
    """How many PRs a run that ended since then named first: named by none of the runs that ended before."""


class RunActivity(_Model):
    """A running run's latest tool call, as `_run` read it from the worker's events (DESIGN §8)."""

    tool: str
    """The tool's name, as the runtime names it: `bash`, `read`, an MCP server's tool."""
    did: str
    """What the call did, on one line: a shell call's command, else the runtime's title; empty when it gave neither."""
    at: datetime
    """When `_run` read it."""


class Run(_Model):
    """One worker or split run (`run:ID`)."""

    id: int
    """The run's id."""
    ticket_key: str
    """The ticket it works."""
    ticket_title: str | None = None
    """The ticket's title, as the overseer named it (DESIGN §13); None until it does."""
    kind: str
    """implement | resume | split | plan, or fix-ci for a run from before a resume fixed CI (DESIGN §8)"""
    reasons: list[str] = []
    """Why a resume ran, as its dispatch named them: ci, review, reply, conflict, no_pr, retarget (DESIGN §8)."""
    status: str
    """The journal's status: running, done, blocked, failed, crashed, unpushed, unknown, timeout, stopped."""
    state: RunState
    """Its status, grouped as the UI colors it."""
    private: bool
    """Whether it works a ticket started in canopy, whose conversation never reaches the tracker."""
    ticket_stopped: bool = False
    """Whether the operator stopped its ticket (DESIGN §22): a question it asked then waits on nothing."""
    branch: str | None = None
    """The branch it works on."""
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""
    summary: str | None = None
    """The worker's summary or the harness's note, line breaks kept, cut at 300 characters."""
    prs: list[str] = []
    """The PRs its result names, each an https:// URL."""
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
    worktrees: list[str] = []
    """The worktrees a running run holds, from the workspace root when under it."""
    log_path: str
    """Where its log is: from the workspace root when under it, as a worktree's path is."""
    activity: RunActivity | None = None
    """While it runs, its worker's latest tool call; None before the first, for a template that prints no events, and
    once it ends."""


class TicketSummary(_Model):
    """A ticket as the tickets list shows it."""

    key: str
    """The ticket's key, as the tracker names it."""
    title: str | None = None
    """A short name the overseer gave it from the ticket's own title (DESIGN §13); None until it does."""
    private: bool
    """Started in canopy (DESIGN §22): its conversation never reaches the tracker."""
    start: StartStatus | None = None
    """Whether the operator's start of it stands; None when it was never started in canopy."""
    phase: str | None = None
    """The overseer's last derived phase, for display; never read as truth."""
    last_decision: str | None = None
    """The newest decision a tick recorded about it since it was forgotten: None means no tick has seen it."""
    done: bool
    """Whether the overseer marked it done."""
    branch: str | None = None
    """The branch its work is on."""
    active_at: datetime
    """The newest of: a message, a run starting or ending, a start or stop, a change to it, such as its phase."""
    latest_message_id: int | None = None
    """The newest message in its conversation, so a new message changes the list the stream sends."""
    awaiting: int | None = None
    """The question waiting on the operator's reply, on a started ticket."""
    running_run: int | None = None
    """The run working it now, if one is."""
    plan_waits: bool = False
    """Whether its newest plan waits on the operator: proposed, no planner at work, no changes asked (DESIGN §25)."""


class Unit(_Model):
    """A ticket's work in one repository: its PR and phase (DESIGN §18)."""

    repo: str | None = None
    """The repository, as the workspace names it."""
    pr_url: str | None = None
    """The URL of its PR, once it has one."""
    phase: str | None = None
    """The overseer's last derived phase for this unit, for display; never read as truth."""


class Comment(_Model):
    """Where a mirrored tracker comment came from (DESIGN §22, M19)."""

    id: str
    """The comment's id in the tracker."""
    author: str
    """Who wrote it, as the tracker names them: untrusted text."""
    at: str
    """When it was written, as the tracker gave the time."""
    truncated: bool
    """Whether its body was cut when it was mirrored."""


class Message(_Model):
    """One message in a ticket's conversation."""

    id: int
    """The message's id."""
    at: datetime
    """When the journal recorded it."""
    source: MessageSource
    """Who wrote it."""
    kind: MessageKind
    """What it is."""
    channel: str
    """How it reached the journal: run | cli | web | slack | tracker"""
    run_id: int | None = None
    """The run that wrote it, for a worker's message."""
    answers: int | None = None
    """The message a reply answers."""
    body: str
    """Its text, control characters dropped and line breaks kept: untrusted."""
    comment: Comment | None = None
    """The tracker comment it mirrors, for one that came from the tracker."""


class Decision(_Model):
    """One decision a tick recorded (DESIGN §6): the overseer's, or the harness's attention items and refusals."""

    id: int
    """The decision's id."""
    tick_id: int
    """The tick that recorded it."""
    at: datetime
    """When it was recorded."""
    subject: str
    """What it is about, as `canopy decisions` names it with a unit's repository added: `PROJ-1`, `PROJ-1 (api)`,
    `api`, `chore:deps`, `pr:URL`, or `-` for the whole tick."""
    ticket_key: str | None = None
    """The ticket it is about, when it is about one."""
    repo: str | None = None
    """The repository it is about, when it is about one."""
    chore: str | None = None
    """The chore it is about, when it is about one."""
    pr: str | None = None
    """The URL of the PR it is about, when it is about one."""
    action: str
    """dispatch:<kind> | wait | skip | done | mirror | attention:<reason> | refused:<guard>"""
    rationale: str
    """The overseer's text, untrusted: control characters dropped and line breaks kept. Bounded at 2000 characters
    when it was recorded."""


class Limit(_Model):
    """A limit `canopy grant` raises: a ticket's unit's runs of one kind, or a PR's review runs (DESIGN §22).

    Every run counts, however it ended (D030), so `runs` only grows; at `limit` the loop does no more of the kind until
    the operator grants more or raises the policy.
    """

    kind: LimitKind
    """What it counts."""
    repo: str | None = None
    """The unit's repository; for a review limit, the repository of the unit whose PR it is, if any."""
    pr_url: str | None = None
    """The PR, for a review limit."""
    runs: int
    """Its runs of the kind so far."""
    granted: int
    """The runs the operator granted it past the policy's limit."""
    limit: int
    """The most runs of the kind it may have: the policy's limit plus `granted`."""


class CostTotal(_Model):
    """What a subject's agent runs cost in all, as the agent runtime reported it (§13), however long ago they ran."""

    runs: int
    """How many worker and split runs it counts, a running one included."""
    reviews: int
    """How many review runs it counts, a running one included."""
    priced: int
    """How many of those runs and review runs reported a cost."""
    cost_usd: float | None = None
    """What they cost, in US dollars; None when none reported a cost."""


class TicketForget(_Model):
    """One time the operator forgot a ticket's work (DESIGN §22), and what it dropped."""

    at: datetime
    """When."""
    channel: str | None = None
    """How: `cli` or `web`. None, with `prs`, for a forget made before canopy recorded them."""
    run_id: int | None = None
    """The ticket's newest run then, if it had one."""
    message_id: int | None = None
    """The ticket's newest message then, if it had one: the messages up to it are from before the forget."""
    branch: str | None = None
    """The branch it dropped, the operator's to delete."""
    prs: list[str] | None = None
    """The URLs of the PRs it dropped, the operator's to close; None when not recorded."""


class TicketDetail(_Model):
    """One ticket: what `canopy show` prints, and the latest decisions about it."""

    ticket: TicketSummary
    """The ticket, as the tickets list shows it."""
    units: list[Unit]
    """Its work in each repository."""
    limits: list[Limit] = []
    """Each kind's limit in each repository it has had runs in, then the review limit of each of its units' PRs canopy
    has reviewed."""
    runs: list[Run]
    """Its latest runs, newest first."""
    messages: list[Message]
    """Its conversation: the latest 100 messages, oldest first."""
    forgets: list[TicketForget] = []
    """Each time the operator forgot its work (DESIGN §22), oldest first. The messages up to the latest one's are
    history the loop no longer reads, kept for the operator."""
    decisions: list[Decision]
    """The latest 20 decisions about it across ticks, newest first: why the loop did, or did not, work it."""
    cost: CostTotal
    """What every run of it and every review run naming it cost; not the overseer, whose ticks serve the workspace."""
    drafts: list[Draft] = []
    """Its own drafts (DESIGN §29), the comments its runs would have posted on it, the newest run's first; at most
    10."""


class PlanSummary(_Model):
    """One of a ticket's plans (DESIGN §25): its status and approval, never its text."""

    id: int
    """The plan's id, as `canopy show --plans` names it `plan:ID`."""
    run_id: int
    """The plan run that wrote it, whose id names its file."""
    status: Literal["proposed", "approved", "superseded"]
    """Waiting on the operator, approved, or replaced by a newer plan, a request for one, a skip, or a forget."""
    created_at: datetime
    """When the planner wrote it."""
    approved_at: datetime | None = None
    """When the operator approved it, the latest time; none if never."""
    approved_channel: str | None = None
    """How they approved it: `cli` or `web`."""


class PlanFile(_Model):
    """A plan as its file stands now, read bounded and never through a link (DESIGN §25, Where plans live)."""

    plan: PlanSummary
    """The plan the file is."""
    path: str
    """The file, under the state directory: the operator reads and edits it with their own tools too."""
    text: str | None = None
    """Its Markdown, or none when the file is not a plan any more: `problem` says why."""
    problem: str | None = None
    """Why it is not: missing, not a regular file, unreadable, not UTF-8, empty, or over the bound."""
    sha256: str | None = None
    """The file's SHA-256 now, whenever it could be read: what a save sends back, so an edit made elsewhere since is
    never overwritten unseen."""
    edited: bool
    """Whether it differs from what the planner wrote."""
    changed_since_approval: bool
    """For an approved plan, whether it differs from the text the operator approved, which then needs approving again
    before its implement (`plan_changed`)."""


class PlanReplyView(_Model):
    """A reply in a comment thread on a plan."""

    id: int
    """Its id, unique among the ticket's replies."""
    body: str
    """What it says."""
    at: datetime
    """When it was written."""


class PlanThreadView(_Model):
    """One of the operator's comments on a ticket's plan: a thread on a passage, with its replies (DESIGN §25)."""

    id: int
    """Its id, unique among the ticket's threads."""
    quote: str
    """The passage it is on, whitespace collapsed."""
    prefix: str
    """Up to 32 characters before the passage, the nearest last."""
    suffix: str
    """Up to 32 characters after it, the nearest first."""
    body: str
    """What the comment says."""
    at: datetime
    """When it was written."""
    resolved: bool
    """Whether the operator resolved it. A resolved thread is kept, and asks the planner for nothing."""
    replies: list[PlanReplyView]
    """Its replies, oldest first."""


class PlanTriage(_Model):
    """A ticket's triage before its plan (DESIGN §25, Triage before a plan): its run, how it ended, and its verdict."""

    run_id: int
    """The `needs-plan` run. A ticket is triaged at most once."""
    status: str
    """The run's status: running while it reads; done when it judged; else failed, timeout, unknown, crashed, or
    stopped, and the ticket is planned as if triage were off."""
    verdict: Literal["trivial", "plan"] | None = None
    """What a run that ended `done` judged; none while it runs or for one that ended any other way."""
    reason: str | None = None
    """Its one-sentence reason, or the harness's note for a run that judged nothing, on one line: model text written
    from the ticket, untrusted, which no worker reads."""
    waived: bool = False
    """Whether its waiver is in force, so the ticket's implement goes ahead unplanned: false once the operator asked
    for a plan or skipped it themselves, or forgot the ticket."""
    undoable: bool = False
    """Whether asking for a plan still undoes the waiver in force: its implement has not started, so the ticket has no
    branch. Once it has, asking is refused `bad_plan`."""
    at: datetime
    """When it ended, or when it started while it runs."""


class TicketPlans(_Model):
    """A ticket's plans: whether it needs one, the newest as its file stands, the earlier ones, and the comments."""

    needed: bool
    """Whether its implement waits on an approved plan, by its own setting or `policy.plan`."""
    setting: Literal["plan", "skip"] | None = None
    """The operator's own word for this ticket, which overrides the policy; none to follow it."""
    policy: Literal["off", "approve"]
    """`policy.plan`."""
    planning: int | None = None
    """The plan run writing a plan for it now, if one is: the plan verbs and a save refuse until it ends."""
    triage: PlanTriage | None = None
    """Its triage before a plan (DESIGN §25), if it has had one: running, the waiver it gave, or the one that left it
    to be planned. `needed` stays the policy's word; a waiver in force means it waits on no plan all the same."""
    changes_asked: datetime | None = None
    """When the operator asked for changes no planner has read yet, as the overseer reads it; none if they have not."""
    newest: PlanFile | None = None
    """The newest plan, as its file stands; none if it has had none."""
    plans: list[PlanSummary]
    """Every plan, oldest first, the newest included."""
    threads: list[PlanThreadView]
    """The operator's comments, oldest first: a thread is the ticket's, not one plan's, so it carries to the next."""


class ChoreRun(_Model):
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


class ChoreFinding(_Model):
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


class ChoreSpendWindow(_Model):
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


class ChoreSpend(_Model):
    """What one chore's runs cost in the last day and the last 30 days, read together."""

    day: ChoreSpendWindow
    """The last 24 hours."""
    month: ChoreSpendWindow
    """The last 30 days."""


class ChoreSummary(_Model):
    """A configured chore as `canopy status` lists it: its window, its runs, when it is next due, its open findings."""

    name: str
    """The chore's name, as `chore:NAME` names it."""
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


class ChoreDetail(_Model):
    """One chore: what `canopy show chore:NAME` prints."""

    chore: ChoreSummary
    """The chore, as the chores list shows it."""
    runs: list[ChoreRun]
    """Its latest 10 runs, newest first."""
    notes: list[Message]
    """The operator's notes its next run reads: the latest 10, oldest first."""


class ChoreRunFinding(_Model):
    """A finding as one chore run reported it (DESIGN §19)."""

    id: str
    """The finding's id, as the chore gave it: the same across runs that report it."""
    title: str
    """Its title, as the agent wrote it: untrusted text."""
    detail: str
    """Its detail, as the agent wrote it: untrusted text."""
    link: str | None = None
    """A URL the agent gave for it: untrusted."""


class ChoreRunDetail(_Model):
    """One chore run: its row as its chore's page lists it, and the whole of what it reported (DESIGN §19, §22)."""

    chore: str
    """The chore's name."""
    run: ChoreRun
    """The run, as its chore's page lists it."""
    summary: str | None = None
    """The agent's summary, line breaks kept and not cut: its result bounded it at 2000 characters."""
    note: str | None = None
    """Why the harness decided the run's status, when it did: a timeout, a crash, a result that did not validate."""
    findings: list[ChoreRunFinding] = []
    """An `ok` run's findings, as it listed them."""


class Started(_Model):
    """What a start did: whether it was already started, and a run already working it."""

    already: bool
    """Whether the ticket was already started, so nothing changed."""
    running_run: int | None = None
    """A run already working the ticket, if one is."""
    running_private: bool | None = None
    """Whether that run is private; a public one may still write to the ticket."""


class StopRequest(_Model):
    """A stop, and whether to end the running run now, as `canopy stop --now` does."""

    now: bool = False
    """End the run working the ticket now, rather than let it finish."""


class Stopped(_Model):
    """What a stop did: whether it was already stopped, the run still working it, and whether `now` ended that run."""

    already: bool
    """Whether the ticket was already stopped, so nothing changed."""
    running_run: int | None = None
    """A run still working the ticket, if one is."""
    ended: bool = False
    """Whether `now` ended that run."""


class ForgetRequest(_Model):
    """A forget, and the ticket's key as the operator typed it: the challenge, checked again in code (DESIGN §22)."""

    confirm: Annotated[str, Field(max_length=200)]
    """The ticket's key, typed by the operator; anything else is refused `not_confirmed`."""


class Forgot(_Model):
    """What a forget cleared: the ticket's branch and its units' PRs, which are the operator's to close and delete."""

    branch: str | None = None
    """The branch the ticket's work was on."""
    prs: list[str]
    """The URLs of its units' PRs."""


class GrantRequest(_Model):
    """A grant of one more run of a kind to one of a ticket's units, as `canopy grant KEY KIND --repo NAME` does."""

    kind: GrantKind
    """The kind of run to allow one more of."""
    repo: Annotated[str | None, Field(max_length=200)] = None
    """The unit's repository; may be left out when the ticket has had runs in one repository only."""


class Granted(_Model):
    """What a grant recorded: one more run allowed, every earlier one still counted (D030). The next tick decides."""

    kind: LimitKind
    """The kind it allows one more of."""
    repo: str | None = None
    """The unit's repository, named or found; None for a PR's reviews."""
    runs: int
    """Its runs of the kind so far, unchanged by the grant."""
    limit: int
    """Its limit now, the grant counted."""


class ReplyRequest(_Model):
    """A reply from the conversation's form, with the submission id the form drew when it was rendered."""

    body: Annotated[str, Field(max_length=20_000)]
    """The reply's text. Bounded again in code at 4000 characters, after stripping (DESIGN §22)."""
    submission: Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    """The id the form drew when it was rendered, sent again unchanged on a retry, so a retry records nothing new."""


class PlanAction(_Model):
    """The operator's word on a ticket's plan: `canopy plan KEY --approve`, `canopy plan KEY`, or `--skip`."""

    action: Literal["approve", "request", "skip"]
    """`approve` the newest plan as its file stands, `request` a new plan, or `skip` the plan."""


class PlanChanged(_Model):
    """What the operator's word on a plan did."""

    action: Literal["approve", "request", "skip"]
    """What was asked."""
    plan: int | None = None
    """The plan approved, for `approve`."""
    superseded: int | None = None
    """The plan a request or a skip superseded, if the ticket had one."""
    already: bool
    """Whether the ticket's setting already said so, and nothing was superseded."""
    waived: int | None = None
    """The triage run whose waiver a request undid, or a skip replaced with the operator's own (DESIGN §25)."""


class PlanSave(_Model):
    """The plan editor's Markdown, to write over the plan's file, and the file's hash as the editor read it."""

    markdown: Annotated[str, Field(max_length=100_000)]
    """The plan as edited. A plan is at most 100,000 characters (DESIGN §25)."""
    read_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    """The file's SHA-256 when the editor read it: a file changed since is refused, never overwritten unseen."""


class PlanSaved(_Model):
    """The plan's file as saved."""

    sha256: str
    """Its SHA-256 now: what the next save sends back."""
    size: int
    """Its size in bytes."""


class PlanCommentRequest(_Model):
    """A comment on a passage of a ticket's plan: the passage, the text either side of it, and what it says."""

    quote: Annotated[str, Field(min_length=1, max_length=4000)]
    """The passage, whitespace collapsed."""
    prefix: Annotated[str, Field(max_length=32)] = ""
    """Up to 32 characters before it."""
    suffix: Annotated[str, Field(max_length=32)] = ""
    """Up to 32 characters after it."""
    body: Annotated[str, Field(max_length=20_000)]
    """What it says. Bounded again in code at 4000 characters, after stripping."""


class PlanReplyRequest(_Model):
    """A reply in a comment thread on a plan."""

    body: Annotated[str, Field(max_length=20_000)]
    """What it says. Bounded again in code at 4000 characters, after stripping."""


class PlanAnchor(_Model):
    """A comment's passage, as its words and the text either side of them, each with its whitespace collapsed."""

    quote: Annotated[str, Field(min_length=1, max_length=4000)]
    """The passage."""
    prefix: Annotated[str, Field(max_length=32)] = ""
    """Up to 32 characters before it."""
    suffix: Annotated[str, Field(max_length=32)] = ""
    """Up to 32 characters after it."""


class PlanThreadChange(_Model):
    """A change to a comment thread on a plan: its comment's words, a reply's, or whether it is resolved."""

    body: Annotated[str, Field(max_length=20_000)] | None = None
    """New words for the comment, or with `reply` for that reply."""
    reply: int | None = None
    """The reply `body` is for; none for the comment itself."""
    resolved: bool | None = None
    """Resolve the thread, or reopen it; none to leave it."""
    anchor: PlanAnchor | None = None
    """The passage as it now stands, after an edit of the plan moved or changed its words; none to leave it."""


class PlanThreadDeleted(_Model):
    """A comment thread on a plan, deleted with its replies."""

    id: int
    """The thread deleted."""


class Replied(_Model):
    """What a reply recorded: the message, the message it answers, and whether it was new."""

    message_id: int
    """The message the reply is."""
    answers: int | None = None
    """The question it answers, if it answers one."""
    new: bool
    """Whether it was recorded now, rather than by an earlier submission with the same id."""


class ChoreTried(_Model):
    """What trying a chore started: a recorded run, going on in the background (DESIGN §19)."""

    chore: str
    """The chore's name."""
    run_id: int
    """The chore run the try is, running until its agent ends or its timeout."""


class DismissRequest(_Model):
    """A dismissal of one of a chore's open findings, by its id, or with `undo` the taking back of one (DESIGN §19)."""

    finding: Annotated[str, Field(max_length=200)]
    """The finding's id, as the chore reported it; checked again in code against the finding id's pattern."""
    undo: bool = False
    """Take the dismissal back, as `--undo` does: the finding is listed again."""


class Dismissed(_Model):
    """What a dismissal left: the finding, and whether it is now dismissed."""

    chore: str
    """The chore's name."""
    finding: str
    """The finding's id."""
    dismissed: bool
    """Whether it is now dismissed: false after an `undo`."""


class ReviewDismissRequest(_Model):
    """A dismissal of one of a review run's findings, by its number, or with `undo` the taking back of one."""

    finding: Annotated[int, Field(ge=1, le=20)]
    """The finding's number in the review, from 1."""
    undo: bool = False
    """Take the dismissal back, as `--undo` does."""


class ReviewDismissed(_Model):
    """What a dismissal of a review's finding left: the finding, and whether it is now dismissed."""

    run: int
    """The review run's id."""
    finding: int
    """The finding's number in the review, from 1."""
    dismissed: bool
    """Whether it is now dismissed: false after an `undo`."""


class ReviewSendRequest(_Model):
    """Some of a review run's findings to send to a worker, by number, with the submission id the form drew."""

    findings: Annotated[list[Annotated[int, Field(ge=1, le=20)]], Field(min_length=1, max_length=20)]
    """The findings' numbers in the review, from 1."""
    submission: Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    """The id the form drew when the findings were picked, sent again unchanged on a retry."""


class ReviewSent(_Model):
    """What sending a review's findings recorded: the operator message on the review's ticket that names them."""

    run: int
    """The review run's id."""
    findings: list[int]
    """The findings sent, by number."""
    ticket_key: str
    """The ticket the message went to."""
    message_id: int
    """The message, the operator's go-ahead on the findings."""
    new: bool
    """Whether it was recorded now, rather than by an earlier submission with the same id."""


class Process(_Model):
    """A process the pool found running in a worktree."""

    pid: int
    """Its process id."""
    name: str
    """Its name, control characters dropped."""


class ReviewHold(_Model):
    """A running review that holds a worktree (DESIGN §21)."""

    id: int
    """The review run's id."""
    pr_url: str
    """The URL of the PR it reviews."""
    started_at: datetime
    """When it started."""


class Worktree(_Model):
    """One slot of a pool, as the pool's `status` reports it, with what in the journal holds it."""

    name: str
    """The slot's name in its pool."""
    path: str
    """From the workspace root when under it, as a workspace's pools are; else whole."""
    status: str
    """The pool's own word: available, leased, in-use, dirty, damaged, or unverified; treehouse's also "you're here"."""
    state: WorktreeState
    """Its status, grouped as the UI colors it."""
    branch: str | None = None
    """The branch checked out, or for a detached run's slot, the run's branch."""
    detached: bool = False
    """Whether its HEAD is detached."""
    branch_error: str | None = None
    """Why the pool could not read the branch."""
    holder: str | None = None
    """Who holds its lease, as the pool names them."""
    leased_at: datetime | None = None
    """When its lease was taken."""
    run: Run | None = None
    """The running run holding this lease, matched by lease id."""
    review: ReviewHold | None = None
    """The running review holding this lease, matched by lease id."""
    note: str | None = None
    """Something the operator should know about this slot, in the CLI's words: a stale canopy lease, say."""
    processes: list[Process] = []
    """The processes running in it, at most 20."""


class Pool(_Model):
    """One repository's pool of worktrees, read when asked for."""

    repo: str
    """The repository, as the workspace names it."""
    size: int | None = None
    """The size `capacity` declares for it; None leaves it at the pool's bound: treehouse's `max_trees`, or 16 for
    canopy's (DESIGN §18)."""
    error: str | None = None
    """Why its worktrees could not be read: no clone, or the pool's read failed."""
    worktrees: list[Worktree] = []
    """Its slots."""


class Tick(_Model):
    """A tick, as `canopy status`'s first line shows the latest (DESIGN §14), with how many decisions it recorded."""

    id: int
    """The tick's id."""
    status: str
    """running | ok | skipped | canopy_unavailable | overseer_failed | reconcile_failed | abandoned"""
    dry_run: bool
    """Whether it was a dry run: it recorded decisions and acted on none."""
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""
    summary: str | None = None
    """The overseer's summary of the tick: untrusted text."""
    session_id: str | None = None
    """The overseer's session, when the runtime reported it (§13)."""
    cost_usd: float | None = None
    """What the overseer cost, in US dollars, when the runtime reported it (§13)."""
    new_tokens: int | None = None
    """The tokens the runtime reported the overseer's model took in or wrote anew, every kind but cache reads; None
    when it reported nothing."""
    peak_context: int | None = None
    """The most tokens one of the overseer's model calls was sent, from the cache or not; None when the runtime
    reported nothing, or recorded it before canopy kept it."""
    decisions: int = 0
    """How many decisions it recorded so far."""
    idle: bool | None = None
    """Whether `canopy loop` found it idle (DESIGN §6, Idle pacing); None on a tick no loop ran, and until the loop
    records it, just after the tick ends. Its change is sent on the stream, which marks the spend page stale."""
    woken_by: str | None = None
    """What ended the loop's wait before it: start | timer | gate | message | starts | grant | notice | run | key |
    web. None when `idle` is."""
    canopy_version: str | None = None
    """The version of canopy that ran it, and so recorded its decisions; None on a tick from before that was kept."""


class TickDetail(_Model):
    """One tick: what `canopy decisions ID` prints."""

    tick: Tick
    """The tick, as the ticks list shows it."""
    decisions: list[Decision]
    """Its decisions, in the order they were recorded."""
    output_path: str | None = None
    """Where the overseer's stdout and stderr are, from the workspace root, if the file exists. Its session's events
    are served as the tick's transcript, and its end as the tick's output (DESIGN §22)."""
    previous_id: int | None = None
    """The tick before it, dry runs included, or None on the first."""
    next_id: int | None = None
    """The tick after it, dry runs included, or None on the newest, until the next one starts."""


class TranscriptText(_Model):
    """A finished piece of the agent's text, or of its reasoning."""

    kind: Literal["text"] = "text"
    """What the entry is."""
    at: datetime | None = None
    """When the runtime reported it, if it said."""
    text: str
    """The text: untrusted."""
    reasoning: bool = False
    """Whether it is the model's reasoning rather than its answer."""
    cut: bool = False
    """Cut at the transcript's bound for one text."""
    call: int | None = None
    """The model call it came from, counted from 1, or None before the runtime started the first."""


class TranscriptTool(_Model):
    """One tool call, once it ended: its input as indented JSON, and its output, or its error when `error`."""

    kind: Literal["tool"] = "tool"
    """What the entry is."""
    at: datetime | None = None
    """When the runtime reported it, if it said."""
    tool: str
    """The tool's name."""
    status: Literal["completed", "error"]
    """How the call ended."""
    title: str | None = None
    """The runtime's one-line description of the call, such as the command's purpose or the file's path."""
    input: str
    """Its input, as indented JSON: untrusted."""
    output: str
    """Its output, or its error: untrusted."""
    duration_ms: int | None = None
    """How long it took, in milliseconds, if the runtime said."""
    cut: bool = False
    """Its input or output was cut at the transcript's bound for one."""
    call: int | None = None
    """The model call it came from, counted from 1, or None before the runtime started the first."""


class TranscriptTokens(_Model):
    """One model call's tokens by kind, as the runtime counted them."""

    input: int
    """Input tokens."""
    output: int
    """Output tokens."""
    reasoning: int
    """Reasoning tokens."""
    cache_read: int
    """Input tokens read from the cache."""
    cache_write: int
    """Input tokens written to the cache."""


class TranscriptStep(_Model):
    """One model call ended: why, and what it cost, when the runtime said."""

    kind: Literal["step"] = "step"
    """What the entry is."""
    at: datetime | None = None
    """When the runtime reported it, if it said."""
    reason: str | None = None
    """Why the call ended, in the runtime's word."""
    cost_usd: float | None = None
    """What it cost, in US dollars."""
    tokens: int | None = None
    """Every kind of token together."""
    split: TranscriptTokens | None = None
    """The tokens, each kind apart."""
    call: int | None = None
    """The model call it came from, counted from 1, or None before the runtime started the first."""


class TranscriptError(_Model):
    """The runtime reported an error in the session."""

    kind: Literal["error"] = "error"
    """What the entry is."""
    at: datetime | None = None
    """When the runtime reported it, if it said."""
    name: str
    """The error's name, as the runtime gave it."""
    message: str
    """The error's message: untrusted."""
    call: int | None = None
    """The model call it came from, counted from 1, or None before the runtime started the first."""


type TranscriptEntry = Annotated[
    TranscriptText | TranscriptTool | TranscriptStep | TranscriptError,
    Field(discriminator="kind", description="One entry of a transcript, told apart by its `kind`."),
]
type TranscriptStatus = Annotated[
    Literal["read", "no_session", "no_log"],
    Field(
        description="`read`: the log was read, whether or not it held any of the session's events yet (a running "
        "run's reach it when the run ends). `no_session`: the runtime reported no session (a template without "
        "`--format json`). `no_log`: the log is missing, a symlink, or not a regular file."
    ),
]


class TranscriptPrompt(_Model):
    """The message canopy gave the runtime to start the session (DESIGN §22).

    The first model call's input, but for the agent's definition and the runtime's own system prompt and tools, which
    nothing records.
    """

    text: str
    """The prompt as canopy rendered it, control characters dropped: untrusted in part, since it quotes tickets,
    comments, and PRs."""
    truncated: bool = False
    """It holds more than the bound read."""


class Transcript(_Model):
    """What a run's log or a tick's output holds of its session, read back from the events as printed (DESIGN §22).

    Agent output: untrusted, rendered as text, and bounded. `truncated` says a bound left something out; `unreadable`
    counts events that did not validate.
    """

    status: TranscriptStatus
    """Whether the log was read, and if not, why."""
    session_id: str | None = None
    """The runtime's session, if it reported one."""
    entries: list[TranscriptEntry] = []
    """The session's events, in order."""
    truncated: bool = False
    """A bound left something out."""
    unreadable: int = 0
    """How many events did not validate."""
    prompt: TranscriptPrompt | None = None
    """The session's prompt, kept beside the log, if canopy kept one and it could be read."""


class RawOutput(_Model):
    """The end of a tick's output or a run's log as written, the lines its transcript leaves out included (DESIGN §22).

    A tick's is its overseer's stdout, a `--- stderr ---` line, and its stderr; a run's, its setup commands' output and
    its worker's stdout, stderr, and exit, each under a `--- ... ---` line canopy writes. Agent output: untrusted,
    rendered as text, its control characters dropped. `truncated` says the file holds more than its last `text`, which
    starts at a whole line; `size` is the whole file's, in bytes.
    """

    status: Literal["read", "no_output"]
    """`read`: the file was read; a running tick's or run's holds what it has printed so far. `no_output`: it is
    missing (none kept, or its agent has not started), a symlink, or not a regular file."""
    text: str = ""
    """The end of the file, starting at a whole line."""
    size: int = 0
    """The whole file's size, in bytes."""
    truncated: bool = False
    """The file holds more than `text`."""


class LastTick(_Model):
    """The latest tick, or none before the first, and the newest message a tick has acknowledged."""

    tick: Tick | None = None
    """The latest tick; None before the first."""
    acknowledged: int | None = None
    """The newest message the latest `ok` tick read, which may be an earlier tick than `tick`: an operator message
    after it waits for the next tick, and the attention list is still from before it (§14). None before the first."""


type PauseChannel = Annotated[
    Literal["loop", "cli", "web"],
    Field(description="How the operator paused the loop. `loop` is the `p` key at the loop's terminal."),
]


class Pause(_Model):
    """The operator paused the loop (DESIGN §6): since when, and through which channel."""

    since: datetime
    """When the loop was paused."""
    channel: PauseChannel
    """How it was paused."""


type NoticeChannel = Annotated[Literal["cli", "web"], Field(description="How the operator set the notice.")]


class WorkerNotice(_Model):
    """The operator's notice to workers in force (`canopy notice`, DESIGN §8).

    Every run dispatched while it is in force hears it, and the overseer holds a failed check it explains.
    """

    text: str
    """What the operator told the workers: the operator's own words."""
    since: datetime
    """When it was set."""
    lapses_at: datetime
    """When it lapses, unless the operator clears it or sets another first."""
    channel: NoticeChannel
    """How it was set."""


type MemoryModeName = Annotated[
    Literal["off", "record", "use"],
    Field(description="A memory tier's mode (DESIGN §28): `record` writes and serves nothing; `use` serves too."),
]


class MemoryTier(_Model):
    """One tier of agent memory and what reads it (DESIGN §28), in the words every surface uses."""

    mode: MemoryModeName
    """Its mode."""
    words: str
    """Its mode in words: `off`, `recording`, or `in use`. No two modes share them."""
    band: str
    """What reads this tier, in a sentence that starts with its mode: `Recording only. ...` or `In use. ...`."""


class MemoryState(_Model):
    """Agent memory's tiers while one is on (DESIGN §28): the header's readout and each tier's mode."""

    readout: str
    """`memory: recording` while no tier is at `use`, `memory: in use` once one is."""
    tiers: str
    """Each tier's mode in words, as the readout's hover says it: `ticket notes: recording, lessons: off`."""
    ticket_notes: MemoryTier
    """Notes a ticket's runs write for its later runs."""
    lessons: MemoryTier
    """Lessons workers propose and the operator promotes, `memory.proposals`."""
    proposals_waiting: int
    """How many proposals wait on the operator to promote or reject them; 0 while proposals are off."""


class LoopState(_Model):
    """Whether the loop is paused, the notice to workers in force, and agent memory's tiers.

    While paused, no tick starts until the operator resumes it; a tick running when paused finishes.
    """

    paused: Pause | None = None
    """The pause; None when the loop is not paused."""
    notice: WorkerNotice | None = None
    """The notice to workers in force; None without one."""
    memory: MemoryState | None = None
    """Agent memory's tiers; None while both are off, when memory shows nowhere."""


type MemoryScopeName = Annotated[
    Literal["ticket", "proposal", "lesson"],
    Field(description="What a memory is: a ticket's note, a worker's proposal, or the operator's lesson."),
]
type MemoryStatusName = Annotated[
    Literal["active", "pending", "superseded", "invalid"],
    Field(description="Where a memory stands: in force, waiting on the operator, replaced, or no longer in force."),
]


class MemoryOrigin(_Model):
    """What a lesson was promoted from (DESIGN §28): a proposal, or a ticket's note, past every edit of the lesson."""

    id: int
    """The source's id."""
    scope: MemoryScopeName
    """What the source is."""
    ticket_key: str | None
    """The ticket whose run wrote it."""
    run_id: int | None
    """The run that wrote it."""


class MemoryEntry(_Model):
    """One note, proposal, or lesson (DESIGN §28). Its text is a worker's, or the operator's for a lesson."""

    id: int
    """Its id, as the CLI and a run's result name it."""
    scope: MemoryScopeName
    """What it is."""
    ticket_key: str | None
    """A note's ticket, or a proposal's source ticket; None for a lesson."""
    repo: str | None
    """The repository a proposal or lesson is about; None for every repository, and for a note."""
    key: str
    """Its key: lowercase words joined by hyphens."""
    text: str | None
    """What it says, untrusted and shown as plain text with hidden characters named; None once forgotten or purged."""
    status: MemoryStatusName
    """Where it stands."""
    why: str | None
    """The harness's words for its latest change of status, such as `superseded by note 41`."""
    run_id: int | None
    """The run that wrote it; None for a lesson."""
    head: str | None
    """The commit the run's branch was at when its worker ended, `repo@commit` each for a joint run."""
    created_at: datetime
    """When it was written."""
    use_count: int
    """How many runs said they relied on it."""
    last_used_at: datetime | None
    """When a run last said so; None if none has: read by no run."""
    used_by: list[int] = []
    """The latest runs that said they relied on it, newest first, at most five. A run from before canopy named them
    counts in `use_count` but is not here."""
    review_at: datetime | None
    """A lesson's next review."""
    wrong_at: datetime | None
    """When a run last reported a lesson wrong, until the operator renews it."""
    wrong_run_id: int | None
    """The run that reported it."""
    promoted_from: int | None
    """What a lesson was made from: the proposal or note it was promoted from, or the lesson it was edited from."""
    origin: MemoryOrigin | None = None
    """A lesson's source, as the CLI names it, past every edit; None for a note or a proposal, or a source no longer in
    the journal."""
    version: int = 1
    """Which version of its memory it is: 1 for one that replaced none, one more for each a lesson's edit or promote,
    or a note under the same key, replaced before it. `GET /api/memory/{id}/history` lists them."""
    edited: bool = False
    """Whether it is a lesson the operator made by editing the version before it."""
    private: bool = False
    """Whether the run that wrote it worked a private ticket: its text may hold what the operator kept off the
    tracker."""


class MemoryProposal(_Model):
    """A proposal waiting on the operator, with where it came from (DESIGN §28)."""

    entry: MemoryEntry
    """The proposal."""
    run_kind: str | None
    """The kind of the run that proposed it."""
    run_status: str | None
    """How that run ended."""
    private: bool
    """Whether that run was on a private ticket, whose text may hold what the operator kept off the tracker."""
    ticket_done: bool
    """Whether its ticket is marked done: its work merged or closed, as far as the journal knows."""
    expires_at: datetime
    """When it lapses unless the operator decides it, `PROPOSAL_DAYS` after it was written: the first tick after
    invalidates it."""


class MemoryDigest(_Model):
    """What a run would be served of one tier, as its prompt would carry it (DESIGN §28)."""

    text: str
    """The section, as plain text."""
    ids: list[int]
    """The memories in it."""
    left_out: int
    """How many the cap left out."""
    served: bool
    """True while its tier is at `use`: the next run gets it. False while recording: what `use` would serve."""


class TicketNotes(_Model):
    """One ticket's notes in force, counted, for the list across tickets; its page lists them (DESIGN §28)."""

    ticket_key: str
    """The ticket."""
    count: int
    """How many of its notes are in force."""
    used: int
    """How many of those a run said it relied on."""
    latest_at: datetime
    """When the newest of them was written."""
    title: str | None
    """The ticket's title, as the overseer named it; None while it has named none."""


class MemoryOverview(_Model):
    """Every tier's memory (DESIGN §28): the tickets with notes in force, the proposals waiting, and the lessons."""

    state: MemoryState | None
    """The tiers; None while both are off."""
    tickets: list[TicketNotes]
    """Every ticket with notes in force, counted, the one with the newest note first."""
    proposals: list[MemoryProposal]
    """The proposals waiting on the operator, oldest first."""
    lessons: list[MemoryEntry]
    """The lessons in force: any a run reported wrong first, then by review date, the one due first."""
    lessons_digest: MemoryDigest | None
    """What every run would be served of the lessons; None while proposals are off."""
    repos: list[str]
    """The workspace's repositories, by name: one a promoted lesson may be served to alone."""
    past_proposals: list[MemoryEntry] = []
    """With `history`, the proposals no longer pending, rejected, lapsed, promoted, or forgotten, the latest to leave
    first, at most 50; else none."""
    past_lessons: list[MemoryEntry] = []
    """With `history`, the lessons no longer in force, replaced or forgotten, the latest to leave first, at most 50;
    else none."""


class MemoryFound(_Model):
    """What `canopy memory search` finds as the operator (DESIGN §28, Search): every memory that keeps its text."""

    entries: list[MemoryEntry]
    """The memories whose key or text holds any of the words, best match first, at most 50."""


class TicketMemory(_Model):
    """One ticket's notes (DESIGN §28): every one its runs wrote, and what its next run would be served."""

    state: MemoryState | None
    """The tiers; None while both are off."""
    notes: list[MemoryEntry]
    """Every note of the ticket, in force or not, by key and newest first."""
    digest: MemoryDigest | None
    """What its next run would be served; None while ticket notes are off."""


class MemoryRefusal(_Model):
    """An entry a run sent that `_run` did not write, in the harness's words; never its text (DESIGN §28)."""

    field: str
    """The result field it was in: `notes` or `proposals`."""
    key: str | None
    """Its key, when it had a valid one."""
    why: str
    """Why it was refused."""


class RunMemoryModes(_Model):
    """The mode of each memory tier a run's prompt was rendered under: `off` for a tier its kind does not hear."""

    ticket_notes: MemoryModeName
    """Ticket notes' mode for this run."""
    lessons: MemoryModeName
    """Lessons' mode for this run."""


class RunMemory(_Model):
    """What a run wrote of agent memory, what was rendered into its prompt, and what it had refused (DESIGN §28)."""

    rendered: RunMemoryModes | None
    """The modes it was rendered under; None for a run rendered with memory off, which wrote and read nothing."""
    wrote: list[MemoryEntry]
    """What it wrote, in order."""
    read: list[MemoryEntry]
    """What was rendered into its prompt. Empty while recording: then nothing was served."""
    used: list[int] = []
    """The ids of what it read that it said it relied on, its `memory_used`."""
    wrong: list[int] = []
    """The ids of what it read that it said was wrong, its `memory_wrong`."""
    refused: list[MemoryRefusal]
    """What it sent that was not written."""


class PromoteRequest(_Model):
    """A promote, as `canopy memory promote ID [--text TEXT] [--repo NAME]` takes it (DESIGN §28)."""

    text: Annotated[str | None, Field(max_length=4000)] = None
    """The lesson in the operator's words; None keeps the source's own. Bounded again in code, as the CLI's is."""
    repo: Annotated[str | None, Field(max_length=200)] = None
    """The one repository whose runs are served the lesson; None keeps a proposal's, and a note's every one."""


class MemoryPromoted(_Model):
    """What a promote made: the lesson, what it came from, the lesson it superseded, and whether runs read it now."""

    lesson: MemoryEntry
    """The new lesson, the operator's."""
    source: MemoryEntry
    """The proposal or note it came from, as it was."""
    superseded: int | None
    """The lesson under the same key it replaced, if there was one."""
    served: bool
    """Whether runs are served lessons now, `memory.proposals` at `use`; False while recording."""
    private: bool
    """Whether its text is still a private ticket's run's own words, which may hold what the operator kept off the
    tracker: the warning `canopy memory promote` gives."""


class LessonEditRequest(_Model):
    """An edit, as `canopy memory edit ID [--text TEXT] [--repo NAME | --every-repo]` takes it (DESIGN §28)."""

    text: Annotated[str | None, Field(max_length=4000)] = None
    """The lesson's new words; None keeps its own. Bounded again in code, as the CLI's are."""
    repo: Annotated[str | None, Field(max_length=200)] = None
    """The one repository whose runs are served the lesson; None keeps the lesson's, unless `every_repo`."""
    every_repo: bool = False
    """Serve the lesson to runs in every repository; refused `bad_request` with `repo`."""


class MemoryEdited(_Model):
    """What an edit made: the lesson's new version, the one it replaced, and whether runs read it now."""

    lesson: MemoryEntry
    """The new version, in force under the key."""
    replaced: MemoryEntry
    """The version it replaced, as it is now: superseded, its text kept as the lesson's history."""
    served: bool
    """Whether runs are served lessons now, `memory.proposals` at `use`; False while recording."""


class MemoryHistory(_Model):
    """Every version of a lesson or a note, newest first (DESIGN §28): each edit of a lesson, each note under a key."""

    versions: list[MemoryEntry]
    """The versions, the newest first, each with its `version`."""


class MemoryRejected(_Model):
    """A proposal the operator rejected: no lesson is made of it."""

    id: int
    """The proposal's id."""


class MemoryRenewed(_Model):
    """A lesson the operator renewed: it comes up for review again later, and a run's report it is wrong is cleared."""

    id: int
    """The lesson's id."""
    review_at: datetime
    """When it is next due for review."""


class MemoryForgetRequest(_Model):
    """A forget, and the memory's ref as the operator typed it: the challenge, checked again in code (DESIGN §22)."""

    confirm: Annotated[str, Field(max_length=200)]
    """The memory's ref, `memory:42`, typed by the operator; anything else is refused `not_confirmed`."""


class MemoryForgotten(_Model):
    """A memory whose text a forget deleted: its row stays, without the text. A forgotten lesson is retired."""

    id: int
    """The memory's id."""
    scope: MemoryScopeName
    """What it was."""
    key: str
    """Its key."""
    checkpointed: bool
    """Whether the journal's write-ahead log was checkpointed after; False while a reader held it open, when the text
    may stay in the log until SQLite's next checkpoint."""


class NoticeRequest(_Model):
    """A notice to set, as `canopy notice TEXT --for DURATION` sets it, replacing the one in force."""

    text: Annotated[str, Field(max_length=4096)]
    """What to tell the workers. Bounded again in code at 1024 bytes, after stripping (DESIGN §8)."""
    minutes: Annotated[int | None, Field(ge=1, le=10080)] = None
    """How long it lasts, in minutes; four hours when None."""


class NoticeChanged(_Model):
    """What setting or clearing a notice did, and the state it left."""

    already: bool
    """For a clear, whether no notice was in force, so nothing changed; always false for a set."""
    loop: LoopState
    """The state it left."""


class PauseChanged(_Model):
    """What a pause or a resume did: whether the loop was already so, and the state it left."""

    already: bool
    """Whether the loop was already paused, or already not, so nothing changed."""
    loop: LoopState
    """The state it left."""


class ConfigReload(_Model):
    """What asking the loop to read its config again found (DESIGN §6). It applies at once, or after a running tick."""

    changed: list[str]
    """Keys whose values differ from the config the loop runs on, as `section.key`; `workspace map` for the
    workspace file's repositories. Empty when the files say what the loop already runs on."""
    restart: list[str]
    """The changed keys that take effect only when the loop restarts: the web UI's listener."""
    after_tick: bool
    """A tick is running: it finishes on the config it started with, and the reload follows when it ends."""


class TickAsked(_Model):
    """What asking the loop for a tick now found (DESIGN §6): it starts at once, or when a running tick ends."""

    after_tick: bool
    """A tick is running: the one asked for starts when it ends."""


class SpendWindow(_Model):
    """What the agent runtime reported spending in the last `hours` hours (DESIGN §13).

    Worker, split, chore, and review runs and each tick's overseer, by when they started.
    """

    since: datetime
    """When the window starts."""
    hours: int
    """How long the window is, in hours."""
    cost_usd: float | None = None
    """What it cost, in US dollars; None when nothing in the window reported a cost."""


class Spend(_Model):
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
        "`dry_run` a dry run, whatever the loop said of it."
    ),
]
type SpendKind = Annotated[
    Literal["overseer", "workers", "triage", "plans", "chores", "reviews"],
    Field(
        description="A kind of agent run: each tick's overseer, worker and split runs, triage runs before a plan "
        "(`needs-plan`, DESIGN §25), plan runs (`plan`, §25), chore runs, review runs."
    ),
]


class SpendCosts(_Model):
    """What each kind of agent run cost, in US dollars, as the runtime reported it (§13); None where none reported."""

    overseer: float | None = None
    """The live ticks' overseers."""
    idle: float | None = None
    """The part of `overseer` idle ticks spent."""
    dry_run: float | None = None
    """Dry runs' overseers, apart from `overseer`."""
    workers: float | None = None
    """Worker and split runs."""
    triage: float | None = None
    """Triage runs, which judge whether a ticket needs its plan (`needs-plan`, DESIGN §25)."""
    plans: float | None = None
    """Plan runs, which write a ticket's plan (`plan`, DESIGN §25): what a waived plan would have cost."""
    chores: float | None = None
    """Chore runs, the operator's tries included."""
    reviews: float | None = None
    """Review runs."""
    total: float | None = None
    """Everything, dry runs included, as the 24 hour and 30 day counters count it."""


class SpendDay(_Model):
    """One UTC day's costs."""

    day: str
    """The day, `YYYY-MM-DD`, in UTC."""
    costs: SpendCosts
    """What the runs that started on it cost."""
    done: int = 0
    """How many tickets the loop marked done on it."""


class SpendTicket(_Model):
    """What one ticket's own runs that started in the window cost, and whether it was marked done in the window."""

    key: str
    """The ticket."""
    title: str | None = None
    """Its title, as the overseer named it; None before it did."""
    runs: int
    """How many of its worker and split runs started in the window, a running one included."""
    reviews: int
    """How many review runs naming it started in the window."""
    cost_usd: float | None = None
    """What those cost, in US dollars; None when none reported a cost. Not the overseer's, which is no ticket's."""
    done: Literal["merged", "closed"] | None = None
    """How the loop marked it done in the window (DESIGN §7): its PRs merged, or the tracker closed it, which a
    tracker may do when its PR merges. None when it was not marked done in the window."""
    done_at: datetime | None = None
    """When it was marked done; None when it was not, in the window."""


class SpendPullRequest(_Model):
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


class SpendTool(_Model):
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


class SpendTicks(_Model):
    """How many ended ticks of the window are in a group, and what their overseers cost."""

    group: SpendGroup
    """The group."""
    ticks: int
    """How many ticks."""
    cost_usd: float | None = None
    """What their overseers cost; None when none reported a cost."""


class SpendWoken(_Model):
    """How many of the loop's live ticks one cause woke (`ticks.woken_by`, DESIGN §6), and what they cost."""

    by: str
    """What ended the wait before them: start | timer | gate | message | starts | grant | run | key"""
    ticks: int
    """How many ticks."""
    cost_usd: float | None = None
    """What their overseers cost; None when none reported a cost."""


class SpendUnpriced(_Model):
    """How many of a kind's ended runs in the window reported no cost, of how many."""

    kind: SpendKind
    """The kind of run."""
    runs: int
    """How many ended in the window."""
    unpriced: int
    """How many of them reported no cost."""


class SpendBreakdown(_Model):
    """What a window of whole UTC days cost, today's so far included, as `canopy spend` prints it (ROADMAP M33)."""

    since: datetime
    """When the window starts: midnight UTC on its first day."""
    days: int
    """How many days it spans."""
    per_day: list[SpendDay]
    """Every day in it, oldest first, those with nothing spent included."""
    totals: SpendCosts
    """The whole window's costs."""
    ticks: list[SpendTicks]
    """The ticks that ended in it, a row per group, in a fixed order: idle, busy, hand_run, not_ok, dry_run."""
    woken: list[SpendWoken]
    """The loop's live ticks by what woke them, the most common first."""
    unpriced: list[SpendUnpriced]
    """A row per kind of run, in a fixed order: overseer, workers, triage, plans, chores, reviews."""
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
    waived: int = 0
    """How many triage runs that started in the window waived their ticket's plan (DESIGN §25): the planner runs
    triage saved, to read against what it cost."""
    tickets: list[SpendTicket] = []
    """Each ticket with a run or review run that started in the window, or marked done in it, the costliest first."""
    pull_requests: list[SpendPullRequest] = []
    """Each PR a run that started in the window pushed to, or a review run of it started in it, the costliest first."""
    tools: list[SpendTool] = []
    """What each kind's tool calls returned, by tool, the most characters first: a row per kind and tool."""


type SearchSource = Annotated[
    Literal["ticket", "message", "chore_run", "decision", "tick"],
    Field(description="Where a search hit is (DESIGN §22, Search), in the order the search reads them."),
]


class SearchHit(_Model):
    """One row holding every word of a search, and where it opens."""

    source: SearchSource
    """What the row is."""
    at: datetime
    """The row's time: when it was recorded, started, or last active."""
    snippet: str
    """The field that matched, on one line, cut around its first match: untrusted text."""
    ticket_key: str | None = None
    """The ticket a hit is, or whose message or decision it is."""
    chore: str | None = None
    """The chore a run, note, or decision is about."""
    run_id: int | None = None
    """The run that reported a message, or a chore run's own id."""
    tick_id: int | None = None
    """A tick, or the tick that recorded a decision."""
    label: str | None = None
    """A fixed word: a message's kind (`note` for a chore's), a decision's action, a status, or a ticket's phase."""


class SearchResults(_Model):
    """A search: the words it looked for, its hits by source and newest first, and the sources that had more."""

    words: list[str]
    """The words it looked for, as it split the query."""
    hits: list[SearchHit]
    """Its hits, at most 20 a source, by source and newest first."""
    more: list[SearchSource]
    """The sources that held more hits than it returned."""


type ReviewVerdict = Annotated[Literal["clean", "findings"], Field(description="A review run's verdict (DESIGN §21).")]
type ReviewImpact = Annotated[
    Literal["low", "normal", "high"],
    Field(description="A change's impact, as the reviewer calls it: `low` as `review.low_impact` allows (DESIGN §21)."),
]
type FindingSeverity = Annotated[
    Literal["blocking", "major", "minor"], Field(description="How much a review finding matters (DESIGN §21).")
]
type DiffLineKind = Annotated[
    Literal["add", "del", "ctx"], Field(description="Whether a diff line is added, deleted, or context.")
]


class ReviewSummary(_Model):
    """One review run of a PR at a commit (DESIGN §21): canopy's own review, which is never on the PR (D114)."""

    id: int
    """The review run's id."""
    pr_url: str
    """The PR's URL as the overseer gave it: an opaque https:// string."""
    sha: str
    """The commit it reviewed."""
    ticket_key: str | None = None
    """The ticket the PR is for, when it is for one."""
    repo: str | None = None
    """The PR's repository, as the workspace names it."""
    status: str
    """The journal's status: running, done, failed, unknown, timeout, crashed."""
    state: RunState
    """`done` is done; every other ending is failed."""
    verdict: ReviewVerdict | None = None
    """Its verdict, once it reported one."""
    impact: ReviewImpact | None = None
    """The change's impact, once it reported one."""
    findings: int = 0
    """How many findings it reported."""
    worst: FindingSeverity | None = None
    """The severity of the worst finding it reported, which colors its verdict; None when it reported none."""
    worst_count: int = 0
    """How many of its findings are of the worst severity, which its verdict says in words (`3 findings, 1 major`)."""
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""
    cost_usd: float | None = None
    """What the agent runtime reported it cost, in US dollars; None when it reported nothing."""


class RequestedReview(_Model):
    """A PR the operator asked canopy to review that no review of is running yet: it waits on a tick (DESIGN §21)."""

    pr_url: str
    """The PR's URL, as the operator gave it: an opaque https:// string."""
    created_at: datetime
    """When the operator asked."""
    channel: str
    """Where they asked: `cli` or `web`."""


class ReviewFinding(_Model):
    """One finding, with where it falls in the diff: `file` indexes the diff's files, `line` is on the new side.

    Both are None when the diff does not show the file; `line` alone is None when it does not show the line.
    """

    severity: FindingSeverity
    """How much it matters."""
    title: str
    """Its title, as the reviewer wrote it: untrusted text."""
    location: str
    """Where it is, as the reviewer wrote it: `path:line`, say. Untrusted text."""
    detail: str
    """Its detail, as the reviewer wrote it: untrusted text."""
    file: int | None = None
    """The index in the diff's files of the file it is in; None when the diff does not show it."""
    line: int | None = None
    """The line it is on, on the new side; None when the diff does not show it."""
    dismissed: bool = False
    """Whether the operator dismissed it: no worker or tick acts on it (DESIGN §21)."""


class DiffLine(_Model):
    """One line of a hunk, with its number on each side it is on."""

    kind: DiffLineKind
    """Whether it is added, deleted, or context."""
    old: int | None = None
    """Its number on the old side; None for an added line."""
    new: int | None = None
    """Its number on the new side; None for a deleted line."""
    text: str
    """The line's text, without its `+`, `-`, or space: untrusted."""


class DiffHunk(_Model):
    """One hunk: what follows its `@@` ranges, such as a function's name, and its lines."""

    header: str
    """What follows the hunk's `@@` ranges, such as a function's name."""
    lines: list[DiffLine]
    """Its lines."""


class DiffFile(_Model):
    """One file the commit changes. `old_path` when it was renamed; `binary` when git shows no lines for it."""

    path: str
    """The file's path in the repository."""
    old_path: str | None = None
    """Its path before, when it was renamed."""
    binary: bool = False
    """Whether git shows no lines for it."""
    hunks: list[DiffHunk]
    """Its hunks."""


class ReviewDiff(_Model):
    """The reviewed commit's diff against where it leaves its base branch: the PR's own text, untrusted, and bounded."""

    files: list[DiffFile]
    """The files it changes."""
    truncated: bool = False
    """A bound left something out."""


class ReviewDetail(_Model):
    """One review run in full: its summary, findings, the diff they sit on, and the PR's other review runs."""

    review: ReviewSummary
    """The review run, as the reviews list shows it."""
    ticket_title: str | None = None
    """Its ticket's title, on one line; None when it has no ticket or the ticket no title."""
    summary: str | None = None
    """The reviewer's summary, line breaks kept: untrusted text."""
    note: str | None = None
    """The harness's note, when it decided the status."""
    base_branch: str | None = None
    """The branch the PR merges into."""
    findings: list[ReviewFinding]
    """Its findings, each anchored on the diff where it can be."""
    diff: ReviewDiff | None = None
    """None when there is no diff: a review from before diffs were kept, or one whose base could not be read."""
    sendable: bool = False
    """Whether its findings can be sent to a worker: a `done` review of one of the loop's own PRs (DESIGN §21)."""
    runs: list[ReviewSummary]
    """Every review run of the same PR, newest first, this one included."""


class ReviewRequest(_Model):
    """The operator's request to review a PR the loop does not own (DESIGN §21): open, or how it ended."""

    created_at: datetime
    """When the operator made it."""
    channel: str
    """Where it was made: `cli` or `web`."""
    ended_at: datetime | None = None
    """When it ended; None while it is open."""
    end_reason: Literal["reviewed", "merged", "closed", "unknown_repo", "stopped"] | None = None
    """Why it ended: a `done` review of the PR; the PR merged or closed first, or is in none of the workspace's
    repositories (the overseer's reading); or the operator stopped it. None while it is open."""
    notes: str | None = None
    """The operator's notes for the reviewer, which its prompt carries; None when the request has none."""


class ReviewRequestNotes(_Model):
    """A review request's notes, as `canopy start URL --review --notes TEXT` gives them."""

    notes: Annotated[str, Field(max_length=20_000)] = ""
    """What the reviewer should know or look at closely. Bounded again in code at 4000 characters, after stripping;
    blank is none, and leaves an open request's notes as they were."""


class ReviewRequested(_Model):
    """What a review request recorded: the open request, and whether it was already open or replaced another."""

    request: ReviewRequest
    """The PR's open request."""
    already: bool
    """Whether it was already open, so nothing new was recorded."""


class ReviewRequestStopped(_Model):
    """What stopping a review request did: the request as it was, and a review of the PR still running."""

    request: ReviewRequest
    """The request it ended, as `stopped`."""
    running_review: int | None = None
    """A review run of the PR still running, which finishes; None when none is."""


class PullRequest(_Model):
    """A PR the journal knows (DESIGN §22): one a ticket's unit records, or one canopy reviewed, whoever's it is."""

    url: str
    """The PR's URL: an opaque https:// string canopy never parses."""
    ticket_key: str | None = None
    """The ticket whose unit records it, or the one a review of it named; None for a PR no ticket owns."""
    ticket_title: str | None = None
    """That ticket's title, as the overseer named it; None until it does."""
    title: str | None = None
    """Its own title, as the worker that opened or last updated it reported it: untrusted text; None until one does."""
    repo: str | None = None
    """The PR's repository, as the workspace names it."""
    branch: str | None = None
    """The unit's branch; None for a PR no unit records."""
    phase: str | None = None
    """The unit's phase as the overseer last derived it, for display; None for a PR no unit records."""
    active_at: datetime
    """The newest of its ticket's last change, its review runs' starts and ends, and its review requests'."""
    running_run: int | None = None
    """A run of its ticket working now, whose page it opens."""
    reviews: int = 0
    """How many review runs it has had, however they ended."""
    latest_review: ReviewSummary | None = None
    """Its newest review run, or None when canopy has not reviewed it."""
    review_request: ReviewRequest | None = None
    """The operator's latest review request on it, open or ended; None when they never made one."""


class PullRequestDetail(_Model):
    """One PR: the runs that pushed to it, canopy's reviews of it, and the decisions that name it."""

    pull_request: PullRequest
    """The PR, as the PRs list shows it."""
    review_limit: Limit | None = None
    """Its review runs against its limit (DESIGN §21); None when canopy has never reviewed it."""
    runs: list[Run]
    """Its ticket's runs that reported this PR, and any of its ticket's runs working now, newest first; at most 20."""
    reviews: list[ReviewSummary]
    """Every review run of it, newest first; each opens its own page, with its findings on its diff."""
    decisions: list[Decision]
    """The latest 20 decisions naming it, across ticks, newest first."""
    cost: CostTotal
    """What every run it lists cost, not only the 20 shown, and every review run of it."""
    threads: bool = False
    """Whether canopy has read its review threads or holds a draft for it (DESIGN §29): what
    `GET /pull-request/threads` serves."""


class AttentionUpdated(_Model):
    """The attention list changed. The payload is the whole list."""

    type: Literal["attention.updated"] = "attention.updated"
    """What the event is."""
    items: list[AttentionItem]
    """The attention list, as `GET /attention` returns it."""


class RunsUpdated(_Model):
    """The runs changed. The payload is the whole list, as `GET /runs` returns it."""

    type: Literal["runs.updated"] = "runs.updated"
    """What the event is."""
    runs: list[Run]
    """The runs, as `GET /runs` returns them."""


class TicketsUpdated(_Model):
    """The tickets list changed. The payload is the whole list, as `GET /tickets` returns it."""

    type: Literal["tickets.updated"] = "tickets.updated"
    """What the event is."""
    tickets: list[TicketSummary]
    """The tickets, as `GET /tickets` returns them."""


class ChoresUpdated(_Model):
    """The chores changed: a run started or ended, or a note was added. The payload is the whole list."""

    type: Literal["chores.updated"] = "chores.updated"
    """What the event is."""
    chores: list[ChoreSummary]
    """The chores, as `GET /chores` returns them."""


class ReviewsUpdated(_Model):
    """The review runs changed: one started or ended. The payload is the whole list, as `GET /reviews` returns it."""

    type: Literal["reviews.updated"] = "reviews.updated"
    """What the event is."""
    reviews: list[ReviewSummary]
    """The latest review runs, as `GET /reviews` returns them."""


class ReviewRequestsUpdated(_Model):
    """The PRs waiting on a review changed: one was asked for or stopped, or its review started or failed. Whole."""

    type: Literal["review_requests.updated"] = "review_requests.updated"
    """What the event is."""
    requests: list[RequestedReview]
    """The open review requests no review is running for, as `GET /review-requests` returns them."""


class TicketChanged(_Model):
    """Something about one ticket changed: a page showing it reads it again."""

    type: Literal["ticket.changed"] = "ticket.changed"
    """What the event is."""
    key: str
    """The ticket's key."""


class SpendUpdated(_Model):
    """What a window cost changed. The payload is both windows, as `GET /spend` returns them."""

    type: Literal["spend.updated"] = "spend.updated"
    """What the event is."""
    spend: Spend
    """Both windows, as `GET /spend` returns them."""


class TickUpdated(_Model):
    """A tick started or ended. The payload is what `GET /tick` returns: the latest tick, and what was acknowledged."""

    type: Literal["tick.updated"] = "tick.updated"
    """What the event is."""
    tick: Tick | None = None
    """The latest tick; None before the first."""
    acknowledged: int | None = None
    """The newest message the latest `ok` tick read; None before the first."""


class LoopUpdated(_Model):
    """The loop was paused or resumed, or a notice to workers was set, cleared, or lapsed.

    The payload is what `GET /loop` returns.
    """

    type: Literal["loop.updated"] = "loop.updated"
    """What the event is."""
    paused: Pause | None = None
    """The pause; None when the loop is not paused."""
    notice: WorkerNotice | None = None
    """The notice to workers in force; None without one."""
    memory: MemoryState | None = None
    """Agent memory's tiers; None while both are off."""


class StreamEnding(_Model):
    """The server ends this stream now, its `stream_seconds` up: the page opens another at once, missing nothing."""

    type: Literal["stream.ending"] = "stream.ending"
    """What the event is."""


class StreamEvent(
    RootModel[
        Annotated[
            AttentionUpdated
            | RunsUpdated
            | TicketsUpdated
            | TicketChanged
            | ChoresUpdated
            | ReviewsUpdated
            | ReviewRequestsUpdated
            | SpendUpdated
            | TickUpdated
            | LoopUpdated
            | StreamEnding,
            Field(discriminator="type"),
        ]
    ]
):
    """One message on the event stream, told apart by its `type`. A named model so the UI's types get its name."""

    model_config = ConfigDict(frozen=True)


# Review replies (DESIGN §29)


type DraftKindName = Annotated[
    Literal["thread", "pr", "ticket"],
    Field(description="Where a draft goes: a reply on a review thread, its PR's one comment, or the ticket's."),
]
type DraftStatusName = Annotated[
    Literal["unchecked", "waiting", "refused", "superseded", "dropped", "sending", "unconfirmed", "staged", "sent"],
    Field(description="Where a draft stands (DESIGN §29)."),
]
type DraftStanceName = Annotated[
    Literal["changed", "declined", "answered"],
    Field(description="What a thread's draft says the run did: made the change, declined it, or answered a question."),
]
type ReactionName = Annotated[
    Literal["+1", "-1", "laugh", "confused", "heart", "hooray", "rocket", "eyes"],
    Field(description="A reaction a thread's draft stages on the comment it names, by GitHub's name for it."),
]


class Draft(_Model):
    """A comment a run drafted in place of posting it: a worker's text, untrusted until the operator sends it."""

    run: int
    """The run that drafted it."""
    number: int
    """Its number in the run's drafts, from 1: with the run, how the operator names it."""
    ticket_key: str
    """The ticket the run was for."""
    kind: DraftKindName
    """Where it goes."""
    status: DraftStatusName
    """Where it stands."""
    stance: DraftStanceName | None = None
    """For a thread's draft, what the run did about it."""
    comment_id: int | None = None
    """For a thread's draft, the review comment it names."""
    thread_id: str | None = None
    """For a thread's draft, the thread a read found that comment on; None until one did."""
    issue_url: str | None = None
    """For a ticket's draft, the issue it goes to, as the worker named it: shown for the operator to check."""
    why: str | None = None
    """The harness's words for its latest change of status, such as why it was refused."""
    text: str
    """Its text as it stands, the operator's latest edit or the run's own: plain text, never Markdown, here. Empty
    when it sends its reaction alone."""
    reaction: ReactionName | None = None
    """For a thread's draft, the reaction it stages on the comment it names, as it stands."""
    hash: str
    """The name of that text and reaction, which a send carries so what posts is what the operator read."""
    edited: bool
    """Whether the operator edited it."""
    supersedes_edited: bool
    """Whether a draft it superseded carried the operator's edits, which are not carried over."""
    sent_url: str | None = None
    """Once sent, the comment's or the review's URL on GitHub."""
    reacted: ReactionName | None = None
    """The reaction a send added on GitHub, which stays there though the rest of that send posted nothing."""
    created_at: datetime
    """When the run drafted it."""


class ThreadComment(_Model):
    """One comment on a PR's review thread, as canopy's reader last read it: someone else's text, untrusted."""

    id: int
    """GitHub's id for it."""
    author: str | None = None
    """Its author's login; None for a deleted account."""
    bot: bool
    """Whether GitHub says the author is a bot."""
    created_at: str | None = None
    """When it was posted, as GitHub says it."""
    body: str
    """Its body, cut as a mirrored comment is: plain text here."""
    url: str | None = None
    """Its URL on GitHub."""
    operator_sent: bool
    """Whether the operator sent it through canopy."""


class Thread(_Model):
    """A PR's review thread as last read, where it sits on the diff, and the drafts that answer it."""

    id: str
    """GitHub's node id for it."""
    path: str | None = None
    """The file it is on."""
    line: int | None = None
    """The line it is on, on its side; None for an outdated one."""
    side: Literal["left", "right"] | None = None
    """Which side of the diff the line is on."""
    outdated: bool
    """Whether GitHub says the code it is on has changed since."""
    resolved: bool
    """Whether it is resolved: that stays the reviewer's."""
    file: int | None = None
    """The index of its file in the diff, when the diff shows it."""
    diff_line: int | None = None
    """Its line on the diff's new side, when the diff shows it; None puts it under its file."""
    comments: list[ThreadComment]
    """Its comments, oldest first."""
    drafts: list[Draft]
    """The drafts that answer it, the newest run's last."""


class PullRequestThreads(_Model):
    """A PR's review threads on the diff of the latest run that kept one, and the drafts waiting to be sent."""

    url: str
    """The PR's URL."""
    review_replies: Literal["approve", "post"]
    """How workers' comments reach GitHub now (DESIGN §29)."""
    read_at: datetime | None = None
    """When canopy's reader last read the PR whole; None when it never has."""
    head_sha: str | None = None
    """The PR's head when it was read."""
    diff_run: int | None = None
    """The run whose diff this is, at its pushed head; None when no run kept one."""
    diff_head: str | None = None
    """The commit the diff was taken at, when it was kept."""
    diff: ReviewDiff | None = None
    """The diff; None when no run kept one."""
    threads: list[Thread]
    """Its review threads, in file order, then by line."""
    pr_drafts: list[Draft]
    """The drafts for the PR's own comment, which goes in the review's body."""
    unplaced: list[Draft]
    """Drafts no read has placed on a thread yet: unchecked, or refused for naming one the PR does not have."""


class DraftEditRequest(_Model):
    """An edit of a draft's words, as `canopy draft edit run:ID N --text TEXT [--react NAME | --no-react]` takes it."""

    text: Annotated[str, Field(max_length=8000)]
    """The draft's new text, empty beside a reaction to send it alone. Bounded again in code, as a run's draft is."""
    reaction: ReactionName | None
    """The reaction it stages, or None for none: given every time, so an edit never keeps one the page did not show."""


class DraftDropRequest(_Model):
    """A drop of a draft, or with `undo` the taking back of one."""

    undo: bool = False
    """Take the drop back, as `--undo` does."""


class DraftRef(_Model):
    """A draft the operator sends, and the hash of its text as the page showed it."""

    run: Annotated[int, Field(ge=1)]
    """The run that drafted it."""
    number: Annotated[int, Field(ge=1, le=30)]
    """Its number in the run's drafts."""
    hash: Annotated[str, Field(min_length=12, max_length=12, pattern=r"^[0-9a-f]+$")]
    """The hash of its text as the operator last saw it."""


class DraftSendRequest(_Model):
    """Drafts to send or stage together, as `canopy draft send` and `stage` take them: one PR's go as one review."""

    drafts: Annotated[list[DraftRef], Field(min_length=1, max_length=30)]
    """The drafts, each with the hash of the text the page showed."""


class DraftFailure(_Model):
    """A draft a send could not post, and why: it waits on the operator again."""

    draft: Draft
    """The draft, as it now stands."""
    why: str
    """Why nothing was posted, in the harness's words."""


class DraftsSent(_Model):
    """What a send or a stage did, as `canopy draft send` and `canopy draft stage` report it."""

    posted: list[Draft]
    """The drafts posted now."""
    already: list[Draft]
    """The drafts a send had posted before, which this one left alone."""
    failed: list[DraftFailure]
    """The drafts whose post failed, which wait again."""
    unconfirmed: list[Draft]
    """The drafts whose post ended without saying whether it submitted, until a read of the PR settles them."""
    staged: list[Draft]
    """The drafts a stage put in a pending review, for the operator to submit on GitHub."""
