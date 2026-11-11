"""Tests for the operator's review requests derived in shadow, and their row in `canopy agreement` (§21, §30, §37)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from canopy.cli import agreement as agreement_cli
from canopy.core import db, records, review_runs
from canopy.core.vocab import Decider, PrState, RequestAction, ReviewRunStatus, TickStatus
from canopy.infra import resources
from canopy.loop import agreement, requested_reviews
from canopy.reviews import review_requests
from tests.canopy.helpers import KEY, context, in_tick, sources
from tests.canopy.scenario_helpers import Scenario, review_ends, review_waits, reviews
from tests.conftest import SHARED_TOML

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.context import Context
    from tests.conftest import CanopyEnv

#: A PR of the workspace's one repository, whose clone URL is `https://example.test/acme/repo.git`.
PR = "https://example.test/acme/repo/pull/12"
#: A PR of a repository the workspace does not have.
ELSEWHERE = "https://example.test/acme/other/pull/3"
HEAD = "a" * 40
#: The tests' `vcs` source: the fake connector, playing GitHub.
GITHUB = {"kind": "vcs", "cmd": "connector github", "timeout_minutes": 1}
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
            # The harness's and another PR's decisions are not the overseer's about this one.
            db.record_decision(conn, tick_id, None, "dispatch:review", "x", pr=PR, decider=Decider.HARNESS)
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
def test_the_row_stays_the_overseers_which_starts_the_review_the_derivation_reads(scenario: Scenario) -> None:
    """The harness decides nothing about the request: it is listed to the overseer, whose review is its own."""
    ticked = scenario.tick(reviews(HEAD, PR), dry_run=True)
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
    waited = scenario.tick(review_waits(PR, "the author is still pushing"))
    github_has(watching, "merged")
    scenario.tick(review_ends(PR, "merged"))
    found = agreement.agreement(scenario.conn, datetime.now(UTC), 1)
    [row] = [r for r in found.rows if r.row == agreement.REQUEST]
    assert (row.decisions, row.agrees, row.disagrees, row.situations, row.disagreeing) == (2, 1, 1, 1, 1)
    [disagreed] = found.disagreements
    assert (disagreed.ticket_key, disagreed.rows, disagreed.last_tick) == (PR, (agreement.REQUEST,), waited.tick.id)
    assert disagreed.why == f"derived start at {HEAD}; decided wait"
    assert disagreed.rationale == "the author is still pushing"
    out = scenario.operator("agreement", "--days", "1").out
    assert "review_request          2      1         1           1            1" in out
    assert f"  {PR}  review_request  tick {waited.tick.id}: derived start at {HEAD}; decided wait\n" in out
    assert "      the author is still pushing\n" in out


@pytest.mark.usefixtures("watching")
def test_a_wait_on_a_tickets_own_pr_is_compared_by_the_pr_with_its_rationale(scenario: Scenario) -> None:
    """The overseer names the ticket of one of the loop's PRs, and the request's row still reads its decision."""
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
        db.set_tick_overseer(conn, tick_id, ran=True)
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    found = agreement.agreement(conn, datetime.now(UTC), 1)
    assert (found.stale, found.stale_tickets, found.stale_requests) == (1, 0, 1)
    assert found.as_json()["stale_requests"] == 1
    assert "Stale, counted apart: 1 decision on 0 tickets and 1 review request." in agreement_cli.render(found)
