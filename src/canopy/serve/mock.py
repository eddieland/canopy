"""A journal seeded from fixtures, for the UI's development server and its end-to-end tests (`--mock`).

The server reads and writes it through the same code as the loop's journal: only the attention list and ending a run
are stand-ins, since those belong to the loop (backend.py). Times are fixed around 2026-10-08 12:00 UTC, so a test that
freezes the browser's clock gets the same page every time. `changes` moves the running run's cost now and then, which
the event stream then shows.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import config, conversation, db
from canopy.core.items import Item
from canopy.infra import resources
from canopy.serve.backend import Backend

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.context import Context

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
# The run whose cost `changes` moves.
LIVE_RUN = 41

_REPO_TOML = """\
[tracker]
provider = "jira"
query = "project = ABC"
"""

_USER_TOML = """\
[tracker]
labels = ["agent-ready-mock"]

[paths]
state_dir = {state_dir}
"""


def at(minutes: int) -> str:
    """The journal's time `minutes` after T0."""
    return db.format_time(T0 + timedelta(minutes=minutes))


ATTENTION: tuple[Item, ...] = (
    Item(
        "ABC-100",
        "worker_failed",
        "run 40 (fix-ci, agent/ABC-100-flaky-test) ended failed: the worker exited 1 without a result line; "
        "log /home/op/.canopy/runs/40.log",
        at(-70),
    ),
    Item("ABC-099", "needs_reviewer", "https://github.com/acme/web/pull/88 waits on a reviewer", at(-55)),
    Item(
        "ABC-102",
        "awaiting_reply",
        "message 5: Should the export button be red or blue? The design doc says red, the toolbar uses blue.; "
        "answer with `canopy reply ABC-102`",
        at(-4),
    ),
    Item(
        None,
        "repo_missing",
        "api is in the workspace map but has no clone; run `canopy workspace sync`",
        at(-180),
        repo="api",
    ),
    Item(
        "chore:deps",
        "lodash-advisory",
        "lodash 4.17.20 has a prototype pollution advisory https://github.com/advisories/GHSA-35jh-r3h4-6jhm",
        at(-240),
        finding=True,
    ),
)


def seed(directory: Path) -> Backend:
    """Write a repository, a user config, and a seeded journal under `directory`, and return a Backend over them."""
    repo = directory / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / config.REPO_FILE_NAME).write_text(_REPO_TOML)
    user_file = directory / "config" / "config.toml"
    user_file.parent.mkdir()
    user_file.write_text(_USER_TOML.format(state_dir=json.dumps(str(directory / "state"))))
    cfg = config.load(repo, user_file)
    backend = Backend(
        config=cfg,
        repo_root=repo,
        workspace=None,
        attention=lambda _ctx: list(ATTENTION),
        end_run=_end_run,
        mock=True,
    )
    with backend.open() as ctx:
        db.migrate(ctx.conn, resources.migrations_dir())
        with db.transaction(ctx.conn):
            _fixtures(ctx.conn, str(repo))
    return backend


def _end_run(ctx: Context, run: sqlite3.Row) -> bool:
    current = db.get_run(ctx.conn, int(run["id"]))
    if current is None or current["status"] != "running":
        return False
    note = json.dumps({"harness": "the operator stopped the ticket (mock: no process was killed)"})
    return conversation.close_run(ctx.conn, ctx.config, current, "stopped", note)


async def changes(backend: Backend, seconds: float | None) -> None:
    """Every `seconds`, add a cent to the running run's cost, so the stream has something to show. None: never."""
    if seconds is None:
        return
    while True:
        await asyncio.sleep(seconds)
        with backend.open() as ctx:
            ctx.conn.execute(
                "UPDATE runs SET cost_usd = round(cost_usd + 0.01, 2) WHERE id = ? AND status = 'running'", (LIVE_RUN,)
            )


def _fixtures(conn: sqlite3.Connection, repo: str) -> None:
    conn.execute(
        "INSERT INTO ticks (id, started_at, ended_at, status, summary) VALUES (1, ?, ?, 'ok', 'mock tick')",
        (at(-60), at(-59)),
    )
    tickets = (
        # key, phase, branch, last seen
        ("ABC-099", "in_review", "agent/ABC-099-search", -59),
        ("ABC-100", "ci_failing", "agent/ABC-100-flaky-test", -59),
        ("ABC-101", "implementing", "agent/ABC-101-login", 10),
        ("ABC-102", "needs_human", "agent/ABC-102-export", -4),
        ("ABC-103", "in_review", "agent/ABC-103-billing-v2", -80),
        ("ABC-104", "ci_failing", "agent/ABC-104-retry-queue", 5),
    )
    for key, phase, branch, seen in tickets:
        conn.execute(
            "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, phase, branch) VALUES (?, ?, ?, ?, ?, ?)",
            (key, repo, at(-300), at(seen), phase, branch),
        )
    conn.execute(
        "INSERT INTO ticket_units (ticket_key, branch, pr_url, phase) VALUES (?, ?, ?, ?)",
        ("ABC-099", "agent/ABC-099-search", "https://github.com/acme/web/pull/88", "in_review"),
    )
    conn.execute(
        "INSERT INTO ticket_units (ticket_key, branch, pr_url, phase) VALUES (?, ?, ?, ?)",
        ("ABC-103", "agent/ABC-103-billing-v2", "https://github.com/acme/web/pull/91", "in_review"),
    )
    runs = (
        # id, ticket, kind, branch, started, ended, status, result, private, cost
        (
            38,
            "ABC-103",
            "implement",
            "agent/ABC-103-billing-v2",
            -150,
            -125,
            "done",
            {
                "summary": "Moved billing to the v2 endpoint and removed the v1 client.",
                "prs": {"web": "https://github.com/acme/web/pull/91"},
            },
            1,
            1.84,
        ),
        (
            39,
            "ABC-099",
            "implement",
            "agent/ABC-099-search",
            -90,
            -61,
            "done",
            {
                "summary": "Search now debounces input and cancels stale requests.",
                "prs": {"web": "https://github.com/acme/web/pull/88"},
            },
            0,
            2.31,
        ),
        (
            40,
            "ABC-100",
            "fix-ci",
            "agent/ABC-100-flaky-test",
            -75,
            -70,
            "failed",
            {
                "harness": "the worker exited 1 without a result line",
            },
            0,
            0.18,
        ),
        (
            42,
            "ABC-102",
            "implement",
            "agent/ABC-102-export",
            -30,
            -4,
            "blocked",
            {
                "summary": "Added the export button and its CSV writer; its color waits on you.",
                "question": "Should the export button be red or blue? The design doc says red, the toolbar uses blue.",
            },
            1,
            1.07,
        ),
        (41, "ABC-101", "implement", "agent/ABC-101-login", 0, None, "running", None, 0, 0.42),
        (43, "ABC-104", "fix-ci", "agent/ABC-104-retry-queue", 5, None, "running", None, 1, 0.12),
    )
    for run_id, key, kind, branch, started, ended, status, result, private, cost in runs:
        conn.execute(
            "INSERT INTO runs (id, tick_id, ticket_key, kind, branch, started_at, ended_at, status, result_json, "
            "log_path, private, session_id, cost_usd, tokens_input, tokens_output) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                key,
                kind,
                branch,
                at(started),
                at(ended) if ended is not None else None,
                status,
                json.dumps(result) if result is not None else None,
                f"/home/op/.canopy/runs/{run_id}.log",
                private,
                f"ses_mock{run_id}",
                cost,
                int(cost * 40_000),
                int(cost * 6_000),
            ),
        )
    conn.execute(
        "INSERT INTO run_slots (run_id, slot_path, lease_id, lease_holder, base_branch) VALUES (?, ?, ?, ?, ?)",
        (LIVE_RUN, "/home/op/.treehouse/web-1", "lease-1", "canopy:ABC-101", "main"),
    )
    conn.execute(
        "INSERT INTO run_slots (run_id, slot_path, lease_id, lease_holder, base_branch) VALUES (?, ?, ?, ?, ?)",
        (43, "/home/op/.treehouse/web-2", "lease-2", "canopy:ABC-104", "main"),
    )
    for key, started in (("ABC-102", -35), ("ABC-104", -20)):
        conn.execute(
            "INSERT INTO starts (subject_kind, subject_id, status, started_at, channel) VALUES ('ticket', ?, ?, ?, ?)",
            (key, "started", at(started), "web"),
        )
    conn.execute(
        "INSERT INTO starts (subject_kind, subject_id, status, started_at, stopped_at, channel) "
        "VALUES ('ticket', ?, 'stopped', ?, ?, 'cli')",
        ("ABC-103", at(-160), at(-100)),
    )
    messages = (
        # id, ticket, at, source, kind, channel, run, body, answers
        (
            1,
            "ABC-103",
            -140,
            "worker",
            "question",
            "run",
            38,
            "Keep the v1 client for the mobile app, or remove it?",
            None,
        ),
        (2, "ABC-103", -135, "operator", "reply", "cli", None, "Remove it: the mobile app moved to v2 last week.", 1),
        (
            3,
            "ABC-103",
            -125,
            "worker",
            "report",
            "run",
            38,
            "Moved billing to the v2 endpoint and removed the v1 client.\nhttps://github.com/acme/web/pull/91",
            None,
        ),
        (
            4,
            "ABC-102",
            -4,
            "worker",
            "report",
            "run",
            42,
            "Added the export button and its CSV writer; its color waits on you.",
            None,
        ),
        (
            5,
            "ABC-102",
            -4,
            "worker",
            "question",
            "run",
            42,
            "Should the export button be red or blue? The design doc says red, the toolbar uses blue.",
            None,
        ),
        (
            7,
            "ABC-099",
            -61,
            "worker",
            "report",
            "run",
            39,
            "Search now debounces input and cancels stale requests.\nhttps://github.com/acme/web/pull/88",
            None,
        ),
    )
    for message_id, key, when, source, kind, channel, run_id, body, answers in messages:
        conn.execute(
            "INSERT INTO messages (id, subject_kind, subject_id, at, source, kind, channel, run_id, body, answers) "
            "VALUES (?, 'ticket', ?, ?, ?, ?, ?, ?, ?, ?)",
            (message_id, key, at(when), source, kind, channel, run_id, body, answers),
        )
    conn.execute(
        "INSERT INTO messages (id, subject_kind, subject_id, at, source, kind, channel, body, comment_id, author, "
        "commented_at) VALUES (6, 'ticket', 'ABC-101', ?, 'tracker', 'comment', 'tracker', ?, '10001', "
        "'557058:ann', ?)",
        (at(-50), "Please keep the old login route working until the mobile app ships. <b>Thanks!</b>", at(-52)),
    )
