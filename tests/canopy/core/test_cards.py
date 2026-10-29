"""A running agent's card: what a `status` call says, and how a run's row keeps it (DESIGN §41)."""

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from canopy.core import cards, db
from canopy.core.vocab import RunStatus
from canopy.runtime.report import Called
from tests.canopy.helpers import plan_run, present

CARD: dict[str, object] = {
    "summary": "Fixing the parser;\nthe tests pass.",
    "now": "  writing\tthe PR body ",
    "done": [{"step": "fix the parser", "proof": "tests pass: 42/42"}],
    "next": ["open the PR", "answer the review"],
}


def status(card: object, *, completed: bool = True, tool: str = "canopy_run_status") -> Called:
    """A `status` call as the agent's events print it."""
    return Called(tool, completed=completed, input=card if isinstance(card, dict) else {})


def test_a_card_is_plain_lines_held_to_its_bounds() -> None:
    card = cards.Card.model_validate(CARD)
    assert (card.summary, card.now, card.stuck) == ("Fixing the parser; the tests pass.", "writing the PR body", None)
    assert card.done == (cards.Done(step="fix the parser", proof="tests pass: 42/42"),)
    for wrong in (
        {"summary": "s"},  # no `now`
        {**CARD, "now": " \n "},  # nothing printable
        {**CARD, "now": "x" * (cards.MAX_LINE + 1)},
        {**CARD, "summary": "x" * (cards.MAX_SUMMARY + 1)},
        {**CARD, "next": ["n"] * (cards.MAX_STEPS + 1)},
        {**CARD, "done": [{"step": "s"}]},  # no proof
        {**CARD, "stuck": 3},
        {**CARD, "mood": "fine"},
    ):
        with pytest.raises(ValidationError):
            cards.Card.model_validate(wrong)


def test_only_a_completed_status_call_that_validates_is_a_card() -> None:
    assert cards.tool_name() == "canopy_run_status"
    assert cards.read_call(status(CARD)) == cards.Card.model_validate(CARD)
    assert cards.read_call(status(CARD, completed=False)) is None  # the server refused it
    assert cards.read_call(status({"summary": "s"})) is None
    assert cards.read_call(status(CARD, tool="other_status")) is None


@pytest.fixture
def running(conn: sqlite3.Connection, tmp_path: Path) -> int:
    """A running run of PROJ-1."""
    return plan_run(conn, tmp_path)


def test_a_running_run_counts_its_tool_calls_and_keeps_its_latest_card(conn: sqlite3.Connection, running: int) -> None:
    standing = cards.of(present(db.get_run(conn, running)))
    assert standing == cards.Standing(None, None, 0)
    cards.record_call(conn, "runs", running, None)
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    later = cards.Card.model_validate({**CARD, "now": "opening the PR"})
    cards.record_call(conn, "runs", running, later)
    cards.record_call(conn, "runs", running, None)
    standing = cards.of(present(db.get_run(conn, running)))
    assert (standing.card, standing.calls_since) == (later, 1)
    assert standing.at is not None

    # Once the run ends, it keeps its card, and nothing more is counted.
    db.finish_run(conn, "runs", running, RunStatus.DONE, "{}")
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    assert cards.of(present(db.get_run(conn, running))) == standing


def test_a_card_the_journal_holds_that_no_longer_reads_as_one_is_none(conn: sqlite3.Connection, running: int) -> None:
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    conn.execute('UPDATE runs SET card_json = \'{"summary": "s"}\' WHERE id = ?', (running,))
    assert cards.of(present(db.get_run(conn, running))) == cards.Standing(None, None, 1)


def test_a_card_gone_too_many_tool_calls_without_an_update_is_stale(conn: sqlite3.Connection, running: int) -> None:
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    for _ in range(cards.STALE_CALLS - 1):
        cards.record_call(conn, "runs", running, None)
    run = present(db.get_run(conn, running))
    started = str(run["started_at"])
    assert not cards.is_stale(cards.of(run), started)
    cards.record_call(conn, "runs", running, None)
    standing = cards.of(present(db.get_run(conn, running)))
    assert cards.is_stale(standing, started)
    doing = cards.doing(standing, started)
    assert doing is not None
    assert doing.endswith(f", {cards.STALE_CALLS} calls old  stale")
