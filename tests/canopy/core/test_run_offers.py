"""What the runtime offered each agent run, asked as the run started and recorded beside it (DESIGN §13)."""

import json
import sqlite3
from pathlib import Path

import pytest

from canopy.core import run_offers
from canopy.core.run_models import RunTable
from canopy.infra import procs
from canopy.runtime.agents import AgentOffer, ServerOffer
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes


def offered(conn: sqlite3.Connection, table: RunTable, run_id: int) -> tuple[object, ...] | None:
    """What `run_offers.of_run` read back for a run, as plain values."""
    found = run_offers.of_run(conn, table, run_id)
    if found is None:
        return None
    servers = tuple((s.server, s.reach) for s in found.servers)
    return found.asked.agent, found.asked.error, servers, tuple(s.skill for s in found.skills)


def test_a_run_keeps_only_what_it_was_offered_and_the_latest_ask(conn: sqlite3.Connection) -> None:
    servers = (ServerOffer("github", "some", ("offer github_issue_read",)), ServerOffer("sentry", "none"))
    offer = AgentOffer("canopy-worker", servers=servers, skills=("pdf",), denied_skills=("xlsx",))
    run_offers.record(conn, "runs", 1, offer)
    assert offered(conn, "runs", 1) == ("canopy-worker", None, (("github", "some"),), ("pdf",))
    # Another table's run of the same id is another run.
    assert offered(conn, "ticks", 1) is None
    run_offers.record(conn, "runs", 1, AgentOffer("canopy-worker", error="`opencode debug skill` exited 1"))
    assert offered(conn, "runs", 1) == ("canopy-worker", "`opencode debug skill` exited 1", (), ())


def test_an_agent_that_could_not_start_still_has_its_ask_recorded(conn: sqlite3.Connection) -> None:
    runner = procs.SubprocessRunner()
    with pytest.raises(procs.ProcError), run_offers.probing(conn, "runs", 1, runner, ["agent"], cwd=Path(), env={}):
        raise procs.ProcError("no such directory")
    assert offered(conn, "runs", 1) == (None, "its command runs no `opencode run`", (), ())


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
                "config": {"mcp": {"github": {"type": "remote"}, "sentry": {"enabled": False}}},
                "skills": ["pdf", "tracker-jira"],
                "agents": {"canopy-overseer": [["skill", "pdf", "deny"], ["github_*", "*", "deny"]]},
            },
        ),
    )
    scenario.configures(runtime={"overseer_cmd": command("canopy-overseer"), "worker_cmd": command("canopy-worker")})
    ticked = scenario.tick(dispatches(), worker=pushes())
    # The overseer's server denied whole, the one turned off for every agent, and the skill denied by name: none of
    # them was offered to it. The worker's rules deny none.
    assert offered(scenario.conn, "ticks", ticked.tick.id) == ("canopy-overseer", None, (), ("tracker-jira",))
    [run] = ticked.runs
    assert run.status == "done", Path(run.row["log_path"]).read_text()
    assert offered(scenario.conn, "runs", run.id) == (
        "canopy-worker",
        None,
        (("github", "all"),),
        ("pdf", "tracker-jira"),
    )
    # Each asked where its agent ran: the overseer in the repository, the worker in its worktree.
    log = [json.loads(line) for line in opencode_state.with_name("opencode.jsonl").read_text().splitlines()]
    asked = {(entry["argv"][-1], entry["cwd"]) for entry in log if entry["argv"][:2] == ["debug", "agent"]}
    ran = [json.loads(line) for line in agent_log.read_text().splitlines()]
    assert asked == {(entry["argv"][entry["argv"].index("--agent") + 1], entry["cwd"]) for entry in ran}
    assert len(asked) == 2


def command(agent: str) -> str:
    """A command that runs `agent` through OpenCode, which the fake hands to the fake agent."""
    return f"env OPENCODE_CONFIG_DIR={{definitions_dir}} opencode run --agent {agent} {{prompt}}"
