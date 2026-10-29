"""A running agent's card: where its work stands, in its own words, while it runs (DESIGN §41).

A worker, a planner, or a reviewer says where its work stands by calling canopy's `status` tool, each call its whole
card: a summary, what it does now, what is done with the proof of each, what is next, what is in its way, and, for a
long job, its steps, each with a status and a stage, from which canopy says how much is done. The
harness reads the call from the events the agent prints, as it reads the agent's spend, holds it to the tool's own
input, and records it on the run, with how many tool calls the agent had made by then; a call that does not validate,
or that ended in an error, records nothing. So nothing the agent writes reaches the journal but what canopy observes it
print (TRUST_MODEL T1). The card is shown to the operator, and given to no agent.

The run keeps its last card once it ends. A card is as old as the time and the tool calls since it was recorded. A step
is as old as the first card on which it was working: one working longer than the run's last fifth is shown stuck.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, ValidationError

from canopy.core import db, items, records, sql
from canopy.infra import text
from canopy.runtime import servers

if TYPE_CHECKING:
    from collections.abc import Mapping

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
#: How many steps `done` and `next` may each hold, and how many `steps` may.
MAX_STEPS = 20
MAX_PLAN_STEPS = 40
#: A step's status, on the card's `steps`.
type StepStatus = Literal["not_started", "working", "blocked", "done", "skipped"]
#: The share of a run's time limit a step may stay working before it is shown stuck: its last fifth's length.
STUCK_SHARE = 5
#: How many tool calls, or minutes, a running run may go with no update to its card before the card is shown stale.
#: canopy's plugin asks the agent for one at the same count of calls (`.agents/plugins/canopy.js`, DESIGN §41).
STALE_CALLS = 20
STALE_MINUTES = 10


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


class Step(BaseModel):
    """One step of a long job, with where it stands."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    title: Line = Field(description="The step, as its plan names it when there is one.")
    status: StepStatus = Field(description="Where it stands.")
    stage: Line | None = Field(
        default=None,
        description="The stage it belongs to, such as the plan's section, or what part of it is under way; or omit it.",
    )


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
    steps: tuple[Step, ...] = Field(
        default=(),
        max_length=MAX_PLAN_STEPS,
        description="For a long job, every step in order, each with its status: the approved plan's when there is one.",
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
    #: When each of the card's working steps was first seen working, by title.
    working_since: Mapping[str, datetime] = field(default_factory=dict)


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

    Each of the card's working steps keeps the time it was first seen working on an earlier card, if it was working
    on the last; one newly working starts now. Nothing changes for a run not running.
    """
    running = sql.update(table).where("id = ? AND status = 'running'", run_id)
    counted = running.set_to("tool_calls = tool_calls + 1")
    with db.transaction(conn):
        if card is not None:
            at = db.now()
            # Every assignment reads the row as it was, so the card's count is the calls made with this one.
            counted = counted.set(card_json=card.model_dump_json(), card_at=at).set_to("card_calls = tool_calls + 1")
            counted = counted.set(card_working_since=_working_since(conn, table, run_id, card, at))
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
    since = _since(values["card_working_since"])
    return Standing(card, at, max(calls - int(values["card_calls"] or 0), 0), since)


def percent(card: Card) -> int | None:
    """How much of a card's steps is done: its `done` steps' share of those not skipped, rounded down.

    Returns:
        The percent, or None for a card with no steps, or whose every step is skipped.
    """
    counted = [s for s in card.steps if s.status != "skipped"]
    if not counted:
        return None
    return 100 * sum(s.status == "done" for s in counted) // len(counted)


def working_stage(card: Card) -> str | None:
    """The stage of a card's first working step.

    Returns:
        The stage, or None when no step is working or the first working one names none.
    """
    return next((s.stage for s in card.steps if s.status == "working"), None)


def stuck_at(standing: Standing, title: str, timeout_minutes: int) -> datetime | None:
    """When a working step is shown stuck: once it has been working longer than the run's last fifth.

    Returns:
        The time, or None for a step not working on the card.
    """
    since = standing.working_since.get(title)
    return since + timedelta(minutes=timeout_minutes / STUCK_SHARE) if since is not None else None


def is_stale(standing: Standing, started_at: str, now: datetime | None = None) -> bool:
    """Whether a running run's card has gone `STALE_CALLS` tool calls or `STALE_MINUTES` without an update.

    A run with no card counts from its start.

    Returns:
        True when it is stale.
    """
    since = standing.at or db.parse_time(started_at)
    late = (now or datetime.now(UTC)) - since >= timedelta(minutes=STALE_MINUTES)
    return late or standing.calls_since >= STALE_CALLS


def doing(standing: Standing, started_at: str, now: datetime | None = None) -> str | None:
    """A running run's card on one line, for `canopy status`: what it does now, and how old the card is.

    Returns:
        `now: <now>  card 3m, 4 calls old`, marked `stale` when it is; `no card, 12m and 30 calls in` for a run with
        none once that is stale; else None.
    """
    stale = is_stale(standing, started_at, now)
    mark = "  stale" if stale else ""
    if standing.card is None or standing.at is None:
        if not stale:
            return None
        return f"no card, {items.age(started_at, now)} and {_calls(standing.calls_since)} in"
    age = items.age(db.format_time(standing.at), now)
    doing = f"now: {text.one_line(standing.card.now)}{_progress(standing.card)}"
    return f"{doing}  card {age}, {_calls(standing.calls_since)} old{mark}"


def lines(
    standing: Standing,
    *,
    started_at: str,
    running: bool,
    timeout_minutes: int,
    now: datetime | None = None,
) -> list[str]:
    """A run's whole card, for `canopy show`: how old it is, then each field on a line of its own, then its steps.

    A step of a running run is marked stuck once it has worked longer than the last fifth of `timeout_minutes`.

    Returns:
        The lines, indented; one saying there is none for a run with no card.
    """
    card = standing.card
    if card is None or standing.at is None:
        return ["  no card"]
    if running:
        stale = "  stale" if is_stale(standing, started_at, now) else ""
        head = f"  card, {items.age(db.format_time(standing.at), now)} and {_calls(standing.calls_since)} old{stale}"
    else:
        head = f"  last card, {db.format_time(standing.at)}, {_calls(standing.calls_since)} before the run ended"
    found = [head, f"    {card.summary}", f"    now: {card.now}"]
    found.extend(f"    done: {d.step} ({d.proof})" for d in card.done)
    found.extend(f"    next: {step}" for step in card.next)
    if card.stuck is not None:
        found.append(f"    stuck: {card.stuck}")
    if card.steps:
        found.append(f"    steps:{_progress(card)}")
    moment = now or datetime.now(UTC)
    for step in card.steps:
        stage = f" ({step.stage})" if step.stage is not None else ""
        due = stuck_at(standing, step.title, timeout_minutes) if running else None
        late = "  stuck" if due is not None and moment >= due else ""
        found.append(f"      {_MARKS[step.status]} {step.title}{stage}{late}")
    return found


#: How `canopy show` marks a step by its status.
_MARKS: Mapping[StepStatus, str] = {
    "not_started": "[ ]",
    "working": "[>]",
    "blocked": "[!]",
    "done": "[x]",
    "skipped": "[-]",
}


def _progress(card: Card) -> str:
    """How much of a card's steps is done, and the working one's stage, to follow a line; empty with no steps.

    Returns:
        `  40% done, stage tests`, or less as the card says less.
    """
    done = percent(card)
    if done is None:
        return ""
    stage = working_stage(card)
    return f"  {done}% done" + (f", stage {text.one_line(stage)}" if stage is not None else "")


def _working_since(conn: sqlite3.Connection, table: CardTable, run_id: int, card: Card, at: str) -> str | None:
    """Each working step of `card`, by title, with when it was first seen working: on the run's last card, else `at`.

    Returns:
        The times as JSON, or None when no step is working.
    """
    row = sql.execute(conn, sql.select("card_working_since").from_(table).where("id = ?", run_id)).fetchone()
    before = {title: db.format_time(when) for title, when in _since(row[0] if row is not None else None).items()}
    working = {s.title: before.get(s.title, at) for s in card.steps if s.status == "working"}
    return json.dumps(working) if working else None


def _since(raw: object) -> dict[str, datetime]:
    """The times a row's `card_working_since` holds, by step title.

    Returns:
        The times; none where it holds none, and none of those that do not read as one.
    """
    if not isinstance(raw, str):
        return {}
    try:
        found = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(found, dict):
        return {}
    times: dict[str, datetime] = {}
    for title, when in found.items():
        if isinstance(title, str) and isinstance(when, str):
            try:
                times[title] = db.parse_time(when)
            except ValueError:
                continue
    return times


def _calls(count: int) -> str:
    return "1 call" if count == 1 else f"{count} calls"


def _parsed(raw: str) -> Card | None:
    try:
        return Card.model_validate_json(raw)
    except ValidationError:
        return None
