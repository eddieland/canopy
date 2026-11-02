"""Agent memory.

The notes, proposals, and lessons, and what each run's prompt was rendered with (DESIGN §28).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    MemoryAuthor,
    MemoryCited,
    MemoryMode,
    MemoryScope,
    MemoryStatus,
)


@dataclass(frozen=True)
class Memory(Row):
    """A ticket's note, a worker's proposal, or the operator's lesson (DESIGN §28). `body` is None once forgotten."""

    TABLE: ClassVar[LiteralString] = "memories"

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

    TABLE: ClassVar[LiteralString] = "run_memory"

    run_id: int
    ticket_notes: MemoryMode
    proposals: MemoryMode
    # A JSON list of the entries refused from the run's result, each the field, the key if valid, and why.
    refused: str


@dataclass(frozen=True)
class MemoryRead(Row):
    """A memory rendered into a run's prompt (DESIGN §28)."""

    TABLE: ClassVar[LiteralString] = "memory_reads"

    run_id: int
    memory_id: int
    # What the run said of it; None when it cited it in neither list, and for every read from before runs were named.
    cited: MemoryCited | None
