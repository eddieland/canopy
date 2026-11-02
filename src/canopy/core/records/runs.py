"""Workers' runs on tickets.

Each run, the pool slots it leased, why it ran, and what it answered of its checklist (DESIGN §8, §18, §23, §42).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    ItemAnswer,
    PlannerApproval,
    PoolKind,
    ResumeReason,
    RunKind,
    RunStatus,
)


@dataclass(frozen=True)
class PoolSlot(Row):
    """A slot of one of canopy's own pools (DESIGN §18): where it is, and its lease while it has one."""

    TABLE: ClassVar[LiteralString] = "slots"

    repo: str
    name: str
    path: str
    lease_id: str | None
    lease_holder: str | None
    leased_at: str | None
    base: str
    seeded: str


@dataclass(frozen=True)
class RunReason(Row):
    """One reason a `resume` runs, as its dispatch named it (DESIGN §8)."""

    TABLE: ClassVar[LiteralString] = "run_reasons"

    run_id: int
    reason: ResumeReason


@dataclass(frozen=True)
class FlakyKick(Row):
    """A push canopy made to rerun a PR's checks a worker judged flaky: its branch rebased and leased (DESIGN §23)."""

    TABLE: ClassVar[LiteralString] = "flaky_kicks"

    run_id: int
    repo: str
    branch: str
    #: The commit origin's branch held before the kick.
    from_head: str
    #: The rebased commit the kick pushed in its place.
    to_head: str
    kicked_at: str


@dataclass(frozen=True)
class RunRead(Row):
    """A repository an old triage run read without a slot, by name (M55). Kept as history; nothing reads it now."""

    TABLE: ClassVar[LiteralString] = "run_reads"

    run_id: int
    repo: str


@dataclass(frozen=True)
class Run(Row):
    """A worker's run on a ticket (DESIGN §8): what it was asked, how it ended, and what it cost."""

    TABLE: ClassVar[LiteralString] = "runs"

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
    #: Its agent's latest card, as JSON, when it was recorded, and the tool calls made by then (DESIGN §41); None with
    #: no card.
    card_json: str | None
    card_at: str | None
    card_calls: int | None
    #: The tool calls its agent has ended so far.
    tool_calls: int
    #: When each step its card names as working was first seen so, as JSON by title (DESIGN §41); None with none.
    card_working_since: str | None
    #: When the question its card asks was first asked, the letter the operator answered it with, and when (DESIGN
    #: §41); None while it asks none, or waits on the operator.
    card_asked_at: str | None
    card_answer: str | None
    card_answered_at: str | None
    #: How many times its card went stale while it ran, counted once each as a tool call found it (DESIGN §41), and
    #: whether its card as it stands, or the run with none yet, has been counted stale.
    card_lapses: int
    card_stale: bool
    #: The level of `policy.planner_may_approve` a plan or feedback plan run's prompt offered its planner (DESIGN
    #: §25), `off` where it was asked nothing; None for any other kind, and a plan run from before canopy kept it.
    plan_review: PlannerApproval | None


@dataclass(frozen=True)
class RunSlot(Row):
    """A pool slot a run leased (DESIGN §8), one per repository it works in."""

    TABLE: ClassVar[LiteralString] = "run_slots"

    run_id: int
    repo: str | None
    slot_path: str
    lease_id: str
    lease_holder: str
    base_branch: str | None
    git_link: bytes | None
    pool: PoolKind


@dataclass(frozen=True)
class ChecklistAnswer(Row):
    """What a worker's or a task's run answered of an item of its repository's checklist (DESIGN §42): untrusted.

    It names one run: a worker's in `run_id`, or a task's in `task_run_id`, the other None.
    """

    TABLE: ClassVar[LiteralString] = "checklist_answers"

    run_id: int | None
    #: The repository whose list holds the item.
    repo: str
    #: The item's id in that list, as the run was given it.
    item: str
    answer: ItemAnswer
    #: Why the run left the item failing, for `held`; None for any other answer.
    reason: str | None
    task_run_id: int | None
