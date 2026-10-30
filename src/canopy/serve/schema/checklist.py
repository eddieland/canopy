"""The API's types for the checklist's counts (DESIGN §42): how worker runs answered each repository's list.

What `canopy checklist` prints. Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime

from canopy.serve.schema import Model


class ChecklistItemCounts(Model):
    """How the worker runs of a window answered one item of one repository's checklist, by answer.

    Counts only: a `held` answer's reason is the worker's text, which stays on its run.
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
