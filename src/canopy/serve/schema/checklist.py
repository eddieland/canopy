"""The API's types for the checklists (DESIGN §42): each repository's list, and how worker runs answered it.

The lists as the operator's files hold them now; and what `canopy checklist` prints, with the runs behind each item's
`held` and `fixed` answers, and the counts by week. Built on `schema.Model`, as every API type is (schema/__init__.py).
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


class ChecklistPrevious(Model):
    """The window before the counts', as many days and ending where it starts: its totals over every item alone."""

    since: datetime
    """When it starts: local midnight on its first day."""
    until: datetime
    """When it ends: where the counts' window starts."""
    reminded: int
    """How many times its runs were given an item, over every item counted."""
    held: int
    """Of those, how many answered `held`."""
    unanswered: int
    """Of those, how many said nothing of it."""


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
    previous: ChecklistPrevious
    """The window before this one, as many days, `repo`'s alone when it is named, for a page to say how this one
    compares."""


type ChecklistSeverity = Annotated[
    Literal["blocking", "major", "minor"],
    Field(description="How much an item that fails weighs in a checklist review, as a review's finding does."),
]


class ChecklistItem(Model):
    """One item of a repository's list, as the operator wrote it: a rule asked of a worker's diff."""

    id: str
    """The item's id, unique in its list, which a run's answer names."""
    paths: list[str]
    """The paths from the repository's root it is about, each compared as a `high_impact_paths` entry is; empty for
    every path."""
    severity: ChecklistSeverity
    """Its `severity:` line's, else `minor`."""
    rule: str
    """The rule in the operator's words, Markdown, with what passes and what fails."""


class RepoChecklist(Model):
    """A mapped repository's list, as the next worker run in it would be given it, read when the page asked."""

    repo: str
    """The repository's name, as the workspace map has it."""
    file: str | None
    """Where its list's file is, or would be: `<repo>.md` in `paths.checklists`; None when that is unset."""
    items: list[ChecklistItem]
    """Its list's items, in its order; empty when it has none, or one canopy cannot use (`error`)."""
    error: str | None = None
    """Why canopy cannot use its file, which refuses the repository's runs as `bad_prompt`; None when it can, or
    there is none."""


class ChecklistList(Model):
    """Each mapped repository's checklist, as the operator's `paths.checklists` holds them now (DESIGN §42).

    Read from the files when asked, as each run reads them, so an edit shows with no reload. Nothing here changes them.
    """

    directory: str | None
    """`paths.checklists`: the operator's directory of lists; None when it is unset, and no repository is asked."""
    repos: list[RepoChecklist]
    """Each repository of the workspace map, in its order, with its list or none."""
