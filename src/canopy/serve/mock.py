"""A journal seeded from fixtures, for the UI's development server and its end-to-end tests (`--mock`).

The server reads and writes it through the same code as the loop's journal: only the attention list, ending a run, a
reload, a tick asked for, the attempt and review limits and their grants, a chore's try, and the pools' slots are
stand-ins, since the first six belong to the loop, `runs`, `reviews`, and `chores`, and there is no treehouse to ask
(backend.py). A try records its run and starts nothing, so the run stays running.
It is a workspace (DESIGN §18), canopy's usual shape: `api` has no clone, `mobile` and `web` do, `web`'s pool holds one
slot past its declared size, and run 43 holds a slot in both. Two chores are configured (§19): `deps`, whose latest run
found the advisory the attention list shows and which has a note from the operator, and `build-health`, running. Two
ticks recorded decisions about tickets, a unit, a repository, a chore, and a PR (§6). The workspace's policy allows one
resume and two reviews, so ABC-100 is at its resume limit in web, where its run 40, a `fix-ci` from before a resume
fixed CI, counts as one (§8), and PR 88 at its review limit (§22's grants). Run 43, running, is a resume for a failed
check and review feedback together. Runs 39
and 40, tick 2, and chore run 2 left their sessions' events in their logs, as `--format json` prints them, for their
transcripts (DESIGN §22), and the running runs 41 and 43 the events their workers printed so far, with the latest tool
call on each one's row (§8).
ABC-105 is planned (§25): its plan waits on the operator, with three comments on it, one resolved, and an earlier plan
it superseded, each written to its file under the state directory.
Times are fixed around 2026-10-08 12:00 UTC, so a test that freezes the browser's clock gets the same page every time.
`changes` moves the running run's cost now and then, which the event stream then shows.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import chore_view, config, conversation, db, plans, pools, sql, workspace
from canopy.core.context import db_path
from canopy.core.items import Item
from canopy.core.vocab import RunKind, RunStatus
from canopy.infra import logs, resources
from canopy.serve import mock_drafts, mock_reviews
from canopy.serve.backend import Backend, Granted, Limit, Reloading

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core import records
    from canopy.core.context import Context

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
# The run whose cost `changes` moves.
LIVE_RUN = 41
# The running runs, whose logs hold their workers' stdout so far.
RUNNING_LOGS = ("41", "43")

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

[policy]
max_resume_attempts = 1
max_reviews_per_pr = 2
"""

_USER_TOML = """\
[tracker]
labels = ["agent-ready-mock"]

[capacity]
slots_per_repo = 2

[capacity.repo_slots]
web = 4

[memory]
ticket_notes = "use"
proposals = "record"

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
    """The journal's time `minutes` after T0.

    Returns:
        The time as the journal formats it.
    """
    return db.format_time(T0 + timedelta(minutes=minutes))


ATTENTION: tuple[Item, ...] = (
    Item(
        "ABC-100",
        "worker_failed",
        "run:40 (fix-ci, agent/ABC-100-flaky-test) ended failed: the worker exited 1 without a result line; "
        "log /home/op/.canopy/runs/40.log",
        at(-70),
    ),
    Item("ABC-099", "needs_reviewer", "https://github.com/acme/web/pull/88 waits on a reviewer", at(-55)),
    Item(
        "ABC-099",
        "drafts_waiting",
        "3 drafts wait on you, for https://github.com/acme/web/pull/88",
        at(-22),
        repo="web",
    ),
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
    """Where a slot of `repo`'s pool is in the workspace at `root`, in canopy's pinned layout.

    Returns:
        The slot's worktree path, `<root>/.treehouse/<pool>/<slot>/<repo>`.
    """
    return str(root / ".treehouse" / _POOLS[repo] / str(slot) / repo)


def _pools(root: Path) -> dict[str, list[pools.Slot]]:
    """What `treehouse status --json` would show for each cloned repository's pool.

    web: the two running runs' slots, a shell someone opened in a third, one idle, and one dirty, five for a declared
    size of four. mobile: run 43's other slot, and one idle.

    Returns:
        Each cloned repository's slots, by repository name, numbered from 1.
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
            pools.Slot.model_validate({"name": str(n), "path": slot_path(root, repo, n), **slot})
            for n, slot in enumerate(slots, start=1)
        ]
        for repo, slots in found.items()
    }


def seed(directory: Path) -> Backend:
    """Write a workspace, a user config, and a seeded journal under `directory`, and return a Backend over them.

    Returns:
        A mock Backend whose clock is T0, with the fixtures' attention list and pools, and stand-ins for ending a run,
        reloading, and asking for a tick.
    """
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
    slots_by_repo = _pools(root)

    def slots(_ctx: Context, repo: str) -> list[pools.Slot]:
        return list(slots_by_repo.get(repo, []))

    backend = Backend(
        config=cfg,
        workspace=ws,
        attention=_attention,
        end_run=_end_run,
        reload=_reload,
        tick_now=_tick_now,
        limits=_limits,
        review_limit=_review_limit,
        grant=_grant,
        try_chore=_try_chore,
        mock=True,
        slots=slots,
        clock=lambda: T0,
        runner=lambda: mock_drafts.GitHub(db_path(ws)),
    )
    with backend.open() as ctx:
        db.migrate(ctx.conn, resources.migrations_dir())
        with db.transaction(ctx.conn):
            _fixtures(ctx.conn, root)
            _plans(ctx.conn, ws.state_dir, root)
            _memory(ctx.conn)
            mock_reviews.seed(ctx.conn, ws.state_dir, at)
            mock_drafts.seed(ctx.conn, ws.state_dir, at, slot_path(root, "web", 3))
    _transcripts(ws.state_dir)
    return backend


def _attention(ctx: Context) -> list[Item]:
    """The fixtures' list, less a finding the operator dismissed, as `loop.attention.listed` leaves one out.

    Returns:
        `ATTENTION` without the findings dismissed in the mock journal.
    """
    dismissed = {
        (f"chore:{f.chore}", f.finding.id)
        for f in chore_view.open_findings(ctx.conn, ctx.config, ctx.workspace, starts=ctx.finding_starts)
        if f.dismissed
    }
    return [i for i in ATTENTION if (i.ticket_key, i.reason) not in dismissed]


def _end_run(ctx: Context, run: records.Run) -> bool:
    current = db.get_run(ctx.conn, run.id)
    if current is None or current["status"] != "running":
        return False
    note = json.dumps({"harness": "the operator stopped the ticket (mock: no process was killed)"})
    return conversation.close_run(ctx.conn, ctx.config, current, RunStatus.STOPPED, note)


def _reload(_ctx: Context) -> Reloading:
    # No loop runs on the mock's config, so there is nothing to read again.
    return Reloading(changed=(), restart=(), after_tick=False)


def _tick_now() -> bool:
    # No loop runs on the mock's journal, so no tick follows.
    return False


def _limits(ctx: Context, key: str) -> list[Limit]:
    """Each kind's limit of each unit of `key`'s, counted as `runs.policy` counts them: every run in each repository.

    Returns:
        Every kind of every unit, by repository.
    """
    p = ctx.config.policy
    base = {"implement": p.max_implement_attempts, "resume": p.max_resume_attempts}
    counts: dict[str, dict[str, int]] = {}
    counted = (
        sql.select("s.repo, r.kind, count(DISTINCT r.id)")
        .from_("runs r")
        .join("run_slots s ON s.run_id = r.id")
        .where("r.ticket_key = ?", key)
        .where("r.kind NOT IN ('split', 'plan')")
        .where("s.repo IS NOT NULL")
        .group_by("s.repo, r.kind")
    )
    for repo, kind, runs in sql.execute(ctx.conn, counted):
        of = counts.setdefault(str(repo), dict.fromkeys(base, 0))
        of[_counted_as(str(kind))] += int(runs)
    granted: dict[tuple[str, str], int] = {}
    grants = (
        sql.select("repo, kind, sum(runs)").from_("attempt_grants").where("ticket_key = ?", key).group_by("repo, kind")
    )
    for r in sql.execute(ctx.conn, grants):
        unit = (str(r[0]), _counted_as(str(r[1])))
        granted[unit] = granted.get(unit, 0) + int(r[2])
    return [
        Limit(kind, repo, None, runs, granted.get((repo, kind), 0), base[kind] + granted.get((repo, kind), 0))
        for repo, of in sorted(counts.items())
        for kind, runs in of.items()
    ]


def _counted_as(kind: str) -> str:
    # An old fix-ci run, and its grants, count as resume's, as `runs.policy.counted_as` counts them (DESIGN §8).
    return str(RunKind.RESUME) if kind == RunKind.FIX_CI else kind


def _review_limit(ctx: Context, url: str) -> Limit | None:
    runs = len(db.review_runs_of(ctx.conn, url))
    if runs == 0:
        return None
    row = sql.execute(
        ctx.conn,
        sql.select("coalesce(sum(runs), 0)").from_("review_grants").where("pr_url = ?", url),
    ).fetchone()
    granted = int(row[0])
    return Limit("review", None, url, runs, granted, ctx.config.policy.max_reviews_per_pr + granted)


def _grant(ctx: Context, ref: conversation.Ref, kind: str, repo: str | None) -> Granted:
    """One more run, as `canopy grant` records it, with its `unknown` and `unknown_repo` guards and none of the rest.

    Returns:
        The unit's repository (none for a PR), its runs, and its limit with the grant counted.

    Raises:
        Refused: `unknown` for a PR never reviewed, `unknown_repo` for a unit the ticket has had no runs in.
    """
    # Read and insert in one `BEGIN IMMEDIATE` transaction, which holds the write lock from the read to the insert, so
    # the limit reported counts this grant and no other request's.
    with db.transaction(ctx.conn):
        if kind == "review":
            reviewed = _review_limit(ctx, ref.id)
            if reviewed is None:
                raise conversation.Refused(
                    "unknown",
                    f"canopy has not reviewed {ref}, so it has no review limit to grant",
                )
            sql.execute(ctx.conn, sql.insert("review_grants", pr_url=ref.id, runs=1, granted_at=db.format_time(T0)))
            return Granted(repo=None, runs=reviewed.runs, limit=reviewed.limit + 1)
        units = {(found.repo, found.kind): found for found in _limits(ctx, ref.id)}
        repos = {r for r, _ in units}
        if repo is None and len(repos) == 1:
            [repo] = repos
        current = units.get((repo, kind))
        if repo is None or current is None:
            raise conversation.Refused("unknown_repo", f"{ref} has had no runs in {repo or 'one repository only'}")
        sql.execute(
            ctx.conn,
            sql.insert(
                "attempt_grants",
                ticket_key=ref.id,
                repo=repo,
                kind=kind,
                runs=1,
                granted_at=db.format_time(T0),
            ),
        )
        return Granted(repo=repo, runs=current.runs, limit=current.limit + 1)


def _try_chore(ctx: Context, name: str) -> int:
    """A try's run, recorded at T0 as `canopy chore try` records one, with its `running` guard; no process runs it.

    Returns:
        The new chore run's id. It stays running, as no `_chore` will close it.

    Raises:
        Refused: (`running`) a run of the chore is running.
    """
    running = next((r for r in db.running_runs(ctx.conn, "chore_runs") if r["chore"] == name), None)
    if running is not None:
        raise conversation.Refused("running", f"chore run {running['id']} of {name} is running")
    run_id = db.insert_chore_run(ctx.conn, tick_id=None, chore=name, logs_dir=ctx.state_dir / "chore-runs" / name)
    sql.execute(ctx.conn, sql.update("chore_runs").set(started_at=db.format_time(T0)).where("id = ?", run_id))
    return run_id


async def changes(backend: Backend, seconds: float | None) -> None:
    """Every `seconds`, add a cent to the running run's cost, so the stream has something to show. None: never."""
    if seconds is None:
        return
    while True:
        await asyncio.sleep(seconds)
        # On a thread, as the routes keep journal work: a write that waits on another's lock would stall every request.
        await asyncio.to_thread(_add_a_cent, backend)


def _add_a_cent(backend: Backend) -> None:
    with backend.open() as ctx:
        sql.execute(
            ctx.conn,
            sql.update("runs")
            .set_to("cost_usd = round(cost_usd + 0.01, 2)")
            .where("id = ?", LIVE_RUN)
            .where("status = 'running'"),
        )


def _fixtures(conn: sqlite3.Connection, root: Path) -> None:
    repo = str(root)
    # The second read every seeded message: a reply the operator adds waits for the next tick. The loop ran both: the
    # first as it started, the second, idle, when its wait ran out (DESIGN §6, Idle pacing). A fixed release, not this
    # build's version, so a screenshot of a tick does not change with every commit.
    ticks = (
        # id, started, ended, summary, message, session, cost, idle, woken by
        (
            1,
            at(-121),
            at(-119),
            "dispatched 2, waiting on 1:\n- ABC-099 implement\n- ABC-103 implement",
            3,
            "ses_tick1",
            0.28,
            0,
            "start",
        ),
        (2, at(-60), at(-59), "mock tick", 8, "ses_tick2", 0.31, 1, "timer"),
    )
    for tick_id, started, ended, summary, message_id, session, cost, idle, woken_by in ticks:
        sql.execute(
            conn,
            sql.insert(
                "ticks",
                id=tick_id,
                started_at=started,
                ended_at=ended,
                status="ok",
                summary=summary,
                message_id=message_id,
                session_id=session,
                cost_usd=cost,
                idle=idle,
                woken_by=woken_by,
                canopy_version="0.3.1",
            ),
        )
    # Their overseers' tokens, in the proportions the runs' are below.
    sql.execute(
        conn,
        sql.update("ticks")
        .set_to("tokens_input = CAST(cost_usd * 40000 AS INTEGER)")
        .set_to("tokens_output = CAST(cost_usd * 6000 AS INTEGER)")
        .set_to("tokens_cache_read = CAST(cost_usd * 400000 AS INTEGER)")
        .set_to("tokens_peak_context = CAST(cost_usd * 60000 AS INTEGER)")
        .everything(),
    )
    tickets = (
        # key, title (None: not named yet), phase, branch, last seen
        ("ABC-099", "Debounce search input", "review_pending", "agent/ABC-099-search", -59),
        ("ABC-100", "Fix the flaky checkout test", "ci_red", "agent/ABC-100-flaky-test", -59),
        ("ABC-101", "Sign in with SSO", "running", "agent/ABC-101-login", 10),
        ("ABC-102", "Export reports as CSV", "needs_human", "agent/ABC-102-export", -4),
        ("ABC-103", "Move billing to the v2 API", "review_pending", "agent/ABC-103-billing-v2", -80),
        ("ABC-104", None, "ci_red", "agent/ABC-104-retry-queue", 5),
    )
    for key, title, phase, branch, seen in tickets:
        sql.execute(
            conn,
            sql.insert(
                "tickets",
                key=key,
                repo=repo,
                first_seen_at=at(-300),
                last_seen_at=at(seen),
                changed_at=at(seen),
                title=title,
                phase=phase,
                branch=branch,
            ),
        )
    for key, branch, pr_url in (
        ("ABC-099", "agent/ABC-099-search", "https://github.com/acme/web/pull/88"),
        ("ABC-103", "agent/ABC-103-billing-v2", "https://github.com/acme/web/pull/91"),
    ):
        sql.execute(
            conn,
            sql.insert(
                "ticket_units",
                ticket_key=key,
                repo="web",
                branch=branch,
                pr_url=pr_url,
                phase="review_pending",
            ),
        )
    # Each PR's own title, as its worker or its review reported it: not its ticket's, and #12 has no ticket at all.
    sql.execute_many(
        conn,
        sql.insert_rows("pr_titles", ("pr_url", "title", "updated_at")),
        [
            ("https://github.com/acme/web/pull/88", "ABC-099: debounce the search box by 250 ms", at(-59)),
            ("https://github.com/acme/web/pull/91", "ABC-103: move billing to v2 and drop the v1 client", at(-125)),
            ("https://github.com/acme/api/pull/12", "Bump the retry budget for flaky upstreams", at(-79)),
        ],
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
        (43, "ABC-104", "resume", "agent/ABC-104-retry-queue", 5, None, "running", None, 1, 0.12),
    )
    for run_id, key, kind, branch, started, ended, status, result, private, cost in runs:
        sql.execute(
            conn,
            sql.insert(
                "runs",
                id=run_id,
                tick_id=1,
                ticket_key=key,
                kind=kind,
                branch=branch,
                started_at=at(started),
                ended_at=at(ended) if ended is not None else None,
                status=status,
                result_json=json.dumps(result) if result is not None else None,
                log_path=str(root.absolute() / workspace.WORKSPACE_STATE_DIR / "runs" / f"{run_id}.log"),
                private=private,
                session_id=f"ses_mock{run_id}",
                cost_usd=cost,
                tokens_input=int(cost * 40_000),
                tokens_output=int(cost * 6_000),
                tokens_cache_read=int(cost * 400_000),
                tokens_peak_context=int(cost * 60_000),
            ),
        )
    # What each running run's worker did last, as `_run` records it from the events its log holds (_transcripts).
    activities = (
        (LIVE_RUN, "bash", "npm test -- login", 27),
        (43, "bash", "cat /home/op/acme/.treehouse/web-3f9c2a1b/2/web/.github/workflows/ci.yml", 29),
    )
    for run_id, tool, did, minutes in activities:
        sql.execute(
            conn,
            sql.update("runs").set(activity_tool=tool, activity=did, activity_at=at(minutes)).where("id = ?", run_id),
        )
    # Run 39's peak is the most one model call in its transcript was sent (_transcripts), as its page's chart shows.
    sql.execute(conn, sql.update("runs").set(tokens_peak_context=30200).where("id = 39"))
    run_slots = (
        # run, repo, slot, lease, holder: run 43 is joint, a slot in web and one in mobile; 37 and 40 ended long ago
        (37, "web", 4, "lease-37", "canopy:ABC-100"),
        (40, "web", 4, "lease-40", "canopy:ABC-100"),
        (LIVE_RUN, "web", 1, "lease-1", "canopy:ABC-101"),
        (43, "web", 2, "lease-2", "canopy:ABC-104"),
        (43, "mobile", 1, "lease-3", "canopy:ABC-104"),
    )
    for run_id, name, slot, lease, holder in run_slots:
        sql.execute(
            conn,
            sql.insert(
                "run_slots",
                run_id=run_id,
                repo=name,
                slot_path=slot_path(root, name, slot),
                lease_id=lease,
                lease_holder=holder,
                base_branch="main",
            ),
        )
    # Run 43 fixes a failed check and answers review feedback in one run (DESIGN §8).
    sql.execute_many(conn, sql.insert_rows("run_reasons", ("run_id", "reason")), [(43, "ci"), (43, "review")])
    for key, started in (("ABC-102", -35), ("ABC-104", -20)):
        sql.execute(
            conn,
            sql.insert(
                "starts",
                subject_kind="ticket",
                subject_id=key,
                status="started",
                started_at=at(started),
                channel="web",
            ),
        )
    sql.execute(
        conn,
        sql.insert(
            "starts",
            subject_kind="ticket",
            subject_id="ABC-103",
            status="stopped",
            started_at=at(-160),
            stopped_at=at(-100),
            channel="cli",
        ),
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
        sql.execute(
            conn,
            sql.insert(
                "messages",
                id=message_id,
                subject_kind="ticket",
                subject_id=key,
                at=at(when),
                source=source,
                kind=kind,
                channel=channel,
                run_id=run_id,
                body=body,
                answers=answers,
            ),
        )
    sql.execute(
        conn,
        sql.insert(
            "messages",
            id=6,
            subject_kind="ticket",
            subject_id="ABC-101",
            at=at(-50),
            source="tracker",
            kind="comment",
            channel="tracker",
            body="Please keep the old login route working until the mobile app ships. <b>Thanks!</b>",
            comment_id="10001",
            author="557058:ann",
            commented_at=at(-52),
        ),
    )
    _chore_fixtures(conn, root)
    _decisions(conn)
    _tools(conn)
    _models(conn)


# ABC-105's plans (DESIGN §25): the first, superseded after the operator asked for changes, and the second, waiting on
# them, with their comments on it, two open and one resolved. Each comment's passage is in the second plan.
_FIRST_PLAN = """# Schedule report exports

## What changes

In **web**, a report gains a *Schedule* menu: daily or weekly, at an hour. A new job, `ExportJob`, runs each schedule
and emails the CSV.

## Tests

- [ ] a daily schedule runs once a day
"""
_PLAN = """# Schedule report exports

## What changes

In **web**, a report gains a *Schedule* menu: daily or weekly, at an hour the operator picks. A new job,
`ExportJob`, runs each schedule through the existing CSV export and emails a link to the file, never the file itself.

In **api**, `ReportQuery` gains `owner_timezone()`, so an hour means the owner's hour.

## Files

| Repository | File | Why |
| --- | --- | --- |
| web | `app/reports/schedule.py` | the menu and its form |
| web | `app/jobs/export_job.py` | the job |
| api | `api/reports/query.py` | `owner_timezone()` |

## Tests

- [ ] a daily schedule runs once a day, at the owner's hour
- [ ] a weekly schedule skips the other six days
- [ ] the email links to the file and does not attach it

## Out of scope

- Exports to anything but CSV.

## Risks

> The job runner retries a failed job three times. A report that always fails would email nothing, and say nothing.
"""
_PLAN_THREADS = (
    # quote, prefix, suffix, body, minutes, resolved, replies
    (
        "emails a link to the file, never the file itself",
        "the existing CSV export and",
        ".",
        "How long does the link work? Say so in the plan.",
        -10,
        False,
        ("Seven days, as the share links do.",),
    ),
    (
        "A report that always fails would email nothing, and say nothing.",
        "retries a failed job three times.",
        "",
        "Raise it on the attention list after the third failure.",
        -9,
        False,
        (),
    ),
    (
        "at an hour the operator picks",
        "a report gains a Schedule menu: daily or weekly,",
        ". A new job,",
        "Good: the ticket asks for the owner's hour.",
        -11,
        True,
        (),
    ),
)


def _plans(conn: sqlite3.Connection, state_dir: Path, root: Path) -> None:
    sql.execute(
        conn,
        sql.insert(
            "tickets",
            key="ABC-105",
            repo=str(root),
            first_seen_at=at(-90),
            last_seen_at=at(-8),
            changed_at=at(-8),
            title="Schedule report exports",
            phase="plan_proposed",
        ),
    )
    for run_id, started, ended, summary in (
        (35, -60, -52, "A schedule menu and a job that emails the CSV."),
        (44, -30, -14, "A schedule menu, a job that emails a link to the CSV, and the owner's timezone."),
    ):
        sql.execute(
            conn,
            sql.insert(
                "runs",
                id=run_id,
                tick_id=1,
                ticket_key="ABC-105",
                kind="plan",
                branch="",
                started_at=at(started),
                ended_at=at(ended),
                status="done",
                result_json=json.dumps({"status": "done", "summary": summary}),
                log_path=str(state_dir / "runs" / f"{run_id}.log"),
                private=0,
                cost_usd=0.64,
            ),
        )
    for plan_id, run_id, text, status, created in (
        (1, 35, _FIRST_PLAN, "superseded", -52),
        (2, 44, _PLAN, "proposed", -14),
    ):
        written = plans.write(state_dir, "ABC-105", run_id, text)
        sql.execute(
            conn,
            sql.insert(
                "plans",
                id=plan_id,
                ticket_key="ABC-105",
                run_id=run_id,
                created_at=at(created),
                status=status,
                sha256=written.sha256,
                size=written.size,
            ),
        )
    for quote, prefix, suffix, body, minutes, resolved, replies in _PLAN_THREADS:
        thread = sql.insert(
            "plan_threads",
            ticket_key="ABC-105",
            quote=quote,
            prefix=prefix,
            suffix=suffix,
            body=body,
            created_at=at(minutes),
            resolved_at=at(minutes + 1) if resolved else None,
        ).returning("id")
        thread_id = sql.execute(conn, thread).fetchone()[0]
        for reply in replies:
            sql.execute(conn, sql.insert("plan_replies", thread_id=thread_id, body=reply, created_at=at(minutes + 2)))


def _memory(conn: sqlite3.Connection) -> None:
    """Agent memory (DESIGN §28), with ticket notes in use and lessons recording, as the mock's config sets them.

    ABC-100's runs wrote notes, one superseded, and one written to the journal by hand past the bounds, with a link and
    a zero-width space, which every surface shows as plain text with the space named. Run 37 was rendered while notes
    were recording, so it read nothing; run 40 read run 37's note and had a secret refused. Two proposals wait, one from
    a private ticket's run, and one promoted earlier is a lesson, recorded and served to no run.
    """
    sql.execute_many(
        conn,
        sql.insert_rows("run_memory", ("run_id", "ticket_notes", "proposals", "refused")),
        [
            (37, "record", "record", "[]"),
            (39, "use", "record", "[]"),
            (
                40,
                "use",
                "record",
                '[{"field": "notes", "key": "staging-login", "why": "its text looks like it holds a secret"}]',
            ),
            (42, "use", "record", "[]"),
        ],
    )
    notes = (
        # id, scope, ticket, repo, key, body, status, why, run, head, created, last used, uses, promoted from
        (
            1,
            "ticket",
            "ABC-100",
            None,
            "flaky-checkout",
            "checkout.spec.ts fails about one run in five; it looks like a timing issue in the payment step.",
            "superseded",
            "superseded by note 2",
            37,
            "4f1c2a9e07b3",
            at(-200),
            at(-115),
            1,
            None,
        ),
        (
            2,
            "ticket",
            "ABC-100",
            None,
            "flaky-checkout",
            "checkout.spec.ts races the payment iframe: waiting on its load event made it pass 20 of 20 runs locally.",
            "active",
            None,
            40,
            "9b2e5d01c4a7",
            at(-112),
            None,
            0,
            None,
        ),
        (
            3,
            "ticket",
            "ABC-100",
            None,
            "ci-cache",
            (
                "CI's cache key leaves out [package-lock.json](https://evil.example/lock)\u200b, so a bumped "
                "lockfile installs from a stale cache."
            ),
            "active",
            None,
            40,
            "9b2e5d01c4a7",
            at(-112),
            None,
            0,
            None,
        ),
        (
            4,
            "ticket",
            "ABC-102",
            None,
            "export-encoding",
            "The CSV writer needs utf-8-sig for Excel to read accented names; plain utf-8 shows mojibake.",
            "active",
            None,
            42,
            "c0ffee12ab34",
            at(-30),
            None,
            0,
            None,
        ),
        (
            5,
            "proposal",
            "ABC-099",
            "web",
            "web-tests",
            "Run web's tests with `npm test -- --run`: plain `npm test` watches and never exits.",
            "pending",
            None,
            39,
            "77aa21d0e9f3",
            at(-62),
            None,
            0,
            None,
        ),
        (
            6,
            "proposal",
            "ABC-102",
            None,
            # Under lesson 8's key, so the memory page shows a proposal that would replace a lesson in force.
            "billing-client",
            "Billing retries go through retry() in src/billing/client.ts too; never loop on a 503 by hand.",
            "pending",
            None,
            42,
            "c0ffee12ab34",
            at(-30),
            None,
            0,
            None,
        ),
        (
            7,
            "proposal",
            "ABC-103",
            "web",
            "billing-client",
            "Billing calls go through src/billing/client.ts; never call the v1 endpoints directly.",
            "superseded",
            "promoted to lesson 8",
            38,
            "1d2c3b4a5f6e",
            at(-126),
            None,
            0,
            None,
        ),
    )
    sql.execute_many(
        conn,
        sql.insert_rows(
            "memories",
            (
                "id",
                "scope",
                "ticket_key",
                "repo",
                "key",
                "body",
                "status",
                "why",
                "run_id",
                "head",
                "created_at",
                "last_used_at",
                "use_count",
                "promoted_from",
                "author",
                "tick_id",
            ),
        ),
        [(*n, "worker", 1) for n in notes],
    )
    # Note 2 is the second version of `flaky-checkout`, as `_run` links a note to the one under its key it replaced.
    sql.execute(conn, sql.update("memories").set(supersedes=1).where("id = 2"))
    sql.execute(
        conn,
        sql.insert(
            "memories",
            id=8,
            scope="lesson",
            repo="web",
            key="billing-client",
            body="Billing goes through src/billing/client.ts alone; the v1 endpoints are gone.",
            status="active",
            author="operator",
            promoted_from=7,
            created_at=at(-100),
            approved_at=at(-100),
            review_at=db.format_time(T0 + timedelta(days=90)),
        ),
    )
    sql.execute(conn, sql.insert("memory_reads", run_id=40, memory_id=1, cited="used"))


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
        sql.execute(
            conn,
            sql.insert(
                "chore_runs",
                id=run_id,
                tick_id=1,
                chore=name,
                started_at=at(started),
                ended_at=at(ended) if ended is not None else None,
                status=status,
                result_json=json.dumps(result) if result is not None else None,
                log_path=str(root.absolute() / workspace.WORKSPACE_STATE_DIR / "chore-runs" / name / f"{run_id}.log"),
                session_id=f"ses_chore{run_id}",
                cost_usd=cost,
                tokens_input=int(cost * 40_000),
                tokens_output=int(cost * 6_000),
                tokens_cache_read=int(cost * 400_000),
                tokens_peak_context=int(cost * 60_000),
            ),
        )
    sql.execute(
        conn,
        sql.insert(
            "messages",
            id=8,
            subject_kind="chore",
            subject_id=CHORE,
            at=at(-300),
            source="operator",
            kind="reply",
            channel="cli",
            body="Leave out the docs site's lockfile: it is never deployed.",
            submission="mock-note-8",
        ),
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
        sql.execute(
            conn,
            sql.insert(
                "decisions",
                tick_id=tick_id,
                created_at=at(when),
                ticket_key=key,
                repo=repo,
                chore=chore,
                pr=pr,
                action=action,
                rationale=rationale,
            ),
        )


def _tools(conn: sqlite3.Connection) -> None:
    """What the agent runs that ended called, by tool (DESIGN §13); a running run has recorded none yet.

    The overseer's PR reads and tracker searches return the most, as MEASUREMENTS 2026-10-13 found.
    """
    calls = (
        # table, run, tool, calls, errors, characters returned
        ("ticks", 1, "github_pull_request_read", 14, 0, 182_000),
        ("ticks", 1, "jira_search", 3, 0, 81_000),
        ("ticks", 1, "bash", 9, 1, 6_400),
        ("ticks", 2, "github_pull_request_read", 11, 0, 143_000),
        ("ticks", 2, "jira_search", 2, 0, 54_000),
        ("ticks", 2, "bash", 6, 0, 3_900),
        ("runs", 37, "bash", 41, 3, 96_000),
        ("runs", 37, "read", 22, 0, 71_000),
        ("runs", 37, "edit", 9, 1, 2_100),
        ("runs", 38, "bash", 18, 0, 37_000),
        ("runs", 38, "read", 12, 0, 40_000),
        ("runs", 39, "bash", 27, 2, 58_000),
        ("runs", 39, "read", 15, 0, 49_000),
        ("runs", 39, "github_pull_request_read", 2, 0, 21_000),
        ("runs", 40, "bash", 33, 6, 88_000),
        ("runs", 42, "read", 8, 0, 19_000),
        ("chore_runs", 1, "bash", 4, 0, 12_000),
        ("chore_runs", 2, "bash", 6, 1, 15_000),
        ("chore_runs", 3, "read", 3, 0, 4_200),
        ("review_runs", 1, "read", 9, 0, 33_000),
        ("review_runs", 2, "read", 7, 0, 26_000),
        ("review_runs", 4, "bash", 5, 0, 8_800),
    )
    sql.execute_many(
        conn,
        sql.insert_rows("run_tools", ("run_table", "run_id", "tool", "calls", "errors", "result_chars")),
        calls,
    )


def _models(conn: sqlite3.Connection) -> None:
    """Which models served the agent runs that ended, as a tick read their sessions after (DESIGN §13).

    Run 39 switched models partway, so its page splits its cost; the reviewer runs on a model of its own. Run 40's read
    failed and waits to be tried again, chore run 2's session is no longer kept, and run 42 is not read yet.
    """
    reads = (
        # table, run, status, error
        ("ticks", 1, "found", None),
        ("ticks", 2, "found", None),
        ("runs", 37, "found", None),
        ("runs", 38, "found", None),
        ("runs", 39, "found", None),
        ("runs", 40, "failed", "the runtime timed out after 30s"),
        ("chore_runs", 1, "found", None),
        ("chore_runs", 2, "missing", None),
        ("chore_runs", 3, "found", None),
        ("review_runs", 1, "found", None),
        ("review_runs", 2, "found", None),
        ("review_runs", 3, "found", None),
        ("review_runs", 4, "found", None),
    )
    sql.execute_many(
        conn,
        sql.insert_rows("run_model_reads", ("run_table", "run_id", "status", "error", "attempts", "read_at")),
        [(table, run, status, error, 1, at(-58)) for table, run, status, error in reads],
    )
    served = (
        # table, run, model, replies, cost: each run's costs add up to what its row says it cost
        ("ticks", 1, "anthropic/claude-sonnet-4-5", 12, 0.28),
        ("ticks", 2, "anthropic/claude-sonnet-4-5", 13, 0.31),
        ("runs", 37, "anthropic/claude-sonnet-4-5", 64, 1.32),
        ("runs", 38, "anthropic/claude-sonnet-4-5", 81, 1.84),
        ("runs", 39, "anthropic/claude-opus-4-1", 23, 1.65),
        ("runs", 39, "anthropic/claude-sonnet-4-5", 41, 0.66),
        ("chore_runs", 1, "anthropic/claude-haiku-4-5", 9, 0.21),
        ("chore_runs", 3, "anthropic/claude-haiku-4-5", 11, 0.33),
        ("review_runs", 1, "openai/gpt-5", 10, 0.21),
        ("review_runs", 2, "openai/gpt-5", 4, 0.06),
        ("review_runs", 3, "openai/gpt-5", 1, 0.02),
        ("review_runs", 4, "openai/gpt-5", 11, 0.24),
    )
    sql.execute_many(
        conn,
        sql.insert_rows("run_models", ("run_table", "run_id", "model", "replies", "cost_usd")),
        served,
    )


def _event(kind: str, session: str, minutes: float, **fields: object) -> str:
    """One event as `opencode run --format json` prints it, `minutes` after T0.

    Returns:
        The event as one line of JSON.
    """
    ms = int((T0 + timedelta(minutes=minutes)).timestamp() * 1000)
    return json.dumps({"type": kind, "timestamp": ms, "sessionID": session, **fields})


def _start(session: str, minutes: float) -> str:
    return _event("step_start", session, minutes, part={"type": "step-start"})


def _text(session: str, minutes: float, text: str) -> str:
    return _event("text", session, minutes, part={"type": "text", "text": text})


def _tool(session: str, minutes: float, tool: str, state: Mapping[str, object], seconds: float = 1) -> str:
    ms = int((T0 + timedelta(minutes=minutes)).timestamp() * 1000)
    metadata: dict[str, object] = {}
    timed = {**state, "metadata": metadata, "time": {"start": ms - int(seconds * 1000), "end": ms}}
    return _event(
        "tool_use",
        session,
        minutes,
        part={"type": "tool", "callID": f"call_{ms}", "tool": tool, "state": timed},
    )


def _step(session: str, minutes: float, cost: float, reason: str = "tool-calls", sent: int | None = None) -> str:
    # Most of what a call sends is read back from the provider's cache, after the first. `sent` is the call's context,
    # for a session whose context grows as a real one does; without it, a share of the cost.
    sent = int(cost * 30_000) if sent is None else sent
    tokens = {
        "input": sent // 4,
        "output": int(cost * 3_000),
        "reasoning": int(cost * 1_000),
        "cache": {"read": sent - sent // 4 - 512, "write": 512},
    }
    return _event(
        "step_finish",
        session,
        minutes,
        part={"type": "step-finish", "reason": reason, "cost": cost, "tokens": tokens},
    )


def _done(session: str, minutes: float, title: str, command: str, output: str, *, seconds: float = 1) -> str:
    """A bash call that completed.

    Returns:
        The `tool_use` event as one line of JSON.
    """
    state = {"status": "completed", "input": {"command": command, "description": title}, "output": output}
    return _tool(session, minutes, "bash", {**state, "title": title}, seconds)


def _coverage() -> str:
    """The table Jest prints after a run's tests when it collects coverage: a line per file, a long tool result.

    Returns:
        The table, as printed.
    """
    dirs = ("api", "components", "hooks", "lib", "pages", "routes", "search", "store", "styles", "utils")
    names = ("client", "format", "index", "keys", "list", "menu", "panel", "query", "table", "toast", "types", "view")
    rule = f"{'-' * 36}|---------|----------|---------|---------|-------------------"
    lines = [rule, f"{'File':<36}| % Stmts | % Branch | % Funcs | % Lines | Uncovered Line #s", rule]
    for i, (folder, name) in enumerate(itertools.product(dirs, names)):
        uncovered = (i * 37) % 41
        covered = 100 - uncovered
        missed = f"{12 + i % 30}-{40 + i % 50}" if uncovered else ""
        row = f"{covered:>8.2f} | {covered - i % 9:>8.2f} | {covered - i % 5:>7.2f} | {covered:>7.2f}"
        lines.append(f"{f'src/{folder}/{name}.ts':<36}|{row} | {missed}")
    return "\n".join([*lines, rule, ""])


_SEARCH_BOX = """\
1\timport { useState } from 'react'
2\t
3\texport function SearchBox({ onSearch }: { onSearch: (q: string) => void }) {
4\t    const [query, setQuery] = useState('')
5\t    return <input value={query} onChange={(e) => { setQuery(e.target.value); onSearch(e.target.value) }} />
6\t}
"""

# Shortened from what canopy renders, keeping its shape.
_PROMPT_39 = """\
# canopy worker: implement

You are working ticket ABC-099 in slot 3. Each repository listed below is checked out with a detached HEAD, at
`agent/ABC-099-search` as it was pushed, or at that repository's base branch if nothing was pushed there yet. This is
attempt 1 of 3.

## Repositories

- web: /home/op/acme/.treehouse/web-3f9c2a1b/3/web, base `main`

## Task

Read the ticket through the tracker MCP. The tracker is jira. Implement the ticket. Follow the repository's AGENTS.md
and conventions. Before each push, run the checks the repository's contributors run before opening a PR, as its
AGENTS.md, contributing guide, Makefile, or CI workflows name them: formatting, lint, and type checks, and the tests it
asks for. Fix what they find, and push when they pass. A check that fails without your change too, or cannot run here,
is not yours to fix: say which and why in your summary.

## Messages from the operator

None.

## Result

End with one line of JSON: {"status": "done" | "failed" | "blocked", "summary": "...", "prs": {"<repo>": "<url>"}}
"""
_PROMPT_TICK_2 = """\
## State

{
  "tick_id": 2,
  "dry_run": false,
  "tickets": [
    {"key": "ABC-101", "phase": "implementing", "run": 41, "attempt": 1},
    {"key": "ABC-104", "phase": "implementing", "run": 43, "attempt": 1}
  ],
  "prs": [{"url": "https://github.com/acme/web/pull/88", "ticket": "ABC-099", "checks": "pending"}],
  "attention": []
}
"""
_PROMPT_CHORE_2 = """\
# canopy chore: deps

Audit each repository's dependencies against the published advisories. Report each advisory that touches a lockfile
as a finding.

## Repositories

- web: /home/op/acme/web
- mobile: /home/op/acme/mobile

## Notes from the operator

None.
"""
_PROMPT_REVIEW_4 = """\
# canopy reviewer

You are reviewing one pull request at one commit. You did not write it and you have no transcript of whoever did.
This is review 2 of at most 2 of this PR.

- PR: https://github.com/acme/web/pull/88
- Commit: `9b2f4c61`. Review this commit, not whatever the PR's head is by the time you read it.
- Checkout: `checkout` is the repository at that commit. Read anything in it you need.
- Ticket: ABC-099.

## Context from the overseer

The first review found a stale response could replace a newer one; check the abort.
"""
# Run 40's setup command, as `_run` writes it before the worker starts (DESIGN §8), and its runtime's stderr.
_SETUP_40 = """\
--- setup web stdout ---
Lockfile is up to date, resolution step is skipped
Packages: +412
Done in 6.2s
--- setup web stderr ---
 WARN  deprecated inflight@1.0.6
"""
_RUN_STDERR_40 = """\
ERROR 2026-10-08T09:41:12 +3m12s service=session error=rate limited: retry after 30s
"""
_TICK_STDERR = """\
INFO  2026-10-08T11:00:00 +210ms service=default version=1.19.0 args=["run","--format","json"] opencode
WARN  2026-10-08T11:00:01 +1043ms service=mcp key=jira error=timed out after 1000ms listing prompts
"""


def _transcripts(state_dir: Path) -> None:
    """Write the events of runs 39 to 43's, tick 2's, chore run 2's, and reviews 3 and 4's sessions where they go."""
    # The worktree run 39 worked in, as the operator's machine names it: the same on every start, for screenshots.
    web = "/home/op/acme/.treehouse/web-3f9c2a1b/3/web"
    s39, s40, s41, s43 = "ses_mock39", "ses_mock40", "ses_mock41", "ses_mock43"
    s2, c2 = "ses_tick2", "ses_chore2"
    r3, r4 = "ses_review3", "ses_review4"
    run_39 = [
        _start(s39, -90),
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
        _step(s39, -89.3, 0.82, sent=24_600),
        _start(s39, -89.2),
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
            f"Tests: 2 passed, 2 total\n\n{_coverage()}",
            seconds=14,
        ),
        _step(s39, -69.9, 0.97, sent=25_900),
        _start(s39, -69.8),
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
        _step(s39, -61, 0.52, reason="stop", sent=30_200),
    ]
    run_40 = [
        _start(s40, -74.1),
        _text(s40, -74, "Reading the failing job's log first."),
        _done(s40, -73, "Find the failing job", "gh run list --branch agent/ABC-100-flaky-test", "", seconds=2),
        _step(s40, -72.5, 0.18),
        _start(s40, -72.4),
        _event("error", s40, -70.1, error={"name": "APIError", "data": {"message": "Rate limited: retry after 60s"}}),
    ]
    # The running runs print as they go (DESIGN §8): what each has done so far, its cost the seeded run's.
    w41, w43 = "/home/op/acme/.treehouse/web-3f9c2a1b/1/web", "/home/op/acme/.treehouse/web-3f9c2a1b/2/web"
    run_41 = [
        _start(s41, 0.5),
        _text(s41, 0.6, "I'll read the login form first, then its tests."),
        _tool(
            s41,
            1,
            "read",
            {
                "status": "completed",
                "input": {"filePath": f"{w41}/src/login/LoginForm.tsx"},
                "output": "export function LoginForm() {}",
                "title": "src/login/LoginForm.tsx",
            },
        ),
        _step(s41, 1.1, 0.2),
        _start(s41, 1.2),
        _done(s41, 27, "Run the login tests", "npm test -- login", "Tests: 4 passed, 4 total\n", seconds=12),
        _step(s41, 27.1, 0.22),
    ]
    run_43 = [
        _start(s43, 5.5),
        _text(s43, 5.6, "The retry test fails on mobile only. Reading the workflow both repositories run."),
        _done(s43, 29, "Read the CI workflow", f"cat {w43}/.github/workflows/ci.yml", "name: ci\n", seconds=1),
        _step(s43, 29.1, 0.12),
    ]
    chore_2 = [
        _start(c2, -240),
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
        _start(c2, -235.8),
        _text(
            c2,
            -233.1,
            json.dumps({"status": "ok", "summary": "One advisory touches web's lockfile.", "findings": [_LODASH]}),
        ),
        _step(c2, -233, 0.12, reason="stop"),
    ]
    tick_2 = [
        _start(s2, -60.1),
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
    # Review 4 read the diff and the files it touches, then reported what its page shows (mock_reviews).
    review_4 = [
        _start(r4, -57.9),
        _text(r4, -57.8, "I'll read the diff against main, then each file it touches in full."),
        _done(
            r4,
            -57.7,
            "Diff against the base",
            "git diff --stat main...HEAD",
            " src/search/SearchBox.tsx |  4 +++-\n src/search/useSearch.ts  | 21 +++++++++++++++++++++\n",
        ),
        _tool(
            r4,
            -57.5,
            "read",
            {
                "status": "completed",
                "input": {"filePath": "checkout/src/search/useSearch.ts"},
                # The new file is the diff's last hunk, its lines without their `+`.
                "output": "\n".join(line[1:] for line in mock_reviews.DIFF_88.splitlines()[-21:]),
                "title": "src/search/useSearch.ts",
            },
        ),
        _step(r4, -57.4, 0.09, sent=18_200),
        _start(r4, -57.3),
        _text(r4, -57, "The abort is right. `setLoading(false)` only runs on success, so an error leaves it on."),
        _done(r4, -56.6, "Find the other timings", "grep -rn '_MS =' src/config.ts", "export const TOAST_MS = 4000\n"),
        _step(r4, -56.5, 0.11, sent=21_400),
        _start(r4, -56.4),
        _text(r4, -56.1, mock_reviews.LATEST.model_dump_json()),
        _step(r4, -56, 0.04, reason="stop", sent=22_900),
    ]
    # Review 3 ended on a file it could not read, and never printed a result: `unknown`, as its row says.
    review_3 = [
        _start(r3, -69.9),
        _text(r3, -69.8, "Reading the billing client the PR moves to v2."),
        _tool(
            r3,
            -69.5,
            "read",
            {
                "status": "error",
                "input": {"filePath": "checkout/src/billing/client.ts"},
                "error": "File not found: checkout/src/billing/client.ts",
            },
        ),
        _text(r3, -69.2, "The client moved, and the diff does not say where. I'll stop here."),
        _step(r3, -69.1, 0.02, reason="stop", sent=9_400),
    ]
    # The running chore run's log exists, as `canopy chores run` opens it, and holds no events yet.
    none: list[str] = []
    written = (
        ("runs", "39", run_39),
        ("runs", "40", run_40),
        ("runs", "41", run_41),
        ("runs", "43", run_43),
        ("ticks", "2", tick_2),
        ("chore-runs/deps", "2", chore_2),
        ("chore-runs/build-health", "4", none),
        ("reviews", "3", review_3),
        ("reviews", "4", review_4),
    )
    for directory, name, lines in written:
        (state_dir / directory).mkdir(mode=0o700, parents=True, exist_ok=True)
        stdout = "\n".join(lines)
        if not lines:
            text = ""
        elif directory == "runs" and name in RUNNING_LOGS:
            # A running worker's stdout so far: no stderr or exit until it ends.
            text = f"--- worker stdout ---\n{stdout}\n"
        elif directory == "runs" and name == "40":
            # What only its output shows: its setup command's, and the runtime's own lines on stderr.
            worker = f"--- worker stdout ---\n{stdout}\n--- worker stderr ---\n{_RUN_STDERR_40}--- worker exit 1 ---\n"
            text = _SETUP_40 + worker
        elif directory == "runs":
            text = f"--- worker stdout ---\n{stdout}\n--- worker stderr ---\n\n--- worker exit 0 ---\n"
        elif directory == "reviews":
            text = f"--- reviewer stdout ---\n{stdout}\n--- reviewer stderr ---\n\n--- reviewer exit 0 ---\n"
        elif directory.startswith("chore-runs/"):
            text = f"--- chore stdout ---\n{stdout}\n--- chore stderr ---\n\n--- chore exit 0 ---\n"
        else:
            # What OpenCode printed on stderr, which only the tick's output shows.
            text = f"{stdout}\n--- stderr ---\n{_TICK_STDERR}"
        logs.write_private(state_dir / directory / f"{name}.log", text)
    # What canopy gave each runtime, kept beside its log: the first model call's input (DESIGN §22).
    prompts = (
        ("runs", "39", _PROMPT_39),
        ("ticks", "2", _PROMPT_TICK_2),
        ("chore-runs/deps", "2", _PROMPT_CHORE_2),
        ("reviews", "4", _PROMPT_REVIEW_4),
    )
    for directory, name, text in prompts:
        logs.write_private(state_dir / directory / f"{name}.prompt", text)
