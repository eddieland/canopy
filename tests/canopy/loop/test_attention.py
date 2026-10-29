"""The attention list rendered to `attention.md`, and its diff piped to `notify.cmd` (DESIGN §6, §14)."""

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from itertools import starmap
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import db, review_runs
from canopy.core.config import ConfigError, load
from canopy.core.vocab import Decider, ReviewRunStatus
from canopy.loop import attention
from tests.canopy.helpers import KEY, context, in_tick, messages, operator, seen, waits
from tests.canopy.scenario_helpers import Scenario, raises
from tests.conftest import CanopyEnv

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def item(key: str, reason: str, detail: str, age: timedelta) -> attention.Item:
    return attention.Item(key, reason, detail, db.format_time(NOW - age))


def test_render_groups_by_reason() -> None:
    items = [
        item("PROJ-1", "crashed", "run 3 ended crashed", timedelta(hours=2)),
        item("PROJ-2", "needs_author", "https://example.test/pr/2\nsecond line", timedelta(days=1, hours=3)),
        item("PROJ-4", "crashed", "run 5 ended crashed", timedelta(seconds=40)),
    ]
    assert attention.render(items, NOW) == (
        "# canopy attention\n"
        "\n"
        "3 items, updated 2026-09-24 12:00 UTC. An item leaves this list when its cause is gone.\n"
        "\n"
        "## crashed\n"
        "\n"
        "- PROJ-1, 2h: run 3 ended crashed\n"
        "- PROJ-4, 40s: run 5 ended crashed\n"
        "\n"
        "## needs_author\n"
        "\n"
        "- PROJ-2, 1d: https://example.test/pr/2 second line\n"
    )


def test_render_empty() -> None:
    assert attention.render([], NOW) == "# canopy attention\n\nNothing needs you. Updated 2026-09-24 12:00 UTC.\n"


def recorded(*items: tuple[str, str]) -> list[list[str]]:
    """The overseer records each (key, reason) as needing attention, its detail `<key> detail`."""
    return list(starmap(raises, items))


def test_every_tick_rewrites_attention_md(scenario: Scenario, canopy_env: CanopyEnv) -> None:
    path = canopy_env.state_dir / "attention.md"
    scenario.tick(*recorded(("PROJ-3", "needs_author")), dry_run=True)
    text = path.read_text()
    assert "## needs_author\n\n- PROJ-3, " in text
    assert text.endswith(": PROJ-3 detail\n")
    assert path.stat().st_mode & 0o777 == 0o600

    scenario.tick(*waits("PROJ-3"), dry_run=True)
    assert "Nothing needs you." in path.read_text()


def test_notify_gets_new_and_resolved_items_once(scenario: Scenario, canopy_env: CanopyEnv, notified: Path) -> None:
    listing = f"Full list: {canopy_env.state_dir / 'attention.md'}\n"
    # PROJ-3's is an item the overseer records every tick its cause holds; PROJ-4's one it keeps (DESIGN §37).
    both = recorded(("PROJ-3", "flaky_rerun"), ("PROJ-4", "multi_repo"))
    scenario.tick(*both)
    assert messages(notified) == [
        "canopy attention: 2 new, 0 resolved\n"
        "+ PROJ-3 flaky_rerun: PROJ-3 detail\n"
        "+ PROJ-4 multi_repo: PROJ-4 detail\n" + listing,
    ]

    # Still open, even with a reworded detail: nothing new to say.
    scenario.tick(raises("PROJ-3", "flaky_rerun", "reworded"), *waits("PROJ-4"))
    assert len(messages(notified)) == 1

    scenario.tick(*waits("PROJ-3", "PROJ-4"))
    assert messages(notified)[1] == "canopy attention: 0 new, 1 resolved\n- PROJ-3 flaky_rerun\n" + listing

    # An item that comes back after going away is new again.
    scenario.tick(*recorded(("PROJ-3", "flaky_rerun")), *waits("PROJ-4"))
    assert messages(notified)[2].startswith("canopy attention: 1 new, 0 resolved\n+ PROJ-3 flaky_rerun")
    rows = scenario.conn.execute("SELECT ticket_key FROM notifications")
    assert sorted(str(r[0]) for r in rows) == ["PROJ-3", "PROJ-4"]


def reviewed(conn: sqlite3.Connection, logs: Path, key: str, impact: str, sha: str) -> None:
    """A `done` review of `key`'s PR at `sha`, the reviewer, or the harness, judging its impact `impact`."""
    with in_tick(conn, ends_ok=True) as tick_id:
        run_id = review_runs.insert_review_run(
            conn,
            tick_id=tick_id,
            pr_url=f"https://example.test/acme/repo/pull/{key}",
            sha=sha,
            ticket=key,
            repo=None,
            purpose="own",
            logs_dir=logs,
        )
        assert db.claim_run(conn, "review_runs", run_id, os.getpid())
        report = {"status": "done", "verdict": "clean", "impact": impact}
        assert db.finish_run(conn, "review_runs", run_id, ReviewRunStatus.DONE, json.dumps(report))


def test_an_item_whose_pr_has_a_high_impact_review_reaches_the_operator_first(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    notified: Path,
    tmp_path: Path,
) -> None:
    """The latest commit reviewed decides: PROJ-5's `high` was of a commit a later review read again (DESIGN §21)."""
    reviewed(scenario.conn, tmp_path, "PROJ-3", "normal", "a" * 40)
    reviewed(scenario.conn, tmp_path, "PROJ-4", "high", "b" * 40)
    reviewed(scenario.conn, tmp_path, "PROJ-5", "high", "c" * 40)
    reviewed(scenario.conn, tmp_path, "PROJ-5", "normal", "d" * 40)
    scenario.tick(*recorded(("PROJ-3", "needs_author"), ("PROJ-4", "multi_repo"), ("PROJ-5", "needs_author")))
    [message] = messages(notified)
    assert message.splitlines()[1:4] == [
        "+ PROJ-4 multi_repo: PROJ-4 detail",
        "+ PROJ-3 needs_author: PROJ-3 detail",
        "+ PROJ-5 needs_author: PROJ-5 detail",
    ]
    assert [i.ticket_key for i in attention.listed(context(canopy_env))] == ["PROJ-4", "PROJ-3", "PROJ-5"]


def test_failed_notify_is_retried_next_tick(scenario: Scenario, canopy_env: CanopyEnv, notified: Path) -> None:
    needs_author = recorded(("PROJ-3", "needs_author"))
    with mock.patch.dict(os.environ, {"NOTIFY_EXIT": "1"}):
        scenario.tick(*needs_author)  # a failed notification does not fail the tick
    assert scenario.conn.execute("SELECT count(*) FROM notifications").fetchone()[0] == 0
    assert "notify command failed" in (canopy_env.state_dir / "canopy.log").read_text()

    scenario.tick(*needs_author)
    assert [m.splitlines()[1] for m in messages(notified)] == ["+ PROJ-3 needs_author: PROJ-3 detail"] * 2
    assert scenario.conn.execute("SELECT count(*) FROM notifications").fetchone()[0] == 1


def test_a_failed_tick_leaves_the_list_and_notifies_nothing_new(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    notified: Path,
) -> None:
    scenario.tick(*recorded(("PROJ-3", "needs_author")))
    scenario.tick(result="gave up", code=1)
    assert "- PROJ-3, " in (canopy_env.state_dir / "attention.md").read_text()
    assert len(messages(notified)) == 1


def ok_tick(conn: sqlite3.Connection, *decided: tuple[str | None, str], by: Decider = Decider.OVERSEER) -> int:
    """An `ok` tick that records each `(key, action)` in `decided`, by `by`, an attention item as `attention:<reason>`.

    Returns:
        Its id.
    """
    with in_tick(conn, ends_ok=True) as tick_id:
        for key, action in decided:
            db.record_decision(conn, tick_id, key, action, f"{key} detail", decider=by)
    return tick_id


def open_items(conn: sqlite3.Connection) -> list[tuple[str | None, str]]:
    return [(i.ticket_key, i.reason) for i in attention.current(conn)]


def test_an_overseer_item_stands_through_a_tick_not_given_its_ticket_and_goes_when_one_leaves_it_out(
    conn: sqlite3.Connection,
) -> None:
    ok_tick(conn, (KEY, "attention:needs_author"))
    since = attention.current(conn)[0].since
    # The harness decided it, so the overseer was not shown it: its refusal `decided` does not give it the ticket.
    ok_tick(conn, (KEY, "wait"), by=Decider.HARNESS)
    ok_tick(conn, (KEY, "refused:decided"), ("PROJ-2", "wait"))
    [item] = attention.current(conn)
    assert (item.ticket_key, item.reason, item.since) == (KEY, "needs_author", since)
    assert attention.for_overseer(conn, decided={KEY}) == []
    ok_tick(conn, (KEY, "wait"))
    assert open_items(conn) == []


def test_an_overseer_item_recorded_again_keeps_its_age_and_takes_its_new_detail(conn: sqlite3.Connection) -> None:
    ok_tick(conn, (KEY, "attention:needs_author"))
    since = attention.current(conn)[0].since
    ok_tick(conn, ("PROJ-2", "wait"))
    with in_tick(conn, ends_ok=True) as tick_id:
        db.record_decision(conn, tick_id, KEY, "attention:needs_author", "reworded")
    [item] = attention.current(conn)
    assert (item.detail, item.since) == ("reworded", since)


@pytest.mark.parametrize("how", ["done", "stopped"])
def test_an_overseer_item_goes_once_its_ticket_is_done_or_stopped(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    how: str,
) -> None:
    seen(conn, canopy_env, KEY, "PROJ-2")
    ok_tick(conn, (KEY, "attention:needs_author"), ("PROJ-2", "attention:needs_author"))
    if how == "done":
        db.change_ticket(conn, KEY, "done", 1)
        conn.commit()
    else:
        assert operator("start", KEY) == 0
        assert open_items(conn) == [(KEY, "needs_author"), ("PROJ-2", "needs_author")]
        assert operator("stop", KEY) == 0
    assert open_items(conn) == [("PROJ-2", "needs_author")]


def test_the_harnesss_item_goes_the_first_ok_tick_that_does_not_record_it(conn: sqlite3.Connection) -> None:
    # Its cause is read again every tick, whatever reason it names: one it raises from its cause, such as an
    # `attempt_limit`, too (DESIGN §37).
    ok_tick(conn, (KEY, "attention:crashed"), ("PROJ-2", "attention:attempt_limit"), by=Decider.HARNESS)
    assert open_items(conn) == [(KEY, "crashed"), ("PROJ-2", "attempt_limit")]
    ok_tick(conn)
    assert open_items(conn) == []


def test_a_guards_item_is_held_as_the_overseers_is(conn: sqlite3.Connection) -> None:
    # A refused dispatch records its `attempt_limit` in the overseer's call: held through a tick that did not give the
    # overseer the ticket, as its own items are, and gone at the first that did and recorded none.
    ok_tick(conn, ("PROJ-2", "attention:attempt_limit"))
    ok_tick(conn, ("PROJ-2", "wait"), by=Decider.HARNESS)
    assert open_items(conn) == [("PROJ-2", "attempt_limit")]
    ok_tick(conn, ("PROJ-2", "wait"))
    assert open_items(conn) == []


def test_an_overseer_item_about_a_pr_goes_the_next_tick_the_overseer_ran_without_it(conn: sqlite3.Connection) -> None:
    with in_tick(conn, ends_ok=True) as tick_id:
        db.record_decision(conn, tick_id, None, "attention:needs_author", "run 3", pr="https://example.test/pr/3")
    assert open_items(conn) == [("pr:https://example.test/pr/3", "needs_author")]
    ok_tick(conn)
    assert open_items(conn) == []


def test_notify_cmd_takes_no_prompt_placeholder(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user("\n[notify]\ncmd = 'notify-send {prompt}'\n")
    with pytest.raises(ConfigError, match=r"notify\.cmd: Value error, must not contain \{prompt\}"):
        load(canopy_env.root, canopy_env.user_file)


def test_notify_cmd_must_split_into_words(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user('\n[notify]\ncmd = "notify-send \'canopy"\n')
    with pytest.raises(ConfigError, match=r"notify\.cmd: Value error, No closing quotation"):
        load(canopy_env.root, canopy_env.user_file)
