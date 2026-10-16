"""The web UI's search over the journal (DESIGN §22, Search; ROADMAP M31): each source it reads, its bounds, and the
route. Reads only."""

import json

import pytest

from canopy.core import conversation, db, search
from canopy.core.context import Context
from canopy.core.vocab import ChoreRunStatus, RunStatus
from canopy.serve.backend import Backend
from tests.canopy.helpers import running_run
from tests.canopy.web_helpers import SECRET, client


def where(found: search.Found) -> list[tuple[str, str | int | None, str | None]]:
    return [(h.source, h.ticket_key or h.chore or h.tick_id, h.label) for h in found.hits]


def test_a_ticket_is_found_by_its_branchs_slug_the_words_of_its_title(ctx: Context) -> None:
    run = running_run(ctx, "PROJ-7", private=False)
    ctx.conn.execute("UPDATE tickets SET branch = 'agent/PROJ-7-fix-login-redirect' WHERE key = 'PROJ-7'")
    db.set_unit(ctx.conn, "PROJ-7", ctx.repo, "web", pr_url="https://example.test/acme/web/pull/12")
    assert db.get_run(ctx.conn, run) is not None

    assert where(search.search(ctx.conn, "login redirect")) == [("ticket", "PROJ-7", None)]
    assert where(search.search(ctx.conn, "pull/12")) == [("ticket", "PROJ-7", None)]
    assert where(search.search(ctx.conn, "proj-7")) == [("ticket", "PROJ-7", None)]


def test_a_runs_report_and_question_are_found_as_its_tickets_messages(ctx: Context) -> None:
    run = running_run(ctx, "PROJ-1")
    result = {"status": "blocked", "summary": "Retries now back off exponentially.", "question": "Cap at 30s?"}
    db.finish_ticket_run(
        ctx.conn,
        run,
        RunStatus.BLOCKED,
        json.dumps(result),
        messages=conversation.run_messages(RunStatus.BLOCKED, json.dumps(result)),
    )

    found = search.search(ctx.conn, "BACK OFF")
    assert where(found) == [("message", "PROJ-1", "report")]
    assert found.hits[0].run_id == run
    assert found.hits[0].snippet == "Retries now back off exponentially."
    assert where(search.search(ctx.conn, "cap 30s")) == [("message", "PROJ-1", "question")]


def test_a_chore_runs_summary_and_findings_and_its_notes_are_found(ctx: Context) -> None:
    tick = db.start_tick(ctx.conn, dry_run=False)
    run = db.insert_chore_run(ctx.conn, tick_id=tick, chore="deps", logs_dir=ctx.state_dir / "chores")
    finding = {"id": "npm/lodash", "title": "lodash has an advisory", "detail": "Prototype pollution in merge."}
    db.finish_run(
        ctx.conn,
        "chore_runs",
        run,
        ChoreRunStatus.OK,
        json.dumps({"status": "ok", "summary": "Checked 3", "findings": [finding]}),
    )
    # A result that is not JSON, or whose findings are not objects, is passed over rather than failing the search.
    bad = db.insert_chore_run(ctx.conn, tick_id=tick, chore="deps", logs_dir=ctx.state_dir / "chores")
    db.finish_run(ctx.conn, "chore_runs", bad, ChoreRunStatus.FAILED, "not json")
    odd = db.insert_chore_run(ctx.conn, tick_id=tick, chore="deps", logs_dir=ctx.state_dir / "chores")
    db.finish_run(
        ctx.conn, "chore_runs", odd, ChoreRunStatus.OK, json.dumps({"summary": "odd", "findings": ["lodash", 3]})
    )
    db.insert_message(
        ctx.conn, conversation.CHORE, "deps", source="operator", kind="reply", channel="web", body="Ignore lodash."
    )

    found = search.search(ctx.conn, "lodash")
    assert where(found) == [("message", "deps", "note"), ("chore_run", "deps", "ok")]
    assert found.hits[1].run_id == run
    assert found.hits[1].snippet == "Checked 3 lodash has an advisory: Prototype pollution in merge."
    assert where(search.search(ctx.conn, "pollution merge")) == [("chore_run", "deps", "ok")]


def test_a_decisions_rationale_and_a_ticks_summary_are_found_with_their_tick(ctx: Context) -> None:
    tick = db.start_tick(ctx.conn, dry_run=False)
    db.touch_ticket(ctx.conn, "PROJ-2", ctx.repo)
    db.record_decision(ctx.conn, tick, "PROJ-2", "wait", "CI is still running on the flaky suite")
    db.finish_tick(ctx.conn, tick, "ok", "waited on the flaky suite")

    found = search.search(ctx.conn, "flaky suite")
    assert where(found) == [("decision", "PROJ-2", "wait"), ("tick", tick, "ok")]
    assert found.hits[0].tick_id == tick


def test_every_word_must_be_in_one_field_and_wildcards_are_literal(ctx: Context) -> None:
    tick = db.start_tick(ctx.conn, dry_run=False)
    db.record_decision(ctx.conn, tick, None, "wait", "coverage at 50% in some_module")
    db.record_decision(ctx.conn, tick, None, "wait", "coverage at 500 in somexmodule")

    assert [h.snippet for h in search.search(ctx.conn, "50% some_").hits] == ["coverage at 50% in some_module"]
    assert search.search(ctx.conn, "coverage nowhere").hits == []
    assert search.search(ctx.conn, "back\\slash").hits == []


def test_each_source_gives_its_newest_hits_and_says_when_it_has_more(ctx: Context) -> None:
    tick = db.start_tick(ctx.conn, dry_run=False)
    ids = [
        db.record_decision(ctx.conn, tick, None, "wait", f"decision {i} waits") for i in range(search.PER_SOURCE + 3)
    ]

    found = search.search(ctx.conn, "waits")
    assert [h.snippet for h in found.hits] == [f"decision {i} waits" for i in reversed(range(3, len(ids)))]
    assert found.more == ["decision"]
    assert search.search(ctx.conn, "decision 2 waits").more == []


def test_a_snippet_is_one_line_cut_around_the_first_match() -> None:
    text = "start\x1b[2J\n" + "a" * 300 + " needle " + "b" * 300
    cut = search.snippet(text, ("NEEDLE",))
    assert len(cut) == search.SNIPPET
    assert cut.startswith("…a")
    assert cut.endswith("b…")
    assert "needle" in cut
    assert "\x1b" not in cut
    assert "\n" not in cut
    # Near the start, nothing is cut before it.
    assert search.snippet("needle " + "c" * 300, ("needle",)).startswith("needle c")
    assert search.snippet("short\ttext", ("text",)) == "short text"


def test_a_query_is_two_to_two_hundred_characters_of_at_most_eight_words() -> None:
    assert search.words("  fix   login fix ") == ("fix", "login")
    for bad in ("a", " a ", "x" * 201, "a b c d e f g h i"):
        with pytest.raises(search.BadQueryError):
            search.words(bad)


def test_the_route_searches_the_mock_journal_and_refuses_a_bad_query(backend: Backend) -> None:
    c = client(None, backend)
    body = c.get("/api/search", params={"q": "search"}).json()
    assert body["words"] == ["search"]
    assert [(h["source"], h["ticket_key"], h["label"]) for h in body["hits"]] == [
        ("ticket", "ABC-099", "review_pending"),
        ("message", "ABC-099", "report"),
    ]
    assert body["hits"][1]["run_id"] == 39
    assert body["more"] == []

    for q in ("a", "x" * 201, "a b c d e f g h i"):
        answer = c.get("/api/search", params={"q": q})
        assert answer.status_code == 422
        # One shape for every 422, the schema's: a list of validation errors naming the parameter.
        [error] = answer.json()["detail"]
        assert error["loc"] == ["query", "q"]
    assert c.get("/api/search").status_code == 422


def test_the_route_needs_a_session(backend: Backend) -> None:
    assert client(None, backend, key=SECRET).get("/api/search", params={"q": "search"}).status_code == 401
