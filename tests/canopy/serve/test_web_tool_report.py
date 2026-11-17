"""The web UI's Tools report (DESIGN §13): which MCP servers and tools the agents were offered and called.

Reads only.
"""

from datetime import UTC, datetime, timedelta

from canopy.core import db, run_offers, spend, tool_report
from canopy.infra import resources
from canopy.runtime.agents import AgentOffer, ServerOffer
from canopy.runtime.report import ToolUse
from canopy.serve.backend import Backend
from tests.canopy.helpers import context
from tests.canopy.report_helpers import called, task, worker
from tests.canopy.web_helpers import client, signed_in_client
from tests.conftest import CanopyEnv


def test_the_tools_report_counts_each_server_and_tool_by_agent_and_says_what_it_cannot(canopy_env: CanopyEnv) -> None:
    """Two worker runs offered a server and two tools, a task's run never asked about, and a run of the week before."""
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    now = datetime(2026, 11, 8, 12, tzinfo=UTC)
    start, _ = spend.window(now, spend.DEFAULT_DAYS)
    first, second, before = (
        worker(ctx.conn, db.format_time(started))
        for started in (start + timedelta(hours=2), start + timedelta(days=1), start - timedelta(days=2))
    )
    unasked = task(ctx.conn, db.format_time(start + timedelta(hours=3)))
    offer = AgentOffer("canopy-worker", servers=(ServerOffer("github", "some", ("deny github_merge*",)),))
    for run in (first, second, before):
        run_offers.record(
            ctx.conn,
            "runs",
            run,
            AgentOffer(offer.agent, servers=offer.servers, tools=("glob", "shell")),
        )
    called(ctx.conn, "runs", first, 0, ToolUse("shell", 5, 1, 4_000), ToolUse("github_get_me", 2, 0, 800))
    called(ctx.conn, "task_runs", unasked, 0, ToolUse("shell", 1, 0, 400))
    c, _ = signed_in_client(ctx, now=now)
    found = c.get("/api/reports/tools").json()
    assert (found["days"], found["since"], found["until"]) == (7, "2026-11-02T00:00:00Z", "2026-11-09T00:00:00Z")
    assert (found["servers"], found["tools"], found["unused"], found["calls"], found["errors"]) == (1, 2, 1, 8, 1)
    assert (found["runs"], found["unanswered"], found["unasked"]) == (3, 0, 1)
    github, get_me, glob, shell = found["rows"]
    assert github == {
        "kind": "server",
        "name": "github",
        "server": None,
        "listed": True,
        "unused": False,
        "offered": 2,
        "partial": 2,
        "called": 1,
        "unoffered": 0,
        "calls": 2,
        "errors": 0,
        "est_result_tokens": 200,
        "uses": [
            {
                "agent": "canopy-worker",
                "offered": 2,
                "partial": 2,
                "called": 1,
                "unoffered": 0,
                "calls": 2,
                "errors": 0,
                "est_result_tokens": 200,
            },
        ],
    }
    # A server's tool is in no offer by name: listed by its calls, under its server.
    assert (get_me["name"], get_me["server"], get_me["listed"]) == ("github_get_me", "github", False)
    assert (get_me["offered"], get_me["unoffered"], get_me["calls"]) == (0, 1, 2)
    assert (glob["name"], glob["offered"], glob["called"], glob["unused"]) == ("glob", 2, 0, True)
    assert (shell["offered"], shell["called"], shell["unoffered"], shell["calls"], shell["errors"]) == (2, 1, 1, 6, 1)
    assert shell["est_result_tokens"] == 1_100
    assert [u["agent"] for u in shell["uses"]] == ["canopy-worker", "canopy-worker-private"]
    worker_row, private = found["agents"]
    assert worker_row == {
        "agent": "canopy-worker",
        "runs": 2,
        "unanswered": 0,
        "unasked": 0,
        "servers": 1,
        "tools": 2,
        "unused": 1,
        "calls": 7,
        "errors": 1,
        "est_result_tokens": 1_200,
    }
    # No run of the task's agent was answered for: what it is offered is not known, where none would be 0.
    assert (private["servers"], private["tools"], private["unused"]) == (None, None, None)
    assert (private["runs"], private["unasked"], private["calls"]) == (1, 1, 1)
    assert found["previous"] == {
        "since": "2026-10-26T00:00:00Z",
        "until": found["since"],
        "servers": 1,
        "tools": 2,
        "unused": 3,
        "calls": 0,
        "errors": 0,
    }


def test_the_tools_report_reads_the_mocks_day_of_offers_and_calls(backend: Backend) -> None:
    """The mock's day: three servers and seven tools offered, one server and three tools never called."""
    c = client(None, backend)
    found = c.get("/api/reports/tools").json()
    assert (found["days"], found["since"], found["until"]) == (7, "2026-10-02T00:00:00Z", "2026-10-09T00:00:00Z")
    with backend.open() as ctx:
        expected = tool_report.report(ctx.conn, backend.clock(), 7)
    assert [(r["kind"], r["name"], r["offered"], r["called"], r["calls"]) for r in found["rows"]] == [
        (r.kind, r.name, r.offered, r.called, r.calls) for r in expected.rows
    ]
    assert [(r["kind"], r["name"], r["offered"], r["called"], r["calls"]) for r in found["rows"]] == [
        # The planner's and the reviewer's rules leave them only some of the forge's tools.
        ("server", "github", 19, 3, 27),
        ("server", "jira", 18, 2, 5),
        # Offered to every worker's run, and called by none.
        ("server", "sentry", 6, 0, 0),
        ("tool", "bash", 21, 9, 149),
        ("tool", "edit", 9, 1, 9),
        ("tool", "github_pull_request_read", 0, 0, 27),
        ("tool", "glob", 19, 0, 0),
        ("tool", "grep", 19, 0, 0),
        ("tool", "jira_search", 0, 0, 5),
        ("tool", "read", 19, 7, 76),
        # Every load of a skill, and the tasks' and an epic's plan run's, which no offer is on record for.
        ("tool", "skill", 19, 12, 26),
        ("tool", "write", 9, 0, 0),
    ]
    by_name = {r["name"]: r for r in found["rows"]}
    assert by_name["github"]["partial"] == 10
    assert (by_name["skill"]["unoffered"], by_name["skill"]["errors"]) == (3, 1)
    assert [(r["name"], r["server"]) for r in found["rows"] if not r["listed"]] == [
        ("github_pull_request_read", "github"),
        ("jira_search", "jira"),
    ]
    assert [r["name"] for r in found["rows"] if r["unused"]] == ["sentry", "glob", "grep", "write"]
    assert (found["servers"], found["tools"], found["unused"]) == (3, 7, 4)
    assert (found["calls"], found["errors"]) == (expected.calls, expected.errors) == (292, 15)
    assert [(a["agent"], a["runs"], a["servers"], a["tools"], a["unused"], a["calls"]) for a in found["agents"]] == [
        ("canopy-overseer", 2, 2, 1, 0, 45),
        ("canopy-worker", 4, 3, 7, 5, 160),
        ("canopy-worker-private", 7, 2, 7, 6, 46),
        ("canopy-planner", 8, 2, 5, 6, 5),
        ("canopy-reviewer", 6, 2, 5, 4, 23),
        ("canopy-chore", 1, 1, 7, 7, 3),
        ("canopy-chore-deps", 2, 1, 7, 7, 10),
    ]
    assert (found["runs"], found["unanswered"], found["unasked"]) == (30, 1, 8)
    month = c.get("/api/reports/tools", params={"days": 30}).json()
    assert (month["days"], month["runs"]) == (30, 51)
    assert c.get("/api/reports/tools", params={"days": 0}).status_code == 422
    assert c.get("/api/reports/tools", params={"days": spend.MAX_DAYS + 1}).status_code == 422
