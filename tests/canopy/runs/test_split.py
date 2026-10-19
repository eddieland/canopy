"""Split tickets (DESIGN §18, ROADMAP M8): a split run reads a desk of worktrees and records the tickets it created."""

import json
import sqlite3
from pathlib import Path

import pytest

from canopy.core import db
from canopy.core.vocab import RunKind
from canopy.loop import attention
from canopy.runs import worker
from tests.canopy.conftest import Ws
from tests.canopy.helpers import (
    LABEL,
    InlineRunner,
    agent_runs,
    canopy,
    decisions,
    in_tick,
    pool_statuses,
    present,
    splitter_reports,
    waits,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import git

BOTH = ("api", "web")
#: The tickets a split of PROJ-12 over BOTH makes, and the repository each covers.
CHILDREN = {"PROJ-13": "api", "PROJ-14": "web"}


def split(key: str, request: str = "1", repo: str | tuple[str, ...] = BOTH) -> list[str]:
    """The overseer dispatches a split of `key` over `repo`, asked for in comment `request`."""
    return dispatches(key, RunKind.SPLIT, repo=repo, request=request)


def children(conn: sqlite3.Connection) -> list[tuple[str, str, str, int]]:
    rows = conn.execute("SELECT child_key, parent_key, repo, run_id FROM split_children ORDER BY child_key")
    return [tuple(r) for r in rows]


def test_a_split_reads_a_desk_and_records_its_children(
    ws_scenario: Scenario, ws: Ws, treehouse_state: Path, agent_log: Path
) -> None:
    """M8 acceptance, against the fakes: a requested split creates a child per repository and pushes nothing."""
    (ws.root / "MAP.md").write_text("# Map\n\napi serves {{KEY}}; web calls it.\n")
    conn = ws_scenario.conn
    result = {"status": "done", "summary": "split in two", "children": {"PROJ-13": "api", "PROJ-14": "web"}}
    porcelain = ["git", "-C", "api", "status", "--porcelain=v2", "--branch"]
    run = ws_scenario.run(split("PROJ-12", request="10234"), worker=splitter_reports(result, porcelain))
    assert run.status == "done", run.printed.out

    desk = ws.root / "desks" / "PROJ-12"
    [splitter] = agent_runs(agent_log)
    assert splitter["argv"][:3] == ["run", "--agent", "canopy-splitter"]
    assert splitter["cwd"] == str(desk)
    # Each worktree is at its base, detached: a split creates no branch.
    [status] = splitter["commands"]
    assert "# branch.head (detached)" in status["stdout"]
    assert not desk.exists()
    assert pool_statuses(treehouse_state) == ["available", "available"]
    for name in BOTH:
        assert git("for-each-ref", "refs/heads/", cwd=ws.origins[name]).count("\n") == 0  # only main

    assert children(conn) == [("PROJ-13", "PROJ-12", "api", 1), ("PROJ-14", "PROJ-12", "web", 1)]
    # The children carry the work now: the parent is never dispatched again.
    assert ws_scenario.refuses(dispatches("PROJ-12", repo="api")) == [
        ("refused:bad_split", "PROJ-12 was split into PROJ-13, PROJ-14; dispatch those instead")
    ]
    # The parent gets no branch and no units: the children carry the work.
    assert present(db.get_ticket(conn, "PROJ-12")).branch is None
    assert db.units(conn, "PROJ-12") == []
    assert run.branch == ""
    [(action, rationale)] = decisions(conn, int(run.row["tick_id"]))
    assert action == "dispatch:split"
    assert rationale.startswith("run 1: split PROJ-12 into api, web in api at ")
    assert rationale.endswith(f"; desk {desk}; label {LABEL}; request 10234")

    prompt = run.prompt
    assert prompt.startswith("# canopy worker: split\n")
    assert "Read comment 10234 on PROJ-12." in prompt
    assert f"- `api` at `{desk / 'api'}`, at `main`. The api repository." in prompt
    assert f"- `web` at `{desk / 'web'}`, at `main`. The web repository." in prompt
    assert "attempt 1 of 1" in prompt
    # The map's text, not its path: the splitter may not read outside its desk. Its placeholders are left as
    # they are.
    assert "how they depend on each other:\n\n# Map\n\napi serves {{KEY}}; web calls it.\n" in prompt


@pytest.mark.parametrize(
    ("args", "guard", "reason"),
    [
        (
            ["--repo", "api", "--repo", "web"],
            "unauthorized",
            "--request is required for a split: name the authorized replier's comment on PROJ-12 that asked for it",
        ),
        (
            ["--request", "1", "--repo", "api"],
            "bad_split",
            "a split names every repository PROJ-12 covers, at least two; name each with --repo",
        ),
        (
            ["--request", "1", "--repo", "api", "--repo", "web", "--slug", "work"],
            "bad_slug",
            "a split creates tickets and names no branch; leave out --slug",
        ),
        (
            ["--request", "1", "--repo", "api", "--repo", "web", "--base", "agent/PROJ-1-work"],
            "bad_base",
            "a split creates tickets and starts from no branch; leave out --base",
        ),
    ],
)
def test_split_guards(ws_scenario: Scenario, treehouse_state: Path, args: list[str], guard: str, reason: str) -> None:
    assert ws_scenario.refuses(canopy("dispatch", "PROJ-12", "--label", LABEL, "--kind", "split", *args)) == [
        (f"refused:{guard}", reason)
    ]
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_request_is_for_split_only(ws_scenario: Scenario) -> None:
    assert ws_scenario.refuses(dispatches("PROJ-12", repo="api", request="1")) == [
        ("refused:bad_request", "--request names the comment asking for a split; it is for split only")
    ]


def test_a_started_ticket_is_not_split_and_a_split_has_an_attempt_limit(ws_scenario: Scenario) -> None:
    conn = ws_scenario.conn
    ws_scenario.run(dispatches(repo="api"), worker=pushes())
    assert ws_scenario.refuses(split("PROJ-1")) == [
        ("refused:bad_split", "PROJ-1 already has work on agent/PROJ-1-work; a started ticket is not split")
    ]

    failed = ws_scenario.run(split("PROJ-12"), worker=splitter_reports({"status": "failed", "summary": "one change"}))
    assert failed.status == "failed"
    limit = "PROJ-12 has had 1 split runs and the limit is 1"
    assert ws_scenario.refuses(split("PROJ-12", request="2")) == [
        ("refused:attempt_limit", limit),
        ("attention:attempt_limit", limit),
    ]
    # A split's runs are the ticket's, never a unit's.
    assert db.units(conn, "PROJ-12") == []


def test_a_workspace_of_one_repository_is_never_split(scenario: Scenario) -> None:
    assert scenario.refuses(dispatches(kind=RunKind.SPLIT, request="1")) == [
        ("refused:bad_split", "a split names every repository PROJ-1 covers, at least two; name each with --repo")
    ]


@pytest.mark.parametrize(
    ("result", "note"),
    [
        ({"status": "done", "children": {}}, "a done split must name the tickets it created"),
        ({"status": "done", "children": {"PROJ 13": "api"}}, "child 'PROJ 13' is not a ticket key"),
        ({"status": "done", "children": {"PROJ-12": "api"}}, "child PROJ-12 is the ticket that was split"),
        (
            {"status": "done", "children": {"OLD-1": "api"}},
            "child OLD-1 is not a new ticket: the journal already knows it",
        ),
        (
            {"status": "done", "children": {"SEEN-1": "api"}},
            "child SEEN-1 is not a new ticket: the journal already knows it",
        ),
        (
            {"status": "done", "children": {"PROJ-13": "docs"}},
            "child PROJ-13's repository 'docs' is not one the split was dispatched with",
        ),
        (
            {"status": "done", "children": {"PROJ-13": "api", "PROJ-14": "api"}},
            "two children cover api; a split makes at most one ticket per repository",
        ),
        (
            {"status": "done", "children": {"P-" + "1" * worker.MAX_CHILD_KEY: "api"}},
            f"child {('P-' + '1' * (worker.MAX_CHILD_KEY - 2))!r} is not a ticket key",
        ),
        (
            {"status": "done", "children": {f"PROJ-{i}": "api" for i in range(13, 5000)}},
            "two children cover api; a split makes at most one ticket per repository",
        ),
    ],
)
def test_invalid_children_are_recorded_nowhere(
    ws_scenario: Scenario, treehouse_state: Path, result: object, note: str
) -> None:
    conn = ws_scenario.conn
    # OLD-1 is a ticket the journal has dispatched before, and SEEN-1 one the overseer has decided about: a splitter
    # must claim neither.
    ws_scenario.run(dispatches("OLD-1", repo="api"), worker=pushes())
    ws_scenario.seen("SEEN-1")
    run = ws_scenario.run(split("PROJ-12"), worker=splitter_reports(result))
    assert (run.id, run.status) == (2, "unknown")
    stored = json.loads(run.row["result_json"])
    assert stored["harness"] == f"children not recorded: {note}"
    # A refused map is not stored: however many children it named, the journal keeps none of them.
    assert stored["children"] == {}
    assert children(conn) == []
    assert pool_statuses(treehouse_state) == ["available", "available"]
    [item] = [i for i in attention.from_runs(conn) if i.ticket_key == "PROJ-12"]
    assert item.reason == "unknown_result"
    assert item.detail.startswith("run:2 (split) ended unknown: children not recorded: ")


def test_a_blocked_or_missing_split_result_is_unknown() -> None:
    assert worker.parse_split('{"status":"blocked","children":{}}') is None
    assert worker.parse_split("no result") is None
    assert worker.parse_split('{"status":"failed","summary":"one change"}') == worker.SplitResult(
        status="failed", summary="one change"
    )


def test_a_failed_split_records_what_it_created(ws_scenario: Scenario) -> None:
    result = {"status": "failed", "summary": "tracker errored", "children": {"PROJ-13": "api"}}
    run = ws_scenario.run(split("PROJ-12"), worker=splitter_reports(result))
    assert run.status == "failed"
    assert children(ws_scenario.conn) == [("PROJ-13", "PROJ-12", "api", 1)]


def test_a_timed_out_split_records_the_children_it_reported(ws_scenario: Scenario, treehouse_state: Path) -> None:
    result = {"status": "done", "summary": "split", "children": {"PROJ-13": "api"}}
    runner = InlineRunner(timeout_agent=True, timeout_stdout=json.dumps(result) + "\n")
    run = ws_scenario.run(split("PROJ-12"), runner=runner)
    assert run.status == "timeout"
    assert json.loads(run.row["result_json"])["harness"] == "the splitter timed out after 45 minutes"
    # The child exists in the tracker, so the journal knows it and a retry cannot make it again.
    assert children(ws_scenario.conn) == [("PROJ-13", "PROJ-12", "api", 1)]
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_child_is_not_worked_in_a_workspace_of_another_repository(scenario: Scenario) -> None:
    conn = scenario.conn
    with in_tick(conn, ends_ok=True) as tick_id:
        db.touch_ticket(conn, "PROJ-12", str(scenario.env.root))
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, log_path, status) "
            "VALUES (?, 'PROJ-12', 'split', '', 'x', 'y', 'l', 'done')",
            (tick_id,),
        )
        db.record_split_children(conn, "PROJ-12", 1, {"PROJ-13": "api"})
    assert scenario.refuses(dispatches("PROJ-13"), dry_run=True) == [
        ("refused:unknown_repo", "PROJ-13 was split from PROJ-12 to cover api only; dispatch it with --repo api")
    ]


def test_a_child_is_dispatched_only_in_its_repository(ws_scenario: Scenario) -> None:
    ws_scenario.run(split("PROJ-12"), worker=splitter_reports({"status": "done", "children": CHILDREN}))
    reason = "PROJ-13 was split from PROJ-12 to cover api only; dispatch it with --repo api"
    for repo in ("web", BOTH):
        assert ws_scenario.refuses(dispatches("PROJ-13", repo=repo), dry_run=True) == [("refused:unknown_repo", reason)]
    ticked = ws_scenario.tick(dispatches("PROJ-13", repo="api"), *waits("PROJ-12", "PROJ-14"), dry_run=True)
    would = f"dry run: not dispatched; would work on agent/PROJ-13-work in api; label {LABEL}"
    assert [(d.action, d.rationale) for d in ticked.decisions if d.ticket_key == "PROJ-13"] == [
        ("dispatch:implement", would)
    ]
    assert ws_scenario.refuses(split("PROJ-14"), dry_run=True) == [
        ("refused:bad_split", "PROJ-14 was created by splitting PROJ-12; it is not split again")
    ]


def test_a_dry_run_split_names_what_it_would_split(ws_scenario: Scenario) -> None:
    command = dispatches("PROJ-12", RunKind.SPLIT, repo=("web", "api"), request="c-9", cursors={"comment": "c-9"})
    ticked = ws_scenario.tick(command, dry_run=True)
    would = (
        f"dry run: not dispatched; would split PROJ-12 into web, api; label {LABEL}; request c-9; cursor comment=c-9"
    )
    assert [(d.action, d.rationale) for d in ticked.decisions if d.ticket_key == "PROJ-12"] == [
        ("dispatch:split", would)
    ]
    assert ws_scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_the_state_block_shows_split_children(ws_scenario: Scenario, ws: Ws) -> None:
    conn = ws_scenario.conn
    run = ws_scenario.run(split("PROJ-12"), worker=splitter_reports({"status": "done", "children": CHILDREN}))
    ws_scenario.tick(*waits("PROJ-12", rationale="split into PROJ-13 and PROJ-14"), dry_run=True)

    state = ws_scenario.state()
    assert state["policy"]["max_split_attempts"] == 1
    [ticket] = state["tickets"]
    assert (ticket["key"], ticket["split_attempts"], ticket["units"]) == ("PROJ-12", 1, [])
    assert ticket["last_run"]["kind"] == "split"
    assert state["split_children"] == [
        {"child": c, "parent": "PROJ-12", "repo": r, "split_run_id": 1, "split_ended_at": run.row["ended_at"]}
        for c, r in CHILDREN.items()
    ]

    # Once the parent and every child are done, the children leave the state block.
    for key in ("PROJ-12", *CHILDREN):
        db.set_ticket(conn, key, str(ws.root), done=True)
    assert db.open_split_children(conn) == []
