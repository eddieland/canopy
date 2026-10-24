"""`canopy gc --dry-run` lists the remote branches canopy made that nothing names any more, and deletes none (§26)."""

import json
import sqlite3
from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli import gc as gc_cli
from canopy.cli.main import main
from canopy.core import db
from canopy.loop import gc, gc_branches
from tests.canopy.conftest import Ws
from tests.canopy.helpers import ended_tick
from tests.conftest import git


def pushed(ws: Ws, repo: str, *branches: str) -> dict[str, str]:
    """Push a commit of its own to each of `branches` of `repo`'s origin from its primary clone.

    Returns:
        The commit each branch is at.
    """
    clone = ws.clone(repo)
    heads: dict[str, str] = {}
    for branch in branches:
        git("commit", "--quiet", "--allow-empty", "-m", branch, cwd=clone)
        git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}", cwd=clone)
        heads[branch] = git("rev-parse", "HEAD", cwd=clone)
    return heads


def ticket_run(
    conn: sqlite3.Connection,
    key: str,
    branch: str,
    repo: str = "api",
    *,
    running: bool = False,
    base: str | None = None,
) -> None:
    """A run of `key` on `branch` in `repo`, ended or still running, stacked on `base` if one is given."""
    db.touch_ticket(conn, key, "acme")
    status, ended = ("running", None) if running else ("done", db.now())
    cursor = conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, log_path) "
        "VALUES (?, ?, 'implement', ?, ?, ?, ?, '/nowhere/run.log')",
        (ended_tick(conn, db.now()), key, branch, db.now(), ended, status),
    )
    conn.execute(
        "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder, base_branch) "
        "VALUES (?, ?, '/s', 'l', 'h', ?)",
        (cursor.lastrowid, repo, base),
    )


def task_run(conn: sqlite3.Connection, branch: str, *, stopped: bool, repo: str = "api") -> int:
    """A task in `repo`, stopped or not, with one ended run on `branch`.

    Returns:
        The task's id.
    """
    cursor = conn.execute(
        "INSERT INTO tasks (text, repo, channel, submitted_at, stopped_at) VALUES ('tidy up', ?, 'cli', ?, ?)",
        (repo, db.now(), db.now() if stopped else None),
    )
    task_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO task_runs (task_id, tick_id, branch, repo, slot_path, lease_id, lease_holder, base_branch, pool, "
        "started_at, ended_at, status, log_path) "
        "VALUES (?, ?, ?, ?, '/s', 'l', 'h', 'main', 'canopy', ?, ?, 'done', '')",
        (task_id, ended_tick(conn, db.now()), branch.format(id=task_id), repo, db.now(), db.now()),
    )
    assert task_id is not None
    return task_id


def dry_run(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """What `canopy gc --dry-run --json` reports."""
    assert main(["gc", "--dry-run", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_the_dry_run_lists_only_canopys_branches_that_nothing_names_and_deletes_none(
    ws: Ws,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = ws.journal()
    # Forgotten: its runs stay, and nothing else names its branch.
    ticket_run(conn, "PROJ-1", "agent/PROJ-1-work")
    # Its unit names it.
    ticket_run(conn, "PROJ-2", "agent/PROJ-2-login")
    conn.execute("INSERT INTO ticket_units (ticket_key, repo, branch) VALUES ('PROJ-2', 'api', 'agent/PROJ-2-login')")
    # An open run works on one, and stacks on another.
    ticket_run(conn, "PROJ-3", "agent/PROJ-3-work")
    ticket_run(conn, "PROJ-4", "agent/PROJ-4-work", running=True, base="agent/PROJ-3-work")
    # A run of this journal worked on it in another repository only.
    ticket_run(conn, "PROJ-5", "agent/PROJ-5-work", repo="web")
    # A run worked on it, but its name is not the one canopy gives that ticket.
    ticket_run(conn, "PROJ-6", "agent/PROJ-7-work")
    stopped = task_run(conn, "agent/task/{id}", stopped=True)
    open_task = task_run(conn, "agent/task/{id}", stopped=False)
    conn.commit()
    names = [
        "agent/PROJ-1-work",
        "agent/PROJ-2-login",
        "agent/PROJ-3-work",
        "agent/PROJ-4-work",
        "agent/PROJ-5-work",
        "agent/PROJ-7-work",
        f"agent/task/{stopped}",
        f"agent/task/{open_task}",
        # canopy's name for a ticket, but no run of this journal pushed it: another workspace's, perhaps.
        "agent/PROJ-8-work",
        "PROJ-1-work",
    ]
    heads = pushed(ws, "api", *names)

    report = dry_run(capsys)

    forgotten, task = "agent/PROJ-1-work", f"agent/task/{stopped}"
    assert report["branches"] == [
        {"repo": "api", "name": forgotten, "head": heads[forgotten], "ticket": "PROJ-1", "task": None},
        {"repo": "api", "name": task, "head": heads[task], "ticket": None, "task": stopped},
    ]
    for name in names:
        assert ws.remote_head("api", name) == heads[name]


def test_the_text_report_names_each_branch_and_whose_it_is(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    conn = ws.journal()
    ticket_run(conn, "PROJ-1", "agent/PROJ-1-work", repo="web")
    conn.commit()
    head = pushed(ws, "web", "agent/PROJ-1-work")["agent/PROJ-1-work"]

    assert main(["gc", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert f"  web: agent/PROJ-1-work  (PROJ-1, at {head[:12]})\n" in out
    assert "canopy deletes none, so delete those you are done with yourself:\n" in out


def test_a_branch_deleted_since_the_clones_last_fetch_is_still_listed_until_it_fetches(
    ws: Ws,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The dry run reads the clone's remote-tracking refs and fetches nothing."""
    conn = ws.journal()
    ticket_run(conn, "PROJ-1", "agent/PROJ-1-work")
    conn.commit()
    pushed(ws, "api", "agent/PROJ-1-work")
    git("branch", "--quiet", "-D", "agent/PROJ-1-work", cwd=ws.origins["api"])

    listed = dry_run(capsys)["branches"]
    git("fetch", "--quiet", "--prune", "origin", cwd=ws.clone("api"))

    assert [b["name"] for b in listed] == ["agent/PROJ-1-work"]
    assert dry_run(capsys)["branches"] == []


def test_a_clone_git_cannot_read_is_noted_and_its_branches_left_out(
    ws: Ws,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = ws.journal()
    ticket_run(conn, "PROJ-1", "agent/PROJ-1-work")
    conn.commit()
    pushed(ws, "api", "agent/PROJ-1-work")
    (ws.clone("api") / ".git" / "HEAD").write_text("not a ref\n")

    report = dry_run(capsys)

    assert report["branches"] == []
    assert f"api: git for-each-ref failed in {ws.clone('api')}" in report["notes"]


def test_the_text_report_lists_the_branches(snapshot: SnapshotAssertion) -> None:
    report = gc.Report(
        at="2026-10-24T09:30:00.000Z",
        kinds=[gc.Kind("journal WAL", "files", 0, 0, 0, 0, "checkpointed")],
        journal_size=126_000_000,
        notes=[],
        branches=[
            gc_branches.Branch("api", "agent/PROJ-1-work", "0123456789abcdef0123456789abcdef01234567", "PROJ-1", None),
            gc_branches.Branch("web", "agent/task/3", "fedcba9876543210fedcba9876543210fedcba98", None, 3),
        ],
    )
    assert "\n".join(gc_cli.render(report)) == snapshot
