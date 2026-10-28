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

import functools
import sqlite3
import types
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import Field, asdict, dataclass, fields
from enum import StrEnum
from typing import Any, ClassVar

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is read.
from canopy.core import sql
from canopy.core.vocab import (
    AnchorStatus,
    AuthorKind,
    CheckConclusion,
    CheckStatus,
    ChoreRunStatus,
    ConnectorRunStatus,
    Decider,
    DismissalReason,
    DraftAuthor,
    DraftKind,
    DraftStance,
    DraftStatus,
    FindingAnswer,
    GcPassStatus,
    HoldKind,
    MemoryAuthor,
    MemoryCited,
    MemoryMode,
    MemoryScope,
    MemoryStatus,
    MergeState,
    ModelsRead,
    MoveKind,
    NumberedItem,
    OverrideKind,
    Phase,
    PlanEffort,
    PlanItem,
    PlanSetting,
    PlanStatus,
    PoolKind,
    Proposal,
    PrState,
    Reaction,
    RecordedKind,
    RecordedStatus,
    ReplyMode,
    ResumeReason,
    ReviewDraftAuthor,
    ReviewDraftStatus,
    ReviewItem,
    ReviewRunStatus,
    ReviewState,
    RunKind,
    RunStatus,
    SeenKind,
    SessionsRead,
    SourceKind,
    StartStatus,
    ThreadState,
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
    #: Whether it ran its overseer: False when halted or when nothing was left to it (DESIGN §39); None on a tick from
    #: before that was recorded, or one that ended before it got that far.
    overseer_ran: bool | None
    #: What its first model call read from the cache; None where `tokens_first_call` is, and on a run from before
    #: canopy kept it.
    tokens_first_cache_read: int | None


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
    #: The mirror cursor, unread since M37 retired the mirror (DESIGN §35); kept, since no migration drops a column.
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
    #: The comment cursor, a journal number (DESIGN §35); `last_comment_id` holds it, a tracker's id, instead for a
    #: ticket no tracker source observes.
    comment_cursor: int | None


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
    """A decision a tick recorded (DESIGN §6): the overseer's, a guard's refusal, or the harness's own (§37)."""

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
    #: Who made it; None on a decision recorded before the journal said (TRUST_MODEL T5).
    decider: Decider | None


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
    #: What its first model call read from the cache; None where `tokens_first_call` is, and on a run from before
    #: canopy kept it.
    tokens_first_cache_read: int | None


@dataclass(frozen=True)
class RecordedRun(Row):
    """A run the overseer asked for, recorded at the ask and spawned by the tick after its run (DESIGN §40)."""

    TABLE: ClassVar[str] = "recorded_runs"

    id: int
    tick_id: int
    kind: RecordedKind
    #: The verb's request as the overseer made it, JSON, which the spawn makes again.
    request: str
    #: What it holds while it waits: its ticket, a review's PR and persona, a chore's name.
    ticket_key: str | None
    pr_url: str | None
    persona: str | None
    chore: str | None
    status: RecordedStatus
    #: The run it started as, in its kind's table; None until it starts.
    run_id: int | None
    recorded_at: str
    closed_at: str | None


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
    #: The persona it ran in, and the sha256 of its text (DESIGN §31); None for a review from before canopy recorded it.
    persona: str | None
    persona_digest: str | None
    #: A revision's draft, by its id, and the version of it the revision read (DESIGN §34); None for a review.
    revises: int | None
    revises_version: int | None
    #: Its journal number, taken when it ended (DESIGN §35); None while it runs.
    number: int | None
    #: What its first model call read from the cache; None where `tokens_first_call` is, and on a run from before
    #: canopy kept it.
    tokens_first_cache_read: int | None


@dataclass(frozen=True)
class Task(Row):
    """A one-off task the operator submitted (DESIGN §36): their text, where it runs, and whether they stopped it."""

    TABLE: ClassVar[str] = "tasks"

    id: int
    #: The operator's words: the task's instruction.
    text: str
    #: The repository it runs in, by its name in the map.
    repo: str
    #: The tracker project its tickets may go in; None for none.
    project: str | None
    #: `cli` or `web`: where the operator submitted it.
    channel: str
    submitted_at: str
    #: When the operator stopped it; None while it is not stopped.
    stopped_at: str | None


@dataclass(frozen=True)
class TaskRun(Row):
    """A run of a task's worker (DESIGN §36): the slot it leased, its branch, how it ended, and the head it pushed."""

    TABLE: ClassVar[str] = "task_runs"

    id: int
    task_id: int
    #: The tick that started it.
    tick_id: int
    #: `<branch_prefix>task/<id>`.
    branch: str
    repo: str
    slot_path: str
    lease_id: str
    lease_holder: str
    base_branch: str
    pool: PoolKind
    #: What the slot's `.git` file held when the run started, before any git step; None until `_task` reads it, or
    #: when it was not a file.
    git_link: bytes | None
    pid: int | None
    agent_pid: int | None
    started_at: str
    ended_at: str | None
    status: RunStatus
    result_json: str | None
    #: The commit its branch was at on origin when it ended; None when nothing was pushed.
    head: str | None
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
    #: The newest message about its task when it started: its prompt carries the conversation up to it, and a reply
    #: past it queues the next run. None when the task had none.
    message_id: int | None
    #: The SHA-256, hex, of the report it left, as `_task` kept it in the state directory; None when it left none.
    report_sha256: str | None
    #: What its first model call read from the cache; None where `tokens_first_call` is, and on a run from before
    #: canopy kept it.
    tokens_first_cache_read: int | None


@dataclass(frozen=True)
class Attachment(Row):
    """A text file the operator attached to a ticket or a task, for its runs to read as data (DESIGN §22)."""

    TABLE: ClassVar[str] = "attachments"

    id: int
    #: `ticket` and the ticket's key, or `task` and its id.
    subject_kind: str
    subject_id: str
    #: What runs see it as: a plain file name, unique among the subject's attachments not removed.
    name: str
    #: The bytes of its text as kept, and their SHA-256, hex.
    size: int
    sha256: str
    #: `cli` or `web`: where the operator attached it.
    channel: str
    added_at: str
    #: When the operator removed it, and through which channel; both None while it is attached.
    removed_at: str | None
    removed_channel: str | None


@dataclass(frozen=True)
class TaskTicket(Row):
    """A ticket a task's run reported filing in the task's project, checked on its text alone (DESIGN §36, D003)."""

    TABLE: ClassVar[str] = "task_tickets"

    id: int
    task_id: int
    #: The run whose result reported it.
    task_run_id: int
    #: The ticket's key, as the result spelled it: the tracker's, which canopy works only once it is authorized.
    key: str
    at: str


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
class ReviewRequestPersona(Row):
    """A persona the operator chose for a review request (DESIGN §31), in place of `[personas] reviewer`."""

    TABLE: ClassVar[str] = "review_request_personas"

    request_id: int
    #: The persona's name, as `canopy personas` lists it.
    persona: str


@dataclass(frozen=True)
class ReviewHead(Row):
    """A PR's head commit as canopy last saw it, and since when (DESIGN §21): the clock a review's settle time reads."""

    TABLE: ClassVar[str] = "review_heads"

    pr_url: str
    sha: str
    seen_at: str


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
    #: Why the planner said its plan needs no review, when the harness approved it so (channel `planner`, DESIGN §25).
    approved_reason: str | None
    #: How much work the plan is for its worker, as its planner judged; None when it gave no estimate.
    effort: PlanEffort | None


@dataclass(frozen=True)
class FeedbackPlan(Row):
    """A plan a feedback plan run wrote for a ticket's PRs (DESIGN §32): its status, hashes, and approval. No text."""

    TABLE: ClassVar[str] = "feedback_plans"

    id: int
    ticket_key: str
    run_id: int
    created_at: str
    status: PlanStatus
    #: The file's SHA-256, hex, and its size in bytes, as the planner wrote it.
    sha256: str
    size: int
    #: The file's SHA-256 when the operator approved it, their edits included; set with the time and the channel.
    approved_sha256: str | None
    approved_at: str | None
    approved_channel: str | None
    #: The `resume` that went ahead on the approval, which it spent: an approval goes ahead once.
    spent_run_id: int | None
    #: Why the planner said its plan needs no review, when the harness approved it so (channel `planner`, DESIGN §25).
    approved_reason: str | None
    #: How much work the plan is for its worker, as its planner judged; None when it gave no estimate.
    effort: PlanEffort | None
    #: The SHA-256 of what changed that an approval of it, stale, was last refused for: approving again approves it.
    stale_shown: str | None
    #: The operator message its approval wrote on the ticket, naming its items; None unless the operator approved it.
    approved_message_id: int | None


@dataclass(frozen=True)
class FeedbackPlanPr(Row):
    """A PR a feedback plan read, and its head then (DESIGN §32, Planning again)."""

    TABLE: ClassVar[str] = "feedback_plan_prs"

    plan_id: int
    pr_url: str
    head_sha: str | None
    #: Whether it conflicted with its base then, as its host said; None while it had not said, or for a plan recorded
    #: before this was.
    conflicted: bool | None
    #: The merged PR it was stacked on then, its blocker's (DESIGN §10); None when it was on none, or for a plan
    #: recorded before this was.
    merged_blocker: str | None


@dataclass(frozen=True)
class FeedbackPlanCheck(Row):
    """A named check at the head a feedback plan read, and its conclusion then, None while it had none."""

    TABLE: ClassVar[str] = "feedback_plan_checks"

    plan_id: int
    pr_url: str
    name: str
    conclusion: CheckConclusion | None


@dataclass(frozen=True)
class FeedbackPlanMove(Row):
    """A waiting feedback plan's PR's head or check: its value now, and when canopy saw it take that value (§32)."""

    TABLE: ClassVar[str] = "feedback_plan_moves"

    plan_id: int
    pr_url: str
    kind: MoveKind
    #: A check's name; "" for the head.
    name: str
    #: The head's sha, or the check's conclusion; "" for none.
    value: str
    #: When the harness first saw it take `value`, since it last held another.
    seen_at: str


@dataclass(frozen=True)
class FeedbackPlanSeen(Row):
    """A review or review comment a feedback plan was given, by id and its body's hash, never its text."""

    TABLE: ClassVar[str] = "feedback_plan_seen"

    plan_id: int
    pr_url: str
    item: ReviewItem
    item_id: int
    thread_id: str | None
    author: str | None
    #: The SHA-256, hex, of its body as the plan's read observed it: an edit after changes it.
    body_sha256: str
    #: For a reply, given beside the item it answers: that item's id; None for an item.
    answers: int | None


@dataclass(frozen=True)
class FeedbackPlanItem(Row):
    """An item a feedback plan covers, by its id, and what the plan proposes for it (DESIGN §32)."""

    TABLE: ClassVar[str] = "feedback_plan_items"

    plan_id: int
    #: Its place in the planner's result line, from 1: what an approval names it by.
    number: int
    pr_url: str
    item: PlanItem
    #: A review's or comment's id as the `vcs` source observed it; a failed check's, a conflict's, or a merged
    #: blocker's, below zero, as canopy gave it (`feedback_items.check_id`).
    item_id: int
    proposal: Proposal
    #: The reply the plan would draft, for a review item's change or decline: model text, never an instruction.
    reply: str | None
    #: Whether the operator's approval left it out: its `resume` does not act on it, and the next plan gets it.
    left_out: bool


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
class TicketOverride(Row):
    """The operator's choice for one of a ticket's agents, in force until cleared (DESIGN §31, §13)."""

    TABLE: ClassVar[str] = "ticket_overrides"

    ticket_key: str
    #: `worker`, `planner`, or `reviewer`.
    agent: str
    kind: OverrideKind
    #: What the operator chose: a persona's name.
    value: str
    #: `cli` or `web`: where the operator set it.
    channel: str
    set_at: str


@dataclass(frozen=True)
class NextRunPersona(Row):
    """The persona the operator chose for the next run alone of one of a ticket's agents (DESIGN §31)."""

    TABLE: ClassVar[str] = "next_run_personas"

    ticket_key: str
    #: `worker` or `planner`.
    agent: str
    #: The persona's name.
    persona: str
    #: `cli` or `web`: where the operator set it.
    channel: str
    set_at: str


@dataclass(frozen=True)
class PersonaText(Row):
    """The text of a persona a run or a review was given, once per digest (DESIGN §31)."""

    TABLE: ClassVar[str] = "persona_texts"

    #: The sha256 of `text`, in hex, as a run's `persona_digest` names it.
    digest: str
    #: The persona's text as the prompt carried it.
    text: str
    recorded_at: str


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
    #: When the operator pinned a lesson, which is then never due for review and served first; None if not pinned.
    pinned_at: str | None


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
    """A repository an old triage run read without a slot, by name (M55). Kept as history; nothing reads it now."""

    TABLE: ClassVar[str] = "run_reads"

    run_id: int
    repo: str


@dataclass(frozen=True)
class PlanWaiver(Row):
    """A plan an old triage run waived (M55). Kept as history: nothing reads it, so no waiver holds (DESIGN §25)."""

    TABLE: ClassVar[str] = "plan_waivers"

    id: int
    ticket_key: str
    #: The `needs-plan` run whose result waived it.
    run_id: int
    #: The triage's one-sentence reason, model text written from the ticket.
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
class RunModelRead(Row):
    """How canopy's last read of an agent run's session for its models ended (DESIGN §13): the run, by table and id."""

    TABLE: ClassVar[str] = "run_model_reads"

    run_table: str
    run_id: int
    status: ModelsRead
    #: canopy's words for why it failed; None unless `failed`.
    error: str | None
    #: How many times canopy has read it.
    attempts: int
    read_at: str


@dataclass(frozen=True)
class RunModel(Row):
    """One model an agent run's session names as having written its replies (DESIGN §13), and what they cost."""

    TABLE: ClassVar[str] = "run_models"

    run_table: str
    run_id: int
    #: As `provider/model`.
    model: str
    replies: int
    cost_usd: float


@dataclass(frozen=True)
class RuntimeSession(Row):
    """A session the agent runtime keeps, canopy's or not, as the runtime last recorded it (DESIGN §13)."""

    TABLE: ClassVar[str] = "runtime_sessions"

    session_id: str
    #: The session it ran for as a subagent; None for a session of its own.
    parent_id: str | None
    directory: str
    started_at: str
    updated_at: str
    #: The runtime's own stamp of the update, in milliseconds since the epoch.
    updated_ms: int
    cost_usd: float
    tokens_input: int
    tokens_output: int
    tokens_reasoning: int
    tokens_cache_read: int
    tokens_cache_write: int
    read_at: str


@dataclass(frozen=True)
class RuntimeSessionModel(Row):
    """One model a runtime session's replies name, and what they cost (DESIGN §13)."""

    TABLE: ClassVar[str] = "runtime_session_models"

    session_id: str
    #: As `provider/model`.
    model: str
    replies: int
    cost_usd: float


@dataclass(frozen=True)
class RuntimeSessionRead(Row):
    """How reading the runtime's sessions stands (DESIGN §13): where the next read starts, and how the last ended."""

    TABLE: ClassVar[str] = "runtime_session_reads"

    #: Always 1: the table holds one row.
    id: int
    #: The last session read's update, in the runtime's milliseconds, and its id; both None before the first.
    cursor_updated_ms: int | None
    cursor_session_id: str | None
    status: SessionsRead
    #: canopy's words for why it failed; None unless `failed`.
    error: str | None
    #: How many sessions every read so far passed over as ones canopy cannot read.
    skipped: int
    read_at: str


@dataclass(frozen=True)
class RunReplyModel(Row):
    """The model that wrote one reply of an agent run more than one model served (DESIGN §13)."""

    TABLE: ClassVar[str] = "run_reply_models"

    run_table: str
    run_id: int
    #: The runtime's id of the reply, which the events of the model call that wrote it name in the run's log.
    message: str
    #: As `run_models.model` names it.
    model: str


@dataclass(frozen=True)
class RunOffer(Row):
    """canopy's ask of the runtime, as an agent run started, of what it offered the run (DESIGN §13)."""

    TABLE: ClassVar[str] = "run_offers"

    run_table: str
    run_id: int
    #: The agent the run's command runs; None when it names none.
    agent: str | None
    #: canopy's words for why the runtime could not say; None when it said.
    error: str | None
    asked_at: str


@dataclass(frozen=True)
class RunOfferedServer(Row):
    """One MCP server the runtime offered an agent run (DESIGN §13)."""

    TABLE: ClassVar[str] = "run_offered_servers"

    run_table: str
    run_id: int
    server: str
    #: `all` of its tools, or only `some`.
    reach: str


@dataclass(frozen=True)
class RunOfferedSkill(Row):
    """One skill the runtime offered an agent run (DESIGN §13)."""

    TABLE: ClassVar[str] = "run_offered_skills"

    run_table: str
    run_id: int
    skill: str


@dataclass(frozen=True)
class RunOfferedTool(Row):
    """One of the runtime's built-in tools it offered an agent run (DESIGN §13)."""

    TABLE: ClassVar[str] = "run_offered_tools"

    run_table: str
    run_id: int
    tool: str


@dataclass(frozen=True)
class RunOfferedServerRule(Row):
    """One rule that leaves an agent run only some of an MCP server's tools (DESIGN §13)."""

    TABLE: ClassVar[str] = "run_offered_server_rules"

    run_table: str
    run_id: int
    server: str
    #: Where it applies among the server's rules, from 0: a later one wins where both match a tool.
    position: int
    #: `offer` or `deny`, then the tool names it matches, as the runtime's patterns write them.
    rule: str


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
    #: Its title, the PR author's text, cut and marked, for display only: None from a reader that printed none.
    title: str | None


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
    #: Its journal number, taken when a source first observed it (DESIGN §35).
    number: int | None


@dataclass(frozen=True)
class ItemNumber(Row):
    """An item's journal number (DESIGN §35): taken when a source first observed it, or a review run ended."""

    TABLE: ClassVar[str] = "item_numbers"

    number: int
    kind: NumberedItem
    #: A ticket's key for a comment; a PR's URL for the rest.
    subject: str
    #: The source's id for it, or canopy's own for a review run.
    id: str
    numbered_at: str


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
    #: The comment's text, cut at `conversation.MAX_COMMENT`.
    body: str
    truncated: bool
    #: `worker` when it carries the workers' marks (D069), else `tracker`.
    source: str
    observed_at: str
    #: Its journal number, taken when a source first observed it (DESIGN §35).
    number: int | None


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
    #: Its completed run's journal number (DESIGN §35); None while it runs, and for a commit status, which has no run.
    number: int | None


@dataclass(frozen=True)
class ObservedCheckRun(Row):
    """A completed check run a `vcs` source observed, kept across later reads of its PR (DESIGN §35)."""

    TABLE: ClassVar[str] = "observed_check_runs"

    pr_url: str
    run_id: int
    #: Its context's name, as `observed_checks.name`.
    name: str
    head_sha: str
    conclusion: CheckConclusion
    #: When a source first observed it completed.
    observed_at: str
    #: Its journal number, taken when a source first observed it completed (DESIGN §35).
    number: int | None


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
class ObservedFeed(Row):
    """How far an `artifacts` source has read its store's comment feed (DESIGN §30, §38)."""

    TABLE: ClassVar[str] = "observed_feeds"

    source: str
    #: The cursor the next run reads from: the `seq` of the last change it read, or past changes filtered out.
    through: int
    #: When a run last read the feed to its `end` line with nothing refused; None until one has.
    read_at: str | None


@dataclass(frozen=True)
class ObservedArtifactThread(Row):
    """A thread on an artifact, as the newest change the `artifacts` source read of it left it. Never authority."""

    TABLE: ClassVar[str] = "observed_artifact_threads"

    id: str
    artifact_id: str
    #: The artifact's origin pairs, as a JSON object.
    origin: str
    #: The origin's `canopy.ticket`, where that is a ticket's key.
    ticket: str | None
    #: The passage's words and the text either side; None for a thread on the whole artifact.
    exact: str | None
    prefix: str | None
    suffix: str | None
    anchored_version: int
    state: ThreadState
    #: Whether the passage was in the artifact's latest version when the store printed the change.
    anchor_status: AnchorStatus | None
    #: The store's `seq` of the newest change read of it.
    seq: int
    observed_at: str


@dataclass(frozen=True)
class ObservedArtifactComment(Row):
    """A comment on an artifact, as the newest change the `artifacts` source read of it left it. Never authority."""

    TABLE: ClassVar[str] = "observed_artifact_comments"

    id: str
    thread_id: str
    #: The store's id for who wrote it, stable for the life of the account.
    author: str
    author_name: str
    author_kind: AuthorKind
    #: For an agent's comment, the person it wrote for.
    on_behalf_of: str | None
    via: str
    #: Its text, cut at `conversation.MAX_COMMENT`; empty once deleted.
    body: str
    truncated: bool
    #: Whether it carries every one of the workers' marks (D069).
    marked: bool
    created_at: str
    edited_at: str | None
    deleted_at: str | None
    #: The store's `seq` of the newest change read of it.
    seq: int
    observed_at: str


@dataclass(frozen=True)
class Derivation(Row):
    """One subject a tick derived in code, in shadow (DESIGN §30): a ticket's own phases, or a unit's."""

    TABLE: ClassVar[str] = "derivations"

    id: int
    tick_id: int
    ticket_key: str
    #: The unit's repository; None on the ticket's own row.
    repo: str | None
    #: Whether the ticket is a candidate (DESIGN §17); None on a unit's row and a stale one.
    candidate: bool | None
    #: Whether the tracker said the ticket is closed; None on a unit's row and a stale one.
    closed: bool | None
    #: Every phase of §7's table that held, as a JSON list; empty when none did, or the subject is stale.
    phases: str
    #: The stale or missing observation the subject depends on; None when it was derived.
    stale: str | None
    #: The phase the journal held for the subject when the tick closed: the overseer's.
    overseer_phase: Phase | None


@dataclass(frozen=True)
class GcPass(Row):
    """One pass of garbage collection (DESIGN §26): the retention it ran with, and what it removed."""

    TABLE: ClassVar[str] = "gc_passes"

    id: int
    #: The tick it ran in; None for a pass run by hand.
    tick_id: int | None
    started_at: str
    ended_at: str
    status: GcPassStatus
    run_files_days: int
    tick_files_days: int
    #: The end before which a run's files went, and an `ok` tick's; None when that kind is kept forever.
    run_cutoff: str | None
    tick_cutoff: str | None
    #: The files and the journal's rows it removed, and their bytes, by the kind `canopy gc --dry-run` names, as a JSON
    #: object of `{"files", "bytes"}` or `{"rows", "bytes"}`.
    removed: str
    #: The files it found past retention but could not remove.
    failures: int
    #: What it raised; None for an `ok` pass.
    error: str | None


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
    #: The number of the item of its run's feedback plan whose proposed reply it started from, or None (0093).
    plan_item: int | None


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
class ReviewDraft(Row):
    """A review's draft (DESIGN §34): a review of a PR the loop does not own, as the comment review it would post."""

    TABLE: ClassVar[str] = "review_drafts"

    id: int
    review_run_id: int
    pr_url: str
    #: The commit the review read, which the review is posted on.
    sha: str
    status: ReviewDraftStatus
    why: str | None
    created_at: str
    #: A publish's claim: the version it posts, when it began, and through which channel.
    publish_version: int | None
    publish_started_at: str | None
    publish_channel: str | None
    #: The pending review a post reported: its node id, which a later post deletes it by, and its id.
    pending_review: str | None
    pending_review_id: int | None
    published_at: str | None
    published_review_id: int | None
    published_url: str | None
    #: A JSON list, in the version's order, of each published comment's `id` and `url`.
    published_comments: str | None


@dataclass(frozen=True)
class ReviewDraftVersion(Row):
    """One version of a review's draft, exactly what would post: its body and its comments (DESIGN §34)."""

    TABLE: ClassVar[str] = "review_draft_versions"

    draft_id: int
    version: int
    body: str
    #: A JSON list of comments, each its `path`, `line`, and `text`, and the `finding` it was made from, if any.
    comments: str
    author: ReviewDraftAuthor
    channel: str | None
    #: What made it, in the harness's words.
    change: str
    #: A JSON list of what canopy left out as it made it, and why.
    refused: str
    created_at: str


@dataclass(frozen=True)
class ReviewDraftNote(Row):
    """The operator's note on a review's draft, which asks for a revision while it is newer than the newest version."""

    TABLE: ClassVar[str] = "review_draft_notes"

    id: int
    draft_id: int
    #: The draft's newest version when the note was written: the note is newer while that is still the newest.
    after_version: int
    body: str
    channel: str
    created_at: str


@dataclass(frozen=True)
class ReviewDraftGrant(Row):
    """Revisions the operator granted a review's draft past `policy.max_revisions_per_draft` (DESIGN §34)."""

    TABLE: ClassVar[str] = "review_draft_grants"

    id: int
    draft_id: int
    runs: int
    granted_at: str


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
    #: The feedback plan this run wrote, or the approved one its `resume` follows (DESIGN §32).
    feedback_plan_id: int | None
    #: The persona it ran in, and the sha256 of its text (DESIGN §31); None for a kind no persona reaches, and for a
    #: run from before canopy recorded it.
    persona: str | None
    persona_digest: str | None
    #: The model canopy chose for its agent, from `runtime.models` (DESIGN §13), as it asked the runtime for it; None
    #: when it chose none, so the run went to the runtime's default, and for a run from before canopy chose one.
    model: str | None
    #: What its first model call read from the cache; None where `tokens_first_call` is, and on a run from before
    #: canopy kept it.
    tokens_first_cache_read: int | None


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
    #: The `review` and `ci` cursors as an earlier canopy wrote them, a time and a check run's id; unread since they
    #: became journal numbers (DESIGN §35), kept, since no migration drops a column.
    last_review_id: str | None
    last_ci_run_id: str | None
    #: The `review` and `ci` cursors, journal numbers (DESIGN §35).
    review_cursor: int | None
    ci_cursor: int | None


@dataclass(frozen=True)
class Message(Row):
    """A message in a subject's conversation (DESIGN §22): a worker's report or question, or a reply to one."""

    TABLE: ClassVar[str] = "messages"

    id: int
    #: `ticket` and the ticket's key, `chore` and its name, or `task` and its id.
    subject_kind: str
    subject_id: str
    at: str
    #: `worker`, `operator`, or `tracker`.
    source: str
    #: `report` or `question`, a worker's; `reply`, the operator's; `comment`, a tracker comment a source observed.
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
    #: A task's run that reported it, as `run_id` names a ticket's (DESIGN §36).
    task_run_id: int | None


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
    #: Why the operator dismissed it; None for a dismissal from before canopy asked.
    reason: DismissalReason | None


@dataclass(frozen=True)
class ReviewAnswer(Row):
    """What a resumed worker answered of one of a review's findings (DESIGN §21): the worker's words, untrusted."""

    TABLE: ClassVar[str] = "review_answers"

    run_id: int
    review_run_id: int
    finding: int
    answer: FindingAnswer
    #: Why it declined, or what it says of a fix; None for a fix it said nothing of.
    reason: str | None


@dataclass(frozen=True)
class ReviewHold(Row):
    """A review's finding the harness holds for the operator: it reaches no worker until they send it (DESIGN §21)."""

    TABLE: ClassVar[str] = "review_holds"

    review_run_id: int
    finding: int
    kind: HoldKind
    #: The earlier review run, and its finding, that a rebuttal answers; None for a `late` hold.
    rebuts_run_id: int | None
    rebuts_finding: int | None
    held_at: str
    #: When the operator sent it to a worker, and through which channel; None while it is held.
    released_at: str | None
    released_channel: str | None


@dataclass(frozen=True)
class FindingDismissal(Row):
    """A chore's finding the operator dismissed (DESIGN §19)."""

    TABLE: ClassVar[str] = "finding_dismissals"

    chore: str
    finding_id: str
    dismissed_at: str
    channel: str


@dataclass(frozen=True)
class Seen(Row):
    """A subject whose result the operator has seen (DESIGN §22), named as its reference names it."""

    TABLE: ClassVar[str] = "seen"

    #: The kind of subject: a reference's kind, such as `review` for `review:4`.
    kind: SeenKind
    #: The subject's id within its kind: a review run's id, as text.
    subject: str
    #: When the operator first saw it; for a review that had ended before the table, when it ended.
    at: str
    #: Where they saw it, `cli` or `web`; None for what was taken as seen when the table was made.
    channel: str | None


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


@dataclass(frozen=True)
class WebWrite(Row):
    """A write request the web UI's server let through, or a sign-in, as it answered it (TRUST_MODEL T8)."""

    TABLE: ClassVar[str] = "web_writes"

    id: int
    #: When the request came in.
    at: str
    method: str
    #: The request's path, without its query, at most 512 characters.
    path: str
    #: The HTTP status it was answered with.
    code: int
    #: The peer's address, as the server saw it.
    client: str | None
    #: A fingerprint of the session it was let through as or signed in; None on the mock server, which signs nobody in.
    session: str | None


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


# Cached: resolving a row type's hints costs about a millisecond, and every fetch of a row would pay it again.
@functools.cache
def _converters(row_type: type[Row]) -> Mapping[str, _Convert]:
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
        f"{where} is a {hint}; a row's fields are int, float, str, bytes, bool, a StrEnum, or one of them or None",
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
