"""Typed journal rows: a frozen dataclass per table, and the queries that build them.

A query that returns a table's whole rows builds them through `fetch_all` or `fetch_one` with that table's row type,
so a misspelled column is a type error where it is read, and a query whose columns no longer match its row type fails
where it runs, not in a caller far from it. `tests/canopy/core/test_records.py` checks every row type against its
table after every migration: the same columns, in order, each with the type and nullability its column has.

A column holding one of `vocab`'s closed vocabularies is a field of that `StrEnum`, so the row carries the member and a
value the vocabulary does not hold is refused where the row is read, not where something later branches on it.

Every journal table has a row type. A query that reads some of a table's columns, or joins in another's, reads
`sqlite3.Row`.
"""

from __future__ import annotations

import sqlite3
import types
import typing
from collections.abc import Callable, Sequence
from dataclasses import Field, asdict, dataclass, fields
from enum import StrEnum
from typing import Any, ClassVar

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is read.
from canopy.core import sql
from canopy.core.vocab import (
    CheckConclusion,
    CheckStatus,
    ChoreRunStatus,
    ConnectorRunStatus,
    DraftAuthor,
    DraftKind,
    DraftStance,
    DraftStatus,
    MemoryAuthor,
    MemoryCited,
    MemoryMode,
    MemoryScope,
    MemoryStatus,
    MergeState,
    Phase,
    PlanSetting,
    PlanStatus,
    PoolKind,
    PrState,
    Reaction,
    ReplyMode,
    ResumeReason,
    ReviewItem,
    ReviewRunStatus,
    ReviewState,
    RunKind,
    RunStatus,
    SourceKind,
    StartStatus,
    TicketState,
    TickStatus,
)

# What a column's value is converted with, by its field's type.
_Convert = Callable[[object], object]
# The field types a column's value is checked against as is. A float field also takes an int, as REAL columns may.
_EXACT: dict[object, type] = {int: int, str: str, bytes: bytes}


class Row:
    """A row of one journal table: each subclass is a frozen dataclass whose fields are its columns, in order."""

    TABLE: ClassVar[str]
    # Set by @dataclass on each subclass; declared so `dataclasses.fields` accepts any row type.
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]


class RowError(Exception):
    """A query's columns, or a value in one, do not fit the row type it was read as."""


@dataclass(frozen=True)
class Tick(Row):
    """A tick (DESIGN §6): how it ended, what its overseer cost, what it read, and what the loop knew when it ran it."""

    TABLE: ClassVar[str] = "ticks"

    id: int
    started_at: str
    ended_at: str | None
    dry_run: bool
    status: TickStatus
    summary: str | None
    session_id: str | None
    cost_usd: float | None
    tokens_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_cache_read: int | None
    tokens_cache_write: int | None
    # The newest message, and the time, the tick had read up to; None before it read the journal.
    message_id: int | None
    read_at: str | None
    # Set by `canopy loop` alone (`db.set_tick_loop`): whether the tick was idle, and what started it.
    idle: bool | None
    woken_by: str | None
    tokens_peak_context: int | None
    # Whether the tick's state block told the overseer to run the tracker query; None on a tick from before that was
    # recorded, each of which was told to.
    query_due: bool | None
    tokens_first_call: int | None
    tokens_first_cache_write: int | None
    definitions_digest: str | None
    # The version of canopy that ran the tick; None on a tick from before that was recorded.
    canopy_version: str | None


@dataclass(frozen=True)
class Ticket(Row):
    """A ticket canopy has seen (DESIGN §6): its own phase, branch, and cursors, and where any forget left it."""

    TABLE: ClassVar[str] = "tickets"

    key: str
    # The workspace root.
    repo: str
    first_seen_at: str
    last_seen_at: str
    # The ticket's own last derived phase, for display only; never read as truth.
    phase: Phase | None
    # Fixed by its first implement, and the same in every unit.
    branch: str | None
    last_comment_id: str | None
    needs_human_since: str | None
    done: bool
    last_message_id: int | None
    last_mirrored_id: str | None
    # When the operator last forgot the ticket's work, and its newest run and message then (DESIGN §22).
    forgotten_at: str | None
    forgotten_run_id: int | None
    forgotten_message_id: int | None
    title: str | None
    # The ticket's own plan setting, overriding `policy.plan`; None when unset (DESIGN §25).
    plan_setting: PlanSetting | None
    #: When it last changed: made, or its phase, title, done flag, plan setting, or a unit's phase or PR set anew.
    changed_at: str


@dataclass(frozen=True)
class Forget(Row):
    """One time the operator forgot a ticket's work (DESIGN §22), and what it dropped; its row holds the latest."""

    TABLE: ClassVar[str] = "forgets"

    id: int
    ticket_key: str
    at: str
    # `cli` or `web`; None, with `prs`, for a forget made before forgets were recorded.
    channel: str | None
    # The ticket's newest run and message then: the loop reads only later ones.
    run_id: int | None
    message_id: int | None
    branch: str | None
    # A JSON array of its units' PR URLs.
    prs: str | None


@dataclass(frozen=True)
class Decision(Row):
    """A decision a tick recorded (DESIGN §6): the overseer's, a guard's refusal, or an attention item."""

    TABLE: ClassVar[str] = "decisions"

    id: int
    tick_id: int
    ticket_key: str | None
    action: str
    rationale: str
    created_at: str
    repo: str | None
    chore: str | None
    pr: str | None


@dataclass(frozen=True)
class ChoreRun(Row):
    """A run of a chore (DESIGN §19): the overseer's, or the operator's `canopy chore try`, and how it ended."""

    TABLE: ClassVar[str] = "chore_runs"

    id: int
    # None for a run the operator started with `canopy chore try`.
    tick_id: int | None
    chore: str
    pid: int | None
    agent_pid: int | None
    started_at: str
    ended_at: str | None
    status: ChoreRunStatus
    result_json: str | None
    log_path: str
    session_id: str | None
    cost_usd: float | None
    tokens_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_cache_read: int | None
    tokens_cache_write: int | None
    tokens_peak_context: int | None
    tokens_first_call: int | None
    tokens_first_cache_write: int | None
    definitions_digest: str | None


@dataclass(frozen=True)
class ReviewRun(Row):
    """A run of a reviewer on one PR at one commit (DESIGN §21): the slot it leased, and how it ended."""

    TABLE: ClassVar[str] = "review_runs"

    id: int
    tick_id: int
    pr_url: str
    sha: str
    ticket_key: str | None
    # The repository whose pool the slot came from; None in a workspace of one.
    repo: str | None
    slot_path: str | None
    lease_id: str | None
    lease_holder: str | None
    pid: int | None
    agent_pid: int | None
    started_at: str
    ended_at: str | None
    status: ReviewRunStatus
    result_json: str | None
    log_path: str
    session_id: str | None
    cost_usd: float | None
    tokens_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_cache_read: int | None
    tokens_cache_write: int | None
    base_branch: str | None
    purpose: str
    tokens_peak_context: int | None
    tokens_first_call: int | None
    tokens_first_cache_write: int | None
    definitions_digest: str | None
    pool: PoolKind


@dataclass(frozen=True)
class Start(Row):
    """The operator's start of a subject worked privately (DESIGN §22): the authorization, written only by them."""

    TABLE: ClassVar[str] = "starts"

    subject_kind: str
    subject_id: str
    status: StartStatus
    started_at: str
    # When the operator stopped it; None while it is started.
    stopped_at: str | None
    # The channel of the latest start or stop.
    channel: str


@dataclass(frozen=True)
class ReviewRequest(Row):
    """The operator's request to review a PR the loop does not own (DESIGN §21): open, or how it ended."""

    TABLE: ClassVar[str] = "review_requests"

    id: int
    pr_url: str
    created_at: str
    channel: str
    ended_at: str | None
    end_reason: str | None
    notes: str | None


@dataclass(frozen=True)
class PoolSlot(Row):
    """A slot of one of canopy's own pools (DESIGN §18): where it is, and its lease while it has one."""

    TABLE: ClassVar[str] = "slots"

    repo: str
    name: str
    path: str
    lease_id: str | None
    lease_holder: str | None
    leased_at: str | None
    base: str
    seeded: str


@dataclass(frozen=True)
class Plan(Row):
    """A plan a plan run wrote (DESIGN §25): its status, its file's hash as written, and its approval. No text."""

    TABLE: ClassVar[str] = "plans"

    id: int
    ticket_key: str
    run_id: int
    created_at: str
    status: PlanStatus
    # The file's SHA-256, hex, and its size in bytes, as the planner wrote it.
    sha256: str
    size: int
    # The file's SHA-256 when the operator approved it, their edits included; set with the time and the channel.
    approved_sha256: str | None
    approved_at: str | None
    approved_channel: str | None


@dataclass(frozen=True)
class TicketGrant(Row):
    """Runs the operator granted a ticket past its limit for a kind counted per ticket (DESIGN §22, §25)."""

    TABLE: ClassVar[str] = "ticket_grants"

    id: int
    ticket_key: str
    kind: RunKind
    runs: int
    granted_at: str


@dataclass(frozen=True)
class PlanThread(Row):
    """One of the operator's comments on a ticket's plan, anchored by its passage's words (DESIGN §25)."""

    TABLE: ClassVar[str] = "plan_threads"

    id: int
    ticket_key: str
    # The passage, and up to 32 characters either side of it, each with its whitespace collapsed.
    quote: str
    prefix: str
    suffix: str
    body: str
    created_at: str
    # When the operator resolved it; None while it is open.
    resolved_at: str | None


@dataclass(frozen=True)
class PlanReply(Row):
    """A reply in a plan's comment thread (DESIGN §25)."""

    TABLE: ClassVar[str] = "plan_replies"

    id: int
    thread_id: int
    body: str
    created_at: str


@dataclass(frozen=True)
class Memory(Row):
    """A ticket's note, a worker's proposal, or the operator's lesson (DESIGN §28). `body` is None once forgotten."""

    TABLE: ClassVar[str] = "memories"

    id: int
    scope: MemoryScope
    ticket_key: str | None
    repo: str | None
    key: str
    body: str | None
    status: MemoryStatus
    why: str | None
    author: MemoryAuthor
    run_id: int | None
    tick_id: int | None
    head: str | None
    supersedes: int | None
    promoted_from: int | None
    created_at: str
    approved_at: str | None
    last_used_at: str | None
    use_count: int
    review_at: str | None
    invalidated_at: str | None
    wrong_at: str | None
    wrong_run_id: int | None


@dataclass(frozen=True)
class RunMemory(Row):
    """What a run's prompt was rendered under, each memory tier's mode, and what `_run` refused of it (DESIGN §28)."""

    TABLE: ClassVar[str] = "run_memory"

    run_id: int
    ticket_notes: MemoryMode
    proposals: MemoryMode
    # A JSON list of the entries refused from the run's result, each the field, the key if valid, and why.
    refused: str


@dataclass(frozen=True)
class MemoryRead(Row):
    """A memory rendered into a run's prompt (DESIGN §28)."""

    TABLE: ClassVar[str] = "memory_reads"

    run_id: int
    memory_id: int
    # What the run said of it; None when it cited it in neither list, and for every read from before runs were named.
    cited: MemoryCited | None


@dataclass(frozen=True)
class RunReason(Row):
    """One reason a `resume` runs, as its dispatch named it (DESIGN §8)."""

    TABLE: ClassVar[str] = "run_reasons"

    run_id: int
    reason: ResumeReason


@dataclass(frozen=True)
class RunRead(Row):
    """A repository a run that leases no slot reads, by name, as its dispatch named it (DESIGN §25)."""

    TABLE: ClassVar[str] = "run_reads"

    run_id: int
    repo: str


@dataclass(frozen=True)
class PlanWaiver(Row):
    """A plan a triage run waived for its ticket, because its validated result judged the work trivial (DESIGN §25)."""

    TABLE: ClassVar[str] = "plan_waivers"

    id: int
    ticket_key: str
    #: The `needs-plan` run whose result waived it.
    run_id: int
    #: The triage's one-sentence reason, model text written from the ticket, shown to the operator and no worker.
    reason: str
    at: str


@dataclass(frozen=True)
class FollowUp(Row):
    """A follow-up ticket a public worker filed and its validated result reported, worked under its parent (§18)."""

    TABLE: ClassVar[str] = "follow_ups"

    #: The follow-up's own key, a ticket of the tracker's that may have no `tickets` row yet.
    key: str
    #: The ticket whose run filed it, whose authorization it is worked under.
    parent_key: str
    #: The run whose result reported it.
    run_id: int
    #: The repository the worker named for it, the only one it is dispatched in; None leaves that to the overseer.
    repo: str | None
    at: str


@dataclass(frozen=True)
class RunTool(Row):
    """What one tool's calls in an agent run put into its context (DESIGN §13): the run, by its table and id."""

    TABLE: ClassVar[str] = "run_tools"

    run_table: str
    run_id: int
    tool: str
    calls: int
    errors: int
    result_chars: int


@dataclass(frozen=True)
class ObservedPr(Row):
    """A PR as canopy's GitHub reader last read it whole (DESIGN §29)."""

    TABLE: ClassVar[str] = "observed_prs"

    url: str
    repository: str
    number: int
    head_sha: str | None
    base_ref: str | None
    state: PrState | None
    draft: bool
    mergeable: str | None
    author: str | None
    observed_at: str
    #: Its labels' names, as a JSON list.
    labels: str
    mergeable_state: MergeState | None


@dataclass(frozen=True)
class ObservedReview(Row):
    """A review or a review comment of a PR, as the reader last read it whole (DESIGN §29). Text, never authority."""

    TABLE: ClassVar[str] = "observed_reviews"

    pr_url: str
    item: ReviewItem
    id: int
    author: str | None
    bot: bool
    state: ReviewState | None
    created_at: str | None
    body: str
    url: str | None
    review_id: int | None
    thread_id: str | None
    path: str | None
    line: int | None
    side: str | None
    outdated: bool | None
    resolved: bool | None
    observed_at: str


@dataclass(frozen=True)
class ObservedTicket(Row):
    """A ticket as the tracker connector last read it whole (DESIGN §30). Text, never authority."""

    TABLE: ClassVar[str] = "observed_tickets"

    key: str
    title: str
    body: str
    state: TicketState
    #: Its labels, as a JSON list of `{"name", "added_at"}`.
    labels: str
    updated_at: str | None
    #: The keys it names as blocking it, as a JSON list.
    blockers: str
    observed_at: str


@dataclass(frozen=True)
class ObservedComment(Row):
    """A tracker comment as the tracker connector first read it (DESIGN §30). Text, never authority."""

    TABLE: ClassVar[str] = "observed_comments"

    ticket: str
    id: str
    author: str
    commented_at: str
    #: The comment's text, cut at the mirror's length.
    body: str
    truncated: bool
    #: `worker` when it carries the workers' marks (D069), else `tracker`.
    source: str
    observed_at: str


@dataclass(frozen=True)
class ObservedBranch(Row):
    """A branch under the branch prefix, as the `vcs` connector last read its repository whole (DESIGN §30)."""

    TABLE: ClassVar[str] = "observed_branches"

    repository: str
    name: str
    head_sha: str
    observed_at: str


@dataclass(frozen=True)
class ObservedCheck(Row):
    """A named CI context at a PR's head, as the `vcs` connector last read the PR whole (DESIGN §30)."""

    TABLE: ClassVar[str] = "observed_checks"

    pr_url: str
    name: str
    head_sha: str
    status: CheckStatus
    conclusion: CheckConclusion | None
    run_id: int | None
    url: str | None
    observed_at: str


@dataclass(frozen=True)
class ConnectorRun(Row):
    """One run of a source (DESIGN §30): what it was asked, how it ended, and what it read."""

    TABLE: ClassVar[str] = "connector_runs"

    id: int
    #: The tick that made it; None for the loop's poll between ticks (DESIGN §6).
    tick_id: int | None
    source: str
    kind: SourceKind
    started_at: str
    ended_at: str
    status: ConnectorRunStatus
    #: What it was sent, as JSON.
    request: str
    #: The lines it recorded of each kind, as a JSON object.
    recorded: str
    #: The lines it refused of each kind, as a JSON object.
    refused: str
    #: The harness's words for what it did not read; None for an `ok` run.
    missed: str | None
    #: The last of its stderr.
    stderr: str
    #: The query's result, the keys in order, as a JSON list, when it read the query to the end.
    query_result: str | None
    #: The review query's result, the URLs in order, as a JSON list, when it read it to the end.
    review_query_result: str | None


@dataclass(frozen=True)
class Draft(Row):
    """A comment a run would have posted, waiting on the operator to send, edit, or drop it (DESIGN §29)."""

    TABLE: ClassVar[str] = "drafts"

    id: int
    run_id: int
    number: int
    ticket_key: str
    kind: DraftKind
    repo: str | None
    pr_url: str | None
    comment_id: int | None
    issue_url: str | None
    stance: DraftStance | None
    thread_id: str | None
    status: DraftStatus
    why: str | None
    basis: str
    superseded_by: int | None
    created_at: str
    checked_at: str | None
    send_started_at: str | None
    send_version: int | None
    pending_review: str | None
    pending_review_id: int | None
    sent_at: str | None
    sent_comment_id: int | None
    sent_review_id: int | None
    sent_url: str | None
    sent_channel: str | None
    #: The reaction a send added on GitHub, which stays there even when the send's review then failed.
    reacted: Reaction | None
    reacted_at: str | None


@dataclass(frozen=True)
class DraftVersion(Row):
    """One version of a draft's text: the run's own, or one of the operator's edits (DESIGN §29)."""

    TABLE: ClassVar[str] = "draft_versions"

    draft_id: int
    version: int
    #: The text; empty when the version sends its reaction alone.
    body: str
    author: DraftAuthor
    channel: str | None
    created_at: str
    #: The reaction it stages on the review comment its thread's draft names, if any.
    reaction: Reaction | None


@dataclass(frozen=True)
class RunReplies(Row):
    """The `trust.review_replies` a run was rendered under, and the drafts `_run` refused of it (DESIGN §29)."""

    TABLE: ClassVar[str] = "run_replies"

    run_id: int
    mode: ReplyMode
    # Whether the run's prompt asked for a ticket's draft.
    ticket_drafts: bool
    # A JSON list of the drafts refused from the run's result, each its number and why.
    refused: str


@dataclass(frozen=True)
class Run(Row):
    """A worker's run on a ticket (DESIGN §8): what it was asked, how it ended, and what it cost."""

    TABLE: ClassVar[str] = "runs"

    id: int
    tick_id: int
    ticket_key: str
    kind: RunKind
    #: The detached `_run`'s pid, and below, its worker's.
    pid: int | None
    branch: str
    started_at: str
    ended_at: str | None
    status: RunStatus
    result_json: str | None
    log_path: str
    worker_pid: int | None
    session_id: str | None
    cost_usd: float | None
    tokens_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_cache_read: int | None
    tokens_cache_write: int | None
    private: bool
    tokens_peak_context: int | None
    tokens_first_call: int | None
    tokens_first_cache_write: int | None
    definitions_digest: str | None
    #: The worker's latest tool call, what it was doing, and when; None before its first.
    activity_tool: str | None
    activity: str | None
    activity_at: str | None
    plan_id: int | None


@dataclass(frozen=True)
class RunSlot(Row):
    """A pool slot a run leased (DESIGN §8), one per repository it works in."""

    TABLE: ClassVar[str] = "run_slots"

    run_id: int
    repo: str | None
    slot_path: str
    lease_id: str
    lease_holder: str
    base_branch: str | None
    git_link: bytes | None
    pool: PoolKind


@dataclass(frozen=True)
class TicketUnit(Row):
    """A ticket's work in one repository (D058): its branch, PR, and phase."""

    TABLE: ClassVar[str] = "ticket_units"

    ticket_key: str
    repo: str | None
    branch: str | None
    pr_url: str | None
    phase: Phase | None
    last_review_id: str | None
    last_ci_run_id: str | None


@dataclass(frozen=True)
class Message(Row):
    """A message in a subject's conversation (DESIGN §22): a worker's report or question, or a reply to one."""

    TABLE: ClassVar[str] = "messages"

    id: int
    #: `ticket`, and the ticket's key.
    subject_kind: str
    subject_id: str
    at: str
    #: `worker`, `operator`, or `tracker`.
    source: str
    #: `report` or `question`, a worker's; `reply`, the operator's.
    kind: str
    #: `run`, `cli`, `web`, `slack`, or `tracker`.
    channel: str
    run_id: int | None
    body: str
    #: The message a reply answers, when the channel knows it.
    answers: int | None
    submission: str | None
    comment_id: str | None
    author: str | None
    commented_at: str | None
    truncated: bool


@dataclass(frozen=True)
class Notice(Row):
    """A notice the operator set for the overseer, until it lapses or is ended."""

    TABLE: ClassVar[str] = "notices"

    id: int
    body: str
    set_at: str
    channel: str
    lapses_at: str
    ended_at: str | None
    ended_channel: str | None


@dataclass(frozen=True)
class Notification(Row):
    """A notification a sink was sent (DESIGN §20), kept so the same one is not sent twice."""

    TABLE: ClassVar[str] = "notifications"

    sink: str
    fingerprint: str
    ticket_key: str | None
    reason: str
    repo: str | None
    sent_at: str


@dataclass(frozen=True)
class NotifyEvent(Row):
    """An event in the outbox the notification sinks read (DESIGN §20)."""

    TABLE: ClassVar[str] = "notify_events"

    id: int
    grp: str
    kind: str
    at: str
    #: A JSON object of the event's fields.
    fields: str


@dataclass(frozen=True)
class NotifySink(Row):
    """A notification sink's place in the outbox (DESIGN §20), and how its deliveries have gone."""

    TABLE: ClassVar[str] = "notify_sinks"

    name: str
    #: The newest event it was delivered.
    cursor: int
    created_at: str
    last_delivery_at: str | None
    last_digest_at: str | None
    failures: int
    last_error: str | None


@dataclass(frozen=True)
class Pause(Row):
    """The loop's pause, while the operator has it paused."""

    TABLE: ClassVar[str] = "pause"

    id: int
    paused_at: str
    channel: str


@dataclass(frozen=True)
class PrTitle(Row):
    """A PR's title, as canopy last read it."""

    TABLE: ClassVar[str] = "pr_titles"

    pr_url: str
    title: str
    updated_at: str


@dataclass(frozen=True)
class ReviewDismissal(Row):
    """A review's finding the operator dismissed (DESIGN §21)."""

    TABLE: ClassVar[str] = "review_dismissals"

    review_run_id: int
    finding: int
    dismissed_at: str
    channel: str


@dataclass(frozen=True)
class FindingDismissal(Row):
    """A chore's finding the operator dismissed (DESIGN §19)."""

    TABLE: ClassVar[str] = "finding_dismissals"

    chore: str
    finding_id: str
    dismissed_at: str
    channel: str


@dataclass(frozen=True)
class ReviewGrant(Row):
    """Review runs the operator granted a PR past its limit (DESIGN §21)."""

    TABLE: ClassVar[str] = "review_grants"

    id: int
    pr_url: str
    runs: int
    granted_at: str


@dataclass(frozen=True)
class AttemptGrant(Row):
    """Attempts the operator granted a ticket's runs of one kind past its limit."""

    TABLE: ClassVar[str] = "attempt_grants"

    id: int
    ticket_key: str
    repo: str
    kind: RunKind
    runs: int
    granted_at: str


@dataclass(frozen=True)
class SplitChild(Row):
    """A ticket a split run filed, and the ticket it was split from."""

    TABLE: ClassVar[str] = "split_children"

    child_key: str
    parent_key: str
    repo: str
    run_id: int


def fetch_all[R: Row](conn: sqlite3.Connection, row_type: type[R], query: sql.Composable) -> list[R]:
    """Run `query`, a statement built with `sql`, and build each row it returns as `row_type`.

    Returns:
        The rows, in the order the query returned them.
    """
    cur = sql.execute(conn, query)
    build = _builder(row_type, cur.description)
    return [build(r) for r in cur.fetchall()]


def fetch_one[R: Row](conn: sqlite3.Connection, row_type: type[R], query: sql.Composable) -> R | None:
    """Run `query`, a statement built with `sql`, and build its first row as `row_type`.

    Returns:
        The first row, or None when the query returned none.
    """
    cur = sql.execute(conn, query)
    build = _builder(row_type, cur.description)
    first = cur.fetchone()
    return None if first is None else build(first)


def columns(row: sqlite3.Row | Row) -> sqlite3.Row | dict[str, Any]:
    """A row of a table with a row type or one still read as `sqlite3.Row`, either way read by column name.

    For a helper that reads the same columns, such as a run's cost, from rows of several tables, while some of those
    tables have no row type yet.

    Returns:
        A typed row's fields by name, or the `sqlite3.Row` itself.
    """
    return asdict(row) if isinstance(row, Row) else row


def _builder[R: Row](row_type: type[R], description: Sequence[Sequence[object]]) -> Callable[[Sequence[object]], R]:
    """Check a query's columns against `row_type`'s fields, and return what builds one row of it.

    Returns:
        A function from one row the query returns to the row type.

    Raises:
        RowError: The query returns a column `row_type` has no field for, leaves a field out, or repeats one.
    """
    columns = [str(d[0]) for d in description]
    converters = _converters(row_type)
    if sorted(columns) != sorted(converters):
        missing = sorted(set(converters) - set(columns))
        extra = sorted(set(columns) - set(converters))
        unfit: list[str] = []
        if missing:
            unfit.append(f"missing {', '.join(missing)}")
        if extra:
            unfit.append(f"no field for {', '.join(extra)}")
        # Neither, when the query names a column twice.
        raise RowError(f"query does not fit {row_type.__name__}: {'; '.join(unfit) or 'a column is repeated'}")
    named = [(column, converters[column]) for column in columns]

    def build(row: Sequence[object]) -> R:
        return row_type(**{name: convert(value) for (name, convert), value in zip(named, row, strict=True)})

    return build


def _converters(row_type: type[Row]) -> dict[str, _Convert]:
    """Each field of `row_type`, by name, with what converts its column's value.

    Returns:
        The converters, in field order.
    """
    hints = typing.get_type_hints(row_type)
    return {f.name: _converter(row_type.TABLE, f.name, hints[f.name]) for f in fields(row_type)}


def _converter(table: str, name: str, hint: object) -> _Convert:
    """What converts a column's value to `hint`, refusing a value of another type.

    Returns:
        The converter. A `T | None` field passes None through and converts anything else as `T`.

    Raises:
        RowError: `hint` is not a type a column can hold.
    """
    args = typing.get_args(hint)
    others = [a for a in args if a is not type(None)]
    if typing.get_origin(hint) in {types.UnionType, typing.Union} and type(None) in args and len(others) == 1:
        inner = _converter(table, name, others[0])
        return lambda value: None if value is None else inner(value)
    where = f"{table}.{name}"
    exact = _EXACT.get(hint)
    if exact is not None:
        return lambda value: _checked(where, value, (exact,))
    if hint is float:
        return lambda value: float(typing.cast("float", _checked(where, value, (float, int))))
    if hint is bool:
        return lambda value: _flag(where, value)
    if isinstance(hint, type) and issubclass(hint, StrEnum):
        vocabulary: type[StrEnum] = hint
        return lambda value: _member(where, vocabulary, value)
    raise RowError(
        f"{where} is a {hint}; a row's fields are int, float, str, bytes, bool, a StrEnum, or one of them or None"
    )


def _checked(where: str, value: object, allowed: tuple[type, ...]) -> object:
    """`value`, if it is one of `allowed`.

    Returns:
        `value`, unchanged.

    Raises:
        RowError: It is of another type, None included.
    """
    if not isinstance(value, allowed):
        expected = " or ".join(t.__name__ for t in allowed)
        raise RowError(f"{where} is {type(value).__name__}, not {expected}")
    return value


def _flag(where: str, value: object) -> bool:
    """A flag column's value as a bool. SQLite has no boolean: a flag is stored as 0 or 1.

    Returns:
        True for 1, False for 0.

    Raises:
        RowError: The value is anything else.
    """
    if isinstance(value, int) and value in {0, 1}:
        return value == 1
    raise RowError(f"{where} holds neither 0 nor 1, as a flag must")


def _member(where: str, vocabulary: type[StrEnum], value: object) -> StrEnum:
    """A vocabulary column's value as the member of `vocabulary` it names.

    Returns:
        The member whose value is `value`.

    Raises:
        RowError: The value is not a string, or not one `vocabulary` holds.
    """
    text = str(_checked(where, value, (str,)))
    try:
        return vocabulary(text)
    except ValueError:
        raise RowError(f"{where} holds {text!r}, which is not a {vocabulary.__name__}") from None
