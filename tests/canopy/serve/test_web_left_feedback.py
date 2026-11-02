"""Feedback a ticket's review cursors left with no worker, on its page and sent from it (DESIGN §7).

Over the mock journal, whose ABC-103 has two review comments tick 2 passed: the page lists them as `canopy show` does,
and a send writes the operator's reply `canopy send KEY N` would.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from canopy.core import db
from canopy.core.vocab import PassReason
from canopy.serve.schema.ticket import LeftFeedback
from tests.canopy.helpers import present
from tests.canopy.web_helpers import SECRET, client, signed_in

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def test_the_api_names_every_reason_canopy_records() -> None:
    assert set(get_args(LeftFeedback.model_fields["reason"].annotation)) == {r.value for r in PassReason}


def test_a_tickets_page_lists_the_feedback_it_left_with_why_and_the_tick(backend: Backend) -> None:
    found = client(None, backend).get("/api/tickets/ABC-103").json()["left_feedback"]
    assert [(f["number"], f["id"], f["author"], f["path"], f["line"], f["reason"], f["tick_id"]) for f in found] == [
        (1, 2_468_020_011, "carol", "src/billing/client.ts", 42, "optional", 2),
        (2, 2_468_020_037, "carol", "src/billing/v1.ts", 8, "would_reset_approval", 2),
    ]
    assert client(None, backend).get("/api/tickets/ABC-102").json()["left_feedback"] == []


def test_left_feedback_sent_from_the_web_reaches_the_ticket_as_the_cli_sends_it(backend: Backend) -> None:
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)
    url = "/api/tickets/ABC-103/sends"
    sent = {"numbers": [2], "submission": "left-0001"}

    assert c.post(url, json=sent, headers={"origin": headers["origin"]}).status_code == 403
    assert c.post(url, json={**sent, "numbers": []}, headers=headers).status_code == 422
    refused = c.post(url, json={**sent, "numbers": [9]}, headers=headers)
    assert (refused.status_code, refused.json()["detail"]["guard"]) == (409, "bad_reference")

    recorded = c.post(url, json=sent, headers=headers).json()
    assert {k: recorded[k] for k in ("numbers", "new")} == {"numbers": [2], "new": True}
    with backend.open() as ctx:
        message = present(db.get_message(ctx.conn, recorded["message_id"]))
        assert (message.subject_id, message.source, message.channel) == ("ABC-103", "operator", "web")
        assert message.body == (
            "Address this review item, which the loop left with no worker: review comment 2468020037 by carol on "
            "https://github.com/acme/web/pull/91 at src/billing/v1.ts:8 (left as would_reset_approval)."
        )
    again = c.post(url, json=sent, headers=headers).json()
    assert (again["message_id"], again["new"]) == (recorded["message_id"], False)
