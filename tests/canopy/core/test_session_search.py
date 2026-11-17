"""Sessions found by what they said, did, and read, through the index, each hit's snippet read from the record."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.cli.main import main
from canopy.core import db, records, session_index, session_list, session_search
from canopy.core.session_search import Mark
from canopy.runtime.implementation import Version
from tests.canopy.helpers import Kept, called, recorded, replied, runtime_forgets, runtime_record, sent, wrote

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    import pytest

    from canopy.core.context import Context
    from canopy.core.session_list import Listed, Whose
    from tests.conftest import CanopyEnv

#: 2026-11-17T12:00:00Z, in milliseconds since the epoch.
NOON_MS = 1_794_916_800_000


def kept(ctx: Context, *sessions: Kept) -> None:
    """Keep `sessions` in the runtime's record and the journal, and index them, as the loop's waits do."""
    runtime_record(*sessions)
    recorded(ctx.conn, *sessions)
    session_index.step(ctx.conn, ctx.state_dir, version=Version.TWO, exclude=())


def hits(ctx: Context, words: str, whose: Whose = "outside") -> list[Listed]:
    """The sessions a search of `words` finds, best first, as the list shows them."""
    return list(
        session_list.listing(
            ctx.conn,
            whose=whose,
            state_dir=ctx.state_dir,
            exclude=(),
            words=words.split(),
            text=Version.TWO,
        ).sessions,
    )


def snippets(found: Sequence[Listed]) -> list[str | None]:
    """Each hit's snippet, its words marked."""
    return [
        session_search.marked_text(s.hit.snippet) if s.hit is not None and s.hit.snippet is not None else None
        for s in found
    ]


def ran_in(conn: sqlite3.Connection, session_id: str) -> None:
    """Record a tick whose overseer ran in session `session_id`, so the session is canopy's."""
    tick_id = db.start_tick(conn, dry_run=False)
    records.update(records.Tick).set(session_id=session_id).where("id = ?", tick_id).run(conn)


def test_a_session_is_found_by_what_it_was_sent_what_its_agent_wrote_or_its_title_with_a_message(ctx: Context) -> None:
    kept(
        ctx,
        Kept("ses_sent", "/home/me", title="Birds", messages=[sent("count the sanderling flock")], updated=NOON_MS),
        Kept(
            "ses_wrote",
            "/home/me",
            title="Shore survey",
            messages=[replied(wrote("the turnstone was on the jetty"), called("read", {"path": "t.md"}, "a ruff"))],
            updated=NOON_MS + 1,
        ),
    )

    assert snippets(hits(ctx, "sanderling")) == ["count the *sanderling* flock"]
    assert snippets(hits(ctx, "turnstone jetty")) == ["the *turnstone* was on the *jetty* t.md a ruff"]
    # Its title and a message hold the words between them; a word the tool call read finds it too.
    assert [s.session_id for s in hits(ctx, "survey ruff")] == ["ses_wrote"]
    # A title that holds every word finds its session with no snippet.
    [titled] = hits(ctx, "shore")
    assert titled.hit is not None
    assert (titled.title, titled.hit.snippet, titled.hit.more) == ("Shore survey", None, 0)
    assert hits(ctx, "sanderling jetty") == []


def test_one_of_canopys_is_never_found_by_what_it_was_sent_and_opens_its_run(ctx: Context) -> None:
    ran_in(ctx.conn, "ses_tick")
    kept(
        ctx,
        Kept(
            "ses_tick",
            "/work",
            title="Tick",
            messages=[sent("the state block lists a shrike"), replied(wrote("dispatched the shrike's ticket"))],
            updated=NOON_MS,
        ),
    )

    [found] = hits(ctx, "shrike", "canopy")

    assert snippets([found]) == ["dispatched the *shrike*'s ticket"]
    assert found.made_by is not None
    assert found.made_by.table == "ticks"
    assert found.hit is not None
    assert found.hit.more == 0
    assert hits(ctx, "state block", "canopy") == []
    assert hits(ctx, "shrike") == []


def test_hits_are_ranked_a_word_in_a_title_weighing_more_and_say_how_many_more_messages_hold_them(ctx: Context) -> None:
    kept(
        ctx,
        Kept(
            "ses_body",
            "/home/me",
            title="Errands",
            messages=[sent("buy a gannet print"), sent("frame the gannet print"), sent("hang it")],
            updated=NOON_MS + 1,
        ),
        Kept("ses_title", "/home/me", title="Gannet", messages=[sent("unrelated")], updated=NOON_MS),
    )

    found = hits(ctx, "gannet")

    assert [s.session_id for s in found] == ["ses_title", "ses_body"]
    assert found[1].hit is not None
    assert found[1].hit.more == 1


def test_a_snippet_is_read_from_the_record_and_there_is_none_for_a_session_it_no_longer_keeps(ctx: Context) -> None:
    kept(
        ctx,
        Kept("ses_a", "/home/me", messages=[sent("a skua\N{RIGHT-TO-LEFT OVERRIDE} over\tthe\nbay")], updated=NOON_MS),
    )
    [hit] = hits(ctx, "skua")
    assert hit.hit is not None
    assert hit.hit.snippet == [Mark("a "), Mark("skua", marked=True), Mark(" over the bay")]

    runtime_forgets("ses_a")
    [gone] = hits(ctx, "skua")

    assert gone.hit is not None
    assert gone.hit.snippet is None


def test_a_query_in_the_indexs_own_syntax_is_searched_as_words_and_none_is_an_error(ctx: Context) -> None:
    """As memory's search holds its own: FTS5's operators, quotes, and column filters are words, or nothing."""
    kept(
        ctx,
        Kept("ses_a", "/home/me", title="A title", messages=[sent("the NEAR tern AND the far one")], updated=NOON_MS),
    )

    assert [s.session_id for s in hits(ctx, 'tern" OR "x')] == []
    assert [s.session_id for s in hits(ctx, "NEAR( tern* AND")] == ["ses_a"]
    # A column filter is two words, one the title holds and one a message holds.
    assert [s.session_id for s in hits(ctx, "{title}: ^tern")] == ["ses_a"]
    assert hits(ctx, '" * ( )') == []
    assert hits(ctx, "-") == []


def test_canopy_sessions_finds_one_by_what_it_said_or_says_why_text_is_titles(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.append_user("\n[sessions]\nsearch = 'text'\n")
    sessions = (
        Kept(
            "ses_mine",
            "/home/me/notes",
            title="Notes",
            messages=[sent("where did the godwit go"), replied(wrote("the godwit flew south"))],
            updated=NOON_MS,
        ),
    )
    runtime_record(*sessions)
    with canopy_env.journal() as conn:
        recorded(conn, *sessions)
        if canopy_env.runtime is Version.TWO:
            session_index.step(conn, canopy_env.state_dir, version=Version.TWO, exclude=())

    assert main(["sessions", "godwit"]) == 0
    printed = capsys.readouterr().out
    assert main(["sessions", "godwit", "--json"]) == 0
    as_json = json.loads(capsys.readouterr().out)

    if canopy_env.runtime is Version.TWO:
        assert "Sessions outside canopy that hold godwit, best match first:" in printed
        assert "*godwit*" in printed
        assert "(1 more message holds them)" in printed
        assert "The index holds 1 session" in printed
        assert as_json["search"] == "text"
        assert as_json["sessions"][0]["hit"]["more"] == 1
        assert as_json["index"]["sessions"] == 1
    else:
        assert "Sessions outside canopy whose title holds godwit: none." in printed
        assert "runtime.version 1 is deprecated" in printed
        assert (as_json["search"], as_json["index"]) == ("titles", None)
        assert as_json["why_titles"] is not None
