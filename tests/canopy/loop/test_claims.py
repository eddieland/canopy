"""A dispatch's claims checked in code against the connectors' observations (DESIGN §35, ROADMAP M37).

Each case writes what the connectors observed by hand, at the real time, since a dispatch reads them at it, and
dispatches through the `canopy dispatch` command and the `dispatch` tool, each in a dry-run tick of its own: both must
record the same decision, a refusal or the run the dispatch would have started.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db
from canopy.loop import observations
from tests.canopy.helpers import KEY, LABEL, decisions, in_tick, mcp_session, operator, tool_call
from tests.canopy.observation_helpers import (
    PR,
    TRACKER,
    TRUST,
    branches_read,
    check,
    comment,
    held,
    observe_pr,
    observe_ticket,
    review,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    from tests.conftest import CanopyEnv

BRANCH = f"agent/{KEY}-work"
#: When the comments and review items here were written: long before the observations, which are the real time's.
EARLIER = "2026-10-01T10:00:00Z"
LATER = "2026-10-01T11:00:00Z"


@pytest.fixture
def observed(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> sqlite3.Connection:
    """KEY observed fresh, labeled, with a branch and its PR in `repo`, held since before it was read. Returns the
    journal."""
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
    comment(observed, "101", author, EARLIER, "Go ahead.", source=source)
    found = dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors={"comment": "101"})
    assert found[0] == action


def test_a_resume_for_reply_may_rest_on_an_operator_message_instead(observed: sqlite3.Connection) -> None:
    comment(observed, "101", "acc-9", EARLIER, "Go ahead.")
    reply = {"comment": "101"}
    assert dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors=reply)[0] == (
        "refused:unauthorized"
    )
    assert operator("reply", KEY, "Do what acc-9 asks.") == 0
    [message] = conversation.operator_messages_after(observed, KEY, 0)
    cursors = {**reply, "message": str(message.id)}
    assert dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors=cursors)[0] == "dispatch:resume"


def test_a_resume_for_review_covers_a_trusted_reviewers_item(observed: sqlite3.Connection) -> None:
    review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    found = dispatched(observed, kind="resume", label=LABEL, reasons=["review"], cursors={"review": EARLIER})
    assert found[0] == "dispatch:resume"


def test_untrusted_review_items_need_an_operator_message_after_them(observed: sqlite3.Connection) -> None:
    review(observed, 1, "octocat", "changes_requested", EARLIER, "Rename the helper.")
    review(observed, 2, "stranger", None, LATER, "Why not a map?", item="comment")
    covered = {"review": LATER}
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


@pytest.mark.parametrize(
    ("cursors", "reasons", "why"),
    [
        pytest.param({"comment": "999"}, ["reply"], "comment cursor 999 names no comment observed", id="a-comment"),
        pytest.param(
            {"review": LATER},
            ["review"],
            f"review cursor {LATER} is the time of no review item",
            id="a-time",
        ),
        pytest.param({"ci": "77"}, ["ci"], f"ci cursor 77 names no check run observed at the head of {PR}", id="ci"),
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
    count = observations.MAX_NEW_ITEMS + 1
    for n in range(count):
        comment(observed, f"{200 + n}", "acc-1", f"2026-10-01T10:{n:02}:00Z", f"Comment {n}.")
    shown = {"comment": str(200 + count - 2)}
    assert dispatched(observed, kind="resume", label=LABEL, reasons=["reply"], cursors=shown)[0] == "dispatch:resume"
    action, reason = dispatched(
        observed,
        kind="resume",
        label=LABEL,
        reasons=["reply"],
        cursors={"comment": str(200 + count - 1)},
    )
    assert action == "refused:unobserved"
    assert "passes comments on PROJ-1 the state block left out" in reason


def test_a_private_ticket_is_not_refused(observed: sqlite3.Connection) -> None:
    # Its start record authorizes it, whatever was observed of it, stale included (DESIGN §22).
    assert operator("start", KEY) == 0
    observed.execute("UPDATE observed_tickets SET observed_at = ?, labels = '[]'", (ago(hours=1),))
    assert dispatched(observed, kind="resume", reasons=["reply"])[0] == "dispatch:resume"


def test_an_unobserved_ticket_keeps_its_claims(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    # No tracker source covers it: the label and the reply stay the overseer's word, as the worker checks again (D051).
    held(canopy_env, conn, KEY, at=ago(hours=1))
    with_unit(canopy_env, conn, KEY, pr=None)
    found = dispatched(conn, kind="resume", label=LABEL, reasons=["reply"], cursors={"comment": "101"})
    assert found[0] == "dispatch:resume"


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
