"""Every session the runtime keeps, recorded while `canopy loop` waits between ticks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.core import pause, runtime_sessions
from canopy.core.vocab import SessionsRead
from canopy.infra import logs
from canopy.loop import repeat, sessions
from canopy.runtime import sessions as runtime
from canopy.runtime.report import MAX_SESSIONS, SessionPage, SessionSpend
from tests.canopy.helpers import FakeTime, console, context, overseer_does

if TYPE_CHECKING:
    from canopy.core.context import Context
    from tests.conftest import CanopyEnv


def spent(session_id: str, updated_ms: int = 1_000) -> SessionSpend:
    """A session the runtime reports, outside canopy."""
    return SessionSpend(session_id, None, "/home/me", 1_000, updated_ms, 0.5, 1, 2, 0, 0, 0)


def page(count: int) -> SessionPage:
    """A page of `count` sessions, its cursor after the last."""
    found = tuple(spent(f"ses_{i}", 1_000 + i) for i in range(count))
    return SessionPage("found", found, cursor=(1_000 + count - 1, f"ses_{count - 1}") if count else None)


def test_a_caught_up_recorder_reads_again_every_few_minutes(ctx: Context) -> None:
    time = FakeTime()
    recorder = sessions.Recorder(time.clock, logs.for_tick(None))
    with mock.patch.object(runtime, "updated_after", autospec=True, return_value=page(2)) as read:
        assert recorder.step(ctx) is SessionsRead.FOUND
        time.sleep(sessions.EVERY_SECONDS - 1)
        assert recorder.step(ctx) is None
        time.sleep(1)
        assert recorder.step(ctx) is SessionsRead.FOUND

    assert read.call_count == 2
    assert runtime_sessions.of_session(ctx.conn, "ses_1") is not None


def test_a_full_page_is_followed_by_the_next_soon_after(ctx: Context) -> None:
    time = FakeTime()
    recorder = sessions.Recorder(time.clock, logs.for_tick(None))
    with mock.patch.object(runtime, "updated_after", autospec=True, side_effect=[page(MAX_SESSIONS), page(0)]) as read:
        recorder.step(ctx)
        time.sleep(sessions.GAP_SECONDS)
        assert recorder.step(ctx) is SessionsRead.FOUND
        time.sleep(sessions.GAP_SECONDS)
        assert recorder.step(ctx) is None

    assert [c.args[0] for c in read.call_args_list] == [None, (1_000 + MAX_SESSIONS - 1, f"ses_{MAX_SESSIONS - 1}")]


def test_what_a_read_raises_never_ends_the_loop(ctx: Context) -> None:
    time = FakeTime()
    recorder = sessions.Recorder(time.clock, logs.for_tick(None))
    with mock.patch.object(runtime, "updated_after", autospec=True, side_effect=RuntimeError("boom")):
        assert recorder.step(ctx) is SessionsRead.FAILED
        time.sleep(sessions.GAP_SECONDS)
        assert recorder.step(ctx) is None


def test_the_recorder_reads_nothing_while_the_loop_is_paused(ctx: Context) -> None:
    recorder = sessions.Recorder(FakeTime().clock, logs.for_tick(None))
    pause.pause(ctx.conn, channel=pause.LOOP)
    with mock.patch.object(runtime, "updated_after", autospec=True, return_value=page(1)) as read:
        assert recorder.step(ctx) is None
        pause.resume(ctx.conn)
        assert recorder.step(ctx) is SessionsRead.FOUND
    assert read.call_count == 1


def test_a_live_loop_records_the_sessions_and_a_dry_run_none(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    for dry_run in (True, False):
        time = FakeTime()
        term, _ = console()
        with overseer_does(), mock.patch.object(runtime, "updated_after", autospec=True, return_value=page(1)) as read:
            repeat.run(
                context(canopy_env),
                dry_run=dry_run,
                interval_minutes=1,
                max_ticks=2,
                console=term,
                stop=repeat.Stop(),
                sleep=time.sleep,
                clock=time.clock,
            )
        assert read.called is not dry_run

    assert runtime_sessions.of_session(canopy_env.journal(), "ses_0") is not None


@pytest.mark.parametrize("search", ["off", "titles"])
def test_the_recorder_reads_titles_only_while_sessions_search_keeps_them(canopy_env: CanopyEnv, search: str) -> None:
    canopy_env.append_user(f"\n[sessions]\nsearch = '{search}'\nexclude = ['~/clients/']\n")
    canopy_env.journal()
    ctx = context(canopy_env)
    with mock.patch.object(runtime, "updated_after", autospec=True, return_value=page(0)) as read:
        sessions.Recorder(FakeTime().clock, logs.for_tick(None)).step(ctx)

    read_now = runtime_sessions.last_read(ctx.conn)
    assert read_now is not None
    assert read.call_args.kwargs["titles"] is (search == "titles")
    assert read_now.titles == (json.dumps([str(Path.home() / "clients")]) if search == "titles" else None)
