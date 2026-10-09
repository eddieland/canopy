"""A journal seeded from fixtures, for the UI's development server and its end-to-end tests (`--mock`).

The server reads and writes it through the same code as the loop's journal: only the attention list, ending a run, and
the pools' slots are stand-ins, since the first two belong to the loop and there is no treehouse to ask (backend.py).
It is a workspace (DESIGN §18), canopy's usual shape: `api` has no clone, `mobile` and `web` do, `web`'s pool holds one
slot past its declared size, and run 43 holds a slot in both. Two chores are configured (§19): `deps`, whose latest run
found the advisory the attention list shows and which has a note from the operator, and `build-health`, running. Two
ticks recorded decisions about tickets, a unit, a repository, a chore, and a PR (§6). Times
are fixed around 2026-10-08 12:00 UTC, so a test that freezes the browser's clock gets the same page every time.
`changes` moves the running run's cost now and then, which the event stream then shows.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import config, conversation, db, treehouse, workspace
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

_MAP_TOML = """\
[workspace]
name = "acme"

[repos.api]
url = "https://github.com/acme/api"
summary = "The public API."

[repos.mobile]
url = "https://github.com/acme/mobile"
summary = "The mobile app."

[repos.web]
url = "https://github.com/acme/web"
summary = "The web app."

[tracker]
provider = "jira"
query = "project = ABC"
"""

_USER_TOML = """\
[tracker]
labels = ["agent-ready-mock"]

[capacity]
slots_per_repo = 2

[capacity.repo_slots]
web = 4

[chores.deps]
prompt = "{chores}/deps.md"
every_minutes = 360
days = ["mon", "tue", "wed", "thu", "fri"]
hours = "08:00-18:00"
timezone = "UTC"
when = "Skip it when nothing has merged to main since the last run."

[chores.build-health]
prompt = "{chores}/build-health.md"
every_minutes = 120

[notify.sinks.remote]
mailbox = true
"""
# The chore whose finding the attention list shows, and a run of each chore.
CHORE = "deps"
_LODASH = {
    "id": "lodash-advisory",
    "title": "lodash 4.17.20 has a prototype pollution advisory",
    "detail": "web's lockfile pins lodash 4.17.20 through an old date picker; 4.17.21 fixes it.",
    "link": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm",
}
# Each cloned repository's pool directory, as treehouse names it: the clone's name and a short hash of its remote.
_POOLS = {"mobile": "mobile-8e41d0c7", "web": "web-3f9c2a1b"}


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


def slot_path(root: Path, repo: str, slot: int) -> str:
    """Where a slot of `repo`'s pool is in the workspace at `root`, in canopy's pinned layout."""
    return str(root / ".treehouse" / _POOLS[repo] / str(slot) / repo)


def _pools(root: Path) -> dict[str, list[treehouse.Slot]]:
    """What `treehouse status --json` would show for each cloned repository's pool.

    web: the two running runs' slots, a shell someone opened in a third, one idle, and one dirty, five for a declared
    size of four. mobile: run 43's other slot, and one idle.
    """
    found: dict[str, list[dict[str, object]]] = {
        "web": [
            {
                "status": "leased",
                "branch": "agent/ABC-101-login",
                "lease_id": "lease-1",
                "lease_holder": "canopy:ABC-101",
                "leased_at": at(0),
                "processes": [{"pid": 48211, "name": "opencode"}, {"pid": 48390, "name": "node"}],
            },
            {
                "status": "leased",
                "branch": "agent/ABC-104-retry-queue",
                "lease_id": "lease-2",
                "lease_holder": "canopy:ABC-104",
                "leased_at": at(5),
                "processes": [{"pid": 48502, "name": "opencode"}],
            },
            {"status": "in-use", "detached": True, "processes": [{"pid": 2210, "name": "zsh"}]},
            {"status": "available", "detached": True},
            {"status": "dirty", "detached": True},
        ],
        "mobile": [
            {
                "status": "leased",
                "branch": "agent/ABC-104-retry-queue",
                "lease_id": "lease-3",
                "lease_holder": "canopy:ABC-104",
                "leased_at": at(5),
                "processes": [{"pid": 48530, "name": "node"}],
            },
            {"status": "available", "detached": True},
        ],
    }
    return {
        repo: [
            treehouse.Slot.model_validate({"name": str(n), "path": slot_path(root, repo, n), **slot})
            for n, slot in enumerate(slots, start=1)
        ]
        for repo, slots in found.items()
    }


def seed(directory: Path) -> Backend:
    """Write a workspace, a user config, and a seeded journal under `directory`, and return a Backend over them."""
    root = directory / "acme"
    root.mkdir(parents=True)
    (root / config.WORKSPACE_FILE_NAME).write_text(_MAP_TOML)
    for repo in _POOLS:
        (root / workspace.REPOS_DIR / repo / ".git").mkdir(parents=True)
    user_file = directory / "config" / "config.toml"
    chores = user_file.parent / "chores"
    chores.mkdir(parents=True)
    for name in (CHORE, "build-health"):
        (chores / f"{name}.md").write_text(f"Check {name} for the mock workspace.\n")
    user_file.write_text(_USER_TOML.replace("{chores}", str(chores)))
    ws = workspace.load(root)
    cfg = config.load(root, user_file)
    workspace.ensure_state_dir(ws, cfg.paths.state_dir)
    pools = _pools(root)

    def slots(_ctx: Context, pool: treehouse.Pool) -> list[treehouse.Slot]:
        return list(pools.get(pool.cwd.name, [])) if pool.cwd is not None else []

    backend = Backend(
        config=cfg,
        repo_root=root,
        workspace=ws,
        attention=lambda _ctx: list(ATTENTION),
        end_run=_end_run,
        mock=True,
        slots=slots,
        clock=lambda: T0,
    )
    with backend.open() as ctx:
        db.migrate(ctx.conn, resources.migrations_dir())
        with db.transaction(ctx.conn):
            _fixtures(ctx.conn, root)
            # A message for `canopy-notify-relay --url` to read (DESIGN §20).
            ctx.conn.execute(
                "INSERT INTO notify_mailbox (sink, at, message) VALUES ('remote', ?, ?)",
                (at(-5), json.dumps({"version": 1, "sink": "remote", "text": "canopy attention: 1 new\n+ ABC-100"})),
            )
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


def _fixtures(conn: sqlite3.Connection, root: Path) -> None:
    repo = str(root)
    conn.executemany(
        # The second read every seeded message: a reply the operator adds waits for the next tick.
        "INSERT INTO ticks (id, started_at, ended_at, status, summary, message_id, session_id, cost_usd) "
        "VALUES (?, ?, ?, 'ok', ?, ?, ?, ?)",
        [
            (1, at(-121), at(-119), "dispatched 2, waiting on 1", 3, "ses_tick1", 0.28),
            (2, at(-60), at(-59), "mock tick", 8, "ses_tick2", 0.31),
        ],
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
        "INSERT INTO ticket_units (ticket_key, repo, branch, pr_url, phase) VALUES (?, 'web', ?, ?, ?)",
        ("ABC-099", "agent/ABC-099-search", "https://github.com/acme/web/pull/88", "in_review"),
    )
    conn.execute(
        "INSERT INTO ticket_units (ticket_key, repo, branch, pr_url, phase) VALUES (?, 'web', ?, ?, ?)",
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
    run_slots = (
        # run, repo, slot, lease, holder: run 43 is joint, a slot in web and one in mobile
        (LIVE_RUN, "web", 1, "lease-1", "canopy:ABC-101"),
        (43, "web", 2, "lease-2", "canopy:ABC-104"),
        (43, "mobile", 1, "lease-3", "canopy:ABC-104"),
    )
    for run_id, name, slot, lease, holder in run_slots:
        conn.execute(
            "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder, base_branch) "
            "VALUES (?, ?, ?, ?, ?, 'main')",
            (run_id, name, slot_path(root, name, slot), lease, holder),
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
    _chore_fixtures(conn)
    _decisions(conn)


def _chore_fixtures(conn: sqlite3.Connection) -> None:
    chore_runs = (
        # id, chore, started, ended, status, result, cost
        (1, CHORE, -480, -474, "ok", {"status": "ok", "summary": "No advisory touches the lockfiles."}, 0.21),
        (
            2,
            CHORE,
            -240,
            -233,
            "ok",
            {"status": "ok", "summary": "One advisory touches web's lockfile.", "findings": [_LODASH]},
            0.26,
        ),
        (
            3,
            "build-health",
            -130,
            -124,
            "ok",
            {"status": "ok", "summary": "main is green; two flaky checks passed on a retry."},
            0.33,
        ),
        (4, "build-health", -10, None, "running", None, 0.05),
    )
    for run_id, name, started, ended, status, result, cost in chore_runs:
        conn.execute(
            "INSERT INTO chore_runs (id, tick_id, chore, started_at, ended_at, status, result_json, log_path, "
            "session_id, cost_usd, tokens_input, tokens_output) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                name,
                at(started),
                at(ended) if ended is not None else None,
                status,
                json.dumps(result) if result is not None else None,
                f"/home/op/.canopy/chores/{run_id}.log",
                f"ses_chore{run_id}",
                cost,
                int(cost * 40_000),
                int(cost * 6_000),
            ),
        )
    conn.execute(
        "INSERT INTO messages (id, subject_kind, subject_id, at, source, kind, channel, body, submission) "
        "VALUES (8, 'chore', ?, ?, 'operator', 'reply', 'cli', ?, 'mock-note-8')",
        (CHORE, at(-300), "Leave out the docs site's lockfile: it is never deployed."),
    )


def _decisions(conn: sqlite3.Connection) -> None:
    decisions = (
        # tick, at, ticket, repo, chore, pr, action, rationale
        (1, -120, "ABC-102", None, None, None, "dispatch:implement", "started privately; implement the export button"),
        (1, -120, "ABC-100", "web", None, None, "dispatch:fix-ci", "CI fails on test_retry in web; fix-ci"),
        (1, -120, "ABC-099", "web", None, "https://github.com/acme/web/pull/88", "wait", "PR 88 waits on review"),
        (1, -120, None, None, CHORE, None, "dispatch:chore", "chore run 2"),
        (1, -120, None, "api", None, None, "attention:repo_missing", "api has no clone"),
        (2, -60, "ABC-102", None, None, None, "wait", "awaiting the operator's answer to message 5"),
        (2, -60, "ABC-104", None, None, None, "refused:running", "run 43 is still working ABC-104"),
        (
            2,
            -60,
            "ABC-101",
            None,
            None,
            None,
            "wait",
            "run 41 is implementing it.\n  The ticket says <b>keep</b> the old route:\tleft for the worker.",
        ),
        (
            2,
            -60,
            "ABC-099",
            "web",
            None,
            "https://github.com/acme/web/pull/88",
            "attention:needs_reviewer",
            "no reviewer",
        ),
        (
            2,
            -60,
            None,
            None,
            None,
            "https://github.com/acme/api/pull/12",
            "wait",
            "no new commit since the last review",
        ),
    )
    for tick_id, when, key, repo, chore, pr, action, rationale in decisions:
        conn.execute(
            "INSERT INTO decisions (tick_id, created_at, ticket_key, repo, chore, pr, action, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tick_id, at(when), key, repo, chore, pr, action, rationale),
        )
