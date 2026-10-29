"""A running agent's card: where its work stands, in its own words, while it runs (DESIGN §41).

A worker, a planner, or a reviewer says where its work stands by calling canopy's `status` tool, each call its whole
card: a summary, what it does now, what is done with the proof of each, what is next, and what is in its way. The
harness reads the call from the events the agent prints, as it reads the agent's spend, holds it to the tool's own
input, and records it on the run, with how many tool calls the agent had made by then; a call that does not validate,
or that ended in an error, records nothing. So nothing the agent writes reaches the journal but what canopy observes it
print (TRUST_MODEL T1). The card is shown to the operator, and given to no agent.

The run keeps its last card once it ends. A card is as old as the time and the tool calls since it was recorded.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, ValidationError

from canopy.core import db, records, sql
from canopy.runtime import servers

if TYPE_CHECKING:
    from datetime import datetime

    from canopy.runtime.report import Called

#: The server of the `status` tool, as a run's inline config names it, and the tool: the agent sees it as
#: `canopy_run_status`.
SERVER = "canopy_run"
TOOL = "status"
#: How the runtime starts the server: this interpreter's canopy, which `-P` keeps off the working directory's modules
#: (TRUST_MODEL T7).
SERVER_COMMAND = (sys.executable, "-P", "-m", "canopy", "_mcp", "--status")
#: A run's CANOPY_RUN_ID that names a run keeping a card: a worker's or a planner's id, or a review's, `review-7`.
RUN_ID_RE = re.compile(r"(?:review-)?[0-9]{1,18}")
#: The run tables whose runs keep a card: a worker's and a planner's, and a review's.
type CardTable = Literal["runs", "review_runs"]

#: How long the summary and what is in the way may be, and every other line, in characters.
MAX_SUMMARY = 400
MAX_LINE = 200
#: How many steps `done` and `next` may each hold.
MAX_STEPS = 20


def _line(value: str) -> str:
    """One line of a card: control characters made spaces, whitespace collapsed, and not empty.

    Returns:
        The line.

    Raises:
        ValueError: Nothing printable is left.
    """
    line = " ".join("".join(c if c.isprintable() else " " for c in value).split())
    if not line:
        raise ValueError("must not be empty")
    return line


#: A line of a card: plain text, held to `MAX_LINE` characters before its whitespace is collapsed.
Line = Annotated[StrictStr, Field(max_length=MAX_LINE), AfterValidator(_line)]


class Done(BaseModel):
    """A finished step, with what shows it is done."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    step: Line = Field(description="What was done.")
    proof: Line = Field(description='What shows it, such as "tests pass: 42/42", "pushed abc123", or "not pushed".')


class Card(BaseModel):
    """The input of a `status` call, the agent's whole card: each call replaces the one before."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    summary: Annotated[StrictStr, Field(max_length=MAX_SUMMARY), AfterValidator(_line)] = Field(
        description="Where the work stands, in one or two sentences, for someone who skipped the transcript.",
    )
    now: Line = Field(description="What you are doing this moment.")
    done: tuple[Done, ...] = Field(
        default=(),
        max_length=MAX_STEPS,
        description="The steps finished so far, in order, each with its proof.",
    )
    next: tuple[Line, ...] = Field(default=(), max_length=MAX_STEPS, description="What is left, in order.")
    stuck: Annotated[StrictStr, Field(max_length=MAX_SUMMARY), AfterValidator(_line)] | None = Field(
        default=None,
        description="What is in your way that you are working around, such as CI down or a flaky test; else omit it.",
    )


@dataclass(frozen=True)
class Standing:
    """A run's card as it stands, with how old it is."""

    #: The card; None when the run has recorded none.
    card: Card | None
    #: When it was recorded; None with no card.
    at: datetime | None
    #: The tool calls the agent ended since: since the run started, with no card.
    calls_since: int


def tool_name() -> str:
    """The name the agent, and the definitions' rules, know the tool by.

    Returns:
        `canopy_run_status`.
    """
    return servers.tool_name(SERVER, TOOL)


def read_call(called: Called) -> Card | None:
    """The card a tool call the agent made says, if it is a `status` call that completed and validates.

    Returns:
        The card, or None for any other call, a refused one, or one whose input is not a card.
    """
    if called.tool != tool_name() or not called.completed:
        return None
    try:
        return Card.model_validate(called.input)
    except ValidationError:
        return None


def record_call(conn: sqlite3.Connection, table: CardTable, run_id: int, card: Card | None) -> None:
    """Count one tool call the running run `run_id` of `table` ended, and record `card` as its card if given.

    Nothing changes for a run not running.
    """
    running = sql.update(table).where("id = ? AND status = 'running'", run_id)
    counted = running.set_to("tool_calls = tool_calls + 1")
    if card is not None:
        # Every assignment reads the row as it was, so the card's count is the calls made with this one.
        counted = counted.set(card_json=card.model_dump_json(), card_at=db.now()).set_to("card_calls = tool_calls + 1")
    with db.transaction(conn):
        sql.execute(conn, counted)


def of(row: sqlite3.Row | records.Row) -> Standing:
    """A run's card as its row records it, with how old it is.

    A card the journal holds that no longer reads as one, as after a change to its bounds, is shown as none.

    Returns:
        The card, when it was recorded, and the tool calls since.
    """
    values = records.columns(row)
    calls = int(values["tool_calls"] or 0)
    raw = values["card_json"]
    card = _parsed(str(raw)) if raw is not None else None
    if card is None or values["card_at"] is None:
        return Standing(None, None, calls)
    at = db.parse_time(str(values["card_at"]))
    return Standing(card, at, max(calls - int(values["card_calls"] or 0), 0))


def _parsed(raw: str) -> Card | None:
    try:
        return Card.model_validate_json(raw)
    except ValidationError:
        return None
