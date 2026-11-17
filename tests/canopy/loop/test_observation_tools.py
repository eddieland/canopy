"""The overseer's read of a unit's review items' text (DESIGN §27, §30), through its tool, in a tick of its own.

Each case writes what the `vcs` source observed by hand and calls `canopy_review-items` as the overseer does; a read
records nothing, and neither does a refusal a guard makes, unlike a verb's: a read decides nothing about its ticket.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from canopy.core import db, overseer_runs
from canopy.core.vocab import Decider
from canopy.loop import observation_tools, tools
from tests.canopy.helpers import KEY, in_tick, operator, overseer_calls, reads_items
from tests.canopy.observation_helpers import PR, TRACKER, TRUST, held, observe_pr, observe_ticket, review

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from tests.canopy.helpers import Called
    from tests.conftest import CanopyEnv


#: What a ticket the journal has no record of is refused with: as the verbs say it, and nothing is recorded.
UNKNOWN = (
    "review-items refused (unknown): canopy has no record of PROJ-9: the tracker query did not return it, and the "
    "operator did not start it; name only tickets the state block lists"
)
#: What a number below 1 is refused with: the item, then the tuple left empty without it.
ZERO = (
    "numbers.0: Input should be greater than or equal to 1\n"
    "numbers: Tuple should have at least 1 item after validation, not 0"
)


@pytest.fixture
def observed(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> sqlite3.Connection:
    """KEY held and observed open with the queue label, its unit in `repo` at PR, observed open. Returns the journal."""
    canopy_env.configure(canopy_env.user_file, {**TRACKER, **TRUST})
    held(canopy_env, conn, KEY)
    observe_ticket(conn)
    db.set_unit(conn, KEY, str(canopy_env.root), "repo", pr_url=PR)
    observe_pr(conn)
    conn.commit()
    return conn


def test_it_reads_each_items_text_by_number_behind_the_cursor_too_and_records_nothing(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    handled = review(observed, 1, "octocat", "approved", "2026-10-20T09:00:00.000Z", "Looks fine.")
    db.set_unit(observed, KEY, str(canopy_env.root), "repo", cursors={"review": str(handled)})
    asked = review(observed, 2, "octocat", "changes_requested", "2026-10-20T11:00:00.000Z", "Rename the helper.")
    review(observed, 3, "stranger", None, "2026-10-20T11:10:00.000Z", "Why not a map?", item="comment")
    replied = review(observed, 4, "operator", None, "2026-10-20T11:20:00.000Z", "CANOPY: Renamed it.", item="comment")
    observed.commit()
    with in_tick(observed) as tick_id:
        # Each once, in journal order, whatever order and repeats the call names them in.
        said = overseer_calls(reads_items(KEY, replied, asked, handled, asked))
    assert not said.error, said.text
    note, found = said.text.split("\n\n", 1)
    assert note == observation_tools.DATA_NOTE
    assert json.loads(found) == {
        "key": KEY,
        "repo": "repo",
        "items": [
            {
                "number": handled,
                "item": "review",
                "id": 1,
                "author": "octocat",
                "trusted": True,
                "worker": False,
                "state": "approved",
                "at": "2026-10-20T09:00:00.000Z",
                "body": "Looks fine.",
            },
            {
                "number": asked,
                "item": "review",
                "id": 2,
                "author": "octocat",
                "trusted": True,
                "worker": False,
                "state": "changes_requested",
                "at": "2026-10-20T11:00:00.000Z",
                "body": "Rename the helper.",
            },
            {
                "number": replied,
                "item": "comment",
                "id": 4,
                "author": "operator",
                "trusted": False,
                "worker": True,
                "state": None,
                "at": "2026-10-20T11:20:00.000Z",
                "body": "CANOPY: Renamed it.",
            },
        ],
    }
    assert db.decisions_for_tick(observed, tick_id) == []


def test_a_number_of_no_item_on_the_units_pr_is_refused(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    asked = review(observed, 2, "octocat", "changes_requested", "2026-10-20T11:00:00.000Z", "Rename the helper.")
    # An item of another PR has a number too, which names nothing on this unit's.
    other = review(observed, 5, "octocat", "commented", "2026-10-20T11:00:00.000Z", "Here?", pr=f"{PR}1")
    observed.commit()
    with in_tick(observed) as tick_id:
        said = overseer_calls(reads_items(KEY, asked, other, 999))
    assert said.error
    assert said.text == (
        f"review-items refused (unobserved): {other}, 999 name no review item observed on {PR}; name the numbers the "
        f"state block shows in reviews[].number for {KEY} in repo"
    )
    # A read decides nothing about its ticket, so its refusal is not recorded as a decision (`loop.duties`).
    assert db.decisions_for_tick(observed, tick_id) == []


def test_a_ticket_the_harness_decided_this_tick_is_refused(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    """The block hid the ticket's text on purpose (DESIGN §37), so the read does not hand it back."""
    asked = review(observed, 2, "octocat", "changes_requested", "2026-10-20T11:00:00.000Z", "Rename the helper.")
    observed.commit()
    with in_tick(observed) as tick_id:
        db.record_decision(observed, tick_id, KEY, "wait", "its worker is running", decider=Decider.HARNESS)
        said = overseer_calls(reads_items(KEY, asked))
    assert said.error
    assert said.text == (
        "review-items refused (decided): the harness decided PROJ-1 this tick (the state block's `harness`); read "
        "nothing of it"
    )
    assert "Rename" not in said.text
    assert [d.action for d in db.decisions_for_tick(observed, tick_id)] == ["wait"]


def test_a_ticket_in_a_run_given_another_subject_is_refused(observed: sqlite3.Connection) -> None:
    """Run once per subject, a run's message holds its subject alone, so the read hands it no other's (DESIGN §40)."""
    asked = review(observed, 2, "octocat", "changes_requested", "2026-10-20T11:00:00.000Z", "Rename the helper.")
    observed.commit()
    with in_tick(observed) as tick_id:
        overseer_runs.start(observed, tick_id, subject="PROJ-2")
        observed.commit()
        said = overseer_calls(reads_items(KEY, asked))
    assert said.error
    assert said.text == "review-items refused (decided): this run is given PROJ-2 alone; read nothing of PROJ-1"
    assert db.decisions_for_tick(observed, tick_id) == []


def test_its_own_ticket_in_a_run_given_it_is_read(observed: sqlite3.Connection) -> None:
    """The run given the ticket reads its items as a run given the whole block does."""
    asked = review(observed, 2, "octocat", "changes_requested", "2026-10-20T11:00:00.000Z", "Rename the helper.")
    observed.commit()
    with in_tick(observed) as tick_id:
        overseer_runs.start(observed, tick_id, subject=KEY)
        observed.commit()
        said = overseer_calls(reads_items(KEY, asked))
    assert not said.error, said.text
    assert "Rename the helper." in said.text


def stopped(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The operator started KEY in canopy, then stopped it."""
    conn.commit()
    assert operator("start", KEY) == 0
    assert operator("stop", KEY) == 0


def done(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """KEY is marked done."""
    db.set_ticket(conn, KEY, str(env.root), done=True)


def unlabeled(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The tracker observes KEY without the queue label."""
    conn.execute("UPDATE observed_tickets SET labels = '[]' WHERE key = ?", (KEY,))


def closed(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The tracker observes KEY closed."""
    conn.execute("UPDATE observed_tickets SET state = 'closed' WHERE key = ?", (KEY,))


@pytest.mark.parametrize(
    ("hidden", "why"),
    [
        (stopped, "the operator stopped it"),
        (done, "it is marked done"),
        (unlabeled, "it carries no queue label"),
        (closed, "the tracker says it is closed"),
    ],
    ids=["stopped", "done", "unlabeled", "closed"],
)
def test_a_ticket_the_block_shows_no_text_of_is_refused(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    hidden: Callable[[CanopyEnv, sqlite3.Connection], None],
    why: str,
) -> None:
    """A non-candidate is listed by key alone (TRUST_MODEL T7), and a stopped or done ticket not at all.

    Read from the observation as the block reads it, so a tick whose derivation raised refuses the same.
    """
    asked = review(observed, 2, "octocat", "changes_requested", "2026-10-20T11:00:00.000Z", "Rename the helper.")
    hidden(canopy_env, observed)
    observed.commit()
    with in_tick(observed) as tick_id:
        said = overseer_calls(reads_items(KEY, asked))
    assert said.error
    assert said.text == f"review-items refused (unlisted): the state block shows none of {KEY}'s text this tick: {why}"
    assert "Rename" not in said.text
    assert db.decisions_for_tick(observed, tick_id) == []


@pytest.mark.parametrize(
    ("move", "refusal"),
    [
        (reads_items("PROJ 1", 1), f"key: invalid ticket key 'PROJ 1': must match {tools.KEY_RE.pattern}"),
        (reads_items("PROJ-9", 1), UNKNOWN),
        (reads_items(KEY, 1, repo="nope"), "'nope' is not a repository in this workspace (repo)"),
        (reads_items("PROJ-2", 1), "PROJ-2 has no unit in repo: it has no unit yet"),
        (reads_items("PROJ-3", 1), "PROJ-3 in repo has no PR yet, so no review item to read"),
        (reads_items(KEY), "numbers: Tuple should have at least 1 item after validation, not 0"),
        (reads_items(KEY, 0), ZERO),
        (reads_items(KEY, *range(1, 22)), "numbers: Tuple should have at most 20 items after validation, not 21"),
    ],
    ids=["bad-key", "unknown", "no-such-repo", "no-unit", "no-pr", "no-numbers", "zero", "too-many"],
)
def test_a_read_of_no_unit_pr_or_item_is_refused(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    move: Called,
    refusal: str,
) -> None:
    held(canopy_env, observed, "PROJ-2")
    held(canopy_env, observed, "PROJ-3")
    db.set_unit(observed, "PROJ-3", str(canopy_env.root), "repo")
    observed.commit()
    with in_tick(observed) as tick_id:
        said = overseer_calls(move)
    assert said.error
    assert said.text == refusal
    assert db.decisions_for_tick(observed, tick_id) == []


def test_a_read_outside_a_tick_is_refused(canopy_env: CanopyEnv) -> None:
    said = overseer_calls(reads_items(KEY, 1))
    assert said.error
    assert said.text == "no tick is running (CANOPY_TICK_ID is not set); the overseer's verbs run only inside one"
