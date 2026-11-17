"""Which servers and tools a window's runs were offered and called, and what the calls returned (DESIGN §13).

Over a hand-written journal: runs of each kind, what the runtime said it offered them, and the calls they recorded.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from canopy.core import run_offers, spend, sql, tool_report
from canopy.runtime.agents import AgentOffer, ServerOffer
from canopy.runtime.report import ToolUse
from tests.canopy.helpers import earlier
from tests.canopy.report_helpers import called, review, task, tick, worker

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence
    from pathlib import Path

    from canopy.core.run_models import RunTable
    from tests.conftest import Journals

NOW: Final = datetime(2026, 11, 8, 12, tzinfo=UTC)


def offered(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    agent: str,
    tools: Sequence[str] = ("read", "shell", "skill"),
    **servers: str,
) -> None:
    """What the runtime said it offered a run: its own `tools`, and each of `servers` with the reach given."""
    offer = AgentOffer(
        agent,
        servers=tuple(
            ServerOffer(name, "some" if reach == "some" else "all", ("deny x",) if reach == "some" else ())
            for name, reach in servers.items()
        ),
        tools=tuple(tools),
    )
    run_offers.record(conn, table, run_id, offer)


def row(found: tool_report.Tools, name: str, kind: tool_report.Kind = "tool") -> tool_report.Row:
    """A report's row for the server or tool `name`."""
    [one] = [r for r in found.rows if r.name == name and r.kind == kind]
    return one


def test_a_tool_is_counted_by_the_runs_offered_it_and_those_that_called_it(conn: sqlite3.Connection) -> None:
    """Offered is a run whose offer names it; called, one of those with a call of it, failed or not."""
    day = earlier(NOW, 1)
    first, second, reviewer = worker(conn, day), worker(conn, day), review(conn, day)
    offered(conn, "runs", first, "canopy-worker")
    offered(conn, "runs", second, "canopy-worker")
    offered(conn, "review_runs", reviewer, "canopy-reviewer", ("read",))
    called(conn, "runs", first, 0, ToolUse("shell", 9, 2, 700), ToolUse("read", 4, 0, 4000))
    called(conn, "runs", second, 0, ToolUse("shell", 1, 1, 30))
    found = tool_report.report(conn, NOW, 7)
    assert [(r.kind, r.name) for r in found.rows] == [("tool", "read"), ("tool", "shell"), ("tool", "skill")]
    shell = row(found, "shell")
    assert shell.uses == [
        tool_report.Use("canopy-worker", offered=2, called=2, runs=2, calls=10, errors=3, result_chars=730),
    ]
    assert (shell.listed, shell.server, shell.unused) == (True, None, False)
    read = row(found, "read")
    assert read.uses == [
        tool_report.Use("canopy-worker", offered=2, called=1, runs=1, calls=4, result_chars=4000),
        tool_report.Use("canopy-reviewer", offered=1),
    ]
    assert (read.offered, read.called, read.calls) == (3, 1, 4)
    assert row(found, "skill").unused
    assert (found.servers, found.tools, found.unused, found.calls, found.errors) == (0, 3, 1, 14, 3)
    assert found.agents == [
        tool_report.Agent(
            "canopy-worker",
            runs=2,
            said=2,
            unanswered=0,
            tools=3,
            unused=1,
            calls=14,
            errors=3,
            result_chars=4730,
        ),
        tool_report.Agent("canopy-reviewer", runs=1, said=1, unanswered=0, tools=1, unused=1),
    ]


def test_a_load_of_any_skill_is_a_call_of_the_skill_tool(conn: sqlite3.Connection) -> None:
    """A run's loads are recorded by skill; together they are one run that called the skill tool."""
    ran = worker(conn, earlier(NOW, 1))
    offered(conn, "runs", ran, "canopy-worker")
    called(conn, "runs", ran, 0, ToolUse("skill:tracker-jira", 1, 0, 3000), ToolUse("skill:terse", 2, 1, 50))
    found = tool_report.report(conn, NOW, 7)
    assert row(found, "skill").uses == [
        tool_report.Use("canopy-worker", offered=1, called=1, runs=1, calls=3, errors=1, result_chars=3050),
    ]
    assert [r.name for r in found.rows] == ["read", "shell", "skill"]


def test_a_server_is_called_in_a_run_that_called_a_tool_named_for_it(conn: sqlite3.Connection) -> None:
    """A server's tools are known by their calls alone, each under the server's name as the runtime writes it."""
    day = earlier(NOW, 1)
    first, second, third = worker(conn, day), worker(conn, day), worker(conn, day)
    offered(conn, "runs", first, "canopy-worker", github="all", **{"my.tracker": "some"})
    offered(conn, "runs", second, "canopy-worker", github="all", **{"my.tracker": "some"})
    offered(conn, "runs", third, "canopy-worker", ())
    called(
        conn,
        "runs",
        first,
        0,
        ToolUse("github_pull_request_read", 3, 1, 9000),
        ToolUse("github_get_me", 1, 0, 100),
        ToolUse("shell", 1, 0, 10),
    )
    # A run offered no server called one's tool all the same: counted, and not among the runs offered it.
    called(conn, "runs", third, 0, ToolUse("github_get_me", 1, 0, 100), ToolUse("elsewhere_tool", 2, 0, 20))
    found = tool_report.report(conn, NOW, 7)
    github = row(found, "github", "server")
    assert github.uses == [
        tool_report.Use("canopy-worker", offered=2, called=1, runs=2, calls=5, errors=1, result_chars=9200),
    ]
    assert github.uses[0].unoffered == 1
    tracker = row(found, "my.tracker", "server")
    assert tracker.uses == [tool_report.Use("canopy-worker", offered=2, partial=2)]
    assert tracker.unused
    read = row(found, "github_pull_request_read")
    assert (read.server, read.listed, read.offered, read.runs, read.calls) == ("github", False, 0, 1, 3)
    assert not read.unused
    # A tool no offer names and no server's name opens is listed by its calls, placed nowhere.
    assert (row(found, "elsewhere_tool").server, row(found, "elsewhere_tool").listed) == (None, False)
    # The runtime's own tool, offered to two runs and called by one of them, stays its own.
    assert (row(found, "shell").server, row(found, "shell").listed) == (None, True)
    assert (found.servers, found.tools, found.unused) == (2, 3, 3)
    [agent] = found.agents
    assert (agent.servers, agent.tools, agent.unused, agent.calls) == (2, 3, 3, 8)


def test_a_tool_is_of_the_server_with_the_longest_name_it_opens_with(conn: sqlite3.Connection) -> None:
    """`git_hub_x` is `git_hub`'s, not `git`'s, in the row it sits under and in the runs each server counts."""
    ran = worker(conn, earlier(NOW, 1))
    offered(conn, "runs", ran, "canopy-worker", (), git="all", git_hub="all")
    called(conn, "runs", ran, 0, ToolUse("git_hub_issue", 2, 0, 40))
    found = tool_report.report(conn, NOW, 7)
    assert row(found, "git_hub_issue").server == "git_hub"
    assert (row(found, "git_hub", "server").called, row(found, "git_hub", "server").calls) == (1, 2)
    assert (row(found, "git", "server").called, row(found, "git", "server").calls) == (0, 0)
    assert row(found, "git", "server").unused


def test_a_tool_of_the_runtime_s_own_is_no_server_s_whatever_its_name(conn: sqlite3.Connection) -> None:
    """A tool an offer names stays the runtime's own, in its row and in the runs a server of its prefix counts."""
    ran = worker(conn, earlier(NOW, 1))
    offered(conn, "runs", ran, "canopy-worker", ("web_fetch",), web="all")
    called(conn, "runs", ran, 0, ToolUse("web_fetch", 3, 0, 90))
    found = tool_report.report(conn, NOW, 7)
    assert (row(found, "web_fetch").server, row(found, "web_fetch").listed) == (None, True)
    web = row(found, "web", "server")
    assert (web.offered, web.called, web.runs, web.calls) == (1, 0, 0, 0)
    assert web.unused


def test_what_the_journal_cannot_say_is_counted_apart(conn: sqlite3.Connection) -> None:
    """A run never asked about, and one the runtime could not answer for, have calls and no offer."""
    day = earlier(NOW, 1)
    asked, unanswered, never = worker(conn, day), worker(conn, day), task(conn, day)
    offered(conn, "runs", asked, "canopy-worker", ("shell",))
    run_offers.record(conn, "runs", unanswered, AgentOffer("canopy-worker", error="it timed out"))
    called(conn, "runs", unanswered, 0, ToolUse("shell", 2, 0, 20))
    called(conn, "task_runs", never, 0, ToolUse("shell", 5, 0, 50), ToolUse("write", 1, 0, 5))
    found = tool_report.report(conn, NOW, 7)
    shell = row(found, "shell")
    assert shell.uses == [
        tool_report.Use("canopy-worker", offered=1, runs=1, calls=2, result_chars=20),
        tool_report.Use("canopy-worker-private", runs=1, calls=5, result_chars=50),
    ]
    assert [u.unoffered for u in shell.uses] == [1, 1]
    # Offered once and called only by runs with no offer on record: not a tool nobody calls.
    assert not shell.unused
    assert (row(found, "write").listed, row(found, "write").offered) == (False, 0)
    assert [(a.agent, a.runs, a.said, a.unanswered, a.unasked) for a in found.agents] == [
        ("canopy-worker", 2, 1, 1, 0),
        ("canopy-worker-private", 1, 0, 0, 1),
    ]
    assert (found.runs, found.unanswered, found.unasked) == (3, 1, 1)


def test_only_the_window_s_ended_runs_are_read(conn: sqlite3.Connection) -> None:
    """A run counts in the window it started in, once it has ended; a tick that ran no overseer is no run."""
    for started in (earlier(NOW, 1), earlier(NOW, 8)):
        ran = worker(conn, started)
        offered(conn, "runs", ran, "canopy-worker", ("shell",), github="all")
        called(conn, "runs", ran, 0, ToolUse("shell", 1, 0, 10))
    running = worker(conn, earlier(NOW, 0), ended=False)
    offered(conn, "runs", running, "canopy-worker", ("shell", "read"), jira="all")
    found = tool_report.report(conn, NOW, 7)
    assert (found.since, found.until, found.days) == ("2026-11-02T00:00:00.000Z", "2026-11-09T00:00:00.000Z", 7)
    assert [(r.kind, r.name, r.offered, r.calls) for r in found.rows] == [
        ("server", "github", 1, 0),
        ("tool", "shell", 1, 1),
    ]
    assert [(a.agent, a.runs) for a in found.agents] == [("canopy-worker", 1)]
    before = tool_report.between(conn, *spend.window_before(found.since, 7))
    assert (before.until, before.days) == (found.since, 7)
    assert [(r.name, r.offered) for r in before.rows] == [("github", 1), ("shell", 1)]
    empty = tool_report.between(conn, NOW - timedelta(days=40), NOW - timedelta(days=30))
    assert (empty.rows, empty.agents) == ([], [])
    assert (empty.servers, empty.tools, empty.unused, empty.calls, empty.runs) == (0, 0, 0, 0, 0)


def test_the_overseer_s_ticks_count_under_it(conn: sqlite3.Connection) -> None:
    """A tick whose overseer ran is its run; one that ran none is no agent's."""
    ran = tick(conn, earlier(NOW, 1))
    tick(conn, earlier(NOW, 1), overseer_ran=0)
    offered(conn, "ticks", ran, "canopy-overseer", (), canopy="all")
    called(conn, "ticks", ran, 0, ToolUse("canopy_decide", 2, 0, 80))
    found = tool_report.report(conn, NOW, 7)
    [agent] = found.agents
    assert (agent.agent, agent.runs, agent.servers, agent.tools, agent.unused, agent.calls) == (
        "canopy-overseer",
        1,
        1,
        0,
        0,
        2,
    )
    assert row(found, "canopy", "server").called == 1


def test_each_read_starts_from_the_window_s_runs(tmp_path: Path, journals: Journals) -> None:
    """The run table leads, by its `started_at` index, so a window's cost is its own runs', not the whole history's.

    A journal in a test is too small for a slow plan to show in its time, so the plan is what is held.
    """
    conn = journals.open(tmp_path / "canopy.db")
    since, until = earlier(NOW, 7), earlier(NOW, 0)
    prefixes = {"git": "git_", "git_hub": "git_hub_"}
    for query in (
        tool_report._ran(since, until),  # noqa: SLF001
        tool_report._offered(since, until),  # noqa: SLF001
        tool_report._called(since, until),  # noqa: SLF001
        tool_report._servers(since, until),  # noqa: SLF001
        tool_report._reached("git", prefixes, {"git_own"}, since, until),  # noqa: SLF001
    ):
        plan = [str(step[3]) for step in sql.execute(conn, sql.frag("EXPLAIN QUERY PLAN {}", query))]
        runs = [step for step in plan if re.match(r"(SEARCH|SCAN) r\b", step)]
        assert runs, plan
        for step in runs:
            assert re.match(r"SEARCH r USING (COVERING )?INDEX \w+ \(started_at>\? AND started_at<\?\)", step), plan
        for step in plan:
            if re.match(r"(SEARCH|SCAN) [ost]\b", step):
                assert re.match(
                    r"SEARCH [ost] USING (PRIMARY KEY|COVERING INDEX \w+) \(run_table=\? AND run_id=\?",
                    step,
                ), plan
