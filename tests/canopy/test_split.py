"""Split tickets (DESIGN §18, ROADMAP M8): a split run reads a desk of worktrees and records the tickets it created."""

import json
import os
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.loop import attention
from canopy.runs import worker
from tests.canopy.conftest import Ws, seed_pools
from tests.canopy.helpers import InlineRunner, in_tick, journal, wait_for_run
from tests.conftest import CanopyEnv, git

LABEL = "agent-ready-tester"


def split(key: str, *args: str) -> list[str]:
    return ["dispatch", key, "--label", LABEL, "--kind", "split", *args]


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str]]:
    return [(str(d["action"]), str(d["rationale"])) for d in db.decisions_for_tick(conn, tick_id)]


@contextmanager
def splitter_reports(result: Mapping[str, object], *commands: list[str]) -> Iterator[None]:
    """Until the block ends, the fake splitter runs `commands` and then prints `result`."""
    env = {"FAKE_SPLITTER_RESULT": json.dumps(result), "FAKE_SPLITTER_COMMANDS": json.dumps(list(commands))}
    with mock.patch.dict(os.environ, env):
        yield


def pool_statuses(treehouse_state: Path) -> list[str]:
    pools: dict[str, dict[str, list[dict[str, str]]]] = json.loads(treehouse_state.read_text())["pools"]
    return [s["status"] for p in pools.values() for s in p["slots"]]


def children(conn: sqlite3.Connection) -> list[tuple[str, str, str, int]]:
    rows = conn.execute("SELECT child_key, parent_key, repo, run_id FROM split_children ORDER BY child_key")
    return [tuple(r) for r in rows]


def test_a_split_reads_a_desk_and_records_its_children(ws: Ws, treehouse_state: Path, agent_log: Path) -> None:
    """M8 acceptance, against the fakes: a requested split creates a child per repository and pushes nothing."""
    seed_pools(ws, treehouse_state)
    (ws.root / "MAP.md").write_text("# Map\n\napi serves {{KEY}}; web calls it.\n")
    conn = ws.journal()
    result = {"status": "done", "summary": "split in two", "children": {"PROJ-13": "api", "PROJ-14": "web"}}
    with (
        in_tick(conn) as tick_id,
        splitter_reports(result, ["git", "-C", "api", "status", "--porcelain=v2", "--branch"]),
    ):
        assert main(split("PROJ-12", "--request", "10234", "--repo", "api", "--repo", "web")) == 0
        run = wait_for_run(conn, 1)
        assert run["status"] == "done", Path(run["log_path"]).read_text()

        desk = ws.root / "desks" / "PROJ-12"
        [splitter] = [json.loads(line) for line in agent_log.read_text().splitlines()]
        assert splitter["argv"][:3] == ["run", "--agent", "canopy-splitter"]
        assert splitter["cwd"] == str(desk)
        # Each worktree is at its base, detached: a split creates no branch.
        [status] = splitter["commands"]
        assert "# branch.head (detached)" in status["stdout"]
        assert not desk.exists()
        assert pool_statuses(treehouse_state) == ["available", "available"]
        for name in ("api", "web"):
            assert git("for-each-ref", "refs/heads/", cwd=ws.origins[name]).count("\n") == 0  # only main

        assert children(conn) == [("PROJ-13", "PROJ-12", "api", 1), ("PROJ-14", "PROJ-12", "web", 1)]
        # The children carry the work now: the parent is never dispatched again.
        implement = ["dispatch", "PROJ-12", "--label", LABEL, "--kind", "implement", "--repo", "api"]
        assert main(implement, runner=InlineRunner()) == 1
        assert decisions(conn, tick_id)[-1] == (
            "refused:bad_split",
            "PROJ-12 was split into PROJ-13, PROJ-14; dispatch those instead",
        )
        # The parent gets no branch and no units: the children carry the work.
        parent = db.get_ticket(conn, "PROJ-12")
        assert parent is not None
        assert parent["branch"] is None
        assert db.units(conn, "PROJ-12") == []
        assert run["branch"] == ""
        (action, rationale), _ = decisions(conn, tick_id)
        assert action == "dispatch:split"
        assert rationale.startswith("run 1: split PROJ-12 into api, web in api at ")
        assert rationale.endswith(f"; desk {desk}; label {LABEL}; request 10234")

        prompt = (ws.state_dir / "runs" / "1.prompt").read_text()
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
def test_split_guards(ws: Ws, treehouse_state: Path, args: list[str], guard: str, reason: str) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        assert main(split("PROJ-12", *args), runner=runner) == 1
        assert decisions(conn, tick_id) == [(f"refused:{guard}", reason)]
        assert runner.spawned == []
        assert pool_statuses(treehouse_state) == ["available", "available"]


def test_request_is_for_split_only(ws: Ws, treehouse_state: Path) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn) as tick_id:
        args = ["dispatch", "PROJ-12", "--label", LABEL, "--kind", "implement", "--repo", "api", "--request", "1"]
        assert main(args, runner=InlineRunner()) == 1
        assert decisions(conn, tick_id) == [
            ("refused:bad_request", "--request names the comment asking for a split; it is for split only")
        ]


def test_a_started_ticket_is_not_split_and_a_split_has_an_attempt_limit(ws: Ws, treehouse_state: Path) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn) as tick_id:
        db.touch_ticket(conn, "PROJ-1", str(ws.root))
        conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-work' WHERE key = 'PROJ-1'")
        runner = InlineRunner()
        assert main(split("PROJ-1", "--request", "1", "--repo", "api", "--repo", "web"), runner=runner) == 1

        assert main(split("PROJ-12", "--request", "1", "--repo", "api", "--repo", "web"), runner=runner) == 0
        assert db.finish_run(conn, 1, "failed", "{}")
        for s in db.run_slots(conn, 1):
            assert runner.run(
                ["treehouse", "return", "--force", s["slot_path"]], env={"TREEHOUSE_ROOT": str(ws.root)}
            ).ok
        assert main(split("PROJ-12", "--request", "2", "--repo", "api", "--repo", "web"), runner=runner) == 1
        assert decisions(conn, tick_id) == [
            ("refused:bad_split", "PROJ-1 already has work on agent/PROJ-1-work; a started ticket is not split"),
            ("dispatch:split", decisions(conn, tick_id)[1][1]),
            ("refused:attempt_limit", "PROJ-12 has had 1 split runs and the limit is 1"),
            ("attention:attempt_limit", "PROJ-12 has had 1 split runs and the limit is 1"),
        ]
        # A split's runs are the ticket's, never a unit's.
        assert db.units(conn, "PROJ-12") == []


def test_a_workspace_of_one_repository_is_never_split(canopy_env: CanopyEnv, treehouse_state: Path) -> None:
    conn = journal(canopy_env)
    with in_tick(conn) as tick_id:
        assert main(split("PROJ-1", "--request", "1", "--repo", "repo"), runner=InlineRunner()) == 1
        assert decisions(conn, tick_id) == [
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
    ws: Ws, treehouse_state: Path, agent_log: Path, result: object, note: str
) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn), mock.patch.dict(os.environ, {"FAKE_SPLITTER_RESULT": json.dumps(result)}):
        # OLD-1 is a ticket the journal has dispatched before, and SEEN-1 one the overseer has decided about: a splitter
        # must claim neither.
        db.touch_ticket(conn, "OLD-1", str(ws.root))
        db.touch_ticket(conn, "SEEN-1", str(ws.root))
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path, status) "
            "VALUES (1, 'OLD-1', 'implement', 'agent/OLD-1-work', 'x', 'l', 'done')"
        )
        assert main(split("PROJ-12", "--request", "1", "--repo", "api", "--repo", "web")) == 0
        run = wait_for_run(conn, 2)
        assert run["status"] == "unknown"
        stored = json.loads(run["result_json"])
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


def test_a_failed_split_records_what_it_created(ws: Ws, treehouse_state: Path, agent_log: Path) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    result = {"status": "failed", "summary": "tracker errored", "children": {"PROJ-13": "api"}}
    with in_tick(conn), splitter_reports(result):
        assert main(split("PROJ-12", "--request", "1", "--repo", "api", "--repo", "web")) == 0
        run = wait_for_run(conn, 1)
        assert run["status"] == "failed"
        assert children(conn) == [("PROJ-13", "PROJ-12", "api", 1)]


def test_a_timed_out_split_records_the_children_it_reported(ws: Ws, treehouse_state: Path) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn):
        result = {"status": "done", "summary": "split", "children": {"PROJ-13": "api"}}
        runner = InlineRunner(timeout_agent=True, timeout_stdout=json.dumps(result) + "\n")
        assert main(split("PROJ-12", "--request", "1", "--repo", "api", "--repo", "web"), runner=runner) == 0
        assert main(["_run", "1"], runner=runner) == 0
        run = db.get_run(conn, 1)
        assert run is not None
        assert run["status"] == "timeout"
        assert json.loads(run["result_json"])["harness"] == "the splitter timed out after 45 minutes"
        # The child exists in the tracker, so the journal knows it and a retry cannot make it again.
        assert children(conn) == [("PROJ-13", "PROJ-12", "api", 1)]
        assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_child_is_not_worked_in_a_workspace_of_another_repository(
    canopy_env: CanopyEnv, treehouse_state: Path
) -> None:
    conn = journal(canopy_env)
    with in_tick(conn, dry_run=True) as tick_id:
        db.touch_ticket(conn, "PROJ-12", str(canopy_env.root))
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, log_path, status) "
            "VALUES (?, 'PROJ-12', 'split', '', 'x', 'y', 'l', 'done')",
            (tick_id,),
        )
        db.record_split_children(conn, "PROJ-12", 1, {"PROJ-13": "api"})
        assert main(["dispatch", "PROJ-13", "--repo", "repo", "--label", LABEL, "--kind", "implement"]) == 1
        assert decisions(conn, tick_id) == [
            ("refused:unknown_repo", "PROJ-13 was split from PROJ-12 to cover api only; dispatch it with --repo api")
        ]


def test_a_child_is_dispatched_only_in_its_repository(ws: Ws, treehouse_state: Path) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn, dry_run=True) as tick_id:
        db.touch_ticket(conn, "PROJ-12", str(ws.root))
        conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, log_path, status) "
            "VALUES (?, 'PROJ-12', 'split', '', 'x', 'y', 'l', 'done')",
            (tick_id,),
        )
        db.record_split_children(conn, "PROJ-12", 1, {"PROJ-13": "api", "PROJ-14": "web"})

        def implement(key: str, *repos: str) -> int:
            args = ["dispatch", key, "--label", LABEL, "--kind", "implement"]
            return main([*args, *(a for r in repos for a in ("--repo", r))])

        assert implement("PROJ-13", "web") == 1
        assert implement("PROJ-13", "api", "web") == 1
        assert implement("PROJ-13", "api") == 0
        assert main(split("PROJ-14", "--request", "1", "--repo", "api", "--repo", "web")) == 1
        reason = "PROJ-13 was split from PROJ-12 to cover api only; dispatch it with --repo api"
        assert decisions(conn, tick_id)[:3] == [
            ("refused:unknown_repo", reason),
            ("refused:unknown_repo", reason),
            ("dispatch:implement", f"dry run: not dispatched; would work on agent/PROJ-13-work in api; label {LABEL}"),
        ]
        assert decisions(conn, tick_id)[3] == (
            "refused:bad_split",
            "PROJ-14 was created by splitting PROJ-12; it is not split again",
        )


def test_a_dry_run_split_names_what_it_would_split(ws: Ws, treehouse_state: Path) -> None:
    conn = ws.journal()
    with in_tick(conn, dry_run=True) as tick_id:
        assert (
            main(split("PROJ-12", "--request", "c-9", "--repo", "web", "--repo", "api", "--cursor", "comment=c-9")) == 0
        )
        assert decisions(conn, tick_id) == [
            (
                "dispatch:split",
                (
                    f"dry run: not dispatched; would split PROJ-12 into web, api; label {LABEL}; request c-9; "
                    "cursor comment=c-9"
                ),
            )
        ]
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_the_state_block_shows_split_children(ws: Ws, treehouse_state: Path, agent_log: Path) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn), splitter_reports({"status": "done", "children": {"PROJ-13": "api", "PROJ-14": "web"}}):
        assert main(split("PROJ-12", "--request", "1", "--repo", "api", "--repo", "web")) == 0
        run = wait_for_run(conn, 1)
        with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
            os.environ.pop("CANOPY_TICK_ID")
            assert main(["tick", "--dry-run"]) == 0

    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    state = json.loads(overseer["argv"][3].split("```json\n", 1)[1].split("\n```", 1)[0])
    assert state["policy"]["max_split_attempts"] == 1
    [ticket] = state["tickets"]
    assert (ticket["key"], ticket["split_attempts"], ticket["units"]) == ("PROJ-12", 1, [])
    assert ticket["last_run"]["kind"] == "split"
    assert state["split_children"] == [
        {"child": c, "parent": "PROJ-12", "repo": r, "split_run_id": 1, "split_ended_at": run["ended_at"]}
        for c, r in (("PROJ-13", "api"), ("PROJ-14", "web"))
    ]

    # Once the parent and every child are done, the children leave the state block.
    for key in ("PROJ-12", "PROJ-13", "PROJ-14"):
        db.set_ticket(conn, key, str(ws.root), done=True)
    assert db.open_split_children(conn) == []
