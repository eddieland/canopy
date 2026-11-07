"""The operator's message to a running run from its page in the web UI (DESIGN §44, TRUST_MODEL T1, T8).

It is sent through `conversation.reply`, the function `canopy reply run:ID "..."` calls, with channel `web`, so the
CLI's guards refuse it as they refuse the CLI's; the run's page lists what was sent and when its agent fetched each.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from canopy.core import cards, conversation, run_inbox
from canopy.runtime.report import Called
from canopy.serve.backend import Backend
from tests.canopy.helpers import in_run
from tests.canopy.web_helpers import client, refused, signed_in

#: A message's form, with the submission id it drew. Run 41 of the mock runs, working ABC-101; run 39 has ended.
MESSAGE = {"body": "Drop the logout half: ABC-107 has it now.", "submission": "form-0001"}


def test_a_message_from_the_page_reaches_the_running_run_and_a_retry_records_nothing(backend: Backend) -> None:
    c = client(None, backend)
    headers = signed_in(c)
    assert c.get("/api/runs/41").json()["messages"] == []

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
    [listed] = c.get("/api/runs/41").json()["messages"]
    assert (listed["body"], listed["delivered_at"], listed["fetched_at"]) == (MESSAGE["body"], None, None)

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

    # The page says when its agent fetched them, as `canopy show run:ID` does: by a call that started after both were
    # written, a second on, so never in the millisecond the later one was.
    started = datetime.now(UTC) + timedelta(seconds=1)
    fetch = Called(tool=run_inbox.tool_name(), completed=True, input={}, started_at=started)
    with backend.open() as ctx:
        run_inbox.record_fetch(ctx.conn, "runs", 41, fetch)
    shown = c.get("/api/runs/41").json()["messages"]
    assert [m["id"] for m in shown] == [sent["message_id"], told["message_id"]]
    assert all(m["delivered_at"] is not None and m["fetched_at"] is not None for m in shown)
    # The list sends none: they are the page's alone.
    assert {r["id"]: r["messages"] for r in c.get("/api/runs").json()}[41] == []


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
