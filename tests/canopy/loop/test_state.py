"""The overseer's state block, whole, rendered from journals written by hand, against snapshots (DESIGN §6 step 4).

Other tests assert on the one part of the block their feature adds. These hold the whole of it, so a change to its
shape is a diff in review, and a regression in a part no other test names still fails. The snapshots are syrupy's,
in `__snapshots__/test_state/`; `make snapshots` records the ones that differ.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from canopy.core import config, conversation, db, pools, workspace
from canopy.core.context import Context
from canopy.core.vocab import Phase, ResumeReason, RunStatus, StartStatus, TickStatus
from canopy.infra import procs
from canopy.loop import duties, harness, harness_dispatches, phases, tick
from canopy.runs import policy, reconcile
from tests.canopy.helpers import chore_toml

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv

DAY = "2026-10-16"
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
# What a snapshot shows in place of the workspace root, which is in a temporary directory.
WORKSPACE = "/workspace"
PR = "https://example.test/acme/repo/pull/7"
#: A row the harness dispatches for, enabled here as a measurement would enable it (DESIGN §37).
CONFLICTED = harness_dispatches.Row(ResumeReason.CONFLICT, "The PR conflicts with its base: bring it in.")


def test_the_state_block_of_a_new_workspace(canopy_env: CanopyEnv, markdown_snapshot: SnapshotAssertion) -> None:
    ctx = context(canopy_env)
    with clock("10:00"):
        tick_id = db.start_tick(ctx.conn, dry_run=False)
    assert rendered(canopy_env, ctx, tick_id, dry_run=False, query_due=True, running=0, leased=[]) == markdown_snapshot


def test_the_state_block_of_a_busy_workspace(canopy_env: CanopyEnv, markdown_snapshot: SnapshotAssertion) -> None:
    # Every section the block can have: a chore, reviews, a notice, tickets in each state the block tells apart, and
    # the harness's dispatches to come.
    prompts(canopy_env, "build-health", "deps")
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\nreview_cmd = '{template}'\n", 1)
    # build-health is the overseer's to decide; deps, with no `when`, is the harness's to run (DESIGN §37).
    canopy_env.write_user(
        user + "\n[review]\nagent_prs = true\n" + chore_toml(extra='when = "Weekdays only."\n') + chore_toml("deps"),
    )
    ctx = context(canopy_env)
    conn = ctx.conn
    root = str(canopy_env.root)
    runs_dir = canopy_env.state_dir / "runs"

    with clock("09:00"):
        earlier = db.start_tick(conn, dry_run=False)
        # PROJ-1: its PR is open and its CI failed; a resume for it and a review ran, so it cools down, and the
        # operator wrote to it.
        db.set_ticket(
            conn,
            "PROJ-1",
            root,
            title="Retry flaky uploads",
            phase=Phase.CI_RUNNING,
            cursors={"comment": "10001"},
        )
        implement = db.insert_run(
            conn,
            tick_id=earlier,
            key="PROJ-1",
            kind="implement",
            branch="agent/PROJ-1-retry",
            slots=[slot(1)],
            runs_dir=runs_dir,
        )
        # PROJ-6 was split before follow-ups replaced splits (M46): its retired phase and run kind still read.
        db.set_ticket(conn, "PROJ-6", root, title="Rework the importer", phase=Phase.SPLIT)
        split = db.insert_run(
            conn,
            tick_id=earlier,
            key="PROJ-6",
            kind="split",
            branch="",
            slots=[slot(3)],
            runs_dir=runs_dir,
            works_units=False,
        )
        # PROJ-5 merged, and the tracker still shows it open: the query found it.
        db.set_ticket(conn, "PROJ-5", root, title="Bump the SDK", phase=Phase.MERGED, done=True)
        decide(conn, earlier, "PROJ-5", "done", "merged")
        db.record_decision(conn, earlier, None, duties.QUERIED_ACTION, duties.queried_rationale(["PROJ-1", "PROJ-5"]))
        # PROJ-3 was started privately and stopped; PROJ-4 is private and its worker asked a question; PROJ-7 is
        # private, and its PR conflicts with its base.
        with db.transaction(conn):
            for key in ("PROJ-3", "PROJ-4", "PROJ-7"):
                db.touch_ticket(conn, key, root)
                db.set_start(conn, conversation.TICKET, key, status=StartStatus.STARTED, channel="cli")
            db.set_start(conn, conversation.TICKET, "PROJ-3", status=StartStatus.STOPPED, channel="cli")
        db.set_ticket(conn, "PROJ-4", root, title="Tidy the CLI help")
        conn.execute(
            "INSERT INTO notices (body, set_at, channel, lapses_at) VALUES (?, ?, 'cli', ?)",
            ("CI is down for maintenance until noon.", stamp("09:00"), stamp("12:00")),
        )
    with clock("09:20"):
        db.finish_run(conn, "runs", split, RunStatus.DONE, None)
        question = db.insert_run(
            conn,
            tick_id=earlier,
            key="PROJ-4",
            kind="implement",
            branch="agent/PROJ-4-help",
            slots=[slot(4)],
            runs_dir=runs_dir,
            private=True,
        )
    with clock("09:30"):
        db.finish_run(conn, "runs", question, RunStatus.BLOCKED, None)
        db.insert_message(
            conn,
            conversation.TICKET,
            "PROJ-4",
            source="worker",
            kind="question",
            channel="run",
            run_id=question,
            body="Should `--help` list the hidden commands?",
        )
    with clock("09:40"):
        db.finish_run(conn, "runs", implement, RunStatus.DONE, None)
        db.set_unit(conn, "PROJ-1", root, "repo", phase="ci_red", pr_url=PR, cursors={"ci": "5551"})
        decide(conn, earlier, "PROJ-1", "attention:needs_reviewer", "no reviewer is assigned", repo="repo")
        # The operator sent a run's reply to a review comment through canopy: the block names it by id (DESIGN §29).
        conn.execute(
            "INSERT INTO drafts (run_id, number, ticket_key, kind, repo, pr_url, comment_id, stance, status, basis, "
            "created_at, sent_at, sent_comment_id, sent_review_id, sent_url) VALUES "
            "(?, 1, 'PROJ-1', 'thread', 'repo', ?, 501, 'changed', 'sent', 'x', 'x', 'x', 9001, 9000, 'u')",
            (implement, PR),
        )
    with clock("09:45"):
        fix = db.insert_run(
            conn,
            tick_id=earlier,
            key="PROJ-1",
            kind="resume",
            branch="agent/PROJ-1-retry",
            slots=[slot(1)],
            runs_dir=runs_dir,
            reasons=("ci", "review"),
        )
    with clock("09:50"):
        db.finish_run(conn, "runs", fix, RunStatus.DONE, None)
        policy.grant(conn, ctx.config, "PROJ-1", "resume", repo="repo", runs=1)
        db.insert_message(
            conn,
            conversation.TICKET,
            "PROJ-1",
            source="operator",
            kind="reply",
            channel="cli",
            body="Keep the retry count at three.",
        )
        db.finish_tick(conn, earlier, TickStatus.OK, "")
    with clock("09:55"):
        # PROJ-2 is being implemented now.
        db.set_ticket(conn, "PROJ-2", root, title="Add a dark mode", phase=Phase.RUNNING)
        db.insert_run(
            conn,
            tick_id=earlier,
            key="PROJ-2",
            kind="implement",
            branch="agent/PROJ-2-dark",
            slots=[slot(2)],
            runs_dir=runs_dir,
        )
    with clock("10:00"):
        # The harness decided PROJ-2 before the overseer: the block names it, and lists it no more (DESIGN §37). Its
        # derivation found PROJ-7's unit conflicted, a row enabled here as a measurement would: the harness resumes it
        # after the overseer.
        tick_id = tick_deciding(conn, root, "PROJ-2")
        derive_conflicted(conn, tick_id, "PROJ-7")

    leased = [
        pools.Slot(
            name="repo-2",
            path=canopy_env.root / "slots" / "repo-2",
            status="leased",
            lease_id="lease-2",
            lease_holder=f"{pools.HOLDER_PREFIX}PROJ-2",
            leased_at=stamp("09:55"),
        ),
    ]
    with mock.patch.object(harness_dispatches, "ROWS", {Phase.CONFLICTED: CONFLICTED}):
        assert (
            rendered(canopy_env, ctx, tick_id, dry_run=True, query_due=False, running=1, leased=leased)
            == markdown_snapshot
        )


def prompts(env: CanopyEnv, *names: str) -> None:
    """Write a prompt for each chore of `names`, where `chore_toml` names it."""
    for name in names:
        prompt = env.home / "chores" / f"{name}.md"
        prompt.parent.mkdir(exist_ok=True)
        prompt.write_text(f"# {name}\n")


def derive_conflicted(conn: sqlite3.Connection, tick_id: int, key: str) -> None:
    """Record that tick `tick_id` derived `key` a fresh candidate holding no row, and its unit in `repo` conflicted."""
    conflicted = [
        phases.Derived(key, None, (), candidate=True, closed=False),
        phases.Derived(key, "repo", (Phase.CONFLICTED,)),
    ]
    phases.record(conn, tick_id, conflicted)


def context(env: CanopyEnv) -> Context:
    ws = workspace.load(env.root)
    return Context(
        config=config.load(env.root, env.user_file),
        conn=env.journal(),
        runner=procs.SubprocessRunner(),
        ws=ws,
    )


@contextmanager
def clock(hhmm: str) -> Iterator[None]:
    """Until the block ends, the journal records every time it writes as `hhmm` on the snapshots' day."""
    with mock.patch.object(db, "now", autospec=True, return_value=stamp(hhmm)):
        yield


def tick_deciding(conn: sqlite3.Connection, root: str, key: str) -> int:
    """Start a dry-run tick in which the harness decided `key`, a worker of which is running, and return its id."""
    tick_id = db.start_tick(conn, dry_run=True)
    why = f"{Phase.RUNNING}: {harness.ROWS[Phase.RUNNING].why}"
    harness.record(conn, tick_id, root, [harness.Decision(key, Phase.RUNNING, "wait", why)])
    return tick_id


def stamp(hhmm: str) -> str:
    return f"{DAY}T{hhmm}:00.000Z"


def decide(
    conn: sqlite3.Connection,
    tick_id: int,
    key: str,
    action: str,
    rationale: str,
    *,
    repo: str | None = None,
    chore: str | None = None,
    pr: str | None = None,
) -> None:
    """Record a decision at the clock's time: the schema's default is the real one."""
    decision = db.record_decision(conn, tick_id, key, action, rationale, repo=repo, chore=chore, pr=pr)
    conn.execute("UPDATE decisions SET created_at = ? WHERE id = ?", (db.now(), decision))


def slot(n: int) -> db.RunSlot:
    return db.RunSlot(
        repo="repo",
        slot_path=Path(WORKSPACE) / "slots" / f"repo-{n}",
        lease_id=f"lease-{n}",
        lease_holder=f"{pools.HOLDER_PREFIX}PROJ-{n}",
        base_branch="main",
    )


def rendered(
    env: CanopyEnv,
    ctx: Context,
    tick_id: int,
    *,
    dry_run: bool,
    query_due: bool,
    running: int,
    leased: list[pools.Slot],
) -> str:
    """The tick's state block, with its JSON indented so a change to it is a readable diff, and the root replaced."""
    capacity = reconcile.Capacity(max_workers=ctx.config.capacity.max_workers, running=running)
    block = tick.state_block(
        ctx,
        tick_id=tick_id,
        dry_run=dry_run,
        now=NOW,
        reconciled=reconcile.Reconciled(capacity, {"repo": leased}),
        query_due=query_due,
    )
    head, rest = block.split("```json\n", 1)
    compact, tail = rest.split("\n```", 1)
    state = json.dumps(json.loads(compact), indent=2, ensure_ascii=False)
    return f"{head}```json\n{state}\n```{tail}".replace(str(env.root), WORKSPACE)
