"""Validating and bounding what a connector prints (DESIGN §30), before anything is written."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest import mock

from canopy.core import observe, records, sql
from canopy.core.config import Source
from canopy.core.vocab import ConnectorRunStatus
from canopy.infra import logs

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.context import Context

PR = "https://github.com/acme/api/pull/7"
VCS = Source(kind="vcs", cmd="connector github")
ASKED = observe.Request(prs=[PR], repositories=[observe.Repository("repo")], branch_prefix="agent/")


def prints(state: Path, *lines: dict[str, Any] | str, **more: object) -> None:
    """Have the fake connector, as `github`, print `lines`, then the `end` line `more` gives, or one of all asked."""
    state.write_text(json.dumps({"github": {"lines": list(lines), **more}}))


def run(ctx: Context, request: observe.Request = ASKED) -> observe.Observed:
    """Run the `vcs` source for `request`."""
    return observe.observe(ctx.conn, ctx.config, ctx.runner, VCS, request, log=logs.for_tick(None))


def branches(ctx: Context) -> list[tuple[str, str]]:
    """Each observed branch, as (repository, name)."""
    found = records.fetch_all(
        ctx.conn,
        records.ObservedBranch,
        sql.frag("SELECT * FROM observed_branches ORDER BY name"),
    )
    return [(b.repository, b.name) for b in found]


def branch(name: str, sha: str = "abc1234") -> dict[str, Any]:
    """A `branch` line in the repository `repo`."""
    return {"kind": "branch", "repository": "repo", "name": name, "head_sha": sha}


def test_a_branch_outside_the_prefix_is_refused_and_its_repository_keeps_its_rows(
    ctx: Context,
    connector_state: Path,
) -> None:
    prints(connector_state, branch("agent/one"))
    assert run(ctx).status is ConnectorRunStatus.OK
    prints(connector_state, branch("agent/two"), branch("main"))
    found = run(ctx)
    assert (found.status, found.refused) == (ConnectorRunStatus.PARTIAL, {"branch": 1})
    assert found.missed == "did not read 1 repository (repo) whole"
    assert branches(ctx) == [("repo", "agent/one")]

    prints(connector_state, branch("agent/two"))
    run(ctx)
    assert branches(ctx) == [("repo", "agent/two")], "a branch gone from the source is gone from the journal"


def test_a_line_whose_subject_cannot_be_read_leaves_no_subject_of_its_kind_whole(
    ctx: Context,
    connector_state: Path,
) -> None:
    prints(connector_state, branch("agent/one"), {"kind": "check", "status": "completed"}, "not json")
    found = run(ctx)
    assert found.whole.prs == frozenset()
    assert found.whole.repositories == {"repo"}
    assert found.missed == f"did not read 1 PR ({PR}) whole"


def test_a_line_over_its_bound_is_refused_unread_and_leaves_nothing_whole(ctx: Context, connector_state: Path) -> None:
    prints(connector_state, branch("agent/" + "x" * 150))
    with mock.patch.object(observe, "MAX_LINE", 150):
        found = run(ctx)
    assert (found.status, found.refused, found.whole) == (ConnectorRunStatus.PARTIAL, {"unread": 1}, observe.Whole())
    assert branches(ctx) == []


def test_output_past_its_bound_is_cut_off_and_records_nothing(ctx: Context, connector_state: Path) -> None:
    prints(connector_state, *[branch(f"agent/b{n}") for n in range(20)])
    with mock.patch.object(observe, "MAX_OUTPUT", 500):
        found = run(ctx)
    assert found.status is ConnectorRunStatus.FAILED
    assert (found.missed or "").startswith("it printed more than")
    assert branches(ctx) == []


def test_a_review_comment_without_its_thread_is_refused(ctx: Context, connector_state: Path) -> None:
    review = {"kind": "review", "pr": PR, "item": "comment", "id": 5, "body": "no thread"}
    prints(connector_state, review)
    found = run(ctx)
    assert (found.refused, found.whole.prs) == ({"review": 1}, frozenset())


def test_a_time_without_an_offset_is_the_sources_utc(ctx: Context, connector_state: Path) -> None:
    pr = {"kind": "pr", "url": PR, "repository": "acme/api", "number": 7}
    check = {"kind": "check", "pr": PR, "head_sha": "abc1234", "name": "build", "status": "queued"}
    review = {"kind": "review", "pr": PR, "item": "review", "id": 9, "time": "2026-10-18T09:00:00"}
    prints(connector_state, pr, check, review, {**review, "id": 10, "time": "yesterday"})
    found = run(ctx)
    assert found.refused == {"review": 1}
    prints(connector_state, pr, check, review)
    run(ctx)
    [seen] = records.fetch_all(ctx.conn, records.ObservedReview, sql.frag("SELECT * FROM observed_reviews"))
    assert seen.created_at == "2026-10-18T09:00:00.000Z"


def test_a_review_keeps_the_commit_it_was_given_on_and_a_comment_none(ctx: Context, connector_state: Path) -> None:
    pr = {"kind": "pr", "url": PR, "repository": "acme/api", "number": 7}
    review = {"kind": "review", "pr": PR, "item": "review", "id": 9, "state": "approved", "commit": "abc1234"}
    thread = {"id": "PRRT_1", "path": "a.py", "line": 3, "side": "right", "outdated": False, "resolved": False}
    comment = {"kind": "review", "pr": PR, "item": "comment", "id": 10, "commit": "abc1234", "thread": thread}
    prints(connector_state, pr, review, comment, {**review, "id": 11, "commit": "not a sha"})
    assert run(ctx).refused == {"review": 1}
    prints(connector_state, pr, review, comment)
    run(ctx)
    seen = records.fetch_all(ctx.conn, records.ObservedReview, sql.frag("SELECT * FROM observed_reviews ORDER BY id"))
    assert [(r.id, r.commit_sha) for r in seen] == [(9, "abc1234"), (10, None)]


def test_a_prs_title_is_kept_to_one_line_cut_and_marked_and_none_when_not_printed(
    ctx: Context,
    connector_state: Path,
) -> None:
    pr = {"kind": "pr", "url": PR, "repository": "acme/api", "number": 7}
    prints(connector_state, {**pr, "title": "Retry the upstream\non a 503 " + "x" * 300})
    assert run(ctx).refused == {}
    [seen] = records.fetch_all(ctx.conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs"))
    assert (seen.title or "").startswith("Retry the upstream on a 503 x")
    assert (len(seen.title or ""), (seen.title or "").endswith("...")) == (observe.MAX_TITLE, True)

    prints(connector_state, pr)
    run(ctx)
    [seen] = records.fetch_all(ctx.conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs"))
    assert seen.title is None, "a reader that prints no title leaves none, rather than the last one read"


def test_the_request_holds_only_what_is_asked() -> None:
    assert observe.Request(prs=[]).to_json() == {"prs": []}
    tickets = [observe.AskedTicket("PROJ-1", "2026-10-18T09:00:00.000Z"), observe.AskedTicket("PROJ-2")]
    assert observe.Request(query="q", tickets=tickets).to_json() == {
        "query": "q",
        "tickets": [{"key": "PROJ-1", "comments_since": "2026-10-18T09:00:00.000Z"}, {"key": "PROJ-2"}],
    }
