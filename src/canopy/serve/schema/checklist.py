"""The API's types for the checklist's counts (DESIGN §42): how worker runs answered each repository's list.

What `canopy checklist` prints, with the runs behind each item's `held` and `fixed` answers, and the counts by week.
Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type AnsweringRun = Annotated[
    Literal["run", "task"],
    Field(description="Whose run gave a checklist answer: a worker's, or a one-off task's (DESIGN §36)."),
]


class ChecklistRun(Model):
    """A run of the window that gave an item an answer: a worker's or a task's, with the reason it held it."""

    kind: AnsweringRun
    """Whose run it is."""
    id: int
    """The run's id: a worker run's, or the task's run's."""
    task_id: int | None
    """The task a task's run is of; None for a worker's."""
    started_at: datetime
    """When it started, by which the window holds it."""
    reason: str | None
    """Why it left the item failing, for a `held` answer: the worker's words, untrusted, on one line and cut as the
    health report cuts a note; its run's page has them whole. None for a `fixed` one."""


class ChecklistItemCounts(Model):
    """How the worker runs of a window answered one item of one repository's checklist, by answer.

    With the newest runs behind its `held` and `fixed` answers, and the reason each one held it.
    """

    repo: str
    """The repository whose list holds the item."""
    item: str
    """The item's id, as the operator's list names it: untrusted text, as every journal string is."""
    reminded: int
    """How many runs were given the item: each answered it, or is counted `unanswered`."""
    passed: int
    """How many answered `pass`: the diff held to the item as it was."""
    fixed: int
    """How many answered `fixed`: the diff did not, and the run committed the fix."""
    held: int
    """How many answered `held`: the diff does not, and the run left it so, for a reason it gave."""
    not_applicable: int
    """How many answered `n/a`: the item is about nothing the diff changes."""
    unanswered: int
    """How many said nothing of it in their result."""
    held_runs: list[ChecklistRun]
    """The runs that answered `held`, the newest first, at most twenty: `held` counts them all."""
    fixed_runs: list[ChecklistRun]
    """The runs that answered `fixed`, the newest first, at most twenty: `fixed` counts them all."""


class ChecklistWeek(Model):
    """How the runs that started in one local ISO week of the window answered one item, by answer."""

    repo: str
    """The repository whose list holds the item."""
    item: str
    """The item's id, as the operator's list names it: untrusted text."""
    week: str
    """The ISO week, `2026-W41`, of canopy's clock: Monday to Sunday. The window's first and last may be part weeks."""
    reminded: int
    """How many runs of the week were given the item; 0 for a week none was."""
    passed: int
    """How many answered `pass`."""
    fixed: int
    """How many answered `fixed`."""
    held: int
    """How many answered `held`."""
    not_applicable: int
    """How many answered `n/a`."""
    unanswered: int
    """How many said nothing of it."""


class ChecklistCounts(Model):
    """The answers of the worker runs that started in a window of whole local days, as `canopy checklist` counts them.

    Today's so far included, by when each run started; a run still running has recorded no answers yet.
    """

    since: datetime
    """When the window starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight after today."""
    days: int
    """How many days it spans."""
    repo: str | None = None
    """The one repository counted; None for every one."""
    items: list[ChecklistItemCounts]
    """A row per repository and item a run of the window was given: by repository, then each item in its list's
    order. Empty when no run of the window was given a list."""
    weeks: list[ChecklistWeek]
    """A row per item of `items` and ISO week the window touches, none skipped: the items in `items`' order, each
    one's weeks oldest first."""
