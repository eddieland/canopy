"""How much of each run went to finding its way before its work (ROADMAP M70, stage 0's gate).

Over a hand-written journal whose runs' logs hold OpenCode 1's events: each role's anchor, the counts and medians per
role and repository, the gate, and `canopy orientation`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from canopy.cli import orientation as orientation_cli
from canopy.cli.main import main
from canopy.core import db, orientation, plans, records, review_diff, review_runs
from canopy.core.vocab import PoolKind, ReviewRunStatus, RunKind, RunStatus
from canopy.runtime import transcript
from canopy.runtime.implementation import Version
from canopy.runtime.report import Touch
from canopy.runtime.transcript import Use
from tests.canopy.helpers import in_tick, in_zone, present

if TYPE_CHECKING:
    import sqlite3

    import pytest
    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv, Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
SESSION = "ses_abc123"
#: A tool call each, as the log holds it: (tool, input), completed unless the input says `"failed": True`.
type Call = tuple[str, dict[str, object]]


def at(start: datetime, minutes: float) -> str:
    """The time `minutes` after `start`, as the journal writes it."""
    return db.format_time(start + timedelta(minutes=minutes))


def log_of(path: Path, calls: list[Call], *, cost: float = 0.5) -> str:
    """Write a session's log at `path` that makes `calls`, a model call costing `cost` ended after each; its path."""
    lines: list[str] = []
    for tool, given in calls:
        status = "error" if given.pop("failed", False) else "completed"
        state = {"status": status, "input": given, "output": "", "error": "no", "time": {}}
        part = {"type": "tool", "callID": "c", "tool": tool, "state": state}
        lines.append(json.dumps({"type": "tool_use", "timestamp": 1, "sessionID": SESSION, "part": part}))
        tokens = {"input": 10, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        finish = {"type": "step-finish", "reason": "tool-calls", "cost": cost, "tokens": tokens}
        lines.append(json.dumps({"type": "step_finish", "timestamp": 1, "sessionID": SESSION, "part": finish}))
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def read(path: str, *, failed: bool = False) -> Call:
    return ("read", {"filePath": path, "failed": True} if failed else {"filePath": path})


def edit(path: str) -> Call:
    return ("edit", {"filePath": path, "oldString": "a", "newString": "b"})


GREP: Call = ("grep", {"pattern": "parse"})
SHELL_SEARCH: Call = ("bash", {"command": "rg parse"})
TESTS: Call = ("bash", {"command": "uv run pytest"})


def worker(
    conn: sqlite3.Connection,
    tmp_path: Path,
    kind: RunKind,
    start: datetime,
    calls: list[Call] | None,
    *,
    repos: tuple[str, ...] = ("web",),
    key: str = "PROJ-1",
) -> int:
    """A worker's or a planner's run that started at `start` and ended, in slots of `repos`, its log making `calls`.

    No log at all when `calls` is None. Returns its id.
    """
    db.touch_ticket(conn, key, "/ws")
    with in_tick(conn) as tick_id:
        run = records.insert(
            records.Run,
            tick_id=tick_id,
            ticket_key=key,
            kind=kind,
            branch=f"agent/{key}",
            started_at=at(start, 0),
            ended_at=at(start, 30),
            status=RunStatus.DONE,
            log_path="",
            session_id=SESSION,
        ).run(conn)
    run_id = present(run.lastrowid)
    log = tmp_path / f"run-{run_id}.log"
    path = log_of(log, calls) if calls is not None else str(log)
    records.update(records.Run).set(log_path=path).where("id = ?", run_id).run(conn)
    for repo in repos:
        records.insert(
            records.RunSlot,
            run_id=run_id,
            repo=repo,
            slot_path=f"/pool/{repo}/{run_id}",
            lease_id=f"l{run_id}{repo}",
            lease_holder="canopy",
            base_branch="main",
            pool=PoolKind.TREEHOUSE,
        ).run(conn)
    return run_id


def journal_of_runs(conn: sqlite3.Connection, tmp_path: Path, now: datetime) -> None:
    """A run of each role in the last day, a joint one, one with no log, and an implement before the window."""
    day = now - timedelta(days=1)
    # Two searches and a read of another file, then the file it edits: three calls before, of five.
    worker(
        conn,
        tmp_path,
        RunKind.IMPLEMENT,
        day,
        [GREP, SHELL_SEARCH, read("/pool/web/1/src/b.py"), read("/pool/web/1/src/a.py"), edit("/pool/web/1/src/a.py")],
    )
    # Its first call is the edit, of a file it never read: nothing before it.
    worker(conn, tmp_path, RunKind.RESUME, day, [edit("src/a.py"), TESTS])
    # A joint run: a failed read does not anchor it, the one after it does.
    worker(
        conn,
        tmp_path,
        RunKind.IMPLEMENT,
        day,
        [GREP, read("/p/api/x.py", failed=True), read("/p/api/x.py"), edit("/p/api/x.py")],
        repos=("web", "api"),
        key="PROJ-2",
    )
    # Its log is gone: counted, not read.
    worker(conn, tmp_path, RunKind.IMPLEMENT, day, None, key="PROJ-3")
    # A plan naming `src/c.py`, read after the desk's ticket file.
    planned = worker(conn, tmp_path, RunKind.PLAN, day, [read("/desk/TICKET.md"), GREP, read("/desk/web/src/c.py")])
    plans.write(tmp_path, "PROJ-1", planned, "## Steps\n\n1. Change `src/c.py` to parse dates.\n")
    # A feedback plan: no anchor of its own.
    worker(conn, tmp_path, RunKind.FEEDBACK_PLAN, day, [read("/desk/web/src/a.py")])
    # Before the window.
    worker(conn, tmp_path, RunKind.IMPLEMENT, now - timedelta(days=30), [GREP, edit("a.py")])
    with in_tick(conn) as tick_id:
        review = review_runs.insert_review_run(
            conn,
            tick_id=tick_id,
            pr_url="https://example.test/acme/web/pull/9",
            sha="a" * 40,
            ticket=None,
            repo="web",
            purpose="request",
            logs_dir=tmp_path,
        )
        task = records.insert(records.Task, text="t", repo="web", channel="cli", submitted_at=at(day, 0)).run(conn)
        records.insert(
            records.TaskRun,
            task_id=present(task.lastrowid),
            tick_id=tick_id,
            branch="agent/task/1",
            repo="web",
            slot_path="/pool/1/web",
            lease_id="l1",
            lease_holder="canopy:task:1",
            base_branch="main",
            pool=PoolKind.TREEHOUSE,
            started_at=at(day, 0),
            ended_at=at(day, 5),
            status=RunStatus.DONE,
            log_path=log_of(tmp_path / "task.log", [TESTS, edit("/pool/1/web/README.md")]),
            session_id=SESSION,
        ).run(conn)
    review_log = present(review_runs.get_review_run(conn, review)).log_path
    log_of(Path(review_log), [read("/r/web/README.md"), GREP, read("/r/web/src/d.py")])
    review_diff.keep(
        review_diff.path_for(review_log),
        "diff --git a/src/d.py b/src/d.py\n--- a/src/d.py\n+++ b/src/d.py\n",
    )
    records.update(records.ReviewRun).set(
        started_at=at(day, 0),
        ended_at=at(day, 20),
        status=ReviewRunStatus.DONE,
        session_id=SESSION,
    ).where("id = ?", review).run(conn)


def uses(*touches: Touch) -> list[Use]:
    """Calls that did `touches`, every one completed, each after a dollar more of spend than the last."""
    return [Use(t, completed=True, spent=float(i)) for i, t in enumerate(touches)]


SEARCH = Touch("search")


def test_a_workers_anchor_is_the_first_read_of_the_file_its_first_edit_changed() -> None:
    """Or the edit itself, when it read none of its files first; a run that edits nothing has none."""
    run = uses(SEARCH, Touch("read", ("/s/b.py",)), Touch("read", ("/s/src/a.py",)), Touch("edit", ("src/a.py",)))
    assert orientation.edit_anchor(run) == 2
    assert orientation.edit_anchor(uses(SEARCH, Touch("edit", ("a.py",)))) == 1
    assert orientation.edit_anchor(uses(SEARCH, Touch("read", ("a.py",)))) is None
    assert orientation.read_anchor(run, ["src/a.py"]) == 2
    assert orientation.read_anchor(run, []) is None
    found = orientation.orientation_of(run, 2)
    assert (found.calls, found.before, found.searches, found.share, found.spent) == (4, 2, 1, 0.5, 2.0)
    assert not orientation.orientation_of(run, None).anchored


def test_paths_are_the_same_file_when_one_ends_as_the_other_does_at_a_directory() -> None:
    assert orientation.same_file("/pool/web/1/src/a.py", "src/a.py")
    assert orientation.same_file("src/a.py", "/pool/web/1/src/a.py")
    assert orientation.same_file("a.py", "a.py")
    assert not orientation.same_file("/pool/web/1/xsrc/a.py", "src/a.py")
    assert not orientation.same_file("", "a.py")


def test_a_plans_paths_are_the_words_with_a_directory_or_an_extension() -> None:
    text = (
        "Change `src/parse.py` and ./lib/util, see README.md. Not e.g. this, nor .hidden, 1.5 hours, or `src/parse.py`."
    )
    assert orientation.plan_paths(text) == ["src/parse.py", "lib/util", "README.md"]


def test_runs_are_measured_per_role_and_repository_with_the_gate(tmp_path: Path, journals: Journals) -> None:
    """Medians of the anchored runs; a run with no log counts as not read, one with no anchor as not anchored."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_runs(conn, tmp_path, NOW)
    found = orientation.measure(conn, NOW, 14, state_dir=tmp_path, version=Version.ONE)
    assert found.days == 14
    rows = [(r.role, r.repo, r.runs, r.read, r.anchored, r.calls, r.before, r.searches, r.share) for r in found.roles]
    assert rows == [
        ("implement", "api+web", 1, 1, 1, 4, 2, 1, 0.5),
        ("implement", "web", 2, 1, 1, 5, 3, 2, 0.6),
        ("resume", "web", 1, 1, 1, 2, 0, 0, 0.0),
        ("plan", "web", 1, 1, 1, 3, 2, 1, 2 / 3),
        ("feedback-plan", "web", 1, 1, 0, 1, None, None, None),
        ("review", "web", 1, 1, 1, 3, 2, 1, 2 / 3),
        ("task", "web", 1, 1, 1, 2, 1, 0, 0.5),
    ]
    assert found.roles[1].spent == 1.5  # three model calls of fifty cents before its anchor
    gates = [(g.repo, g.anchored, g.share, g.searches, g.passed) for g in found.gates]
    # web's two anchored worker runs: a median share of 30%, over the quarter, and one search.
    assert gates == [("api+web", 1, 0.5, 1, True), ("web", 2, 0.3, 1, True)]
    month = orientation.measure(conn, NOW, 60, state_dir=tmp_path, version=Version.ONE)
    assert month.roles[1].runs == 3
    assert orientation.measure(conn, NOW - timedelta(days=60), 1, state_dir=tmp_path, version=Version.ONE).roles == ()


def test_a_run_whose_log_was_cut_is_read_and_not_anchored(tmp_path: Path, journals: Journals) -> None:
    """Its share would be of the calls read, not of every call it made, so it leaves the medians."""
    conn = journals.open(tmp_path / "canopy.db")
    calls = [GREP, read("/pool/web/1/src/a.py"), edit("/pool/web/1/src/a.py"), TESTS, TESTS, TESTS]
    run_id = worker(conn, tmp_path, RunKind.IMPLEMENT, NOW - timedelta(hours=1), calls)
    log = Path(present(db.get_run(conn, run_id))["log_path"])
    # Room for the first four events of the log, its first two calls and their model calls, and no more.
    bound = sum(len(line) + 1 for line in log.read_text().splitlines()[:4])
    with mock.patch.object(transcript, "MAX_BYTES", bound):
        found = orientation.measure(conn, NOW, 1, state_dir=tmp_path, version=Version.ONE)
    [implement] = found.roles
    assert (implement.runs, implement.read, implement.anchored, implement.calls, implement.share) == (1, 1, 0, 2, None)
    assert found.gates[0].share is None


def test_the_gate_holds_a_median_at_or_under_both_bounds() -> None:
    assert not orientation.Gate("web", 3, share=0.25, searches=3).passed
    assert orientation.Gate("web", 3, share=0.1, searches=3.5).passed
    assert not orientation.Gate("web", 0, share=None, searches=None).passed


def test_the_report_is_printed_as_a_table(tmp_path: Path, journals: Journals, snapshot: SnapshotAssertion) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_runs(conn, tmp_path, NOW)
    with in_zone("UTC"):
        found = orientation.measure(conn, NOW, 14, state_dir=tmp_path, version=Version.ONE)
        assert "\n".join(orientation_cli.render(found)) == snapshot
        empty = orientation.measure(conn, NOW - timedelta(days=60), 1, state_dir=tmp_path, version=Version.ONE)
        assert orientation_cli.render(empty) == [
            "Orientation over 1 day, since 2026-08-09 UTC, by role and repository: medians before the anchor.",
            "",
            "No run started and ended in the window.",
        ]


def test_canopy_orientation_reads_the_last_two_weeks(
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--days` narrows it, and `--json` prints it as data."""
    journal_of_runs(canopy_env.journal(), tmp_path, datetime.now(UTC))
    assert main(["orientation"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[3].split() == ["implement", "api+web", "1", "1", "1", "4", "2", "1", "50%", "$1.00"]
    assert main(["orientation", "--days", "60", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["days"] == 60
    assert found["gate"] == {"share": 0.25, "searches": 3}
    assert found["roles"][1] == {
        "role": "implement",
        "repo": "web",
        "runs": 3,
        "read": 2,
        "anchored": 2,
        "calls": 3.5,
        "before": 2,
        "searches": 1.5,
        "share": 0.55,
        "spent_usd": 1.0,
    }
    assert found["gates"][1] == {"repo": "web", "anchored": 3, "share": 0.5, "searches": 1, "passed": True}
    assert main(["orientation", "--days", "0"]) == 2
