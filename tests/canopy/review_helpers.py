"""Helpers the review tests share: a reviewer's reports, a review run in this process, and a commit to review (§21)."""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final, Unpack

from canopy.cli.main import main
from canopy.core import db
from canopy.core.review_drafts import Comment
from tests.canopy.helpers import Behavior, Called, InlineRunner, in_tick, present, reported, scripted, tick_starts
from tests.conftest import GitPool, git

# A PR the loop opened.
PR: Final = "https://github.com/acme/api/pull/7"
FINDINGS: Final = {
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
        },
    ],
}
CLEAN: Final = {"status": "done", "verdict": "clean", "impact": "low", "summary": "Nothing found."}
#: A coworker's PR, which the loop did not open: a `review.query` match, whose review has a draft (DESIGN §34).
THEIRS: Final = "https://github.com/acme/api/pull/8"
#: The reviewer's report on the commit `feature_commit` pushes, which adds `retry.py`'s two lines: one finding on a line
#: of the diff, one on a file the diff does not touch.
REPORT: Final = {
    "status": "done",
    "verdict": "findings",
    "impact": "normal",
    "summary": "Two defects.",
    "findings": [
        {"severity": "blocking", "title": "loops forever", "location": "retry.py:1", "detail": "Nothing ends it."},
        {"severity": "minor", "title": "no tests", "location": "tests/test_retry.py:3", "detail": "Add one."},
    ],
}
#: What `REPORT`'s draft makes of its finding on a line of the diff: a comment on it.
ON_LINE: Final = Comment("retry.py", 1, "loops forever\n\nNothing ends it.", finding=1)
#: What it makes of its finding off the diff: a part of the body.
OFF_DIFF: Final = "`tests/test_retry.py:3`\n\nno tests\n\nAdd one."


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
        tick_starts(InlineRunner())
        run_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
        assert main(["_review", str(run_id)], runner=runner or InlineRunner()) == 0
    return run_id


def review(*args: str, sha: str, pr: str = PR) -> list[str]:
    """`canopy review run` of `pr` at `sha` in `repo`."""
    return ["review", "run", "--pr", pr, "--sha", sha, "--repo", "repo", *args]


@contextmanager
def reviewer_reports(
    report: object,
    *commands: list[str],
    tools: Sequence[Called] = (),
    **behavior: Unpack[Behavior],
) -> Iterator[None]:
    """Until the block ends, the fake reviewer prints `report`, verbatim if it is a string.

    It prints it after making the calls `tools` names and running `commands`, if given.
    """
    with scripted("REVIEWER", reported(report, commands, tools), behavior):
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
