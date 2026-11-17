"""What an index of every OpenCode 2 session's text reads, from OpenCode 2.1.4's database (ROADMAP M72, stage 2)."""

import os
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from canopy.runtime.opencode2 import indexed_text
from canopy.runtime.report import MessageText, SessionHead
from tests.canopy.helpers import Kept, called, replied, runtime_database, runtime_record, sent, wrote


@pytest.fixture
def data_home(tmp_path: Path) -> Iterator[Path]:
    """The operator's `$XDG_DATA_HOME`, under which the runtime and each sandbox role keep their records."""
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path)}):
        yield tmp_path


def role(data_home: Path, name: str) -> Path:
    """Where a sandbox role's runtime keeps its record, under the operator's data home."""
    return runtime_database(data_home / "canopy" / "sandbox" / name)


def head(session_id: str, record: Path | None = None) -> SessionHead:
    """A session's head, as `heads` reads it, kept by the operator's record or `record`."""
    return SessionHead(session_id, None, "/work", None, 1, str(record or runtime_database()))


def test_heads_are_read_after_a_cursor_oldest_first_or_before_one_newest_first_merged_across_records(
    data_home: Path,
) -> None:
    runtime_record(
        Kept("ses_a", "/work", title="First\tline", updated=10),
        Kept("ses_c", "/work", parent_id="ses_a", updated=30),
        Kept("ses 9", "/work", updated=25),
    )
    runtime_record(Kept("ses_b", "/sandbox", updated=20), path=role(data_home, "worker"))

    after = indexed_text.heads((10, "ses_a"), newest_first=False, limit=10)
    newest = indexed_text.heads(None, newest_first=True, limit=3)

    assert [(at, h.session_id if h else None) for at, h in after.rows] == [
        ((20, "ses_b"), "ses_b"),
        ((25, "ses 9"), None),
        ((30, "ses_c"), "ses_c"),
    ]
    assert [at for at, _ in newest.rows] == [(30, "ses_c"), (25, "ses 9"), (20, "ses_b")]
    first = indexed_text.heads(None, newest_first=False, limit=1).rows[0][1]
    assert first is not None
    assert (first.title, first.record) == ("First line", str(runtime_database()))
    assert after.rows[0][1] is not None
    assert after.rows[0][1].record == str(role(data_home, "worker"))


def test_a_roles_record_canopy_cannot_read_is_passed_over_whole_and_the_operators_fails_the_read(
    data_home: Path,
) -> None:
    runtime_record(Kept("ses_a", "/work"))
    broken = role(data_home, "review")
    broken.parent.mkdir(parents=True)
    broken.write_text("not a database")

    found = indexed_text.heads(None, newest_first=True, limit=10)

    assert (found.outcome, found.passed_over, len(found.rows)) == ("found", 1, 1)
    assert indexed_text.kept().unread == {str(broken)}
    runtime_database().write_text("not a database")
    assert indexed_text.heads(None, newest_first=True, limit=10).outcome == "failed"
    assert indexed_text.kept().outcome == "failed"


def test_a_sessions_text_is_read_by_message_and_part_and_a_message_whose_json_is_not_expected_passed_over(
    data_home: Path,
) -> None:
    runtime_record(
        Kept(
            "ses_a",
            "/work",
            messages=[
                sent("make the button blue"),
                ("user", "not JSON"),
                ("assistant", {"content": "a string, not parts"}),
                replied(wrote("Done."), called("shell", {"command": "rg button"}, "src/a.css")),
            ],
        ),
    )

    found = indexed_text.texts(head("ses_a"), max_messages=100, max_chars=1000, max_total=10_000)

    assert found.outcome == "found"
    assert not found.cut
    assert [(p.message_id, p.part, p.text) for p in found.parts] == [
        ("msg_ses_a_0", "sent", "make the button blue"),
        ("msg_ses_a_3", "wrote", "Done."),
        ("msg_ses_a_3", "given", "rg button"),
        ("msg_ses_a_3", "returned", "src/a.css"),
    ]


def test_a_sessions_text_past_its_bounds_is_cut_and_says_so(data_home: Path) -> None:
    runtime_record(Kept("ses_a", "/work", messages=[sent("x" * 50), sent("second"), sent("third")]))

    long_part = indexed_text.texts(head("ses_a"), max_messages=100, max_chars=10, max_total=10_000)
    few = indexed_text.texts(head("ses_a"), max_messages=2, max_chars=100, max_total=10_000)
    little = indexed_text.texts(head("ses_a"), max_messages=100, max_chars=100, max_total=40)

    assert long_part.parts[0] == MessageText("msg_ses_a_0", "sent", "x" * 10, cut=True)
    assert long_part.cut
    assert (len(few.parts), few.cut) == (2, True)
    assert (len(little.parts), little.cut) == (1, True)


def test_a_session_or_a_record_the_runtime_no_longer_keeps_is_missing(data_home: Path) -> None:
    runtime_record(Kept("ses_a", "/work", messages=[sent("hello")]))

    assert indexed_text.texts(head("ses_gone"), max_messages=1, max_chars=1, max_total=1).outcome == "missing"
    elsewhere = head("ses_a", data_home / "planted.db")
    assert indexed_text.texts(elsewhere, max_messages=1, max_chars=1, max_total=1).outcome == "missing"
    assert indexed_text.message(str(data_home / "planted.db"), "ses_a", "msg_ses_a_0", max_chars=10) is None


def test_one_message_is_read_again_for_a_snippet(data_home: Path) -> None:
    runtime_record(Kept("ses_a", "/work", messages=[sent("first"), replied(wrote("second"))]))

    found = indexed_text.message(str(runtime_database()), "ses_a", "msg_ses_a_1", max_chars=100)

    assert found == [MessageText("msg_ses_a_1", "wrote", "second")]
    assert indexed_text.message(str(runtime_database()), "ses_a", "msg_gone", max_chars=100) is None


def test_every_sessions_id_is_read_by_the_record_that_keeps_it(data_home: Path) -> None:
    runtime_record(Kept("ses_a", "/work"), Kept("ses_b", "/work"))
    runtime_record(Kept("ses_c", "/sandbox"), path=role(data_home, "worker"))

    found = indexed_text.kept()

    assert found.records == {
        str(runtime_database()): {"ses_a", "ses_b"},
        str(role(data_home, "worker")): {"ses_c"},
    }
    assert found.unread == frozenset()
