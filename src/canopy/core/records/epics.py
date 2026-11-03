"""Epics: work spanning several tickets, the operator's own subject (DESIGN §43).

Each epic, the repositories its plan reads, and its member tickets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row


@dataclass(frozen=True)
class Epic(Row):
    """An epic the operator submitted (DESIGN §43): their goal, and where its tickets come from."""

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
