"""The attention items the overseer keeps: recorded once, naming what each is about, and held until that ends it.

`needs_author`, `multi_repo`, and `notice_rerun` (DESIGN §14, §37, `core.kept_items`). The journals are written by
hand: the overseer's record made through its command or its tool, the ticks around it closed as the case needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db, kept_items
from canopy.core.vocab import Phase, TickStatus
from canopy.loop import attention, harness, phases
from tests.canopy.helpers import KEY, decisions, in_tick, mcp_session, operator, tool_call, waits
from tests.canopy.observation_helpers import PR, check, comment, held, review
from tests.canopy.scenario_helpers import raises, skips_tick

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core.context import Context
    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv

#: KEY's unit, whose PR is the helpers' PR.
REPO = "repo"


def records_item(conn: sqlite3.Connection, reason: str, *more: str, key: str = KEY) -> int:
    """The overseer records `reason` about `key`, with `more` of the command's options, in an `ok` tick of its own.

    Returns:
        The tick's id.
    """
    with in_tick(conn, ends_ok=True) as tick_id:
        assert main(["attention", key, reason, "--detail", f"{key} detail", *more]) == 0
    return tick_id


def ticks(conn: sqlite3.Connection, *statuses: TickStatus, key: str = KEY) -> None:
    """A tick for each of `statuses` that gives the overseer `key` and records no item about it: it waits."""
    for status in statuses:
        tick_id = db.start_tick(conn, dry_run=False)
        db.record_decision(conn, tick_id, key, "wait", "nothing new")
        db.finish_tick(conn, tick_id, status, "test")


def open_items(conn: sqlite3.Connection) -> list[tuple[str | None, str, str | None]]:
    return [(i.ticket_key, i.reason, i.repo) for i in attention.current(conn)]


def answers(conn: sqlite3.Connection, *, submission: str | None = None) -> None:
    """The operator answers on KEY: a message of theirs, or with `submission` an instruction a verb of theirs wrote."""
    db.insert_message(
        conn,
        conversation.TICKET,
        KEY,
        source="operator",
        kind="reply",
        channel="cli",
        body="Split it.",
        submission=submission,
    )
    conn.commit()


@pytest.fixture
def unit(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """KEY, held since before anything was observed, with its unit in REPO at the helpers' PR."""
    held(canopy_env, conn, KEY)
    db.set_unit(conn, KEY, str(canopy_env.root), REPO, pr_url=PR)
    conn.commit()


@pytest.mark.usefixtures("unit")
def test_a_needs_author_naming_a_comment_is_held_until_the_comment_cursor_passes_it(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    asks = comment(conn, "c1", "acc-1", "2026-10-20T11:00:00Z", "Should this be a new service?")
    later = comment(conn, "c2", "acc-1", "2026-10-20T11:30:00Z", "And what about the old one?")
    recorded = records_item(conn, "needs_author", "--item", str(asks))
    [decision] = db.decisions_for_tick(conn, recorded)
    assert (decision.kept, decision.item) == (True, asks)
    # Ticks that give the overseer the ticket and leave the item out, a skipped one, and one whose overseer failed.
    ticks(conn, TickStatus.OK, TickStatus.SKIPPED, TickStatus.OVERSEER_FAILED, TickStatus.OK)
    assert open_items(conn) == [(KEY, "needs_author", None)]
    [listed] = attention.for_overseer(conn)
    assert listed == {"ticket": KEY, "reason": "needs_author", "since": decision.created_at, "kept": True, "item": asks}
    # A cursor short of it ends nothing; one at it does.
    db.set_ticket(conn, KEY, str(canopy_env.root), cursors={"comment": str(asks - 1)})
    assert open_items(conn) == [(KEY, "needs_author", None)]
    db.set_ticket(conn, KEY, str(canopy_env.root), cursors={"comment": str(later)})
    assert open_items(conn) == []
    assert attention.for_overseer(conn) == []


@pytest.mark.usefixtures("unit")
def test_a_needs_author_naming_a_review_item_is_held_until_its_units_review_cursor_passes_it(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    pushback = review(conn, 41, "octocat", "commented", "2026-10-20T11:00:00Z", "Why not reuse the queue?")
    records_item(conn, "needs_author", "--repo", REPO, "--item", str(pushback))
    ticks(conn, TickStatus.OK, TickStatus.OK)
    # The ticket's comment cursor is not the cursor of this item's kind.
    db.set_ticket(conn, KEY, str(canopy_env.root), cursors={"comment": str(pushback)})
    assert open_items(conn) == [(KEY, "needs_author", REPO)]
    db.set_unit(conn, KEY, str(canopy_env.root), REPO, cursors={"review": str(pushback)})
    assert open_items(conn) == []


@pytest.mark.usefixtures("unit")
@pytest.mark.parametrize("reason", ["needs_author", "multi_repo"])
def test_an_item_about_its_ticket_alone_is_held_until_the_operator_answers_after_it(
    conn: sqlite3.Connection,
    reason: str,
) -> None:
    answers(conn)  # before it: no answer to it
    records_item(conn, reason)
    ticks(conn, TickStatus.OK, TickStatus.SKIPPED, TickStatus.OVERSEER_FAILED)
    answers(conn, submission=f"{conversation.INSTRUCTION}grant")  # a verb's instruction answers nothing
    assert open_items(conn) == [(KEY, reason, None)]
    answers(conn)
    assert open_items(conn) == []


@pytest.mark.usefixtures("unit")
def test_a_notice_rerun_is_held_until_a_newer_run_of_its_check_is_observed(conn: sqlite3.Connection) -> None:
    check(conn, "build", "completed", "failure", run_id=11)
    check(conn, "lint", "completed", "failure", run_id=12)
    [held_run] = conn.execute("SELECT number FROM observed_check_runs WHERE run_id = 11").fetchone()
    records_item(conn, "notice_rerun", "--repo", REPO, "--item", str(held_run))
    ticks(conn, TickStatus.OK, TickStatus.SKIPPED, TickStatus.OVERSEER_FAILED, TickStatus.OK)
    answers(conn)  # the operator's answer reruns nothing
    check(conn, "lint", "completed", "success", run_id=13)  # another check's newer run
    check(conn, "build", "in_progress", None, run_id=14)  # its rerun, still running
    assert open_items(conn) == [(KEY, "notice_rerun", REPO)]
    check(conn, "build", "completed", "success", run_id=14)
    assert open_items(conn) == []


@pytest.mark.usefixtures("unit")
@pytest.mark.parametrize("how", ["done", "stopped"])
def test_each_kept_item_goes_once_its_ticket_is_done_or_stopped(conn: sqlite3.Connection, how: str) -> None:
    check(conn, "build", "completed", "failure", run_id=11)
    [held_run] = conn.execute("SELECT number FROM observed_check_runs").fetchone()
    records_item(conn, "multi_repo")
    records_item(conn, "notice_rerun", "--repo", REPO, "--item", str(held_run))
    records_item(conn, "needs_author")
    assert len(open_items(conn)) == 3
    if how == "done":
        db.change_ticket(conn, KEY, "done", 1)
        conn.commit()
    else:
        assert operator("start", KEY) == 0
        assert operator("stop", KEY) == 0
    assert open_items(conn) == []


@pytest.mark.usefixtures("unit")
def test_two_records_of_one_item_hold_it_until_both_are_ended(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    first = comment(conn, "c1", "acc-1", "2026-10-20T11:00:00Z", "Is this in scope?")
    second = comment(conn, "c2", "acc-1", "2026-10-20T11:30:00Z", "Who owns the old path?")
    records_item(conn, "needs_author", "--item", str(first))
    since = attention.current(conn)[0].since
    records_item(conn, "needs_author", "--item", str(second))
    assert [(r.item, r.reason) for r in kept_items.held(conn)] == [(first, "needs_author"), (second, "needs_author")]
    db.set_ticket(conn, KEY, str(canopy_env.root), cursors={"comment": str(first)})
    [item] = attention.current(conn)
    assert (item.ticket_key, item.reason, item.detail) == (KEY, "needs_author", f"{KEY} detail")
    assert item.since > since  # open since the record still held
    assert [r.get("item") for r in attention.for_overseer(conn)] == [second]


@pytest.mark.usefixtures("unit")
def test_a_dry_runs_record_counts_only_while_its_tick_is_the_latest(conn: sqlite3.Connection) -> None:
    with in_tick(conn, dry_run=True, ends_ok=True):
        assert main(["attention", KEY, "multi_repo", "--detail", "api and web"]) == 0
    assert open_items(conn) == [(KEY, "multi_repo", None)]
    ticks(conn, TickStatus.OK)
    assert open_items(conn) == []


@pytest.mark.usefixtures("unit")
def test_an_item_recorded_every_tick_before_it_was_kept_is_read_as_then_and_not_listed(
    conn: sqlite3.Connection,
) -> None:
    with in_tick(conn, ends_ok=True) as tick_id:
        db.record_decision(conn, tick_id, KEY, "attention:needs_author", "from before")
    assert open_items(conn) == [(KEY, "needs_author", None)]
    # Not listed, so the overseer records it once more if its cause holds, and the list keeps it open.
    assert attention.for_overseer(conn) == []
    records_item(conn, "needs_author")
    ticks(conn, TickStatus.OK)
    assert open_items(conn) == [(KEY, "needs_author", None)]


#: A record of each kept reason that names nothing that could end it, as the command and its tool take it, and why.
UNNAMED = {
    "no ticket": (
        ["needs_author", "--pr", PR],
        {"pr": PR, "reason": "needs_author"},
        "needs_author is held until something about its ticket ends it: name the ticket",
    ),
    "no check run": (
        [KEY, "notice_rerun", "--repo", REPO],
        {"key": KEY, "reason": "notice_rerun", "repo": REPO},
        "notice_rerun is held until a newer run of its check is observed: name the check run's number",
    ),
    "nothing observed": (
        [KEY, "needs_author", "--item", "999"],
        {"key": KEY, "reason": "needs_author", "item": 999},
        "item 999 names nothing the journal observed",
    ),
}


@pytest.mark.usefixtures("unit")
@pytest.mark.parametrize("case", UNNAMED, ids=list(UNNAMED))
def test_a_kept_item_that_names_nothing_that_could_end_it_is_refused(conn: sqlite3.Connection, case: str) -> None:
    command, arguments, why = UNNAMED[case]
    for through in ("command", "tool"):
        with in_tick(conn) as tick_id:
            if through == "command":
                assert main(["attention", *command, "--detail", "d"]) == 1
            else:
                said = mcp_session(tool_call("attention", **arguments, detail="d")).said()
                assert said.error
                assert "refused (unnamed)" in said.text
            assert decisions(conn, tick_id) == [("refused:unnamed", why)]
    assert attention.current(conn) == []


@pytest.mark.usefixtures("unit")
def test_a_kept_item_naming_what_is_not_its_own_is_refused(conn: sqlite3.Connection) -> None:
    elsewhere = comment(conn, "c1", "acc-1", "2026-10-20T11:00:00Z", "On another ticket.")
    conn.execute("UPDATE item_numbers SET subject = 'PROJ-2' WHERE number = ?", (elsewhere,))
    check(conn, "build", "completed", "failure", run_id=11)
    [run] = conn.execute("SELECT number FROM observed_check_runs").fetchone()
    pushback = review(conn, 41, "octocat", "commented", "2026-10-20T11:00:00Z", "Why?")
    with in_tick(conn) as tick_id:
        assert main(["attention", KEY, "needs_author", "--detail", "d", "--item", str(elsewhere)]) == 1
        assert main(["attention", KEY, "needs_author", "--detail", "d", "--item", str(run)]) == 1
        assert main(["attention", KEY, "notice_rerun", "--detail", "d", "--item", str(pushback)]) == 1
        assert main(["attention", KEY, "notice_rerun", "--detail", "d", "--repo", "other", "--item", str(run)]) == 1
        # Not a guard's refusal: `item` on a reason that names none is a field the tool cannot take.
        assert main(["attention", KEY, "multi_repo", "--detail", "d", "--item", str(run)]) != 0
    assert [why for _, why in decisions(conn, tick_id)] == [
        f"item {elsewhere} is a comment on another ticket",
        f"item {run} is a check_run, which no needs_author names",
        f"item {pushback} is a review, which no notice_rerun names",
    ]


def test_a_merged_ticket_with_a_multi_repo_open_is_left_to_the_overseer(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    ctx: Context,
) -> None:
    held(canopy_env, conn, KEY)
    conn.commit()
    merged: Sequence[phases.Derived] = [phases.Derived(KEY, None, (Phase.MERGED,), candidate=True, closed=False)]
    with mock.patch.object(harness, "ROWS", {Phase.MERGED: harness.Row("done", "every unit's PR merged")}):
        assert [d.action for d in harness.decide(ctx, merged)] == ["done"]
        records_item(conn, "multi_repo")
        assert harness.decide(ctx, merged) == []


def test_the_overseer_records_one_once_and_ticks_that_leave_it_out_keep_it(scenario: Scenario) -> None:
    scenario.seen(KEY)
    first = scenario.tick(raises(KEY, "multi_repo", "api and web, unrelated"))
    scenario.tick(*waits(KEY))
    [listed] = scenario.state()["attention"]  # what the second tick's overseer was shown
    assert (listed["reason"], listed["kept"]) == ("multi_repo", True)
    scenario.tick(skips_tick("mcp_unavailable: github"), code=1)
    scenario.tick(result="gave up", code=1)
    scenario.tick(*waits(KEY))
    [item] = attention.current(scenario.conn)
    [recorded] = [d for d in first.decisions if d.action == "attention:multi_repo"]
    assert (item.ticket_key, item.reason, item.since) == (KEY, "multi_repo", recorded.created_at)
    scenario.operator("reply", KEY, "Do them jointly.")
    assert scenario.attention() == []
