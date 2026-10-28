"""A public worker's `{{PREVIOUS_RUNS}}` (DESIGN §8): what the ticket's latest runs reported, as each run is fresh."""

import json
import sqlite3
from pathlib import Path
from typing import Final

from canopy.core import conversation, db
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    commit_and_push,
    in_tick,
    operator,
    present,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import CanopyEnv, GitPool

PR: Final = "https://example.test/pr/1"


def result(status: RunStatus, summary: str, **extra: str) -> str:
    return json.dumps({"status": status, "branch": BRANCH, "prs": {"repo": PR}, "summary": summary, **extra})


def ended(
    conn: sqlite3.Connection,
    tmp_path: Path,
    kind: RunKind,
    status: RunStatus,
    summary: str,
    **extra: str,
) -> int:
    """Record a run of KEY that ended as `status` with `summary`, and the messages it reports, as `_run` does."""
    with in_tick(conn) as tick_id:
        db.touch_ticket(conn, KEY, "repo")
        run_id = db.insert_run(
            conn,
            tick_id=tick_id,
            key=KEY,
            kind=kind,
            branch=BRANCH,
            slots=(),
            runs_dir=tmp_path,
            works_units=False,
        )
    stored = result(status, summary, **extra)
    assert db.finish_ticket_run(conn, run_id, status, stored, messages=conversation.run_messages(status, stored))
    return run_id


def test_a_resume_worker_reads_what_the_implement_before_it_reported(scenario: Scenario, git_pool: GitPool) -> None:
    reported = result(RunStatus.DONE, "Added the login form.\nTests pass.")
    implement = scenario.run(dispatches(slug="work"), worker=worker_does(*commit_and_push(BRANCH), result=reported))
    assert "## Earlier runs" not in implement.prompt

    resume = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI]))
    assert (
        f"## Earlier runs\n\nRun {implement.id}, `implement`, ended `done` at {implement.row['ended_at']}.\n"
        f"Its report:\n> Added the login form.\n> Tests pass.\n> {PR}\n\n"
    ) in resume.prompt


def test_the_latest_runs_are_listed_oldest_first_with_a_blocked_runs_question(
    conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    assert conversation.prompt_previous_runs(conn, KEY) is None
    ended(conn, tmp_path, RunKind.IMPLEMENT, RunStatus.DONE, "the oldest")
    ids = [
        ended(conn, tmp_path, RunKind.RESUME, RunStatus.BLOCKED, "half done", question="Red or blue?"),
        ended(conn, tmp_path, RunKind.FIX_CI, RunStatus.FAILED, "could not\x1b[2Jreproduce"),
        ended(conn, tmp_path, RunKind.RESUME, RunStatus.DONE, "the newest"),
    ]
    with in_tick(conn) as tick_id:
        # A run still going has reported nothing yet.
        db.insert_run(
            conn,
            tick_id=tick_id,
            key=KEY,
            kind=RunKind.RESUME,
            branch=BRANCH,
            slots=(),
            runs_dir=tmp_path,
            works_units=False,
        )

    text = present(conversation.prompt_previous_runs(conn, KEY))
    blocks = text.split("\n\n")
    # The latest three that ended, oldest first: neither the oldest nor the run still going.
    assert [b.split(",")[0] for b in blocks] == [f"Run {i}" for i in ids]
    assert "the oldest" not in text
    assert blocks[0].startswith(f"Run {ids[0]}, `resume`, ended `blocked` at ")
    assert blocks[0].endswith(f"Its report:\n> half done\n> {PR}\nIts question:\n> Red or blue?")
    # A report is the worker's text: no control character reaches the prompt.
    assert f"Its report:\n> could not [2Jreproduce\n> {PR}" in blocks[1]


def test_runs_from_before_a_forget_are_left_out(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    ended(conn, tmp_path, RunKind.IMPLEMENT, RunStatus.FAILED, "the old approach")
    assert operator("forget", KEY) == 0
    assert conversation.prompt_previous_runs(conn, KEY) is None
    later = ended(conn, tmp_path, RunKind.IMPLEMENT, RunStatus.DONE, "the new approach")
    text = present(conversation.prompt_previous_runs(conn, KEY))
    assert text.startswith(f"Run {later}, `implement`, ended `done`")
    assert "the old approach" not in text
