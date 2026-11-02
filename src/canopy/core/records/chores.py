"""The operator's recurring chores.

Their runs, and the findings the operator dismissed (DESIGN §19).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    ChoreRunStatus,
)


@dataclass(frozen=True)
class ChoreRun(Row):
    """A run of a chore (DESIGN §19): the overseer's, or the operator's `canopy chore try`, and how it ended."""

    TABLE: ClassVar[LiteralString] = "chore_runs"

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
    #: The model canopy chose for its agent, the chore's own `model` or `runtime.models`' (DESIGN §13), as it asked the
    #: runtime for it; None when it chose none or the chore runs an agent of the operator's own, and on a run from
    #: before canopy recorded it.
    model: str | None


@dataclass(frozen=True)
class FindingDismissal(Row):
    """A chore's finding the operator dismissed (DESIGN §19)."""

    TABLE: ClassVar[LiteralString] = "finding_dismissals"

    chore: str
    finding_id: str
    dismissed_at: str
    channel: str
