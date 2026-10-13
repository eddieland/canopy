"""A journal seeded from fixtures, for the UI's development server and its end-to-end tests (`--mock`).

The server reads and writes it through the same code as the loop's journal: only the attention list, ending a run, a
reload, and the pools' slots are stand-ins, since the first three belong to the loop and there is no treehouse to ask
(backend.py).
It is a workspace (DESIGN §18), canopy's usual shape: `api` has no clone, `mobile` and `web` do, `web`'s pool holds one
slot past its declared size, and run 43 holds a slot in both. Two chores are configured (§19): `deps`, whose latest run
found the advisory the attention list shows and which has a note from the operator, and `build-health`, running. Two
ticks recorded decisions about tickets, a unit, a repository, a chore, and a PR (§6). Runs 39 and 40, tick 2, and chore
run 2 left their sessions' events in their logs, as `--format json` prints them, for their transcripts (DESIGN §22).
Times are fixed around 2026-10-08 12:00 UTC, so a test that freezes the browser's clock gets the same page every time.
`changes` moves the running run's cost now and then, which the event stream then shows.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import config, conversation, db, treehouse, workspace
from canopy.core.items import Item
from canopy.infra import logs, resources
from canopy.serve import mock_reviews
from canopy.serve.backend import Backend, Reloading

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
ticket_url = "https://jira.example/browse/{key}"
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
                "detached": True,
                "lease_id": "lease-1",
                "lease_holder": "canopy:ABC-101",
                "leased_at": at(0),
                "processes": [{"pid": 48211, "name": "opencode"}, {"pid": 48390, "name": "node"}],
            },
            {
                "status": "leased",
                "detached": True,
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
                "detached": True,
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
    workspace.ensure_state_dir(ws.state_dir)
    pools = _pools(root)

    def slots(_ctx: Context, pool: treehouse.Pool) -> list[treehouse.Slot]:
        return list(pools.get(pool.cwd.name, [])) if pool.cwd is not None else []

    backend = Backend(
        config=cfg,
        workspace=ws,
        attention=lambda _ctx: list(ATTENTION),
        end_run=_end_run,
        reload=_reload,
        mock=True,
        slots=slots,
        clock=lambda: T0,
    )
    with backend.open() as ctx:
        db.migrate(ctx.conn, resources.migrations_dir())
        with db.transaction(ctx.conn):
            _fixtures(ctx.conn, root)
            mock_reviews.seed(ctx.conn, ws.state_dir, at)
    _transcripts(ws.state_dir)
    return backend


def _end_run(ctx: Context, run: sqlite3.Row) -> bool:
    current = db.get_run(ctx.conn, int(run["id"]))
    if current is None or current["status"] != "running":
        return False
    note = json.dumps({"harness": "the operator stopped the ticket (mock: no process was killed)"})
    return conversation.close_run(ctx.conn, ctx.config, current, "stopped", note)


def _reload(_ctx: Context) -> Reloading:
    # No loop runs on the mock's config, so there is nothing to read again.
    return Reloading(changed=(), restart=(), after_tick=False)


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
            (
                1,
                at(-121),
                at(-119),
                "dispatched 2, waiting on 1:\n- ABC-099 implement\n- ABC-103 implement",
                3,
                "ses_tick1",
                0.28,
            ),
            (2, at(-60), at(-59), "mock tick", 8, "ses_tick2", 0.31),
        ],
    )
    tickets = (
        # key, title (None: not named yet), phase, branch, last seen
        ("ABC-099", "Debounce search input", "in_review", "agent/ABC-099-search", -59),
        ("ABC-100", "Fix the flaky checkout test", "ci_failing", "agent/ABC-100-flaky-test", -59),
        ("ABC-101", "Sign in with SSO", "implementing", "agent/ABC-101-login", 10),
        ("ABC-102", "Export reports as CSV", "needs_human", "agent/ABC-102-export", -4),
        ("ABC-103", "Move billing to the v2 API", "in_review", "agent/ABC-103-billing-v2", -80),
        ("ABC-104", None, "ci_failing", "agent/ABC-104-retry-queue", 5),
    )
    for key, title, phase, branch, seen in tickets:
        conn.execute(
            "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, title, phase, branch) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, repo, at(-300), at(seen), title, phase, branch),
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
                "summary": (
                    "Search now debounces input and cancels stale requests.\n"
                    "- `useSearch` waits 250ms after the last key\n"
                    "- a new query aborts the one in flight\n"
                    "- tests cover both, with **fake timers**\n"
                    "- `make check` passes\n"
                    "\n"
                    "Left the result cache as it was: ABC-112 owns it."
                ),
                "prs": {"web": "https://github.com/acme/web/pull/88"},
            },
            0,
            2.31,
        ),
        (
            37,
            "ABC-100",
            "implement",
            "agent/ABC-100-flaky-test",
            -200,
            -170,
            "done",
            {
                "summary": "The checkout test now waits for the payment frame instead of a fixed sleep.",
                "prs": {"web": "https://github.com/acme/web/pull/86"},
            },
            0,
            1.32,
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
                str(root.absolute() / workspace.WORKSPACE_STATE_DIR / "runs" / f"{run_id}.log"),
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
    _chore_fixtures(conn, root)
    _decisions(conn)


def _chore_fixtures(conn: sqlite3.Connection, root: Path) -> None:
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
                str(root.absolute() / workspace.WORKSPACE_STATE_DIR / "chores" / f"{run_id}.log"),
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


def _event(kind: str, session: str, minutes: float, **fields: object) -> str:
    """One event as `opencode run --format json` prints it, `minutes` after T0."""
    ms = int((T0 + timedelta(minutes=minutes)).timestamp() * 1000)
    return json.dumps({"type": kind, "timestamp": ms, "sessionID": session, **fields})


def _text(session: str, minutes: float, text: str) -> str:
    return _event("text", session, minutes, part={"type": "text", "text": text})


def _tool(session: str, minutes: float, tool: str, state: dict[str, object], seconds: float = 1) -> str:
    ms = int((T0 + timedelta(minutes=minutes)).timestamp() * 1000)
    metadata: dict[str, object] = {}
    timed = {**state, "metadata": metadata, "time": {"start": ms - int(seconds * 1000), "end": ms}}
    return _event(
        "tool_use", session, minutes, part={"type": "tool", "callID": f"call_{ms}", "tool": tool, "state": timed}
    )


def _step(session: str, minutes: float, cost: float, reason: str = "tool-calls") -> str:
    # Most of what a call sends is read back from the provider's cache, after the first.
    sent = int(cost * 30_000)
    tokens = {
        "input": sent // 4,
        "output": int(cost * 3_000),
        "reasoning": int(cost * 1_000),
        "cache": {"read": sent - sent // 4 - 512, "write": 512},
    }
    return _event(
        "step_finish", session, minutes, part={"type": "step-finish", "reason": reason, "cost": cost, "tokens": tokens}
    )


def _done(session: str, minutes: float, title: str, command: str, output: str, *, seconds: float = 1) -> str:
    """A bash call that completed."""
    state = {"status": "completed", "input": {"command": command, "description": title}, "output": output}
    return _tool(session, minutes, "bash", {**state, "title": title}, seconds)


_SEARCH_BOX = """\
1\timport { useState } from 'react'
2\t
3\texport function SearchBox({ onSearch }: { onSearch: (q: string) => void }) {
4\t    const [query, setQuery] = useState('')
5\t    return <input value={query} onChange={(e) => { setQuery(e.target.value); onSearch(e.target.value) }} />
6\t}
"""

_TICK_STDERR = """\
INFO  2026-10-08T11:00:00 +210ms service=default version=1.19.0 args=["run","--format","json"] opencode
WARN  2026-10-08T11:00:01 +1043ms service=mcp key=jira error=timed out after 1000ms listing prompts
"""


def _transcripts(state_dir: Path) -> None:
    """Write the events of run 39's, run 40's, tick 2's, and chore run 2's sessions where the loop would write them."""
    # The worktree run 39 worked in, as the operator's machine names it: the same on every start, for screenshots.
    web = "/home/op/acme/.treehouse/web-3f9c2a1b/3/web"
    s39, s40, s2, c2 = "ses_mock39", "ses_mock40", "ses_tick2", "ses_chore2"
    run_39 = [
        _event("step_start", s39, -90, part={"type": "step-start"}),
        _text(s39, -89.9, "I'll read the ticket, then the search box."),
        _tool(
            s39,
            -89.8,
            "jira_get_issue",
            {
                "status": "completed",
                "input": {"issue_key": "ABC-099"},
                "output": '{"key": "ABC-099", "summary": "Search fires a request per keystroke", "status": "To Do"}',
                "title": "",
            },
        ),
        _tool(
            s39,
            -89.5,
            "read",
            {
                "status": "completed",
                "input": {"filePath": f"{web}/src/search/SearchBox.tsx"},
                "output": _SEARCH_BOX,
                "title": "src/search/SearchBox.tsx",
            },
        ),
        _tool(
            s39,
            -89.4,
            "read",
            {
                "status": "error",
                "input": {"filePath": f"{web}/src/search/useSearch.ts"},
                "error": f"File not found: {web}/src/search/useSearch.ts",
            },
        ),
        _step(s39, -89.3, 0.82),
        _text(s39, -80, "There is no search hook yet. I'll add one that debounces and aborts the stale request."),
        _tool(
            s39,
            -79,
            "write",
            {
                "status": "completed",
                "input": {"filePath": f"{web}/src/search/useSearch.ts", "content": "export function useSearch() {}"},
                "output": "Wrote file successfully.",
                "title": "src/search/useSearch.ts",
            },
        ),
        _done(
            s39,
            -70,
            "Run the search tests",
            "npm test -- search",
            "PASS src/search/SearchBox.test.tsx\n  ✓ debounces input (310 ms)\n  ✓ cancels a stale request (12 ms)\n\n"
            "Tests: 2 passed, 2 total\n",
            seconds=14,
        ),
        _step(s39, -69.9, 0.97),
        _done(
            s39,
            -63,
            "Push the branch",
            "git push origin HEAD:refs/heads/agent/ABC-099-search",
            "To github.com:acme/web.git\n * [new branch]      HEAD -> agent/ABC-099-search\n",
            seconds=3,
        ),
        _tool(
            s39,
            -62,
            "github_create_pull_request",
            {
                "status": "completed",
                "input": {
                    "owner": "acme",
                    "repo": "web",
                    "title": "ABC-099: debounce search and cancel stale requests",
                    "head": "agent/ABC-099-search",
                    "base": "main",
                },
                "output": '{"number": 88, "url": "https://github.com/acme/web/pull/88"}',
                "title": "",
            },
        ),
        _text(
            s39,
            -61.1,
            '{"status": "done", "summary": "Search now debounces input and cancels stale requests.", '
            '"prs": {"web": "https://github.com/acme/web/pull/88"}}',
        ),
        _step(s39, -61, 0.52, reason="stop"),
    ]
    run_40 = [
        _text(s40, -74, "Reading the failing job's log first."),
        _done(s40, -73, "Find the failing job", "gh run list --branch agent/ABC-100-flaky-test", "", seconds=2),
        _step(s40, -72.5, 0.18),
        _event("error", s40, -70.1, error={"name": "APIError", "data": {"message": "Rate limited: retry after 60s"}}),
    ]
    chore_2 = [
        _text(c2, -239.9, "Checking each repository's lockfile against the advisories."),
        _done(
            c2,
            -238,
            "Audit web's dependencies",
            "npm audit --omit=dev",
            "lodash  <=4.17.20\nSeverity: high\nPrototype Pollution - https://github.com/advisories/GHSA-35jh-r3h4-6jhm"
            "\nfix available via `npm audit fix`\n\n1 high severity vulnerability\n",
            seconds=6,
        ),
        _done(c2, -236, "Audit mobile's dependencies", "npm audit --omit=dev", "found 0 vulnerabilities\n", seconds=5),
        _step(c2, -235.9, 0.14),
        _text(
            c2,
            -233.1,
            json.dumps({"status": "ok", "summary": "One advisory touches web's lockfile.", "findings": [_LODASH]}),
        ),
        _step(c2, -233, 0.12, reason="stop"),
    ]
    tick_2 = [
        _text(s2, -60, "Reading the journal's state first."),
        _done(s2, -59.9, "Read the loop's state", "canopy state", "## Tickets\n- ABC-101 implementing (run 41)\n"),
        _tool(
            s2,
            -59.8,
            "github_pull_request_read",
            {
                "status": "completed",
                "input": {"method": "get_status", "owner": "acme", "repo": "web", "pullNumber": 88},
                "output": '{"state": "pending", "statuses": [{"context": "ci/build", "state": "success"}]}',
                "title": "",
            },
        ),
        # canopy prints a refusal on stderr and exits 1; the runtime still reports the call completed.
        _done(
            s2,
            -59.7,
            "Dispatch ABC-104",
            "canopy dispatch ABC-104 --label canopy --kind implement --repo web",
            "Error: dispatch refused (running): run 43 is still working ABC-104; the refusal was recorded\n",
        ),
        _done(
            s2,
            -59.5,
            "Record the decision on ABC-101",
            "canopy decide ABC-101 wait 'run 41 is implementing it.'",
            "recorded decision 8\n",
        ),
        _text(s2, -59.1, '{"status": "ok", "summary": "mock tick"}'),
        _step(s2, -59, 0.31, reason="stop"),
    ]
    # The running runs' logs exist, as `canopy dispatch` opens them, and hold no events until their runs end.
    none: list[str] = []
    written = (
        ("runs", "39", run_39),
        ("runs", "40", run_40),
        ("runs", "41", none),
        ("runs", "43", none),
        ("ticks", "2", tick_2),
        ("chores", "2", chore_2),
        ("chores", "4", none),
    )
    for directory, name, lines in written:
        (state_dir / directory).mkdir(mode=0o700, exist_ok=True)
        stdout = "\n".join(lines)
        if not lines:
            text = ""
        elif directory == "runs":
            text = f"--- worker stdout ---\n{stdout}\n--- worker stderr ---\n\n--- worker exit 0 ---\n"
        elif directory == "chores":
            text = f"--- chore stdout ---\n{stdout}\n--- chore stderr ---\n\n--- chore exit 0 ---\n"
        else:
            # What OpenCode printed on stderr, which only the tick's output shows.
            text = f"{stdout}\n--- stderr ---\n{_TICK_STDERR}"
        logs.write_private(state_dir / directory / f"{name}.log", text)
