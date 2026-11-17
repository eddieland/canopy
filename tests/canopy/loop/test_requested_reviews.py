"""Tests for the operator's review requests: derived, answered by the harness, and compared (§21, §30, §37)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.cli import agreement as agreement_cli
from canopy.core import db, records, review_runs
from canopy.core.vocab import Decider, PrState, RequestAction, ReviewRunStatus, TickStatus
from canopy.infra import logs, resources
from canopy.loop import agreement, harness_dispatches, harness_reviews, outlook, requested_reviews, review_tools, tools
from canopy.reviews import review_requests
from canopy.reviews import start as review_start
from canopy.reviews import view as review_view
from tests.canopy.helpers import KEY, context, in_tick, sources, waits
from tests.canopy.scenario_helpers import Scenario, dispatches, review_ends, review_waits, reviews
from tests.conftest import SHARED_TOML

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping

    from canopy.core.context import Context
    from tests.conftest import CanopyEnv

#: A PR of the workspace's one repository, whose clone URL is `https://example.test/acme/repo.git`.
PR = "https://example.test/acme/repo/pull/12"
#: A PR of a repository the workspace does not have.
ELSEWHERE = "https://example.test/acme/other/pull/3"
HEAD = "a" * 40
#: The tests' `vcs` source: the fake connector, playing GitHub.
GITHUB = {"kind": "vcs", "cmd": "connector github", "timeout_minutes": 1}
#: What a start of a run or a review, or a guard's refusal of one, records as its action.
STARTS = ("dispatch:", "refused:")
#: One of the loop's own PRs, KEY's unit's, which the overseer reviews below the operator's requests in §7's order.
OWN = "https://example.test/acme/repo/pull/13"
REVIEWER = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer --format json {prompt}"


def requested(conn: sqlite3.Connection, url: str = PR) -> records.ReviewRequest:
    """The operator's open request for a review of `url`, made just now."""
    records.insert(records.ReviewRequest, pr_url=url, created_at=db.now(), channel="cli").run(conn)
    found = review_requests.open_request(conn, url)
    assert found is not None
    return found


def observed(
    conn: sqlite3.Connection,
    url: str = PR,
    *,
    state: PrState = PrState.OPEN,
    draft: bool = False,
    minutes_ago: int = 0,
) -> None:
    """The `vcs` source's read of `url` at HEAD, `minutes_ago`."""
    at = db.format_time(datetime.now(UTC) - timedelta(minutes=minutes_ago))
    records.insert(
        records.ObservedPr,
        url=url,
        repository="acme/repo",
        number=int(url.rsplit("/", 1)[-1]),
        head_sha=HEAD,
        state=state,
        draft=draft,
        observed_at=at,
    ).run(conn)


def review_ran(ctx: Context, status: ReviewRunStatus, sha: str = HEAD) -> None:
    """A review of PR at `sha`, the loop's own, that is `status` now."""
    with in_tick(ctx.conn) as tick_id:
        run_id = review_runs.insert_review_run(
            ctx.conn,
            tick_id=tick_id,
            pr_url=PR,
            sha=sha,
            ticket=None,
            repo="repo",
            purpose=review_requests.PURPOSE,
            logs_dir=ctx.workspace.state_dir,
        )
    ended = None if status is ReviewRunStatus.RUNNING else db.now()
    records.update(records.ReviewRun).set(status=status, ended_at=ended).where("id = ?", run_id).run(ctx.conn)


def derived(ctx: Context) -> list[tuple[str, RequestAction, str | None, str | None]]:
    """What the harness would do with each open request now: its PR, action, reason, and what is stale."""
    found = requested_reviews.derive(ctx, datetime.now(UTC))
    return [(d.pr_url, d.action, d.reason, d.stale) for d in found]


def test_a_request_at_an_unreviewed_head_starts_its_review(ctx: Context) -> None:
    """Its checks are no reason to wait: the operator asked for the review now."""
    requested(ctx.conn)
    observed(ctx.conn)
    [found] = requested_reviews.derive(ctx, datetime.now(UTC))
    assert (found.action, found.reason, found.head_sha, found.stale) == (RequestAction.START, None, HEAD, None)


def test_a_head_already_reviewed_ends_the_request_reviewed(ctx: Context) -> None:
    """A request made after its head's review is answered by it, as the review-run tool's refusal answers it."""
    observed(ctx.conn)
    review_ran(ctx, ReviewRunStatus.DONE)
    requested(ctx.conn)
    assert derived(ctx) == [(PR, RequestAction.END, review_requests.REVIEWED, None)]


def test_a_request_waits_on_its_review_running_and_on_a_draft(ctx: Context) -> None:
    """An older head's review, failed, leaves the head owed its own."""
    requested(ctx.conn)
    observed(ctx.conn, draft=True)
    review_ran(ctx, ReviewRunStatus.FAILED, sha="b" * 40)
    assert derived(ctx) == [(PR, RequestAction.WAIT, "a draft", None)]
    review_ran(ctx, ReviewRunStatus.RUNNING)
    assert derived(ctx) == [(PR, RequestAction.WAIT, "a review of it is running", None)]


@pytest.mark.parametrize(
    ("url", "state", "cloned", "reason"),
    [
        (PR, PrState.MERGED, True, review_requests.MERGED),
        (PR, PrState.CLOSED, True, review_requests.CLOSED),
        (ELSEWHERE, PrState.OPEN, True, review_requests.UNKNOWN_REPO),
        (PR, PrState.OPEN, False, review_requests.UNKNOWN_REPO),
    ],
)
def test_a_merged_closed_or_unknown_prs_request_ends(
    ctx: Context,
    url: str,
    state: PrState,
    cloned: bool,  # noqa: FBT001  (a parameter of the case)
    reason: str,
) -> None:
    """A PR in no repository of the workspace, or in one with no clone, ends `unknown_repo` however it was read."""
    if not cloned:
        (ctx.workspace.repos[0].path / ".git").rmdir()
    requested(ctx.conn, url)
    observed(ctx.conn, url, state=state, minutes_ago=0 if url == PR else 600)
    assert derived(ctx) == [(url, RequestAction.END, reason, None)]


@pytest.mark.parametrize(
    "clone",
    [
        "https://user:secret@EXAMPLE.test/acme/repo/",
        "git@example.test:acme/repo.git",
        "ssh://git@example.test:22/acme/repo",
    ],
)
def test_a_pr_is_in_the_repository_whose_clone_url_names_its_host_and_repository(
    canopy_env: CanopyEnv,
    clone: str,
) -> None:
    """Any clone URL `git clone` takes names its repository, however it is spelled."""
    canopy_env.write_shared(SHARED_TOML.replace("https://example.test/acme/repo.git", clone))
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    requested(ctx.conn)
    observed(ctx.conn)
    assert [action for _, action, _, _ in derived(ctx)] == [RequestAction.START]


def test_a_request_whose_pr_is_unread_or_old_waits_as_stale(ctx: Context) -> None:
    """The overseer reads no GitHub beside the `vcs` source (§39), so neither does the derivation."""
    requested(ctx.conn)
    [(_, action, _, stale)] = derived(ctx)
    assert (action, stale) == (RequestAction.WAIT, f"{PR} never observed")
    observed(ctx.conn, minutes_ago=600)
    [(_, action, _, stale)] = derived(ctx)
    assert action is RequestAction.WAIT
    assert stale is not None
    assert stale.startswith(f"{PR} last observed ")


def compared(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str, str | None]]:
    """Tick `tick_id`'s requests against what the overseer did about their PRs."""
    return [(c.pr_url, c.verdict, c.why) for c in requested_reviews.compare(conn, tick_id)]


def test_each_move_of_the_overseers_agrees_with_its_derivation_or_says_why_not(ctx: Context) -> None:
    """A refused review is still the overseer's start, but for `reviewed`, which answers the request."""
    conn = ctx.conn
    one = requested_reviews.Derived(1, PR, RequestAction.START, head_sha=HEAD)
    cases: list[tuple[requested_reviews.Derived, list[tuple[str, str]], str]] = [
        (one, [("dispatch:review", "review run 1")], "agrees"),
        (one, [("refused:capacity", "full"), ("attention:review_limit", "limit")], "agrees"),
        (one, [("wait", "busy")], "disagrees"),
        (one, [("refused:reviewed", "done")], "disagrees"),
        (requested_reviews.Derived(1, PR, RequestAction.WAIT, "a draft"), [], "agrees"),
        (requested_reviews.Derived(1, PR, RequestAction.END, "merged"), [("review:end", "merged")], "agrees"),
        (requested_reviews.Derived(1, PR, RequestAction.END, "merged"), [("review:end", "closed")], "disagrees"),
        (requested_reviews.Derived(1, PR, RequestAction.END, "reviewed"), [("refused:reviewed", "done")], "agrees"),
        (requested_reviews.Derived(1, PR, RequestAction.WAIT, stale="never observed"), [], "stale"),
    ]
    requested(conn)
    for derivation, decisions, verdict in cases:
        with in_tick(conn) as tick_id:
            requested_reviews.record(conn, tick_id, [derivation])
            for action, rationale in decisions:
                db.record_decision(conn, tick_id, None, action, rationale, pr=PR)
            # The harness's item about it, and another PR's decision, are not the overseer's about this one.
            db.record_decision(conn, tick_id, None, "attention:x", "x", pr=PR, decider=Decider.HARNESS)
            db.record_decision(conn, tick_id, None, "dispatch:review", "x", pr=ELSEWHERE)
        [(_, found, _)] = compared(conn, tick_id)
        assert found == verdict, (derivation, decisions)
    with in_tick(conn) as tick_id:
        requested_reviews.record(conn, tick_id, [one])
        db.record_decision(conn, tick_id, None, "wait", "busy", pr=PR)
    assert compared(conn, tick_id) == [(PR, "disagrees", f"derived start at {HEAD}; decided wait")]


def test_a_decision_about_a_tickets_own_pr_is_the_requests_too(ctx: Context) -> None:
    """A review the operator asked for of one of the loop's PRs names its ticket; an attention refusal is no review."""
    conn = ctx.conn
    requested(conn)
    with in_tick(conn) as tick_id:
        requested_reviews.record(conn, tick_id, [requested_reviews.Derived(1, PR, RequestAction.START, head_sha=HEAD)])
        db.record_decision(conn, tick_id, KEY, "refused:raised", "the harness raises it", pr=PR)
    assert compared(conn, tick_id) == [(PR, "disagrees", f"derived start at {HEAD}; decided nothing")]
    with in_tick(conn) as tick_id:
        requested_reviews.record(conn, tick_id, [requested_reviews.Derived(1, PR, RequestAction.START, head_sha=HEAD)])
        db.record_decision(conn, tick_id, KEY, "dispatch:review", "review run 1", pr=PR)
    assert compared(conn, tick_id) == [(PR, "agrees", None)]


@pytest.fixture
def watching(scenario: Scenario, connector_state: Path) -> Path:
    """A workspace with a reviewer and a `vcs` source, the operator's request for PR, and GitHub's PR at HEAD, open.

    Returns:
        The fake connector's state file, which the test may write again.
    """
    scenario.configures(runtime={"review_cmd": REVIEWER})
    scenario.configures("private", connect=sources(github=GITHUB))
    scenario.operator("start", PR, "--review")
    github_has(connector_state)
    return connector_state


def github_has(state: Path, pr_state: str = "open") -> None:
    """GitHub's PR at HEAD, in `pr_state`, as the fake connector reads it."""
    line = {"kind": "pr", "url": PR, "repository": "acme/repo", "number": 12, "head_sha": HEAD, "state": pr_state}
    state.write_text(json.dumps({"github": {"lines": [line]}}))


@pytest.mark.usefixtures("watching")
def test_the_harness_starts_the_review_of_a_request_it_takes_and_the_overseer_is_not_run(scenario: Scenario) -> None:
    """A dry run checks the review's guards and records it as the harness's; nothing is left to the overseer."""
    ticked = scenario.tick(dry_run=True)
    about = [(d.action, d.decider) for d in ticked.decisions if d.pr == PR]
    assert about == [("dispatch:review", Decider.HARNESS)]
    assert not ticked.tick.overseer_ran
    # The overseer decided nothing about it, so there is nothing to compare.
    assert compared(scenario.conn, ticked.tick.id) == []


def own_pr(scenario: Scenario) -> None:
    """PR is one of the loop's own, KEY's unit's: its request stays the overseer's."""
    scenario.seen(KEY)
    db.set_unit(scenario.conn, KEY, str(scenario.env.root), "repo", pr_url=PR)


@pytest.mark.usefixtures("watching")
def test_the_harnesss_review_holds_its_worker_from_the_overseers_dispatch(scenario: Scenario) -> None:
    """One worker, which the requested review ranks first for: new work waits, and the review is checked to start."""
    scenario.configures(capacity={"max_workers": 1})
    scenario.seen("PROJ-2")
    ticked = scenario.tick(dispatches("PROJ-2"), dry_run=True)
    assert ticked.tick.overseer_ran
    made = [(d.ticket_key, d.pr, d.action, d.decider) for d in ticked.decisions if d.action.startswith(STARTS)]
    assert made == [
        ("PROJ-2", None, "refused:reserved", Decider.OVERSEER),
        (None, PR, "dispatch:review", Decider.HARNESS),
    ]
    assert scenario.state()["dispatches_to_come"] == {"reviews": [PR], "holds_workers": 1, "runs": [], "chores": []}


@pytest.mark.usefixtures("watching")
def test_a_request_on_one_of_the_loops_own_prs_stays_the_overseers(scenario: Scenario) -> None:
    """The overseer names its ticket, and its review is its own; the derivation is beside it in shadow."""
    own_pr(scenario)
    ticked = scenario.tick(reviews(HEAD, PR), *waits(KEY), dry_run=True)
    rows = records.select(records.RequestDerivation).where("tick_id = ?", ticked.tick.id).all(scenario.conn)
    assert [(r.pr_url, r.action, r.head_sha, r.stale) for r in rows] == [(PR, RequestAction.START, HEAD, None)]
    about = [(d.action, d.decider) for d in ticked.decisions if d.pr == PR]
    assert about == [("dispatch:review", Decider.OVERSEER)]
    assert compared(scenario.conn, ticked.tick.id) == [(PR, "agrees", None)]


def test_canopy_agreement_counts_the_requests_row_and_lists_its_disagreements(
    scenario: Scenario,
    watching: Path,
) -> None:
    """An overseer that waits on a review the derivation starts disagrees, with its rationale beside it."""
    own_pr(scenario)
    waited = scenario.tick(review_waits(PR, "the author is still pushing"), *waits(KEY))
    github_has(watching, "merged")
    scenario.tick(review_ends(PR, "merged"), *waits(KEY))
    found = agreement.agreement(scenario.conn, datetime.now(UTC), 1)
    [row] = [r for r in found.rows if r.row == agreement.REQUEST]
    assert (row.decisions, row.agrees, row.disagrees, row.situations, row.disagreeing) == (2, 1, 1, 1, 1)
    [disagreed] = [d for d in found.disagreements if d.ticket_key == PR]
    assert (disagreed.ticket_key, disagreed.rows, disagreed.last_tick) == (PR, (agreement.REQUEST,), waited.tick.id)
    assert disagreed.why == f"derived start at {HEAD}; decided wait"
    assert disagreed.rationale == "the author is still pushing"
    out = scenario.operator("agreement", "--days", "1").out
    # Its line in the table of every row, then in the table of each row alone.
    counted, _ = (line.split() for line in out.splitlines() if line.startswith("review_request"))
    assert counted == ["review_request", "2", "1", "1", "0", "1", "1", "0"]
    assert f"  {PR}  review_request  [action]  tick {waited.tick.id}: derived start at {HEAD}; decided wait\n" in out
    assert "      the author is still pushing\n" in out


@pytest.mark.usefixtures("watching")
def test_a_wait_on_a_tickets_own_pr_is_compared_by_the_pr_with_its_rationale(scenario: Scenario) -> None:
    """The overseer names the ticket of one of the loop's PRs, and the request's row still reads its decision."""
    own_pr(scenario)
    waited = scenario.tick(review_waits(PR, "the author is still pushing", ticket=KEY))
    found = agreement.agreement(scenario.conn, datetime.now(UTC), 1)
    [row] = [r for r in found.rows if r.row == agreement.REQUEST]
    assert (row.decisions, row.disagrees) == (1, 1)
    [disagreed] = [d for d in found.disagreements if d.ticket_key == PR]
    assert (disagreed.last_tick, disagreed.why) == (waited.tick.id, f"derived start at {HEAD}; decided wait")
    assert disagreed.rationale == "the author is still pushing"


def test_a_stale_request_is_counted_apart_from_the_stale_tickets(ctx: Context) -> None:
    """A request's PR is no ticket: `canopy agreement` counts the stale requests in a field of their own."""
    conn = ctx.conn
    requested(conn)
    with in_tick(conn) as tick_id:
        stale = requested_reviews.Derived(1, PR, RequestAction.WAIT, stale=f"{PR} never observed")
        requested_reviews.record(conn, tick_id, [stale])
        db.set_tick_overseer(conn, tick_id, runs=1)
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    found = agreement.agreement(conn, datetime.now(UTC), 1)
    assert (found.stale, found.stale_tickets, found.stale_requests) == (1, 0, 1)
    assert found.as_json()["stale_requests"] == 1
    assert "Stale, counted apart: 1 decision on 0 tickets and 1 review request." in agreement_cli.render(found)


def answers(ctx: Context, *, dry_run: bool = False) -> tuple[int, list[tuple[str, str]]]:
    """A tick that derives the open requests and has the harness answer those it takes, before any overseer.

    Returns:
        The tick, and the harness's decisions about PRs in it, each its action and rationale.
    """
    with in_tick(ctx.conn, dry_run=dry_run) as tick_id:
        requested_reviews.record(ctx.conn, tick_id, requested_reviews.derive(ctx, datetime.now(UTC)))
        harness_reviews.decide(ctx, tick_id, dry_run=dry_run, log=logs.for_tick(tick_id))
    made = db.decisions_for_tick(ctx.conn, tick_id)
    return tick_id, [(d.action, d.rationale) for d in made if d.pr is not None and d.decider is Decider.HARNESS]


def present_request(conn: sqlite3.Connection, url: str) -> records.ReviewRequest:
    """The latest request on `url`, which the test knows is there."""
    found = review_requests.latest_request(conn, url)
    assert found is not None
    return found


def test_the_harness_waits_on_a_draft_and_on_a_pr_never_read(ctx: Context) -> None:
    """Each wait is its own decision about the PR, and the request stays open."""
    requested(ctx.conn)
    assert answers(ctx)[1] == [("wait", f"stale: {PR} never observed; it waits for the vcs source to read it")]
    observed(ctx.conn, draft=True)
    assert answers(ctx)[1] == [("wait", "a draft")]
    assert review_requests.open_request(ctx.conn, PR) is not None


@pytest.mark.parametrize(
    ("url", "state", "reason"),
    [
        (PR, PrState.MERGED, review_requests.MERGED),
        (PR, PrState.CLOSED, review_requests.CLOSED),
        (ELSEWHERE, PrState.OPEN, review_requests.UNKNOWN_REPO),
    ],
)
def test_the_harness_ends_a_request_no_review_could_answer(
    ctx: Context,
    url: str,
    state: PrState,
    reason: str,
) -> None:
    """A dry run records the end and ends nothing; a live tick ends it with what the source read."""
    requested(ctx.conn, url)
    observed(ctx.conn, url, state=state)
    assert answers(ctx, dry_run=True)[1] == [("review:end", f"dry run: not ended; {reason}")]
    assert review_requests.open_request(ctx.conn, url) is not None
    assert answers(ctx)[1] == [("review:end", reason)]
    ended = present_request(ctx.conn, url)
    assert (ended.ended_at is not None, ended.end_reason) == (True, reason)


def test_the_harness_ends_a_request_whose_head_is_reviewed_already(ctx: Context) -> None:
    """As the review-run tool's refusal `reviewed` ends it for the overseer."""
    observed(ctx.conn)
    review_ran(ctx, ReviewRunStatus.DONE)
    requested(ctx.conn)
    assert answers(ctx)[1] == [("review:end", review_requests.REVIEWED)]
    assert present_request(ctx.conn, PR).end_reason == review_requests.REVIEWED


def test_the_harness_answers_no_request_on_one_of_the_loops_own_prs(canopy_env: CanopyEnv, ctx: Context) -> None:
    """Chosen conservatively: its ticket's rows are the overseer's to weigh beside it."""
    requested(ctx.conn)
    observed(ctx.conn, draft=True)
    db.set_unit(ctx.conn, KEY, str(canopy_env.root), "repo", pr_url=PR)
    tick_id, made = answers(ctx)
    assert (made, harness_reviews.taken(ctx.conn, tick_id)) == ([], frozenset())


def test_the_overseers_review_verbs_about_a_request_the_harness_takes_are_refused_decided(ctx: Context) -> None:
    """A steered overseer cannot overrule the harness: each refusal is recorded about the PR."""
    conn = ctx.conn
    requested(conn)
    observed(conn)
    calls = [
        lambda: review_tools.review_run(ctx, review_tools.ReviewRun(pr=PR, sha=HEAD, repo="repo")),
        lambda: review_tools.review_wait(ctx, review_tools.ReviewWait(pr=PR, rationale="checks still running")),
        lambda: review_tools.review_end(ctx, review_tools.ReviewEnd(pr=PR, reason="merged")),
    ]
    with in_tick(conn) as tick_id:
        requested_reviews.record(conn, tick_id, requested_reviews.derive(ctx, datetime.now(UTC)))
        for call in calls:
            with pytest.raises(tools.Refused, match=r"refused \(decided\)"):
                call()
    made = [(d.action, d.pr, d.decider) for d in db.decisions_for_tick(conn, tick_id)]
    assert made == [("refused:decided", PR, Decider.OVERSEER)] * 3
    assert review_requests.open_request(conn, PR) is not None


def test_a_request_the_harness_ended_this_tick_is_still_refused_decided(ctx: Context) -> None:
    """It is open no longer, but the harness's end stands: the overseer may not review or wait on its PR."""
    conn = ctx.conn
    requested(conn)
    observed(conn, state=PrState.MERGED)
    with in_tick(conn) as tick_id:
        requested_reviews.record(conn, tick_id, requested_reviews.derive(ctx, datetime.now(UTC)))
        harness_reviews.decide(ctx, tick_id, dry_run=False, log=logs.for_tick(tick_id))
        assert review_requests.open_request(conn, PR) is None
        with pytest.raises(tools.Refused, match=r"refused \(decided\)"):
            review_tools.review_run(ctx, review_tools.ReviewRun(pr=PR, sha=HEAD, repo="repo"))
        with pytest.raises(tools.Refused, match=r"refused \(decided\)"):
            review_tools.review_wait(ctx, review_tools.ReviewWait(pr=PR, rationale="checks still running"))
    made = [(d.action, d.decider) for d in db.decisions_for_tick(conn, tick_id)]
    assert made == [("review:end", Decider.HARNESS), *[("refused:decided", Decider.OVERSEER)] * 2]


def starts(ctx: Context) -> tuple[int, records.RequestDerivation]:
    """A tick that derived a start for the open request on PR, still open for the harness to make it.

    Returns:
        The tick and the row it derived.
    """
    with in_tick(ctx.conn) as tick_id:
        requested_reviews.record(ctx.conn, tick_id, requested_reviews.derive(ctx, datetime.now(UTC)))
    [row] = harness_reviews.starts(ctx.conn, tick_id)
    return tick_id, row


def test_the_harness_starts_the_review_with_no_ticket_and_no_context(ctx: Context) -> None:
    """Nothing model-written reaches the reviewer, and the review is recorded as the harness's own."""
    requested(ctx.conn)
    observed(ctx.conn)
    tick_id, row = starts(ctx)
    started = review_start.Started(run_id=7, pid=1, slot=Path("/slots/1"))
    with mock.patch.object(review_start, "start", autospec=True, return_value=started) as start:
        harness_reviews.make_review(ctx, tick_id, row, dry_run=False, log=logs.for_tick(tick_id))
    asked = review_start.Request(pr=PR, sha=HEAD, ticket=None, repo="repo")
    start.assert_called_once_with(ctx, tick_id=tick_id, request=asked, context=None)
    made = [(d.action, d.rationale, d.decider) for d in db.decisions_for_tick(ctx.conn, tick_id)]
    assert made == [("dispatch:review", f"review run 7: {HEAD} in /slots/1", Decider.HARNESS)]


@pytest.mark.parametrize(("guard", "ends"), [("capacity", False), ("reviewed", True)])
def test_a_guard_that_refuses_the_harnesss_review_is_recorded_as_its_refusal(
    ctx: Context,
    guard: str,
    *,
    ends: bool,
) -> None:
    """A refusal `reviewed` answers the request, as it does the overseer's."""
    requested(ctx.conn)
    observed(ctx.conn)
    tick_id, row = starts(ctx)
    refusal = review_start.Refusal(guard, "no")
    with mock.patch.object(review_start, "start", autospec=True, side_effect=refusal):
        harness_reviews.make_review(ctx, tick_id, row, dry_run=False, log=logs.for_tick(tick_id))
    made = [(d.action, d.decider) for d in db.decisions_for_tick(ctx.conn, tick_id)]
    assert made == [(f"refused:{guard}", Decider.HARNESS)]
    assert (review_requests.open_request(ctx.conn, PR) is None) == ends


def test_a_request_the_harness_decided_is_not_compared(ctx: Context) -> None:
    """The overseer decided nothing about it."""
    requested(ctx.conn)
    observed(ctx.conn, draft=True)
    tick_id, made = answers(ctx)
    assert (made, compared(ctx.conn, tick_id)) == ([("wait", "a draft")], [])


def test_the_state_block_names_the_harnesss_reviews_to_come_and_lists_no_request_it_takes(ctx: Context) -> None:
    """The overseer is shown neither the request nor its PR, only that the harness starts its review."""
    requested(ctx.conn)
    observed(ctx.conn)
    tick_id, row = starts(ctx)
    taken = harness_reviews.taken(ctx.conn, tick_id)
    section = review_view.state_section(ctx.conn, ctx.config, datetime.now(UTC), taken=taken)
    assert (taken, section is not None and section["requests"]) == (frozenset({PR}), [])
    to_come = harness_dispatches.section(
        harness_dispatches.Plan([], []),
        harness_reviews.reviews_to_come([row]),
        review_workers=harness_reviews.holds(ctx, tick_id),
    )
    assert to_come == {"reviews": [PR], "holds_workers": 1, "runs": [], "chores": []}
    assert harness_dispatches.section(harness_dispatches.Plan([], [])) is None


def test_a_poll_finds_a_review_the_harness_would_start_and_no_news_in_its_wait(ctx: Context) -> None:
    """A start names its head, so it wakes the loop once; a wait is the same poll after poll."""
    requested(ctx.conn)
    observed(ctx.conn, draft=True)
    now = datetime.now(UTC)
    waiting = outlook.read(ctx, now)
    assert ("request", PR, "wait", "a draft") in waiting
    records.update(records.ObservedPr).set(draft=False).where("url = ?", PR).run(ctx.conn)
    assert outlook.news(waiting, outlook.read(ctx, now)) == [("request", PR, "start", HEAD)]


@pytest.mark.parametrize(
    ("capacity", "free"),
    [
        ({"max_workers": 1, "max_reviews": 2}, "1 of 1 workers"),
        ({"max_workers": 3, "max_reviews": 1}, "1 of 1 review runs"),
    ],
)
def test_the_overseers_own_review_leaves_the_harnesss_requested_review_its_worker_and_review_run(
    scenario: Scenario,
    capacity: Mapping[str, int],
    free: str,
) -> None:
    """Refused `reserved` as it is asked for, so the request, ranked first, is not refused `capacity` at its start."""
    conn = scenario.conn
    scenario.configures(capacity=capacity)
    requested(conn)
    observed(conn)
    scenario.seen(KEY)
    db.set_unit(conn, KEY, str(scenario.env.root), "repo", pr_url=OWN)
    with scenario.ticking(dry_run=True) as tick_id:
        requested_reviews.record(conn, tick_id, requested_reviews.derive(context(scenario.env), datetime.now(UTC)))
        said = scenario.overseer(reviews(HEAD, OWN, ticket=KEY), error=True)
    assert "review refused (reserved)" in said.text
    [(action, why)] = [(d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id) if d.pr == OWN]
    assert action == "refused:reserved"
    assert why.startswith(f"{free} are free, and the harness's dispatches to come this tick that rank above this one")


def test_a_review_the_operator_requested_of_a_tickets_pr_is_not_held_behind_the_harnesss(ctx: Context) -> None:
    """Both rank first in §7's order; and with no request to start the harness holds nothing ahead of any review."""
    requested(ctx.conn)
    observed(ctx.conn)
    tick_id, _ = starts(ctx)
    assert harness_dispatches.reserved_for_review(ctx, tick_id, OWN, KEY) == review_start.Reserved(1, 1)
    assert harness_dispatches.reserved_for_review(ctx, tick_id, PR, None) == review_start.UNRESERVED
    with in_tick(ctx.conn) as later:
        pass
    assert harness_dispatches.reserved_for_review(ctx, later, OWN, KEY) == review_start.UNRESERVED
