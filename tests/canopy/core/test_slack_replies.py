"""A `slack` source's replies (DESIGN §22, §30, ROADMAP M64): a listed operator's is their message, once."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from canopy.core import conversation, db, observe, records, slack_replies, sql
from canopy.core.config import Source
from canopy.core.vocab import ConnectorRunStatus
from canopy.infra import logs
from tests.canopy.helpers import KEY

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.context import Context

NAME = "slack"
OPERATOR = "U0OPERATOR"
SOURCE = Source(kind="slack", cmd=f"connector {NAME}", operators=(OPERATOR,))


def says(ts: str, body: str, *, user: str = OPERATOR, ticket: str = KEY) -> dict[str, object]:
    """A `reply` line as `canopy-connect-slack` prints one."""
    return {"kind": "reply", "ticket": ticket, "thread": "1790.000001", "ts": ts, "user": user, "body": body}


def reads(state: Path, *lines: dict[str, object] | str, **end: object) -> None:
    """Have the fake connector, as the slack source, print `lines`, then the `end` line `end` gives."""
    state.write_text(json.dumps({NAME: {"lines": list(lines), "end": {"tickets": [KEY], **end}}}))


def asked(state: Path) -> list[dict[str, Any]]:
    """What the fake connector was asked, each run in order."""
    log = state.parent / "connector.jsonl"
    return [json.loads(line)["request"] for line in log.read_text().splitlines()] if log.exists() else []


def run(ctx: Context, *, dry_run: bool = False) -> observe.Observed:
    """Run the slack source, as a tick does."""
    request = observe.Request(repo=ctx.repo)
    return slack_replies.read(ctx.conn, ctx.runner, SOURCE, request, dry_run=dry_run, log=logs.for_tick(None))


def replies(ctx: Context) -> list[records.Message]:
    """The operator's messages to KEY, oldest first."""
    found = records.fetch_all(
        ctx.conn,
        records.Message,
        sql.select("*").from_("messages").where("source = 'operator' AND subject_id = ?", KEY).order_by("id"),
    )
    return list(found)


def test_a_listed_operators_reply_is_their_message_recorded_once(ctx: Context, connector_state: Path) -> None:
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    question = db.insert_message(ctx.conn, "ticket", KEY, source="worker", kind="question", channel="run", body="A?")
    reads(connector_state, says("1790.000005", "  B, and keep the old path.  "))
    first = run(ctx)
    assert (first.status, first.recorded, first.refused, first.missed) == (
        ConnectorRunStatus.OK,
        {"reply": 1},
        {},
        None,
    )
    [reply] = replies(ctx)
    # As `canopy reply` records one: the operator's words, answering the question, on the channel it came through.
    assert (reply.kind, reply.channel, reply.body, reply.answers) == (
        "reply",
        "slack",
        "B, and keep the old path.",
        question,
    )
    assert reply.submission == "slack:1790-000005"
    assert conversation.latest_question(ctx.conn, KEY) is None
    # The reader reads the thread again on every run: the same message records nothing new.
    again = run(ctx)
    assert (again.recorded, len(replies(ctx))) == ({"already": 1}, 1)
    # Asked about the workspace, as canopy's messages to the sink name it, which files the sink's threads.
    assert asked(connector_state) == [{"repo": ctx.repo}, {"repo": ctx.repo}]


def test_a_reply_from_anyone_not_listed_records_nothing(ctx: Context, connector_state: Path) -> None:
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    reads(connector_state, says("1790.000005", "LGTM, ship it", user="U0COWORKER"))
    ran = run(ctx)
    assert (ran.status, ran.recorded, ran.refused) == (ConnectorRunStatus.OK, {}, {"unlisted": 1})
    assert replies(ctx) == []


def test_a_reply_canopy_refuses_records_nothing_and_is_counted(ctx: Context, connector_state: Path) -> None:
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    reads(
        connector_state,
        says("1790.000005", "x" * (conversation.MAX_OPERATOR + 1)),
        says("1790.000006", "on a ticket canopy never saw", ticket="PROJ-404"),
        # A line `canopy-connect-slack` would never print: its user is no Slack user id.
        says("1790.000007", "forged", user="operator"),
        says("1790.000008", "the one that counts"),
    )
    ran = run(ctx)
    assert (ran.status, ran.recorded) == (ConnectorRunStatus.OK, {"reply": 1})
    assert ran.refused == {"bad_body": 1, "unknown": 1, "reply": 1}
    assert [m.body for m in replies(ctx)] == ["the one that counts"]


def test_a_run_without_its_end_line_records_nothing(ctx: Context, connector_state: Path) -> None:
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    connector_state.write_text(json.dumps({NAME: {"lines": [says("1790.000005", "go")], "end": None}}))
    ran = run(ctx)
    assert (ran.status, ran.missed) == (ConnectorRunStatus.FAILED, "it ended without its end line")
    assert replies(ctx) == []


def test_threads_the_reader_could_not_read_make_the_run_partial(ctx: Context, connector_state: Path) -> None:
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    unread = [f"PROJ-{n}" for n in range(2, 9)]
    reads(connector_state, says("1790.000005", "go"), unread=unread)
    ran = run(ctx)
    assert (ran.status, ran.recorded) == (ConnectorRunStatus.PARTIAL, {"reply": 1})
    assert ran.missed == "did not read the Slack threads of PROJ-2, PROJ-3, PROJ-4, PROJ-5, PROJ-6 and 2 more"


def test_a_dry_run_records_no_message(ctx: Context, connector_state: Path) -> None:
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    reads(connector_state, says("1790.000005", "go"), says("1790.000006", "+1", user="U0COWORKER"))
    ran = run(ctx, dry_run=True)
    assert (ran.recorded, ran.refused) == ({"dry_run": 1}, {"unlisted": 1})
    assert replies(ctx) == []
