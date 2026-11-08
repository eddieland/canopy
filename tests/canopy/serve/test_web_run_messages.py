"""The operator's message to a running run from its ticket's reply form in the web UI (DESIGN §44, TRUST_MODEL T1, T8).

It is sent through `conversation.reply`, the function `canopy reply run:ID "..."` calls, with channel `web`, so the
CLI's guards refuse it as they refuse the CLI's; the ticket's conversation holds it, and says which run it was sent to
and when that run's agent fetched it.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from canopy.core import cards, conversation, db, records, run_inbox
from canopy.core.vocab import RunStatus
from canopy.runtime.report import Called
from canopy.serve import live
from canopy.serve.backend import Backend
from canopy.serve.schema.event import TicketChanged, TicketsUpdated
from tests.canopy.helpers import in_run, present
from tests.canopy.web_helpers import client, refused, signed_in

#: A message's form, with the submission id it drew. Run 41 of the mock runs, working ABC-101; run 39 has ended.
MESSAGE = {"body": "Drop the logout half: ABC-107 has it now.", "submission": "form-0001"}


def test_a_message_reaches_the_running_run_and_its_ticket_says_when_it_was_fetched(backend: Backend) -> None:
    c = client(None, backend)
    headers = signed_in(c)

    sent = c.post("/api/runs/41/messages", json=MESSAGE, headers=headers).json()
    # Its answers directory is not there yet, so its agent is not told; the ticket's next run reads it.
    assert {k: v for k, v in sent.items() if k != "message_id"} == {"new": True, "told": False}
    again = c.post("/api/runs/41/messages", json=MESSAGE, headers=headers).json()
    assert again == {**sent, "new": False}
    with backend.open() as ctx:
        [recorded] = run_inbox.sent_to(ctx.conn, "runs", 41)
    assert (recorded.id, recorded.subject_id, recorded.source, recorded.channel) == (
        sent["message_id"],
        "ABC-101",
        "operator",
        "web",
    )
    assert recorded.answers is None
    # The ticket's own conversation holds it, sent to the run and not written where its agent reads it.
    listed = _message(c, sent["message_id"])
    assert (listed["body"], listed["to_run"], listed["delivered_at"], listed["fetched_at"]) == (
        MESSAGE["body"],
        41,
        None,
        None,
    )

    # While its agent works, its answers directory is there, and the messages are written where it reads them.
    with backend.open() as ctx:
        answers = cards.answers_dir(ctx.state_dir, "41")
    cards.make_answers(answers)
    later = {"body": "And keep the old form behind a flag.", "submission": "form-0002"}
    told = c.post("/api/runs/41/messages", json=later, headers=headers).json()
    assert (told["new"], told["told"]) == (True, True)
    written = json.loads((answers / run_inbox.TEXTS_FILE).read_text())
    assert [m["text"] for m in written["messages"]] == [MESSAGE["body"], later["body"]]
    assert json.loads((answers / run_inbox.MARK_FILE).read_text()) == {"newest": told["message_id"]}

    # The conversation says when its agent fetched them, as `canopy show run:ID` does: by a call that started after
    # both were written, a second on, so never in the millisecond the later one was.
    _fetch(backend)
    for message_id in (sent["message_id"], told["message_id"]):
        shown = _message(c, message_id)
        assert shown["to_run"] == 41
        assert shown["delivered_at"] is not None
        assert shown["fetched_at"] is not None


def test_a_fetch_changes_the_ticket_on_the_stream_though_its_summary_holds(backend: Backend) -> None:
    c = client(None, backend)
    headers = signed_in(c)
    with backend.open() as ctx:
        cards.make_answers(cards.answers_dir(ctx.state_dir, "41"))
        sent = live._Sent()  # noqa: SLF001  (the stream's own record of what it sent)
        sent.changes(backend, ctx)
        assert c.post("/api/runs/41/messages", json=MESSAGE, headers=headers).json()["told"] is True
        sent.changes(backend, ctx)
        _fetch(backend)
        events = [e.root for e in sent.changes(backend, ctx)]
    # Only the ticket's page reads again: the list has nothing new to say.
    assert [type(e) for e in events if isinstance(e, TicketsUpdated)] == []
    assert [e.key for e in events if isinstance(e, TicketChanged)] == ["ABC-101"]


def test_a_message_to_a_run_that_ended_is_refused_naming_its_tickets_reply(backend: Backend) -> None:
    c = client(None, backend)
    headers = signed_in(c)
    said = refused(c.post("/api/runs/39/messages", json=MESSAGE, headers=headers))
    assert said.startswith("ended: run:39 has ended")
    assert "`canopy reply ABC-" in said
    missing = refused(c.post("/api/runs/99/messages", json=MESSAGE, headers=headers))
    assert missing == "unknown: canopy has no record of run:99"
    with backend.open() as ctx:
        assert run_inbox.sent_to(ctx.conn, "runs", 39) == []


def test_a_submission_tried_on_the_run_then_sent_to_its_ticket_records_one_message(backend: Backend) -> None:
    c = client(None, backend)
    headers = signed_in(c)
    with backend.open() as ctx:
        ended = present(records.select(records.Run).where("id = ?", 39).one(ctx.conn)).ticket_key

    # The run ended between the page drawing its box and the send: refused, and the form sends again to the ticket.
    assert refused(c.post("/api/runs/39/messages", json=MESSAGE, headers=headers)).startswith("ended")
    replied = c.post(f"/api/tickets/{ended}/replies", json=MESSAGE, headers=headers).json()
    assert replied["new"] is True
    assert _count(c, ended, MESSAGE["body"]) == 1

    # Recorded on the run, its answer lost and the run ended since: sent again to the ticket, it records nothing.
    once = {"body": "Leave the migration alone.", "submission": "form-0003"}
    to_run = c.post("/api/runs/41/messages", json=once, headers=headers).json()
    _end(backend, 41)
    again = c.post("/api/tickets/ABC-101/replies", json=once, headers=headers).json()
    assert again == {"message_id": to_run["message_id"], "answers": None, "new": False}
    assert _count(c, "ABC-101", once["body"]) == 1


def test_a_submission_replied_to_the_ticket_then_sent_to_its_run_records_one_message(backend: Backend) -> None:
    c = client(None, backend)
    headers = signed_in(c)
    replied = c.post("/api/tickets/ABC-101/replies", json=MESSAGE, headers=headers).json()
    again = c.post("/api/runs/41/messages", json=MESSAGE, headers=headers).json()
    assert again == {"message_id": replied["message_id"], "new": False, "told": False}
    assert _count(c, "ABC-101", MESSAGE["body"]) == 1
    with backend.open() as ctx:
        # The reply stays the ticket's, for its next run: the running one was never sent it.
        assert run_inbox.sent_to(ctx.conn, "runs", 41) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ("   ", "bad_body: the reply is empty"),
        ("x" * (conversation.MAX_OPERATOR + 1), f"bad_body: the reply is {conversation.MAX_OPERATOR + 1} characters"),
    ],
)
def test_an_empty_or_overlong_message_is_refused_as_the_cli_refuses_it(
    backend: Backend,
    body: str,
    said: str,
) -> None:
    c = client(None, backend)
    headers = signed_in(c)
    assert refused(c.post("/api/runs/41/messages", json={**MESSAGE, "body": body}, headers=headers)).startswith(said)
    with backend.open() as ctx:
        assert run_inbox.sent_to(ctx.conn, "runs", 41) == []


def test_a_message_is_refused_inside_a_run(backend: Backend) -> None:
    c = client(None, backend)
    headers = signed_in(c)
    with in_run(7):
        assert refused(c.post("/api/runs/41/messages", json=MESSAGE, headers=headers)).startswith("inside_run")
    with backend.open() as ctx:
        assert run_inbox.sent_to(ctx.conn, "runs", 41) == []


def _message(c: TestClient, message_id: int) -> dict[str, object]:
    """Message `message_id` as ABC-101's page reads it."""
    [found] = [m for m in c.get("/api/tickets/ABC-101").json()["messages"] if m["id"] == message_id]
    return found


def _count(c: TestClient, key: str, body: str) -> int:
    """How many of ticket `key`'s messages say `body`."""
    return sum(m["body"] == body for m in c.get(f"/api/tickets/{key}").json()["messages"])


def _fetch(backend: Backend) -> None:
    """Run 41's agent fetches its messages, by a call that started a second from now."""
    started = datetime.now(UTC) + timedelta(seconds=1)
    fetch = Called(tool=run_inbox.tool_name(), completed=True, input={}, started_at=started)
    with backend.open() as ctx:
        run_inbox.record_fetch(ctx.conn, "runs", 41, fetch)


def _end(backend: Backend, run_id: int) -> None:
    """Run `run_id` ends, done."""
    with backend.open() as ctx, db.transaction(ctx.conn):
        records.update(records.Run).where("id = ?", run_id).set(status=RunStatus.DONE).run(ctx.conn)
