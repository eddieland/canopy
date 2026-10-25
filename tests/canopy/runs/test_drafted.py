"""Reading the threads a run's drafts answer (DESIGN §29): after the run, and each tick until a read is whole."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.core import drafts, observe, records, replies, review_diff, sql
from canopy.core.config import load
from canopy.core.vocab import DraftKind, DraftStatus, ResumeReason, ReviewItem, RunKind
from canopy.infra import logs, procs
from canopy.loop import attention
from canopy.runs import drafted
from tests.canopy.helpers import (
    APPROVE,
    DRAFTS_PR,
    KEY,
    all_drafts,
    comment,
    context,
    github_has,
    present,
    reads,
    thread,
    tick_reads,
    waits,
)
from tests.canopy.scenario_helpers import dispatches, sends_drafts

if TYPE_CHECKING:
    from canopy.core.context import Context
    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv

PR = DRAFTS_PR
#: KEY's run on its `work` branch, as each drafting run here is.
WORK = dispatches(slug="work")
#: A resume of KEY for a conflict on its PR: a reason no observation has to authorize, which the drafts do not need.
RESUME = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CONFLICT])


@pytest.mark.usefixtures("git_pool")
def test_after_a_run_its_pr_is_read_and_its_drafts_checked(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    github_has(github_state, comment(501), comment(502, "PRRT_2"))
    run = scenario.run(
        WORK,
        worker=sends_drafts([thread(501), thread(999), {"on": "pr", "pr": PR, "text": "Fixed CI."}]),
    )
    reply, unknown, body = all_drafts(conn)
    assert (reply.status, reply.thread_id) == (DraftStatus.WAITING, "PRRT_1")
    assert reply.checked_at is not None
    assert (unknown.status, unknown.why) == (DraftStatus.REFUSED, f"unknown_thread: {PR} has no review comment 999")
    assert (body.status, body.thread_id) == (DraftStatus.WAITING, None)
    found = present(replies.run_replies(conn, run.id))
    assert [(r.number, r.why) for r in drafts.refused_of(found)] == [(2, unknown.why)]
    assert reads(github_state) == [{"prs": [PR]}]
    observed = records.fetch_all(conn, records.ObservedReview, sql.frag("SELECT * FROM observed_reviews ORDER BY id"))
    assert [(o.item, o.id, o.thread_id, o.author) for o in observed] == [
        (ReviewItem.COMMENT, 501, "PRRT_1", "alice"),
        (ReviewItem.COMMENT, 502, "PRRT_2", "alice"),
    ]


@pytest.mark.usefixtures("git_pool")
def test_a_failed_read_keeps_the_drafts_unchecked_until_a_tick_reads_the_pr_whole(
    scenario: Scenario,
    github_state: Path,
    ctx: Context,
) -> None:
    conn = scenario.conn
    scenario.configures("private", trust=APPROVE)
    github_has(github_state, comment(501), down=True)
    scenario.run(WORK, worker=sends_drafts([thread(501)]))
    [draft] = all_drafts(conn)
    assert draft.status is DraftStatus.UNCHECKED
    [item] = drafted.waiting(conn)
    assert (item.ticket_key, item.repo) == (KEY, "repo")
    assert (
        item.detail
        == f"1 draft waits on you, for {PR}; its threads could not be read yet, so 1 cannot be sent until they are"
    )
    assert drafts.unchecked_prs(conn) == [PR]

    github_has(github_state, comment(501), unread=[PR])
    tick_reads(ctx)
    assert present(drafts.get(conn, draft.id)).status is DraftStatus.UNCHECKED

    github_has(github_state, comment(501))
    tick_reads(ctx)
    assert present(drafts.get(conn, draft.id)).status is DraftStatus.WAITING
    assert drafted.waiting(conn)[0].detail == f"1 draft waits on you, for {PR}"
    assert [r["prs"] for r in reads(github_state)] == [[PR], [PR], [PR]]
    tick_reads(ctx)
    # The PR is still read each tick, as its unit's (DESIGN §30), and a checked draft stays checked.
    assert present(drafts.get(conn, draft.id)).status is DraftStatus.WAITING


@pytest.mark.usefixtures("git_pool")
def test_a_stop_cuts_the_read_after_a_run_short(scenario: Scenario, github_state: Path, tmp_path: Path) -> None:
    scenario.configures("private", trust=APPROVE)
    reading = tmp_path / "reading"
    github_has(github_state, comment(501), hang=str(reading))
    stopper = threading.Thread(target=stop_once_there, args=(reading,), daemon=True)
    stopper.start()
    started = time.monotonic()
    run = scenario.run(WORK, worker=sends_drafts([thread(501)]))
    stopper.join()
    assert time.monotonic() - started < 50, "the read was not cut short"
    assert run.status == "done"
    [draft] = all_drafts(scenario.conn)
    assert draft.status is DraftStatus.UNCHECKED
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


def stop_once_there(path: Path) -> None:
    """Send this process SIGTERM once `path` exists, as `canopy stop` would a run, or give up after 30 seconds."""
    deadline = time.monotonic() + 30
    while not path.exists():
        if time.monotonic() > deadline:
            return
        time.sleep(0.05)
    os.kill(os.getpid(), signal.SIGTERM)


@pytest.mark.usefixtures("git_pool")
def test_a_later_runs_draft_supersedes_an_unsent_one_for_the_same_thread(
    scenario: Scenario,
    github_state: Path,
) -> None:
    scenario.configures("private", trust=APPROVE)
    github_has(github_state, comment(501), comment(503, "PRRT_1", "bob"), comment(502, "PRRT_2"))
    scenario.run(WORK, worker=sends_drafts([thread(501), thread(502), {"on": "pr", "pr": PR, "text": "One."}]))
    again = [thread(503, text="Renamed, again."), {"on": "pr", "pr": PR, "text": "Two."}]
    later = scenario.run(RESUME, worker=sends_drafts(again))
    old_reply, untouched, old_body, reply, body = all_drafts(scenario.conn)
    assert (old_reply.status, old_reply.superseded_by) == (DraftStatus.SUPERSEDED, reply.id)
    assert old_reply.why == f"superseded by run {later.id}'s draft 1"
    assert untouched.status is DraftStatus.WAITING
    assert (old_body.status, old_body.superseded_by) == (DraftStatus.SUPERSEDED, body.id)
    assert (reply.status, body.status) == (DraftStatus.WAITING, DraftStatus.WAITING)


@pytest.mark.usefixtures("git_pool")
def test_a_run_drafts_once_for_a_thread(scenario: Scenario, github_state: Path) -> None:
    scenario.configures("private", trust=APPROVE)
    github_has(github_state, comment(501), comment(503, "PRRT_1", "bob"))
    scenario.run(WORK, worker=sends_drafts([thread(501), thread(503)]))
    first, second = all_drafts(scenario.conn)
    assert first.status is DraftStatus.WAITING
    assert (second.status, second.why) == (
        DraftStatus.REFUSED,
        "a second draft for the thread draft 1 answers; a thread takes one",
    )


@pytest.mark.usefixtures("git_pool")
def test_a_ticket_draft_supersedes_the_ticket_draft_before_it(scenario: Scenario, github_state: Path) -> None:
    conn = scenario.conn
    issues = {"kind": "tracker", "post_cmd": "canopy-post-github"}
    scenario.configures("private", trust=APPROVE, connect={"sources": {"issues": issues}})
    github_has(github_state)
    ticket = {"on": "ticket", "url": "https://github.com/acme/api/issues/1", "text": "Which base?"}
    scenario.run(WORK, worker=sends_drafts([ticket]))
    scenario.polls()
    scenario.run(RESUME, worker=sends_drafts([{**ticket, "text": "Which base, main or next?"}]))
    old, new = all_drafts(conn)
    assert (old.kind, old.status, old.superseded_by) == (DraftKind.TICKET, DraftStatus.SUPERSEDED, new.id)
    assert new.status is DraftStatus.WAITING
    [item] = drafted.waiting(conn)
    assert (item.ticket_key, item.repo, item.detail) == (KEY, None, "1 draft waits on you, for the ticket")


@pytest.mark.usefixtures("git_pool")
def test_drafts_on_a_merged_pr_wait_on_nobody(scenario: Scenario, github_state: Path) -> None:
    conn, env = scenario.conn, scenario.env
    scenario.configures("private", trust=APPROVE)
    github_has(github_state, comment(501))
    scenario.run(WORK, worker=sends_drafts([thread(501)]))
    assert len(drafted.waiting(conn)) == 1
    state = json.loads(github_state.read_text())
    state["prs"][PR]["pr"] = {"state": "merged"}
    github_state.write_text(json.dumps(state))
    found = observe.read(conn, load(env.root, env.user_file), procs.SubprocessRunner(), [PR], logs.for_tick(None))
    assert found.whole == {PR}
    assert drafted.waiting(conn) == []


@pytest.mark.usefixtures("git_pool")
def test_waiting_drafts_are_the_operators_item_alone(scenario: Scenario, github_state: Path) -> None:
    # The reviewer is trusted, so the comment raises no `untrusted_review` of the harness's (DESIGN §14).
    scenario.configures("private", trust={**APPROVE, "trusted_reviewers": ["alice"]})
    github_has(github_state, comment(501))
    scenario.run(WORK, worker=sends_drafts([thread(501)]))
    scenario.tick(*waits(KEY, rationale="waiting on review"))
    assert [(i.ticket_key, i.reason, i.repo) for i in attention.current(scenario.conn)] == [
        (KEY, "drafts_waiting", "repo"),
    ]
    assert "drafts_waiting" not in str(scenario.state())
    assert attention.for_overseer(scenario.conn) == []


@pytest.mark.usefixtures("git_pool")
def test_dropping_drafts_takes_them_off_the_attention_list_without_a_tick(
    scenario: Scenario,
    github_state: Path,
) -> None:
    scenario.configures("private", trust={**APPROVE, "trusted_reviewers": ["alice"]})
    github_has(github_state, comment(501), comment(502, "PRRT_2"))
    run = scenario.run(WORK, worker=sends_drafts([thread(501), thread(502)]))
    scenario.tick(*waits(KEY))
    page = scenario.env.state_dir / attention.FILE_NAME
    ctx = context(scenario.env)
    [item] = [i for i in attention.listed(ctx) if i.reason == drafted.WAITING_REASON]
    assert item.detail == f"2 drafts wait on you, for {PR}"
    scenario.operator("draft", "drop", f"run:{run.id}", "1")
    [item] = [i for i in attention.listed(ctx) if i.reason == drafted.WAITING_REASON]
    assert item.detail == f"1 draft waits on you, for {PR}"
    assert "1 draft waits on you" in page.read_text()
    scenario.operator("draft", "drop", f"run:{run.id}", "2")
    assert [i for i in attention.listed(ctx) if i.reason == drafted.WAITING_REASON] == []
    assert drafted.WAITING_REASON not in page.read_text()
    assert "\nAttention (0):" in scenario.operator("status").out


def test_a_read_records_only_what_it_read_whole_and_a_line_it_cannot_use_leaves_its_pr_unread(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    other = "https://github.com/acme/api/pull/8"
    third = "https://github.com/acme/api/pull/9"
    lines = [
        {"kind": "pr", "url": PR, "repository": "acme/api", "number": 7, "state": "open"},
        {"kind": "review", "pr": PR, **comment(501)},
        {"kind": "ticket", "key": "PROJ-1", "title": "a tracker's line, which a vcs source does not own"},
        {"kind": "review", "pr": other, **comment(601)},
        {"kind": "review", "pr": other, "item": "comment", "id": 602, "body": "no thread"},
        {"kind": "review", "pr": third, **comment(701)},
        {"kind": "end", "prs": [PR, other]},
    ]
    reader = tmp_path / "reader"
    reader.write_text(
        "#!/bin/sh\ncat >/dev/null\ncat <<'EOF'\n" + "\n".join(map(json.dumps, lines)) + "\nnot json\nEOF\n",
    )
    reader.chmod(0o755)
    canopy_env.write_private(f'[connect.sources.github]\nkind = "vcs"\ncmd = "{reader}"\n')
    found = observe.read(
        conn,
        load(canopy_env.root, canopy_env.user_file),
        procs.SubprocessRunner(),
        [PR, other, third],
        logs.for_tick(None),
    )
    # `other` has a line canopy refused, so it is not whole; `third` is not named whole.
    assert found.whole == {PR}
    assert found.failure == "the reader did not read it whole"
    observed = records.fetch_all(conn, records.ObservedReview, sql.frag("SELECT * FROM observed_reviews"))
    assert [(o.pr_url, o.id) for o in observed] == [(PR, 501)]
    [pr] = records.fetch_all(conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs"))
    assert (pr.url, pr.number, pr.draft) == (PR, 7, False)


@pytest.mark.usefixtures("git_pool")
def test_a_run_under_approve_keeps_its_diff_at_its_pushed_head(scenario: Scenario, github_state: Path) -> None:
    scenario.configures("private", trust=APPROVE)
    github_has(github_state, comment(501))
    run = scenario.run(WORK, worker=sends_drafts([thread(501)]))
    diff = review_diff.run_path_for(str(run.row["log_path"]), "repo")
    assert diff.is_file()
    assert review_diff.read(diff) is not None
    head = review_diff.read_head(diff)
    assert head is not None
    assert len(head) == 40


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize("write", ["keep_head", "keep"])
def test_a_diff_that_cannot_be_kept_leaves_the_run_and_its_drafts_as_they_are(
    scenario: Scenario,
    github_state: Path,
    write: str,
) -> None:
    scenario.configures("private", trust=APPROVE)
    github_has(github_state, comment(501))
    with mock.patch.object(review_diff, write, autospec=True, side_effect=OSError("No space left on device")):
        run = scenario.run(WORK, worker=sends_drafts([thread(501)]))
    assert run.status == "done"
    [draft] = drafts.of_run(scenario.conn, run.id)
    assert draft.status is DraftStatus.WAITING
    assert not review_diff.run_path_for(str(run.row["log_path"]), "repo").exists()


@pytest.mark.usefixtures("git_pool")
def test_a_run_under_post_keeps_no_diff(scenario: Scenario) -> None:
    scenario.configures("private", trust={"review_replies": "post"})
    run = scenario.run(WORK, worker=sends_drafts([]))
    assert not review_diff.run_path_for(str(run.row["log_path"]), "repo").exists()
