"""What a running tick's overseer or chore run's agent has printed, kept as it prints it (DESIGN §6, §19, §22)."""

import io
import json
import sqlite3
from pathlib import Path

from canopy.core import db, progress
from canopy.core.vocab import TickStatus
from canopy.infra import logs
from tests.canopy.helpers import in_tick, present

TOKENS = {"input": 100, "output": 20, "reasoning": 3, "cache": {"read": 400, "write": 50}}


def event(kind: str, part: object) -> str:
    return json.dumps({"type": kind, "timestamp": 1, "sessionID": "ses_live", "part": part}) + "\n"


STEP = event("step_finish", {"type": "step-finish", "reason": "tool-calls", "cost": 0.25, "tokens": TOKENS})


def test_each_line_reaches_the_log_and_a_ticks_session_and_spend_so_far_reach_the_tick(
    conn: sqlite3.Connection,
) -> None:
    out = io.StringIO()
    with in_tick(conn) as tick_id:
        watch = progress.Progress(conn, "ticks", tick_id, out, logs.for_tick(tick_id), agent="overseer", fields={})
        watch("starting\n")
        assert present(db.get_tick(conn, tick_id)).session_id is None
        watch(event("text", {"type": "text", "text": "Reading the tickets."}))
        tick = present(db.get_tick(conn, tick_id))
        assert (tick.session_id, tick.cost_usd) == ("ses_live", None)
        watch(STEP)
        assert present(db.usage_of(present(db.get_tick(conn, tick_id)))).cost_usd == 0.25
        watch(STEP)
        assert present(db.usage_of(present(db.get_tick(conn, tick_id)))).cost_usd == 0.5
    assert out.getvalue().startswith("starting\n")
    assert out.getvalue().count("step_finish") == 2


def test_a_chore_runs_spend_so_far_reaches_its_row_and_nothing_reaches_one_that_ended(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    with in_tick(conn) as tick_id:
        run_id = db.insert_chore_run(conn, tick_id=tick_id, chore="build-health", logs_dir=tmp_path)
        watch = progress.Progress(
            conn, "chore_runs", run_id, io.StringIO(), logs.for_tick(tick_id), agent="chore", fields={}
        )
        watch(STEP)
        run = present(db.get_chore_run(conn, run_id))
        assert (run.session_id, run.cost_usd) == ("ses_live", 0.25)

        # A tick that ended is not written to by an overseer still printing: what it cost is recorded as it ended.
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        ended = progress.Progress(
            conn, "ticks", tick_id, io.StringIO(), logs.for_tick(tick_id), agent="overseer", fields={}
        )
        ended(STEP)
        assert present(db.get_tick(conn, tick_id)).cost_usd is None
