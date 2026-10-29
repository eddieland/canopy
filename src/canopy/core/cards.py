"""A running agent's card: where its work stands, in its own words, while it runs (DESIGN §41).

A worker, a planner, or a reviewer says where its work stands by calling canopy's `status` tool, each call its whole
card: a summary, what it does now, what is done with the proof of each, what is next, what is in its way, and the work
as steps, each with its status and stage. The harness reads the call from the events the agent prints, as it reads the
agent's spend, holds it to the tool's own input, and records it on the run, with how many tool calls the agent had made
by then and when each step last changed; a call that does not validate, or that ended in an error, records nothing. So
nothing the agent writes reaches the journal but what canopy observes it print (TRUST_MODEL T1). The card is shown to
the operator, and given to no agent.

The run keeps its last card once it ends. A card is as old as the time and the tool calls since it was recorded. Its
steps say how much of the work is finished, and a step left `working` for a fifth of the run's timeout is shown stuck.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError

from canopy.core import db, items, records, sql
from canopy.infra import text
from canopy.runtime import servers

if TYPE_CHECKING:
    from collections.abc import Sequence

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

#: How long the summary and what is in the way may be, every other line, and a step's stage, in characters.
MAX_SUMMARY = 400
MAX_LINE = 200
MAX_STAGE = 60
#: How many steps `done`, `next`, and `steps` may each hold.
MAX_STEPS = 20
#: How many tool calls, or minutes, a running run may go with no update to its card before the card is shown stale.
#: canopy's plugin asks the agent for one at the same count of calls (`.agents/plugins/canopy.js`, DESIGN §41).
STALE_CALLS = 20
STALE_MINUTES = 10
#: A running run's step left `working`, with the same stage, for this share of the run's timeout is shown stuck.
STUCK_SHARE = 5

#: Where a step on a card stands.
type StepStatus = Literal["not_started", "working", "blocked", "done", "skipped"]
#: The statuses of a step that needs no more work, which count toward a card's percent done.
FINISHED: frozenset[StepStatus] = frozenset({"done", "skipped"})


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
#: A step's stage: a short line, such as `tests` or `review`.
Stage = Annotated[StrictStr, Field(max_length=MAX_STAGE), AfterValidator(_line)]


class Done(BaseModel):
    """A finished step, with what shows it is done."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    step: Line = Field(description="What was done.")
    proof: Line = Field(description='What shows it, such as "tests pass: 42/42", "pushed abc123", or "not pushed".')


class Step(BaseModel):
    """A step of the work as the agent tracks it: what it is, where it stands, and the stage it belongs to."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    title: Line = Field(description="The step, as the plan or your own checklist names it.")
    status: StepStatus = Field(description="Where it stands.")
    stage: Stage | None = Field(default=None, description="The stage it belongs to, such as `tests`; else omit it.")


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
        max_length=MAX_STEPS,
        description="The whole work as steps, in order, each with its status: the same steps each call, as they move.",
    )


@dataclass(frozen=True)
class StepTimes:
    """When a step on a run's card last changed, as the harness keeps it beside the card."""

    #: When a card first gave the step its status and stage.
    since: datetime
    #: For a `working` step, when it is shown stuck if nothing changes, a fifth of the run's timeout after `since`;
    #: None for any other step.
    stuck_at: datetime | None


@dataclass(frozen=True)
class Standing:
    """A run's card as it stands, with how old it is."""

    #: The card; None when the run has recorded none.
    card: Card | None
    #: When it was recorded; None with no card.
    at: datetime | None
    #: The tool calls the agent ended since: since the run started, with no card.
    calls_since: int
    #: When each of the card's steps last changed, in its order; empty with no steps, or none kept for them.
    steps: Sequence[StepTimes] = ()


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


def stuck_after(timeout_minutes: int) -> timedelta:
    """How long a step of a run whose timeout is `timeout_minutes` may stay `working` before it is shown stuck.

    Returns:
        A fifth of the timeout.
    """
    return timedelta(minutes=timeout_minutes) / STUCK_SHARE


def record_call(
    conn: sqlite3.Connection,
    table: CardTable,
    run_id: int,
    card: Card | None,
    *,
    stuck_after: timedelta,
) -> None:
    """Count one tool call the running run `run_id` of `table` ended, and record `card` as its card if given.

    Each of the card's steps keeps when it last changed: one the last card had, by its title, with the same status and
    stage keeps its times, and any other starts now, a `working` one to be shown stuck `stuck_after` later, a fifth of
    the run's timeout (`stuck_after()`). Nothing changes for a run not running.
    """
    running = sql.update(table).where("id = ? AND status = 'running'", run_id)
    counted = running.set_to("tool_calls = tool_calls + 1")
    with db.transaction(conn):
        if card is not None:
            at = db.now()
            moment = db.parse_time(at)
            kept = _steps_json(_kept_steps(_last(conn, table, run_id), card, moment, stuck_after), moment)
            # Every assignment reads the row as it was, so the card's count is the calls made with this one.
            counted = counted.set(card_json=card.model_dump_json(), card_at=at, card_steps_json=kept)
            counted = counted.set_to("card_calls = tool_calls + 1")
        sql.execute(conn, counted)


def of(row: sqlite3.Row | records.Row) -> Standing:
    """A run's card as its row records it, with how old it is.

    A card the journal holds that no longer reads as one, as after a change to its bounds, is shown as none.

    Returns:
        The card, when it was recorded, the tool calls since, and when each of its steps last changed.
    """
    values = records.columns(row)
    calls = int(values["tool_calls"] or 0)
    raw = values["card_json"]
    card = _parsed(str(raw)) if raw is not None else None
    if card is None or values["card_at"] is None:
        return Standing(None, None, calls)
    at = db.parse_time(str(values["card_at"]))
    steps = _steps_kept(values["card_steps_json"], card, at)
    return Standing(card, at, max(calls - int(values["card_calls"] or 0), 0), steps)


def percent_done(card: Card) -> int | None:
    """How much of the card's work is finished: its steps `done` or `skipped`, over all its steps.

    A skipped step needs no more work, so it counts as finished. Rounded down, so 100 means every step is.

    Returns:
        The percent, from 0 to 100; None for a card with no steps.
    """
    if not card.steps:
        return None
    return 100 * _finished(card) // len(card.steps)


def working(card: Card) -> Step | None:
    """The step the card says the agent works on: its first `working` step.

    Returns:
        The step, or None when none is working.
    """
    return next((step for step in card.steps if step.status == "working"), None)


def stuck(standing: Standing, now: datetime | None = None) -> list[tuple[Step, StepTimes]]:
    """The `working` steps of a running run's card past their time: a fifth of the run's timeout without a change.

    Returns:
        Each such step with its times, in the card's order.
    """
    if standing.card is None or len(standing.steps) != len(standing.card.steps):
        return []
    moment = now or datetime.now(UTC)
    paired = zip(standing.card.steps, standing.steps, strict=True)
    return [(s, t) for s, t in paired if s.status == "working" and t.stuck_at is not None and moment >= t.stuck_at]


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
        `now: <now>  card 3m, 4 calls old`, marked `stale` when it is, then with steps how far they are, as
        `steps 42% of 7, stage tests, 1 stuck`; `no card, 12m and 30 calls in` for a run with none once that is stale;
        else None.
    """
    stale = is_stale(standing, started_at, now)
    mark = "  stale" if stale else ""
    if standing.card is None or standing.at is None:
        if not stale:
            return None
        return f"no card, {items.age(started_at, now)} and {_calls(standing.calls_since)} in"
    age = items.age(db.format_time(standing.at), now)
    said = f"now: {text.one_line(standing.card.now)}  card {age}, {_calls(standing.calls_since)} old{mark}"
    steps = _steps_line(standing, now)
    return f"{said}  {steps}" if steps else said


def lines(standing: Standing, *, started_at: str, running: bool, now: datetime | None = None) -> list[str]:
    """A run's whole card, for `canopy show`: how old it is, then each field on a line of its own.

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
    found.extend(_step_lines(standing, running=running, now=now))
    found.extend(f"    done: {d.step} ({d.proof})" for d in card.done)
    found.extend(f"    next: {step}" for step in card.next)
    if card.stuck is not None:
        found.append(f"    stuck: {card.stuck}")
    return found


def _finished(card: Card) -> int:
    return sum(step.status in FINISHED for step in card.steps)


def _steps_line(standing: Standing, now: datetime | None) -> str:
    """A running card's steps on one line.

    Returns:
        `steps 42% of 7, stage tests, 1 stuck`; empty with no steps.
    """
    card = standing.card
    percent = percent_done(card) if card is not None else None
    if card is None or percent is None:
        return ""
    found = f"steps {percent}% of {len(card.steps)}"
    at = working(card)
    if at is not None and at.stage is not None:
        found += f", stage {at.stage}"
    late = len(stuck(standing, now))
    return f"{found}, {late} stuck" if late else found


def _step_lines(standing: Standing, *, running: bool, now: datetime | None) -> list[str]:
    """A card's steps, for `canopy show`.

    Returns:
        How far they are, then each with its status and stage, and how long it has been stuck if it is; none with no
        steps.
    """
    card = standing.card
    percent = percent_done(card) if card is not None else None
    if card is None or percent is None:
        return []
    head = f"    steps: {_finished(card)} of {len(card.steps)} finished, {percent}%"
    at = working(card)
    if at is not None and at.stage is not None:
        head += f"; stage {at.stage}"
    late = {id(step): times for step, times in stuck(standing, now)} if running else {}
    found = [head]
    for step in card.steps:
        stage = f" ({step.stage})" if step.stage is not None else ""
        times = late.get(id(step))
        mark = f"  stuck {items.age(db.format_time(times.since), now)}" if times is not None else ""
        found.append(f"    step {step.status}{stage}: {step.title}{mark}")
    return found


def _calls(count: int) -> str:
    return "1 call" if count == 1 else f"{count} calls"


def _parsed(raw: str) -> Card | None:
    try:
        return Card.model_validate_json(raw)
    except ValidationError:
        return None


def _last(conn: sqlite3.Connection, table: CardTable, run_id: int) -> tuple[Card | None, Sequence[StepTimes]]:
    """What the run `run_id` of `table` holds now of its card.

    Returns:
        The card, None with none, and when each of its steps last changed.
    """
    query = sql.select("card_json, card_at, card_steps_json").from_(table).where("id = ?", run_id)
    row = sql.execute(conn, query).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None, ()
    card = _parsed(str(row[0]))
    return (card, _steps_kept(row[2], card, db.parse_time(str(row[1])))) if card is not None else (None, ())


def _kept_steps(
    last: tuple[Card | None, Sequence[StepTimes]],
    card: Card,
    at: datetime,
    stuck_after: timedelta,
) -> tuple[StepTimes, ...]:
    """When each of `card`'s steps last changed, recorded at `at` after the `last` card and its steps' times.

    Returns:
        A step's times, for each of its steps: those of the step the last card had by its title, if it had the same
        status and stage then; else starting at `at`.
    """
    before, times = last
    earlier: dict[str, tuple[Step, StepTimes]] = {}
    if before is not None and len(before.steps) == len(times):
        for step, kept in zip(before.steps, times, strict=True):
            earlier.setdefault(step.title, (step, kept))
    found: list[StepTimes] = []
    for step in card.steps:
        prior = earlier.pop(step.title, None)
        if prior is not None and (prior[0].status, prior[0].stage) == (step.status, step.stage):
            found.append(prior[1])
        else:
            found.append(StepTimes(at, at + stuck_after if step.status == "working" else None))
    return tuple(found)


class _Kept(BaseModel):
    """How the journal keeps a step's times: in seconds from its card's, so they move with the card's time."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    #: How long before its card was recorded the step took its status and stage.
    held: float
    #: For a `working` step, how long after that it is shown stuck; None for any other step.
    stuck_after: float | None = None


#: A card's steps' times, as the journal keeps them.
_KEPT: TypeAdapter[tuple[_Kept, ...]] = TypeAdapter(tuple[_Kept, ...])


def _steps_json(times: Sequence[StepTimes], at: datetime) -> str:
    """The times of the steps of a card recorded at `at`, as the journal keeps them.

    Returns:
        Its `card_steps_json`.
    """
    kept = (
        _Kept(
            held=(at - t.since).total_seconds(),
            stuck_after=None if t.stuck_at is None else (t.stuck_at - t.since).total_seconds(),
        )
        for t in times
    )
    return json.dumps([k.model_dump() for k in kept])


def _steps_kept(raw: object, card: Card, at: datetime) -> tuple[StepTimes, ...]:
    """The times the journal keeps of `card`'s steps, recorded at `at`, from `raw`, its `card_steps_json`.

    Returns:
        A step's times for each step; none when it keeps none, or not one for each step.
    """
    if raw is None:
        return ()
    try:
        kept = _KEPT.validate_json(str(raw))
    except ValidationError:
        return ()
    if len(kept) != len(card.steps):
        return ()
    times = ((at - timedelta(seconds=k.held), k.stuck_after) for k in kept)
    return tuple(StepTimes(since, None if late is None else since + timedelta(seconds=late)) for since, late in times)
