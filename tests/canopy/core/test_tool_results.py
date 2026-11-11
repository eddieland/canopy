"""What each role's tool calls put into its context (ROADMAP M71, stage 0's measurement).

Over a hand-written journal whose runs' logs hold the events of the runtime `--runtime` names: a shell command counted
as the program it runs, a cut result counted, a repeated read counted, `status` characters summed, a log past the bound
read and marked, and `canopy tool-results`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from canopy.cli import tool_results as tool_results_cli
from canopy.cli.main import main
from canopy.core import cards, db, overseer_runs, records, review_runs, tool_results
from canopy.core.vocab import ChoreRunStatus, ReviewRunStatus, RunKind, RunStatus
from canopy.runtime import transcript
from canopy.runtime.implementation import Version
from tests.canopy.helpers import in_tick, in_zone, present

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    import pytest
    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv, Journals

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
SESSION = "ses_abc123"


@dataclass(frozen=True)
class Made:
    """A tool call as a test writes it, whatever the runtime: `shell` for the runtime's shell, `read` by `path`."""

    tool: str
    given: Mapping[str, object] = field(default_factory=dict)
    #: What it returned: its output, or its error when it `failed`.
    output: str = ""
    failed: bool = False
    #: What the runtime's metadata says of its cut; None for metadata that says nothing.
    cut: bool | None = None


def read(path: str, chars: int, *, cut: bool | None = False, failed: bool = False) -> Made:
    return Made("read", {"path": path}, "r" * chars, failed=failed, cut=cut)


def shell(command: str, chars: int, *, cut: bool | None = False) -> Made:
    return Made("shell", {"command": command, "description": "run it"}, "s" * chars, cut=cut)


def status(summary: str, now: str) -> Made:
    return Made(cards.tool_name(), {"summary": summary, "now": now}, "ok")


def sent(made: Made) -> int:
    """The characters a call's input is as compact JSON: what its agent wrote to make it."""
    return len(json.dumps(made.given, separators=(",", ":")))


def log_of(path: Path, calls: Sequence[Made], version: Version) -> str:
    """Write a session's log at `path` making `calls` as runtime `version` prints them, each a model call; its path."""
    shell_tool, path_key = ("bash", "filePath") if version is Version.ONE else ("shell", "path")
    lines: list[str] = []
    for made in calls:
        tool = shell_tool if made.tool == "shell" else made.tool
        given = {path_key if k == "path" else k: v for k, v in made.given.items()}
        state: dict[str, object] = {"status": "error" if made.failed else "completed", "input": given, "time": {}}
        state["error" if made.failed else "output"] = made.output
        if made.cut is not None:
            said = {"truncated": made.cut}
            state["metadata"] = said if version is Version.ONE else {"metadata": said, "rawInput": "{}"}
        part = {"type": "tool", "callID": "c", "tool": tool, "state": state}
        lines.append(json.dumps({"type": "tool_use", "timestamp": 1, "sessionID": SESSION, "part": part}))
        tokens = {"input": 10, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        finish = {"type": "step-finish", "reason": "tool-calls", "cost": 0.5, "tokens": tokens}
        lines.append(json.dumps({"type": "step_finish", "timestamp": 1, "sessionID": SESSION, "part": finish}))
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def at(start: datetime, minutes: float) -> str:
    """The time `minutes` after `start`, as the journal writes it."""
    return db.format_time(start + timedelta(minutes=minutes))


def worker(conn: sqlite3.Connection, log: Path, start: datetime, calls: Sequence[Made] | None, version: Version) -> int:
    """An implement run that started at `start` and ended, its log at `log` making `calls`, or none when None."""
    db.touch_ticket(conn, "PROJ-1", "/ws")
    path = log_of(log, calls, version) if calls is not None else str(log)
    with in_tick(conn) as tick_id:
        run = records.insert(
            records.Run,
            tick_id=tick_id,
            ticket_key="PROJ-1",
            kind=RunKind.IMPLEMENT,
            branch="agent/PROJ-1",
            started_at=at(start, 0),
            ended_at=at(start, 30),
            status=RunStatus.DONE,
            log_path=path,
            session_id=SESSION,
        ).run(conn)
    return present(run.lastrowid)


#: The first implement run's calls: two reads of one file, a cut read, a cut `gh run view` behind a `cd`, a `gh pr
#: view`, a failed search whose metadata says nothing of a cut, and two `status` calls.
FIRST: Sequence[Made] = (
    read("/pool/web/1/src/a.py", 100),
    read("/pool/web/1/./src/a.py", 100),
    read("/pool/web/1/src/b.py", 50, cut=True),
    shell("cd web && gh run view 7 --log-failed", 1000, cut=True),
    shell("gh pr view 3 --json comments", 200),
    status("Half done.", "testing"),
    Made("grep", {"pattern": "parse"}, "no matches", failed=True),
    status("Done.", "pushing"),
)
SECOND: Sequence[Made] = (status("Started.", "reading"), read("/pool/web/2/src/c.py", 30))


def journal_of_runs(conn: sqlite3.Connection, tmp_path: Path, state_dir: Path, now: datetime, version: Version) -> None:
    """Two implement runs and one with no log in the last day, one before the window, a review, a chore, an overseer."""
    day = now - timedelta(days=1)
    worker(conn, tmp_path / "first.log", day, FIRST, version)
    worker(conn, tmp_path / "second.log", day, SECOND, version)
    worker(conn, tmp_path / "gone.log", day, None, version)
    worker(conn, tmp_path / "old.log", now - timedelta(days=30), [shell("make", 5)], version)
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
        records.insert(
            records.ChoreRun,
            tick_id=tick_id,
            chore="todos",
            started_at=at(day, 0),
            ended_at=at(day, 5),
            status=ChoreRunStatus.OK,
            log_path=log_of(tmp_path / "chore.log", [shell("FOO=1 /usr/bin/rg TODO", 20)], version),
            session_id=SESSION,
        ).run(conn)
        overseer = overseer_runs.start(conn, tick_id)
        records.update(records.OverseerRun).set(
            started_at=at(day, 0),
            ended_at=at(day, 2),
            session_id=SESSION,
        ).where("id = ?", overseer).run(conn)
        (state_dir / "ticks").mkdir(parents=True, exist_ok=True)
        log_of(state_dir / "ticks" / f"{tick_id}.log", [Made("canopy_decide", {"decisions": []}, "ok")], version)
    review_log = present(review_runs.get_review_run(conn, review)).log_path
    # A failed read reads nothing, so the read after it is no repeat.
    log_of(Path(review_log), [read("/r/README.md", 40, failed=True, cut=None), read("/r/README.md", 40)], version)
    records.update(records.ReviewRun).set(
        started_at=at(day, 0),
        ended_at=at(day, 20),
        status=ReviewRunStatus.DONE,
        session_id=SESSION,
    ).where("id = ?", review).run(conn)


def test_a_shell_command_counts_as_the_program_it_runs() -> None:
    """Past a `cd` or a variable, without its directory, and gh's and git's with their subcommands."""
    assert tool_results.shell_program("cd web && gh run view 7 --log-failed") == "gh run view"
    assert tool_results.shell_program("gh pr view 3 --json comments") == "gh pr view"
    assert tool_results.shell_program("gh api repos/acme/web/pulls/3") == "gh api"
    assert tool_results.shell_program("git diff main...HEAD") == "git diff"
    assert tool_results.shell_program("git -C web log") == "git"
    assert tool_results.shell_program("FOO=1 /usr/bin/rg TODO | head") == "rg"
    assert tool_results.shell_program("uv run pytest -q") == "uv"
    assert tool_results.shell_program("cd web") == "cd"
    assert tool_results.shell_program('echo "unclosed') is None
    assert tool_results.shell_program("") is None


def test_runs_are_measured_per_role_and_tool(tmp_path: Path, journals: Journals, runtime: Version) -> None:
    """Each tool's calls, characters, median, share, cuts, and repeated reads; each role's `status` characters."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_runs(conn, tmp_path, tmp_path, NOW, runtime)
    found = tool_results.measure(conn, NOW, 14, state_dir=tmp_path, version=runtime)
    assert [r.role for r in found.roles] == ["implement", "review", "chore", "overseer"]
    implement = found.roles[0]
    assert (implement.runs, implement.read, implement.cut_logs, implement.calls) == (3, 2, 0, 10)
    assert (implement.chars, implement.repeated) == (1496, 1)
    status_sent = [sent(FIRST[5]) + sent(FIRST[7]), sent(SECOND[0])]
    assert (implement.status_runs, implement.status_calls, implement.status_chars) == (2, 3, sum(status_sent))
    assert implement.status_median == sum(status_sent) / 2
    rows = [(t.tool, t.calls, t.chars, t.median, t.cut, t.unknown, t.repeated) for t in implement.tools]
    assert rows == [
        ("$ gh run view", 1, 1000, 1000, 1, 0, 0),
        ("read", 4, 280, 75, 1, 0, 1),
        ("$ gh pr view", 1, 200, 200, 0, 0, 0),
        ("grep", 1, 10, 10, 0, 1, 0),
        ("canopy_run_status", 3, 6, 2, 0, 3, 0),
    ]
    assert implement.tools[0].share == 1000 / 1496
    review, chore, overseer = found.roles[1:]
    assert [(t.tool, t.calls, t.repeated) for t in review.tools] == [("read", 2, 0)]
    assert review.status_runs == 0
    assert review.status_median is None
    assert [(t.tool, t.chars) for t in chore.tools] == [("$ rg", 20)]
    assert [(t.tool, t.chars) for t in overseer.tools] == [("canopy_decide", 2)]
    month = tool_results.measure(conn, NOW, 60, state_dir=tmp_path, version=runtime)
    assert month.roles[0].runs == 4
    assert tool_results.measure(conn, NOW - timedelta(days=60), 1, state_dir=tmp_path, version=runtime).roles == ()


def test_a_shell_call_the_agent_named_bash_counts_as_its_program(
    tmp_path: Path,
    journals: Journals,
    runtime: Version,
) -> None:
    """OpenCode 2 prints a call under the name its agent gave, `bash` for some: its row is still its program's."""
    conn = journals.open(tmp_path / "canopy.db")
    calls = [Made("bash", {"command": "gh pr view 3 --json comments"}, "s" * 40), shell("gh run view 7", 60)]
    worker(conn, tmp_path / "named.log", NOW - timedelta(hours=1), calls, runtime)
    [implement] = tool_results.measure(conn, NOW, 1, state_dir=tmp_path, version=runtime).roles
    assert [(t.tool, t.calls, t.chars) for t in implement.tools] == [("$ gh run view", 1, 60), ("$ gh pr view", 1, 40)]


def test_a_log_past_the_bound_is_read_to_it_and_marked(tmp_path: Path, journals: Journals, runtime: Version) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    run_id = worker(conn, tmp_path / "long.log", NOW - timedelta(hours=1), FIRST, runtime)
    log = present(db.get_run(conn, run_id))["log_path"]
    # Room for the first two events of the log, its first call and its model call, and no more.
    bound = sum(len(line) + 1 for line in Path(log).read_text().splitlines()[:2])
    with mock.patch.object(transcript, "MAX_BYTES", bound):
        found = tool_results.measure(conn, NOW, 1, state_dir=tmp_path, version=runtime)
    [implement] = found.roles
    assert (implement.read, implement.cut_logs, implement.calls, implement.chars) == (1, 1, 1, 100)
    assert found.bound == bound
    assert f"read to its first {bound} bytes" in tool_results_cli.render(found)[1]
    assert "1 read, 1 of them to the bound" in tool_results_cli.render(found)[3]


def test_the_report_is_printed_as_tables_and_as_json(
    tmp_path: Path,
    journals: Journals,
    runtime: Version,
    snapshot: SnapshotAssertion,
) -> None:
    """The same figures whichever runtime printed the logs, so one snapshot holds both."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_runs(conn, tmp_path, tmp_path, NOW, runtime)
    with in_zone("UTC"):
        found = tool_results.measure(conn, NOW, 14, state_dir=tmp_path, version=runtime)
        assert "\n".join(tool_results_cli.render(found)) == snapshot(name="text")
        assert json.dumps(found.as_json(), indent=2) == snapshot(name="json")
        empty = tool_results.measure(conn, NOW - timedelta(days=60), 1, state_dir=tmp_path, version=runtime)
        assert tool_results_cli.render(empty)[2:] == ["", "No run started and ended in the window."]


def test_canopy_tool_results_reads_the_last_two_weeks(
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--days` narrows it, and `--json` prints it as data."""
    journal_of_runs(canopy_env.journal(), tmp_path, canopy_env.state_dir, datetime.now(UTC), canopy_env.runtime)
    assert main(["tool-results"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[3] == "implement: 3 runs, 2 read; 10 calls returned 1.5k characters."
    assert main(["tool-results", "--days", "60", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert (found["days"], found["log_bound_bytes"]) == (60, transcript.MAX_BYTES)
    assert [(r["role"], r["runs"], r["read"]) for r in found["roles"]] == [
        ("implement", 4, 3),
        ("review", 1, 1),
        ("chore", 1, 1),
        ("overseer", 1, 1),
    ]
    assert found["roles"][0]["tools"][0] == {
        "tool": "$ gh run view",
        "calls": 1,
        "result_chars": 1000,
        "median_chars": 1000.0,
        "share": 1000 / 1501,
        "cut": 1,
        "cut_unknown": 0,
        "repeated_reads": 0,
    }
    assert main(["tool-results", "--days", "0"]) == 2
