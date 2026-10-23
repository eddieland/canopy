"""`canopy grant` (DESIGN §8, §22): the operator lets a unit at its attempt limit run again; every run still counts."""

import sqlite3

import pytest

from canopy.cli.main import main
from canopy.core import config, db
from canopy.runs import policy
from tests.canopy.helpers import KEY, granted_meanwhile, in_run, in_tick, waits
from tests.canopy.scenario_helpers import Scenario, dispatches, fails
from tests.conftest import GitPool


def fail_twice(scenario: Scenario) -> None:
    """Spend both of PROJ-1's implement attempts in `repo`."""
    for _ in range(2):
        assert scenario.run(worker=fails()).status == "failed"


def grants(conn: sqlite3.Connection) -> list[tuple[str, str, str, int]]:
    rows = conn.execute("SELECT ticket_key, repo, kind, runs FROM attempt_grants ORDER BY id")
    return [(str(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in rows]


def limit_of(runs: int) -> tuple[str, str]:
    """The refusal of an implement of PROJ-1 that has had `runs` implement runs, its limit."""
    return ("refused:attempt_limit", f"PROJ-1 in repo has had {runs} implement runs and the limit is {runs}")


def test_a_grant_lets_a_unit_at_its_limit_run_again_and_every_run_still_counts(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    fail_twice(scenario)
    [first, _] = scenario.refuses(dispatches())
    assert first == limit_of(2)

    # The ticket has had runs in one repository, so the grant needs no --repo.
    granted = scenario.operator("grant", KEY, "implement")
    assert "PROJ-1 in repo has had 2 implement runs, and may now have 3." in granted.out
    assert "This is attempt 3 of 3." in scenario.run(worker=fails()).prompt

    # The granted run counted like any other: the unit is at its raised limit.
    [first, _] = scenario.refuses(dispatches())
    assert first == limit_of(3)
    # Grants add up, and are per kind: resume keeps the policy's limit.
    granted = scenario.operator("grant", KEY, "implement", "--repo", "repo", "--runs", "2")
    assert "has had 3 implement runs, and may now have 5." in granted.out
    assert policy.grants(scenario.conn) == {(KEY, "repo"): {"implement": 3}}
    cfg = config.load(scenario.env.root, scenario.env.user_file)
    assert policy.unit_limits(cfg, policy.grants(scenario.conn)[KEY, "repo"]) == {"implement": 5, "resume": 6}

    # The overseer's state block shows the unit's grants beside its attempts, so it dispatches past the policy's limit.
    scenario.tick(*waits(KEY, rationale="nothing new"))
    [unit] = scenario.ticket_state()["units"]
    assert unit["attempts"] == {"implement": 3, "resume": 0}
    assert unit["granted"] == {"implement": 3}


def test_a_unit_with_no_grant_has_no_granted_key(scenario: Scenario, git_pool: GitPool) -> None:
    fail_twice(scenario)
    scenario.tick(*waits(KEY, rationale="nothing new"))
    [unit] = scenario.ticket_state()["units"]
    assert "granted" not in unit


def test_a_grant_reports_the_limit_of_its_own_transaction_whatever_grant_commits_beside_it(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    fail_twice(scenario)
    conn = scenario.conn
    cfg = config.load(scenario.env.root, scenario.env.user_file)
    unit_grant = (
        "INSERT INTO attempt_grants (ticket_key, repo, kind, runs, granted_at) VALUES (?, 'repo', 'implement', 1, ?)"
    )
    # No other grant commits between this one and the read of its limit, so two at once never report the same (#341).
    with granted_meanwhile(conn, policy, "grants", unit_grant, KEY, db.now()) as tried:
        granted = policy.grant(conn, cfg, KEY, "implement", repo=None, runs=1)
    assert tried == ["locked"]
    assert (granted.repo, granted.runs, granted.limit) == ("repo", 2, 3)

    # A ticket's grants likewise.
    ticket_grant = "INSERT INTO ticket_grants (ticket_key, kind, runs, granted_at) VALUES (?, 'plan', 1, ?)"
    before = policy.ticket_limit(conn, cfg, KEY, "plan")
    with granted_meanwhile(conn, policy, "ticket_grants", ticket_grant, KEY, db.now()) as tried:
        planned = policy.grant_ticket(conn, cfg, KEY, "plan", runs=1)
    assert tried == ["locked"]
    assert planned.limit == before + 1 == policy.ticket_limit(conn, cfg, KEY, "plan")


@pytest.mark.parametrize("env", ["CANOPY_TICK_ID", "CANOPY_RUN_ID"])
def test_only_the_operator_grants(
    scenario: Scenario,
    git_pool: GitPool,
    capsys: pytest.CaptureFixture[str],
    env: str,
) -> None:
    fail_twice(scenario)
    capsys.readouterr()
    # Inside a tick, as the overseer; or inside a run, as its agent, with no tick named: not the operator's shell.
    with in_tick(scenario.conn, ends_ok=True) if env == "CANOPY_TICK_ID" else in_run(1):
        assert main(["grant", KEY, "implement"]) == 1
        assert "grant refused (inside_run)" in capsys.readouterr().err
        assert grants(scenario.conn) == []


def test_grant_refusals(scenario: Scenario, git_pool: GitPool) -> None:
    refused = scenario.operator("grant", KEY, "resume", code=1)
    assert f"grant refused (unknown): canopy has no record of {KEY}" in refused.err
    db.touch_ticket(scenario.conn, KEY, "repo")
    refused = scenario.operator("grant", KEY, "resume", code=1)
    assert "grant refused (unknown_repo): name the repository with repo (--repo): it has had no runs" in refused.err

    fail_twice(scenario)
    refused = scenario.operator("grant", KEY, "resume", "--repo", "other", code=1)
    assert f"grant refused (unknown_repo): {KEY} has had no runs in other" in refused.err
    # A split's limit is the ticket's, not a unit's: only config raises it.
    scenario.operator("grant", KEY, "split", code=2)
    scenario.operator("grant", KEY, "resume", "--runs", "0", code=2)
    # A resume fixes CI now, and fix-ci runs count as resume runs (DESIGN §8).
    refused = scenario.operator("grant", KEY, "fix-ci", code=1)
    assert (
        "grant refused (bad_kind): a resume now fixes CI, and fix-ci runs count as resume runs: grant resume instead"
        in refused.err
    )
    assert grants(scenario.conn) == []


def test_a_forgotten_ticket_is_granted_in_the_repository_its_runs_were_in(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    fail_twice(scenario)
    forgot = scenario.operator("forget", KEY)
    assert f"grant it another with `canopy grant {KEY} implement --repo repo`" in forgot.out
    assert db.units(scenario.conn, KEY) == []
    scenario.operator("grant", KEY, "implement")
    assert grants(scenario.conn) == [(KEY, "repo", "implement", 1)]
    # Granted, the unit is no longer at its limit, so forgetting it again, once it has something new to drop, says
    # nothing about one.
    scenario.operator("reply", KEY, "Try the v2 client.")
    assert "its limit is" not in scenario.operator("forget", KEY).out
