"""Initiatives: work spanning several tickets, the operator's own subject (DESIGN §43).

Each initiative, the repositories its plan reads, and its member tickets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row


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
