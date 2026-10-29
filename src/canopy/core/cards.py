"""A running agent's status card (DESIGN §8, §27, ROADMAP M65): where its work stands, as it last said.

Every worker, planner, and reviewer run is given one tool of canopy's, `status`, by a server named `canopy_run` in its
inline config, `canopy _mcp --status`, which the runtime names `canopy_run_status`. The server validates a call against
`Card` and writes nothing. canopy records the card from the call as the run prints it: the reader of the agent's events
in `_run` and `_review` finds a completed call of the tool, validates its input again, and replaces the run's whole card
with it (`seen`). So nothing the agent writes reaches the journal but through what canopy observes it print, as its
spend does. Every other tool call the run completes counts on the card, so the card says how old it is in calls as in
minutes. The run keeps its last card after it ends.

A card is the agent's text, which may echo a ticket's or a PR's: each field is bounded plain text on one line, with no
hidden character, shown to the operator as data and put in no agent's prompt or tool result (TRUST_MODEL T1).
"""

from __future__ import annotations

import json
import re
import sys
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError

from canopy.core import db, records, sql
from canopy.core.conversation import REVIEW_RUN_PREFIX
from canopy.core.items import age
from canopy.runtime import servers

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection
    from datetime import datetime

    from canopy.runtime.report import Called
    from canopy.runtime.watch import Change

#: The server every worker's, planner's, and reviewer's run is given, as its inline config names it, and its one tool:
#: the runtime names it `canopy_run_status`, as the definitions allow it.
SERVER = "canopy_run"
TOOL = "status"
#: How the runtime starts that server: this interpreter's canopy. `-P` keeps the working directory off the import path,
#: so no file there can stand in for canopy's own modules (TRUST_MODEL T7).
SERVER_COMMAND = (sys.executable, "-P", "-m", "canopy", "_mcp", "--status")
#: The bounds of a card's text, in characters, and of its lists, in items.
MAX_SUMMARY = 500
MAX_LINE = 200
MAX_STUCK = 300
MAX_ITEMS = 20
#: What a refusal says outside the runs the tool serves.
NOT_SERVED = "the status tool serves a worker's, a planner's, or a reviewer's run alone, and this is none"

#: The tables of the runs that keep a card: a worker's or a planner's run, and a review's.
type Table = Literal["runs", "review_runs"]

#: A run's id, as CANOPY_RUN_ID names a worker's or a planner's run, after `REVIEW_RUN_PREFIX` for a review's.
_RUN_ID_RE = re.compile(r"[1-9][0-9]*")


def _plain(value: str) -> str:
    text = " ".join(value.split())
    if not text:
        raise ValueError("must not be empty")
    if not text.isprintable():
        raise ValueError("must be plain text, with no control or hidden character")
    return text


#: Plain text on one line, within its bound: whitespace runs, line breaks included, become one space.
_Plain = AfterValidator(_plain)


class _Part(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)


class Done(_Part):
    """A finished step, with what shows it is done."""

    #: The step.
    what: Annotated[StrictStr, Field(max_length=MAX_LINE, description="The step you finished."), _Plain]
    #: What shows it is done.
    proof: Annotated[
        StrictStr,
        Field(
            max_length=MAX_LINE,
            description='What shows it is done: "tests pass: 42/42", "pushed abc123", or "not pushed" when true.',
        ),
        _Plain,
    ]


class Card(_Part):
    """Where a running agent's work stands: the input of the `status` tool, replacing the run's whole card."""

    #: For someone who skipped the transcript.
    summary: Annotated[
        StrictStr,
        Field(max_length=MAX_SUMMARY, description="One or two sentences on the work, for someone who read none of it."),
        _Plain,
    ]
    #: What the agent is doing this moment.
    now: Annotated[StrictStr, Field(max_length=MAX_LINE, description="What you are doing this moment."), _Plain]
    #: Its finished steps, in order.
    done: Annotated[
        tuple[Done, ...],
        Field(max_length=MAX_ITEMS, description="Each step you finished, in order, with its proof."),
    ] = ()
    #: What is left, in order.
    next: Annotated[
        tuple[Annotated[StrictStr, Field(max_length=MAX_LINE), _Plain], ...],
        Field(max_length=MAX_ITEMS, description="What is left, in order."),
    ] = ()
    #: What is in its way that it works around.
    stuck: Annotated[
        StrictStr | None,
        Field(
            max_length=MAX_STUCK,
            description="What is in your way that you are working around, such as CI down or a flaky test; leave it "
            "out when nothing is.",
        ),
        AfterValidator(lambda v: None if v is None or not v.strip() else _plain(v)),
    ] = None


#: How a card's lists read back from the journal.
_DONE: TypeAdapter[tuple[Done, ...]] = TypeAdapter(tuple[Done, ...])
_NEXT: TypeAdapter[tuple[str, ...]] = TypeAdapter(tuple[str, ...])


def served() -> dict[str, tuple[str, ...]]:
    """The server that gives a run the `status` tool, for `canopy.runtime.servers.env`.

    Returns:
        Its name and the command the runtime starts it with.
    """
    return {SERVER: SERVER_COMMAND}


def tool_name() -> str:
    """The name the agent, and the definitions' rules, know the tool by.

    Returns:
        `canopy_run_status`, as the runtime names it.
    """
    return servers.tool_name(SERVER, TOOL)


def serves(run_id_env: str) -> bool:
    """Whether CANOPY_RUN_ID's value `run_id_env` names a run the tool serves: a worker's, a planner's, or a review's.

    A worker's or a planner's run is named by its id alone, and a review's after `REVIEW_RUN_PREFIX`, as `_run` and
    `_review` set it; a chore's and a task's are named otherwise, and the overseer's process has none.

    Returns:
        True for those runs' values.
    """
    return _RUN_ID_RE.fullmatch(run_id_env.removeprefix(REVIEW_RUN_PREFIX)) is not None


def seen(conn: sqlite3.Connection, table: Table, run_id: int, change: Change) -> None:
    """Record what one line a running run printed says of its card: a new card, or one more tool call since it.

    A completed call of the `status` tool whose input is a card replaces the run's whole card; any other tool call the
    line ended, an invalid call of the tool among them, counts as one call since the card. Nothing changes for a run not
    running, or one with no card yet that called no `status`.
    """
    if change.did is None:
        return
    card = card_of(change.called)
    if card is None:
        sql.execute(
            conn,
            sql.update("run_cards")
            .set_to("calls_since = calls_since + 1")
            .where("run_table = ? AND run_id = ?", table, run_id),
        )
        return
    record(conn, table, run_id, card)


def card_of(called: Called | None) -> Card | None:
    """The card a tool call made, if it is a completed call of the `status` tool whose input validates.

    Returns:
        The card, or None for any other call, or a call whose input is not a card.
    """
    if called is None or called.tool != tool_name():
        return None
    try:
        return Card.model_validate(called.input)
    except ValidationError:
        return None


def record(conn: sqlite3.Connection, table: Table, run_id: int, card: Card) -> None:
    """Replace run `run_id`'s whole card in `table` with `card`, stamped now; nothing changes for one not running."""
    done = json.dumps([d.model_dump() for d in card.done])
    with db.transaction(conn):
        running = sql.select("1").from_(table).where("id = ? AND status = 'running'", run_id)
        if sql.execute(conn, running).fetchone() is None:
            return
        sql.execute(
            conn,
            sql.insert(
                "run_cards",
                run_table=table,
                run_id=run_id,
                summary=card.summary,
                now=card.now,
                done=done,
                next=json.dumps(list(card.next)),
                stuck=card.stuck,
                updated_at=db.now(),
                calls_since=0,
            ).on_conflict(
                "(run_table, run_id) DO UPDATE SET summary = excluded.summary, now = excluded.now, "
                "done = excluded.done, next = excluded.next, stuck = excluded.stuck, updated_at = excluded.updated_at, "
                "calls_since = 0",
            ),
        )


def of_run(conn: sqlite3.Connection, table: Table, run_id: int) -> records.RunCard | None:
    """Return run `run_id`'s card in `table`, the last its agent gave, or None when it gave none."""
    query = sql.select("*").from_("run_cards").where("run_table = ? AND run_id = ?", table, run_id)
    return records.fetch_one(conn, records.RunCard, query)


def of_runs(conn: sqlite3.Connection, table: Table, run_ids: Collection[int]) -> dict[int, records.RunCard]:
    """Return the cards of the runs `run_ids` in `table`, by run id; a run that gave none is left out."""
    if not run_ids:
        return {}
    query = sql.select("*").from_("run_cards").where("run_table = ?", table).where_in("run_id", run_ids)
    return {card.run_id: card for card in records.fetch_all(conn, records.RunCard, query)}


def shown(card: records.RunCard, now: datetime | None = None) -> list[str]:
    """The whole card, as `canopy show` prints it: how old it is, then each field it holds.

    Returns:
        Its lines, a list's items each on a line of its own.
    """
    lines = [f"Card, {_old(card, now)}:", f"  summary: {card.summary}", f"  now: {card.now}"]
    done = _stored(_DONE, card.done)
    if done:
        lines += ["  done:", *(f"    - {d.what}: {d.proof}" for d in done)]
    following = _stored(_NEXT, card.next)
    if following:
        lines += ["  next:", *(f"    - {step}" for step in following)]
    if card.stuck:
        lines.append(f"  stuck: {card.stuck}")
    return lines


def now_line(card: records.RunCard, now: datetime | None = None) -> str:
    """What a running run is doing, as its card says, for `canopy status`.

    Returns:
        Its `now`, and how old the card is.
    """
    return f"now: {card.now}  (card {_old(card, now)})"


def _old(card: records.RunCard, now: datetime | None) -> str:
    calls = card.calls_since
    return f"{age(card.updated_at, now)} old, {calls} tool call{'' if calls == 1 else 's'} since"


def _stored[T](adapter: TypeAdapter[tuple[T, ...]], text: str) -> tuple[T, ...]:
    """Read back a list a card stored.

    Returns:
        Its items; empty when it does not read as one, which canopy never writes.
    """
    try:
        return adapter.validate_json(text)
    except ValidationError:
        return ()
