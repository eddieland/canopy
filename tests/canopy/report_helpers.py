"""Agent runs written by hand, for the tests of the reports that read what runs were offered and called (DESIGN §13).

A run of each kind that started at a given time and ended, and what its session and events say it called.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records
from canopy.core.vocab import ChoreRunStatus, PoolKind, ReviewRunStatus, RunKind, RunStatus
from tests.canopy.helpers import present

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.run_models import RunTable
    from canopy.runtime.report import ToolUse


def tick(conn: sqlite3.Connection, started: str, *, overseer_ran: int = 1) -> int:
    """A tick that started at `started` and ended, whose overseer ran unless `overseer_ran` is 0."""
    made = records.insert(
        records.Tick,
        started_at=started,
        ended_at=started,
        dry_run=0,
        overseer_ran=overseer_ran,
    ).run(conn)
    return present(made.lastrowid)


def worker(
    conn: sqlite3.Connection,
    started: str,
    *,
    kind: RunKind = RunKind.IMPLEMENT,
    private: bool = False,
    ended: bool = True,
) -> int:
    """A worker's or a planner's run that started at `started`, ended unless `ended` is false."""
    db.touch_ticket(conn, "PROJ-1", "/ws")
    run = records.insert(
        records.Run,
        tick_id=tick(conn, started, overseer_ran=0),
        ticket_key="PROJ-1",
        kind=kind,
        branch="agent/PROJ-1",
        started_at=started,
        ended_at=started if ended else None,
        status=RunStatus.DONE if ended else RunStatus.RUNNING,
        log_path="l",
        private=int(private),
    ).run(conn)
    return present(run.lastrowid)


def review(conn: sqlite3.Connection, started: str) -> int:
    """A review run that started at `started` and ended."""
    run = records.insert(
        records.ReviewRun,
        tick_id=tick(conn, started, overseer_ran=0),
        pr_url="https://example.test/acme/web/pull/9",
        sha="a" * 40,
        started_at=started,
        ended_at=started,
        status=ReviewRunStatus.DONE,
        log_path="l",
    ).run(conn)
    return present(run.lastrowid)


def chore(conn: sqlite3.Connection, started: str) -> int:
    """A chore's run that started at `started` and ended."""
    run = records.insert(
        records.ChoreRun,
        tick_id=tick(conn, started, overseer_ran=0),
        chore="deps",
        started_at=started,
        ended_at=started,
        status=ChoreRunStatus.OK,
        log_path="l",
    ).run(conn)
    return present(run.lastrowid)


def task(conn: sqlite3.Connection, started: str) -> int:
    """A task's run that started at `started` and ended: one the runtime is never asked about."""
    made = records.insert(records.Task, text="Do it.", repo="web", channel="cli", submitted_at=started).run(conn)
    run = records.insert(
        records.TaskRun,
        task_id=present(made.lastrowid),
        tick_id=tick(conn, started, overseer_ran=0),
        branch="agent/task/1",
        repo="web",
        slot_path="/pool/web/1",
        lease_id="lease",
        lease_holder="canopy",
        base_branch="main",
        pool=PoolKind.CANOPY,
        started_at=started,
        ended_at=started,
        status=RunStatus.DONE,
        log_path="l",
    ).run(conn)
    return present(run.lastrowid)


def called(conn: sqlite3.Connection, table: RunTable, run_id: int, replies: int, *tools: ToolUse) -> None:
    """What a run's session and events say: the model calls it made, and its calls by tool."""
    if table == "ticks":
        db.set_tick_report(conn, run_id, "s", None, tools=tools)
    else:
        db.set_run_report(conn, table, run_id, "s", None, tools=tools)
    if replies:
        records.insert(
            records.RunModel,
            run_table=table,
            run_id=run_id,
            model="anthropic/claude-sonnet-4-5",
            replies=replies,
            cost_usd=0.0,
        ).run(conn)
