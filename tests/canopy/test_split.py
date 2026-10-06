"""Split tickets (DESIGN §18, ROADMAP M8): `dispatch --kind split`, the split run, and its children's repositories.

The harness's half of M8's acceptance: a split names two repositories, leases nothing, and records the children its
worker reports, and each child is then dispatched only in its own repository. Whether a child is labeled, and when, is
the overseer's to read from the tracker; the fakes cannot show it.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.loop import attention
from canopy.runs import worker
from tests.canopy.helpers import InlineRunner, Ws, journal, make_ws, wait_for_run
from tests.conftest import CanopyEnv

LABEL = "agent-ready-tester"
CHILDREN = {"PROJ-2": "api", "PROJ-3": "web"}


@pytest.fixture
def ws(canopy_env: CanopyEnv, treehouse_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ws:
    return make_ws(tmp_path, monkeypatch)


def in_tick(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, *, dry_run: bool = False) -> int:
    tick_id = db.start_tick(conn, dry_run=dry_run)
    monkeypatch.setenv("CANOPY_TICK_ID", str(tick_id))
    return tick_id


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str]]:
    return [(str(d["action"]), str(d["rationale"])) for d in db.decisions_for_tick(conn, tick_id)]


def split(key: str, *args: str) -> list[str]:
    """A split dispatch, with the authorized replier's comment that asked for it."""
    return ["dispatch", key, "--label", LABEL, "--kind", "split", "--request", "10234", *args]


def splitter_reports(monkeypatch: pytest.MonkeyPatch, children: dict[str, str], status: str = "done") -> None:
    result = {"status": status, "summary": "split it", "children": children}
    monkeypatch.setenv("FAKE_SPLITTER_RESULT", json.dumps(result))


def split_run(conn: sqlite3.Connection, parent: str, children: dict[str, str], *, status: str = "done") -> int:
    """Record a finished split run of `parent` that created `children`, as `_run` would."""
    tick_id = db.start_tick(conn, dry_run=False)
    db.finish_tick(conn, tick_id, "ok", "test")
    db.touch_ticket(conn, parent, "acme")
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key=parent,
        kind="split",
        lease=None,
        branch=None,
        runs_dir=Path("/state/runs"),
        repos=sorted(set(children.values())),
    )
    assert db.finish_run(conn, run_id, status, "{}", children=children)
    return run_id


def test_a_split_leases_nothing_runs_at_the_root_and_records_its_children(
    ws: Ws, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (ws.root / "MAP.md").write_text("# map\n")
    conn = ws.journal()
    tick_id = in_tick(conn, monkeypatch)
    splitter_reports(monkeypatch, CHILDREN)
    assert main(split("PROJ-1", "--repo", "web", "--repo", "api", "--context", "Split per the map")) == 0
    run = wait_for_run(conn, 1)

    assert run["status"] == "done", Path(run["log_path"]).read_text()
    assert (run["kind"], run["slot_path"], run["lease_id"], run["branch"], run["repo"]) == (
        "split",
        None,
        None,
        None,
        None,
    )
    assert db.run_repos(conn, 1) == ["api", "web"]
    assert decisions(conn, tick_id) == [
        ("dispatch:split", f"run 1: split across web, api as asked in comment 10234; label {LABEL}")
    ]
    # No pool was touched: the split reads the primary clones from the workspace root.
    assert not treehouse_state.exists()
    [agent] = [json.loads(line) for line in agent_log.read_text().splitlines()]
    assert agent["cwd"] == str(ws.root)
    assert agent["argv"][:3] == ["run", "--agent", "canopy-splitter"]
    prompt = agent["argv"][3]
    assert prompt.startswith("# canopy worker: split\n")
    assert f"- `api`, cloned at `{ws.clone('api')}`: The api repository." in prompt
    assert f"`{ws.root / 'MAP.md'}`" in prompt
    assert "Split per the map" in prompt
    assert "attempt 1 of 1" in prompt
    assert "Read comment `10234` on PROJ-1." in prompt

    assert [(c["child_key"], c["parent_key"], c["repo"], c["run_id"]) for c in db.open_splits(conn)] == [
        ("PROJ-2", "PROJ-1", "api", 1),
        ("PROJ-3", "PROJ-1", "web", 1),
    ]
    ticket = db.get_ticket(conn, "PROJ-1")
    assert ticket is not None
    assert ticket["branch"] is None
    assert json.loads(run["result_json"])["children"] == CHILDREN


def test_a_child_is_dispatched_only_in_its_recorded_repository(
    ws: Ws, treehouse_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = ws.journal()
    split_run(conn, "PROJ-1", CHILDREN)
    tick_id = in_tick(conn, monkeypatch, dry_run=True)
    implement = ["dispatch", "PROJ-3", "--label", LABEL, "--kind", "implement"]
    assert main([*implement, "--repo", "api"]) == 1
    assert main([*implement, "--repo", "web"]) == 0
    assert main(split("PROJ-2", "--repo", "api", "--repo", "web")) == 1
    assert decisions(conn, tick_id) == [
        ("refused:unknown_repo", "PROJ-3 was split from PROJ-1 for web; it is worked only there"),
        ("dispatch:implement", f"dry run: not dispatched; would work on agent/PROJ-3-work in web; label {LABEL}"),
        ("refused:unknown_repo", "PROJ-2 was split from PROJ-1 for api; it is not split again"),
    ]


def test_split_guards(ws: Ws, treehouse_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = ws.journal()
    tick_id = in_tick(conn, monkeypatch, dry_run=True)
    both = ("--repo", "api", "--repo", "web")
    cases = [
        split("PROJ-1", "--repo", "api"),
        split("PROJ-1", "--repo", "api", "--repo", "api"),
        split("PROJ-1", "--repo", "api", "--repo", "docs"),
        split("PROJ-1", *both, "--slug", "halves"),
        split("PROJ-1", *both, "--base", "agent/PROJ-9-work"),
        ["dispatch", "PROJ-1", "--label", LABEL, "--kind", "implement", *both],
        # The loop never splits on its own judgment: a split names the comment that asked for it (D055).
        ["dispatch", "PROJ-1", "--label", LABEL, "--kind", "split", *both],
        ["dispatch", "PROJ-1", "--label", LABEL, "--kind", "implement", "--repo", "api", "--request", "10234"],
        split("PROJ-1", *both),
    ]
    assert [main(args) for args in cases] == [1, 1, 1, 1, 1, 1, 1, 1, 0]
    assert decisions(conn, tick_id) == [
        (
            "refused:unknown_repo",
            "split names every repository PROJ-1 covers, at least two, each with --repo (api, web)",
        ),
        (
            "refused:unknown_repo",
            "split names every repository PROJ-1 covers, at least two, each with --repo (api, web)",
        ),
        ("refused:unknown_repo", "'docs' is not a repository in this workspace (api, web)"),
        ("refused:bad_slug", "split creates tickets and pushes no branch; --slug is for implement"),
        ("refused:bad_base", "split creates tickets and pushes no branch, so it has no base"),
        (
            "refused:unknown_repo",
            "implement works in one repository; only split names several until joint runs (ROADMAP M7, D052)",
        ),
        (
            "refused:unauthorized",
            "split needs --request naming the authorized replier's comment on PROJ-1 that asked for it",
        ),
        ("refused:bad_request", "--request names the comment that asked for a split; implement takes none"),
        (
            "dispatch:split",
            f"dry run: not dispatched; would split it across api, web as asked in comment 10234; label {LABEL}",
        ),
    ]


def test_a_ticket_with_work_in_one_repository_is_not_split_and_a_split_is_tried_once(
    ws: Ws, treehouse_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = ws.journal()
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner()
    db.touch_ticket(conn, "PROJ-5", "acme")
    db.insert_run(
        conn,
        tick_id=tick_id,
        key="PROJ-5",
        kind="implement",
        lease=db.RunLease(ws.root / "slot", "l1", "canopy:PROJ-5", "main"),
        branch="agent/PROJ-5-work",
        runs_dir=ws.state_dir / "runs",
        repo="api",
    )
    db.finish_run(conn, 1, "done", "{}")
    split_run(conn, "PROJ-1", {"PROJ-2": "api"}, status="failed")
    assert main(split("PROJ-5", "--repo", "api", "--repo", "web"), runner=runner) == 1
    assert main(split("PROJ-1", "--repo", "api", "--repo", "web"), runner=runner) == 1
    assert runner.spawned == []
    assert decisions(conn, tick_id) == [
        ("refused:unknown_repo", "PROJ-5 is worked in api; a ticket with work in one repository is not split"),
        ("refused:attempt_limit", "PROJ-1 has had 1 split runs and the limit is 1"),
        ("attention:attempt_limit", "PROJ-1 has had 1 split runs and the limit is 1"),
    ]


def test_a_single_repository_is_never_split(canopy_env: CanopyEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch, dry_run=True)
    assert main(split("PROJ-1", "--repo", "repo", "--repo", "other")) == 1
    assert decisions(conn, tick_id) == [
        ("refused:unknown_repo", "split needs a workspace of several repositories; this is a single repository")
    ]


@pytest.mark.parametrize(
    ("result", "problem"),
    [
        ({"status": "done", "children": {}}, "a done split names the tickets it created in children"),
        ({"status": "done", "children": {"PROJ 2": "api"}}, "'PROJ 2' is not a ticket key"),
        ({"status": "done", "children": {"P" * 101: "api"}}, f"{'P' * 100!r} is not a ticket key"),
        ({"status": "done", "children": {"PROJ-1": "api"}}, "PROJ-1 is the ticket that was split"),
        (
            {"status": "done", "children": {"PROJ-2": "docs"}},
            "PROJ-2's repository 'docs' is not one the split was dispatched with",
        ),
        ({"status": "done", "children": {"PROJ-2": "api", "PROJ-3": "api"}}, "two children are for api"),
        ({"status": "done", "children": {"OLD-1": "api"}}, "OLD-1 is already a child of OLD"),
        (
            {"status": "done", "children": {"WORKED-1": "web"}},
            "WORKED-1 already has runs, so this split did not create it",
        ),
        ({"status": "done", "children": CHILDREN}, ""),
        ({"status": "failed", "children": {"PROJ-2": "api"}}, ""),
        ({"status": "failed"}, ""),
    ],
)
def test_children_are_checked_before_they_are_recorded(
    canopy_env: CanopyEnv, result: dict[str, object], problem: str
) -> None:
    conn = journal(canopy_env)
    split_run(conn, "OLD", {"OLD-1": "api"})
    split_run(conn, "WORKED-1", {"X-1": "api"}, status="failed")  # any run counts, a split's too
    parsed = worker.SplitResult.model_validate(result)
    assert worker.check_children(conn, "PROJ-1", parsed, ["api", "web"]) == problem


def test_children_that_fail_the_check_are_not_recorded(
    ws: Ws, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = ws.journal()
    in_tick(conn, monkeypatch)
    runner = InlineRunner()
    assert main(split("PROJ-1", "--repo", "api", "--repo", "web"), runner=runner) == 0
    splitter_reports(monkeypatch, {"PROJ-2": "api", "PROJ-3": "docs"})
    assert main(["_run", "1"], runner=runner) == 0

    run = db.get_run(conn, 1)
    assert run is not None
    assert run["status"] == "unknown"
    result = json.loads(run["result_json"])
    assert result["children"] == {}
    assert result["harness"] == (
        "the split's children were not recorded: PROJ-3's repository 'docs' is not one the split was dispatched with"
    )
    assert db.open_splits(conn) == []
    [item] = attention.from_runs(conn)
    assert (item.ticket_key, item.reason) == ("PROJ-1", "unknown_result")
    assert item.detail.startswith("run 1 (split) ended unknown: the split's children were not recorded")


def test_the_state_block_carries_split_children_until_the_parent_is_done(
    ws: Ws, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = ws.journal()
    run_id = split_run(conn, "PROJ-1", CHILDREN)
    ended = db.get_run(conn, run_id)
    assert ended is not None
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    monkeypatch.setenv(
        "FAKE_AGENT_COMMANDS",
        json.dumps([["canopy", "ticket", "set", "PROJ-1", "--phase", "split"]]),
    )
    assert main(["tick"]) == 0
    db.set_ticket(conn, "PROJ-1", "acme", done=True)
    assert main(["tick"]) == 0

    first, second = (
        json.loads(json.loads(line)["argv"][3].split("```json\n", 1)[1].split("\n```", 1)[0])
        for line in agent_log.read_text().splitlines()
    )
    assert first["split_children"] == [
        {"key": k, "parent": "PROJ-1", "repo": r, "split_run_id": run_id, "split_ended_at": ended["ended_at"]}
        for k, r in CHILDREN.items()
    ]
    assert first["policy"] == {
        "max_implement_attempts": 2,
        "max_fix_ci_attempts": 2,
        "fix_ci_cooldown_minutes": 30,
        "max_resume_attempts": 3,
        "max_split_attempts": 1,
    }
    [parent] = first["tickets"]
    assert (parent["key"], parent["repo"], parent["attempts"]["split"], parent["last_run"]["kind"]) == (
        "PROJ-1",
        None,
        1,
        "split",
    )
    ticket = db.get_ticket(conn, "PROJ-1")
    assert ticket is not None
    assert ticket["phase"] == "split"
    # Once the parent is done, its children are ordinary tickets.
    assert second["split_children"] == []


def test_a_killed_split_run_is_crashed_and_returns_no_slot(
    ws: Ws, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = ws.journal()
    in_tick(conn, monkeypatch)
    assert main(split("PROJ-1", "--repo", "api", "--repo", "web"), runner=InlineRunner()) == 0
    conn.execute("UPDATE runs SET pid = 999999999")  # `_run` is gone
    monkeypatch.delenv("CANOPY_TICK_ID")
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0

    run = db.get_run(conn, 1)
    assert run is not None
    assert run["status"] == "crashed"
    calls = json.loads(treehouse_state.read_text())["calls"]
    assert [c[0] for c in calls] == ["status", "status"]  # each pool read, nothing returned
    [item] = attention.current(conn)
    assert (item.ticket_key, item.reason) == ("PROJ-1", "crashed")
    assert item.detail.startswith("run 1 (split) ended crashed: the worker process is gone; log ")


def test_a_split_cannot_report_blocked() -> None:
    # The splitter has no label tools, so it cannot raise the needs-human label a blocked run waits on.
    assert worker.parse_result('{"status": "blocked", "question": "which?"}', worker.SplitResult) is None
    assert worker.parse_result('{"status": "blocked", "question": "which?"}', worker.WorkerResult) is not None
