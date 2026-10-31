"""A running agent's card: what a `status` call says, and how a run's row keeps it (DESIGN §41)."""

import functools
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from canopy.core import cards, conversation, db, records, review_runs
from canopy.core.vocab import ReviewRunStatus, RunStatus
from canopy.runtime.report import Called
from tests.canopy.helpers import in_tick, plan_run, present

CARD: dict[str, object] = {
    "summary": "Fixing the parser;\nthe tests pass.",
    "now": "  writing\tthe PR body ",
    "done": [{"step": "fix the parser", "proof": "tests pass: 42/42"}],
    "next": ["open the PR", "answer the review"],
}
#: A time long before the test runs.
OLD = "2026-01-01T00:00:00.000Z"


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


def test_a_lone_line_for_next_is_a_list_of_one() -> None:
    assert cards.Card.model_validate({**CARD, "next": " open\tthe PR "}).next == ("open the PR",)
    assert cards.read_call(status({**CARD, "next": "open the PR"})) == cards.Card.model_validate(
        {**CARD, "next": ["open the PR"]},
    )
    with pytest.raises(ValidationError):
        cards.Card.model_validate({**CARD, "next": " \n "})


def test_only_a_completed_status_call_that_validates_is_a_card() -> None:
    assert cards.tool_name() == "canopy_run_status"
    assert cards.read_call(status(CARD)) == cards.Card.model_validate(CARD)
    assert cards.read_call(status(CARD, completed=False)) is None  # the server refused it
    assert cards.read_call(status({"summary": "s"})) is None
    assert cards.read_call(status(CARD, tool="other_status")) is None


def test_a_tasks_run_keeps_a_card_but_asks_no_question_on_it(tmp_path: Path) -> None:
    """Its card is read as any run's, but one that asks a question is not; nor has it an answers directory (§36)."""
    asking = {**CARD, "question": {"ask": "Which?", "options": ["a", "b"], "recommend": "A"}}
    assert cards.read_call(status(asking)) is not None
    assert cards.read_call(status(asking), may_ask=False) is None
    assert cards.read_call(status(CARD), may_ask=False) == cards.Card.model_validate(CARD)
    assert [bool(cards.RUN_ID_RE.fullmatch(r)) for r in ("7", "review-7", "task-7", "chore-7")] == [
        True,
        True,
        True,
        False,
    ]
    assert [cards.may_ask(r) for r in ("7", "review-7", "task-7", "chore-7")] == [True, True, False, False]
    with pytest.raises(ValueError, match="names no run whose card may ask"):
        cards.answers_dir(tmp_path, "task-7")


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


def steps(*statuses: str) -> list[dict[str, object]]:
    """A card's steps, one per status, each titled by its place and staged by the half it is in."""
    return [
        {"title": f"step {n}", "status": status, "stage": "first" if n <= len(statuses) // 2 else "second"}
        for n, status in enumerate(statuses, 1)
    ]


def test_a_cards_steps_say_how_much_is_done_and_the_working_ones_stage() -> None:
    card = cards.Card.model_validate({**CARD, "steps": steps("done", "skipped", "working", "not_started", "blocked")})
    assert (cards.percent(card), cards.working_stage(card)) == (25, "second")  # 1 of the 4 not skipped
    assert cards.percent(cards.Card.model_validate(CARD)) is None
    assert cards.percent(cards.Card.model_validate({**CARD, "steps": steps("skipped")})) is None
    with pytest.raises(ValidationError):
        cards.Card.model_validate({**CARD, "steps": [{"title": "t", "status": "started"}]})
    with pytest.raises(ValidationError):
        cards.Card.model_validate({**CARD, "steps": steps(*["done"] * (cards.MAX_PLAN_STEPS + 1))})


def test_a_working_step_keeps_when_it_started_working_and_is_stuck_past_the_runs_last_fifth(
    conn: sqlite3.Connection,
    running: int,
) -> None:
    def card(*statuses: str) -> cards.Card:
        return cards.Card.model_validate({**CARD, "steps": steps(*statuses)})

    cards.record_call(conn, "runs", running, card("working", "not_started"))
    first = cards.of(present(db.get_run(conn, running)))
    started = first.working_since["step 1"]
    # Still working on the next card, it keeps its start; the step that starts working now starts now.
    conn.execute("UPDATE runs SET card_working_since = json_set(card_working_since, '$.\"step 1\"', ?)", (OLD,))
    cards.record_call(conn, "runs", running, card("working", "working"))
    later = cards.of(present(db.get_run(conn, running)))
    assert later.working_since["step 1"] == db.parse_time(OLD)
    assert later.working_since["step 2"] >= started
    # Past the last fifth of a 45-minute run, 9 minutes, it is shown stuck; the other is not yet.
    shown = cards.lines(later, started_at=OLD, running=True, timeout_minutes=45, ref="run:1")
    assert shown[-3:] == [
        "    steps:  0% done, stage first",
        "      [>] step 1 (first)  stuck",
        "      [>] step 2 (second)",
    ]
    assert cards.stuck_at(later, "step 1", 45) == db.parse_time(OLD) + timedelta(minutes=9)
    assert cards.stuck_at(later, "step 9", 45) is None
    # A step done, then working again, starts again; a card with none working keeps no times.
    cards.record_call(conn, "runs", running, card("done", "working"))
    assert "step 1" not in cards.of(present(db.get_run(conn, running))).working_since
    cards.record_call(conn, "runs", running, card("done", "done"))
    assert present(db.get_run(conn, running))["card_working_since"] is None


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
    assert doing.endswith(f"  no update in {cards.STALE_CALLS} tool calls")


def lapses(conn: sqlite3.Connection, run_id: int) -> tuple[int, bool]:
    """How many times run `run_id`'s card has lapsed, and whether it stands counted stale."""
    run = present(records.select(records.Run).where("id = ?", run_id).one(conn))
    return run.card_lapses, run.card_stale


def calls(conn: sqlite3.Connection, run_id: int, count: int) -> None:
    """Run `run_id` ends `count` tool calls that are not `status` calls."""
    for _ in range(count):
        cards.record_call(conn, "runs", run_id, None)


def test_a_card_gone_stale_lapses_once_however_many_calls_find_it_so(conn: sqlite3.Connection, running: int) -> None:
    """The lapse is the change from fresh to stale; a new card is fresh again, and its own lapse counts anew."""
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    calls(conn, running, cards.STALE_CALLS - 1)
    assert lapses(conn, running) == (0, False)
    calls(conn, running, 1)
    assert lapses(conn, running) == (1, True)
    calls(conn, running, 5)
    assert lapses(conn, running) == (1, True)
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    assert lapses(conn, running) == (1, False)
    calls(conn, running, cards.STALE_CALLS)
    assert lapses(conn, running) == (2, True)
    # Once the run ends, nothing more is counted.
    db.finish_run(conn, "runs", running, RunStatus.DONE, "{}")
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    assert lapses(conn, running) == (2, True)


def test_a_run_with_no_card_yet_lapses_once_by_its_calls_or_its_minutes(
    conn: sqlite3.Connection,
    running: int,
    tmp_path: Path,
) -> None:
    """It counts from its start, and its first card, late, ends a lapse already counted."""
    calls(conn, running, cards.STALE_CALLS)
    assert lapses(conn, running) == (1, True)
    calls(conn, running, 3)
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    assert lapses(conn, running) == (1, False)
    # A run gone quiet past the minutes lapses at the first call that finds it so.
    quiet = plan_run(conn, tmp_path, key="PROJ-2")
    records.update(records.Run).set(started_at=OLD).where("id = ?", quiet).run(conn)
    calls(conn, quiet, 1)
    assert lapses(conn, quiet) == (1, True)


def test_an_update_that_comes_too_late_counts_the_lapse_it_ends(conn: sqlite3.Connection, running: int) -> None:
    """A card gone past the minutes with no call between is stale when its update arrives: one lapse, then fresh."""
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    records.update(records.Run).set(card_at=OLD).where("id = ?", running).run(conn)
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    assert lapses(conn, running) == (1, False)
    # The update that is the stale-making call itself is in time.
    calls(conn, running, cards.STALE_CALLS - 1)
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    assert lapses(conn, running) == (1, False)


QUESTION: dict[str, object] = {
    "ask": "Keep the old endpoint for the mobile app, or remove it?",
    "options": ["keep it, deprecated", "remove it now"],
    "recommend": "A",
}


def test_a_question_offers_two_to_five_options_and_recommends_one_of_them() -> None:
    card = cards.Card.model_validate({**CARD, "question": QUESTION})
    assert card.question is not None
    assert (card.question.option("B"), card.question.option("C")) == ("remove it now", None)
    for wrong in (
        {**QUESTION, "options": ["only one"]},
        {**QUESTION, "options": ["o"] * (len(cards.LETTERS) + 1)},
        {**QUESTION, "recommend": "C"},  # names no option
        {**QUESTION, "recommend": "a"},
        {**QUESTION, "ask": " "},
        {**QUESTION, "why": "because"},
    ):
        with pytest.raises(ValidationError):
            cards.Card.model_validate({**CARD, "question": wrong})


def test_a_question_keeps_when_it_was_asked_and_its_answer_while_the_cards_after_it_ask_it(
    conn: sqlite3.Connection,
    running: int,
) -> None:
    def standing() -> cards.Standing:
        return cards.of(present(db.get_run(conn, running)))

    cards.record_call(conn, "runs", running, cards.Card.model_validate({**CARD, "question": QUESTION}))
    asked = standing().asked_at
    assert asked is not None
    assert (standing().answer, standing().answered_at) == (None, None)
    assert cards.record_answer(conn, "runs", running, "B", asked)
    assert standing().answer == "B"
    # Asked again, with the rest of the card changed, it keeps both.
    cards.record_call(conn, "runs", running, cards.Card.model_validate({**CARD, "now": "x", "question": QUESTION}))
    assert (standing().asked_at, standing().answer) == (asked, "B")
    # An answer to the question as asked at another time is not recorded.
    assert not cards.record_answer(conn, "runs", running, "A", asked + timedelta(seconds=1))
    # Another question starts over, with no answer; a card that asks none clears it.
    other = {**QUESTION, "options": ["keep it", "remove it", "ask the mobile team"]}
    cards.record_call(conn, "runs", running, cards.Card.model_validate({**CARD, "question": other}))
    assert standing().asked_at is not None
    assert standing().answer is None
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    assert (standing().asked_at, standing().answer) == (None, None)
    assert present(db.get_run(conn, running))["card_asked_at"] is None


def test_an_answer_reaches_the_agent_in_the_transaction_that_records_it(
    conn: sqlite3.Connection,
    running: int,
    tmp_path: Path,
) -> None:
    """Two answers at once reach the agent in the order the journal recorded them, so it hears the one kept."""
    cards.record_call(conn, "runs", running, cards.Card.model_validate({**CARD, "question": QUESTION}))
    answers = cards.answers_dir(tmp_path, str(running))
    cards.make_answers(answers)
    held: list[bool] = []

    def deliver(path: Path, answered: cards.Answered) -> bool:
        held.append(conn.in_transaction)
        return real(path, answered)

    real = cards.deliver
    with mock.patch.object(cards, "deliver", autospec=True, side_effect=deliver):
        conversation.answer(conn, conversation.parse_ref(f"run:{running}"), "B", state_dir=tmp_path)
    assert held == [True]
    assert json.loads((answers / cards.ANSWER_FILE).read_text())["letter"] == "B"


def test_answers_delivered_at_once_from_two_threads_each_land_whole(tmp_path: Path) -> None:
    """Each thread stages its answer under a name of its own, so neither renames away the other's."""
    question = cards.Question.model_validate(QUESTION)
    asked = datetime(2026, 10, 8, 12, 24, tzinfo=UTC)
    cards.make_answers(tmp_path)
    picks = [cards.Answered(question, asked, ("A", "B")[i % 2], "x", already=False, heard=False) for i in range(200)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        heard = list(pool.map(functools.partial(cards.deliver, tmp_path), picks))
    assert all(heard)
    assert json.loads((tmp_path / cards.ANSWER_FILE).read_text())["letter"] in {"A", "B"}
    assert [p.name for p in tmp_path.iterdir()] == [cards.ANSWER_FILE]


def test_show_lists_a_questions_options_by_letter_and_says_how_to_answer_it(
    conn: sqlite3.Connection,
    running: int,
) -> None:
    cards.record_call(conn, "runs", running, cards.Card.model_validate({**CARD, "question": QUESTION}))
    standing = cards.of(present(db.get_run(conn, running)))
    shown = cards.lines(standing, started_at=OLD, running=True, timeout_minutes=45, ref="run:7")
    assert re.fullmatch(rf"    question, \d+s old: {re.escape(str(QUESTION['ask']))}", shown[-4])
    assert shown[-3] == "      A  keep it, deprecated  (recommended)"
    assert shown[-2:] == [
        "      B  remove it now",
        "      waiting on you: canopy reply run:7 LETTER",
    ]
    asking = cards.asking(standing, "run:7")
    assert asking is not None
    assert re.fullmatch(r"asks you, \d+s: .+\?  canopy reply run:7 A-B \(recommends A\)", asking)
    assert standing.asked_at is not None
    cards.record_answer(conn, "runs", running, "B", standing.asked_at)
    answered = cards.of(present(db.get_run(conn, running)))
    assert cards.lines(answered, started_at=OLD, running=True, timeout_minutes=45, ref="run:7")[-1].startswith(
        "      answered B, ",
    )
    assert cards.asking(answered, "run:7") is None
    db.finish_run(conn, "runs", running, RunStatus.DONE, "{}")
    ended = cards.lines(standing, started_at=OLD, running=False, timeout_minutes=45, ref="run:7")
    assert ended[-1] == "      run ended before an answer"


def test_a_running_runs_question_waits_on_the_operator_until_they_answer_or_the_run_ends(
    conn: sqlite3.Connection,
    running: int,
    tmp_path: Path,
) -> None:
    """Each running run's or review's question unanswered is an attention item, named by its run (DESIGN §41)."""
    with in_tick(conn) as tick_id:
        review = review_runs.insert_review_run(
            conn,
            tick_id=tick_id,
            pr_url="https://example.test/acme/repo/pull/9",
            sha="a" * 40,
            ticket=None,
            repo=None,
            purpose="request",
            logs_dir=tmp_path,
        )
    assert cards.questions(conn) == []
    # A card that asks nothing raises none.
    cards.record_call(conn, "runs", running, cards.Card.model_validate(CARD))
    assert cards.questions(conn) == []
    for table, run_id in (("runs", running), ("review_runs", review)):
        cards.record_call(conn, table, run_id, cards.Card.model_validate({**CARD, "question": QUESTION}))
    asked = cards.of(present(db.get_run(conn, running))).asked_at
    assert asked is not None
    [run_item, review_item] = cards.questions(conn)
    assert (run_item.ticket_key, run_item.reason) == (f"run:{running}", "run_question")
    assert run_item.since == db.format_time(asked)
    assert run_item.detail == (
        f"run:{running} (implement, PROJ-1) asks you, recommends A: {QUESTION['ask']}; "
        f"answer with `canopy reply run:{running} LETTER`"
    )
    assert review_item.ticket_key == f"review:{review}"
    assert review_item.detail.startswith(f"review:{review} (of https://example.test/acme/repo/pull/9) asks you, ")
    # Answered, it waits on no one; the review's ends with its run.
    assert cards.record_answer(conn, "runs", running, "B", asked)
    assert db.finish_run(conn, "review_runs", review, ReviewRunStatus.DONE, "{}")
    assert cards.questions(conn) == []
