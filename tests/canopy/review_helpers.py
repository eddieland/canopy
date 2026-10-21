"""Helpers the review tests share: a reviewer's reports, a review run in this process, and a commit to review (§21)."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Unpack

from canopy.cli.main import main
from canopy.core import db
from tests.canopy.helpers import Behavior, InlineRunner, in_tick, present, reported, scripted
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
    with in_tick(conn, ends_ok=True):
        assert main(review(*args, sha=sha, pr=pr), runner=InlineRunner()) == 0
        run_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
        assert main(["_review", str(run_id)], runner=runner or InlineRunner()) == 0
    return run_id


def review(*args: str, sha: str, pr: str = PR) -> list[str]:
    """`canopy review run` of `pr` at `sha` in `repo`."""
    return ["review", "run", "--pr", pr, "--sha", sha, "--repo", "repo", *args]


@contextmanager
def reviewer_reports(report: object, *commands: list[str], **behavior: Unpack[Behavior]) -> Iterator[None]:
    """Until the block ends, the fake reviewer prints `report`, verbatim if it is a string, after running `commands` if
    given."""
    with scripted("REVIEWER", reported(report, commands), behavior):
        yield


def review_decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str | None, str | None, str, str]]:
    """Each decision the tick recorded, as (ticket, PR, action, rationale)."""
    return [(d.ticket_key, d.pr, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]


def head(git_pool: GitPool) -> str:
    """The commit `main` points to on origin."""
    return git("rev-parse", "main", cwd=git_pool.origin)


def feature_commit(git_pool: GitPool, tmp_path: Path) -> str:
    """Push a commit adding `retry.py` on a branch `feature` off origin's `main`, and return it."""
    seed = tmp_path / "seed"
    git("checkout", "--quiet", "-b", "feature", cwd=seed)
    (seed / "retry.py").write_text("while True:\n    call()\n")
    git("add", "retry.py", cwd=seed)
    git("commit", "--quiet", "-m", "retry", cwd=seed)
    git("push", "--quiet", str(git_pool.origin), "feature", cwd=seed)
    return present(git_pool.remote_head("feature"))
