"""The operator's one-off tasks.

Each task, its runs, and the tickets they filed (DESIGN §36).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    PoolKind,
    RunStatus,
)


@dataclass(frozen=True)
class Task(Row):
    """A one-off task the operator submitted (DESIGN §36): their text, where it runs, and whether they stopped it."""

    TABLE: ClassVar[LiteralString] = "tasks"

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

    TABLE: ClassVar[LiteralString] = "task_runs"

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
    #: The model canopy chose for its private worker, from `runtime.models` (DESIGN §13), as it asked the runtime for
    #: it; None when it chose none, and on a run from before canopy recorded it.
    model: str | None
    #: Its worker's latest card, as JSON, when it was recorded, and the tool calls made by then (DESIGN §41); None with
    #: no card.
    card_json: str | None
    card_at: str | None
    card_calls: int | None
    #: The tool calls its worker has ended so far.
    tool_calls: int
    #: When each step its card names as working was first seen so, as JSON by title (DESIGN §41); None with none.
    card_working_since: str | None
    #: A task's run asks no question on its card, so these stay None; kept so a card reads as any run's (DESIGN §41).
    card_asked_at: str | None
    card_answer: str | None
    card_answered_at: str | None
    #: How many times its card went stale while it ran, counted once each as a tool call found it (DESIGN §41), and
    #: whether its card as it stands, or the run with none yet, has been counted stale.
    card_lapses: int
    card_stale: bool


@dataclass(frozen=True)
class TaskTicket(Row):
    """A ticket a task's run reported filing in the task's project, checked on its text alone (DESIGN §36, D003)."""

    TABLE: ClassVar[LiteralString] = "task_tickets"

    id: int
    task_id: int
    #: The run whose result reported it.
    task_run_id: int
    #: The ticket's key, as the result spelled it: the tracker's, which canopy works only once it is authorized.
    key: str
    at: str
