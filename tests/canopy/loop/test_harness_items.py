"""The attention items the harness raises from their causes (DESIGN §14, §37, ROADMAP M38).

Each of the eight reasons over a journal written by hand, its observations fresh at `NOW`: raised while its cause
holds, and gone once the journal or a fresh observation shows the cause gone. One that rests on an observation is kept
while that observation is stale, or when the derivation could not run. Then through ticks: kept across a `skipped`
tick, an `overseer_failed` one, and an outage, and gone once a read shows its cause gone; and the overseer refused one
through its tool and its command alike.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import db, plans
from canopy.core.vocab import Decider, RunStatus, TickStatus
from canopy.loop import attention, harness_items, phases
from tests.canopy.helpers import (
    KEY,
    PLAN,
    context,
    decisions,
    in_tick,
    mcp_session,
    messages,
    operator,
    running_run,
    tool_call,
    waits,
)
from tests.canopy.observation_helpers import (
    FRESH,
    HEAD,
    NOW,
    OLD,
    PR,
    TRACKER,
    check,
    held,
    observe_pr,
    observe_ticket,
    review,
)
from tests.canopy.scenario_helpers import skips_tick

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv

#: An item, as a test compares it: its ticket, reason, and repository.
type Found = tuple[str | None, str, str | None]


@pytest.fixture
def observed(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> sqlite3.Connection:
    """KEY held and observed open with the queue label, its unit in `repo` with PR observed open at HEAD, all at FRESH.

    Returns the journal.
    """
    canopy_env.configure(canopy_env.user_file, TRACKER)
    held(canopy_env, conn, KEY)
    observe_ticket(conn)
    db.set_unit(conn, KEY, str(canopy_env.root), "repo", pr_url=PR)
    observe_pr(conn)
    conn.commit()
    return conn


def raised(env: CanopyEnv, *, derive: bool = True) -> list[Found]:
    """What the harness raises at NOW over `env`'s journal: from the derivation, or as if it raised, `derive` off."""
    ctx = context(env)
    found = harness_items.raised(ctx, phases.derive(ctx, NOW) if derive else None, NOW)
    return [(i.ticket_key, i.reason, i.repo) for i in found]


def reasons(env: CanopyEnv) -> set[str]:
    """The reasons of what the harness raises at NOW."""
    return {reason for _, reason, _ in raised(env)}


# Each reason's cause, written into the journal, and then what shows it gone.


def green(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The PR's checks pass, and no person has approved it."""
    check(conn, "build", "completed", "success")


def pending(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """A check of the PR runs again: its CI is pending, so no row of review holds."""
    check(conn, "lint", "in_progress", None, run_id=12)


def approved(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The PR's checks pass, and a person approved it."""
    green(env, conn)
    review(conn, 1, "carol", "approved", FRESH)


def merged(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """A read sees the PR merged."""
    conn.execute("UPDATE observed_prs SET state = 'merged'")


def untrusted(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """A reviewer `trust.trusted_reviewers` does not list comments on the PR."""
    review(conn, 1, "mallory", None, FRESH, "Rename it.", item="comment")


def answered(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The operator answers about the feedback, after it, in canopy."""
    conn.commit()
    assert operator("reply", KEY, "Leave the name as it is.") == 0


def unreviewed_at_its_limit(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The loop reviews its own PRs, each once; this one's was of an older head, and its head passes its checks."""
    env.configure(env.user_file, {"review": {"agent_prs": True}, "policy": {"max_reviews_per_pr": 1}})
    green(env, conn)
    reviewed(conn, sha="0ld1234")


def review_granted(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The operator grants the PR another review."""
    conn.commit()
    assert operator("grant", PR, "review") == 0


def red_at_its_limit(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """A check of the PR failed, and its unit has had the one `resume` it may."""
    env.configure(env.user_file, {"policy": {"max_resume_attempts": 1}})
    check(conn, "build", "completed", "failure")
    tick_id = db.start_tick(conn, dry_run=False)
    slot = db.RunSlot("repo", env.root / "slot", "lease-1", "holder", "main")
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key=KEY,
        kind="resume",
        branch=f"agent/{KEY}-work",
        slots=[slot],
        runs_dir=env.state_dir / "runs",
    )
    db.finish_run(conn, "runs", run_id, RunStatus.DONE, None)


def resume_granted(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The operator grants the unit another `resume`."""
    conn.commit()
    assert operator("grant", KEY, "resume", "--repo", "repo") == 0


def review_failed(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The loop's review of the PR crashed."""
    reviewed(conn, status="crashed")


def reviewed_again(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """A newer review of the PR starts."""
    reviewed(conn, status="running")


def reviewed(conn: sqlite3.Connection, *, sha: str = HEAD, status: str = "done", findings: int = 0) -> None:
    """A review run of the PR at `sha`, which started at FRESH and is `status`, with `findings` if it ended done."""
    found = [{"severity": "major", "title": f"Finding {n}"} for n in range(1, findings + 1)]
    result = {"status": "done", "verdict": "findings" if found else "clean", "impact": "normal", "findings": found}
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, ticket_key, repo, started_at, ended_at, status, result_json, "
        "log_path) VALUES (?, ?, ?, ?, 'repo', ?, ?, ?, ?, 'x')",
        (
            db.start_tick(conn, dry_run=False),
            PR,
            sha,
            KEY,
            FRESH,
            None if status == "running" else FRESH,
            status,
            json.dumps(result) if status == "done" else None,
        ),
    )


def plan_waits(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """A planner proposed a plan for the ticket, which waits on the operator."""
    ctx = context(env)
    run_id = running_run(ctx, KEY, private=False)
    db.finish_run(ctx.conn, "runs", run_id, RunStatus.DONE, None)
    plans.record(ctx.conn, KEY, run_id, plans.write(ctx.state_dir, KEY, run_id, PLAN))
    ctx.conn.commit()


def plan_approved(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The operator approves the plan."""
    conn.commit()
    assert operator("plan", KEY, "--approve") == 0


def plan_changed(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """The operator approved the plan, and its file changed after."""
    plan_waits(env, conn)
    plan_approved(env, conn)
    plan = plans.history(conn, KEY)[-1]
    plans.path_for(env.state_dir, KEY, plan.run_id).write_text(f"{PLAN}\nAnd a second thing.\n")


#: Each reason: what raises it, the item, and what shows its cause gone.
CAUSES: dict[str, tuple[Callable[[CanopyEnv, sqlite3.Connection], None], Found, Callable[..., None]]] = {
    "needs_reviewer": (green, (KEY, "needs_reviewer", "repo"), pending),
    "ready_to_merge": (approved, (KEY, "ready_to_merge", "repo"), merged),
    "untrusted_review": (untrusted, (KEY, "untrusted_review", "repo"), answered),
    "review_limit": (unreviewed_at_its_limit, (KEY, "review_limit", "repo"), review_granted),
    "attempt_limit": (red_at_its_limit, (KEY, "attempt_limit", "repo"), resume_granted),
    "review_failed": (review_failed, (KEY, "review_failed", "repo"), reviewed_again),
    "plan_review": (plan_waits, (KEY, "plan_review", None), plan_approved),
    "plan_changed": (plan_changed, (KEY, "plan_changed", None), plan_approved),
}


def test_the_causes_cover_every_reason_the_harness_raises() -> None:
    assert set(CAUSES) == attention.FROM_CAUSES


@pytest.mark.parametrize("reason", sorted(CAUSES))
def test_an_item_is_raised_while_its_cause_holds_and_goes_when_it_is_gone(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    reason: str,
) -> None:
    cause, item, gone = CAUSES[reason]
    cause(canopy_env, observed)
    observed.commit()
    assert item in raised(canopy_env)
    gone(canopy_env, observed)
    observed.commit()
    assert reason not in reasons(canopy_env)


def test_its_details_are_its_own_words(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    red_at_its_limit(canopy_env, observed)
    untrusted(canopy_env, observed)
    observed.commit()
    ctx = context(canopy_env)
    found = {i.reason: i.detail for i in harness_items.raised(ctx, phases.derive(ctx, NOW), NOW)}
    assert found == {
        "untrusted_review": (
            f"{PR} has feedback from a reviewer `trust.trusted_reviewers` does not list: say what to do about it "
            f"with `canopy reply {KEY}`"
        ),
        "attempt_limit": (
            f"{KEY} in repo has had 1 resume runs and the limit is 1; `canopy grant {KEY} resume --repo repo` allows "
            "another"
        ),
    }
    assert "Rename it." not in json.dumps(found)


def test_untrusted_feedback_raises_nothing_while_feedback_plans_plan_it(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    untrusted(canopy_env, observed)
    observed.commit()
    canopy_env.configure(canopy_env.user_file, {"policy": {"feedback_plan": "approve"}})
    assert "untrusted_review" not in reasons(canopy_env)


def test_canopys_own_review_untrusted_waits_on_the_operator(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    # Its findings are feedback: with `canopy:review` not trusted, they wait on the operator as anyone's do (§21).
    canopy_env.configure(canopy_env.user_file, {"review": {"agent_prs": True}})
    green(canopy_env, observed)
    reviewed(observed, findings=1)
    observed.commit()
    assert raised(canopy_env) == [(KEY, "untrusted_review", "repo")]
    answered(canopy_env, observed)
    assert raised(canopy_env) == [(KEY, "needs_reviewer", "repo")]


def test_a_running_worker_wants_no_run_so_raises_no_attempt_limit(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    red_at_its_limit(canopy_env, observed)
    observed.commit()
    running_run(context(canopy_env), KEY, private=False)
    assert "attempt_limit" not in reasons(canopy_env)


def test_a_ticket_seen_closed_or_unlabeled_holds_no_item(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    green(canopy_env, observed)
    plan_waits(canopy_env, observed)
    observed.commit()
    assert reasons(canopy_env) == {"needs_reviewer", "plan_review"}
    observed.execute("UPDATE observed_tickets SET labels = '[]'")
    observed.commit()
    assert raised(canopy_env) == []


#: The reasons whose cause rests on an observation, and what raises each.
OBSERVED = sorted(harness_items.OBSERVED)


def raise_in_an_ok_tick(env: CanopyEnv, conn: sqlite3.Connection) -> list[Found]:
    """Record what the harness raises at NOW in a tick that ends `ok`, as a tick does, and return it."""
    ctx = context(env)
    found = harness_items.raised(ctx, phases.derive(ctx, NOW), NOW)
    with in_tick(conn, ends_ok=True) as tick_id:
        for i in found:
            db.record_decision(
                conn,
                tick_id,
                i.ticket_key,
                f"{attention.ACTION_PREFIX}{i.reason}",
                i.detail,
                repo=i.repo,
                pr=i.pr,
                decider=Decider.HARNESS,
            )
    conn.commit()
    return [(i.ticket_key, i.reason, i.repo) for i in found]


@pytest.mark.parametrize("reason", OBSERVED)
def test_an_item_resting_on_an_observation_is_kept_while_it_is_stale(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    reason: str,
) -> None:
    cause, item, gone = CAUSES[reason]
    cause(canopy_env, observed)
    observed.commit()
    assert item in raise_in_an_ok_tick(canopy_env, observed)
    # A read failed for longer than `connect.max_age_minutes`: the PR's observation is stale, and so is the ticket's.
    observed.execute("UPDATE observed_prs SET observed_at = ?", (OLD,))
    observed.execute("UPDATE observed_tickets SET observed_at = ?", (OLD,))
    observed.commit()
    assert item in raised(canopy_env)
    # Read fresh again, the cause is gone, and so is the item.
    observed.execute("UPDATE observed_prs SET observed_at = ?", (FRESH,))
    observed.execute("UPDATE observed_tickets SET observed_at = ?", (FRESH,))
    gone(canopy_env, observed)
    observed.commit()
    assert reason not in reasons(canopy_env)


def test_a_stale_limit_goes_once_the_operator_lifts_it(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    # The journal shows the cause gone, whatever the observation: a grant, read stale or not, ends the item.
    red_at_its_limit(canopy_env, observed)
    observed.commit()
    raise_in_an_ok_tick(canopy_env, observed)
    observed.execute("UPDATE observed_prs SET observed_at = ?", (OLD,))
    resume_granted(canopy_env, observed)
    assert raised(canopy_env) == []


def test_a_derivation_that_raised_keeps_every_item_resting_on_an_observation(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    green(canopy_env, observed)
    plan_waits(canopy_env, observed)
    observed.commit()
    raise_in_an_ok_tick(canopy_env, observed)
    # The plan still waits, read from the journal; the PR's item is kept as the latest `ok` tick listed it.
    assert raised(canopy_env, derive=False) == [(KEY, "plan_review", None), (KEY, "needs_reviewer", "repo")]


@pytest.mark.parametrize("status", [TickStatus.SKIPPED, TickStatus.OVERSEER_FAILED])
def test_a_tick_that_did_not_close_ok_leaves_the_harnesss_items(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    status: TickStatus,
) -> None:
    green(canopy_env, observed)
    plan_waits(canopy_env, observed)
    observed.commit()
    found = raise_in_an_ok_tick(canopy_env, observed)
    assert sorted(found) == [(KEY, "needs_reviewer", "repo"), (KEY, "plan_review", None)]
    tick_id = db.start_tick(observed, dry_run=False)
    db.finish_tick(observed, tick_id, status, "test")
    observed.commit()
    assert sorted(attention.keys(attention.current(observed))) == sorted(found)


def test_a_tick_keeps_its_item_through_a_skipped_tick_a_failed_one_and_an_outage(
    scenario: Scenario,
    github_state: Path,
    notified: Path,
) -> None:
    # A private ticket, whose PR passes its checks and waits on a reviewer.
    scenario.operator("start", KEY)
    db.set_unit(scenario.conn, KEY, str(scenario.env.root), "repo", pr_url=PR)
    scenario.conn.commit()
    passing = {"name": "build", "status": "completed", "conclusion": "success", "run_id": 11}
    github_state.write_text(json.dumps({"prs": {PR: {"checks": [passing]}}}))
    ticked = scenario.tick(*waits(KEY))
    [raised_by] = [d.decider for d in ticked.decisions if d.action == "attention:needs_reviewer"]
    assert raised_by is Decider.HARNESS
    assert scenario.attention() == [(KEY, "needs_reviewer")]
    assert scenario.state()["attention"] == []
    scenario.tick(skips_tick("mcp_unavailable: github"), code=1)
    scenario.tick(result="gave up", code=1)
    # GitHub is down for longer than an observation stays fresh: the tick closes `ok`, and drops nothing (#219).
    github_state.write_text(json.dumps({"down": True}))
    scenario.time_passes(minutes=31)
    outage = scenario.tick(*waits(KEY))
    assert outage.tick.status == TickStatus.OK
    assert scenario.attention() == [(None, "connector_failed"), (KEY, "needs_reviewer")]
    assert messages(notified)[-1].startswith("canopy attention: 1 new, 0 resolved\n+ - connector_failed")
    # Read again, a check runs: the PR no longer waits on a reviewer, and the item goes.
    running = {**passing, "status": "in_progress", "conclusion": None}
    github_state.write_text(json.dumps({"prs": {PR: {"checks": [running]}}}))
    scenario.tick(*waits(KEY))
    assert scenario.attention() == []
    assert messages(notified)[-1].startswith("canopy attention: 0 new, 2 resolved")


@pytest.mark.parametrize("reason", sorted(attention.FROM_CAUSES))
def test_the_overseer_is_refused_an_item_the_harness_raises(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    reason: str,
) -> None:
    held(canopy_env, conn, KEY)
    conn.commit()
    for through in ("command", "tool"):
        with in_tick(conn) as tick_id:
            if through == "command":
                assert main(["attention", KEY, reason, "--detail", "d"]) == 1
            else:
                said = mcp_session(tool_call("attention", key=KEY, reason=reason, detail="d")).said()
                assert said.error
                assert "refused (raised)" in said.text
            [(action, why)] = decisions(conn, tick_id)
        assert action == "refused:raised"
        assert why == f"the harness raises {reason} itself while its cause holds, and ends it when the cause is gone"
    assert attention.current(conn) == []


def test_the_overseer_still_records_an_item_of_judgment(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    held(canopy_env, conn, KEY)
    conn.commit()
    with in_tick(conn) as tick_id:
        assert main(["attention", KEY, "needs_author", "--detail", "asks about intent"]) == 0
    assert decisions(conn, tick_id) == [("attention:needs_author", "asks about intent")]
