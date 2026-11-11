"""The API's types for the runtime's sessions (DESIGN §13): every session it keeps, listed and found by its title.

Built on `schema.Model`, as every API type is (schema/__init__.py). A title is untrusted text, whatever the runtime
made of a session's first words or a run named it: the UI renders it as text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type SessionsWhose = Annotated[
    Literal["outside", "canopy"],
    Field(
        description="Whose sessions a list holds: `outside`, those outside canopy, the operator's own and another "
        "workspace's runs; `canopy`, this workspace's runs' and their subagents'.",
    ),
]
type SessionsSearch = Annotated[
    Literal["off", "titles"],
    Field(description="What `sessions.search` keeps: `off`, no title, so nothing is listed; `titles`, every title."),
]
type SessionRunKind = Annotated[
    Literal["tick", "run", "chore_run", "review", "task_run", "epic_run"],
    Field(
        description="What made one of canopy's sessions: a tick's overseer, a worker or plan run, a chore run, a "
        "review run, a task's run, or an epic's plan run.",
    ),
]
type SessionsReadStatus = Annotated[
    Literal["found", "missing", "failed"],
    Field(
        description="How the loop's last read of the runtime's record ended: `missing` when the runtime keeps no "
        "session yet, `failed` with canopy's words for why.",
    ),
]


class SessionRun(Model):
    """The run of canopy's that made a session, or the session a subagent of it ran for, and the page it opens."""

    kind: SessionRunKind
    """What it is."""
    id: int
    """Its id among its kind."""
    ticket_key: str | None = None
    """The ticket a worker, plan, or review run worked for."""
    chore: str | None = None
    """A chore run's chore, which names its page."""
    task_id: int | None = None
    """A task run's task, which names its page."""
    epic_id: int | None = None
    """An epic run's epic, whose page lists it."""


class RuntimeSession(Model):
    """A session the runtime keeps, as the list shows it."""

    session_id: str
    """The runtime's id for it."""
    parent_id: str | None = None
    """The session it ran for, as a subagent; None for a session of its own."""
    title: str | None = None
    """Its title, on one line, bounded, nothing hidden in it: untrusted text. None when it has none, or was not read
    since titles were kept."""
    directory: str
    """Where it ran: its working directory, as the runtime recorded it."""
    started_at: datetime
    """When it started."""
    updated_at: datetime
    """When the runtime last updated it."""
    cost_usd: float
    """What it cost, in US dollars, as the runtime reported it."""
    archived: bool
    """Whether the runtime archived it, so its own list leaves it out."""
    made_by: SessionRun | None = None
    """For one of canopy's, the run that made it; None for one outside, or one no run names."""
    reopen: str | None = None
    """For one outside canopy, the shell line that reopens it in the runtime, in its directory, to copy."""
    subagents: list[RuntimeSession] = []
    """The sessions that ran for it as subagents, oldest first, each with its own; empty in a list found by words."""


class SessionsProgress(Model):
    """How far the loop's read of the runtime's record has come."""

    status: SessionsReadStatus | None = None
    """How the last read ended; None before the loop's first."""
    read_at: datetime | None = None
    """When the last read was; None before the loop's first."""
    error: str | None = None
    """canopy's words for why the last read failed; None unless it did."""
    through: datetime | None = None
    """The update of the last session read: every session updated before it was read. None before the first."""
    current: bool
    """Whether the read keeps titles as `sessions.exclude` now says: false until the loop's next read starts again
    from the first session under it."""


class SessionList(Model):
    """The runtime's sessions, newest first, or the newest whose title holds every word, and how far the read has come.

    While `sessions.search` is `off` it holds no session and no progress.
    """

    search: SessionsSearch
    """What `sessions.search` keeps."""
    whose: SessionsWhose
    """Whose sessions it holds."""
    words: list[str]
    """The words each title holds, as the query was split; empty for the whole list."""
    sessions: list[RuntimeSession]
    """The sessions, newest first, each a subagent's under the one it ran for unless found by words."""
    more: bool
    """Whether more sessions matched than it holds."""
    progress: SessionsProgress | None = None
    """How far the loop's read of the runtime's record has come; None while `sessions.search` is `off`."""
