"""A dispatch's claims, and a ticket set's cursors, checked in code against the connectors' observations (DESIGN §35).

Each case writes what the connectors observed by hand, at the real time, since a dispatch reads them at it, and
dispatches through the `canopy dispatch` command and the `dispatch` tool, each in a dry-run tick of its own: both must
record the same decision, a refusal or the run the dispatch would have started. A ticket set goes through `canopy
ticket set` and the `ticket-set` tool the same way, and records a decision only when it is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db, review_runs
from canopy.core.vocab import NumberedItem, ReviewRunStatus
from canopy.loop import observations
from tests.canopy.helpers import KEY, LABEL, decisions, in_tick, mcp_session, operator, present, tick_starts, tool_call
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
)

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
    with_unit(canopy_env, conn, KEY, pr="https://git.example.com/acme/repo/-/merge_requests/7")
    conn.execute("UPDATE ticket_units SET ci_cursor = 11")
    assert dispatched(conn, kind="resume", label=LABEL, reasons=["ci"], cursors={"ci": "12"})[0] == "dispatch:resume"


def test_an_unobserved_ticket_keeps_its_claims(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    # No tracker source covers it: the label and the reply stay the overseer's word, as the worker checks again (D051).
    held(canopy_env, conn, KEY, at=ago(hours=1))
    with_unit(canopy_env, conn, KEY, pr=None)
    found = dispatched(conn, kind="resume", label=LABEL, reasons=["reply"], cursors={"comment": "101"})
    assert found[0] == "dispatch:resume"


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


def test_a_ticket_set_on_a_private_or_unobserved_ticket_is_not_refused(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    # No tracker source covers it: its cursor stays the overseer's word, as a dispatch's does.
    held(canopy_env, conn, KEY, at=ago(hours=1))
    with_unit(canopy_env, conn, KEY, pr=None)
    assert ticket_set(conn, {"comment": "999", "ci": "77"}) == []
    # Its start record authorizes a private one, whatever was observed of it (DESIGN §22).
    canopy_env.configure(canopy_env.user_file, TRACKER)
    observe_ticket(conn, at=ago(hours=1))
    assert operator("start", KEY) == 0
    assert ticket_set(conn, {"comment": "999"}) == []


def test_the_operators_ticket_set_is_not_checked(observed: sqlite3.Connection) -> None:
    # Outside a tick it is the operator's, not a claim of the overseer's; with a tracker source, still a number.
    assert operator("ticket", "set", KEY, "--cursor", "comment=999") == 0
    assert present(db.get_ticket(observed, KEY)).comment_cursor == 999
    assert operator("ticket", "set", KEY, "--cursor", "comment=c-999") == 1


def dispatched(
    conn: sqlite3.Connection,
    *,
    kind: str,
    label: str | None = None,
    reasons: Sequence[str] = (),
    cursors: Mapping[str, str] | None = None,
    base: str | None = None,
) -> tuple[str, str]:
    """Dispatch KEY in `repo` through its command, then its tool, each in a dry-run tick of its own.

    Returns:
        The one decision both recorded.
    """
    found = cursors or {}
    command = ["dispatch", KEY, "--repo", "repo", "--kind", kind]
    command += [*(["--label", label] if label else []), *(["--base", base] if base else [])]
    command += [arg for reason in reasons for arg in ("--reason", reason)]
    command += [arg for name, value in found.items() for arg in ("--cursor", f"{name}={value}")]
    with in_tick(conn, dry_run=True) as tick_id:
        main(command)
        by_command = decisions(conn, tick_id)
    arguments: dict[str, object] = {"key": KEY, "kind": kind, "repos": ["repo"], "reasons": list(reasons)}
    arguments |= {"cursors": dict(found)} | ({"label": label} if label else {}) | ({"base": base} if base else {})
    with in_tick(conn, dry_run=True) as tick_id:
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
        said = mcp_session(tool_call("ticket-set", key=KEY, repo="repo", cursors=dict(cursors))).said()
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
