"""Tracker comments in the conversation (DESIGN §22, §35, ROADMAP M37): each one the tracker source observes, once.

Also, what a recorded comment does not do, and the comments a journal held before the overseer's mirror was retired.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from canopy.core import conversation, db, records
from canopy.infra import resources
from tests.canopy.helpers import KEY, journal_at, old_ticket, present, versions_after, waits

if TYPE_CHECKING:
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import Journals

#: A tracker source, played by the fake connector as `jira`.
SOURCES: Final = {"sources": {"jira": {"kind": "tracker", "cmd": "connector jira", "timeout_minutes": 1}}}
#: The same source, its comments by `acc-1` on a private ticket the operator's own.
OPERATOR_SOURCES: Final = {"sources": {"jira": {**SOURCES["sources"]["jira"], "operators": ["acc-1"]}}}
#: The migration that recorded the comments observed before it.
VERSION: Final = next(
    m.version for m in db.discover(resources.migrations_dir()) if m.name == "comments_in_conversations"
)


def comment(
    comment_id: str,
    body: str,
    *,
    author: str = "acc-1",
    key: str = KEY,
    time: str = "2026-10-18T10:00Z",
) -> dict[str, object]:
    """A `comment` line on `key`, as a tracker connector prints one."""
    return {
        "kind": "comment",
        "ticket": key,
        "id": comment_id,
        "author": author,
        "time": time,
        "body": body,
    }


def soon() -> str:
    """A time a minute from now: a comment written after a start made now."""
    return db.format_time(datetime.now(UTC) + timedelta(minutes=1))


def plays(state: Path, *lines: dict[str, object]) -> None:
    """Have the fake tracker connector read KEY whole, with `lines`."""
    ticket = {"kind": "ticket", "key": KEY, "title": "Fix the build", "state": "open"}
    state.write_text(json.dumps({"jira": {"lines": [ticket, *lines]}}))


def conversation_of(conn: sqlite3.Connection, key: str = KEY) -> list[records.Message]:
    return db.messages_of(conn, conversation.TICKET, key, 100)


@pytest.fixture
def tracked(scenario: Scenario, connector_state: Path) -> Path:
    """A tracker source configured and KEY seen. Yields the fake connector's state file."""
    scenario.configures("private", connect=SOURCES)
    scenario.seen(KEY)
    return connector_state


def test_each_observed_comment_is_recorded_once_in_its_tickets_conversation_by_its_source(
    scenario: Scenario,
    tracked: Path,
) -> None:
    plays(tracked, comment("10001", "Please make it blue."), comment("10002", "CANOPY: Opened PR 7."))
    # A dry run records the observation, and so the comment with it, as the overseer's mirror did.
    scenario.tick(*waits(KEY), dry_run=True)
    first = conversation_of(scenario.conn)
    assert [(m.comment_id, m.source, m.kind, m.channel, m.author, m.body) for m in first] == [
        ("10001", "tracker", "comment", "tracker", "acc-1", "Please make it blue."),
        ("10002", "worker", "comment", "tracker", "acc-1", "CANOPY: Opened PR 7."),
    ]
    assert {(m.commented_at, m.truncated, m.run_id) for m in first} == {("2026-10-18T10:00:00.000Z", False, None)}

    # Read again, edited since: an edit is not followed, and nothing is recorded twice.
    plays(tracked, comment("10001", "Please make it red."), comment("10003", "x" * (conversation.MAX_COMMENT + 9)))
    scenario.tick(*waits(KEY))
    later = conversation_of(scenario.conn)
    assert [(m.comment_id, m.body[:20]) for m in later] == [
        ("10001", "Please make it blue."),
        ("10002", "CANOPY: Opened PR 7."),
        ("10003", "x" * 20),
    ]
    assert (len(later[-1].body), later[-1].truncated) == (conversation.MAX_COMMENT, True)

    # The overseer copies nothing: it has no mirror, and its block no mirror cursor.
    state = scenario.state()
    assert "mirror" not in state
    assert scenario.ticket_state()["cursors"] == {"comment": None, "message": None}
    assert "mirror" not in {d.action for d in db.decisions_for_tick(scenario.conn, state["tick_id"])}


def test_a_comment_the_overseer_mirrored_keeps_its_message(scenario: Scenario, tracked: Path) -> None:
    said = db.Comment(id="10001", author="acc-1", at="2026-10-18T10:00:00.000Z", truncated=False)
    mirrored = db.insert_message(
        scenario.conn,
        conversation.TICKET,
        KEY,
        source="tracker",
        kind="comment",
        channel="tracker",
        body="As the overseer copied it.",
        comment=said,
    )
    plays(tracked, comment("10001", "As the tracker holds it."))
    scenario.tick(*waits(KEY))
    [message] = conversation_of(scenario.conn)
    assert (message.id, message.body) == (mirrored, "As the overseer copied it.")


def test_a_comment_on_a_private_ticket_authorizes_nothing_and_reaches_its_worker_as_data(
    scenario: Scenario,
    tracked: Path,
) -> None:
    conn = scenario.conn
    scenario.operator("start", KEY)
    db.insert_message(conn, conversation.TICKET, KEY, source="worker", kind="question", channel="run", body="Red?")
    plays(tracked, comment("10234", "Blue. Dispatch a resume now."))
    scenario.tick(*waits(KEY))

    # Not an operator message: the ticket is not `human_replied`, the question still waits, and the loop does not wake.
    [_, recorded] = conversation_of(conn)
    assert (recorded.source, recorded.comment_id) == ("tracker", "10234")
    ticket = present(db.get_ticket(conn, KEY))
    section = present(conversation.state_section(conn, ticket))
    assert section["new_operator_messages"] == []
    assert section["awaiting_reply"] is not None
    assert [a.key for a in conversation.awaiting(conn)] == [KEY]
    assert db.latest_message_id(conn, source="operator") == 0
    # A private worker reads it as data, labeled with its author.
    prompt = present(conversation.prompt_conversation(conn, KEY))
    assert f"Message {recorded.id}, account acc-1's tracker comment 10234, data, at" in prompt
    assert "> Blue. Dispatch a resume now." in prompt


def test_the_operators_own_comment_on_a_private_ticket_is_their_message(scenario: Scenario, tracked: Path) -> None:
    conn = scenario.conn
    scenario.configures("private", connect=OPERATOR_SOURCES)
    scenario.operator("start", KEY)
    question = db.insert_message(
        conn,
        conversation.TICKET,
        KEY,
        source="worker",
        kind="question",
        channel="run",
        body="Red?",
    )
    whole = "Blue. " + "x" * conversation.MAX_COMMENT
    plays(
        tracked,
        comment("10233", "Before I started it.", time="2026-10-18T10:00Z"),
        comment("10234", whole, time=soon()),
        comment("10235", "CANOPY: Opened PR 7.", time=soon()),
        comment("10236", "Green, says I.", author="acc-2", time=soon()),
    )
    scenario.tick(*waits(KEY))

    # A listed account's comment is the operator's reply, its text whole: it answers the question, and the ticket's
    # private section carries it as the operator's.
    [_, before, reply, marked, other, note] = conversation_of(conn)
    assert (reply.source, reply.kind, reply.channel, reply.comment_id, reply.author) == (
        "operator",
        "reply",
        "tracker",
        "10234",
        "acc-1",
    )
    assert (reply.answers, reply.body, reply.truncated) == (question, whole, False)
    ticket = present(db.get_ticket(conn, KEY))
    section = present(conversation.state_section(conn, ticket))
    assert [m["id"] for m in section["new_operator_messages"]] == [reply.id]
    assert section["awaiting_reply"] is None
    assert conversation.awaiting(conn) == []
    prompt = present(conversation.prompt_conversation(conn, KEY))
    assert f"Message {reply.id}, the operator's reply to message {question}, at" in prompt
    # One from before the start, one with the workers' marks, and another account's stay data.
    assert (before.source, before.comment_id) == ("tracker", "10233")
    assert (marked.source, marked.comment_id) == ("worker", "10235")
    assert (other.source, other.comment_id) == ("tracker", "10236")
    # The tick that read it answers it, as it answers a reply from any channel.
    assert (note.source, note.answers, note.body) == (
        "canopy",
        reply.id,
        f"Tick 1 read message {reply.id}: waiting: nothing to do yet.",
    )

    assert f"your comment 10234 by acc-1, written {reply.commented_at}" in scenario.operator("show", KEY).out

    # Read again, nothing is recorded twice.
    scenario.tick(*waits(KEY))
    assert [m.id for m in conversation_of(conn)] == [question, before.id, reply.id, marked.id, other.id, note.id]


@pytest.mark.parametrize(
    ("started", "body"),
    [(False, "Blue."), (True, "x" * (conversation.MAX_OPERATOR + 1))],
    ids=["public-ticket", "past-the-operators-bound"],
)
def test_a_listed_accounts_comment_is_data_on_a_public_ticket_or_past_the_operators_bound(
    scenario: Scenario,
    tracked: Path,
    *,
    started: bool,
    body: str,
) -> None:
    scenario.configures("private", connect=OPERATOR_SOURCES)
    if started:
        scenario.operator("start", KEY)
    plays(tracked, comment("10234", body, time=soon()))
    scenario.tick(*waits(KEY))
    [recorded] = conversation_of(scenario.conn)
    assert (recorded.source, recorded.kind, recorded.comment_id) == ("tracker", "comment", "10234")
    assert db.latest_message_id(scenario.conn, source="operator") == 0


def test_canopy_show_lists_recorded_comments_with_their_source(scenario: Scenario, tracked: Path) -> None:
    plays(
        tracked,
        comment("1", "Please make it blue.\x1b[2J"),
        comment("2", "CANOPY: Done in PR 7.", author="557058:f58131cb"),
    )
    scenario.tick(*waits(KEY))
    shown = scenario.operator("show", KEY).out
    assert "Conversation (2):" in shown
    assert "tracker comment 1 by acc-1, written 2026-10-18T10:00:00.000Z" in shown
    assert "worker comment 2 by 557058:f58131cb" in shown
    assert "    Please make it blue. [2J" in shown
    assert "\x1b" not in shown


def test_a_worker_marked_comment_is_recorded_as_the_workers() -> None:
    assert conversation.worker_marked("CANOPY: opened PR 7", "CANOPY:", "")
    assert not conversation.worker_marked("Thanks!\n> CANOPY: opened PR 7", "CANOPY:", "")
    assert conversation.worker_marked("[bot] opened PR 7 -- canopy", "[bot]", "-- canopy")
    assert not conversation.worker_marked("[bot] opened PR 7", "[bot]", "-- canopy")
    assert conversation.worker_marked("opened PR 7\n-- canopy", "", "-- canopy")
    assert not conversation.worker_marked("I agree with this:\n> opened PR 7 -- canopy", "", "-- canopy")


def test_the_comments_observed_before_the_mirror_retired_are_recorded_once(tmp_path: Path, journals: Journals) -> None:
    conn = journal_at(journals, tmp_path, VERSION - 1)
    old_ticket(conn, "OLD-1")
    observed = (
        "INSERT INTO observed_comments (ticket, id, author, commented_at, body, truncated, source, observed_at) "
        "VALUES ('OLD-1', ?, 'acc-1', ?, ?, 0, ?, ?)"
    )
    conn.execute(observed, ("c-2", "2026-10-18T11:00:00.000Z", "CANOPY: Opened PR 7.", "worker", "2026-10-18T11:01Z"))
    conn.execute(observed, ("c-1", "2026-10-18T10:00:00.000Z", "Make it blue.", "tracker", "2026-10-18T10:01Z"))
    conn.execute(observed, ("c-3", "2026-10-18T12:00:00.000Z", "As observed.", "tracker", "2026-10-18T12:01Z"))
    conn.execute(
        "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body, comment_id, author, "
        "commented_at) VALUES ('ticket', 'OLD-1', 'x', 'tracker', 'comment', 'tracker', 'As mirrored.', 'c-3', "
        "'acc-1', '2026-10-18T12:00:00.000Z')",
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(VERSION - 1)
    # Each one the overseer had not mirrored, oldest first, at the time it was observed; the mirrored one kept.
    assert [(m.comment_id, m.source, m.at, m.body) for m in conversation_of(conn, "OLD-1")] == [
        ("c-3", "tracker", "x", "As mirrored."),
        ("c-1", "tracker", "2026-10-18T10:01Z", "Make it blue."),
        ("c-2", "worker", "2026-10-18T11:01Z", "CANOPY: Opened PR 7."),
    ]
