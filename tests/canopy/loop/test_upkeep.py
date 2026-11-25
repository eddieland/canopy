"""The pools' upkeep a live tick runs (DESIGN §26): git maintenance in an idle clone, and `pools.idle_cmd` in a slot.

At most one job a tick, under the dispatch lock it does not wait for, never in a busy pool's clone or a leased slot, and
a failure raises `upkeep_failed`.
"""

import json
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, db, records, upkeep_runs, workspace
from canopy.core.context import Context
from canopy.core.vocab import UpkeepKind, UpkeepStatus
from canopy.infra import lock, logs, procs
from canopy.loop import attention, upkeep
from tests.canopy.conftest import Ws, seed_pools
from tests.canopy.helpers import AS_AN_AGENT, EDITORS_TERMINAL, saw, writes_env
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv, executable, git

type ContextMaker = Callable[..., Context]

LEASE: Final = {"lease_id": "id-1", "lease_holder": "canopy:PROJ-9", "leased_at": "2026-10-22T00:00:00Z"}
NOW: Final = datetime.now(UTC)
LONG_AGO: Final = NOW - timedelta(days=10)


@pytest.fixture
def make_ctx(ws: Ws, canopy_env: CanopyEnv) -> ContextMaker:
    """Build the context `canopy` builds in `ws`, over its journal, with `pools` keys added to the user file."""
    conn = ws.journal()

    def made(**pools: object) -> Context:
        if pools:
            canopy_env.append_user("\n[pools]\n" + "".join(f"{k} = {toml_value(v)}\n" for k, v in pools.items()))
        cfg = config.load(ws.root, canopy_env.user_file)
        return Context(config=cfg, conn=conn, runner=procs.SubprocessRunner(), ws=workspace.load(ws.root))

    return made


def toml_value(value: object) -> str:
    """`value`, a bool, number, string, or table of strings, as TOML writes it."""
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in value.items()) + " }"
    return json.dumps(value)


def tick(ctx: Context) -> int:
    """Start a tick, and run the upkeep in it.

    Returns:
        The tick's id.
    """
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    upkeep.run(ctx, tick_id, logs.for_tick(tick_id))
    return tick_id


def runs(ctx: Context) -> list[tuple[str, str, str | None, str]]:
    """Each upkeep run the journal records, as (kind, repo, slot, status)."""
    return [
        (r.kind, r.repo, r.slot_path, r.status) for r in records.select(records.UpkeepRun).order_by("id").all(ctx.conn)
    ]


def loose_objects(clone: Path) -> int:
    """How many loose objects `clone` has."""
    counts = dict(line.split(": ") for line in git("count-objects", "-v", cwd=clone).splitlines())
    return int(counts["count"])


def idle_slot(ws: Ws, name: str) -> Path:
    """`name`'s one slot, from `seed_pools`, last changed ten days ago."""
    slot = ws.root / ".treehouse" / f"{name}-fake" / "1" / name
    os.utime(slot, (LONG_AGO.timestamp(), LONG_AGO.timestamp()))
    return slot


def recorder(tmp_path: Path, *, code: int = 0) -> tuple[str, Path]:
    """A command that notes the repository and directory it ran in, and exits `code`.

    Returns:
        The command, and the file it writes.
    """
    noted = tmp_path / "idle.log"
    script = executable(
        tmp_path / "idle-cmd",
        f'#!/bin/sh\necho "$CANOPY_REPO $PWD" >> {noted}\necho "out of room" >&2\nexit {code}\n',
    )
    return str(script), noted


def test_a_tick_packs_an_idle_clone_past_its_thresholds_once_in_its_hours(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    ctx = make_ctx(git_max_loose=0)
    assert loose_objects(ws.clone("api")) > 0

    tick(ctx)
    tick(ctx)
    tick(ctx)

    assert loose_objects(ws.clone("api")) == 0
    assert loose_objects(ws.clone("web")) == 0
    # One clone a tick, then neither again within `git_every_hours`.
    assert runs(ctx) == [("pack", "api", None, "done"), ("pack", "web", None, "done")]
    assert upkeep.failed_items(ctx) == []


def test_a_tidy_clone_is_recorded_skipped_and_left(ws: Ws, treehouse_state: Path, make_ctx: ContextMaker) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    ctx = make_ctx()
    loose = loose_objects(ws.clone("api"))

    tick(ctx)

    assert loose_objects(ws.clone("api")) == loose
    assert runs(ctx) == [("pack", "api", None, "skipped"), ("pack", "web", None, "skipped")]
    latest = upkeep_runs.latest(ctx.conn, UpkeepKind.PACK, "api")
    assert latest is not None
    assert latest.detail.endswith("packs, within pools.git_max_packs and git_max_loose")


def test_a_busy_pools_clone_waits_for_a_tick_that_finds_it_idle(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
) -> None:
    seed_pools(ws, treehouse_state)
    state = json.loads(treehouse_state.read_text())
    state["pools"][str(ws.clone("api"))]["slots"][0] |= {"status": "leased", **LEASE}
    treehouse_state.write_text(json.dumps(state))
    ctx = make_ctx(git_max_loose=0)
    loose = loose_objects(ws.clone("api"))

    tick(ctx)

    assert loose_objects(ws.clone("api")) == loose
    assert runs(ctx) == [("pack", "web", None, "done")]


def test_upkeep_runs_nothing_while_another_holds_the_dispatch_lock(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    ctx = make_ctx(git_max_loose=0)

    with lock.hold(ctx.dispatch_lock_path):
        # Another process's hold, as `canopy gc --git` by hand: this one opens the file anew, so flock refuses it.
        tick(ctx)

    assert runs(ctx) == []


def test_git_maintenance_off_runs_none(ws: Ws, treehouse_state: Path, make_ctx: ContextMaker) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    ctx = make_ctx(git_maintenance=False, git_max_loose=0)

    tick(ctx)

    assert runs(ctx) == []


def test_gc_git_by_hand_is_recorded_so_the_loop_waits_its_hours(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    ctx = make_ctx(git_max_loose=0)

    assert main(["gc", "--git"]) == 0
    tick(ctx)

    hand = records.select(records.UpkeepRun).all(ctx.conn)
    assert [(r.repo, r.tick_id, r.status) for r in hand] == [("api", None, "done"), ("web", None, "done")]


def test_gc_git_removes_a_temporary_pack_an_interrupted_fetch_left_a_day_ago(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    pack_dir = ws.clone("api") / ".git" / "objects" / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    stale, fresh = pack_dir / "tmp_pack_abc123", pack_dir / "tmp_pack_def456"
    stale.write_bytes(b"")
    fresh.write_bytes(b"")
    os.utime(stale, (LONG_AGO.timestamp(), LONG_AGO.timestamp()))

    assert main(["gc", "--git"]) == 0

    assert "removed 1 temporary pack files an interrupted fetch left" in capsys.readouterr().out
    assert not stale.exists()
    assert fresh.exists()


def test_a_dry_run_notes_each_clones_own_objects(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["gc", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "\napi: " in out
    assert "\nweb: " in out
    assert " loose objects (" in out
    assert " packs (" in out


def test_idle_cmd_runs_once_in_a_slot_long_idle(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
    tmp_path: Path,
) -> None:
    seed_pools(ws, treehouse_state)
    slot = idle_slot(ws, "api")
    idle_slot(ws, "web")
    cmd, noted = recorder(tmp_path)
    ctx = make_ctx(git_maintenance=False, idle_cmd={"api": cmd})

    tick(ctx)
    tick(ctx)

    assert noted.read_text() == f"api {slot}\n"
    assert runs(ctx) == [("idle", "api", str(slot), "done")]


def test_idle_cmd_runs_with_no_prompt_and_none_of_the_operators_editor_or_terminal(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
    tmp_path: Path,
) -> None:
    seed_pools(ws, treehouse_state)
    idle_slot(ws, "api")
    seen = tmp_path / "idle-env.json"
    ctx = make_ctx(git_maintenance=False, idle_cmd={"api": writes_env(seen)})

    with mock.patch.dict(os.environ, EDITORS_TERMINAL):
        tick(ctx)

    assert saw(seen.read_text()) == AS_AN_AGENT


def test_idle_cmd_waits_for_a_slot_changed_or_leased_lately(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
    tmp_path: Path,
) -> None:
    seed_pools(ws, treehouse_state)
    api = idle_slot(ws, "api")
    cmd, noted = recorder(tmp_path)
    # web's slot was made just now; api's was idle, until a review leased it yesterday.
    ctx = make_ctx(git_maintenance=False, idle_cmd={"api": cmd, "web": cmd}, idle_after_days=3)
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    yesterday = db.format_time(NOW - timedelta(days=1))
    records.insert(
        records.ReviewRun,
        tick_id=tick_id,
        pr_url="https://github.com/acme/api/pull/7",
        sha="a" * 40,
        repo="api",
        slot_path=str(api),
        started_at=yesterday,
        ended_at=yesterday,
        status="done",
        log_path="l",
    ).run(ctx.conn)

    tick(ctx)

    assert not noted.exists()
    assert runs(ctx) == []


def test_idle_cmd_never_runs_in_a_leased_slot(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
    tmp_path: Path,
) -> None:
    seed_pools(ws, treehouse_state)
    idle_slot(ws, "api")
    state = json.loads(treehouse_state.read_text())
    state["pools"][str(ws.clone("api"))]["slots"][0] |= {"status": "leased", **LEASE}
    treehouse_state.write_text(json.dumps(state))
    cmd, noted = recorder(tmp_path)
    ctx = make_ctx(git_maintenance=False, idle_cmd={"api": cmd})

    tick(ctx)

    assert not noted.exists()


def test_a_failed_idle_cmd_raises_upkeep_failed_and_is_tried_again_after_its_days(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
    tmp_path: Path,
) -> None:
    seed_pools(ws, treehouse_state)
    slot = idle_slot(ws, "api")
    cmd, noted = recorder(tmp_path, code=3)
    ctx = make_ctx(git_maintenance=False, idle_cmd={"api": cmd})

    tick(ctx)
    tick(ctx)

    assert noted.read_text() == f"api {slot}\n"
    [item] = upkeep.failed_items(ctx)
    assert item.repo == "api"
    assert f"pools.idle_cmd failed in {slot} at " in item.detail
    assert "exited 3: out of room; the loop tries again 3 days after, while the slot stays idle" in item.detail

    records.update(records.UpkeepRun).set(started_at=db.format_time(LONG_AGO)).everything().run(ctx.conn)
    tick(ctx)

    assert noted.read_text() == f"api {slot}\n" * 2


def test_a_failed_git_maintenance_raises_upkeep_failed_about_its_repository(
    ws: Ws,
    treehouse_state: Path,
    make_ctx: ContextMaker,
) -> None:
    treehouse_state.write_text(json.dumps({"pools": {}}))
    ctx = make_ctx()
    upkeep_runs.record(
        ctx.conn,
        tick_id=None,
        kind=UpkeepKind.PACK,
        repo="web",
        slot_path=None,
        started_at=NOW,
        status=UpkeepStatus.FAILED,
        detail="git maintenance run exited 128: fatal: bad object",
    )

    [item] = upkeep.failed_items(ctx)

    assert item.repo == "web"
    assert item.detail.startswith(f"git maintenance in {ws.clone('web')} failed at ")
    assert item.detail.endswith("fatal: bad object; the loop tries again in 24 hours while its pool is idle")


def test_idle_cmd_is_private(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared('\n[pools]\nidle_cmd = { api = "rm -rf ." }\n')

    with pytest.raises(config.ConfigError, match=r"pools\.idle_cmd"):
        config.load(canopy_env.root, canopy_env.user_file)


def test_an_idle_run_names_its_slot(make_ctx: ContextMaker) -> None:
    ctx = make_ctx()

    unnamed = records.insert(
        records.UpkeepRun,
        kind=UpkeepKind.IDLE,
        repo="api",
        slot_path=None,
        started_at="x",
        ended_at="y",
        status=UpkeepStatus.DONE,
        detail="d",
    )

    with pytest.raises(sqlite3.IntegrityError):
        # An `idle` run names its slot, and a `pack` run none.
        unnamed.run(ctx.conn)


def test_a_tick_lists_a_failed_upkeep_until_a_newer_run_does_not_fail(
    scenario: Scenario,
    conn: sqlite3.Connection,
) -> None:
    def ran(status: UpkeepStatus, detail: str) -> None:
        upkeep_runs.record(
            conn,
            tick_id=None,
            kind=UpkeepKind.PACK,
            repo="repo",
            slot_path=None,
            started_at=datetime.now(UTC),
            status=status,
            detail=detail,
        )

    ran(UpkeepStatus.FAILED, "git maintenance run exited 128: fatal: bad object")
    scenario.tick()

    assert [(i.repo, i.reason) for i in attention.current(conn)] == [("repo", "upkeep_failed")]

    ran(UpkeepStatus.DONE, "packed")
    scenario.tick()

    assert attention.current(conn) == []
