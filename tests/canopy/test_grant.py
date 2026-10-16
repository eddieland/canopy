"""`canopy grant` (DESIGN §8, §22): the operator lets a unit at its attempt limit run again; every run still counts."""

import json
import os
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, db
from canopy.runs import policy
from tests.canopy.helpers import (
    canopy,
    dispatch_and_run,
    dispatch_refused,
    in_tick,
    operator,
    overseer_does,
    prompt_of,
    state_block,
    worker_does,
)
from tests.conftest import CanopyEnv, GitPool

KEY = "PROJ-1"
LABEL = ("--label", "agent-ready-tester")
FAILED = json.dumps({"status": "failed", "summary": "could not build"})


def fail_twice(conn: sqlite3.Connection) -> None:
    """Spend both of PROJ-1's implement attempts in `repo`."""
    with worker_does(result=FAILED):
        for _ in range(2):
            assert dispatch_and_run(conn, *LABEL, "--kind", "implement")["status"] == "failed"


def grants(conn: sqlite3.Connection) -> list[tuple[str, str, str, int]]:
    rows = conn.execute("SELECT ticket_key, repo, kind, runs FROM attempt_grants ORDER BY id")
    return [(str(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in rows]


def test_a_grant_lets_a_unit_at_its_limit_run_again_and_every_run_still_counts(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fail_twice(conn)
    [first, _] = dispatch_refused(conn, *LABEL, "--kind", "implement")
    assert first == ("refused:attempt_limit", "PROJ-1 in repo has had 2 implement runs and the limit is 2")

    # The ticket has had runs in one repository, so the grant needs no --repo.
    assert operator("grant", KEY, "implement") == 0
    assert "PROJ-1 in repo has had 2 implement runs, and may now have 3." in capsys.readouterr().out
    with worker_does(result=FAILED):
        run = dispatch_and_run(conn, *LABEL, "--kind", "implement")
    assert "This is attempt 3 of 3." in prompt_of(canopy_env, int(run["id"]))

    # The granted run counted like any other: the unit is at its raised limit.
    [first, _] = dispatch_refused(conn, *LABEL, "--kind", "implement")
    assert first == ("refused:attempt_limit", "PROJ-1 in repo has had 3 implement runs and the limit is 3")
    # Grants add up, and are per kind: resume keeps the policy's limit.
    assert operator("grant", KEY, "implement", "--repo", "repo", "--runs", "2") == 0
    assert "has had 3 implement runs, and may now have 5." in capsys.readouterr().out
    assert policy.grants(conn) == {(KEY, "repo"): {"implement": 3}}
    assert policy.unit_limits(config.load(canopy_env.root, canopy_env.user_file), policy.grants(conn)[KEY, "repo"]) == {
        "implement": 5,
        "fix-ci": 2,
        "resume": 3,
    }

    # The overseer's state block shows the unit's grants beside its attempts, so it dispatches past the policy's limit.
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "nothing new")):
        assert main(["tick"]) == 0
        [ticket] = state_block(agent_log)["tickets"]
        [unit] = ticket["units"]
        assert unit["attempts"] == {"implement": 3, "fix-ci": 0, "resume": 0}
        assert unit["granted"] == {"implement": 3}


def test_a_unit_with_no_grant_has_no_granted_key(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
) -> None:
    fail_twice(conn)
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "nothing new")):
        assert main(["tick"]) == 0
        [ticket] = state_block(agent_log)["tickets"]
        [unit] = ticket["units"]
        assert "granted" not in unit


@pytest.mark.parametrize("env", ["CANOPY_TICK_ID", "CANOPY_RUN_ID"])
def test_only_the_operator_grants(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
    env: str,
) -> None:
    fail_twice(conn)
    capsys.readouterr()
    in_run: dict[str, str] = {"CANOPY_RUN_ID": "1"} if env == "CANOPY_RUN_ID" else {}
    with in_tick(conn) as tick_id, mock.patch.dict(os.environ, in_run):
        if in_run:
            os.environ.pop("CANOPY_TICK_ID")
        assert main(["grant", KEY, "implement"]) == 1
        assert "grant refused (inside_run)" in capsys.readouterr().err
        db.finish_tick(conn, tick_id, "ok", "test")
        assert grants(conn) == []


def test_grant_refusals(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert operator("grant", KEY, "resume") == 1
    assert f"grant refused (unknown): canopy has no record of {KEY}" in capsys.readouterr().err
    db.touch_ticket(conn, KEY, "repo")
    assert operator("grant", KEY, "resume") == 1
    assert (
        "grant refused (unknown_repo): name the repository with --repo: it has had no runs" in capsys.readouterr().err
    )

    fail_twice(conn)
    capsys.readouterr()
    assert operator("grant", KEY, "resume", "--repo", "other") == 1
    assert f"grant refused (unknown_repo): {KEY} has had no runs in other" in capsys.readouterr().err
    # A split's limit is the ticket's, not a unit's: only config raises it.
    assert operator("grant", KEY, "split") == 2
    assert operator("grant", KEY, "resume", "--runs", "0") == 2
    assert grants(conn) == []


def test_a_forgotten_ticket_is_granted_in_the_repository_its_runs_were_in(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fail_twice(conn)
    assert operator("forget", KEY) == 0
    assert f"grant it another with `canopy grant {KEY} implement --repo repo`" in capsys.readouterr().out
    assert db.units(conn, KEY) == []
    assert operator("grant", KEY, "implement") == 0
    assert grants(conn) == [(KEY, "repo", "implement", 1)]
    # Granted, the unit is no longer at its limit, so forgetting it again says nothing about one.
    assert operator("forget", KEY) == 0
    assert "its limit is" not in capsys.readouterr().out
