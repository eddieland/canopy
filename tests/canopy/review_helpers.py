"""Helpers the review tests share: a reviewer's reports, and a review run in this process (DESIGN §21)."""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from unittest import mock

from canopy.cli.main import main
from canopy.core import db
from tests.canopy.helpers import InlineRunner, in_tick
from tests.conftest import GitPool, git

# A PR the loop opened.
PR = "https://github.com/acme/api/pull/7"
FINDINGS = {
    "status": "done",
    "verdict": "findings",
    "impact": "normal",
    "summary": "One blocking defect.",
    "findings": [
        {
            "severity": "blocking",
            "title": "retry never stops",
            "location": "src/retry.py:42",
            "detail": "The loop resets attempts on every error.\nA failing call retries forever.",
        }
    ],
}
CLEAN = {"status": "done", "verdict": "clean", "impact": "low", "summary": "Nothing found."}


def run_inline(
    conn: sqlite3.Connection,
    *args: str,
    sha: str,
    pr: str = PR,
    runner: InlineRunner | None = None,
) -> int:
    """Start a review in its own tick and do its `_review` in this process, as the detached one would."""
    with in_tick(conn) as tick_id:
        assert main(review(*args, sha=sha, pr=pr), runner=InlineRunner()) == 0
        run_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
        assert main(["_review", str(run_id)], runner=runner or InlineRunner()) == 0
        db.finish_tick(conn, tick_id, "ok", "test")
    return run_id


def review(*args: str, sha: str, pr: str = PR) -> list[str]:
    """`canopy review run` of `pr` at `sha` in `repo`."""
    return ["review", "run", "--pr", pr, "--sha", sha, "--repo", "repo", *args]


@contextmanager
def reviewer_reports(report: object, *commands: list[str]) -> Iterator[None]:
    """Until the block ends, the fake reviewer runs `commands` and then prints `report`."""
    with mock.patch.dict(
        os.environ,
        {
            "FAKE_REVIEWER_RESULT": report if isinstance(report, str) else json.dumps(report),
            "FAKE_REVIEWER_COMMANDS": json.dumps(list(commands)),
        },
    ):
        yield


def review_decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str | None, str | None, str, str]]:
    """Each decision the tick recorded, as (ticket, PR, action, rationale)."""
    return [(d.ticket_key, d.pr, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]


def head(git_pool: GitPool) -> str:
    """The commit `main` points to on origin."""
    return git("rev-parse", "main", cwd=git_pool.origin)
