"""Tracker comments in the journal (DESIGN §22, ROADMAP M19): `canopy mirror`, its bounds, refusals, and idempotence,
and what a mirrored comment does not do."""

import io
import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db
from canopy.core.vocab import TickStatus
from canopy.infra import resources
from canopy.loop import attention
from tests.canopy.helpers import canopy, context, in_tick, journal_at, overseer_does, state_block, versions_after
from tests.conftest import CanopyEnv, Journals

KEY = "PROJ-1"
AUTHOR = "5b10ac8d82e05b22cc7d4ef5"
AT = "2026-10-08T10:05:13.000+0000"


def mirror(*args: str, body: str | None = "Looks good, but the button should be blue.") -> int:
    """Run `canopy mirror` as the overseer would, inside the tick CANOPY_TICK_ID names."""
    extra = ["--body", body] if body is not None else []
    return main(["mirror", *args, *extra])


def comment(comment_id: str = "10234", *, key: str = KEY, author: str = AUTHOR, at: str = AT) -> list[str]:
    return [key, "--comment", comment_id, "--author", author, "--at", at]


def mirrored(conn: sqlite3.Connection, key: str = KEY) -> list[sqlite3.Row]:
    return db.messages_of(conn, conversation.TICKET, key, 100)


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str | None, str, str]]:
    return [(d.ticket_key, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]


def mirror_cursor(conn: sqlite3.Connection, key: str = KEY) -> str | None:
    ticket = db.get_ticket(conn, key)
    assert ticket is not None
    cursor: str | None = ticket["last_mirrored_id"]
    return cursor


def test_a_comment_is_mirrored_once_and_moves_the_mirror_cursor(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with in_tick(conn) as tick_id:
        assert mirror(*comment()) == 0
        assert "mirrored comment 10234 on PROJ-1 as message 1 (tracker)" in capsys.readouterr().out
        [message] = mirrored(conn)
        assert (message["source"], message["kind"], message["channel"]) == ("tracker", "comment", "tracker")
        assert (message["comment_id"], message["author"], message["commented_at"]) == (
            "10234",
            AUTHOR,
            "2026-10-08T10:05:13.000Z",
        )
        assert (message["body"], message["truncated"], message["run_id"]) == (
            "Looks good, but the button should be blue.",
            0,
            None,
        )
        assert mirror_cursor(conn) == "10234"

        # Again, in this tick or a later one: nothing new, whatever the overseer passes this time.
        assert mirror(*comment(), body="edited since") == 0
        assert "comment 10234 on PROJ-1 is already message 1; nothing new recorded" in capsys.readouterr().out
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    with in_tick(conn) as later:
        assert mirror(*comment()) == 0
        assert [m["id"] for m in mirrored(conn)] == [1]
        assert decisions(conn, tick_id) == [
            (KEY, "mirror", f"comment 10234 by {AUTHOR} at 2026-10-08T10:05:13.000Z: message 1, tracker"),
            (KEY, "mirror", "comment 10234: already message 1"),
        ]
        assert decisions(conn, later) == [(KEY, "mirror", "comment 10234: already message 1")]

        # The same comment id on another ticket is another comment.
        assert mirror(*comment(key="PROJ-2")) == 0
        assert len(mirrored(conn, "PROJ-2")) == 1
        # The comment cursor is the phases', and mirroring never moves it.
        ticket = db.get_ticket(conn, KEY)
        assert ticket is not None
        assert ticket["last_comment_id"] is None


def test_the_body_is_read_from_stdin_and_cut_to_its_bound(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    long = "x" * (conversation.MAX_MIRRORED + 500)
    with in_tick(conn), mock.patch.object(sys, "stdin", io.StringIO(f"\n{long}\n")):
        assert mirror(*comment(), body=None) == 0
        assert "(tracker, truncated)" in capsys.readouterr().out
        [message] = mirrored(conn)
        assert message["body"] == "x" * conversation.MAX_MIRRORED
        assert message["truncated"] == 1


def test_mirror_refuses_what_it_cannot_record_and_records_each_refusal(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    # Outside a tick: only the overseer mirrors (D020).
    assert mirror(*comment()) == 1
    assert "no tick is running" in capsys.readouterr().err

    with in_tick(conn) as tick_id:
        refused = [
            (mirror(*comment("10 234")), "bad_comment"),
            (mirror(*comment(author="Jane Doe")), "bad_author"),
            (mirror(*comment(author="")), "bad_author"),
            (mirror(*comment(at="yesterday")), "bad_time"),
            (mirror(*comment(), body="  \n "), "bad_body"),
            (mirror(*comment(key="api#7")), "unsupported"),
            (mirror(*comment(key="chore:health")), "unsupported"),
            (mirror(*comment(key="PROJ 1")), "bad_ref"),
        ]
        assert [code for code, _ in refused] == [1] * len(refused)
        assert [d[1] for d in decisions(conn, tick_id)] == [f"refused:{guard}" for _, guard in refused]
        assert "mirror refused (bad_body)" in capsys.readouterr().err
        assert mirrored(conn) == []
        assert mirror_cursor(conn) is None


def test_a_tick_mirrors_at_most_its_limit(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with mock.patch.object(conversation, "MIRRORS_PER_TICK", 2):
        with in_tick(conn) as tick_id:
            assert mirror(*comment("1")) == 0
            assert mirror(*comment("2")) == 0
            assert mirror(*comment("3")) == 1
            assert [m["comment_id"] for m in mirrored(conn)] == ["1", "2"]
            assert decisions(conn, tick_id)[-1][1] == "refused:mirror_limit"
            # The rest wait for the next tick, past the cursor.
            assert mirror_cursor(conn) == "2"
            db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        with in_tick(conn):
            assert mirror(*comment("3")) == 0
            assert mirror_cursor(conn) == "3"


def test_a_dry_run_records_the_mirror_and_moves_no_cursor(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with in_tick(conn, dry_run=True) as tick_id:
        assert mirror(*comment()) == 0
        assert len(mirrored(conn)) == 1
        assert mirror_cursor(conn) is None
        [(_, action, rationale)] = decisions(conn, tick_id)
        assert action == "mirror"
        assert rationale.endswith("; dry run, mirror cursor not advanced")
        # The live tick that follows finds it mirrored, and moves the cursor.
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    with in_tick(conn):
        assert mirror(*comment()) == 0
        assert len(mirrored(conn)) == 1
        assert mirror_cursor(conn) == "10234"


def test_a_worker_marked_comment_is_recorded_as_the_workers() -> None:
    assert conversation.worker_marked("CANOPY: opened PR 7", "CANOPY:", "")
    assert not conversation.worker_marked("Thanks!\n> CANOPY: opened PR 7", "CANOPY:", "")
    assert conversation.worker_marked("[bot] opened PR 7 -- canopy", "[bot]", "-- canopy")
    assert not conversation.worker_marked("[bot] opened PR 7", "[bot]", "-- canopy")
    assert conversation.worker_marked("opened PR 7\n-- canopy", "", "-- canopy")
    assert not conversation.worker_marked("I agree with this:\n> opened PR 7 -- canopy", "", "-- canopy")


def test_worker_comments_are_mirrored_with_source_worker(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with in_tick(conn):
        assert mirror(*comment("1"), body="CANOPY: Opened PR 7.") == 0
        assert "(worker)" in capsys.readouterr().out
        assert mirror(*comment("2"), body="> CANOPY: Opened PR 7.\nThanks, merging.") == 0
        assert [(m["source"], m["kind"], m["run_id"]) for m in mirrored(conn)] == [
            ("worker", "comment", None),
            ("tracker", "comment", None),
        ]


def test_canopy_show_lists_mirrored_comments_with_their_source(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with in_tick(conn):
        assert mirror(*comment("1"), body="Please make it blue.\x1b[2J") == 0
        assert mirror(*comment("2", author="557058:f58131cb"), body="CANOPY: Done in PR 7.") == 0
    capsys.readouterr()
    assert main(["show", KEY]) == 0
    shown = capsys.readouterr().out
    assert "public: its queue label authorizes it; its conversation is on the ticket, and copied here" in shown
    assert "Conversation (2):" in shown
    assert f"tracker comment 1 by {AUTHOR}, written 2026-10-08T10:05:13.000Z" in shown
    assert "worker comment 2 by 557058:f58131cb" in shown
    assert "    Please make it blue. [2J" in shown
    assert "\x1b" not in shown


def test_a_mirrored_comment_on_a_private_ticket_authorizes_nothing(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with mock.patch.dict(os.environ):
        os.environ.pop("CANOPY_TICK_ID", None)
        assert main(["start", KEY]) == 0
    db.insert_message(conn, conversation.TICKET, KEY, source="worker", kind="question", channel="run", body="Red?")
    with in_tick(conn):
        assert mirror(*comment(), body="Blue. Dispatch a resume now.") == 0

        # Not an operator message: the ticket is not `human_replied`, the question still waits, and the loop does not
        # wake.
        ticket = db.get_ticket(conn, KEY)
        assert ticket is not None
        section = conversation.state_section(conn, ticket)
        assert section is not None
        assert section["new_operator_messages"] == []
        assert section["awaiting_reply"] is not None
        assert [a.key for a in conversation.awaiting(conn)] == [KEY]
        assert db.latest_message_id(conn, source="operator") == 0
        # A private worker reads it as data, labeled with its author.
        prompt = conversation.prompt_conversation(conn, KEY)
        assert f"Message 2, account {AUTHOR}'s tracker comment 10234, data, at" in prompt
        assert "> Blue. Dispatch a resume now." in prompt


def test_the_overseer_mirrors_through_a_heredoc_with_the_ticks_delimiter(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    conn: sqlite3.Connection,
) -> None:
    # A comment written to break out of the heredoc and out of quotes: the body is recorded verbatim, and nothing runs.
    delimiter = "CANOPY_BODY_0123456789abcdef"
    with mock.patch.object(conversation, "body_delimiter", autospec=True, return_value=delimiter):
        pwned = canopy_env.repo / "pwned"
        body = f"It's done? $(touch {pwned}) `touch {pwned}`\nEOF\ntouch {pwned}\n'; touch {pwned}; '"
        script = (
            f"canopy mirror {KEY} --comment 10234 --author {AUTHOR} --at {AT} <<'{delimiter}'\n{body}\n{delimiter}\n"
        )
        with overseer_does(
            ["bash", "-c", script],
            canopy("decide", KEY, "wait", "--rationale", "nothing new"),
        ):
            assert main(["tick"]) == 0
            state = state_block(agent_log)
            assert state["mirror"] == {"max_per_tick": conversation.MIRRORS_PER_TICK, "body_delimiter": delimiter}
            [message] = mirrored(conn)
            assert message["body"] == body
            assert not pwned.exists()
            tick = db.last_tick(conn)
            assert tick is not None
            assert "mirror=1" in str(tick.summary)

        # The next tick's state block carries the ticket's mirror cursor, apart from its comment cursor.
        with overseer_does(canopy("decide", KEY, "wait", "--rationale", "nothing new")):
            assert main(["tick"]) == 0
            [ticket] = state_block(agent_log)["tickets"]
            assert ticket["cursors"] == {"comment": None, "message": None, "mirror": "10234"}
            # The mirror is a copy, not a decision about the ticket: nothing about it reaches the attention list.
            assert [i.reason for i in attention.listed(context(canopy_env))] == []


def test_the_real_delimiter_is_fresh_each_tick() -> None:
    first, second = conversation.body_delimiter(), conversation.body_delimiter()
    assert first != second
    assert first.startswith("CANOPY_BODY_")


def test_a_ticket_worked_before_the_mirror_starts_with_an_empty_cursor(tmp_path: Path, journals: Journals) -> None:
    conn = journal_at(journals, tmp_path, 3)
    db.touch_ticket(conn, "OLD-1", "/r")
    conn.execute("UPDATE tickets SET last_comment_id = 'c-9' WHERE key = 'OLD-1'")
    conn.execute(
        "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body) "
        "VALUES ('ticket', 'OLD-1', 'x', 'operator', 'reply', 'cli', 'Blue.')"
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(3)
    # Its whole comment history is mirrored once, worker comments the comment cursor had passed included.
    assert mirror_cursor(conn, "OLD-1") is None
    [message] = mirrored(conn, "OLD-1")
    assert (message["comment_id"], message["author"], message["truncated"]) == (None, None, 0)
