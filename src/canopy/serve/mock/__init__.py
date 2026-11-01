"""A journal seeded from fixtures, for the UI's development server and its end-to-end tests (`--mock`).

The server reads and writes it through the same code as the loop's journal: only the attention list, ending a run, a
reload, a tick asked for, the attempt and review limits and their grants, a chore's try, the pools' slots, the models
the runtime lists, and the skills it finds are stand-ins, since the first six belong to the loop, `runs`,
`reviews`, and `chores`, and there is no treehouse or runtime to ask (backend.py): the models are those its runs'
sessions name, and the skills five the `skills` module makes up. A try records its run and starts nothing, so the run
stays running.
It is a workspace (DESIGN §18), canopy's usual shape: `api` has no clone, `mobile` and `web` do, `web`'s pool holds one
slot past its declared size, and run 43 holds a slot in both. Two chores are configured (§19), `deps` and
`build-health`, `deps` on a model of its own (§13). Two ticks recorded decisions about tickets, a unit, a repository,
a chore, and a PR (§6). The
workspace's policy allows one resume and two reviews, so ABC-100 is at its resume limit in web, where its run 40, a
`fix-ci` from before a resume fixed CI, counts as one (§8), and PR 88 at its review limit (§22's grants). Run 43,
running, is a resume for a failed check and review feedback together. The running runs 41 and 43 have the latest tool
call on each one's row (§8). Every run on T0's day that ended reported its first model call, on the definitions snapshot
and the runtime's version the history's last week used, so the spend page's weekly hit rate goes on from it (§13).
Each feature's fixtures are in a module of their own in this package, named for the feature, which `seed` calls: plans,
memory, chore runs, review runs, review replies, feedback plans in each state, personas, one-off tasks, the worker
runs' answers to the checklists, the PRs' check runs, GitHub's times on the PRs, the runs' transcripts, the months
before T0, whose landed tickets the reports page shows, and the machine (a fixed reading).
Times are fixed around 2026-10-08 12:00 UTC, so a test that freezes the browser's clock gets the same page every time.
`changes` moves the running run's cost now and then, which the event stream then shows.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, LiteralString

from canopy.core import (
    cards,
    chore_runs,
    chore_view,
    config,
    conversation,
    db,
    pools,
    records,
    review_runs,
    sql,
    workspace,
)
from canopy.core.context import db_path
from canopy.core.items import Item
from canopy.core.vocab import RunKind, RunStatus
from canopy.infra import resources
from canopy.runtime.report import ModelList
from canopy.serve.backend import Backend, Granted, Limit, Reloading
from canopy.serve.mock import (
    checklists,
    chores,
    ci,
    drafts,
    feedback_plans,
    history,
    host,
    memory,
    personas,
    plan_approvals,
    plans,
    review_waits,
    reviews,
    skills,
    tasks,
    transcripts,
)

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

[policy]
max_resume_attempts = 1
max_reviews_per_pr = 2
"""

_USER_TOML = """\
[tracker]
labels = ["agent-ready-mock"]

# The tracker source config requires (DESIGN §30). The mock runs no tick, so it reads nothing, and `.example` names no
# host anyway.
[connect.sources.jira]
kind = "tracker"
cmd = "canopy-connect-jira --site jira.example"

[capacity]
slots_per_repo = 2
# Runs 41 and 43, and task 6's run, which counts against max_workers too: the limit is full, never past it.
max_workers = 3

[capacity.repo_slots]
web = 4

[spend]
# What the spend page tracks October's runs against; the settings page may raise it to its ceiling.
monthly_budget_usd = 40
# A sink taking loop events would hear at half and at four fifths of it too, beside the budget itself.
budget_alerts = [50, 80]

[memory]
ticket_notes = "use"
proposals = "record"

[trust]
authorized_repliers = ["mock-operator"]
# Whose review feedback a worker addresses unasked; the settings page may only remove one.
trusted_reviewers = ["canopy:review", "lint-bot"]

[runtime.models]
# Only the agents no ticket's page shows, so the settings page has models to name and each ticket keeps the default.
overseer = "anthropic/claude-sonnet-4-5"
chore = "anthropic/claude-haiku-4-5"

[chores.deps]
prompt = "{chores}/deps.md"
# Its own: the advisories it reads are long, so it thinks harder than `build-health`, which takes `runtime.models`'.
model = "anthropic/claude-haiku-4-5@high"
every_minutes = 360
days = ["mon", "tue", "wed", "thu", "fri"]
hours = "08:00-18:00"
timezone = "UTC"
when = "Skip it when nothing has merged to main since the last run."

[chores.build-health]
prompt = "{chores}/build-health.md"
every_minutes = 120
"""
# The chore whose finding the attention list shows.
CHORE = "deps"
# Each cloned repository's pool directory, as treehouse names it: the clone's name and a short hash of its remote.
_POOLS = {"mobile": "mobile-8e41d0c7", "web": "web-3f9c2a1b"}
# The variants the mock's runtime lists for each provider's models, which a ticket's page may choose one at.
_VARIANTS = {"anthropic": ("high", "max"), "openai": ("minimal", "low", "medium", "high")}


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
    # Run 46's feedback plan, which waits on the operator to approve it on PR 88's page (DESIGN §32).
    Item(
        "ABC-099",
        "plan_review",
        "feedback plan 1 for https://github.com/acme/web/pull/88 waits: canopy plan ABC-099 --approve or "
        "canopy reply ABC-099",
        at(-10),
    ),
    # Carol's PR, which the operator asked canopy to review: its review is done, its draft unpublished (DESIGN §34).
    Item(
        f"pr:{reviews.PR_14}",
        "review_waiting",
        f"review:5 and review:6, which you asked for, are done: their drafts of {reviews.PR_14} wait on you to "
        "publish or stage one",
        at(-30),
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
    size of four. mobile: run 43's other slot, and the running task's (tasks.py).

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
            {
                "status": "leased",
                "detached": True,
                "lease_id": tasks.RUNNING_LEASE,
                "lease_holder": f"canopy:task:{tasks.RUNNING_TASK}",
                "leased_at": at(2),
                "processes": [{"pid": 48644, "name": "opencode"}],
            },
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
    prompts = user_file.parent / "chores"
    prompts.mkdir(parents=True)
    for name, title in ((CHORE, "Dependency advisories"), ("build-health", "Build health")):
        (prompts / f"{name}.md").write_text(f"# {title}\n\nCheck {name} for the mock workspace.\n")
    user_file.write_text(_USER_TOML.replace("{chores}", str(prompts)))
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
        runner=lambda: drafts.GitHub(db_path(ws)),
        user_file=user_file,
        models=_models_listed,
        skills=skills.listed,
        # Read when the e2e tests' frozen clock says it is (`NOW` in ui/e2e/helpers.ts), so it reads as just now.
        host=lambda _config, _workspace: host.machine(T0 + timedelta(minutes=30)),
        samples=host.samples(T0 + timedelta(minutes=30)),
        processes=lambda: host.processes(T0 + timedelta(minutes=30)),
        sampling=False,
    )
    with backend.open() as ctx:
        db.migrate(ctx.conn, resources.migrations_dir())
        with db.transaction(ctx.conn):
            _fixtures(ctx.conn, root)
            history.seed(ctx.conn, root)
            plans.seed(ctx.conn, ws.state_dir, at, root)
            memory.seed(ctx.conn, at)
            reviews.seed(ctx.conn, ws.state_dir, at)
            drafts.seed(ctx.conn, ws.state_dir, at, slot_path(root, "web", 3))
            feedback_plans.seed(ctx.conn, ws.state_dir, at, ctx.config.trust, slot_path(root, "web", 3))
            personas.seed(ctx.conn, ctx.config, at)
            tasks.seed(ctx.conn, ws.state_dir, at, lambda repo, n: slot_path(root, repo, n))
            checklists.seed(ctx.conn)
            ci.seed(ctx.conn, at)
            _first_calls(ctx.conn)
            _attachments(ctx.conn)
            # Last but `_every_kind`, so the messages their approvals wrote take ids after every other fixture's.
            feedback_plans.seed_states(
                ctx.conn,
                ws.state_dir,
                at,
                ctx.config.trust,
                repo=str(root),
                slot=slot_path(root, "mobile", 1),
            )
            # After the states, so their plans keep their ids; it writes no message.
            feedback_plans.seed_answered(ctx.conn, ws.state_dir, at, slot_path(root, "web", 3))
            _every_kind(ctx.conn)
            review_waits.seed(ctx.conn, at)
            # Last, so its runs take ids after every other fixture's.
            plan_approvals.seed(ctx.conn, ws.state_dir, root)
        reviews.drafts(ctx.conn, at)
    transcripts.write(ws.state_dir, T0)
    return backend


def _every_kind(conn: sqlite3.Connection) -> None:
    """Give ABC-103's conversation every kind a message can be, so its screenshot shows each bubble (DESIGN §22).

    It already holds a question, the operator's reply a tick has read, and a report. This adds canopy's note on a tick,
    a tracker comment, and a reply no tick has read yet: last of every fixture, so its id is past the latest tick's.
    """
    records.insert(
        records.Message,
        subject_kind="ticket",
        subject_id="ABC-103",
        at=at(-119),
        source="canopy",
        kind="note",
        channel="tick",
        body="Tick 1 read message 2 and decided nothing about ABC-103.",
        answers=2,
    ).run(conn)
    records.insert(
        records.Message,
        subject_kind="ticket",
        subject_id="ABC-103",
        at=at(-100),
        source="tracker",
        kind="comment",
        channel="tracker",
        body="QA signed off on the v2 invoices in staging. Ship it once the PR is green.",
        comment_id="10002",
        author="557058:ann",
        commented_at=at(-101),
    ).run(conn)
    records.insert(
        records.Message,
        subject_kind="ticket",
        subject_id="ABC-103",
        at=at(-30),
        source="operator",
        kind="reply",
        channel="web",
        body="Also drop the v1 webhook handler while you are in there.",
    ).run(conn)


def _attachments(conn: sqlite3.Connection) -> None:
    """Attach a design doc to ABC-102 and to task 1, so their pages show one (DESIGN §22): rows alone, unread."""
    for kind, subject, name, size, added in (
        ("ticket", "ABC-102", "sso-design.md", 18_432, -300),
        ("task", "1", "importer-design-v2.md", 9_216, -420),
    ):
        insert = records.insert(
            records.Attachment,
            subject_kind=kind,
            subject_id=subject,
            name=name,
            size=size,
            sha256="0" * 64,
            channel="web",
            added_at=at(added),
        )
        insert.run(conn)


def _attention(ctx: Context) -> list[Item]:
    """The fixtures' list, less a finding the operator dismissed, as `loop.attention.listed` leaves one out.

    Returns:
        `ATTENTION` without the findings dismissed in the mock journal, the tasks' items as the journal has them, and
        the running runs' questions unanswered, as `loop.attention.shown` adds them.
    """
    dismissed = {
        (f"chore:{f.chore}", f.finding.id)
        for f in chore_view.open_findings(ctx.conn, ctx.config, ctx.workspace, starts=ctx.finding_starts)
        if f.dismissed
    }
    listed = [i for i in ATTENTION if (i.ticket_key, i.reason) not in dismissed] + tasks.attention(ctx.conn)
    return listed + cards.questions(ctx.conn)


def _end_run(ctx: Context, run: records.Run) -> bool:
    current = db.get_run(ctx.conn, run.id)
    if current is None or current["status"] != "running":
        return False
    note = json.dumps({"harness": "the operator stopped the ticket (mock: no process was killed)"})
    return conversation.close_run(ctx.conn, ctx.config, current, RunStatus.STOPPED, note)


def _reload(_ctx: Context) -> Reloading:
    # No loop runs on the mock's config, so there is nothing to read again, a save from the settings page included.
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
        # Counted apart, as `runs.policy` counts them, and shown with no unit's limits.
        .where("r.kind NOT IN ('split', 'plan', 'feedback-plan')")
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
    runs = len(review_runs.review_runs_of(ctx.conn, url))
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
            records.insert(records.ReviewGrant, pr_url=ref.id, runs=1, granted_at=db.format_time(T0)).run(ctx.conn)
            return Granted(repo=None, runs=reviewed.runs, limit=reviewed.limit + 1)
        units = {(found.repo, found.kind): found for found in _limits(ctx, ref.id)}
        repos = {r for r, _ in units}
        if repo is None and len(repos) == 1:
            [repo] = repos
        current = units.get((repo, kind))
        if repo is None or current is None:
            raise conversation.Refused("unknown_repo", f"{ref} has had no runs in {repo or 'one repository only'}")
        records.insert(
            records.AttemptGrant,
            ticket_key=ref.id,
            repo=repo,
            kind=kind,
            runs=1,
            granted_at=db.format_time(T0),
        ).run(ctx.conn)
        return Granted(repo=repo, runs=current.runs, limit=current.limit + 1)


def _models_listed(ctx: Context) -> ModelList:
    """The models the mock's runtime lists: those its journal says served its runs, so a ticket's page may choose one.

    Each lists the variants `_VARIANTS` gives its provider, as OpenCode derives them for a reasoning model.

    Returns:
        Each model a run's session names, once, with its variants.
    """
    served = records.select(records.RunModel).all(ctx.conn)
    models = frozenset(m.model for m in served)
    return ModelList(models, {m: _VARIANTS.get(m.partition("/")[0], ()) for m in models})


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
    run_id = chore_runs.insert_chore_run(
        ctx.conn,
        tick_id=None,
        chore=name,
        logs_dir=ctx.state_dir / "chore-runs" / name,
    )
    records.update(records.ChoreRun).set(started_at=db.format_time(T0)).where("id = ?", run_id).run(ctx.conn)
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
        (
            records.update(records.Run)
            .set_to("cost_usd = round(cost_usd + 0.01, 2)")
            .where("id = ?", LIVE_RUN)
            .where("status = 'running'")
            .run(ctx.conn)
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
        records.insert(
            records.Tick,
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
        ).run(conn)
    # Their overseers' tokens, in the proportions the runs' are below.
    (
        records.update(records.Tick)
        .set_to("tokens_input = CAST(cost_usd * 40000 AS INTEGER)")
        .set_to("tokens_output = CAST(cost_usd * 6000 AS INTEGER)")
        .set_to("tokens_cache_read = CAST(cost_usd * 400000 AS INTEGER)")
        .set_to("tokens_peak_context = CAST(cost_usd * 60000 AS INTEGER)")
        .everything()
        .run(conn)
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
        records.insert(
            records.Ticket,
            key=key,
            repo=repo,
            first_seen_at=at(-300),
            last_seen_at=at(seen),
            changed_at=at(seen),
            title=title,
            phase=phase,
            branch=branch,
        ).run(conn)
    for key, branch, pr_url in (
        ("ABC-099", "agent/ABC-099-search", "https://github.com/acme/web/pull/88"),
        ("ABC-103", "agent/ABC-103-billing-v2", "https://github.com/acme/web/pull/91"),
    ):
        records.insert(
            records.TicketUnit,
            ticket_key=key,
            repo="web",
            branch=branch,
            pr_url=pr_url,
            phase="review_pending",
        ).run(conn)
    # Each PR's own title, as its worker or its review reported it: not its ticket's, and #12 has no ticket at all.
    records.insert_rows(records.PrTitle, ("pr_url", "title", "updated_at")).many(
        conn,
        [
            ("https://github.com/acme/web/pull/88", "ABC-099: debounce the search box by 250 ms", at(-59)),
            ("https://github.com/acme/web/pull/91", "ABC-103: move billing to v2 and drop the v1 client", at(-125)),
            ("https://github.com/acme/api/pull/12", "Bump the retry budget for flaky upstreams", at(-79)),
            ("https://github.com/acme/api/pull/14", "Retry the upstream on a 503, with backoff", at(-30)),
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
        records.insert(
            records.Run,
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
        ).run(conn)
    # What each running run's worker did last, as `_run` records it from the events its log holds (transcripts.py).
    activities = (
        (LIVE_RUN, "bash", "npm test -- login", 27),
        (43, "bash", "cat /home/op/acme/.treehouse/web-3f9c2a1b/2/web/.github/workflows/ci.yml", 29),
    )
    for run_id, tool, did, minutes in activities:
        (
            records.update(records.Run)
            .set(activity_tool=tool, activity=did, activity_at=at(minutes))
            .where("id = ?", run_id)
            .run(conn)
        )
    # What each running run's agent says of where it stands, its card (DESIGN §41): 41's fresh, asking a question, 43's
    # stale, gone more tool calls than `cards.STALE_CALLS` without an update.
    said = (
        (
            LIVE_RUN,
            cards.Card(
                summary="The SSO callback is in and its tests pass; wiring the login button next.",
                now="running the login tests",
                done=(cards.Done(step="add the SSO callback", proof="tests pass: 12/12"),),
                next=("wire the login button", "push", "open the PR"),
                # The steps of ABC-101's approved plan, its sections their stages.
                steps=(
                    cards.Step(title="Add the SSO callback route", status="done", stage="API"),
                    cards.Step(title="Wire the login button", status="working", stage="Web"),
                    cards.Step(title="Remember the last provider", status="skipped", stage="Web"),
                    cards.Step(title="Push and open the PR", status="not_started"),
                ),
                # A question it works around meanwhile, waiting on the operator.
                question=cards.Question(
                    ask="Keep the password form beside the SSO button, or hide it behind a link?",
                    options=("keep both side by side", "hide the form behind a link", "drop the password form"),
                    recommend="B",
                ),
            ),
            24,
            9,
            3,
        ),
        (
            43,
            cards.Card(
                summary="Reading the failed CI job; the queue's retry test is red on this branch alone.",
                now="reading the CI workflow",
                done=(cards.Done(step="read the failed job's log", proof="1 test red: test_retry_backoff"),),
                next=("fix the backoff", "push"),
                stuck="the CI log is cut short; reading the workflow for the step instead",
            ),
            12,
            4,
            26,
        ),
    )
    for run_id, card, minutes, by_then, since in said:
        recorded = records.update(records.Run).set(card_json=card.model_dump_json(), card_at=at(minutes))
        recorded = recorded.set(card_calls=by_then, tool_calls=by_then + since).where("id = ?", run_id)
        working = {s.title: at(minutes) for s in card.steps if s.status == "working"}
        recorded = recorded.set(card_asked_at=at(minutes) if card.question is not None else None)
        recorded.set(card_working_since=json.dumps(working) if working else None).run(conn)
    # Run 39's peak is the most one model call in its transcript was sent (transcripts.py), as its page's chart shows.
    records.update(records.Run).set(tokens_peak_context=30200).where("id = 39").run(conn)
    run_slots = (
        # run, repo, slot, lease, holder: run 43 is joint, a slot in web and one in mobile; 37 and 40 ended long ago
        (37, "web", 4, "lease-37", "canopy:ABC-100"),
        (40, "web", 4, "lease-40", "canopy:ABC-100"),
        (LIVE_RUN, "web", 1, "lease-1", "canopy:ABC-101"),
        (43, "web", 2, "lease-2", "canopy:ABC-104"),
        (43, "mobile", 1, "lease-3", "canopy:ABC-104"),
    )
    for run_id, name, slot, lease, holder in run_slots:
        records.insert(
            records.RunSlot,
            run_id=run_id,
            repo=name,
            slot_path=slot_path(root, name, slot),
            lease_id=lease,
            lease_holder=holder,
            base_branch="main",
        ).run(conn)
    # Run 43 fixes a failed check and answers review feedback in one run (DESIGN §8).
    records.insert_rows(records.RunReason, ("run_id", "reason")).many(conn, [(43, "ci"), (43, "review")])
    for key, started in (("ABC-102", -35), ("ABC-104", -20)):
        records.insert(
            records.Start,
            subject_kind="ticket",
            subject_id=key,
            status="started",
            started_at=at(started),
            channel="web",
        ).run(conn)
    records.insert(
        records.Start,
        subject_kind="ticket",
        subject_id="ABC-103",
        status="stopped",
        started_at=at(-160),
        stopped_at=at(-100),
        channel="cli",
    ).run(conn)
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
            # Markdown, as workers write it: what rich text reads in a bubble (inline code, a heading, a list, a fence)
            # shows in ABC-103's screenshots, its Gruvbox one included.
            (
                "Moved billing to the v2 endpoint and removed the v1 client.\n\n"
                "## What changed\n"
                "- `InvoiceClient` calls `/v2/invoices`; `LegacyInvoiceClient` is gone.\n"
                "- `make check` passes, `test_invoices.py` included.\n\n"
                "```\nuv run pytest -q tests/invoices\n12 passed\n```\n\n"
                "https://github.com/acme/web/pull/91"
            ),
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
        records.insert(
            records.Message,
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
        ).run(conn)
    records.insert(
        records.Message,
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
    ).run(conn)
    chores.seed(conn, root, at, CHORE)
    _decisions(conn)
    _tools(conn)
    _models(conn)


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
        records.insert(
            records.Decision,
            tick_id=tick_id,
            created_at=at(when),
            ticket_key=key,
            repo=repo,
            chore=chore,
            pr=pr,
            action=action,
            rationale=rationale,
        ).run(conn)


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
    records.insert_rows(records.RunTool, ("run_table", "run_id", "tool", "calls", "errors", "result_chars")).many(
        conn,
        calls,
    )


def _models(conn: sqlite3.Connection) -> None:
    """Which models served the agent runs that ended, as their sessions were read once they had (DESIGN §13).

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
    records.insert_rows(records.RunModelRead, ("run_table", "run_id", "status", "error", "attempts", "read_at")).many(
        conn,
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
    records.insert_rows(records.RunModel, ("run_table", "run_id", "model", "replies", "cost_usd")).many(conn, served)


# What each kind's first model call was sent on T0's day, before the run's id adds a little, and the share of it read
# from the cache. A table's name here is fixed, never input (D125).
_FIRST_CALLS: tuple[tuple[LiteralString, int, float], ...] = (
    # table, sent, share read from the cache
    ("ticks", 31_800, 0.86),
    ("runs", 22_400, 0.88),
    ("chore_runs", 14_200, 0.74),
    ("review_runs", 18_600, 0.81),
    ("task_runs", 22_100, 0.69),
)


def _first_calls(conn: sqlite3.Connection) -> None:
    """What the first model call of each run on T0's day that ended was sent, read, and wrote, and what it loaded (§13).

    The definitions snapshot and the runtime's version are the history's last week's, so no week of a series on the
    spend page names a change the fixtures made.
    """
    day = at(-12 * 60)
    for table, sent, hit in _FIRST_CALLS:
        ended = "started_at >= ? AND ended_at IS NOT NULL AND cost_usd IS NOT NULL"
        (
            records.update(records.of_table(table))
            .set_to("tokens_first_call = ? + id * 97", sent)
            .set(definitions_digest=history.SNAPSHOT)
            .where(ended, day)
            .run(conn)
        )
        (
            records.update(records.of_table(table))
            # A few points apart from run to run, so a chore's series is not its kind's.
            .set_to("tokens_first_cache_read = CAST(tokens_first_call * (? - id % 3 * 0.03) AS INTEGER)", hit)
            .where(ended, day)
            .run(conn)
        )
        (
            records.update(records.of_table(table))
            .set_to("tokens_first_cache_write = tokens_first_call - tokens_first_cache_read")
            .where(ended, day)
            .run(conn)
        )
    (
        records.update(records.RunModelRead)
        .set(runtime_version=history.RUNTIME)
        .where("status = ? AND runtime_version IS NULL", "found")
        .run(conn)
    )
