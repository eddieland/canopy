"""Each tick's run of the connectors (DESIGN §30): what each source is asked, what it read whole, and how it failed."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.core import connector_runs, db, observe, records, sql
from canopy.core.vocab import (
    CheckConclusion,
    CheckStatus,
    ConnectorRunStatus,
    MergeState,
    PrState,
    SourceKind,
    TicketState,
)
from canopy.infra import logs
from canopy.loop import connectors, poll
from tests.canopy.helpers import context, reads, waits
from tests.canopy.observation_helpers import artifact_change

if TYPE_CHECKING:
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario

PR = "https://github.com/acme/api/pull/7"
KEYS = ("PROJ-1", "PROJ-2")
#: Both sources the fake connector plays, each under its own name.
SOURCES = {
    "sources": {
        "jira": {"kind": "tracker", "cmd": "connector jira", "timeout_minutes": 1},
        "github": {"kind": "vcs", "cmd": "connector github", "timeout_minutes": 1},
    },
}
#: An artifact store's comment feed, the fake connector playing it as `louvre`.
ARTIFACTS = {"kind": "artifacts", "cmd": "connector louvre", "timeout_minutes": 1}
#: The Slack sink's ticket threads, the fake connector playing their reader as `slack`, one operator listed.
OPERATOR = "U0OPERATOR"
SLACK = {"kind": "slack", "cmd": "connector slack", "timeout_minutes": 1, "operators": [OPERATOR]}


def ticket(key: str, title: str = "Fix the build", **more: object) -> dict[str, object]:
    """A `ticket` line for `key`."""
    return {"kind": "ticket", "key": key, "title": title, "state": "open", **more}


def pr(**more: object) -> dict[str, object]:
    """A `pr` line for PR."""
    return {"kind": "pr", "url": PR, "repository": "acme/api", "number": 7, "head_sha": "abc1234", **more}


def plays(state: Path, **sources: dict[str, Any]) -> None:
    """Have the fake connector answer as each source named is given; a source not named reads everything asked."""
    state.write_text(json.dumps(sources))


def asked(state: Path) -> list[dict[str, Any]]:
    """What the fake connector was asked, each run in order, with the source's name."""
    log = state.parent / "connector.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def runs(scenario: Scenario) -> list[records.ConnectorRun]:
    """Every connector run the journal holds, in order."""
    return records.fetch_all(scenario.conn, records.ConnectorRun, sql.frag("SELECT * FROM connector_runs ORDER BY id"))


def observed_tickets(scenario: Scenario) -> dict[str, records.ObservedTicket]:
    """The observed tickets, by key."""
    found = records.fetch_all(scenario.conn, records.ObservedTicket, sql.frag("SELECT * FROM observed_tickets"))
    return {t.key: t for t in found}


@pytest.fixture
def watched(scenario: Scenario, connector_state: Path) -> Path:
    """Both sources configured, the tickets KEYS seen, and PROJ-1's unit holding PR. Yields the connector's state."""
    scenario.configures("private", connect=SOURCES)
    scenario.configures("private", review={"query": "is:pr review-requested:@me"})
    scenario.seen(*KEYS)
    db.set_unit(scenario.conn, "PROJ-1", str(scenario.env.root), "repo", pr_url=PR)
    return connector_state


def test_a_tick_asks_each_source_its_own_kind_and_records_what_it_read_whole(scenario: Scenario, watched: Path) -> None:
    plays(
        watched,
        jira={
            "lines": [
                ticket("PROJ-1", labels=[{"name": "agent", "added_at": "2026-10-18T09:00:00"}], blockers=["PROJ-9"]),
                {"kind": "comment", "ticket": "PROJ-1", "id": "10001", "author": "acc-1", "time": "2026-10-18T10:00Z"},
                ticket("PROJ-9"),
                pr(),
            ],
            "query": ["PROJ-2", "PROJ-1"],
        },
        github={
            "lines": [
                pr(labels=["agent"], mergeable_state="blocked"),
                {
                    "kind": "check",
                    "pr": PR,
                    "head_sha": "abc1234",
                    "name": "build",
                    "status": "completed",
                    "conclusion": "success",
                    "run_id": 11,
                },
                {"kind": "branch", "repository": "repo", "name": "agent/proj-1", "head_sha": "abc1234"},
                ticket("PROJ-2"),
            ],
        },
    )
    ticked = scenario.tick(*waits(*KEYS))
    assert ticked.tick.status == "ok"

    tracker, vcs = asked(watched)
    assert tracker == {
        "name": "jira",
        "request": {"query": "project = PROJ", "tickets": [{"key": "PROJ-1"}, {"key": "PROJ-2"}]},
    }
    assert vcs["name"] == "github"
    assert vcs["request"]["prs"] == [PR]
    assert [r["name"] for r in vcs["request"]["repositories"]] == ["repo"]
    assert (vcs["request"]["branch_prefix"], vcs["request"]["review_query"]) == ("agent/", "is:pr review-requested:@me")

    jira, github = runs(scenario)
    assert (jira.source, jira.kind, jira.status, jira.tick_id) == ("jira", SourceKind.TRACKER, "ok", ticked.tick.id)
    # A ticket the run did not name whole is not recorded, and a line of a kind the source does not own is skipped.
    assert (json.loads(jira.recorded), json.loads(jira.refused)) == ({"comment": 1, "ticket": 1}, {})
    assert json.loads(jira.query_result or "") == ["PROJ-2", "PROJ-1"]
    assert (github.status, json.loads(github.recorded)) == ("ok", {"branch": 1, "check": 1, "pr": 1})
    assert json.loads(github.review_query_result or "") == []

    [seen] = observed_tickets(scenario).values()
    assert (seen.key, seen.state, json.loads(seen.blockers)) == ("PROJ-1", TicketState.OPEN, ["PROJ-9"])
    assert json.loads(seen.labels) == [{"name": "agent", "added_at": "2026-10-18T09:00:00.000Z"}]
    [observed] = records.fetch_all(scenario.conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs"))
    assert (json.loads(observed.labels), observed.mergeable_state) == (["agent"], MergeState.BLOCKED)
    [check] = records.fetch_all(scenario.conn, records.ObservedCheck, sql.frag("SELECT * FROM observed_checks"))
    assert (check.name, check.status, check.conclusion) == ("build", CheckStatus.COMPLETED, CheckConclusion.SUCCESS)
    [branch] = records.fetch_all(scenario.conn, records.ObservedBranch, sql.frag("SELECT * FROM observed_branches"))
    assert (branch.repository, branch.name) == ("repo", "agent/proj-1")
    [comment] = records.fetch_all(scenario.conn, records.ObservedComment, sql.frag("SELECT * FROM observed_comments"))
    assert (comment.ticket, comment.id, comment.source, comment.body) == ("PROJ-1", "10001", "tracker", "(no text)")
    assert comment.commented_at == "2026-10-18T10:00:00.000Z"
    # The comment reaches its ticket's conversation, as data, and moves no cursor; the overseer's state block shows
    # what the connector read (DESIGN §35).
    assert scenario.conn.execute("SELECT count(*) FROM messages WHERE comment_id = '10001'").fetchone()[0] == 1
    assert scenario.state()["observations"]["query"]["result"] == ["PROJ-2", "PROJ-1"]
    assert "cursors" not in scenario.ticket_state("PROJ-1")  # neither is set, so the block leaves them out
    assert scenario.attention() == []

    # The next run asks only for comments newer than the newest the journal holds.
    scenario.tick(*waits(*KEYS))
    assert asked(watched)[2]["request"]["tickets"][0] == {"key": "PROJ-1", "comments_since": "2026-10-18T10:00:00.000Z"}


def test_a_pr_last_seen_open_is_read_after_its_ticket_is_done_until_a_read_sees_it_merged(
    scenario: Scenario,
    watched: Path,
) -> None:
    plays(watched, github={"lines": [pr(state="open")]})
    scenario.tick(*waits(*KEYS))
    db.set_ticket(scenario.conn, "PROJ-1", str(scenario.env.root), done=True)

    plays(watched, github={"lines": [pr(state="merged")]})
    scenario.tick(*waits("PROJ-2"))
    assert asked(watched)[-1]["request"]["prs"] == [PR]
    [observed] = records.fetch_all(scenario.conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs"))
    assert observed.state is PrState.MERGED

    scenario.tick(*waits("PROJ-2"))
    assert asked(watched)[-1]["request"]["prs"] == []


def test_a_pr_with_an_open_review_request_is_read_so_its_review_knows_its_base(
    scenario: Scenario,
    watched: Path,
) -> None:
    requested = "https://github.com/acme/api/pull/8"
    scenario.operator("start", requested, "--review")
    scenario.tick(*waits(*KEYS))
    assert asked(watched)[-1]["request"]["prs"] == [PR, requested]

    scenario.operator("stop", requested)
    scenario.tick(*waits(*KEYS))
    assert asked(watched)[-1]["request"]["prs"] == [PR]


def test_a_line_out_of_bounds_is_refused_its_subject_kept_and_the_rest_recorded(
    scenario: Scenario,
    watched: Path,
) -> None:
    plays(watched, jira={"lines": [ticket("PROJ-1", title="Before")]})
    scenario.tick(*waits(*KEYS))
    before = observed_tickets(scenario)["PROJ-1"]

    labels = [{"name": f"l{n}"} for n in range(101)]
    long = "word " * 100
    plays(watched, jira={"lines": [ticket("PROJ-1", title="After", labels=labels), ticket("PROJ-2", title=long)]})
    ticked = scenario.tick(*waits(*KEYS))
    assert ticked.tick.status == "ok"

    found = observed_tickets(scenario)
    assert found["PROJ-1"] == before, "a ticket whose line was refused keeps its rows and their age"
    assert len(found["PROJ-2"].title) == 200
    assert found["PROJ-2"].title.endswith("...")
    jira = runs(scenario)[-2]
    assert (jira.status, json.loads(jira.refused)) == (ConnectorRunStatus.PARTIAL, {"ticket": 1})
    assert jira.missed == "did not read 1 ticket (PROJ-1) whole"
    [item] = [i for i in scenario.attention() if i[1] == connector_runs.FAILED_REASON]
    assert item == (None, connector_runs.FAILED_REASON)


def test_a_cut_off_output_keeps_the_previous_observations_and_the_tick_goes_on(
    scenario: Scenario,
    watched: Path,
) -> None:
    plays(watched, github={"lines": [pr(labels=["agent"])]})
    scenario.tick(*waits(*KEYS))
    [first] = records.fetch_all(scenario.conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs"))

    plays(watched, github={"lines": [pr(head_sha="def5678")], "end": None, "stderr": "GitHub went away"})
    ticked = scenario.tick(*waits(*KEYS))
    assert ticked.tick.status == "ok", "a failed source does not fail the tick"
    assert records.fetch_all(scenario.conn, records.ObservedPr, sql.frag("SELECT * FROM observed_prs")) == [first]
    github = runs(scenario)[-1]
    assert (github.status, github.recorded, github.stderr) == ("failed", "{}", "GitHub went away")
    assert github.missed == "it ended without its end line: GitHub went away"
    [failed] = connector_runs.failures(scenario.conn, ticked.tick.id)
    assert failed.detail == "github (vcs) failed: it ended without its end line: GitHub went away"
    assert (None, connector_runs.FAILED_REASON) in scenario.attention()

    # The first run that reads everything clears the item.
    plays(watched)
    scenario.tick(*waits(*KEYS))
    assert scenario.attention() == []


def test_a_source_that_does_not_start_fails_and_the_tick_goes_on(scenario: Scenario, watched: Path) -> None:
    scenario.configures("private", connect={"sources": {"github": {"cmd": "no-such-connector"}}})
    ticked = scenario.tick(*waits(*KEYS))
    assert ticked.tick.status == "ok"
    jira, github = runs(scenario)
    assert (jira.status, github.status) == ("ok", "failed")
    assert (github.missed or "").startswith("it did not start")


def test_output_that_cannot_be_recorded_fails_the_run_keeps_the_old_rows_and_the_tick_goes_on(
    scenario: Scenario,
    watched: Path,
) -> None:
    plays(watched)
    scenario.tick(*waits(*KEYS))
    before = observed_tickets(scenario)

    with mock.patch.object(observe, "_record", autospec=True, side_effect=sqlite3.IntegrityError("CHECK failed")):
        ticked = scenario.tick(*waits(*KEYS))
    assert ticked.tick.status == "ok"
    jira, github = runs(scenario)[-2:]
    assert (jira.status, github.status) == ("failed", "failed")
    assert (jira.missed or "").startswith("its output was not recorded: IntegrityError")
    assert observed_tickets(scenario) == before
    assert (None, connector_runs.FAILED_REASON) in scenario.attention()


def test_status_names_each_source_its_last_run_and_the_age_of_its_observations(
    scenario: Scenario,
    watched: Path,
) -> None:
    assert "jira  tracker  never ran" in scenario.operator("status").out
    plays(watched, jira={"lines": [ticket("PROJ-1")]})
    scenario.tick(*waits(*KEYS))
    out = scenario.operator("status").out
    assert "Connectors (2):" in out
    assert "  jira  tracker  last ran" in out
    assert "  github  vcs  last ran" in out
    # PROJ-2 was named whole with no line of its own, so it is gone from the tracker as far as the run read.
    assert "1 never observed, stale" in out
    scenario.time_passes(minutes=31)
    assert "oldest observation 31m old" in scenario.operator("status").out


def test_the_default_vcs_source_is_canopys_own_reader_and_reads_each_watched_pr(
    scenario: Scenario,
    github_state: Path,
) -> None:
    scenario.seen("PROJ-1")
    db.set_unit(scenario.conn, "PROJ-1", str(scenario.env.root), "repo", pr_url=PR)
    github_state.write_text(json.dumps({"prs": {PR: {"checks": [{"name": "build", "status": "in_progress"}]}}}))
    scenario.tick(*waits("PROJ-1"))
    [run] = runs(scenario)
    assert (run.source, run.status) == ("github", "ok")
    [check] = records.fetch_all(scenario.conn, records.ObservedCheck, sql.frag("SELECT * FROM observed_checks"))
    assert (check.pr_url, check.status, check.head_sha) == (PR, CheckStatus.IN_PROGRESS, "abc1234")


def test_canopys_own_reader_is_asked_the_whole_request_each_tick_with_or_without_a_pr(
    scenario: Scenario,
    github_state: Path,
) -> None:
    scenario.seen("PROJ-1")
    scenario.configures("private", review={"query": "is:pr review-requested:@me"})
    github_state.write_text(json.dumps({"prs": {PR: {}}, "branches": {"repo": {"agent/PROJ-1": "abc1234"}}}))
    ticked = scenario.tick(*waits("PROJ-1"))
    assert ticked.tick.status == "ok"
    [asked] = reads(github_state)
    assert (asked["prs"], [r["name"] for r in asked["repositories"]]) == ([], ["repo"])
    assert (asked["branch_prefix"], asked["review_query"]) == ("agent/", "is:pr review-requested:@me")
    [run] = runs(scenario)
    assert (run.source, run.status) == ("github", "ok")
    [branch] = records.fetch_all(scenario.conn, records.ObservedBranch, sql.frag("SELECT * FROM observed_branches"))
    assert (branch.repository, branch.name) == ("repo", "agent/PROJ-1")

    db.set_unit(scenario.conn, "PROJ-1", str(scenario.env.root), "repo", pr_url=PR)
    scenario.tick(*waits("PROJ-1"))
    assert reads(github_state)[-1]["prs"] == [PR]
    assert [r.status for r in runs(scenario)] == ["ok", "ok"]
    # No source failed. The PR it read is open with no checks and no approval, so it waits on a reviewer (DESIGN §14).
    assert scenario.attention() == [("PROJ-1", "needs_reviewer")]


def test_an_artifacts_source_reads_its_feed_past_its_cursor_last_and_in_shadow(
    scenario: Scenario,
    watched: Path,
) -> None:
    scenario.configures("private", connect={"sources": {"louvre": ARTIFACTS}})
    plays(watched, louvre={"lines": [artifact_change(1, body="Why shard it?"), artifact_change(2)]})
    ticked = scenario.tick(*waits(*KEYS))
    assert ticked.tick.status == "ok"

    assert [r["name"] for r in asked(watched)] == ["jira", "github", "louvre"]
    assert asked(watched)[-1]["request"] == {"since": 0}
    louvre = runs(scenario)[-1]
    assert (louvre.source, louvre.kind, louvre.status, louvre.tick_id) == (
        "louvre",
        SourceKind.ARTIFACTS,
        ConnectorRunStatus.OK,
        ticked.tick.id,
    )
    assert json.loads(louvre.recorded) == {"comment_created": 2}
    found = records.fetch_all(
        scenario.conn,
        records.ObservedArtifactComment,
        sql.select("*").from_("observed_artifact_comments").order_by("seq"),
    )
    assert [c.body for c in found] == ["Why shard it?", "Comment 2."]
    # Each reaches its ticket's conversation, quoting its passage. By an author the operator does not list, it is data
    # the overseer is not shown, and waits on the operator as an attention item (DESIGN §38).
    assert "Why shard it?" not in json.dumps(scenario.state())
    said = scenario.conn.execute("SELECT subject_id, source, channel, body FROM messages WHERE body LIKE '%shard%'")
    assert [tuple(r) for r in said] == [
        (KEYS[0], "artifact", "artifacts", "> shard it\n\nWhy shard it?"),
        (KEYS[0], "artifact", "artifacts", "> shard it\n\nComment 2."),
    ]
    assert scenario.attention() == [(KEYS[0], "untrusted_artifact_comment")]

    scenario.tick(*waits(*KEYS))
    assert asked(watched)[-1]["request"] == {"since": 2}
    out = scenario.operator("status").out
    assert "Connectors (3):" in out
    assert "  louvre  artifacts  last ran" in out
    assert "feed through change 2, read to its end" in out


def test_an_artifacts_source_read_short_raises_connector_failed_and_reads_the_change_again(
    scenario: Scenario,
    watched: Path,
) -> None:
    # Comments by an author the operator lists, so the source's own item is the only one.
    listed = {"authorized_authors": ["u_ana"]}
    scenario.configures("private", connect={"sources": {"louvre": ARTIFACTS}}, artifacts=listed)
    plays(watched, louvre={"lines": [artifact_change(1), {"kind": "comment_created", "seq": 2}, artifact_change(3)]})
    ticked = scenario.tick(*waits(*KEYS))
    assert ticked.tick.status == "ok", "a source read short does not fail the tick"
    [failed] = connector_runs.failures(scenario.conn, ticked.tick.id)
    assert failed.detail == (
        "louvre (artifacts) partial: did not read the feed past change 1: the line after it was refused"
    )
    assert (None, connector_runs.FAILED_REASON) in scenario.attention()
    assert "feed through change 1, never read to its end, stale" in scenario.operator("status").out

    plays(watched, louvre={"lines": [artifact_change(2), artifact_change(3)]})
    scenario.tick(*waits(*KEYS))
    assert asked(watched)[-1]["request"] == {"since": 1}
    assert scenario.attention() == []


def slack_reply(ts: str, body: str, *, user: str = OPERATOR) -> dict[str, object]:
    """A `reply` line on PROJ-1, as `canopy-connect-slack` prints one."""
    return {"kind": "reply", "ticket": "PROJ-1", "thread": "1790.000001", "ts": ts, "user": user, "body": body}


def operator_replies(scenario: Scenario) -> list[tuple[str, str]]:
    """Each operator message to PROJ-1, as its channel and body, oldest first."""
    query = "SELECT channel, body FROM messages WHERE source = 'operator' AND subject_id = 'PROJ-1' ORDER BY id"
    return [(str(r[0]), str(r[1])) for r in scenario.conn.execute(query)]


def test_a_slack_source_records_a_listed_operators_reply_in_a_live_tick_and_a_poll(
    scenario: Scenario,
    watched: Path,
) -> None:
    scenario.configures("private", connect={"sources": {"slack": SLACK}})
    first = {"lines": [slack_reply("1790.000005", "Use the staging config.")], "end": {"tickets": ["PROJ-1"]}}
    plays(watched, slack=first)
    # A dry tick runs the source, and records no message (D036).
    assert scenario.tick(*waits(*KEYS), dry_run=True).tick.status == "ok"
    assert operator_replies(scenario) == []
    ticked = scenario.tick(*waits(*KEYS))
    assert [r["name"] for r in asked(watched)][-1] == "slack"
    # Asked for the operator's replies alone: nobody else's words reach canopy.
    assert asked(watched)[-1]["request"] == {"repo": str(scenario.env.root), "operators": [OPERATOR]}
    slack = runs(scenario)[-1]
    assert (slack.source, slack.kind, slack.status, slack.tick_id) == (
        "slack",
        SourceKind.SLACK,
        ConnectorRunStatus.OK,
        ticked.tick.id,
    )
    assert json.loads(slack.recorded) == {"reply": 1}
    assert operator_replies(scenario) == [("slack", "Use the staging config.")]
    assert "  slack  slack  last ran" in scenario.operator("status").out

    # Between ticks, the loop's poll reads it too: a reply it records is an operator message, which ends the wait (§6).
    later = [slack_reply("1790.000005", "Use the staging config."), slack_reply("1790.000009", "And add a test.")]
    plays(watched, slack={"lines": later, "end": {"tickets": ["PROJ-1"]}})
    polled = poll.run(context(scenario.env), logs.for_tick(None))
    assert polled is not None
    assert polled["slack"].recorded == {"already": 1, "reply": 1}
    assert operator_replies(scenario)[-1] == ("slack", "And add a test.")


def test_a_slack_source_read_short_raises_connector_failed(scenario: Scenario, watched: Path) -> None:
    scenario.configures("private", connect={"sources": {"slack": SLACK}})
    plays(watched, slack={"end": {"tickets": ["PROJ-1"], "unread": ["PROJ-2"]}})
    ticked = scenario.tick(*waits(*KEYS))
    [failed] = connector_runs.failures(scenario.conn, ticked.tick.id)
    assert failed.detail == "slack (slack) partial: did not read the Slack threads of PROJ-2"
    assert (None, connector_runs.FAILED_REASON) in scenario.attention()


def test_a_clone_url_reaches_a_connector_without_its_credentials() -> None:
    assert connectors.without_credentials("https://me:tok@github.com/acme/api.git") == "https://github.com/acme/api.git"
    assert connectors.without_credentials("git@github.com:acme/api.git") == "git@github.com:acme/api.git"
