"""The API's types. The UI's TypeScript types are generated from the OpenAPI schema these produce (ui/AGENTS.md).

Change them here, then regenerate the UI's types with `npm run gen:api` in ui/. Every text field that comes from the
journal is untrusted: the UI renders it as text, never as HTML (DESIGN §22).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

# A run's status, in five groups the UI colors (DESIGN §22). `blocked` asked a question; `failed` is every ending a
# human must look at (failed, crashed, unpushed, unknown, timeout); `stopped` is the operator's.
type RunState = Literal["running", "blocked", "done", "failed", "stopped"]
# Who wrote a message, what it is, and how it reached the journal (DESIGN §22).
type MessageSource = Literal["worker", "operator", "tracker"]
type MessageKind = Literal["report", "question", "reply", "comment"]
type StartStatus = Literal["started", "stopped"]
# A worktree's state, in five groups the UI colors (DESIGN §22). `working` is held by a run or review the journal shows
# running; `held` is leased or in use by anything else; `dirty` is unleased with uncommitted changes; `broken` is
# damaged, unverified, or a status canopy does not know.
type WorktreeState = Literal["working", "held", "dirty", "idle", "broken"]


class _Model(BaseModel):
    # Fields with defaults are still always sent, so the generated TypeScript types mark them required.
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class Meta(_Model):
    """The server itself: what it runs and whether its data is real."""

    version: str
    mock: bool


class Session(_Model):
    """Whether this browser is signed in, and if so the token its writes must carry (D082)."""

    signed_in: bool
    token: str | None = None


class SignIn(_Model):
    """The listener secret, as the operator gave it to the sign-in page."""

    secret: Annotated[str, Field(min_length=1, max_length=1000)]


class Refusal(_Model):
    """A guard refused the operator's action: which guard, and why, as the CLI says it."""

    guard: str
    reason: str


class RefusalResponse(_Model):
    """A 409's body."""

    detail: Refusal


class AttentionItem(_Model):
    """One item on the attention list (DESIGN §14): what needs the operator, and since when."""

    # Stable across ticks and rewordings: the item's fingerprint.
    id: str
    # How the CLI names it: `PROJ-1`, `api`, `PROJ-1 (api)`, `chore:deps`.
    subject: str
    # The ticket it is about, when it is about one; a chore's and a repository's items have none.
    ticket_key: str | None = None
    chore: str | None = None
    repo: str | None = None
    # Why: `awaiting_reply`, `worker_failed`, ..., or a chore finding's id.
    reason: str
    detail: str
    since: datetime
    # A chore's finding rather than a ticket's item.
    finding: bool = False


class Run(_Model):
    """One worker or split run (`run:ID`)."""

    id: int
    ticket_key: str
    # implement | fix-ci | resume | split
    kind: str
    # The journal's status: running, done, blocked, failed, crashed, unpushed, unknown, timeout, stopped.
    status: str
    state: RunState
    private: bool
    branch: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    # The worker's summary or the harness's note, on one line.
    summary: str | None = None
    prs: list[str] = []
    # The runtime's session, for opening its transcript with the runtime's own tools.
    session_id: str | None = None
    cost_usd: float | None = None
    tokens: int | None = None
    # The worktrees a running run holds.
    worktrees: list[str] = []
    log_path: str


class TicketSummary(_Model):
    """A ticket as the tickets list shows it."""

    key: str
    # Started in canopy (DESIGN §22): its conversation never reaches the tracker.
    private: bool
    start: StartStatus | None = None
    # The overseer's last derived phase, for display; never read as truth.
    phase: str | None = None
    done: bool
    branch: str | None = None
    # The newest of: a message, a run starting or ending, a start or stop, a tick seeing it.
    active_at: datetime
    latest_message_id: int | None = None
    # The question waiting on the operator's reply, on a started ticket.
    awaiting: int | None = None
    running_run: int | None = None


class Unit(_Model):
    """A ticket's work in one repository: its PR and phase (DESIGN §18)."""

    repo: str | None = None
    pr_url: str | None = None
    phase: str | None = None


class Comment(_Model):
    """Where a mirrored tracker comment came from (DESIGN §22, M19)."""

    id: str
    author: str
    at: str
    truncated: bool


class Message(_Model):
    """One message in a ticket's conversation."""

    id: int
    at: datetime
    source: MessageSource
    kind: MessageKind
    # run | cli | web | slack | tracker
    channel: str
    run_id: int | None = None
    # The message a reply answers.
    answers: int | None = None
    body: str
    comment: Comment | None = None


class TicketDetail(_Model):
    """One ticket: what `canopy show` prints."""

    ticket: TicketSummary
    units: list[Unit]
    runs: list[Run]
    # The latest 100, oldest first.
    messages: list[Message]


class Started(_Model):
    """What a start did: whether it was already started, and a run already working it."""

    already: bool
    running_run: int | None = None
    # Whether that run is private; a public one may still write to the ticket.
    running_private: bool | None = None


class StopRequest(_Model):
    """A stop, and whether to end the running run now, as `canopy stop --now` does."""

    now: bool = False


class Stopped(_Model):
    """What a stop did: whether it was already stopped, the run still working it, and whether `now` ended that run."""

    already: bool
    running_run: int | None = None
    ended: bool = False


class ReplyRequest(_Model):
    """A reply from the conversation's form, with the submission id the form drew when it was rendered."""

    # Bounded again in code at 4000 characters, after stripping (DESIGN §22).
    body: Annotated[str, Field(max_length=20_000)]
    submission: Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class Replied(_Model):
    """What a reply recorded: the message, the message it answers, and whether it was new."""

    message_id: int
    answers: int | None = None
    new: bool


class Process(_Model):
    """A process treehouse found running in a worktree."""

    pid: int
    name: str


class ReviewHold(_Model):
    """A running review that holds a worktree (DESIGN §21)."""

    id: int
    pr_url: str
    started_at: datetime


class Worktree(_Model):
    """One slot of a treehouse pool, as `treehouse status --json` reports it, with what in the journal holds it."""

    name: str
    path: str
    # treehouse's own word: available, leased, in-use, dirty, damaged, unverified, or "you're here".
    status: str
    state: WorktreeState
    branch: str | None = None
    detached: bool = False
    # Why treehouse could not read the branch.
    branch_error: str | None = None
    holder: str | None = None
    leased_at: datetime | None = None
    # The running run or review holding this lease, matched by lease id.
    run: Run | None = None
    review: ReviewHold | None = None
    # Something the operator should know about this slot, in the CLI's words: a stale canopy lease, say.
    note: str | None = None
    processes: list[Process] = []


class Pool(_Model):
    """One repository's treehouse pool, read when asked for."""

    repo: str
    # The size `capacity` declares for it; None leaves it to treehouse's `max_trees` (DESIGN §18).
    size: int | None = None
    # Why its worktrees could not be read: no clone, or treehouse failed.
    error: str | None = None
    worktrees: list[Worktree] = []


class AttentionUpdated(_Model):
    """The attention list changed. The payload is the whole list."""

    type: Literal["attention.updated"] = "attention.updated"
    items: list[AttentionItem]


class RunsUpdated(_Model):
    """The runs changed. The payload is the whole list, as `GET /runs` returns it."""

    type: Literal["runs.updated"] = "runs.updated"
    runs: list[Run]


class TicketsUpdated(_Model):
    """The tickets list changed. The payload is the whole list, as `GET /tickets` returns it."""

    type: Literal["tickets.updated"] = "tickets.updated"
    tickets: list[TicketSummary]


class TicketChanged(_Model):
    """Something about one ticket changed: a page showing it reads it again."""

    type: Literal["ticket.changed"] = "ticket.changed"
    key: str


class StreamEvent(
    RootModel[Annotated[AttentionUpdated | RunsUpdated | TicketsUpdated | TicketChanged, Field(discriminator="type")]]
):
    """One message on the event stream, told apart by its `type`. A named model so the UI's types get its name."""

    model_config = ConfigDict(frozen=True)
