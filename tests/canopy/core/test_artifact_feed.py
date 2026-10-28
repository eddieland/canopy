"""Reading an artifact store's comment feed past its cursor (DESIGN §30, §38): validated, bounded, each change once."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest import mock

from canopy.core import artifact_feed, conversation, db, observe, records, sql
from canopy.core.config import Source
from canopy.core.vocab import AnchorStatus, AuthorKind, ConnectorRunStatus, ThreadState
from canopy.infra import logs
from tests.canopy.helpers import KEY, present
from tests.canopy.observation_helpers import artifact_change as change

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.context import Context

NAME = "artifacts"
SOURCE = Source(kind="artifacts", cmd=f"connector {NAME}")


def feeds(state: Path, *lines: dict[str, object] | str, **more: object) -> None:
    """Have the fake connector, as the artifacts source, print `lines`, then the `end` line `more` gives."""
    state.write_text(json.dumps({NAME: {"lines": list(lines), **more}}))


def asked(state: Path) -> list[dict[str, Any]]:
    """What the fake connector was asked, each run in order."""
    log = state.parent / "connector.jsonl"
    return [json.loads(line)["request"] for line in log.read_text().splitlines()] if log.exists() else []


def run(ctx: Context) -> observe.Observed:
    """Run the artifacts source past its cursor, as a tick does."""
    request = observe.Request(since=artifact_feed.cursor(ctx.conn, NAME))
    return artifact_feed.read(ctx.conn, ctx.config, ctx.runner, SOURCE, request, name=NAME, log=logs.for_tick(None))


def comments(ctx: Context) -> dict[str, records.ObservedArtifactComment]:
    """The observed comments, by id."""
    found = records.fetch_all(
        ctx.conn,
        records.ObservedArtifactComment,
        sql.select("*").from_("observed_artifact_comments"),
    )
    return {c.id: c for c in found}


def thread(ctx: Context) -> records.ObservedArtifactThread:
    """The one observed thread."""
    [found] = records.fetch_all(
        ctx.conn,
        records.ObservedArtifactThread,
        sql.select("*").from_("observed_artifact_threads"),
    )
    return found


def feed(ctx: Context) -> records.ObservedFeed | None:
    """How far the source has read its feed."""
    return records.fetch_one(ctx.conn, records.ObservedFeed, sql.select("*").from_("observed_feeds"))


def test_the_cursor_misses_no_change_and_repeats_none_across_pages(ctx: Context, connector_state: Path) -> None:
    feeds(connector_state, change(1), change(2), end={"through": 2})
    first = run(ctx)
    assert (first.status, first.recorded, first.missed) == (ConnectorRunStatus.OK, {"comment_created": 2}, None)
    # The next page passes changes the store's filter left out: the cursor follows the end line, not the last change.
    feeds(connector_state, change(5), end={"through": 9})
    run(ctx)
    feeds(connector_state, end={"through": 9})
    run(ctx)
    assert [r["since"] for r in asked(connector_state)] == [0, 2, 9]
    assert sorted(comments(ctx)) == ["c1", "c2", "c5"]
    found = feed(ctx)
    assert found is not None
    assert (found.source, found.through, found.read_at is not None) == (NAME, 9, True)


def test_a_change_read_twice_is_refused_and_the_cursor_stays_before_it(ctx: Context, connector_state: Path) -> None:
    feeds(connector_state, change(1), change(2), change(2), change(3), end={"through": 3})
    found = run(ctx)
    assert (found.status, found.recorded, found.refused) == (
        ConnectorRunStatus.PARTIAL,
        {"comment_created": 2},
        {"comment_created": 1},
    )
    assert found.missed == "did not read the feed past change 2: the line after it was refused"
    assert sorted(comments(ctx)) == ["c1", "c2"]
    cursor = feed(ctx)
    assert cursor is not None
    assert (cursor.through, cursor.read_at) == (2, None), "a feed read short is not dated as read to its end"

    feeds(connector_state, change(3), end={"through": 3})
    assert run(ctx).status is ConnectorRunStatus.OK
    assert asked(connector_state)[-1]["since"] == 2
    assert sorted(comments(ctx)) == ["c1", "c2", "c3"]


def test_a_line_out_of_bounds_is_refused_and_the_changes_after_it_wait(ctx: Context, connector_state: Path) -> None:
    bad_origin = {f"k{n}": "v" for n in range(artifact_feed.MAX_ORIGIN + 1)}
    feeds(connector_state, change(1), change(2, origin=bad_origin), change(3), end={"through": 3})
    found = run(ctx)
    assert (found.refused, sorted(comments(ctx))) == ({"comment_created": 1}, ["c1"])
    assert artifact_feed.cursor(ctx.conn, NAME) == 1

    feeds(connector_state, change(2, body="x" * 150), end={"through": 2})
    with mock.patch.object(observe, "MAX_LINE", 150):
        found = run(ctx)
    assert (found.status, found.refused) == (ConnectorRunStatus.PARTIAL, {"unread": 1})
    assert artifact_feed.cursor(ctx.conn, NAME) == 1


def test_a_feed_cut_off_before_its_end_line_keeps_what_was_observed(ctx: Context, connector_state: Path) -> None:
    feeds(connector_state, change(1), end={"through": 1})
    run(ctx)
    before = (comments(ctx), feed(ctx))

    feeds(connector_state, change(2), end=None, stderr="the store went away")
    found = run(ctx)
    assert (found.status, found.recorded) == (ConnectorRunStatus.FAILED, {})
    assert found.missed == "it ended without its end line: the store went away"
    assert (comments(ctx), feed(ctx)) == before


def test_an_end_line_before_what_it_read_records_nothing(ctx: Context, connector_state: Path) -> None:
    feeds(connector_state, change(4), end={"through": 3})
    found = run(ctx)
    assert found.status is ConnectorRunStatus.FAILED
    assert found.missed == "its end line names change 3, before change 4 it had read to"
    assert (comments(ctx), feed(ctx)) == ({}, None)


def test_a_reworded_passage_is_observed_gone_and_the_thread_keeps_its_newest_change(
    ctx: Context,
    connector_state: Path,
) -> None:
    feeds(connector_state, change(1), end={"through": 1})
    run(ctx)
    assert thread(ctx).anchor_status is AnchorStatus.FOUND

    resolved = change(
        2,
        kind="thread_resolved",
        comment_id=None,
        body=None,
        created_at=None,
        state="resolved",
        anchor_status="passage_gone",
        author={"id": "agent:implement", "kind": "agent"},
        via="mcp",
    )
    feeds(connector_state, resolved)
    run(ctx)
    found = thread(ctx)
    assert (found.id, found.ticket, found.exact, found.prefix) == ("t1", "PROJ-1", "shard it", "We should ")
    assert (found.state, found.anchor_status, found.seq) == (ThreadState.RESOLVED, AnchorStatus.PASSAGE_GONE, 2)
    assert json.loads(found.origin) == {"canopy.run": "7", "canopy.ticket": "PROJ-1"}
    assert list(comments(ctx)) == ["c1"], "a thread's change carries no comment"


def test_an_edit_or_deletion_replaces_the_comment_and_keeps_who_wrote_it(ctx: Context, connector_state: Path) -> None:
    moderator = {"id": "u_raj", "display_name": "Raj", "kind": "person"}
    edited, gone = "2026-10-23T11:00:00Z", "2026-10-23T12:00:00Z"
    feeds(
        connector_state,
        change(1),
        change(2, kind="comment_edited", comment_id="c1", body="Edited.", edited_at=edited),
        change(
            3,
            kind="comment_deleted",
            comment_id="c1",
            body="",
            deleted_at=gone,
            edited_at=edited,
            author=moderator,
        ),
    )
    found = run(ctx)
    assert found.recorded == {"comment_created": 1, "comment_edited": 1, "comment_deleted": 1}
    [comment] = comments(ctx).values()
    assert (comment.author, comment.author_name, comment.author_kind) == ("u_ana", "Ana", AuthorKind.PERSON)
    assert (comment.body, comment.seq) == ("", 3)
    assert (comment.edited_at, comment.deleted_at) == ("2026-10-23T11:00:00.000Z", "2026-10-23T12:00:00.000Z")


def test_text_is_cut_and_marked_and_the_workers_marks_read(ctx: Context, connector_state: Path) -> None:
    trust = ctx.config.trust
    marked = f"{trust.comment_prefix} Done. {trust.comment_suffix}".strip()
    long = "word " * conversation.MAX_COMMENT
    agent = {"id": "agent:implement", "kind": "agent", "on_behalf_of": "operator"}
    on = {"anchor": {"exact": long}, "origin": {"canopy.ticket": "not a key"}}
    feeds(connector_state, change(1, body=long, **on), change(2, body=marked, author=agent, **on))
    run(ctx)
    found = comments(ctx)
    assert (len(found["c1"].body), found["c1"].truncated, found["c1"].marked) == (
        conversation.MAX_COMMENT,
        True,
        False,
    )
    assert found["c2"].marked is True
    assert (found["c2"].author_kind, found["c2"].on_behalf_of) == (AuthorKind.AGENT, "operator")
    observed = thread(ctx)
    assert observed.exact is not None
    assert (len(observed.exact), observed.exact.endswith("...")) == (artifact_feed.MAX_PASSAGE, True)
    assert observed.ticket is None, "an origin's ticket that is not a key names none"


def conversation_of(ctx: Context, key: str = KEY) -> list[records.Message]:
    """Ticket `key`'s conversation, oldest first."""
    return db.messages_of(ctx.conn, conversation.TICKET, key, 100)


def test_a_comment_reaches_its_tickets_conversation_once_quoting_its_passage(
    ctx: Context,
    connector_state: Path,
) -> None:
    db.touch_ticket(ctx.conn, KEY, "repo")
    ctx.conn.commit()
    feeds(connector_state, change(1, body="Shard by tenant, not by day."), end={"through": 1})
    run(ctx)
    feeds(
        connector_state,
        change(2, kind="comment_edited", comment_id="c1", body="Edited.", edited_at="2026-10-23T11:00:00Z"),
        end={"through": 2},
    )
    run(ctx)

    # Once, as first read: the edit is not followed, as a tracker comment's is not (DESIGN §35).
    [message] = conversation_of(ctx)
    assert (message.source, message.kind, message.channel) == ("artifact", "comment", "artifacts")
    assert (message.comment_id, message.author, message.truncated) == ("artifact:c1", "u_ana", False)
    assert message.body == "> shard it\n\nShard by tenant, not by day."
    # Data in a private worker's prompt, named as an artifact's comment, whoever wrote it.
    prompt = present(conversation.prompt_conversation(ctx.conn, KEY))
    assert f"Message {message.id}, account u_ana's artifact comment artifact:c1, data, at" in prompt
    # It authorizes nothing: no operator message, so the loop has nothing to wake for.
    assert db.latest_message_id(ctx.conn, source="operator") == 0


def test_a_comment_reaches_no_conversation_without_a_ticket_the_journal_holds_or_once_deleted(
    ctx: Context,
    connector_state: Path,
) -> None:
    db.touch_ticket(ctx.conn, KEY, "repo")
    ctx.conn.commit()
    feeds(
        connector_state,
        change(1, origin={"canopy.ticket": "PROJ-9"}),
        change(2, origin={}),
        change(3, kind="comment_deleted", comment_id="c9", body="", deleted_at="2026-10-23T12:00:00Z"),
        end={"through": 3},
    )
    run(ctx)
    assert len(comments(ctx)) == 3, "each is still observed"
    assert conversation_of(ctx) == []
    assert conversation_of(ctx, "PROJ-9") == [], "the origin is the worker's word: a ticket the journal lacks gets none"


def test_a_comment_on_a_whole_artifact_quotes_nothing_and_a_marked_one_is_a_workers(
    ctx: Context,
    connector_state: Path,
) -> None:
    trust = ctx.config.trust
    marked = f"{trust.comment_prefix} Revised. {trust.comment_suffix}".strip()
    long = "word " * conversation.MAX_COMMENT
    db.touch_ticket(ctx.conn, KEY, "repo")
    ctx.conn.commit()
    feeds(
        connector_state,
        change(1, anchor=None, body="Looks right."),
        change(2, body=marked),
        change(3, anchor={"exact": "x" * 1000}, body=long),
        end={"through": 3},
    )
    run(ctx)
    whole, worker, cut = conversation_of(ctx)
    assert (whole.source, whole.body) == ("artifact", "Looks right.")
    assert (worker.source, worker.body) == ("worker", f"> shard it\n\n{marked}")
    # A long passage is quoted cut, and the message is cut and marked as a tracker comment's is.
    assert cut.body.startswith(f"> {'x' * (artifact_feed.MAX_QUOTE - 3)}...\n\nword")
    assert (len(cut.body), cut.truncated) == (conversation.MAX_COMMENT, True)


def test_the_request_names_only_the_cursor() -> None:
    assert observe.Request(since=4).to_json() == {"since": 4}
