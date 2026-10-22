"""The API's shared types: the base model, and what more than one feature's routes serve (DESIGN §22).

The UI's TypeScript types are generated from the OpenAPI schema these produce, with each feature's own types in the
`*_schema.py` modules beside this one (ui/AGENTS.md). Change a model where it is defined, then regenerate the UI's types
with `npm run gen:api` in ui/. Every text field that comes from the journal is untrusted: the UI renders it as text,
never as HTML (DESIGN §22).

A model's docstring is its description in the schema, and so is each field's: the string below it. Every model and
field has one, and so does every named type; a test checks (test_serve.py). They reach the UI as JSDoc comments on
the generated types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

type RunState = Annotated[
    Literal["running", "blocked", "done", "failed", "stopped"],
    Field(
        description="A run's status, in five groups the UI colors (DESIGN §22). `blocked` asked a question; `failed` "
        "is every ending a human must look at (failed, crashed, unpushed, unknown, timeout); `stopped` is the "
        "operator's.",
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
type LimitKind = Annotated[
    Literal["implement", "resume", "review"],
    Field(description="What a limit counts: a unit's runs of one kind, or with `review` a PR's review runs."),
]
type StartStatus = Annotated[
    Literal["started", "stopped"],
    Field(description="Whether the operator's start of a ticket in canopy stands, or was stopped (DESIGN §22)."),
]


class Model(BaseModel):
    """The base of every API model, here and in each feature's `*_schema.py`: frozen, and refusing unknown fields."""

    # Fields with defaults are still always sent, so the generated TypeScript types mark them required. A field's
    # docstring is its description in the schema.
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_serialization_defaults_required=True,
        use_attribute_docstrings=True,
    )


class Meta(Model):
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


class Session(Model):
    """Whether this browser is signed in, and if so the token its writes must carry."""

    signed_in: bool
    """Whether the request carried a valid session cookie, or the server signs nobody in (mock data only)."""
    token: str | None = None
    """The token every write sends as `X-Canopy-Token`; None when signed out."""


class SignIn(Model):
    """The listener secret, as the operator gave it to the sign-in page."""

    secret: Annotated[str, Field(min_length=1, max_length=1000)]
    """The listener secret, from the file `canopy secret` wrote."""


class ErrorResponse(Model):
    """The body of an error that is not a guard's refusal or a validation error: a 401, a 403, a 404, or a 503."""

    detail: str
    """What went wrong, in words."""


class Refusal(Model):
    """A guard refused the operator's action: which guard, and why, as the CLI says it."""

    guard: str
    """The guard's name, as the CLI prints it: `bad_ref`, `not_confirmed`, `config_invalid`, ..."""
    reason: str
    """Why it refused, in the CLI's words."""


class RefusalResponse(Model):
    """A 409's body."""

    detail: Refusal
    """The guard that refused, and its reason."""


class AttentionItem(Model):
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


class RunsSince(Model):
    """What the runs did since a moment: the page's note on returning to a tab left hidden (ui/DESIGN.md)."""

    ended: int
    """How many runs ended since then, whatever their status."""
    prs_opened: int
    """How many PRs a run that ended since then named first: named by none of the runs that ended before."""


class RunActivity(Model):
    """A running run's latest tool call, as `_run` read it from the worker's events (DESIGN §8)."""

    tool: str
    """The tool's name, as the runtime names it: `bash`, `read`, an MCP server's tool."""
    did: str
    """What the call did, on one line: a shell call's command, else the runtime's title; empty when it gave neither."""
    at: datetime
    """When `_run` read it."""


class ServedModel(Model):
    """One model that wrote an agent run's replies, as the runtime's record of its session says (DESIGN §13)."""

    model: str
    """As `provider/model`, as the runtime names it."""
    replies: int
    """How many of the run's replies it wrote."""
    cost_usd: float
    """What those replies cost, in US dollars, as the runtime priced them."""


class ModelsServed(Model):
    """Which models served an agent run, read from its session after it ended (DESIGN §13, Each agent's model)."""

    status: Literal["running", "no_session", "unread", "found", "missing", "failed"]
    """`running` until it ends; `no_session` when it ended with none to read; `unread` until a tick reads it, a few
    each tick; `found`, its models in `models`; `missing` when the runtime no longer keeps its session; `failed` when
    the read failed, tried again a day later, a few times at most."""
    models: list[ServedModel] = []
    """When `found`, each model, the most costly first; empty for a session that made no model call."""
    error: str | None = None
    """When `failed`, canopy's words for why."""


class Run(Model):
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
    persona: str | None = None
    """The persona it ran in (DESIGN §31); None for a kind no persona reaches, or a run from before canopy recorded
    it."""
    persona_digest: str | None = None
    """The sha256 of the persona's text as its prompt carried it, in hex: two runs with different digests had
    different texts under one name."""
    models: ModelsServed | None = None
    """Which models served it, on its page and in the runs list; None where another page lists it."""


class TicketSummary(Model):
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


class Comment(Model):
    """Where a mirrored tracker comment came from (DESIGN §22, M19)."""

    id: str
    """The comment's id in the tracker."""
    author: str
    """Who wrote it, as the tracker names them: untrusted text."""
    at: str
    """When it was written, as the tracker gave the time."""
    truncated: bool
    """Whether its body was cut when it was mirrored."""


class Message(Model):
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


class Decision(Model):
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
    decider: Literal["overseer", "harness"] | None = None
    """Who made it: the overseer, through one of its verbs, or the harness on its own (DESIGN §37); None for one
    recorded before the journal said."""


class Limit(Model):
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


class CostTotal(Model):
    """What a subject's agent runs cost in all, as the agent runtime reported it (§13), however long ago they ran."""

    runs: int
    """How many worker runs it counts, a running one included."""
    reviews: int
    """How many review runs it counts, a running one included."""
    priced: int
    """How many of those runs and review runs reported a cost."""
    cost_usd: float | None = None
    """What they cost, in US dollars; None when none reported a cost."""


class Granted(Model):
    """What a grant recorded: one more run allowed, every earlier one still counted (D030). The next tick decides."""

    kind: LimitKind
    """The kind it allows one more of."""
    repo: str | None = None
    """The unit's repository, named or found; None for a PR's reviews."""
    runs: int
    """Its runs of the kind so far, unchanged by the grant."""
    limit: int
    """Its limit now, the grant counted."""


class ReplyRequest(Model):
    """A reply from the conversation's form, with the submission id the form drew when it was rendered."""

    body: Annotated[str, Field(max_length=20_000)]
    """The reply's text. Bounded again in code at 4000 characters, after stripping (DESIGN §22)."""
    submission: Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    """The id the form drew when it was rendered, sent again unchanged on a retry, so a retry records nothing new."""


class Replied(Model):
    """What a reply recorded: the message, the message it answers, and whether it was new."""

    message_id: int
    """The message the reply is."""
    answers: int | None = None
    """The question it answers, if it answers one."""
    new: bool
    """Whether it was recorded now, rather than by an earlier submission with the same id."""


class Tick(Model):
    """A tick, as `canopy status`'s first line shows the latest (DESIGN §14), with how many decisions it recorded."""

    id: int
    """The tick's id."""
    status: str
    """running, ok, skipped, canopy_unavailable, disk_low, overseer_failed, reconcile_failed, error, or abandoned"""
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


class TickDetail(Model):
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
    models: ModelsServed
    """Which models served its overseer."""


class LastTick(Model):
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


class Pause(Model):
    """The operator paused the loop (DESIGN §6): since when, and through which channel."""

    since: datetime
    """When the loop was paused."""
    channel: PauseChannel
    """How it was paused."""


type NoticeChannel = Annotated[Literal["cli", "web"], Field(description="How the operator set the notice.")]


class WorkerNotice(Model):
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


class MemoryTier(Model):
    """One tier of agent memory and what reads it (DESIGN §28), in the words every surface uses."""

    mode: MemoryModeName
    """Its mode."""
    words: str
    """Its mode in words: `off`, `recording`, or `in use`. No two modes share them."""
    band: str
    """What reads this tier, in a sentence that starts with its mode: `Recording only. ...` or `In use. ...`."""


class MemoryState(Model):
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


class Capacity(Model):
    """What may run at once, `[capacity]`: the limits the runs page counts what is running against (DESIGN §8)."""

    workers: int
    """`max_workers`: worker runs and review runs together (DESIGN §21)."""
    reviews: int
    """`max_reviews`: review runs, within `workers`; 0 turns reviews off."""
    chores: int
    """`max_chores`: chore runs, apart from `workers` (DESIGN §19); 0 turns chores off."""


class LoopState(Model):
    """Whether the loop is paused, the notice to workers in force, agent memory's tiers, and what may run at once.

    While paused, no tick starts until the operator resumes it; a tick running when paused finishes.
    """

    capacity: Capacity
    """What may run at once, from the config the loop serves."""
    paused: Pause | None = None
    """The pause; None when the loop is not paused."""
    notice: WorkerNotice | None = None
    """The notice to workers in force; None without one."""
    memory: MemoryState | None = None
    """Agent memory's tiers; None while both are off, when memory shows nowhere."""


class NoticeRequest(Model):
    """A notice to set, as `canopy notice TEXT --for DURATION` sets it, replacing the one in force."""

    text: Annotated[str, Field(max_length=4096)]
    """What to tell the workers. Bounded again in code at 1024 bytes, after stripping (DESIGN §8)."""
    minutes: Annotated[int | None, Field(ge=1, le=10080)] = None
    """How long it lasts, in minutes; four hours when None."""


class NoticeChanged(Model):
    """What setting or clearing a notice did, and the state it left."""

    already: bool
    """For a clear, whether no notice was in force, so nothing changed; always false for a set."""
    loop: LoopState
    """The state it left."""


class PauseChanged(Model):
    """What a pause or a resume did: whether the loop was already so, and the state it left."""

    already: bool
    """Whether the loop was already paused, or already not, so nothing changed."""
    loop: LoopState
    """The state it left."""


class ConfigReload(Model):
    """What asking the loop to read its config again found (DESIGN §6). It applies at once, or after a running tick."""

    changed: list[str]
    """Keys whose values differ from the config the loop runs on, as `section.key`; `workspace map` for the
    workspace file's repositories. Empty when the files say what the loop already runs on."""
    restart: list[str]
    """The changed keys that take effect only when the loop restarts: the web UI's listener."""
    after_tick: bool
    """A tick is running: it finishes on the config it started with, and the reload follows when it ends."""


class TickAsked(Model):
    """What asking the loop for a tick now found (DESIGN §6): it starts at once, or when a running tick ends."""

    after_tick: bool
    """A tick is running: the one asked for starts when it ends."""
