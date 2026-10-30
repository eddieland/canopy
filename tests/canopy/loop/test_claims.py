"""A dispatch's claims, and a ticket set's cursors, checked in code against the connectors' observations (DESIGN §35).

Each case writes what the connectors observed by hand, at the real time, since a dispatch reads them at it, and
dispatches through the `canopy dispatch` command and the `dispatch` tool, each in a dry-run tick of its own: both must
record the same decision, a refusal or the run the dispatch would have started, with the cursors it would move. A
ticket set goes through `canopy ticket set` and the `ticket-set` tool the same way, and records a decision only when it
is refused. A dispatch's default cursors (DESIGN §37) are read from the dry run's decision, and seen moved by a live
one once its worker starts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db, notice, review_runs
from canopy.core.vocab import NumberedItem, ResumeReason, ReviewRunStatus, RunKind
from canopy.loop import observations
from tests.canopy.helpers import (
    KEY,
    LABEL,
    decisions,
    in_tick,
    last_run,
    mcp_session,
    operator,
    present,
    tick_starts,
    tool_call,
    wait_for_run,
)
from tests.canopy.observation_helpers import (
    HEAD,
    PR,
    TRACKER,
    TRUST,
    artifact_comment,
    branches_read,
    check,
    comment,
    held,
    number_of,
    observe_pr,
    observe_ticket,
    review,
    sent_draft,
)
from tests.canopy.scenario_helpers import dispatches, pushes

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    from tests.canopy.conftest import Ws
    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv

BRANCH = f"agent/{KEY}-work"
#: When the comments and review items here were written: long before the observations, which are the real time's.
EARLIER = "2026-10-01T10:00:00Z"
LATER = "2026-10-01T11:00:00Z"


@pytest.fixture
def observed(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> sqlite3.Connection:
    """KEY observed fresh, labeled, with a branch and its PR in `repo`, held since before it was read.

    Returns the journal.
    """
    canopy_env.configure(canopy_env.user_file, {**TRACKER, **TRUST})
    held(canopy_env, conn, KEY, at=ago(hours=1))
    with_unit(canopy_env, conn, KEY)
    observe_ticket(conn, at=ago())
    observe_pr(conn, at=ago())
    branches_read(conn, at=ago())
    return conn


def test_a_label_not_observed_on_the_ticket_is_unauthorized(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    canopy_env.configure(canopy_env.user_file, TRACKER)
    held(canopy_env, conn, KEY, at=ago(hours=1))
    observe_ticket(conn, labels={"bug": None}, at=ago())
    branches_read(conn, at=ago())
    action, reason = dispatched(conn, kind="implement", label=LABEL)
    assert action == "refused:unauthorized"
    assert reason.startswith(f"{LABEL!r} was not on {KEY} when the tracker source last read it")


def test_a_label_observed_case_insensitively_dispatches(observed: sqlite3.Connection) -> None:
    assert dispatched(observed, kind="resume", label=LABEL.upper(), reasons=["conflict"])[0] == "dispatch:resume"


@pytest.mark.parametrize(
    ("stale", "why"),
    [
        pytest.param("ticket", f"{KEY} is stale ({KEY} last observed", id="the-ticket"),
        pytest.param("pr", f"{KEY} in repo is stale ({PR} last observed", id="its-units-pr"),
    ],
)
def test_a_dispatch_on_a_stale_subject_is_refused(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    stale: str,
    why: str,
) -> None:
    canopy_env.configure(canopy_env.user_file, {**TRACKER, **TRUST})
    held(canopy_env, conn, KEY, at=ago(hours=2))
    with_unit(canopy_env, conn, KEY)
    observe_ticket(conn, at=ago(hours=1) if stale == "ticket" else ago())
    observe_pr(conn, at=ago(hours=1) if stale == "pr" else ago())
    branches_read(conn, at=ago())
    action, reason = dispatched(conn, kind="resume", label=LABEL, reasons=["conflict"])
    assert action == "refused:stale"
    assert reason.startswith(why)


def test_a_recorded_dispatch_whose_ticket_went_stale_before_its_start_is_refused_then(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    """The claims are checked again as the tick starts the run: fresh at the ask, stale by then, it starts nothing."""
    canopy_env.configure(canopy_env.user_file, {**TRACKER, **TRUST})
    held(canopy_env, conn, KEY, at=ago(hours=2))
    with_unit(canopy_env, conn, KEY)
    observe_ticket(conn, at=ago(hours=0.25))
    observe_pr(conn, at=ago())
    branches_read(conn, at=ago())
    command = ["dispatch", KEY, "--repo", "repo", "--kind", "resume", "--label", LABEL, "--reason", "conflict"]
    with in_tick(conn) as tick_id:
        assert main(command) == 0
        assert decisions(conn, tick_id) == []
        # Its bound shrinks past the ticket's age, as an overseer run that outlasts it would leave it.
        canopy_env.configure(canopy_env.user_file, {"connect": {"max_age_minutes": 10}})
        tick_starts()
        [(action, reason)] = decisions(conn, tick_id)
    assert action == "refused:stale"
    assert reason.startswith(f"{KEY} is stale ({KEY} last observed")


def test_a_stacked_dispatch_on_a_blockers_stale_pr_is_refused(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    blocker = "https://github.com/acme/repo/pull/8"
    with_unit(canopy_env, observed, "PROJ-2", pr=blocker)
    observe_pr(observed, url=blocker, at=ago(hours=1))
    action, reason = dispatched(observed, kind="implement", label=LABEL, base="agent/PROJ-2-work")
    assert action == "refused:stale"
    assert reason.startswith(f"blocker PROJ-2 in repo is stale ({blocker} last observed")


@pytest.mark.parametrize(
    ("author", "source", "action"),
    [
        pytest.param("acc-1", "tracker", "dispatch:resume", id="an-authorized-reply"),
        pytest.param("acc-9", "tracker", "refused:unauthorized", id="someone-not-authorized"),
        pytest.param("acc-1", "worker", "refused:unauthorized", id="a-workers-comment"),
    ],
)
def test_a_resume_for_reply_needs_a_new_authorized_reply_not_a_workers(
    observed: sqlite3.Connection,
    author: str,
    source: str,
    action: str,
) -> None:
    number = comment(observed, "101", author, EARLIER, "Go ahead.", source=source)
    found = dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors={"comment": str(number)})
    assert found[0] == action


def test_a_resume_for_reply_may_rest_on_an_operator_message_instead(observed: sqlite3.Connection) -> None:
    reply = {"comment": str(comment(observed, "101", "acc-9", EARLIER, "Go ahead."))}
    assert dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors=reply)[0] == (
        "refused:unauthorized"
    )
    assert operator("reply", KEY, "Do what acc-9 asks.") == 0
    [message] = conversation.operator_messages_after(observed, KEY, 0)
    cursors = {**reply, "message": str(message.id)}
    assert dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors=cursors)[0] == "dispatch:resume"


@pytest.mark.parametrize(
    ("author", "kind", "marked", "action"),
    [
        pytest.param("u_ana", "person", False, "dispatch:resume", id="a-listed-authors"),
        pytest.param("u_bob", "person", False, "refused:unauthorized", id="an-unlisted-authors"),
        pytest.param("u_ana", "agent", False, "refused:unauthorized", id="an-agents"),
        pytest.param("u_ana", "person", True, "refused:unauthorized", id="one-with-the-workers-marks"),
    ],
)
def test_a_resume_for_reply_may_rest_on_a_comment_on_an_artifact_that_is_authority(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    author: str,
    kind: str,
    marked: bool,  # noqa: FBT001  (a parametrized argument)
    action: str,
) -> None:
    # Cited by its message, as an operator message is (DESIGN §38).
    canopy_env.configure(canopy_env.user_file, {"artifacts": {"authorized_authors": ["u_ana"]}})
    message = artifact_comment(observed, "c1", author, kind=kind, marked=marked)
    observed.commit()
    cursors = {"message": str(message)}
    assert dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors=cursors)[0] == action


def test_a_resume_for_review_covers_a_trusted_reviewers_item(observed: sqlite3.Connection) -> None:
    number = review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    found = dispatched(observed, kind="resume", label=LABEL, reasons=["review"], cursors={"review": str(number)})
    assert found[0] == "dispatch:resume"


def test_a_review_submitted_after_a_later_comment_is_still_new(observed: sqlite3.Connection) -> None:
    # A review dated before a comment the cursor passed, but first observed after it: its number is newer, so a resume
    # for review covers it, where a time cursor would have taken it as handled.
    passed = review(observed, 2, "octocat", None, LATER, "Use a map.", item="comment")
    observed.execute("UPDATE ticket_units SET review_cursor = ?", (passed,))
    late = review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    assert late > passed
    found = dispatched(observed, kind="resume", label=LABEL, reasons=["review"], cursors={"review": str(late)})
    assert found[0] == "dispatch:resume"


def test_untrusted_review_items_need_an_operator_message_after_them(observed: sqlite3.Connection) -> None:
    review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    covered = {"review": str(review(observed, 2, "stranger", None, LATER, "Why not a map?", item="comment"))}
    action, reason = dispatched(observed, kind="resume", label=LABEL, reasons=["review"], cursors=covered)
    assert action == "refused:unauthorized"
    assert reason.startswith(f"review comment 2 on {KEY} in repo is not a trusted reviewer's")
    assert operator("reply", KEY, "Take the map suggestion.") == 0
    [message] = conversation.operator_messages_after(observed, KEY, 0)
    cursors = {**covered, "message": str(message.id)}
    found = dispatched(observed, kind="resume", label=LABEL, reasons=["review", "reply"], cursors=cursors)
    assert found[0] == "dispatch:resume"


def test_a_reply_the_operator_sent_is_no_feedback_on_a_pr_they_did_not_open(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    # Known by its id, not by its author: on someone else's PR the operator's login is no PR author's.
    observed.execute("UPDATE observed_prs SET author = 'teammate'")
    review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    covered = {"review": str(review(observed, 2, "operator", None, LATER, "Renamed.", item="comment"))}
    action, reason = dispatched(observed, kind="resume", label=LABEL, reasons=["review"], cursors=covered)
    assert action == "refused:unauthorized"
    assert reason.startswith(f"review comment 2 on {KEY} in repo is not a trusted reviewer's")
    sent_draft(canopy_env, observed, comment_id=2, review_id=90)
    observed.commit()
    found = dispatched(observed, kind="resume", label=LABEL, reasons=["review"], cursors=covered)
    assert found[0] == "dispatch:resume"


def test_a_resume_for_review_covering_nothing_is_unauthorized(observed: sqlite3.Connection) -> None:
    action, reason = dispatched(observed, kind="resume", label=LABEL, reasons=["review"])
    assert action == "refused:unauthorized"
    assert reason.startswith(f"a resume for review covers no feedback by a trusted reviewer on {KEY} in repo")


def test_a_joint_resume_for_review_keeps_its_claim(ws_scenario: Scenario, ws: Ws) -> None:
    # A joint resume carries no unit's review cursor, so it covers nothing to check: its claim stays a claim.
    conn, web = ws_scenario.conn, "https://github.com/acme/web/pull/8"
    ws_scenario.configures("private", trust={"trusted_reviewers": ["octocat"]})
    db.touch_ticket(conn, KEY, str(ws.root))
    conn.execute("UPDATE tickets SET branch = ?", (BRANCH,))
    for repo, url in (("api", PR), ("web", web)):
        conn.execute("INSERT INTO ticket_units (ticket_key, repo, branch) VALUES (?, ?, ?)", (KEY, repo, BRANCH))
        db.set_unit(conn, KEY, str(ws.root), repo, pr_url=url)
        observe_pr(conn, url=url, at=ago())
    review(conn, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    observe_ticket(conn, at=ago())
    joint = ["dispatch", KEY, "--repo", "api", "--repo", "web", "--kind", "resume", "--label", LABEL]
    ws_scenario.overseer(*joint, "--reason", "review", dry_run=True)


@pytest.mark.parametrize(
    ("cursors", "reasons", "why"),
    [
        pytest.param(
            {"comment": "999"},
            ["reply"],
            "comment cursor 999 is the number of no comment observed",
            id="a-comment",
        ),
        pytest.param(
            {"review": "999"},
            ["review"],
            "review cursor 999 is the number of no review item",
            id="a-review",
        ),
        pytest.param(
            {"ci": "77"},
            ["ci"],
            f"ci cursor 77 is the number of no check run observed at the head of {PR}",
            id="ci",
        ),
    ],
)
def test_a_cursor_naming_nothing_observed_is_unobserved(
    observed: sqlite3.Connection,
    cursors: Mapping[str, str],
    reasons: Sequence[str],
    why: str,
) -> None:
    comment(observed, "101", "acc-1", EARLIER, "Go ahead.")
    review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    check(observed, "build", "completed", "failure", run_id=12)
    action, reason = dispatched(observed, kind="resume", label=LABEL, reasons=reasons, cursors=cursors)
    assert action == "refused:unobserved"
    assert reason.startswith(why)


def test_a_cursor_past_what_the_block_left_out_is_unobserved(observed: sqlite3.Connection) -> None:
    numbers = [
        comment(observed, f"{200 + n}", "acc-1", f"2026-10-01T10:{n:02}:00Z", f"Comment {n}.")
        for n in range(observations.MAX_NEW_ITEMS + 1)
    ]
    shown = {"comment": str(numbers[-2])}
    assert dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors=shown)[0] == "dispatch:resume"
    action, reason = dispatched(
        observed,
        kind="resume",
        label=LABEL,
        reasons=["reply"],
        cursors={"comment": str(numbers[-1])},
    )
    assert action == "refused:unobserved"
    assert "passes comments on PROJ-1 the state block left out" in reason


@pytest.mark.parametrize(
    ("before", "newest", "action"),
    [
        pytest.param([("build", HEAD)], 12, "refused:handled", id="red-to-red-at-the-same-head"),
        pytest.param([], 11, "refused:handled", id="the-same-run-still-red"),
        pytest.param([("lint", HEAD)], 12, "dispatch:resume", id="another-context-failed-before"),
        pytest.param([("build", "def5678")], 12, "dispatch:resume", id="it-failed-at-an-earlier-head"),
    ],
)
def test_a_resume_for_ci_alone_needs_a_failure_no_worker_had(
    observed: sqlite3.Connection,
    before: Sequence[tuple[str, str]],
    newest: int,
    action: str,
) -> None:
    # The unit's ci cursor is at run 11, which failed as `before` says; the build's newest run at the head is `newest`.
    for name, head in before:
        check(observed, name, "completed", "failure", run_id=11, head=head)
    check(observed, "build", "completed", "failure", run_id=newest)
    observed.execute("UPDATE ticket_units SET ci_cursor = ?", (number_of(observed, NumberedItem.CHECK_RUN, 11),))
    cursor = number_of(observed, NumberedItem.CHECK_RUN, newest)
    found = dispatched(observed, kind="resume", label=LABEL, reasons=["ci"], cursors={"ci": str(cursor)})
    assert found[0] == action
    if action == "refused:handled":
        assert found[1].startswith(f"every failed check at the head of {PR} (build) failed at that head at or behind")


@pytest.mark.parametrize("role", ["human", "merge", "ignore"])
def test_a_check_its_repository_says_is_not_ci_starts_no_resume_for_ci(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    role: str,
) -> None:
    # The build failed at run 11, which a worker had; `owners` failed since, at run 12, and is not CI.
    canopy_env.configure(canopy_env.shared_file, {"repos": {"repo": {"checks": {"owners": role}}}})
    check(observed, "build", "completed", "failure", run_id=11)
    check(observed, "owners", "completed", "failure", run_id=12)
    had = str(number_of(observed, NumberedItem.CHECK_RUN, 11))
    # Its failure moves no default ci cursor past the build's.
    assert moved(dispatched(observed, kind="resume", label=LABEL, reasons=["ci"])[1]) == {"ci": had}
    observed.execute("UPDATE ticket_units SET ci_cursor = ?", (had,))
    action, reason = dispatched(observed, kind="resume", label=LABEL, reasons=["ci"], cursors={"ci": had})
    assert action == "refused:handled"
    assert reason.startswith(f"every failed check at the head of {PR} (build) failed at that head")


@pytest.mark.parametrize(
    ("reasons", "cursor"),
    [
        pytest.param(["ci", "conflict"], 11, id="not-for-ci-alone"),
        pytest.param(["ci"], None, id="with-the-ci-cursor-empty"),
    ],
)
def test_a_re_run_red_again_is_not_handled(
    observed: sqlite3.Connection,
    reasons: Sequence[str],
    cursor: int | None,
) -> None:
    check(observed, "build", "completed", "failure", run_id=11)
    check(observed, "build", "completed", "failure", run_id=12)
    # The unit's ci cursor at the run it names, or empty.
    first = None if cursor is None else number_of(observed, NumberedItem.CHECK_RUN, cursor)
    observed.execute("UPDATE ticket_units SET ci_cursor = ?", (first,))
    again = str(number_of(observed, NumberedItem.CHECK_RUN, 12))
    found = dispatched(observed, kind="resume", label=LABEL, reasons=reasons, cursors={"ci": again})
    assert found[0] == "dispatch:resume"


def test_a_private_ticket_is_not_refused(observed: sqlite3.Connection) -> None:
    # Its start record authorizes it, whatever was observed of it, stale included (DESIGN §22).
    assert operator("start", KEY) == 0
    observed.execute("UPDATE observed_tickets SET observed_at = ?, labels = '[]'", (ago(hours=1),))
    assert dispatched(observed, kind="resume", reasons=["reply"])[0] == "dispatch:resume"


def test_a_private_tickets_re_run_red_again_is_not_handled(observed: sqlite3.Connection) -> None:
    assert operator("start", KEY) == 0
    check(observed, "build", "completed", "failure", run_id=11)
    check(observed, "build", "completed", "failure", run_id=12)
    observed.execute("UPDATE ticket_units SET ci_cursor = ?", (number_of(observed, NumberedItem.CHECK_RUN, 11),))
    again = str(number_of(observed, NumberedItem.CHECK_RUN, 12))
    assert dispatched(observed, kind="resume", reasons=["ci"], cursors={"ci": again})[0] == "dispatch:resume"


def test_an_unobserved_pr_keeps_its_ci_claim(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    # No source reads a PR of another host: what failed there, and whether a worker had it, stays the overseer's word.
    held(canopy_env, conn, KEY, at=ago(hours=1))
    observe_ticket(conn, at=ago())
    with_unit(canopy_env, conn, KEY, pr="https://git.example.com/acme/repo/-/merge_requests/7")
    conn.execute("UPDATE ticket_units SET ci_cursor = 11")
    assert dispatched(conn, kind="resume", label=LABEL, reasons=["ci"], cursors={"ci": "12"})[0] == "dispatch:resume"


def test_a_resume_moves_each_cursor_of_its_reasons_to_the_newest_item_shown(observed: sqlite3.Connection) -> None:
    # It passes none: each defaults to the newest item of its kind the block showed (DESIGN §37).
    comment(observed, "101", "acc-1", EARLIER, "Go ahead.")
    said = comment(observed, "102", "acc-9", LATER, "Me too.")
    check(observed, "build", "completed", "failure", run_id=11)
    check(observed, "lint", "completed", "failure", run_id=12)
    check(observed, "docs", "completed", "success", run_id=13)
    review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    newest = review(observed, 2, "octocat", None, LATER, "Use a map.", item="comment")
    assert operator("reply", KEY, "And bump the version.") == 0
    [message] = conversation.operator_messages_after(observed, KEY, 0)
    action, rationale = dispatched(observed, kind="resume", label=LABEL, reasons=["reply", "ci", "review"])
    assert action == "dispatch:resume"
    assert moved(rationale) == {
        # The newest comment, an authorized reply's or not, since one before it authorizes the run.
        "comment": str(said),
        "message": str(message.id),
        "ci": str(number_of(observed, NumberedItem.CHECK_RUN, 12)),
        "review": str(newest),
    }


def test_a_resume_moves_no_cursor_of_a_reason_it_does_not_name(observed: sqlite3.Connection) -> None:
    comment(observed, "101", "acc-1", EARLIER, "Go ahead.")
    check(observed, "build", "completed", "failure", run_id=11)
    review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    action, rationale = dispatched(observed, kind="resume", label=LABEL, reasons=["ci"])
    assert action == "dispatch:resume"
    assert moved(rationale) == {"ci": str(number_of(observed, NumberedItem.CHECK_RUN, 11))}


def test_a_ci_cursor_has_no_default_while_a_notice_may_hold_a_check(observed: sqlite3.Connection) -> None:
    # Whether the notice explains the failure is the overseer's judgment (DESIGN §8), so it names the cursor itself.
    check(observed, "build", "completed", "failure", run_id=11)
    notice.set_notice(observed, "Artifactory is down.", minutes=60, channel="cli")
    action, rationale = dispatched(observed, kind="resume", label=LABEL, reasons=["ci"])
    assert action == "dispatch:resume"
    assert moved(rationale) == {}


def test_a_message_the_tick_had_not_read_is_not_passed(observed: sqlite3.Connection) -> None:
    # The block shows the messages the tick read before the overseer ran; one sent since waits for the next tick.
    assert operator("reply", KEY, "Go ahead.") == 0
    [message] = conversation.operator_messages_after(observed, KEY, 0)
    with in_tick(observed, dry_run=True) as tick_id:
        db.set_tick_read(observed, tick_id)
        assert operator("reply", KEY, "And bump the version.") == 0
        main(["dispatch", KEY, "--repo", "repo", "--kind", "resume", "--label", LABEL, "--reason", "reply"])
        [(action, rationale)] = decisions(observed, tick_id)
    assert action == "dispatch:resume"
    assert moved(rationale) == {"message": str(message.id)}


def test_a_review_cursor_stops_short_of_untrusted_feedback(observed: sqlite3.Connection) -> None:
    trusted = review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    untrusted = review(observed, 2, "stranger", None, LATER, "Why not a map?", item="comment")
    after = review(observed, 3, "octocat", None, LATER, "And a test.", item="comment")
    action, rationale = dispatched(observed, kind="resume", label=LABEL, reasons=["review"])
    assert action == "dispatch:resume"
    assert moved(rationale) == {"review": str(trusted)}
    # An operator message after it, which the dispatch carries, is the go-ahead to cover it.
    assert operator("reply", KEY, "Take the map suggestion.") == 0
    [message] = conversation.operator_messages_after(observed, KEY, 0)
    action, rationale = dispatched(observed, kind="resume", label=LABEL, reasons=["review", "reply"])
    assert action == "dispatch:resume"
    assert moved(rationale) == {"message": str(message.id), "review": str(after)}
    assert untrusted < after


def test_a_review_cursor_covering_nothing_it_may_moves_nowhere(observed: sqlite3.Connection) -> None:
    # The first new item waits on the operator, so nothing defaults, and the resume covers nothing it may address.
    review(observed, 1, "stranger", "changes_requested", EARLIER, "Why not a map?")
    action, reason = dispatched(observed, kind="resume", label=LABEL, reasons=["review"])
    assert action == "refused:unauthorized"
    assert reason.startswith(f"a resume for review covers no feedback by a trusted reviewer on {KEY} in repo")


def test_a_review_cursor_moves_to_the_end_of_the_review_run_it_names(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    canopy_env.configure(canopy_env.user_file, {"trust": {"trusted_reviewers": ["canopy:review"]}})
    run = reviewed(observed)
    end = present(review_runs.get_review_run(observed, run)).number
    action, rationale = dispatched(observed, kind="resume", label=LABEL, reasons=["review"], review_run=run)
    assert action == "dispatch:resume"
    assert moved(rationale) == {"review": str(end)}


@pytest.mark.parametrize("kind", ["comment", "review"])
def test_a_default_cursor_passes_nothing_the_block_left_out(observed: sqlite3.Connection, kind: str) -> None:
    numbers = [
        comment(observed, f"{200 + n}", "acc-1", f"2026-10-01T10:{n:02}:00Z", f"Comment {n}.")
        if kind == "comment"
        else review(observed, 200 + n, "octocat", None, f"2026-10-01T10:{n:02}:00Z", f"Fix {n}.", item="comment")
        for n in range(observations.MAX_NEW_ITEMS + 1)
    ]
    reason = "reply" if kind == "comment" else "review"
    action, rationale = dispatched(observed, kind="resume", label=LABEL, reasons=[reason])
    assert action == "dispatch:resume"
    assert moved(rationale) == {kind: str(numbers[-2])}


def test_a_cursor_passed_stops_shorter(observed: sqlite3.Connection) -> None:
    first = comment(observed, "101", "acc-1", EARLIER, "Go ahead.")
    comment(observed, "102", "acc-1", LATER, "Wait, I need to ask the team first.")
    passed = {"comment": str(first)}
    action, rationale = dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors=passed)
    assert action == "dispatch:resume"
    assert moved(rationale) == passed


def test_a_private_ticket_gets_no_default_cursor(observed: sqlite3.Connection) -> None:
    # Its start record authorizes it, not an observation, so no default rests on one: the overseer names its cursors.
    assert operator("start", KEY) == 0
    assert operator("reply", KEY, "Go ahead.") == 0
    action, rationale = dispatched(observed, kind="resume", reasons=["reply"])
    assert action == "dispatch:resume"
    assert moved(rationale) == {}


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize("door", ["command", "tool"])
def test_default_cursors_move_once_the_worker_starts(scenario: Scenario, door: str) -> None:
    conn = with_a_fresh_pr(scenario)
    comment(conn, "101", "acc-1", EARLIER, "Go ahead.")
    said = comment(conn, "102", "acc-1", LATER, "Also the docs.")
    check(conn, "build", "completed", "failure", run_id=11)
    reviewed_item = review(conn, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    reasons = [ResumeReason.REPLY, ResumeReason.CI, ResumeReason.REVIEW]
    if door == "command":
        scenario.run(dispatches(kind=RunKind.RESUME, reasons=reasons), worker=pushes())
    else:
        resumed(conn, reasons)
    assert cursors_of(conn) == (said, number_of(conn, NumberedItem.CHECK_RUN, 11), reviewed_item)


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize("door", ["command", "tool"])
def test_a_refused_dispatch_moves_no_default_cursor(scenario: Scenario, door: str) -> None:
    conn = with_a_fresh_pr(scenario)
    comment(conn, "101", "acc-1", EARLIER, "Go ahead.")
    check(conn, "build", "completed", "failure", run_id=11)
    review(conn, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    reasons = [ResumeReason.REPLY, ResumeReason.CI, ResumeReason.REVIEW]
    # A label not on the ticket: the claims refuse it after its cursors defaulted.
    if door == "command":
        [(action, _)] = scenario.refuses(dispatches(kind=RunKind.RESUME, reasons=reasons, label="bug"))
        assert action == "refused:unauthorized"
    else:
        resumed(conn, reasons, label="bug", refused=True)
    assert cursors_of(conn) == (None, None, None)


@pytest.mark.parametrize(
    ("cursors", "why"),
    [
        pytest.param({"comment": "999"}, "comment cursor 999 is the number of no comment observed", id="a-comment"),
        pytest.param({"review": "999"}, "review cursor 999 is the number of no review item", id="a-review"),
        pytest.param({"ci": "77"}, f"ci cursor 77 is the number of no check run observed at the head of {PR}", id="ci"),
    ],
)
def test_a_ticket_set_cursor_naming_nothing_observed_is_unobserved(
    observed: sqlite3.Connection,
    cursors: Mapping[str, str],
    why: str,
) -> None:
    said = comment(observed, "101", "acc-1", EARLIER, "Go ahead.")
    reviewed = review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    check(observed, "build", "completed", "failure", run_id=12)
    [(action, reason)] = ticket_set(observed, cursors)
    assert action == "refused:unobserved"
    assert reason.startswith(why)
    ran = number_of(observed, NumberedItem.CHECK_RUN, 12)
    assert ticket_set(observed, {"comment": str(said), "review": str(reviewed), "ci": str(ran)}) == []


def test_a_ticket_set_cursor_past_what_the_block_left_out_is_unobserved(observed: sqlite3.Connection) -> None:
    numbers = [
        comment(observed, f"{200 + n}", "acc-1", f"2026-10-01T10:{n:02}:00Z", f"Comment {n}.")
        for n in range(observations.MAX_NEW_ITEMS + 1)
    ]
    assert ticket_set(observed, {"comment": str(numbers[-2])}) == []
    [(action, reason)] = ticket_set(observed, {"comment": str(numbers[-1])})
    assert action == "refused:unobserved"
    assert "passes comments on PROJ-1 the state block left out" in reason


def test_a_review_cursor_may_name_a_review_runs_end(observed: sqlite3.Connection) -> None:
    # A review run takes its number when it ends, which the block shows and the overseer passes as the cursor.
    tick_id = db.start_tick(observed, dry_run=False)
    run = observed.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, ticket_key, started_at, status, log_path) "
        "VALUES (?, ?, 'abc1234', ?, ?, 'running', 'x')",
        (tick_id, PR, KEY, "2026-10-01T11:59:00.000Z"),
    ).lastrowid
    assert run is not None
    assert db.finish_run(observed, "review_runs", run, ReviewRunStatus.DONE, None)
    number = present(review_runs.get_review_run(observed, run)).number
    assert ticket_set(observed, {"review": str(number)}) == []


@pytest.mark.parametrize(
    ("stale", "cursors", "why"),
    [
        pytest.param("ticket", {"comment": "1"}, "comment cursor 1 passes comments on PROJ-1", id="the-ticket"),
        pytest.param("pr", {"review": "2"}, f"review cursor 2: {KEY} in repo is stale", id="its-units-pr"),
    ],
)
def test_a_ticket_set_cursor_on_a_stale_subject_passes_nothing_new(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    stale: str,
    cursors: Mapping[str, str],
    why: str,
) -> None:
    # It starts nothing, so it is not refused stale, but the block shows nothing new of a stale subject to pass.
    canopy_env.configure(canopy_env.user_file, {**TRACKER, **TRUST})
    held(canopy_env, conn, KEY, at=ago(hours=2))
    with_unit(canopy_env, conn, KEY)
    observe_ticket(conn, at=ago(hours=1) if stale == "ticket" else ago())
    observe_pr(conn, at=ago(hours=1) if stale == "pr" else ago())
    branches_read(conn, at=ago())
    comment(conn, "101", "acc-1", EARLIER, "Go ahead.")
    review(conn, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    [(action, reason)] = ticket_set(conn, cursors)
    assert action == "refused:unobserved"
    assert reason.startswith(why)


def test_a_ticket_set_on_a_private_ticket_is_not_refused(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    # Its start record authorizes it, whatever was observed of it (DESIGN §22).
    held(canopy_env, conn, KEY, at=ago(hours=1))
    with_unit(canopy_env, conn, KEY, pr=None)
    canopy_env.configure(canopy_env.user_file, TRACKER)
    observe_ticket(conn, at=ago(hours=1))
    assert operator("start", KEY) == 0
    assert ticket_set(conn, {"comment": "999"}) == []


def test_the_operators_ticket_set_is_not_checked(observed: sqlite3.Connection) -> None:
    # Outside a tick it is the operator's, not a claim of the overseer's; with a tracker source, still a number.
    assert operator("ticket", "set", KEY, "--cursor", "comment=999") == 0
    assert present(db.get_ticket(observed, KEY)).comment_cursor == 999
    assert operator("ticket", "set", KEY, "--cursor", "comment=c-999") == 2


def dispatched(
    conn: sqlite3.Connection,
    *,
    kind: str,
    label: str | None = None,
    reasons: Sequence[str] = (),
    cursors: Mapping[str, str] | None = None,
    base: str | None = None,
    review_run: int | None = None,
) -> tuple[str, str]:
    """Dispatch KEY in `repo` through its command, then its tool, each in a dry-run tick of its own.

    Each tick has read the journal, as a tick does before its overseer runs, so it shows every message sent before.

    Returns:
        The one decision both recorded.
    """
    found = cursors or {}
    command = ["dispatch", KEY, "--repo", "repo", "--kind", kind]
    command += [*(["--label", label] if label else []), *(["--base", base] if base else [])]
    command += ["--review-run", str(review_run)] if review_run is not None else []
    command += [arg for reason in reasons for arg in ("--reason", reason)]
    command += [arg for name, value in found.items() for arg in ("--cursor", f"{name}={value}")]
    with in_tick(conn, dry_run=True) as tick_id:
        db.set_tick_read(conn, tick_id)
        main(command)
        by_command = decisions(conn, tick_id)
    arguments: dict[str, object] = {"key": KEY, "kind": kind, "repos": ["repo"], "reasons": list(reasons)}
    arguments |= {"cursors": dict(found)} | ({"label": label} if label else {}) | ({"base": base} if base else {})
    arguments |= {"review_run": review_run} if review_run is not None else {}
    with in_tick(conn, dry_run=True) as tick_id:
        db.set_tick_read(conn, tick_id)
        mcp_session(tool_call("dispatch", **arguments))
        by_tool = decisions(conn, tick_id)
    assert by_command == by_tool
    [decision] = by_command
    return decision


def ticket_set(conn: sqlite3.Connection, cursors: Mapping[str, str]) -> list[tuple[str, str]]:
    """Move KEY's cursors in `repo` through `canopy ticket set`, then its tool, each in a dry-run tick of its own.

    Returns:
        The decisions both recorded: none when they took the cursors, else the refusal.
    """
    command = ["ticket", "set", KEY, "--repo", "repo"]
    command += [arg for name, value in cursors.items() for arg in ("--cursor", f"{name}={value}")]
    with in_tick(conn, dry_run=True) as tick_id:
        code = main(command)
        by_command = decisions(conn, tick_id)
    with in_tick(conn, dry_run=True) as tick_id:
        setting = {"key": KEY, "repo": "repo", "cursors": dict(cursors)}
        said = mcp_session(tool_call("ticket-set", tickets=[setting])).said()
        by_tool = decisions(conn, tick_id)
    assert by_command == by_tool
    assert (code != 0, said.error) == (bool(by_command), bool(by_command)), said.text
    return by_command


def with_unit(env: CanopyEnv, conn: sqlite3.Connection, key: str, *, pr: str | None = PR) -> None:
    """Give `key` the branch its first implement would have recorded, and its unit in `repo` with `pr`."""
    branch = f"agent/{key}-work"
    db.touch_ticket(conn, key, str(env.root))
    conn.execute("UPDATE tickets SET branch = ? WHERE key = ?", (branch, key))
    conn.execute("INSERT INTO ticket_units (ticket_key, repo, branch) VALUES (?, 'repo', ?)", (key, branch))
    if pr is not None:
        db.set_unit(conn, key, str(env.root), "repo", pr_url=pr)


def ago(*, hours: float = 0) -> str:
    """The journal's form of the time `hours` ago: now, without any."""
    return db.format_time(datetime.now(UTC) - timedelta(hours=hours))


def moved(rationale: str) -> dict[str, str]:
    """The cursors a dry-run dispatch's rationale says it would move, by name."""
    found: dict[str, str] = {}
    for part in rationale.split("; "):
        if part.startswith("cursor "):
            name, _, value = part.removeprefix("cursor ").partition("=")
            found[name] = value
    return found


def reviewed(conn: sqlite3.Connection) -> int:
    """A canopy review run of KEY's PR at HEAD, ended done with a finding, so it took its number; return its id."""
    result = {
        "status": "done",
        "verdict": "findings",
        "impact": "normal",
        "findings": [{"severity": "major", "title": "X"}],
    }
    run = conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, ticket_key, started_at, status, log_path) "
        "VALUES (?, ?, ?, ?, ?, 'running', 'x')",
        (db.start_tick(conn, dry_run=False), PR, HEAD, KEY, ago()),
    ).lastrowid
    assert run is not None
    assert db.finish_run(conn, "review_runs", run, ReviewRunStatus.DONE, json.dumps(result))
    return run


def with_a_fresh_pr(scenario: Scenario) -> sqlite3.Connection:
    """KEY observed fresh and labeled, implemented in `repo` with PR its pull request, and PR observed fresh at HEAD.

    Returns:
        The journal.
    """
    env, conn = scenario.env, scenario.conn
    scenario.configures(**TRACKER, **TRUST)
    held(env, conn, KEY, at=ago(hours=1))
    observe_ticket(conn, at=ago())
    branches_read(conn, at=ago())
    scenario.run(dispatches(), worker=pushes(prs={"repo": PR}))
    observe_pr(conn, at=ago())
    return conn


def resumed(
    conn: sqlite3.Connection,
    reasons: Sequence[ResumeReason],
    *,
    label: str = LABEL,
    refused: bool = False,
) -> None:
    """The overseer resumes KEY in `repo` for `reasons` through the `dispatch` tool, passing no cursor.

    It runs in a tick of its own, which starts the run it recorded, as a tick does once its overseer has ended, and the
    run is waited for; with `refused`, the tool must refuse it.
    """
    arguments = {"key": KEY, "kind": "resume", "label": label, "repos": ["repo"], "reasons": [str(r) for r in reasons]}
    with in_tick(conn, ends_ok=True):
        said = mcp_session(tool_call("dispatch", **arguments)).said()
        assert said.error == refused, said.text
        if not refused:
            tick_starts()
    if not refused:
        wait_for_run(conn, int(last_run(conn)["id"]))


def cursors_of(conn: sqlite3.Connection) -> tuple[int | None, int | None, int | None]:
    """KEY's `comment` cursor, and its unit's in `repo` `ci` and `review` cursors."""
    [unit] = conn.execute("SELECT ci_cursor, review_cursor FROM ticket_units WHERE ticket_key = ?", (KEY,)).fetchall()
    return present(db.get_ticket(conn, KEY)).comment_cursor, unit["ci_cursor"], unit["review_cursor"]
