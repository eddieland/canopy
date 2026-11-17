"""The web UI's Skills report (DESIGN §13): which skills the agents were offered and loaded, and what they cost.

Reads only.
"""

from datetime import UTC, datetime, timedelta

from canopy.core import db, records, run_offers, skill_report, spend
from canopy.core.vocab import RunKind, RunStatus
from canopy.infra import resources
from canopy.runtime.agents import AgentOffer
from canopy.runtime.report import ToolUse
from canopy.serve.backend import Backend
from tests.canopy.helpers import context
from tests.canopy.web_helpers import client, signed_in_client
from tests.conftest import CanopyEnv


def test_the_skills_report_counts_each_skill_by_agent_and_says_what_it_cannot(canopy_env: CanopyEnv) -> None:
    """Two worker runs offered two skills, one of them loaded, and a run of the week before, by a fixed clock."""
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    now = datetime(2026, 11, 8, 12, tzinfo=UTC)
    start, _ = spend.window(now, spend.DEFAULT_DAYS)
    db.touch_ticket(ctx.conn, "PROJ-1", "/ws")
    runs = []
    for started in (start + timedelta(hours=2), start + timedelta(days=1), start - timedelta(days=2)):
        stamp = db.format_time(started)
        tick = records.insert(records.Tick, started_at=stamp, ended_at=stamp, dry_run=0, overseer_ran=0).run(ctx.conn)
        run = records.insert(
            records.Run,
            tick_id=tick.lastrowid,
            ticket_key="PROJ-1",
            kind=RunKind.IMPLEMENT,
            branch="agent/PROJ-1",
            started_at=stamp,
            ended_at=stamp,
            status=RunStatus.DONE,
            log_path="l",
        ).run(ctx.conn)
        assert run.lastrowid is not None
        runs.append(run.lastrowid)
    first, second, before = runs
    sizes = {"audit": 400, "terse": 5}
    run_offers.record(
        ctx.conn,
        "runs",
        first,
        AgentOffer("canopy-worker", skills=tuple(sizes), listing_chars=sizes),
    )
    # The second run's offer is from before canopy kept an entry's length, and its session is not read.
    run_offers.record(ctx.conn, "runs", second, AgentOffer("canopy-worker", skills=tuple(sizes)))
    run_offers.record(ctx.conn, "runs", before, AgentOffer("canopy-worker", skills=("audit",)))
    db.set_run_report(ctx.conn, "runs", first, "s", None, tools=[ToolUse("skill:audit", 2, 1, 8_000)])
    records.insert(records.RunModel, run_table="runs", run_id=first, model="a/b", replies=10, cost_usd=0.0).run(
        ctx.conn,
    )
    c, _ = signed_in_client(ctx, now=now)
    found = c.get("/api/reports/skills").json()
    assert (found["days"], found["since"], found["until"]) == (7, "2026-11-02T00:00:00Z", "2026-11-09T00:00:00Z")
    assert (found["offered"], found["unused"], found["loads"], found["unnamed"]) == (2, 1, 1, 0)
    assert (found["runs"], found["unanswered"], found["unasked"]) == (2, 0, 0)
    # Both runs were offered skills: one is counted, and the other's offer has no length on record.
    assert (found["listed"], found["unsized"], found["unread"], found["counted"]) == (2, 1, 0, 1)
    # 400 characters of front matter in each of ten model calls, and five of the other skill's: a thousand tokens.
    assert found["est_front_matter_tokens"] == (400 * 10 + 5 * 10) // 4
    assert found["est_call_tokens"] == 405 // 4
    audit, terse = found["skills"]
    assert {k: v for k, v in audit.items() if k != "uses"} == {
        "name": "audit",
        "countable": True,
        "unused": False,
        "offered": 2,
        "loaded": 1,
        "unoffered": 0,
        "loads": 1,
        "failed": 1,
        "est_body_tokens": 2_000,
        "front_matter_chars": 400,
        "est_call_tokens": 100,
        "counted": 1,
        "calls": 10,
        "est_front_matter_tokens": 1_000,
    }
    assert audit["uses"] == [
        {
            "agent": "canopy-worker",
            "offered": 2,
            "loaded": 1,
            "unoffered": 0,
            "loads": 1,
            "failed": 1,
            "est_body_tokens": 2_000,
            "front_matter_chars": 400,
            "est_call_tokens": 100,
            "counted": 1,
            "calls": 10,
            "est_front_matter_tokens": 1_000,
        },
    ]
    assert (terse["name"], terse["unused"], terse["front_matter_chars"], terse["est_call_tokens"]) == (
        "terse",
        True,
        5,
        1,
    )
    assert found["agents"] == [
        {
            "agent": "canopy-worker",
            "runs": 2,
            "unanswered": 0,
            "unasked": 0,
            "listed": 2,
            "unsized": 1,
            "unread": 0,
            "counted": 1,
            "calls": 10,
            "skills": 2,
            "unused": 1,
            "loads": 1,
            "unnamed": 0,
            "est_call_tokens": 405 // 4,
            "est_front_matter_tokens": 4_050 // 4,
        },
    ]
    # The window before ends where this one starts: its run was offered one skill, with no length, and loaded none,
    # so it has no cost to compare with: not known, never a cost of nothing.
    assert found["previous"] == {
        "since": "2026-10-26T00:00:00Z",
        "until": found["since"],
        "offered": 1,
        "unused": 1,
        "est_call_tokens": None,
    }


def test_the_skills_report_reads_the_mocks_day_of_offers_and_loads(backend: Backend) -> None:
    """The mock's day: eight skills offered, four of them never loaded, and the runs the journal cannot cost."""
    c = client(None, backend)
    found = c.get("/api/reports/skills").json()
    assert (found["days"], found["since"], found["until"]) == (7, "2026-10-02T00:00:00Z", "2026-10-09T00:00:00Z")
    with backend.open() as ctx:
        expected = skill_report.report(ctx.conn, backend.clock(), 7)
        listed = backend.skills(ctx).files
    assert [(s["name"], s["offered"], s["loaded"], s["loads"]) for s in found["skills"]] == [
        (s.name, s.offered, s.loaded, s.loads) for s in expected.skills
    ]
    assert [(s["name"], s["offered"], s["loaded"], s["unoffered"], s["loads"]) for s in found["skills"]] == [
        # The operator's own skill, denied to every agent: a call for it that failed, and no offer.
        ("canopy", 0, 0, 0, 0),
        ("canopy-artifacts", 4, 0, 0, 0),
        ("design-system", 11, 1, 0, 1),
        ("e2e-playwright", 11, 3, 0, 3),
        ("release-notes", 19, 3, 1, 5),
        ("store-listing", 3, 0, 0, 0),
        ("terse", 19, 0, 0, 0),
        # The prompts' skill: most runs offered it loaded it, and the tasks' and an epic's plan run besides.
        ("tracker-jira", 19, 12, 3, 15),
        ("write-a-skill", 19, 0, 0, 0),
    ]
    assert (found["offered"], found["unused"], found["loads"], found["unnamed"]) == (8, 4, 24, 1)
    assert [s["name"] for s in found["skills"] if s["unused"]] == [
        "canopy-artifacts",
        "store-listing",
        "terse",
        "write-a-skill",
    ]
    # The skills the skills page lists are costed at the mock's entry for each: its name and what the page says of it.
    by_name = {s["name"]: s for s in found["skills"]}
    assert {f.name: by_name[f.name]["front_matter_chars"] for f in listed} == {
        f.name: len(f.name) + len(f.description or "") for f in listed
    }
    agents = [
        (a["agent"], a["runs"], a["unanswered"], a["unasked"], a["listed"], a["counted"]) for a in found["agents"]
    ]
    assert agents == [
        # Offered no skill: its runs are answered for, and no part of what a cost is counted over.
        ("canopy-overseer", 2, 0, 0, 0, 0),
        ("canopy-worker", 4, 0, 0, 4, 2),
        # Its two runs of tickets, and five tasks' runs the runtime is never asked about.
        ("canopy-worker-private", 7, 0, 5, 2, 1),
        # Five plans' runs, none with its session read, and three epics' plan runs never asked about.
        ("canopy-planner", 8, 0, 3, 5, 0),
        ("canopy-reviewer", 6, 1, 0, 5, 3),
        ("canopy-chore", 1, 0, 0, 1, 1),
        ("canopy-chore-deps", 2, 0, 0, 2, 1),
    ]
    overseer, worker, private, planner = found["agents"][:4]
    # The overseer is sent no list, a known nothing; the worker's costs each call some 390 tokens; the planner's has
    # no call counted, so nothing says what its list costs.
    assert (overseer["skills"], overseer["est_call_tokens"], overseer["est_front_matter_tokens"]) == (0, 0, 0)
    assert (worker["skills"], worker["unused"], worker["loads"], worker["est_call_tokens"]) == (7, 3, 11, 387)
    assert (planner["counted"], planner["est_call_tokens"], planner["est_front_matter_tokens"]) == (0, None, None)
    # The call that named no skill was the private worker's: any skill of its may be the one it loaded.
    assert (private["unnamed"], found["unnamed"]) == (1, 1)
    assert (found["runs"], found["unanswered"], found["unasked"]) == (30, 1, 8)
    # Nineteen runs were offered a skill, the overseer's two none: eight are counted, the rest have no session read.
    assert (found["listed"], found["unsized"], found["unread"], found["counted"]) == (19, 0, 11, 8)
    # The whole, estimated once: not the agents' estimates summed, each of which rounds down.
    assert found["est_front_matter_tokens"] == expected.sent_tokens == 88_610
    # Some 350 tokens of front matter in each of the 254 model calls counted: the overseer's calls are not among them.
    assert found["est_call_tokens"] == 348
    # The month reaches the workers' runs of the weeks before, offered with no length kept: counted over no more runs.
    month = c.get("/api/reports/skills", params={"days": 30}).json()
    assert (month["days"], month["listed"], month["unsized"], month["counted"]) == (30, 24, 5, found["counted"])
    assert c.get("/api/reports/skills", params={"days": 0}).status_code == 422
    assert c.get("/api/reports/skills", params={"days": spend.MAX_DAYS + 1}).status_code == 422
