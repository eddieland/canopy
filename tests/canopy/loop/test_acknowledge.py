"""A tick's note on a ticket (DESIGN §22, Messages): what the first `ok` tick to read the operator's messages did.

The operator's message is never the last word in the conversation for want of a run: the tick that reads it says, in
canopy's words, what it decided about the ticket.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import conversation, db, records
from canopy.core.vocab import Decider, RunKind
from canopy.loop import acknowledge
from tests.canopy.helpers import KEY, present, raises, waits
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    import sqlite3

    from tests.canopy.scenario_helpers import Scenario


def conversation_of(conn: sqlite3.Connection, key: str = KEY) -> list[tuple[str, str, str, int | None]]:
    """Each message on `key`, oldest first: who wrote it, what it is, its body, and the message it answers."""
    return [
        (str(m.source), str(m.kind), str(m.body), m.answers)
        for m in db.messages_of(conn, conversation.TICKET, key, 100)
    ]


def newest_operator_message(conn: sqlite3.Connection) -> int:
    """The id of the newest message the operator wrote."""
    return db.latest_message_id(conn, source="operator")


def test_a_tick_that_waits_on_a_reply_says_so_under_it(scenario: Scenario) -> None:
    scenario.seen()
    scenario.operator("reply", KEY, "Use the v2 client.")
    message = newest_operator_message(scenario.conn)
    ticked = scenario.tick(*waits(KEY, rationale="CI is still running on the PR."))
    assert conversation_of(scenario.conn) == [
        ("operator", "reply", "Use the v2 client.", None),
        (
            "canopy",
            "note",
            f"Tick {ticked.tick.id} read message {message}: waiting: CI is still running on the PR.",
            message,
        ),
    ]
    # The next tick read nothing new from the operator, so it says nothing.
    scenario.tick(*waits(KEY))
    assert len(conversation_of(scenario.conn)) == 2


def test_a_tick_that_dispatches_names_the_run_it_started(scenario: Scenario) -> None:
    scenario.seen()
    scenario.operator("reply", KEY, "Go ahead.")
    message = newest_operator_message(scenario.conn)
    ticked = scenario.tick(dispatches(cursors={"message": str(message)}))
    [ran] = ticked.runs
    notes = [m for m in conversation_of(scenario.conn) if m[0] == "canopy"]
    assert notes == [
        ("canopy", "note", f"Tick {ticked.tick.id} read message {message}: started run {ran.id} (implement).", message),
    ]


def test_one_note_answers_every_message_a_tick_read_on_its_ticket(scenario: Scenario) -> None:
    scenario.seen(KEY, "PROJ-2")
    scenario.operator("reply", KEY, "First.")
    scenario.operator("reply", KEY, "Second.")
    scenario.operator("reply", "PROJ-2", "Elsewhere.")
    first, second, elsewhere = (
        int(m["id"]) for m in scenario.conn.execute("SELECT id FROM messages WHERE source = 'operator' ORDER BY id")
    )
    ticked = scenario.tick(*waits(KEY), raises("PROJ-2", "needs_author", "the ticket names no repository"))
    tick = ticked.tick.id
    assert conversation_of(scenario.conn)[-1] == (
        "canopy",
        "note",
        f"Tick {tick} read messages {first} and {second}: waiting: nothing to do yet.",
        second,
    )
    assert conversation_of(scenario.conn, "PROJ-2")[-1] == (
        "canopy",
        "note",
        f"Tick {tick} read message {elsewhere}: needs you (needs_author): the ticket names no repository.",
        elsewhere,
    )


def test_a_dry_run_or_a_failed_tick_notes_nothing_and_the_next_ok_tick_does(scenario: Scenario) -> None:
    scenario.seen()
    scenario.operator("reply", KEY, "Use the v2 client.")
    message = newest_operator_message(scenario.conn)
    scenario.tick(*waits(KEY), dry_run=True)
    scenario.tick(*waits(KEY), exit_code=1, code=1)
    assert [m[0] for m in conversation_of(scenario.conn)] == ["operator"]
    ticked = scenario.tick(*waits(KEY))
    assert conversation_of(scenario.conn)[-1][2] == (
        f"Tick {ticked.tick.id} read message {message}: waiting: nothing to do yet."
    )


def test_a_private_workers_conversation_leaves_the_notes_out(scenario: Scenario) -> None:
    scenario.operator("start", KEY)
    scenario.operator("reply", KEY, "Use the v2 client.")
    scenario.tick(*waits(KEY))
    assert [m[0] for m in conversation_of(scenario.conn)] == ["operator", "canopy"]
    prompt = present(conversation.prompt_conversation(scenario.conn, KEY))
    assert "Use the v2 client." in prompt
    assert "Tick " not in prompt


def decision(action: str, rationale: str) -> records.Decision:
    """A decision about KEY, as a tick recorded it."""
    return records.Decision(
        id=1,
        tick_id=7,
        ticket_key=KEY,
        action=action,
        rationale=rationale,
        created_at="",
        repo=None,
        chore=None,
        pr=None,
        decider=Decider.OVERSEER,
        kept=False,
        item=None,
        kind=None,
    )


def test_a_note_says_each_decision_in_a_few_words_and_cuts_a_long_reason() -> None:
    made = [
        decision("refused:capacity", "every slot is busy."),
        decision("skip", "the ticket\nis closed"),
        decision("done", "merged"),
        decision(f"dispatch:{RunKind.RESUME}", "dry run: not dispatched; would resume"),
    ]
    assert acknowledge.body(7, KEY, [40], made) == (
        "Tick 7 read message 40: refused capacity: every slot is busy; skipped: the ticket is closed; done: merged; "
        "dispatch:resume: dry run: not dispatched; would resume."
    )
    cut = acknowledge.body(7, KEY, [40], [decision("wait", "x" * 400)])
    assert cut == f"Tick 7 read message 40: waiting: {'x' * (acknowledge.MAX_REASON - 1)}…."
    # A tick owes every ticket with a new message a decision; one it is not owed, such as a stopped ticket's, says so.
    assert acknowledge.body(7, KEY, [40, 41], []) == f"Tick 7 read messages 40 and 41 and decided nothing about {KEY}."
