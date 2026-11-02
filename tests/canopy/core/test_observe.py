"""Validating and bounding what a connector prints (DESIGN §30), before anything is written."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest import mock

from canopy.core import observe, records, sql
from canopy.core.config import Source
from canopy.core.vocab import ConnectorRunStatus
from canopy.infra import logs
from tests.canopy.helpers import reads

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.context import Context
    from tests.canopy.scenario_helpers import Scenario

PR = "https://github.com/acme/api/pull/7"
VCS = Source(kind="vcs", cmd="connector github")
ASKED = observe.Request(prs=[PR], repositories=[observe.Repository("repo")], branch_prefix="agent/")
#: Every observed review item.
REVIEWS = "SELECT * FROM observed_reviews"


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


def test_a_held_checks_re_run_is_observed_at_the_same_head_and_the_run_it_repeats_kept(
    ctx: Context,
    connector_state: Path,
) -> None:
    pr = {"kind": "pr", "url": PR, "repository": "acme/api", "number": 7}
    build = {"kind": "check", "pr": PR, "head_sha": "abc1234", "name": "build", "status": "completed"}
    prints(connector_state, pr, {**build, "conclusion": "failure", "run_id": 11})
    run(ctx)
    status = {**build, "name": "deploy", "conclusion": "failure", "run_id": None}
    rerun = {**build, "status": "in_progress", "run_id": 12}
    prints(connector_state, pr, rerun, status)
    run(ctx)
    prints(connector_state, pr, {**rerun, "status": "completed", "conclusion": "failure"}, status)
    run(ctx)
    checks = records.fetch_all(ctx.conn, records.ObservedCheck, sql.frag("SELECT * FROM observed_checks ORDER BY name"))
    assert [(c.name, c.head_sha, c.run_id) for c in checks] == [("build", "abc1234", 12), ("deploy", "abc1234", None)]
    kept = records.fetch_all(ctx.conn, records.ObservedCheckRun, sql.frag("SELECT * FROM observed_check_runs"))
    assert sorted((r.run_id, r.name, r.head_sha, r.conclusion) for r in kept) == [
        (11, "build", "abc1234", "failure"),
        (12, "build", "abc1234", "failure"),
    ], "a commit status has no run to keep"


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


def test_a_prs_times_are_kept_in_the_journals_shape_and_none_when_not_printed(
    ctx: Context,
    connector_state: Path,
) -> None:
    pr = {"kind": "pr", "url": PR, "repository": "acme/api", "number": 7}
    times = {
        "created_at": "2026-10-17T09:00:00Z",
        "ready_at": "2026-10-18T08:00:00+02:00",
        "review_requested_at": "2026-10-18T09:00:00",
        "merged_at": "2026-10-19T15:00:00Z",
        "closed_at": "2026-10-19T15:00:00Z",
    }
    prints(connector_state, {**pr, **times})
    assert run(ctx).refused == {}
    [seen] = records.fetch_all(ctx.conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs"))
    assert (seen.created_at, seen.ready_at, seen.review_requested_at, seen.merged_at, seen.closed_at) == (
        "2026-10-17T09:00:00.000Z",
        "2026-10-18T06:00:00.000Z",
        "2026-10-18T09:00:00.000Z",
        "2026-10-19T15:00:00.000Z",
        "2026-10-19T15:00:00.000Z",
    )

    prints(connector_state, {**pr, "merged_at": "last Tuesday"})
    assert run(ctx).refused == {"pr": 1}, "a time canopy cannot read refuses the line"
    prints(connector_state, pr)
    run(ctx)
    [seen] = records.fetch_all(ctx.conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs"))
    assert (seen.created_at, seen.ready_at, seen.review_requested_at, seen.merged_at, seen.closed_at) == (
        None,
        None,
        None,
        None,
        None,
    ), "a reader that prints no times, as an older one, leaves none"


def test_the_request_holds_only_what_is_asked() -> None:
    assert observe.Request(prs=[]).to_json() == {"prs": []}
    tickets = [observe.AskedTicket("PROJ-1", "2026-10-18T09:00:00.000Z"), observe.AskedTicket("PROJ-2")]
    assert observe.Request(query="q", tickets=tickets).to_json() == {
        "query": "q",
        "tickets": [{"key": "PROJ-1", "comments_since": "2026-10-18T09:00:00.000Z"}, {"key": "PROJ-2"}],
    }


def test_each_item_keeps_its_journal_number_across_reads_and_a_later_one_takes_a_later_number(
    ctx: Context,
    connector_state: Path,
) -> None:
    pr = {"kind": "pr", "url": PR, "repository": "acme/api", "number": 7}
    first = {"kind": "review", "pr": PR, "item": "review", "id": 9, "time": "2026-10-18T09:00:00Z"}
    build = {"kind": "check", "pr": PR, "head_sha": "abc1234", "name": "build", "status": "in_progress", "run_id": 12}
    prints(connector_state, pr, first, build)
    run(ctx)
    [going] = records.fetch_all(ctx.conn, records.ObservedCheck, sql.frag("SELECT * FROM observed_checks"))
    assert going.number is None, "a run still going is numbered once it completes"
    # Read again, the PR's rows replaced: the first review keeps its number. One submitted since, though dated before
    # it, takes a later number, as does the run that completed.
    late = {**first, "id": 8, "time": "2026-10-18T08:00:00Z"}
    completed = {**build, "status": "completed", "conclusion": "failure"}
    prints(connector_state, pr, first, late, completed)
    run(ctx)
    numbers = {r.id: r.number for r in records.fetch_all(ctx.conn, records.ObservedReview, sql.frag(REVIEWS))}
    [done] = records.fetch_all(ctx.conn, records.ObservedCheck, sql.frag("SELECT * FROM observed_checks"))
    [kept] = records.fetch_all(ctx.conn, records.ObservedCheckRun, sql.frag("SELECT * FROM observed_check_runs"))
    assert None not in (numbers[9], numbers[8], done.number)
    assert (numbers[9] or 0) < (numbers[8] or 0) < (done.number or 0) == kept.number
    run(ctx)
    again = {r.id: r.number for r in records.fetch_all(ctx.conn, records.ObservedReview, sql.frag(REVIEWS))}
    assert again == numbers


#: GitHub's times for a merged PR, as the reader prints them and as the journal keeps them.
TIMES = {
    "created_at": "2026-09-01T09:00:00Z",
    "ready_at": "2026-09-01T10:00:00Z",
    "review_requested_at": "2026-09-01T11:00:00Z",
    "merged_at": "2026-09-02T15:00:00Z",
    "closed_at": "2026-09-02T15:00:00Z",
}
KEPT = tuple(f"{value[:-1]}.000Z" for value in TIMES.values())
#: PRs canopy observed merged, closed, and open.
MERGED = "https://github.com/acme/api/pull/1"
CLOSED = "https://github.com/acme/api/pull/2"
OPEN = "https://github.com/acme/api/pull/3"


def github_holds(state: Path, prs: dict[str, dict[str, Any]], **more: object) -> None:
    """Make the fake GitHub hold each of `prs`, its value the PR's entry: `pr`, `reviews`, and `checks`."""
    state.write_text(json.dumps({"prs": prs, **more}))


def times_of(ctx: Context, url: str) -> tuple[str | None, ...]:
    """The times the journal holds of the PR `url`."""
    pr = records.select(records.ObservedPr).where("url = ?", url).one(ctx.conn)
    assert pr is not None
    return (pr.created_at, pr.ready_at, pr.review_requested_at, pr.merged_at, pr.closed_at)


def observed_before_times(ctx: Context, github_state: Path) -> None:
    """Have a tick's read observe `MERGED`, `CLOSED`, and `OPEN` as a reader that kept no times did, with a review."""
    review = {"item": "review", "id": 11, "author": "ann", "state": "approved", "time": "2026-09-02T09:00:00Z"}
    github_holds(
        github_state,
        {
            MERGED: {"pr": {"state": "merged"}, "reviews": [review]},
            CLOSED: {"pr": {"state": "closed"}},
            OPEN: {},
        },
    )
    assert observe.read(ctx.conn, ctx.config, ctx.runner, [MERGED, CLOSED, OPEN], logs.for_tick(None)).failure is None


def test_a_backfill_asks_only_about_merged_and_closed_prs_without_times(ctx: Context, github_state: Path) -> None:
    observed_before_times(ctx, github_state)
    assert observe.missing_times(ctx.conn) == [MERGED, CLOSED], "an open PR is read again each tick"

    github_holds(github_state, {MERGED: {"pr": {"state": "merged", **TIMES}}, CLOSED: {"pr": {"state": "closed"}}})
    done = observe.backfill_times(ctx.conn, ctx.config, ctx.runner, [MERGED, CLOSED], log=logs.for_tick(None))

    assert (done.asked, done.filled, done.unread, done.failures) == (2, 1, [], [])
    assert times_of(ctx, MERGED) == KEPT
    assert observe.missing_times(ctx.conn) == [CLOSED], "a reader that printed no times leaves the PR to ask again"


def test_a_backfill_takes_only_the_times_and_keeps_those_held(ctx: Context, github_state: Path) -> None:
    observed_before_times(ctx, github_state)
    before = records.select(records.ObservedPr).where("url = ?", MERGED).one(ctx.conn)
    reviews = records.select(records.ObservedReview).all(ctx.conn)
    records.update(records.ObservedPr).set(merged_at="2026-09-03T00:00:00.000Z").where("url = ?", MERGED).run(ctx.conn)
    check = {"name": "ci", "status": "completed", "conclusion": "failure", "run_id": 9}
    github_holds(
        github_state,
        {MERGED: {"pr": {"state": "open", "title": "Renamed", **TIMES}, "reviews": [], "checks": [check]}},
    )

    observe.backfill_times(ctx.conn, ctx.config, ctx.runner, [MERGED], log=logs.for_tick(None))

    after = records.select(records.ObservedPr).where("url = ?", MERGED).one(ctx.conn)
    assert after is not None
    assert before is not None
    assert times_of(ctx, MERGED) == (*KEPT[:3], "2026-09-03T00:00:00.000Z", KEPT[4]), "a time held is kept"
    assert (after.state, after.title, after.observed_at) == (before.state, before.title, before.observed_at)
    assert records.select(records.ObservedReview).all(ctx.conn) == reviews, "a merged PR's reviews are not replaced"
    assert records.select(records.ObservedCheck).all(ctx.conn) == []
    assert records.select(records.ObservedCheckRun).all(ctx.conn) == [], "no check run is first observed today"


def test_a_backfill_names_what_it_could_not_read_and_asks_in_batches(ctx: Context, github_state: Path) -> None:
    observed_before_times(ctx, github_state)
    github_holds(
        github_state,
        {MERGED: {"pr": {"state": "merged", **TIMES}}, CLOSED: {"pr": {"state": "closed", **TIMES}}},
        unread=[CLOSED],
    )
    with mock.patch.object(observe, "BACKFILL_BATCH", 1):
        done = observe.backfill_times(ctx.conn, ctx.config, ctx.runner, [MERGED, CLOSED], log=logs.for_tick(None))
    assert (done.filled, done.unread) == (1, [CLOSED])
    assert times_of(ctx, CLOSED) == (None,) * 5
    assert [read["prs"] for read in reads(github_state)[1:]] == [[MERGED], [CLOSED]]

    github_holds(github_state, {}, down=True)
    done = observe.backfill_times(ctx.conn, ctx.config, ctx.runner, [CLOSED], log=logs.for_tick(None))
    assert (done.filled, done.unread) == (0, [CLOSED])
    assert done.failures == ["the reader ended without its end line"]


def test_canopy_backfill_fills_in_times_once_and_says_what_it_did(
    scenario: Scenario,
    ctx: Context,
    github_state: Path,
) -> None:
    observed_before_times(ctx, github_state)
    github_holds(github_state, {MERGED: {"pr": {"state": "merged", **TIMES}}}, unread=[CLOSED])

    assert scenario.operator("backfill", "--dry-run").out.startswith("2 PRs merged or closed without GitHub's times")
    assert len(reads(github_state)) == 1, "a dry run reads nothing"
    partial = scenario.operator("backfill", code=1)
    assert partial.out == "Read 1 PR of 2; filled in times on 1.\n"
    assert f"could not read {CLOSED}" in partial.err

    github_holds(github_state, {CLOSED: {"pr": {"state": "closed", **TIMES}}})
    assert scenario.operator("backfill").out == "Read 1 PR of 1; filled in times on 1.\n"
    assert scenario.operator("backfill").out.startswith("Every merged or closed PR canopy observed has GitHub's times")
