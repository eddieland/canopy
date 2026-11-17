"""The index of what every session the runtime keeps said, kept in step from its record (ROADMAP M72, stage 2)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest import mock

from canopy.core import db, records, session_index, session_search
from canopy.runtime.implementation import Version
from tests.canopy.helpers import (
    Kept,
    called,
    replied,
    runtime_database,
    runtime_forgets,
    runtime_record,
    sent,
    wrote,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.core.context import Context

#: When the tests' steps run.
NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


def step(ctx: Context, *, exclude: Sequence[str] = (), seconds: float = 60.0, now: datetime = NOW) -> bool:
    """Run one step of keeping the index in step with the operator's record, and return whether it is behind."""
    stepped = session_index.step(
        ctx.conn,
        ctx.state_dir,
        version=Version.TWO,
        exclude=exclude,
        seconds=seconds,
        now=now,
    )
    assert stepped.error is None
    return stepped.behind


def found(ctx: Context, *words: str, canopy: bool = False) -> list[str]:
    """The sessions the index finds by `words`, best first."""
    return [f.session_id for f in session_search.found(ctx.state_dir, words, canopy=canopy)]


def ran_in(conn: sqlite3.Connection, session_id: str) -> None:
    """Record a tick whose overseer ran in session `session_id`, so the session is canopy's."""
    tick_id = db.start_tick(conn, dry_run=False)
    records.update(records.Tick).set(session_id=session_id).where("id = ?", tick_id).run(conn)


def test_the_first_build_goes_newest_first_a_step_stops_at_its_time_and_the_next_goes_on_from_there(
    ctx: Context,
) -> None:
    runtime_record(
        Kept("ses_old", "/home/me", messages=[sent("an alpaca from last year")], updated=10),
        Kept("ses_mid", "/home/me", messages=[sent("an alpaca from last month")], updated=20),
        Kept("ses_new", "/home/me", messages=[sent("an alpaca from last week")], updated=30),
    )

    # A step whose time has run out still takes one session, the newest left.
    assert step(ctx, seconds=0) is True
    assert found(ctx, "alpaca") == ["ses_new"]
    assert step(ctx, seconds=0) is True
    assert sorted(found(ctx, "alpaca")) == ["ses_mid", "ses_new"]
    assert step(ctx, seconds=0) is False

    assert sorted(found(ctx, "alpaca")) == ["ses_mid", "ses_new", "ses_old"]
    progress = session_index.progress(ctx.state_dir, ())
    assert progress is not None
    assert (progress.sessions, progress.built, progress.back_to, progress.current) == (3, True, None, True)
    assert progress.through == db.format_time(datetime.fromtimestamp(0.03, UTC))


def test_a_session_updated_since_is_indexed_again_whole_in_place_of_its_rows(ctx: Context) -> None:
    runtime_record(Kept("ses_a", "/home/me", messages=[sent("draft the kestrel notes")], updated=10))
    step(ctx)
    runtime_record(Kept("ses_a", "/home/me", messages=[sent("draft the osprey notes")], updated=40))
    runtime_record(Kept("ses_b", "/home/me", title="An osprey", updated=50))

    assert step(ctx) is False

    assert found(ctx, "kestrel") == []
    assert sorted(found(ctx, "osprey")) == ["ses_a", "ses_b"]


def test_a_session_the_runtime_dropped_is_gone_after_the_daily_sweep(ctx: Context) -> None:
    runtime_record(
        Kept("ses_a", "/home/me", messages=[sent("the heron count")], updated=10),
        Kept("ses_b", "/home/me", messages=[sent("the heron map")], updated=20),
    )
    step(ctx)
    runtime_forgets("ses_a")

    step(ctx, now=NOW + timedelta(hours=1))
    assert sorted(found(ctx, "heron")) == ["ses_a", "ses_b"]
    step(ctx, now=NOW + session_index.SWEEP_EVERY)

    assert found(ctx, "heron") == ["ses_b"]


def test_a_sandbox_roles_record_is_indexed_and_one_canopy_cannot_read_passed_over_whole(ctx: Context) -> None:
    data = runtime_database().parents[1]
    runtime_record(Kept("ses_a", "/home/me", messages=[sent("a wren")], updated=10))
    runtime_record(
        Kept("ses_w", "/work", messages=[replied(wrote("a wren in the sandbox"))], updated=20),
        path=runtime_database(data / "canopy" / "sandbox" / "worker"),
    )
    broken = runtime_database(data / "canopy" / "sandbox" / "review")
    broken.parent.mkdir(parents=True)
    broken.write_text("not a database")

    step(ctx)

    assert sorted(found(ctx, "wren")) == ["ses_a", "ses_w"]
    progress = session_index.progress(ctx.state_dir, ())
    assert progress is not None
    assert progress.passed_over == 1


def test_a_first_build_whose_record_cannot_be_read_is_not_behind(ctx: Context) -> None:
    """A record the runtime left unreadable ends the step with its error, not behind, so the next waits its gap."""
    broken = runtime_database()
    broken.parent.mkdir(parents=True)
    broken.write_text("not a database")

    stepped = session_index.step(ctx.conn, ctx.state_dir, version=Version.TWO, exclude=(), now=NOW)

    assert stepped.error is not None
    assert not stepped.behind


def test_a_session_of_canopys_is_never_indexed_by_what_it_was_sent(ctx: Context) -> None:
    ran_in(ctx.conn, "ses_tick")
    runtime_record(
        Kept(
            "ses_tick",
            "/work",
            messages=[sent("the state block names a pelican"), replied(wrote("dispatched the puffin ticket"))],
            updated=10,
        ),
        Kept("ses_sub", "/work", parent_id="ses_tick", messages=[sent("a pelican for the subagent")], updated=20),
        Kept("ses_mine", "/home/me", messages=[sent("a pelican of my own")], updated=30),
    )

    step(ctx)

    assert found(ctx, "pelican") == ["ses_mine"]
    assert found(ctx, "pelican", canopy=True) == []
    assert found(ctx, "puffin", canopy=True) == ["ses_tick"]


def test_a_session_in_an_excluded_directory_is_never_indexed_and_a_change_to_exclude_builds_it_again(
    ctx: Context,
) -> None:
    runtime_record(
        Kept("ses_client", "/home/me/clients/acme", messages=[sent("the grebe audit")], updated=10),
        Kept("ses_mine", "/home/me/notes", messages=[sent("the grebe list")], updated=20),
    )
    step(ctx, exclude=["/home/me/clients"])
    assert found(ctx, "grebe") == ["ses_mine"]
    progress = session_index.progress(ctx.state_dir, ())
    assert progress is not None
    assert progress.current is False

    step(ctx)

    assert sorted(found(ctx, "grebe")) == ["ses_client", "ses_mine"]


def test_a_message_past_the_bound_is_cut_and_its_hit_says_so(ctx: Context) -> None:
    runtime_record(
        Kept(
            "ses_a",
            "/home/me",
            messages=[sent(f"the curlew {'x ' * 30} the dunlin"), sent("the curlew again")],
            updated=10,
        ),
    )
    with mock.patch.object(session_index, "MAX_MESSAGE_CHARS", 40):
        step(ctx)

    [hit] = session_search.found(ctx.state_dir, ["curlew"], canopy=False)
    assert (hit.cut, hit.more) == (True, 1)
    assert found(ctx, "dunlin") == []


def test_a_message_whose_json_is_not_what_the_reader_expects_is_passed_over(ctx: Context) -> None:
    runtime_record(
        Kept(
            "ses_a",
            "/home/me",
            messages=[("user", "not JSON at all: the plover"), ("assistant", {"content": "the plover"})],
            updated=10,
        ),
        Kept("ses_b", "/home/me", messages=[replied(called("read", {"path": "plover.md"}, "the plover file"))]),
    )

    step(ctx)

    assert found(ctx, "plover") == ["ses_b"]


def test_the_index_is_removed_and_built_again_whole(ctx: Context) -> None:
    runtime_record(Kept("ses_a", "/home/me", title="The stilt", updated=10))
    step(ctx)
    assert session_index.size(ctx.state_dir)

    assert session_index.remove(ctx.state_dir) is True
    assert session_index.size(ctx.state_dir) is None
    assert session_index.progress(ctx.state_dir, ()) is None
    assert found(ctx, "stilt") == []
    assert session_index.remove(ctx.state_dir) is False

    step(ctx)
    assert found(ctx, "stilt") == ["ses_a"]


def test_an_index_of_another_shape_or_a_file_that_is_no_index_is_built_again(ctx: Context) -> None:
    runtime_record(Kept("ses_a", "/home/me", title="The avocet", updated=10))
    session_index.path(ctx.state_dir).write_text("not a database")
    step(ctx)
    assert found(ctx, "avocet") == ["ses_a"]

    with mock.patch.object(session_index, "SHAPE", session_index.SHAPE + 1):
        progress = session_index.progress(ctx.state_dir, ())
        assert progress is not None
        assert progress.current is False
        step(ctx)
    assert found(ctx, "avocet") == ["ses_a"]


def test_text_is_titles_under_opencode_1_or_a_sqlite_too_old_to_delete_from_the_index() -> None:
    why = session_index.why_titles(version=Version.ONE)
    assert why is not None
    assert "runtime.version 1 is deprecated" in why
    assert session_index.effective("text", version=Version.ONE) == "titles"
    assert session_index.why_titles(version=Version.TWO) is None
    assert session_index.effective("text", version=Version.TWO) == "text"

    with mock.patch.object(sqlite3, "sqlite_version_info", (3, 42, 0)):
        assert session_index.why_titles(version=Version.TWO) == session_index.OLD_SQLITE
        assert session_index.effective("text", version=Version.TWO) == "titles"
    assert session_index.effective("off", version=Version.ONE) == "off"
