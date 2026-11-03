"""Initiatives: work spanning several tickets, the operator's own subject (DESIGN §43).

Each initiative, the repositories its plan reads, its member tickets, and its plan runs and their slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is read.
from canopy.core.vocab import PoolKind, RunStatus


@dataclass(frozen=True)
class Initiative(Row):
    """An initiative the operator submitted (DESIGN §43): their goal, and where its tickets come from."""

    TABLE: ClassVar[LiteralString] = "initiatives"

    id: int
    #: The operator's words: the goal its plan is written for.
    text: str
    #: The tracker project its breakdown's tickets are filed in; None for none.
    project: str | None
    #: A tracker key whose children are put to the operator as suggestions; None for none.
    epic: str | None
    #: `cli` or `web`: where the operator submitted it.
    channel: str
    submitted_at: str


@dataclass(frozen=True)
class InitiativeRepo(Row):
    """A repository an initiative's plan reads, by its name in the map."""

    TABLE: ClassVar[LiteralString] = "initiative_repos"

    initiative_id: int
    repo: str


@dataclass(frozen=True)
class InitiativeMember(Row):
    """A ticket the operator made a member of an initiative, and, once they removed it, when (DESIGN §43)."""

    TABLE: ClassVar[LiteralString] = "initiative_members"

    id: int
    initiative_id: int
    ticket_key: str
    added_at: str
    #: `cli` or `web`: where the operator added it.
    added_channel: str
    #: When the operator removed it; None while it is a member.
    removed_at: str | None
    removed_channel: str | None


@dataclass(frozen=True)
class InitiativeRun(Row):
    """A run of an initiative's planner (DESIGN §43): its desk, how it ended, and what it spent."""

    TABLE: ClassVar[LiteralString] = "initiative_runs"

    id: int
    initiative_id: int
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
    #: The newest message about the initiative its prompt carried: a reply after it asks for the next plan.
    message_id: int | None
    #: The model canopy chose for it, written into its definition; None when the runtime's default serves it.
    model: str | None
    tool_calls: int


@dataclass(frozen=True)
class InitiativeRunSlot(Row):
    """A slot an initiative's plan run leased, one per repository, returned when the run ends (DESIGN §43)."""

    TABLE: ClassVar[LiteralString] = "initiative_run_slots"

    run_id: int
    repo: str
    slot_path: str
    lease_id: str
    lease_holder: str
    base_branch: str
    pool: PoolKind
    #: What the slot's `.git` file held when the run started; None until the run reads it, or when it was no file.
    git_link: bytes | None
