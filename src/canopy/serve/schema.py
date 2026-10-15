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
    Literal["worker", "operator", "tracker"], Field(description="Who wrote a message (DESIGN §22).")
]
type MessageKind = Annotated[
    Literal["report", "question", "reply", "comment"], Field(description="What a message is (DESIGN §22).")
]
type GrantKind = Annotated[
    Literal["implement", "fix-ci", "resume"],
    Field(description="A kind of run a ticket's unit is limited in, which `canopy grant` raises (DESIGN §8, §22)."),
]
type LimitKind = Annotated[
    Literal["implement", "fix-ci", "resume", "review"],
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


class Run(_Model):
    """One worker or split run (`run:ID`)."""

    id: int
    """The run's id."""
    ticket_key: str
    """The ticket it works."""
    ticket_title: str | None = None
    """The ticket's title, as the overseer named it (DESIGN §13); None until it does."""
    kind: str
    """implement | fix-ci | resume | split"""
    status: str
    """The journal's status: running, done, blocked, failed, crashed, unpushed, unknown, timeout, stopped."""
    state: RunState
    """Its status, grouped as the UI colors it."""
    private: bool
    """Whether it works a ticket started in canopy, whose conversation never reaches the tracker."""
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
    """The newest of: a message, a run starting or ending, a start or stop, a tick seeing it."""
    latest_message_id: int | None = None
    """The newest message in its conversation, so a new message changes the list the stream sends."""
    awaiting: int | None = None
    """The question waiting on the operator's reply, on a started ticket."""
    running_run: int | None = None
    """The run working it now, if one is."""


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
    decisions: list[Decision]
    """The latest 20 decisions about it across ticks, newest first: why the loop did, or did not, work it."""
    cost: CostTotal
    """What every run of it and every review run naming it cost; not the overseer, whose ticks serve the workspace."""


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


class Replied(_Model):
    """What a reply recorded: the message, the message it answers, and whether it was new."""

    message_id: int
    """The message the reply is."""
    answers: int | None = None
    """The question it answers, if it answers one."""
    new: bool
    """Whether it was recorded now, rather than by an earlier submission with the same id."""


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
    """A process treehouse found running in a worktree."""

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
    """One slot of a treehouse pool, as `treehouse status --json` reports it, with what in the journal holds it."""

    name: str
    """The slot's name in its pool."""
    path: str
    """From the workspace root when under it, as a workspace's pools are; else whole."""
    status: str
    """treehouse's own word: available, leased, in-use, dirty, damaged, unverified, or "you're here"."""
    state: WorktreeState
    """Its status, grouped as the UI colors it."""
    branch: str | None = None
    """The branch checked out, or for a detached run's slot, the run's branch."""
    detached: bool = False
    """Whether its HEAD is detached."""
    branch_error: str | None = None
    """Why treehouse could not read the branch."""
    holder: str | None = None
    """Who holds its lease, as treehouse names them."""
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
    """One repository's treehouse pool, read when asked for."""

    repo: str
    """The repository, as the workspace names it."""
    size: int | None = None
    """The size `capacity` declares for it; None leaves it to treehouse's `max_trees` (DESIGN §18)."""
    error: str | None = None
    """Why its worktrees could not be read: no clone, or treehouse failed."""
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
    decisions: int = 0
    """How many decisions it recorded so far."""
    idle: bool | None = None
    """Whether `canopy loop` found it idle (DESIGN §6, Idle pacing); None on a tick no loop ran, and until the loop
    records it, just after the tick ends. Its change is sent on the stream, which marks the spend page stale."""
    woken_by: str | None = None
    """What ended the loop's wait before it: start | timer | gate | message | starts | grant | run | key. None when
    `idle` is."""


class TickDetail(_Model):
    """One tick: what `canopy decisions ID` prints."""

    tick: Tick
    """The tick, as the ticks list shows it."""
    decisions: list[Decision]
    """Its decisions, in the order they were recorded."""
    output_path: str | None = None
    """Where the overseer's stdout and stderr are, from the workspace root, if the file exists. Its session's events
    are served as the tick's transcript, and its end as the tick's output (DESIGN §22)."""


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


class TickOutput(_Model):
    """The end of a tick's overseer output as written: its stdout, a `--- stderr ---` line, its stderr (DESIGN §22).

    Agent output: untrusted, rendered as text, its control characters dropped. `truncated` says the file holds more
    than its last `text`, which starts at a whole line; `size` is the whole file's, in bytes.
    """

    status: Literal["read", "no_output"]
    """`read`: the file was read. `no_output`: it is missing (none kept, or the tick is still running), a symlink, or
    not a regular file."""
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


class LoopState(_Model):
    """Whether the loop is paused, and the notice to workers in force.

    While paused, no tick starts until the operator resumes it; a tick running when paused finishes.
    """

    paused: Pause | None = None
    """The pause; None when the loop is not paused."""
    notice: WorkerNotice | None = None
    """The notice to workers in force; None without one."""


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
    Literal["overseer", "workers", "chores", "reviews"],
    Field(description="A kind of agent run: each tick's overseer, worker and split runs, chore runs, review runs."),
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
    """A row per kind of run, in a fixed order: overseer, workers, chores, reviews."""
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
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""
    cost_usd: float | None = None
    """What the agent runtime reported it cost, in US dollars; None when it reported nothing."""


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


class PullRequest(_Model):
    """A PR the journal knows (DESIGN §22): one a ticket's unit records, or one canopy reviewed, whoever's it is."""

    url: str
    """The PR's URL: an opaque https:// string canopy never parses."""
    ticket_key: str | None = None
    """The ticket whose unit records it, or the one a review of it named; None for a PR no ticket owns."""
    ticket_title: str | None = None
    """That ticket's title, as the overseer named it; None until it does."""
    repo: str | None = None
    """The PR's repository, as the workspace names it."""
    branch: str | None = None
    """The unit's branch; None for a PR no unit records."""
    phase: str | None = None
    """The unit's phase as the overseer last derived it, for display; None for a PR no unit records."""
    active_at: datetime
    """The newest of its ticket's last sighting and its review runs' starts and ends."""
    running_run: int | None = None
    """A run of its ticket working now, whose page it opens."""
    reviews: int = 0
    """How many review runs it has had, however they ended."""
    latest_review: ReviewSummary | None = None
    """Its newest review run, or None when canopy has not reviewed it."""


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


class StreamEvent(
    RootModel[
        Annotated[
            AttentionUpdated
            | RunsUpdated
            | TicketsUpdated
            | TicketChanged
            | ChoresUpdated
            | SpendUpdated
            | TickUpdated
            | LoopUpdated,
            Field(discriminator="type"),
        ]
    ]
):
    """One message on the event stream, told apart by its `type`. A named model so the UI's types get its name."""

    model_config = ConfigDict(frozen=True)
