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
from canopy.core.vocab import Phase, RunStatus, StartStatus, TickStatus
from canopy.infra import procs
from canopy.loop import tick
from canopy.runs import policy, reconcile
from tests.canopy.helpers import chore_toml

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv

DAY = "2026-10-16"
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
DELIMITER = "CANOPY_BODY_0123456789abcdef"
# What a snapshot shows in place of the workspace root, which is in a temporary directory.
WORKSPACE = "/workspace"
PR = "https://example.test/acme/repo/pull/7"


def test_the_state_block_of_a_new_workspace(canopy_env: CanopyEnv, markdown_snapshot: SnapshotAssertion) -> None:
    ctx = context(canopy_env)
    with clock("10:00"):
        tick_id = db.start_tick(ctx.conn, dry_run=False)
    assert rendered(canopy_env, ctx, tick_id, dry_run=False, query_due=True, running=0, leased=[]) == markdown_snapshot


def test_the_state_block_of_a_busy_workspace(canopy_env: CanopyEnv, markdown_snapshot: SnapshotAssertion) -> None:
    # Every section the block can have: a chore, reviews, a notice, tickets in each state the block tells apart.
    prompt = canopy_env.home / "chores" / "build-health.md"
    prompt.parent.mkdir()
    prompt.write_text("# Build health\n")
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\nreview_cmd = '{template}'\n", 1)
    canopy_env.write_user(user + "\n[review]\nagent_prs = true\n" + chore_toml(extra='when = "Weekdays only."\n'))
    ctx = context(canopy_env)
    conn = ctx.conn
    root = str(canopy_env.root)
    runs_dir = canopy_env.state_dir / "runs"

    with clock("09:00"):
        earlier = db.start_tick(conn, dry_run=False)
        # PROJ-1: its PR is open and its CI failed; one fix-ci ran, so it cools down, and the operator wrote to it.
        db.set_ticket(
            conn, "PROJ-1", root, title="Retry flaky uploads", phase=Phase.CI_RUNNING, cursors={"comment": "10001"}
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
        # PROJ-6 was split in two, and neither child is done.
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
        db.record_split_children(conn, "PROJ-6", split, {"PROJ-7": "repo", "PROJ-8": "repo"})
        # PROJ-5 merged, and the tracker still shows it open.
        db.set_ticket(conn, "PROJ-5", root, title="Bump the SDK", phase=Phase.MERGED, done=True)
        decide(conn, earlier, "PROJ-5", "done", "merged")
        # PROJ-3 was started privately and stopped; PROJ-4 is private and its worker asked a question.
        with db.transaction(conn):
            for key in ("PROJ-3", "PROJ-4"):
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
        db.set_unit(conn, "PROJ-1", root, "repo", phase="ci_failed", pr_url=PR, cursors={"ci": "5551"})
        decide(conn, earlier, "PROJ-1", "attention:needs_reviewer", "no reviewer is assigned", repo="repo")
    with clock("09:45"):
        fix = db.insert_run(
            conn,
            tick_id=earlier,
            key="PROJ-1",
            kind="fix-ci",
            branch="agent/PROJ-1-retry",
            slots=[slot(1)],
            runs_dir=runs_dir,
        )
    with clock("09:50"):
        db.finish_run(conn, "runs", fix, RunStatus.DONE, None)
        policy.grant(conn, ctx.config, "PROJ-1", "fix-ci", repo="repo", runs=1)
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
        tick_id = db.start_tick(conn, dry_run=True)

    leased = [
        pools.Slot(
            name="repo-2",
            path=canopy_env.root / "slots" / "repo-2",
            status="leased",
            lease_id="lease-2",
            lease_holder=f"{pools.HOLDER_PREFIX}PROJ-2",
            leased_at=stamp("09:55"),
        )
    ]
    assert (
        rendered(canopy_env, ctx, tick_id, dry_run=True, query_due=False, running=1, leased=leased) == markdown_snapshot
    )


def context(env: CanopyEnv) -> Context:
    ws = workspace.load(env.root)
    return Context(
        config=config.load(env.root, env.user_file), conn=env.journal(), runner=procs.SubprocessRunner(), ws=ws
    )


@contextmanager
def clock(hhmm: str) -> Iterator[None]:
    """Until the block ends, the journal records every time it writes as `hhmm` on the snapshots' day."""
    with mock.patch.object(db, "now", autospec=True, return_value=stamp(hhmm)):
        yield


def stamp(hhmm: str) -> str:
    return f"{DAY}T{hhmm}:00.000Z"


def decide(conn: sqlite3.Connection, tick_id: int, key: str, action: str, rationale: str, **about: str) -> None:
    """Record a decision at the clock's time: the schema's default is the real one."""
    decision = db.record_decision(conn, tick_id, key, action, rationale, **about)
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
    with mock.patch.object(conversation, "body_delimiter", autospec=True, return_value=DELIMITER):
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
