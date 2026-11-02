"""Feedback a `review` cursor passed with no worker, and what is still left of it (DESIGN §7).

Over a journal written by hand: what `left` reads, until a resolve, an answer on its thread, or a read that no longer
sees the item ends it, how `canopy show` lists it to the operator, and how `canopy send` overrules the call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from canopy.core import db, passed_reviews, records
from canopy.core.vocab import PassReason
from canopy.runs import drafts
from tests.canopy.helpers import KEY, context, operator
from tests.canopy.observation_helpers import FRESH, PR, TRACKER, held, observe_pr, passed_over, review

if TYPE_CHECKING:
    import sqlite3

    from tests.conftest import CanopyEnv


@pytest.fixture
def observed(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> sqlite3.Connection:
    """KEY held, its unit in `repo` with PR observed open.

    Returns the journal.
    """
    canopy_env.configure(canopy_env.user_file, TRACKER)
    held(canopy_env, conn, KEY)
    db.set_unit(conn, KEY, str(canopy_env.root), "repo", pr_url=PR)
    observe_pr(conn)
    return conn


def left(env: CanopyEnv) -> list[tuple[int, str]]:
    """KEY's feedback still left with no worker: each item's id and reason."""
    ctx = context(env)
    found = passed_reviews.left(ctx.conn, ctx.config.trust, drafts.sent_by_pr(ctx.conn), [KEY])
    return [(p.id, p.reason.value) for p in found.get(KEY, [])]


def test_feedback_passed_over_is_left_until_answered_resolved_or_gone(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    for ident in (1, 2, 3, 4):
        review(observed, ident, "carol", None, FRESH, "A nit.", item="comment", thread=f"T{ident}")
        passed_over(observed, ident, PassReason.QUESTION if ident == 4 else PassReason.OPTIONAL)
    observed.commit()
    assert left(canopy_env) == [(1, "optional"), (2, "optional"), (3, "optional"), (4, "question")]
    # A worker answers the first on its thread; a person's reply there is no answer.
    review(observed, 5, "operator", None, FRESH, "CANOPY: Done.", item="comment", thread="T1")
    review(observed, 6, "carol", None, FRESH, "Any news?", item="comment", thread="T2")
    observed.execute("UPDATE observed_reviews SET resolved = 1 WHERE id = 3")
    observed.execute("DELETE FROM observed_reviews WHERE id = 4")
    observed.commit()
    assert left(canopy_env) == [(2, "optional")]


def test_a_forget_drops_what_was_left_on_the_prs_it_drops(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    review(observed, 1, "carol", None, FRESH, "A nit.", item="comment")
    passed_over(observed, 1)
    observed.commit()
    assert left(canopy_env) == [(1, "optional")]
    assert operator("forget", KEY) == 0
    assert left(canopy_env) == []


def test_show_lists_what_is_left_with_why_and_the_tick(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    review(observed, 4443461025, "mgilson", None, FRESH, "No action required.", item="comment")
    observed.execute("UPDATE observed_reviews SET path = 's3_backfill.py', line = 378")
    tick_id = passed_over(observed, 4443461025, PassReason.WOULD_RESET_APPROVAL)
    observed.commit()
    capsys.readouterr()
    assert operator("show", KEY) == 0
    out = capsys.readouterr().out
    assert "Feedback left with no worker (1): unanswered, on threads not resolved" in out
    assert (
        "  repo  comment 4443461025 (number 1) by mgilson at s3_backfill.py:378: would_reset_approval, "
        f"by the overseer in tick {tick_id}\n    {PR}#review-4443461025\n"
    ) in out


def test_send_writes_the_operators_go_ahead_naming_what_was_left(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nit = review(observed, 4443461025, "mgilson", None, FRESH, "Could also use chain().", item="comment")
    observed.execute("UPDATE observed_reviews SET path = 's3_backfill.py', line = 384")
    passed_over(observed, 4443461025)
    observed.commit()
    capsys.readouterr()
    assert operator("send", KEY, str(nit)) == 0
    assert "the next tick reads it as your go-ahead" in capsys.readouterr().out
    [message] = records.select(records.Message).where("subject_id = ?", KEY).all(observed)
    assert message.body == (
        f"Address this review item, which the loop left with no worker: review comment 4443461025 by mgilson on {PR} "
        "at s3_backfill.py:384 (left as optional)."
    )
    assert "chain()" not in message.body
    # Sent again, the same reply is not recorded twice.
    assert operator("send", KEY, str(nit)) == 0
    assert "already went to it" in capsys.readouterr().out


def test_send_refuses_a_number_of_nothing_left(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    review(observed, 1, "carol", None, FRESH, "A nit.", item="comment", resolved=True)
    passed_over(observed, 1, PassReason.RESOLVED)
    observed.commit()
    assert operator("send", KEY, "1") != 0
    err = capsys.readouterr().err
    assert f"send refused (bad_reference): {KEY} has no feedback left with no worker numbered 1" in err
