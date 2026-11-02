"""The tickets canopy works, and their work in each repository.

Each ticket, its unit of work in each repository, and the tickets its runs filed (DESIGN §6, §18, D058).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    Phase,
    PlanSetting,
)


@dataclass(frozen=True)
class Ticket(Row):
    """A ticket canopy has seen (DESIGN §6): its own phase, branch, and cursors, and where any forget left it."""

    TABLE: ClassVar[LiteralString] = "tickets"

    key: str
    # The workspace root.
    repo: str
    first_seen_at: str
    last_seen_at: str
    # The ticket's own last derived phase, for display only; never read as truth.
    phase: Phase | None
    # Fixed by its first implement, and the same in every unit.
    branch: str | None
    #: The comment cursor of a ticket no `tracker` source observed, the tracker's comment id: unread since config
    #: required one (DESIGN §39), and kept, since no migration drops a column.
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
    #: The comment cursor, a journal number (DESIGN §35).
    comment_cursor: int | None


@dataclass(frozen=True)
class FollowUp(Row):
    """A follow-up ticket a public worker filed and its validated result reported, worked under its parent (§18)."""

    TABLE: ClassVar[LiteralString] = "follow_ups"

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
class TicketUnit(Row):
    """A ticket's work in one repository (D058): its branch, PR, and phase."""

    TABLE: ClassVar[LiteralString] = "ticket_units"

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
class SplitChild(Row):
    """A ticket a split run filed, and the ticket it was split from."""

    TABLE: ClassVar[LiteralString] = "split_children"

    child_key: str
    parent_key: str
    repo: str
    run_id: int
