"""A running agent's card: what a `status` call says, and how a run's row keeps it (DESIGN §41)."""

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest import mock

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
#: A fifth of the worker's default timeout, 45 minutes.
STUCK = cards.stuck_after(45)


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
    cards.record_call(conn, "runs", running, None, stuck_after=STUCK)
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD), stuck_after=STUCK)
    later = cards.Card.model_validate({**CARD, "now": "opening the PR"})
    cards.record_call(conn, "runs", running, later, stuck_after=STUCK)
    cards.record_call(conn, "runs", running, None, stuck_after=STUCK)
    standing = cards.of(present(db.get_run(conn, running)))
    assert (standing.card, standing.calls_since) == (later, 1)
    assert standing.at is not None

    # Once the run ends, it keeps its card, and nothing more is counted.
    db.finish_run(conn, "runs", running, RunStatus.DONE, "{}")
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD), stuck_after=STUCK)
    assert cards.of(present(db.get_run(conn, running))) == standing


def test_a_card_the_journal_holds_that_no_longer_reads_as_one_is_none(conn: sqlite3.Connection, running: int) -> None:
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD), stuck_after=STUCK)
    conn.execute('UPDATE runs SET card_json = \'{"summary": "s"}\' WHERE id = ?', (running,))
    assert cards.of(present(db.get_run(conn, running))) == cards.Standing(None, None, 1)


def steps(*said: tuple[str, ...]) -> dict[str, object]:
    """A card whose steps are `said`, each a title and a status, and a stage when it names one."""
    return {**CARD, "steps": [dict(zip(("title", "status", "stage"), step, strict=False)) for step in said]}


def test_a_card_may_carry_steps_each_with_a_status_and_a_stage_held_to_their_bounds() -> None:
    card = cards.Card.model_validate(steps(("read the\nparser", "done", " code "), ("fix it", "working")))
    assert card.steps == (
        cards.Step(title="read the parser", status="done", stage="code"),
        cards.Step(title="fix it", status="working"),
    )
    assert cards.Card.model_validate(CARD).steps == ()
    for wrong in (
        steps(("fix it", "in_progress")),  # todowrite's word, not the card's
        steps(("fix it", "working", "x" * (cards.MAX_STAGE + 1))),
        steps(("x" * (cards.MAX_LINE + 1), "working")),
        steps((" ", "working")),
        steps(*[("step", "not_started")] * (cards.MAX_STEPS + 1)),
        {**CARD, "steps": [{"title": "fix it", "status": "done", "eta": "5m"}]},
        {**CARD, "steps": [{"status": "done"}]},
    ):
        with pytest.raises(ValidationError):
            cards.Card.model_validate(wrong)


def test_percent_done_counts_the_done_and_skipped_steps_rounded_down_and_the_first_working_one_is_worked_on() -> None:
    card = cards.Card.model_validate(
        steps(
            ("read", "done"),
            ("ask", "skipped"),
            ("fix", "working", "code"),
            ("test", "working", "tests"),
            ("wait", "blocked"),
            ("push", "not_started"),
        ),
    )
    assert cards.percent_done(card) == 33  # 2 of 6
    assert cards.working(card) == cards.Step(title="fix", status="working", stage="code")
    assert cards.percent_done(cards.Card.model_validate(steps(("read", "done"), ("ask", "skipped")))) == 100
    assert cards.percent_done(cards.Card.model_validate(steps(("read", "not_started")))) == 0
    no_steps = cards.Card.model_validate(CARD)
    assert (cards.percent_done(no_steps), cards.working(no_steps)) == (None, None)


def minute(m: int) -> str:
    """The journal's time `m` minutes past 10:00."""
    return f"2026-10-29T10:{m:02d}:00.000Z"


@contextmanager
def at_minute(m: int) -> Iterator[None]:
    """Until the block ends, the journal's time is `m` minutes past 10:00."""
    with mock.patch.object(db, "now", autospec=True, return_value=minute(m)):
        yield


def recorded(conn: sqlite3.Connection, run: int, m: int, card: Mapping[str, object]) -> cards.Standing:
    """Record `card` on `run` at minute `m`, and read back where it stands."""
    with at_minute(m):
        cards.record_call(conn, "runs", run, cards.Card.model_validate(card), stuck_after=STUCK)
    return cards.of(present(db.get_run(conn, run)))


def times(standing: cards.Standing) -> list[tuple[str, str | None]]:
    """When each step of a card last changed, and when it is stuck, as the journal formats them."""
    return [
        (db.format_time(t.since), None if t.stuck_at is None else db.format_time(t.stuck_at)) for t in standing.steps
    ]


def stuck_titles(standing: cards.Standing, m: int) -> list[str]:
    """The titles of the card's steps stuck at minute `m`."""
    return [step.title for step, _ in cards.stuck(standing, db.parse_time(minute(m)))]


def test_a_step_keeps_its_time_until_its_status_or_stage_changes_and_working_a_fifth_of_the_timeout_is_stuck(
    conn: sqlite3.Connection,
    running: int,
) -> None:
    assert timedelta(minutes=9) == STUCK
    first = recorded(conn, running, 0, steps(("read", "done"), ("fix", "working", "code"), ("push", "not_started")))
    assert times(first) == [(minute(0), None), (minute(0), minute(9)), (minute(0), None)]

    # Each step is found by its title wherever it moved, and only `push`, which started, starts anew.
    second = recorded(conn, running, 5, steps(("fix", "working", "code"), ("push", "working"), ("read", "done")))
    assert times(second) == [(minute(0), minute(9)), (minute(5), minute(14)), (minute(0), None)]
    assert stuck_titles(second, 8) == []
    assert stuck_titles(second, 9) == ["fix"]
    assert stuck_titles(second, 14) == ["fix", "push"]

    # A new stage is a change, so `fix` starts anew; a step done is never stuck.
    third = recorded(conn, running, 10, steps(("fix", "working", "tests"), ("push", "done"), ("read", "done")))
    assert times(third) == [(minute(10), minute(19)), (minute(10), None), (minute(0), None)]
    assert stuck_titles(third, 18) == []

    # A card that drops its steps drops their times, and a card whose times the journal lost has none stuck.
    assert recorded(conn, running, 11, CARD).steps == ()
    again = recorded(conn, running, 12, steps(("fix", "working")))
    conn.execute("UPDATE runs SET card_steps_json = '[]' WHERE id = ?", (running,))
    assert again.steps
    assert stuck_titles(cards.of(present(db.get_run(conn, running))), 59) == []


def test_status_and_show_say_how_far_the_steps_are_and_which_is_stuck(conn: sqlite3.Connection, running: int) -> None:
    card = steps(("read", "done"), ("ask", "skipped"), ("fix", "working", "code"), ("push", "not_started"))
    standing = recorded(conn, running, 0, card)
    started = minute(0)
    fresh, late = db.parse_time(minute(3)), db.parse_time(minute(12))
    said = "now: writing the PR body  card 3m, 0 calls old  steps 50% of 4, stage code"
    assert cards.doing(standing, started, fresh) == said
    assert str(cards.doing(standing, started, late)).endswith("old  stale  steps 50% of 4, stage code, 1 stuck")
    shown = cards.lines(standing, started_at=started, running=True, now=late)
    assert shown[3:8] == [
        "    steps: 2 of 4 finished, 50%; stage code",
        "    step done: read",
        "    step skipped: ask",
        "    step working (code): fix  stuck 12m",
        "    step not_started: push",
    ]
    # Once the run ended, no step is stuck.
    assert "    step working (code): fix" in cards.lines(standing, started_at=started, running=False, now=late)
