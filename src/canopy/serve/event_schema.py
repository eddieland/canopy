"""The API's types for the event stream (DESIGN §22): each message it sends, and the union that tells them apart.

Built on `schema.Model`, as every API type is (schema.py). A new event is a model here, in `StreamEvent`'s union
(ui/AGENTS.md).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, RootModel

from canopy.serve.chore_schema import ChoreSummary
from canopy.serve.review_schema import RequestedReview, ReviewSummary
from canopy.serve.schema import (
    AttentionItem,
    Capacity,
    MemoryState,
    Model,
    Pause,
    Run,
    Tick,
    TicketSummary,
    WorkerNotice,
)
from canopy.serve.spend_schema import Spend
from canopy.serve.task_schema import TaskSummary


class AttentionUpdated(Model):
    """The attention list changed. The payload is the whole list."""

    type: Literal["attention.updated"] = "attention.updated"
    """What the event is."""
    items: list[AttentionItem]
    """The attention list, as `GET /attention` returns it."""


class RunsUpdated(Model):
    """The runs changed. The payload is the whole list, as `GET /runs` returns it."""

    type: Literal["runs.updated"] = "runs.updated"
    """What the event is."""
    runs: list[Run]
    """The runs, as `GET /runs` returns them."""


class TicketsUpdated(Model):
    """The tickets list changed. The payload is the whole list, as `GET /tickets` returns it."""

    type: Literal["tickets.updated"] = "tickets.updated"
    """What the event is."""
    tickets: list[TicketSummary]
    """The tickets, as `GET /tickets` returns them."""


class ChoresUpdated(Model):
    """The chores changed: a run started or ended, or a note was added. The payload is the whole list."""

    type: Literal["chores.updated"] = "chores.updated"
    """What the event is."""
    chores: list[ChoreSummary]
    """The chores, as `GET /chores` returns them."""


class TasksUpdated(Model):
    """The tasks changed: one was submitted, replied to, or stopped, or a run of one started or ended. Whole."""

    type: Literal["tasks.updated"] = "tasks.updated"
    """What the event is."""
    tasks: list[TaskSummary]
    """The tasks, as `GET /tasks` returns them."""


class TaskChanged(Model):
    """Something about one task changed, its summary or its conversation: a page showing it reads it again."""

    type: Literal["task.changed"] = "task.changed"
    """What the event is."""
    id: int
    """The task's id, as `task:N` names it."""


class ReviewsUpdated(Model):
    """The review runs changed: one started or ended. The payload is the whole list, as `GET /reviews` returns it."""

    type: Literal["reviews.updated"] = "reviews.updated"
    """What the event is."""
    reviews: list[ReviewSummary]
    """The latest review runs, as `GET /reviews` returns them."""


class ReviewRequestsUpdated(Model):
    """The PRs waiting on a review changed: one was asked for or stopped, or its review started or failed. Whole."""

    type: Literal["review_requests.updated"] = "review_requests.updated"
    """What the event is."""
    requests: list[RequestedReview]
    """The open review requests no review is running for, as `GET /review-requests` returns them."""


class TicketChanged(Model):
    """Something about one ticket changed: a page showing it reads it again."""

    type: Literal["ticket.changed"] = "ticket.changed"
    """What the event is."""
    key: str
    """The ticket's key."""


class SpendUpdated(Model):
    """What a window cost changed. The payload is both windows, as `GET /spend` returns them."""

    type: Literal["spend.updated"] = "spend.updated"
    """What the event is."""
    spend: Spend
    """Both windows, as `GET /spend` returns them."""


class TickUpdated(Model):
    """A tick started or ended. The payload is what `GET /tick` returns: the latest tick, and what was acknowledged."""

    type: Literal["tick.updated"] = "tick.updated"
    """What the event is."""
    tick: Tick | None = None
    """The latest tick; None before the first."""
    acknowledged: int | None = None
    """The newest message the latest `ok` tick read; None before the first."""


class LoopUpdated(Model):
    """The loop was paused or resumed, a notice to workers was set, cleared, or lapsed, or a reload changed capacity.

    The payload is what `GET /loop` returns.
    """

    type: Literal["loop.updated"] = "loop.updated"
    """What the event is."""
    capacity: Capacity
    """What may run at once, from the config the loop serves."""
    paused: Pause | None = None
    """The pause; None when the loop is not paused."""
    notice: WorkerNotice | None = None
    """The notice to workers in force; None without one."""
    memory: MemoryState | None = None
    """Agent memory's tiers; None while both are off."""


class StreamEnding(Model):
    """The server ends this stream now, its `stream_seconds` up: the page opens another at once, missing nothing."""

    type: Literal["stream.ending"] = "stream.ending"
    """What the event is."""


class StreamEvent(
    RootModel[
        Annotated[
            AttentionUpdated
            | RunsUpdated
            | TicketsUpdated
            | TicketChanged
            | ChoresUpdated
            | TasksUpdated
            | TaskChanged
            | ReviewsUpdated
            | ReviewRequestsUpdated
            | SpendUpdated
            | TickUpdated
            | LoopUpdated
            | StreamEnding,
            Field(discriminator="type"),
        ]
    ],
):
    """One message on the event stream, told apart by its `type`. A named model so the UI's types get its name."""

    model_config = ConfigDict(frozen=True)
