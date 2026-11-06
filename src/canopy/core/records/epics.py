"""Epics: work spanning several tickets, the operator's own subject (DESIGN §43).

Each epic, the repositories its plan reads, its member tickets, its plan runs and their slots, and its plans.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is read.
from canopy.core.vocab import PlanStatus, PoolKind, RunStatus


@dataclass(frozen=True)
class Epic(Row):
    """An epic the operator submitted (DESIGN §43): their goal, where its tickets come from, and if they stopped it."""

    TABLE: ClassVar[LiteralString] = "epics"

    id: int
    #: The operator's words: the goal its plan is written for.
    text: str
    #: The tracker project its breakdown's tickets are filed in; None for none.
    project: str | None
    #: A tracker key whose children are put to the operator as suggestions; None for none.
    tracker_epic: str | None
    #: `cli` or `web`: where the operator submitted it.
    channel: str
    submitted_at: str
    #: When the operator stopped it; None while it is not stopped.
    stopped_at: str | None
    #: The id the web's form drew for it, so a retry records it once; None for one the CLI submitted.
    submission: str | None


@dataclass(frozen=True)
class EpicRepo(Row):
    """A repository an epic's plan reads, by its name in the map."""

    TABLE: ClassVar[LiteralString] = "epic_repos"

    epic_id: int
    repo: str


@dataclass(frozen=True)
class EpicMember(Row):
    """A ticket the operator made a member of an epic, and, once they removed it, when (DESIGN §43)."""

    TABLE: ClassVar[LiteralString] = "epic_members"

    id: int
    epic_id: int
    ticket_key: str
    added_at: str
    #: `cli` or `web`: where the operator added it.
    added_channel: str
    #: When the operator removed it; None while it is a member.
    removed_at: str | None
    removed_channel: str | None
    #: The ids, space-separated, that changes of its epic's plan reached it by since its work last took one in: its
    #: next plan run is told them, and the operator's approval of its plan clears them; None for none (DESIGN §43).
    changed_ids: str | None


@dataclass(frozen=True)
class EpicRun(Row):
    """A run of an epic's planner (DESIGN §43): its desk, how it ended, and what it spent."""

    TABLE: ClassVar[LiteralString] = "epic_runs"

    id: int
    epic_id: int
    #: The tick that started it.
    tick_id: int
    #: The desk of links to its slots, one per repository, that it runs in.
    desk_path: str
    pid: int | None
    agent_pid: int | None
    started_at: str
    ended_at: str | None
    status: RunStatus
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
    tokens_first_cache_read: int | None
    definitions_digest: str | None
    #: The newest message about the epic its prompt carried: a reply after it asks for the next plan.
    message_id: int | None
    #: The model canopy chose for it, written into its definition; None when the runtime's default serves it.
    model: str | None
    tool_calls: int


@dataclass(frozen=True)
class EpicRunSlot(Row):
    """A slot an epic's plan run leased, one per repository, returned when the run ends (DESIGN §43)."""

    TABLE: ClassVar[LiteralString] = "epic_run_slots"

    run_id: int
    repo: str
    slot_path: str
    lease_id: str
    lease_holder: str
    base_branch: str
    pool: PoolKind
    #: What the slot's `.git` file held when the run started; None until the run reads it, or when it was no file.
    git_link: bytes | None


@dataclass(frozen=True)
class EpicPlan(Row):
    """A plan an epic's plan run wrote (DESIGN §43): its hashes and status, never its text, which is a file."""

    TABLE: ClassVar[LiteralString] = "epic_plans"

    id: int
    epic_id: int
    #: The plan run that wrote it.
    run_id: int
    created_at: str
    status: PlanStatus
    #: The file's hash and size as its planner wrote it.
    sha256: str
    size: int
    #: The file's hash when the operator approved it, their edits included; None until approved.
    approved_sha256: str | None
    approved_at: str | None
    #: `cli` or `web`: where the operator approved it.
    approved_channel: str | None


@dataclass(frozen=True)
class EpicMemberEntry(Row):
    """A breakdown entry a member of an epic fulfils, as the operator registered it (DESIGN §43)."""

    TABLE: ClassVar[LiteralString] = "epic_member_entries"

    member_id: int
    #: The entry's id, `B<n>`, in the plan approved when the operator registered it.
    entry: str
