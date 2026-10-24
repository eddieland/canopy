"""The derivation, in shadow (DESIGN §30): §7's table derived from journals written by hand, one case per row.

Each case is checked against snapshots; the tests also cover how a tick's derivation compares with what its overseer set
and decided.

The snapshots are syrupy's, in `__snapshots__/test_phases.ambr`; `make snapshots` records the ones that differ.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from canopy.core import conversation, db, records, sql
from canopy.core.config import CANOPY_REVIEWER
from canopy.core.vocab import Phase
from canopy.loop import phases
from tests.canopy.helpers import KEY, canopy, context, in_tick, seen
from tests.canopy.observation_helpers import artifact_comment

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from syrupy.assertion import SnapshotAssertion

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv

#: The time each case is derived at; an observation since `FRESH` is fresh, one at `OLD` stale.
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
FRESH = "2026-10-20T11:59:00.000Z"
OLD = "2026-10-20T10:00:00.000Z"
PR = "https://github.com/acme/repo/pull/7"
HEAD = "abc1234"
#: canopy_env's queue label.
LABEL = "agent-ready-tester"
#: A tracker source, so tickets are observed.
TRACKER = {"sources": {"jira": {"kind": "tracker", "cmd": "connector jira"}}}

type Case = Callable[[CanopyEnv, sqlite3.Connection], None]


def observe_ticket(
    conn: sqlite3.Connection,
    key: str = KEY,
    *,
    state: str = "open",
    labels: Mapping[str, str | None] | None = None,
    blockers: tuple[str, ...] = (),
    at: str = FRESH,
) -> None:
    """Record the tracker's view of `key`: labeled with the queue label unless `labels` says otherwise."""
    named = {LABEL: None} if labels is None else labels
    conn.execute(
        "INSERT INTO observed_tickets (key, title, body, state, labels, updated_at, blockers, observed_at) "
        "VALUES (?, 'Fix the build', '', ?, ?, NULL, ?, ?)",
        (
            key,
            state,
            json.dumps([{"name": n, "added_at": a} for n, a in named.items()]),
            json.dumps(list(blockers)),
            at,
        ),
    )


def comment(conn: sqlite3.Connection, at: str, *, author: str = "acc-1", source: str = "tracker") -> None:
    """Record a tracker comment on KEY at `at`."""
    conn.execute(
        "INSERT INTO observed_comments (ticket, id, author, commented_at, body, truncated, source, observed_at) "
        "VALUES (?, ?, ?, ?, 'Go ahead.', 0, ?, ?)",
        (KEY, at, author, at, source, FRESH),
    )


def branches_read(conn: sqlite3.Connection, *names: str) -> None:
    """Record a `vcs` run that read the repository's branches whole, with `names` under the prefix."""
    conn.execute(
        "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, "
        "stderr) VALUES (NULL, 'github', 'vcs', ?, ?, 'ok', ?, '{}', '{}', '')",
        (FRESH, FRESH, json.dumps({"repositories": [{"name": "repo"}]})),
    )
    for name in names:
        conn.execute(
            "INSERT INTO observed_branches (repository, name, head_sha, observed_at) VALUES ('repo', ?, ?, ?)",
            (name, HEAD, FRESH),
        )


def unit(env: CanopyEnv, conn: sqlite3.Connection, *, pr: str | None = PR, **cursors: str) -> None:
    """Give KEY a unit in `repo`, with `pr` and the cursors given."""
    db.set_unit(conn, KEY, str(env.root), "repo", pr_url=pr, cursors=cursors)


def observe_pr(conn: sqlite3.Connection, *, state: str = "open", mergeable: str = "mergeable", at: str = FRESH) -> None:
    """Record PR as the reader saw it, opened by `operator`, at HEAD."""
    conn.execute(
        "INSERT INTO observed_prs (url, repository, number, head_sha, base_ref, state, draft, mergeable, author, "
        "observed_at, labels, mergeable_state) VALUES (?, 'acme/repo', 7, ?, 'main', ?, 0, ?, 'operator', ?, '[]', ?)",
        (PR, HEAD, state, mergeable, at, "dirty" if mergeable == "conflicting" else "clean"),
    )


def check(
    conn: sqlite3.Connection,
    name: str = "build",
    status: str = "completed",
    conclusion: str | None = "success",
) -> None:
    """Record a check at PR's head, its run 11."""
    conn.execute(
        "INSERT INTO observed_checks (pr_url, name, head_sha, status, conclusion, run_id, url, observed_at) "
        "VALUES (?, ?, ?, ?, ?, 11, NULL, ?)",
        (PR, name, HEAD, status, conclusion, FRESH),
    )


def review(conn: sqlite3.Connection, author: str, state: str, *, at: str = FRESH, body: str = "") -> None:
    """Record a review of PR by `author`."""
    conn.execute(
        "INSERT INTO observed_reviews (pr_url, item, id, author, bot, state, created_at, body, observed_at) "
        "VALUES (?, 'review', (SELECT count(*) + 1 FROM observed_reviews), ?, 0, ?, ?, ?, ?)",
        (PR, author, state, at, body, FRESH),
    )


def a_tick(conn: sqlite3.Connection) -> int:
    """A tick for a run or a review to belong to."""
    return db.start_tick(conn, dry_run=False)


def running(conn: sqlite3.Connection, kind: str = "implement") -> int:
    """A run of KEY still running."""
    cur = conn.execute(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path) VALUES (?, ?, ?, '', ?, 'x')",
        (a_tick(conn), KEY, kind, FRESH),
    )
    return int(cur.lastrowid or 0)


def reviewed(conn: sqlite3.Connection, findings: int, persona: str | None = None) -> None:
    """A review run of PR's head that ended done, with `findings` findings, in `persona`."""
    found = [{"severity": "major", "title": f"Finding {n}"} for n in range(1, findings + 1)]
    result = {"status": "done", "verdict": "findings" if found else "clean", "impact": "normal", "findings": found}
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, ticket_key, started_at, ended_at, status, result_json, "
        "log_path, persona, persona_digest) VALUES (?, ?, ?, ?, ?, ?, 'done', ?, 'x', ?, ?)",
        (a_tick(conn), PR, HEAD, KEY, FRESH, FRESH, json.dumps(result), persona, persona and "x"),
    )


def green(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """KEY's unit holds PR, open, its one check green."""
    unit(env, conn)
    observe_pr(conn)
    check(conn)


def case_ready(_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    branches_read(conn)


def case_plan_proposed(_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    branches_read(conn)
    run = running(conn, "plan")
    conn.execute("UPDATE runs SET status = 'done', ended_at = ? WHERE id = ?", (FRESH, run))
    conn.execute(
        "INSERT INTO plans (ticket_key, run_id, created_at, status, sha256, size) VALUES (?, ?, ?, 'proposed', 'x', 1)",
        (KEY, run, FRESH),
    )


def case_blocked(_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    branches_read(conn)
    conn.execute("UPDATE observed_tickets SET blockers = '[\"PROJ-9\"]' WHERE key = ?", (KEY,))
    observe_ticket(conn, "PROJ-9", labels={})


def case_running(_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    running(conn)


def case_pushed_no_pr(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    branches_read(conn, f"agent/{KEY}-fix-the-build")
    unit(env, conn, pr=None)


def case_conflicted(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    unit(env, conn)
    observe_pr(conn, mergeable="conflicting")


def case_ci_running(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    unit(env, conn)
    observe_pr(conn)
    check(conn)
    check(conn, "test", "in_progress", None)


def case_ci_red(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    unit(env, conn, ci="10")
    observe_pr(conn)
    check(conn, conclusion="failure")


def case_review_pending(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    env.configure(env.user_file, {"review": {"agent_prs": True}})
    green(env, conn)


def case_review_findings(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    env.configure(env.user_file, {"review": {"agent_prs": True}, "trust": {"trusted_reviewers": [CANOPY_REVIEWER]}})
    green(env, conn)
    reviewed(conn, findings=2)


def case_changes_requested(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    env.configure(env.user_file, {"trust": {"trusted_reviewers": ["Octocat"]}})
    green(env, conn)
    review(conn, "octocat", "changes_requested", body="Rename it.")


def case_untrusted_review(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    green(env, conn)
    review(conn, "stranger", "commented", body="Why not a map?")


def case_green_unreviewed(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    green(env, conn)


def case_approved(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    green(env, conn)
    review(conn, "octocat", "approved")


def case_merged(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    unit(env, conn)
    observe_pr(conn, state="merged")


def case_needs_human(_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    branches_read(conn, f"agent/{KEY}-fix-the-build")
    labels = json.dumps([{"name": LABEL, "added_at": None}, {"name": "needs-human", "added_at": FRESH}])
    conn.execute("UPDATE observed_tickets SET labels = ? WHERE key = ?", (labels, KEY))


def case_human_replied(env: CanopyEnv, conn: sqlite3.Connection) -> None:
    case_needs_human(env, conn)
    env.configure(env.user_file, {"trust": {"authorized_repliers": ["acc-1"]}})
    comment(conn, "2026-10-20T11:59:30.000Z")


CASES: Mapping[str, Case] = {
    "ready": case_ready,
    "plan_proposed": case_plan_proposed,
    "blocked": case_blocked,
    "running": case_running,
    "pushed_no_pr": case_pushed_no_pr,
    "conflicted": case_conflicted,
    "ci_running": case_ci_running,
    "ci_red": case_ci_red,
    "review_pending": case_review_pending,
    "review_findings": case_review_findings,
    "changes_requested": case_changes_requested,
    "untrusted_review": case_untrusted_review,
    "green_unreviewed": case_green_unreviewed,
    "approved": case_approved,
    "merged": case_merged,
    "needs_human": case_needs_human,
    "human_replied": case_human_replied,
}


def derived(env: CanopyEnv) -> list[phases.Derived]:
    """What the derivation makes of `env`'s journal at NOW, read with its config as it is now."""
    ctx = context(env)
    return phases.derive(ctx, NOW)


@pytest.fixture
def observed(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> sqlite3.Connection:
    """A tracker source configured, and KEY seen and observed open with the queue label. Returns the journal."""
    canopy_env.configure(canopy_env.user_file, {"connect": TRACKER})
    seen(conn, canopy_env)
    observe_ticket(conn)
    conn.commit()
    return conn


@pytest.mark.parametrize("case", CASES, ids=list(CASES))
def test_each_row_of_the_phase_table(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    case: str,
    snapshot: SnapshotAssertion,
) -> None:
    CASES[case](canopy_env, observed)
    observed.commit()
    found = derived(canopy_env)
    assert found == snapshot
    assert any(case in d.phases for d in found), f"{case} did not hold"


def test_a_head_is_review_pending_until_each_of_personas_reviewers_has_reviewed_it(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    # DESIGN §31: under `[personas] reviewers`, a head waits on a `done` review in each persona.
    reviewers = {"personas": {"reviewers": ["skeptic", "explainer"]}}
    canopy_env.configure(canopy_env.user_file, {"review": {"agent_prs": True}, **reviewers})
    green(canopy_env, observed)
    reviewed(observed, findings=0, persona="skeptic")
    observed.commit()
    assert any(phases.Phase.REVIEW_PENDING in d.phases for d in derived(canopy_env))
    reviewed(observed, findings=0, persona="explainer")
    observed.commit()
    assert not any(phases.Phase.REVIEW_PENDING in d.phases for d in derived(canopy_env))


def test_a_closed_ticket_has_no_phase(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    observed.execute("UPDATE observed_tickets SET state = 'closed'")
    observed.commit()
    assert derived(canopy_env) == [phases.Derived(KEY, None, candidate=False, closed=True)]


def test_a_ticket_without_the_queue_label_is_no_candidate(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    observed.execute("UPDATE observed_tickets SET labels = '[]'")
    observed.commit()
    assert derived(canopy_env) == [phases.Derived(KEY, None, candidate=False, closed=False)]


@pytest.mark.parametrize(
    ("statement", "stale"),
    [
        ("DELETE FROM observed_tickets", f"{KEY} never observed"),
        ("UPDATE observed_tickets SET observed_at = '2026-10-20T10:00:00.000Z'", f"{KEY} last observed {OLD}"),
        ("UPDATE observed_tickets SET blockers = '[\"PROJ-9\"]'", "blocker PROJ-9 never observed"),
        # A candidate with no PR depends on the branches, which no run read.
        ("", "branches of repo not observed since 2026-10-20T11:30:00.000Z"),
    ],
    ids=["missing", "old", "blocker", "branches"],
)
def test_a_ticket_that_depends_on_a_stale_or_missing_observation_is_stale(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    statement: str,
    stale: str,
) -> None:
    if statement:
        observed.execute(statement)
    observed.commit()
    assert derived(canopy_env) == [phases.Derived(KEY, None, stale=stale)]


def test_without_a_tracker_source_a_public_ticket_is_stale(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    seen(conn, canopy_env)
    assert derived(canopy_env) == [phases.Derived(KEY, None, stale="no tracker source observes tickets")]


def test_a_unit_whose_pr_is_stale_is_stale(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    unit(canopy_env, observed)
    observe_pr(observed, at=OLD)
    observed.commit()
    assert derived(canopy_env)[1] == phases.Derived(KEY, "repo", stale=f"{PR} last observed {OLD}")


def test_a_check_the_repository_names_human_is_not_ci(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    canopy_env.configure(canopy_env.shared_file, {"repos": {"repo": {"human_checks": ["deploy/approval"]}}})
    green(canopy_env, observed)
    check(observed, "deploy/approval", "pending", None)
    observed.commit()
    assert derived(canopy_env)[1].phases == (phases.Phase.GREEN_UNREVIEWED,)


def test_a_failure_the_ci_cursor_has_passed_is_not_ci_red(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    unit(canopy_env, observed, ci="11")
    observe_pr(observed)
    check(observed, conclusion="failure")
    observed.commit()
    assert derived(canopy_env)[1].phases == ()


def test_a_bot_approval_is_no_approval_and_feedback_at_the_cursor_is_handled(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    unit(canopy_env, observed, review="2026-10-20T11:59:00Z")
    observe_pr(observed)
    check(observed)
    review(observed, "stranger", "commented", body="Why?")
    observed.execute("UPDATE observed_reviews SET bot = 1, state = 'approved'")
    observed.commit()
    assert derived(canopy_env)[1].phases == (phases.Phase.GREEN_UNREVIEWED,)


def test_a_comment_on_an_artifact_that_is_authority_is_a_reply(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    case_needs_human(canopy_env, observed)
    canopy_env.configure(canopy_env.user_file, {"artifacts": {"authorized_authors": ["u_ana"]}})
    artifact_comment(observed, "c1", "u_bob")
    observed.commit()
    [own] = [d for d in derived(canopy_env) if d.repo is None]
    assert (Phase.NEEDS_HUMAN in own.phases, Phase.HUMAN_REPLIED in own.phases) == (True, False)
    # A listed author's is, as an operator message is (DESIGN §38).
    artifact_comment(observed, "c2", "u_ana")
    observed.commit()
    [own] = [d for d in derived(canopy_env) if d.repo is None]
    assert Phase.HUMAN_REPLIED in own.phases


def test_a_private_ticket_needs_a_human_from_the_journal_alone(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    seen(conn, canopy_env)
    conn.execute(
        "INSERT INTO starts (subject_kind, subject_id, status, started_at, channel) "
        "VALUES ('ticket', ?, 'started', ?, 'cli')",
        (KEY, FRESH),
    )
    run = running(conn)
    conn.execute("UPDATE runs SET status = 'blocked', ended_at = ? WHERE id = ?", (FRESH, run))
    branches_read(conn, f"agent/{KEY}-work")
    conn.commit()
    assert derived(canopy_env)[0] == phases.Derived(
        KEY,
        None,
        (phases.Phase.NEEDS_HUMAN,),
        candidate=True,
        closed=False,
    )


def test_an_untrusted_review_waits_on_an_operator_reply_and_no_verbs_instruction(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    case_untrusted_review(canopy_env, observed)
    ticket = conversation.Ref(conversation.TICKET, KEY)
    with db.transaction(observed):
        conversation.write_reply(
            observed,
            ticket,
            "Address item 1 of feedback plan 1.",
            channel="cli",
            submission="x",
            answers=False,
        )
    assert any(phases.Phase.UNTRUSTED_REVIEW in d.phases for d in derived(canopy_env))
    with db.transaction(observed):
        conversation.write_reply(observed, ticket, "Go ahead with the map.", channel="cli", submission=None)
    assert not any(phases.Phase.UNTRUSTED_REVIEW in d.phases for d in derived(canopy_env))


def recorded(conn: sqlite3.Connection, tick_id: int, *derived: phases.Derived) -> None:
    """Record `derived` as tick `tick_id`'s derivation."""
    phases.record(conn, tick_id, derived)


@pytest.mark.parametrize(
    ("phase", "actions", "verdict"),
    [
        ("ci_red", ["dispatch:resume"], "agrees"),
        ("ci_red", ["wait", "attention:attempt_limit"], "agrees"),
        ("ci_running", ["wait"], "disagrees"),
        ("ci_red", ["attention:needs_reviewer"], "disagrees"),
        ("ci_red", ["attention:crashed"], "disagrees"),
    ],
    ids=["resume", "wait-at-limit", "other-phase", "other-action", "harness-item-only"],
)
def test_a_ticket_agrees_when_the_overseer_set_a_row_that_held_and_decided_what_it_allows(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    phase: str,
    actions: list[str],
    verdict: str,
) -> None:
    unit(canopy_env, conn)
    with in_tick(conn) as tick_id:
        recorded(
            conn,
            tick_id,
            phases.Derived(KEY, None, (), candidate=True, closed=False),
            phases.Derived(KEY, "repo", (phases.Phase.CI_RED, phases.Phase.CONFLICTED)),
        )
        db.set_unit(conn, KEY, str(canopy_env.root), "repo", phase=phase)
        for action in actions:
            db.record_decision(conn, tick_id, KEY, action, "because")
        phases.record_overseer(conn, tick_id)
    [compared] = phases.compare(conn, tick_id)
    assert compared.verdict == verdict, compared.why


@pytest.mark.parametrize(
    ("action", "verdict"),
    [("dispatch:implement", "agrees"), ("dispatch:plan", "agrees"), ("wait", "disagrees")],
)
def test_a_ready_ticket_the_overseer_dispatched_agrees_though_it_left_it_running(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    action: str,
    verdict: str,
) -> None:
    seen(conn, canopy_env)
    with in_tick(conn) as tick_id:
        recorded(conn, tick_id, phases.Derived(KEY, None, (phases.Phase.READY,), candidate=True, closed=False))
        db.record_decision(conn, tick_id, KEY, action, "because")
        db.set_ticket(conn, KEY, str(canopy_env.root), phase=phases.Phase.RUNNING)
        phases.record_overseer(conn, tick_id)
    [compared] = phases.compare(conn, tick_id)
    assert compared.verdict == verdict, compared.why


def test_a_closed_ticket_agrees_when_marked_done_and_a_stale_one_is_counted_apart(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    with in_tick(conn) as tick_id:
        recorded(
            conn,
            tick_id,
            phases.Derived("PROJ-1", None, candidate=False, closed=True),
            phases.Derived("PROJ-2", None, stale="PROJ-2 never observed"),
            phases.Derived("PROJ-3", None, (phases.Phase.READY,), candidate=True, closed=False),
        )
        db.record_decision(conn, tick_id, "PROJ-1", "done", "closed")
        db.record_decision(conn, tick_id, "PROJ-2", "wait", "why not")
        db.record_decision(conn, tick_id, "PROJ-3", "wait", "no capacity")
        phases.record_overseer(conn, tick_id)
    assert [(c.ticket_key, c.verdict) for c in phases.compare(conn, tick_id)] == [
        ("PROJ-1", "agrees"),
        ("PROJ-2", "stale"),
        ("PROJ-3", "disagrees"),
    ]
    counts = phases.tally(conn, tick_id)
    assert phases.describe(counts) == "derived 1 agree, 1 disagree, 1 stale"
    assert phases.describe(Counter()) == ""


def test_a_tick_derives_in_shadow_and_records_the_phase_its_overseer_left(
    scenario: Scenario,
    connector_state: Path,
) -> None:
    scenario.configures(
        "private",
        connect={
            "sources": {
                "jira": {"kind": "tracker", "cmd": "connector jira", "timeout_minutes": 1},
                "github": {"kind": "vcs", "cmd": "connector github", "timeout_minutes": 1},
            },
        },
    )
    scenario.seen("PROJ-1", "PROJ-2")
    labeled = [{"name": LABEL}, {"name": "needs-human", "added_at": "2026-10-18T09:00:00Z"}]
    lines = [
        {"kind": "ticket", "key": "PROJ-1", "title": "One", "state": "open", "labels": labeled},
        {"kind": "ticket", "key": "PROJ-2", "title": "Two", "state": "open", "labels": [{"name": LABEL}]},
    ]
    connector_state.write_text(json.dumps({"jira": {"lines": lines, "query": ["PROJ-1", "PROJ-2"]}}))
    ticked = scenario.tick(
        canopy("ticket", "set", "PROJ-1", "--phase", "needs_human"),
        canopy("decide", "PROJ-1", "wait", "--rationale", "waits on a human"),
        canopy("ticket", "set", "PROJ-2", "--phase", "needs_human"),
        canopy("decide", "PROJ-2", "wait", "--rationale", "waits on a human"),
        queried=None,
    )
    tick_id = ticked.tick.id
    rows = records.fetch_all(
        scenario.conn,
        records.Derivation,
        sql.frag("SELECT * FROM derivations ORDER BY ticket_key"),
    )
    assert [(r.ticket_key, json.loads(r.phases), r.overseer_phase) for r in rows] == [
        ("PROJ-1", ["ready", "needs_human"], "needs_human"),
        ("PROJ-2", ["ready"], "needs_human"),
    ]
    assert {(c.ticket_key, c.verdict) for c in phases.compare(scenario.conn, tick_id)} == {
        ("PROJ-1", "agrees"),
        ("PROJ-2", "disagrees"),
    }
    # In shadow: the derivation decides nothing. The query the source read is the harness's to record (DESIGN §6).
    assert [d.action for d in db.decisions_for_tick(scenario.conn, tick_id)] == ["queried", "wait", "wait"]
