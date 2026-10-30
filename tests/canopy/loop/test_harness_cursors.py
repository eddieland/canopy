"""The harness moves cursors past what needs no handling (DESIGN §37, ROADMAP M38): a worker's comment, a reply sent.

Over journals written by hand, observed fresh at `NOW`: a ticket's `comment` cursor passes the workers' comments
directly after it, and a unit's `review` cursor the workers' review items and the replies the operator sent, and each
stops at the first item anything else, never moving back. A stale subject keeps its cursor. Then through ticks: each
move recorded as the harness's and shown by `canopy decisions`, the state block showing what is left past it, and a dry
run moving nothing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from canopy.core import db
from canopy.core.vocab import Decider, ReviewRunStatus, TickStatus
from canopy.loop import harness, harness_cursors, phases
from tests.canopy.helpers import KEY, context, in_tick, operator, waits
from tests.canopy.observation_helpers import (
    FRESH,
    NOW,
    OLD,
    PR,
    TRACKER,
    TRUST,
    comment,
    held,
    observe_pr,
    observe_ticket,
    review,
    review_number,
    sent_draft,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv

#: A body that carries the workers' marks, `trust.comment_prefix` by default (D069).
MARKED = "CANOPY: Renamed it, as asked."


@pytest.fixture
def observed(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> sqlite3.Connection:
    """KEY held and observed open with the queue label, its unit in `repo` with PR observed open, all at FRESH.

    Returns the journal.
    """
    canopy_env.configure(canopy_env.user_file, TRACKER)
    canopy_env.configure(canopy_env.user_file, TRUST)
    held(canopy_env, conn, KEY)
    observe_ticket(conn)
    db.set_unit(conn, KEY, str(canopy_env.root), "repo", pr_url=PR)
    observe_pr(conn)
    conn.commit()
    return conn


def test_a_workers_comment_after_the_cursor_is_passed(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    first = comment(observed, "c1", "acc-1", FRESH, MARKED, source="worker")
    second = comment(observed, "c2", "acc-1", FRESH, MARKED, source="worker")
    observed.commit()
    assert moves(canopy_env) == [
        harness_cursors.Move(KEY, None, "comment", None, second, ("worker comment c1", "worker comment c2")),
    ]
    assert first < second


def test_a_persons_comment_after_a_workers_stops_the_move_at_the_workers(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    worker = comment(observed, "c1", "acc-1", FRESH, MARKED, source="worker")
    comment(observed, "c2", "acc-1", FRESH, "Please also retry on 503.")
    comment(observed, "c3", "acc-1", FRESH, MARKED, source="worker")
    observed.commit()
    assert moves(canopy_env) == [harness_cursors.Move(KEY, None, "comment", None, worker, ("worker comment c1",))]
    # Once the person's comment is handled, the worker's after it is passed.
    observed.execute("UPDATE tickets SET comment_cursor = ? WHERE key = ?", (worker + 1, KEY))
    observed.commit()
    [after] = moves(canopy_env)
    assert (after.before, after.passed) == (worker + 1, ("worker comment c3",))


def test_a_cursor_with_an_item_that_needs_handling_after_it_stays(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    comment(observed, "c1", "acc-1", FRESH, "Please also retry on 503.")
    comment(observed, "c2", "acc-1", FRESH, MARKED, source="worker")
    review(observed, 1, "octocat", None, FRESH, "Rename it.", item="comment")
    review(observed, 2, "operator", None, FRESH, MARKED, item="comment")
    observed.commit()
    assert moves(canopy_env) == []


def test_a_review_runs_number_stops_the_review_cursor(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    passed = review(observed, 1, "operator", None, FRESH, MARKED, item="comment")
    # A canopy review run takes its number when it ends, between the two replies.
    tick_id = db.start_tick(observed, dry_run=False)
    run = observed.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, ticket_key, started_at, status, log_path) "
        "VALUES (?, ?, 'abc1234', ?, ?, 'running', 'x')",
        (tick_id, PR, KEY, FRESH),
    ).lastrowid
    assert run is not None
    assert db.finish_run(observed, "review_runs", run, ReviewRunStatus.DONE, None)
    review(observed, 2, "operator", None, FRESH, MARKED, item="comment")
    observed.commit()
    [move] = moves(canopy_env)
    assert (move.name, move.after, move.passed) == ("review", passed, ("worker review comment 1",))


def test_a_reply_the_operator_sent_and_the_review_it_went_in_are_passed(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    trusted = review(observed, 1, "octocat", None, FRESH, "Rename it.", item="comment")
    review(observed, 90, "operator", "commented", FRESH)
    sent = review(observed, 2, "operator", None, FRESH, "Renamed.", item="comment")
    sent_draft(canopy_env, observed, comment_id=2, review_id=90)
    observed.execute("UPDATE ticket_units SET review_cursor = ? WHERE ticket_key = ?", (trusted, KEY))
    observed.commit()
    assert moves(canopy_env) == [
        harness_cursors.Move(
            KEY,
            "repo",
            "review",
            trusted,
            sent,
            ("review 90 the operator sent", "review comment 2 the operator sent"),
        ),
    ]


def test_an_empty_review_holding_only_a_workers_reply_is_passed_and_one_holding_a_persons_is_not(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    # GitHub wraps a reply on a thread in a review of its own, with no body.
    review(observed, 90, "operator", "commented", FRESH)
    reply = review(observed, 1, "operator", None, FRESH, MARKED, item="comment")
    review(observed, 91, "octocat", "commented", FRESH)
    review(observed, 2, "octocat", None, FRESH, "Rename it.", item="comment")
    observed.execute("UPDATE observed_reviews SET review_id = 90 WHERE id = 1")
    observed.execute("UPDATE observed_reviews SET review_id = 91 WHERE id = 2")
    observed.commit()
    [move] = moves(canopy_env)
    assert (move.after, move.passed) == (reply, ("review 90, holding only those", "worker review comment 1"))


def test_a_private_tickets_cursors_move_as_a_public_ones(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    # What an item is does not hang on what authorizes the ticket's runs (DESIGN §22).
    assert operator("start", KEY) == 0
    comment(observed, "c1", "acc-1", FRESH, MARKED, source="worker")
    review(observed, 1, "operator", None, FRESH, MARKED, item="comment")
    observed.commit()
    assert [(m.name, m.passed) for m in moves(canopy_env)] == [
        ("comment", ("worker comment c1",)),
        ("review", ("worker review comment 1",)),
    ]


def test_a_stale_subject_keeps_its_cursor(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    comment(observed, "c1", "acc-1", FRESH, MARKED, source="worker")
    review(observed, 1, "operator", None, FRESH, MARKED, item="comment")
    observed.execute("UPDATE observed_tickets SET observed_at = ?", (OLD,))
    observed.execute("UPDATE observed_prs SET observed_at = ?", (OLD,))
    observed.commit()
    assert moves(canopy_env) == []


def test_a_cursor_is_never_moved_back(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    worker = comment(observed, "c1", "acc-1", FRESH, MARKED, source="worker")
    observed.commit()
    [move] = moves(canopy_env)
    # The overseer passed it further meanwhile: the move leaves the cursor, and records nothing.
    observed.execute("UPDATE tickets SET comment_cursor = ? WHERE key = ?", (worker + 5, KEY))
    observed.commit()
    with in_tick(observed) as tick_id:
        assert harness_cursors.record(observed, tick_id, [move]) == []
    assert db.decisions_for_tick(observed, tick_id) == []
    assert cursors(observed) == (worker + 5, None)
    # Past a cursor, the workers' comments before it are not moved to.
    assert moves(canopy_env) == []


def test_a_move_is_recorded_as_the_harnesss_and_decides_nothing_about_the_ticket(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    worker = comment(observed, "c1", "acc-1", FRESH, MARKED, source="worker")
    observed.commit()
    ctx = context(canopy_env)
    with in_tick(observed) as tick_id:
        assert harness_cursors.record(observed, tick_id, harness_cursors.moves(ctx, NOW)) != []
        phases.record(observed, tick_id, phases.derive(ctx, NOW))
    [decision] = db.decisions_for_tick(observed, tick_id)
    assert (decision.ticket_key, decision.action, decision.decider) == (KEY, harness.CURSOR_ACTION, Decider.HARNESS)
    assert decision.rationale == (
        f"comment cursor from unset to {worker}, past what needs no handling: worker comment c1"
    )
    assert cursors(observed) == (worker, None)
    # The ticket is still the overseer's: not the harness's decision, and still compared with the overseer's.
    assert harness.recorded(observed, tick_id) == []
    assert not harness.decided(observed, tick_id, KEY)
    assert [c.ticket_key for c in phases.compare(observed, tick_id)] == [KEY]


def test_a_tick_moves_the_review_cursor_past_a_workers_reply_and_shows_it(
    scenario: Scenario,
    github_state: Path,
) -> None:
    worked_pr(scenario, github_state)
    ticked = scenario.tick(*waits(KEY))
    assert ticked.tick.status == TickStatus.OK
    [moved] = [d for d in ticked.decisions if d.action == harness.CURSOR_ACTION]
    assert (moved.ticket_key, moved.repo, moved.decider) == (KEY, "repo", Decider.HARNESS)
    passed = int(review_number(scenario.conn, 501))
    assert moved.rationale == (
        f"review cursor in repo from unset to {passed}, past what needs no handling: review 101, holding only those, "
        "worker review comment 501"
    )
    assert cursors(scenario.conn) == (None, passed)
    # The block shows nothing past the cursor, and the overseer still decided the ticket.
    assert units(scenario)[0]["reviews"] == []
    assert [d.decider for d in ticked.decisions if d.ticket_key == KEY and d.action == "wait"] == [Decider.OVERSEER]
    assert "[harness] review cursor in repo from unset to" in scenario.operator("decisions").out
    # A person's comment after it needs handling: it stays new, and the cursor where it was.
    github_state.write_text(json.dumps({"prs": {PR: {"reviews": [*WORKED, review_comment(502, "octocat", "Why?")]}}}))
    later = scenario.tick(*waits(KEY))
    assert [d.action for d in later.decisions if d.action == harness.CURSOR_ACTION] == []
    assert cursors(scenario.conn) == (None, passed)
    assert [r["id"] for r in units(scenario)[0]["reviews"]] == [502]


def test_a_dry_run_moves_no_cursor(scenario: Scenario, github_state: Path) -> None:
    worked_pr(scenario, github_state)
    dry = scenario.tick(*waits(KEY), dry_run=True)
    assert [d.action for d in dry.decisions if d.action == harness.CURSOR_ACTION] == []
    assert cursors(scenario.conn) == (None, None)
    assert [r["id"] for r in units(scenario)[0]["reviews"]] == [101, 501]


#: A worker's reply on a review thread, as GitHub holds it: a review comment with the workers' marks, wrapped in an
#: empty review of its own.
WORKED = [
    {"item": "review", "id": 101, "author": "me", "state": "commented", "time": "2026-10-18T10:00:00Z", "body": ""},
    {
        "item": "comment",
        "id": 501,
        "author": "me",
        "time": "2026-10-18T10:00:00Z",
        "body": MARKED,
        "review": 101,
        "thread": {"id": "PRRT_1", "path": "src/app.py", "line": 12, "side": "right"},
    },
]


def moves(env: CanopyEnv) -> list[harness_cursors.Move]:
    """The cursors the harness would move over `env`'s journal at NOW."""
    return harness_cursors.moves(context(env), NOW)


def cursors(conn: sqlite3.Connection) -> tuple[int | None, int | None]:
    """KEY's `comment` cursor and its unit's `review` cursor."""
    comment_cursor = conn.execute("SELECT comment_cursor FROM tickets WHERE key = ?", (KEY,)).fetchone()[0]
    review_cursor = conn.execute("SELECT review_cursor FROM ticket_units WHERE ticket_key = ?", (KEY,)).fetchone()[0]
    return comment_cursor, review_cursor


def worked_pr(scenario: Scenario, github_state: Path) -> None:
    """KEY seen, with no tracker source, its unit's PR on the fake GitHub holding a worker's reply, `WORKED`."""
    scenario.seen(KEY)
    db.set_unit(scenario.conn, KEY, str(scenario.env.root), "repo", pr_url=PR)
    scenario.conn.commit()
    github_state.write_text(json.dumps({"prs": {PR: {"reviews": WORKED}}}))


def review_comment(ident: int, author: str, body: str) -> dict[str, object]:
    """A person's review comment on a thread of its own, as the fake GitHub holds it."""
    where = {"id": f"PRRT_{ident}", "path": "src/app.py", "line": 3, "side": "right"}
    return {"item": "comment", "id": ident, "author": author, "time": "2026-10-18T11:00:00Z", "body": body,
            "thread": where}  # fmt: skip


def units(scenario: Scenario) -> list[dict[str, Any]]:
    """KEY's units, as the latest overseer's state block observed them."""
    [ticket] = scenario.state()["observations"]["tickets"]
    found: list[dict[str, Any]] = ticket["units"]
    return found
