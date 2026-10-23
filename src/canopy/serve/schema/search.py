"""The API's types for search (DESIGN §22, Search): a search's hits and where each opens.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type SearchSource = Annotated[
    Literal["ticket", "task", "message", "chore_run", "decision", "tick"],
    Field(description="Where a search hit is (DESIGN §22, Search), in the order the search reads them."),
]


class SearchHit(Model):
    """One row holding every word of a search, and where it opens."""

    source: SearchSource
    """What the row is."""
    at: datetime
    """The row's time: when it was recorded, started, or last active."""
    snippet: str
    """The field that matched, on one line, cut around its first match: untrusted text."""
    ticket_key: str | None = None
    """The ticket a hit is, or whose message or decision it is."""
    chore: str | None = None
    """The chore a run, note, or decision is about."""
    task_id: int | None = None
    """The one-off task a hit is, or whose message it is (DESIGN §36)."""
    task_title: str | None = None
    """That task's first line that holds anything, on one line and cut short: the operator's text, still untrusted."""
    run_id: int | None = None
    """The run that reported a message (a task's run, for a task's message), or a chore run's own id."""
    tick_id: int | None = None
    """A tick, or the tick that recorded a decision."""
    label: str | None = None
    """A fixed word: a message's kind (`note` for a chore's), a decision's action, a status, or a ticket's phase."""


class SearchResults(Model):
    """A search: the words it looked for, its hits by source and newest first, and the sources that had more."""

    words: list[str]
    """The words it looked for, as it split the query."""
    hits: list[SearchHit]
    """Its hits, at most 20 a source, by source and newest first."""
    more: list[SearchSource]
    """The sources that held more hits than it returned."""
