"""How `canopy status`, `canopy show`, and the other read-back commands name tickets, runs, costs, and chores.

And how a report prints as JSON, for `--json`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from canopy.core import contract, db, records
from canopy.infra.text import one_line
from canopy.loop import attention

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from canopy.core import chore_view

#: How much of a persona's digest a line shows: enough to tell two versions of it apart.
DIGEST_WIDTH = 12


def run_kind(row: sqlite3.Row) -> str:
    """A run's kind as a line shows it: a `resume` with its reasons, `resume (ci, review)` (DESIGN §8).

    Returns:
        The kind, followed by its reasons in parentheses when the run has any.
    """
    reasons = db.reasons_in(row)
    return f"{row['kind']} ({', '.join(reasons)})" if reasons else str(row["kind"])


def named(key: object, title: object) -> str:
    """A ticket as a line names it: `PROJ-1: <its title>`, or its key alone before the overseer names it.

    Returns:
        The key and its title fit for one line, or the key alone when `title` is empty or None.
    """
    return f"{key}: {one_line(str(title))}" if title else str(key)


def phase_of(conn: sqlite3.Connection, ticket: records.Ticket) -> str:
    """A ticket's phase as the operator reads it: the recorded one, else what the last tick decided, else unseen.

    Returns:
        The phase to print. When none is recorded, a note naming the last decision about the ticket, if there is one.
    """
    if ticket.phase is not None:
        return ticket.phase
    decided = db.last_decision_of(conn, ticket.key)
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


def persona_of(row: sqlite3.Row) -> str:
    """The persona a run or a review ran in (DESIGN §31), as `  persona skeptic 1a2b3c4d5e6f`, its digest cut short.

    Returns:
        The name and digest with two leading spaces, to append to a line, or "" for a run that recorded none.
    """
    if row["persona"] is None:
        return ""
    return f"  persona {row['persona']} {str(row['persona_digest'])[:DIGEST_WIDTH]}"


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


def report_json(report: dict[str, Any]) -> str:
    """A report as `--json` prints it: one JSON object, with each value on a line of its own.

    An agent reads a long report from the file its runtime saves it to, through file tools that cut a line at a few
    thousand characters, so a report on one line is cut short. A line for each value keeps all of it readable for about
    2% more than the compact form, where indenting by two costs a third to a half more.

    Returns:
        The JSON text, its keys sorted.
    """
    return json.dumps(report, sort_keys=True, indent=0)
