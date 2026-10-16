"""How `canopy status`, `canopy show`, and the other read-back commands name tickets, runs, costs, and chores."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from canopy.core import contract, db, records
from canopy.loop import attention

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from canopy.core import chore_view

# Agent-written text is cut to this many characters to fit one terminal line.
SUMMARY_WIDTH = 160


def named(key: object, title: object) -> str:
    """A ticket as a line names it: `PROJ-1: <its title>`, or its key alone before the overseer names it.

    Returns:
        The key and its title fit for one line, or the key alone when `title` is empty or None.
    """
    return f"{key}: {one_line(str(title))}" if title else str(key)


def one_line(text: str) -> str:
    """Agent-written text, fit for one terminal line: control characters dropped, whitespace collapsed, and cut.

    Returns:
        The flattened text, cut to `SUMMARY_WIDTH` characters and ended with "..." when longer.
    """
    flat = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return flat if len(flat) <= SUMMARY_WIDTH else flat[: SUMMARY_WIDTH - 3] + "..."


def phase_of(conn: sqlite3.Connection, ticket: sqlite3.Row) -> str:
    """A ticket's phase as the operator reads it: the recorded one, else what the last tick decided, else unseen.

    Returns:
        The phase to print. When none is recorded, a note naming the last decision about the ticket, if there is one.
    """
    if ticket["phase"]:
        return str(ticket["phase"])
    decided = db.last_decision_of(conn, str(ticket["key"]))
    return f"not recorded, last decision {decided}" if decided is not None else "not seen by a tick yet"


def result_of(run: sqlite3.Row | records.Row) -> dict[str, object]:
    """A run's stored result as an object; {} when it has none or it does not parse.

    Returns:
        The parsed `result_json`, its values still untrusted, or {} when it is empty, not JSON, or not an object.
    """
    return contract.stored_object(records.columns(run)["result_json"])


def prs_of(result: Mapping[str, object]) -> list[str]:
    """The PRs a run's result named, each a plain https:// URL; anything else is not printed.

    Returns:
        The plain URLs among the result's `prs` values, or its `pr` when `prs` is not an object.
    """
    return contract.stored_prs(result)


def spent(row: sqlite3.Row | records.Row) -> str:
    """What a run or a tick cost, as `  $0.25, 12.3k tokens`, or "" when the runtime reported nothing.

    Returns:
        The cost with two leading spaces, to append to a line, or "" when `row` records no usage.
    """
    usage = db.usage_of(row)
    return f"  {usage.describe()}" if usage is not None else ""


def chore_line(state: chore_view.ChoreState, now: datetime) -> str:
    """A chore's state on one line: running, or its last run and when it is due.

    Returns:
        How long the chore has been running, or its last run's status and age and when it is next due, as of `now`.
    """
    if state.running is not None:
        return f"running for {attention.age(state.running.started_at, now)}"
    latest = state.latest
    last = "never run" if latest is None else f"last {latest.status} {attention.age(latest.started_at, now)} ago"
    due = state.due_at(now)
    when = "due now" if due is None or due <= now else f"due in {attention.age(db.format_time(now), due)}"
    return f"{last}, {when}"
