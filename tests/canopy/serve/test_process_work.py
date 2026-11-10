"""The system resources page's processes, each tied to the running run whose process it is."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from canopy.core import chore_runs, db, records, review_runs
from canopy.core.vocab import RunStatus
from canopy.serve import mock, process_work
from canopy.serve.schema.host import HostProcess, HostProcesses, ProcessWork
from tests.canopy.web_helpers import client

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
PR = "https://github.com/acme/web/pull/88"


def a_process(pid: int) -> HostProcess:
    """A sleeping process `pid`, under process 1."""
    return HostProcess(
        pid=pid,
        parent=1,
        name="worker",
        command="worker",
        user="operator",
        state="sleeping",
        cpu=0.0,
        rss=0,
        threads=1,
        started_at=None,
    )


def read(*pids: int) -> HostProcesses:
    """The processes `pids`, as a read of the machine finds them."""
    return HostProcesses(read_at=NOW, over_seconds=10.0, processes=[a_process(pid) for pid in pids])


def worker_run(conn: sqlite3.Connection, key: str, pid: int | None, worker_pid: int | None) -> int:
    """A running worker run of `key` whose process recorded `pid`, and its worker `worker_pid`."""
    db.touch_ticket(conn, key, "/ws")
    tick_id = db.start_tick(conn, dry_run=False)
    run_id = db.insert_run(conn, tick_id=tick_id, key=key, kind="implement", branch="", slots=[], runs_dir=Path())
    records.update(records.Run).set(pid=pid, worker_pid=worker_pid).where("id = ?", run_id).run(conn)
    return run_id


def work_of(found: HostProcesses) -> dict[int, ProcessWork | None]:
    """Each process's work, by pid."""
    return {p.pid: p.work for p in found.processes or []}


def test_a_running_runs_process_carries_its_run_and_its_ticket(conn: sqlite3.Connection) -> None:
    run_id = worker_run(conn, "PROJ-1", 100, 101)

    found = work_of(process_work.tagged(conn, read(100, 101, 102)))

    # The run's own process; its worker sits under it in the tree, so it carries nothing of its own.
    assert found == {100: ProcessWork(kind="run", id=run_id, ticket_key="PROJ-1"), 101: None, 102: None}


def test_an_ended_runs_pid_may_be_another_process_now_and_is_not_tagged(conn: sqlite3.Connection) -> None:
    run_id = worker_run(conn, "PROJ-1", 100, 101)
    records.update(records.Run).set(status=RunStatus.DONE).where("id = ?", run_id).run(conn)

    assert work_of(process_work.tagged(conn, read(100, 101))) == {100: None, 101: None}


def test_the_agent_carries_its_run_where_the_runs_own_process_is_gone(conn: sqlite3.Connection) -> None:
    run_id = worker_run(conn, "PROJ-1", 100, 101)

    found = work_of(process_work.tagged(conn, read(101)))

    assert found == {101: ProcessWork(kind="run", id=run_id, ticket_key="PROJ-1")}


def test_a_chores_and_a_reviews_processes_name_their_chore_and_pr(conn: sqlite3.Connection) -> None:
    chore = chore_runs.insert_chore_run(conn, tick_id=None, chore="deps", logs_dir=Path())
    records.update(records.ChoreRun).set(pid=200, agent_pid=201).where("id = ?", chore).run(conn)
    tick_id = db.start_tick(conn, dry_run=False)
    review = review_runs.insert_review_run(
        conn,
        tick_id=tick_id,
        pr_url=PR,
        sha="abc",
        ticket="PROJ-2",
        repo="web",
        purpose="own",
        logs_dir=Path(),
    )
    records.update(records.ReviewRun).set(pid=300).where("id = ?", review).run(conn)

    found = work_of(process_work.tagged(conn, read(200, 201, 300)))

    assert found[200] == ProcessWork(kind="chore", id=chore, chore="deps")
    assert found[300] == ProcessWork(kind="review", id=review, pr_url=PR, ticket_key="PROJ-2")
    assert found[201] is None


def test_off_linux_there_is_nothing_to_tag(conn: sqlite3.Connection) -> None:
    worker_run(conn, "PROJ-1", 100, 101)
    unread = HostProcesses(read_at=NOW, over_seconds=None, processes=None)

    assert process_work.tagged(conn, unread) is unread


def test_the_mocks_running_runs_are_its_machines_processes(tmp_path: Path) -> None:
    c = client(None, mock.seed(tmp_path / "mock"))

    found = c.get("/api/host/processes").json()

    tagged = {p["pid"]: p["work"] for p in found["processes"] if p["work"] is not None}
    assert {pid: (w["kind"], w["id"], w["ticket_key"]) for pid, w in tagged.items()} == {
        50110: ("run", 41, "ABC-101"),
        50140: ("run", 43, "ABC-104"),
    }
