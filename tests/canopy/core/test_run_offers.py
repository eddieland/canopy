"""What the runtime offered each agent run, asked as the run started and recorded beside it (DESIGN §13)."""

import contextlib
import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import run_offers
from canopy.core.run_models import RunTable
from canopy.infra import logs, procs
from canopy.runtime.agents import AgentOffer, ServerOffer
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes


def offered(conn: sqlite3.Connection, table: RunTable, run_id: int) -> tuple[object, ...] | None:
    """What `run_offers.of_run` read back for a run, as plain values: its agent, error, servers, and skills."""
    found = run_offers.of_run(conn, table, run_id)
    if found is None:
        return None
    servers = tuple((s.server, s.reach) for s in found.servers)
    return found.asked.agent, found.asked.error, servers, tuple(s.skill for s in found.skills)


def tools_and_rules(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
) -> tuple[tuple[str, ...], dict[str, list[str]]]:
    """The built-in tools a run was offered, and the rules that leave it some of a server's tools, as plain values."""
    found = run_offers.of_run(conn, table, run_id)
    assert found is not None
    return tuple(t.tool for t in found.tools), {server: list(rules) for server, rules in found.server_rules.items()}


def test_a_run_keeps_only_what_it_was_offered_and_the_latest_ask(conn: sqlite3.Connection) -> None:
    rules = ("deny github_*", "offer github_issue_read")
    servers = (ServerOffer("github", "some", rules), ServerOffer("sentry", "none", ("offer sentry_x",)))
    offer = AgentOffer(
        "canopy-worker",
        servers=servers,
        skills=("pdf",),
        denied_skills=("xlsx",),
        tools=("bash", "read"),
    )
    run_offers.record(conn, "runs", 1, offer)
    assert offered(conn, "runs", 1) == ("canopy-worker", None, (("github", "some"),), ("pdf",))
    # A server not offered keeps none of its rules either.
    assert tools_and_rules(conn, "runs", 1) == (("bash", "read"), {"github": list(rules)})
    # Another table's run of the same id is another run.
    assert offered(conn, "ticks", 1) is None
    run_offers.record(conn, "runs", 1, AgentOffer("canopy-worker", error="`opencode debug skill` exited 1"))
    assert offered(conn, "runs", 1) == ("canopy-worker", "`opencode debug skill` exited 1", (), ())
    assert tools_and_rules(conn, "runs", 1) == ((), {})


def test_an_agent_that_could_not_start_still_has_its_ask_recorded(conn: sqlite3.Connection) -> None:
    with pytest.raises(procs.ProcError), probing(conn, procs.SubprocessRunner(), ["agent"]):
        raise procs.ProcError("no such directory")
    assert offered(conn, "runs", 1) == (None, "its command runs no `opencode run`", (), ())


def test_a_run_that_ends_before_the_runtime_answers_waits_only_so_long(conn: sqlite3.Connection) -> None:
    answer = threading.Event()

    def slow(args: Sequence[str], **_: object) -> procs.Result:
        answer.wait(timeout=60)
        return procs.Result(tuple(args), 1, "", "")

    runner = mock.create_autospec(procs.SubprocessRunner, instance=True, spec_set=True)
    runner.run.side_effect = slow
    try:
        with (
            mock.patch.object(run_offers, "WAIT_SECONDS", 0.01),
            probing(conn, runner, ["opencode", "run", "--agent=x"]),
        ):
            pass
    finally:
        answer.set()
    assert offered(conn, "runs", 1) == (None, "the runtime had not answered 0.01 seconds after the run ended", (), ())


def test_a_journal_that_refuses_the_record_leaves_the_run_its_own_outcome(
    conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def closes() -> None:
        conn.close()
        raise procs.ProcError("no such directory")

    with pytest.raises(procs.ProcError), probing(conn, procs.SubprocessRunner(), ["agent"]):
        closes()
    assert "could not record what the run was offered" in caplog.text


@contextlib.contextmanager
def probing(conn: sqlite3.Connection, runner: procs.Runner, argv: Sequence[str]) -> Iterator[None]:
    """`run_offers.probing` for run 1 of `runs`, in no directory of its own."""
    with run_offers.probing(conn, "runs", 1, runner, argv, cwd=Path(), env={}, log=logs.for_tick(None)):
        yield


# A pool the worker can push from.
@pytest.mark.usefixtures("git_pool")
def test_each_run_records_what_the_runtime_offered_its_agent(
    scenario: Scenario,
    opencode_state: Path,
    agent_log: Path,
) -> None:
    opencode_state.write_text(
        json.dumps(
            {
                # GitHub's outside code mode, as a server an agent needs is set, since every agent is denied it.
                "config": {"mcp": {"github": {"type": "remote", "codemode": False}, "sentry": {"enabled": False}}},
                "skills": ["pdf", "tracker-jira"],
                "agents": {
                    "canopy-overseer": [
                        ["skill", "pdf", "deny"],
                        ["github_*", "*", "deny"],
                        ["canopy_*", "*", "deny"],
                        ["canopy_dispatch", "*", "allow"],
                    ],
                },
            },
        ),
    )
    scenario.configures(runtime={"overseer_cmd": command("canopy-overseer"), "worker_cmd": command("canopy-worker")})
    ticked = scenario.tick(dispatches(), worker=pushes())
    # The overseer's server denied whole, the one turned off for every agent, and the skill denied by name: none of
    # them was offered to it. canopy's own, which its run alone is given, it was offered in part, as its rules allow
    # some of its tools. The worker's rules deny none, and its run is given no server of canopy's.
    assert offered(scenario.conn, "ticks", ticked.tick.id) == (
        "canopy-overseer",
        None,
        (("canopy", "some"),),
        ("tracker-jira",),
    )
    [run] = ticked.runs
    assert run.status == "done", Path(run.row["log_path"]).read_text()
    assert offered(scenario.conn, "runs", run.id) == (
        "canopy-worker",
        None,
        (("github", "all"),),
        ("pdf", "tracker-jira"),
    )
    tools, rules = tools_and_rules(scenario.conn, "runs", run.id)
    assert {"edit", "shell"} <= set(tools)
    assert rules == {}
    # Each asked where its agent ran, by a server started there: the overseer in the repository, the worker in its
    # worktree.
    log = [json.loads(line) for line in opencode_state.with_name("opencode.jsonl").read_text().splitlines()]
    asked = {entry["cwd"] for entry in log if entry["argv"][:1] == ["serve"]}
    ran = [json.loads(line) for line in agent_log.read_text().splitlines()]
    assert asked == {entry["cwd"] for entry in ran}
    assert len(asked) == 2


def command(agent: str) -> str:
    """A command that runs `agent` through OpenCode, which the fake hands to the fake agent."""
    return f"env OPENCODE_CONFIG_DIR={{definitions_dir}} opencode run --agent {agent} {{prompt}}"
