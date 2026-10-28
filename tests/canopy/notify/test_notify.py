"""Notification sinks (DESIGN §20, ROADMAP M10): per-sink delivery of the attention diff, events, and digests."""

import dataclasses
import functools
import json
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db, outbox, runtime_sessions, spend
from canopy.core.config import ConfigError, load
from canopy.core.items import Item, fingerprint
from canopy.notify import journal as notify_journal
from canopy.notify import message
from canopy.runtime.report import SessionPage, SessionSpend
from tests.canopy.helpers import (
    InlineRunner,
    canopy,
    chore_reports,
    in_tick,
    messages,
    tick_starts,
    waits,
    with_events,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, asks, dispatches, raises
from tests.conftest import CanopyEnv, GitPool

#: The line an overseer that gave up ends on, in place of the one that ends a tick.
GAVE_UP = "gave up"


def add_sink(scenario: Scenario, script: Path, name: str, out: Path, **settings: object) -> None:
    """Configure the sink `name`, with `settings`: `script` appends to `out`, failing with the number in `out`.exit."""
    scenario.configures(notify={"sinks": {name: {"cmd": f"{script} {out} {out}.exit", **settings}}})


def json_messages(out: Path) -> list[dict[str, Any]]:
    return [json.loads(m) for m in messages(out)]


def needing_reviewers(*keys: str) -> list[list[str]]:
    """The overseer raises each of `keys` on the attention list as needing a reviewer."""
    return [raises(key, "needs_author") for key in keys]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("[notify]\ncmd = 'x'\n[notify.sinks.default]\ncmd = 'y'\n", "set notify.cmd or \\[notify.sinks.default\\]"),
        ("[notify.sinks.slack]\ncmd = 'post {prompt}'\n", r"must not contain \{prompt\}"),
        ("[notify.sinks.slack]\ncmd = ''\n", "must not be empty"),
        ("[notify.sinks.slack]\ncmd = 'x'\nevents = ['everything']\n", "events"),
        ("[notify.sinks.slack]\ncmd = 'x'\ndigest_every_minutes = 30\n", "greater than or equal to 60"),
        ("[notify.sinks.slack]\ncmd = 'x'\ndigest_min_usd = 5\n", "digest_min_usd needs digest_every_minutes"),
        ("[notify.sinks.slack]\ncmd = 'x'\ndigest_every_minutes = 60\ndigest_min_usd = 0\n", "greater than 0"),
        ("[notify.sinks.slack]\ncmd = 'x'\nbatch_minutes = 0\n", "greater than or equal to 1"),
        ("[notify.sinks.slack]\ncmd = 'x'\nbatch_minutes = 1441\n", "less than or equal to 1440"),
        ("[notify.sinks.Slack]\ncmd = 'x'\n", "sink name 'Slack'"),
        ("".join(f"[notify.sinks.s{i}]\ncmd = 'x'\n" for i in range(6)), "at most 5 sinks"),
    ],
)
def test_sink_config_is_checked(canopy_env: CanopyEnv, extra: str, message: str) -> None:
    canopy_env.append_user("\n" + extra)
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.root, canopy_env.user_file)


def test_notify_cmd_is_the_default_sink(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user("\n[notify]\ncmd = 'notify-me'\n[notify.sinks.b]\ncmd = 'b'\n")
    sinks = load(canopy_env.root, canopy_env.user_file).notify.all_sinks()
    assert list(sinks) == ["b", "default"]
    assert (sinks["default"].cmd, sinks["default"].format, sinks["default"].events) == (
        "notify-me",
        "text",
        ("attention",),
    )
    assert (sinks["b"].format, sinks["b"].events, sinks["b"].digest_every_minutes) == (
        "json",
        ("attention", "loop"),
        None,
    )


def test_a_repository_cannot_add_a_sink(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared("\n[notify.sinks.x]\ncmd = 'curl evil'\n")
    with pytest.raises(ConfigError, match=r"notify\.sinks is private"):
        load(canopy_env.root, canopy_env.user_file)


def test_notify_cmd_is_the_sink_named_default(scenario: Scenario, sink_script: Path, tmp_path: Path) -> None:
    """`notify.cmd` is the sink `default`: what was notified as `default` is not notified again."""
    conn = scenario.conn
    conn.execute(
        "INSERT INTO notifications (sink, fingerprint, ticket_key, reason, repo, sent_at) "
        "VALUES ('default', ?, 'PROJ-3', 'needs_author', NULL, 'x')",
        (fingerprint("PROJ-3", "needs_author"),),
    )
    out = tmp_path / "notified.txt"
    scenario.configures(notify={"cmd": f"{sink_script} {out}"})
    scenario.tick(*needing_reviewers("PROJ-3"))
    assert messages(out) == []
    rows = [tuple(r) for r in conn.execute("SELECT sink, ticket_key, reason FROM notifications")]
    assert rows == [("default", "PROJ-3", "needs_author")]

    # Renamed to a sink of its own, it is new there and hears about every open item once.
    scenario.configures(notify={"cmd": None, "sinks": {"mine": {"format": "text", "cmd": f"{sink_script} {out}"}}})
    scenario.tick(*needing_reviewers("PROJ-3"))
    [message] = messages(out)
    assert "+ PROJ-3 needs_author: PROJ-3 detail\n" in message
    assert [tuple(r) for r in conn.execute("SELECT sink FROM notifications")] == [("mine",)]


def test_a_json_sink_hears_about_runs(scenario: Scenario, git_pool: GitPool, sink_script: Path, tmp_path: Path) -> None:
    out = tmp_path / "slack.txt"
    add_sink(scenario, sink_script, "slack", out, events=["attention", "loop", "runs"])
    scenario.tick()  # the sink's first publish: from here on it hears every event
    question = "Should the retry be per request or per session?\nThe ticket says both."
    blocked = json.dumps({"status": "blocked", "branch": "agent/PROJ-1-work", "summary": "x", "question": question})
    titled("PROJ-1", "Retry failed checkouts", scenario)
    scenario.run(worker=worker_does(result=blocked))
    scenario.tick(*needing_reviewers("PROJ-9"), *waits("PROJ-1"))

    [message] = json_messages(out)
    assert message["version"] == 1
    assert message["sink"] == "slack"
    assert message["repo"] == str(scenario.env.root)
    assert message["attention"]["added"] == [
        {
            "ticket": "PROJ-9",
            "title": None,  # not named yet
            "repo": None,
            "reason": "needs_author",
            "detail": "PROJ-9 detail",
            "since": message["attention"]["added"][0]["since"],
            "ui": None,  # a tick run by hand serves no web UI to link to
        },
    ]
    assert message["attention"]["open"] == 1
    started, ended = message["events"]
    assert started["kind"] == "run.started"
    assert (started["ticket"], started["run"], started["run_kind"], started["attempt"], started["limit"]) == (
        "PROJ-1",
        1,
        "implement",
        1,
        2,
    )
    assert started["title"] == ended["title"] == "Retry failed checkouts"
    assert ended["kind"] == "run.ended"
    assert (ended["status"], ended["question"]) == ("blocked", " ".join(question.split()))
    assert ended["line"].startswith("< PROJ-1 run 1 implement ended blocked: x question: Should the retry")
    assert message["omitted"] == 0
    assert message["digest"] is None
    assert message["text"].startswith("canopy attention: 1 new, 0 resolved\n+ PROJ-9 needs_author: PROJ-9 detail\n> ")

    # Delivered events are not sent again.
    scenario.tick(*needing_reviewers("PROJ-9"), *waits("PROJ-1"))
    assert len(messages(out)) == 1


def titled(key: str, title: str, scenario: Scenario) -> None:
    """Record `key`'s title, as an overseer does once it has read the ticket, in a tick of its own."""
    scenario.overseer("ticket", "set", key, "--title", title)


def test_without_sinks_no_event_is_recorded(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=worker_does())
    assert scenario.conn.execute("SELECT count(*) FROM notify_events").fetchone()[0] == 0


def test_a_failing_sink_does_not_hold_back_another_and_catches_up(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    """M10's acceptance against the fakes: one sink down for several ticks, the other reports it, then it catches up."""
    slack, desk = tmp_path / "slack.txt", tmp_path / "desk.txt"
    add_sink(scenario, sink_script, "desk", desk, format="text")
    add_sink(scenario, sink_script, "slack", slack)
    (Path(f"{slack}.exit")).write_text("1")
    for i in range(1, 5):
        scenario.tick(*needing_reviewers(*(f"PROJ-{n}" for n in range(1, i + 1))))
    # Every delivery to slack failed, so it was told nothing; desk heard each change and, once, that slack is failing.
    conn = scenario.conn
    assert conn.execute("SELECT count(*) FROM notifications WHERE sink = 'slack'").fetchone()[0] == 0
    desk_messages = messages(desk)
    assert len(desk_messages) == 4
    failing = [m for m in desk_messages if "! sink slack has failed 3 deliveries in a row" in m]
    assert len(failing) == 1
    assert "exited 1: sink down" in failing[0]
    status = scenario.operator("status").out
    assert "  slack  never delivered; 1 events waiting; 4 failed in a row: exited 1: sink down\n" in status
    assert "  desk  last delivered " in status

    # Back up: one message with the net change, all four items.
    Path(f"{slack}.exit").unlink()
    scenario.tick(*needing_reviewers(*(f"PROJ-{n}" for n in range(1, 5))))  # as the last tick left them
    *_, caught_up = json_messages(slack)
    assert [a["ticket"] for a in caught_up["attention"]["added"]] == ["PROJ-1", "PROJ-2", "PROJ-3", "PROJ-4"]
    # It takes `loop`, so it hears that it was failing.
    assert [e["kind"] for e in caught_up["events"]] == ["loop.sink_failing"]
    row = conn.execute("SELECT failures, last_error FROM notify_sinks WHERE name = 'slack'").fetchone()
    assert tuple(row) == (0, None)


def test_loop_failing_and_recovered_are_sent_once_each(scenario: Scenario, sink_script: Path, tmp_path: Path) -> None:
    out = tmp_path / "phone.txt"
    add_sink(scenario, sink_script, "phone", out, format="text", events=["loop"])
    for _ in range(5):
        scenario.tick(result=GAVE_UP, code=1)
    [failing] = messages(out)
    assert failing.startswith("canopy: 1 event\n! loop failing: 3 ticks in a row ended other than ok; latest tick 3 ")
    scenario.tick()
    scenario.tick()
    listing = f"Full list: {scenario.env.state_dir / 'attention.md'}\n"
    assert messages(out)[1] == f"canopy: 1 event\n! loop recovered after 5 failed ticks\n{listing}"
    assert len(messages(out)) == 2


def test_a_long_failing_streak_is_one_streak(scenario: Scenario, sink_script: Path, tmp_path: Path) -> None:
    """Pruning keeps the streak's `loop.failing`, and the recovery counts every failed tick, however many."""
    out = tmp_path / "phone.txt"
    add_sink(scenario, sink_script, "phone", out, format="text", events=["loop"])
    for _ in range(3):
        scenario.tick(result=GAVE_UP, code=1)
    assert len(messages(out)) == 1
    conn = scenario.conn
    # The events alone age past pruning, not the ticks of the streak. An event's time is its `at`.
    conn.execute("UPDATE notify_events SET at = ?", (db.format_time(datetime.now(UTC) - timedelta(days=8)),))
    conn.executemany(
        "INSERT INTO ticks (started_at, ended_at, status) VALUES (?, ?, 'overseer_failed')",
        [(db.now(), db.now())] * 1100,
    )
    scenario.tick(result=GAVE_UP, code=1)
    scenario.tick(result=GAVE_UP, code=1)
    assert len(messages(out)) == 1
    scenario.tick()
    assert "! loop recovered after 1105 failed ticks\n" in messages(out)[1]


def test_the_month_reaching_its_budget_is_sent_once_per_budget(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "phone.txt"
    add_sink(scenario, sink_script, "phone", out, format="text", events=["loop"])
    scenario.configures(spend={"monthly_budget_usd": 3})
    conn = scenario.conn
    chore_costs = functools.partial(chore_cost, conn)
    chore_costs(2.0)
    scenario.tick()
    assert messages(out) == []  # $2 of $3
    chore_costs(2.0)
    scenario.tick()
    month = f"{datetime.now().astimezone():%Y-%m}"
    [over] = messages(out)
    assert over.startswith(f"canopy: 1 event\n! spend for {month} reached its budget: $4.00 of $3")
    # canopy loop never read the runtime's sessions, so the part outside canopy is not known.
    assert "; canopy's runs $4.00, outside canopy not read yet\n" in over
    # Told once, even after pruning would have taken the event that says so.
    conn.execute("UPDATE notify_events SET at = ?", (db.format_time(datetime.now(UTC) - timedelta(days=8)),))
    scenario.tick()
    assert len(messages(out)) == 1
    # A budget raised past the month's spend is heard of again once the month reaches it.
    scenario.configures(spend={"monthly_budget_usd": 5})
    scenario.tick()
    assert len(messages(out)) == 1
    chore_costs(2.0)
    scenario.tick()
    assert f"! spend for {month} reached its budget: $6.00 of $5" in messages(out)[1]


def test_each_budget_alert_is_sent_once_as_the_month_reaches_it(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "phone.txt"
    add_sink(scenario, sink_script, "phone", out, format="text", events=["loop"])
    scenario.configures(spend={"monthly_budget_usd": 10, "budget_alerts": [150, 50, 80]})
    month = f"{datetime.now().astimezone():%Y-%m}"
    scenario.tick()  # a new sink hears nothing from before it
    for usd, told in (
        (6.0, "50% of its budget: $6.00"),
        (3.0, "80% of its budget: $9.00"),
        (2.0, "its budget: $11.00"),
    ):
        chore_cost(scenario.conn, usd)
        scenario.tick()
        assert f"! spend for {month} reached {told} of $10" in messages(out)[-1]
    scenario.tick()
    assert len(messages(out)) == 3
    chore_cost(scenario.conn, 6.0)
    scenario.tick()
    assert f"! spend for {month} reached 150% of its budget: $17.00 of $10" in messages(out)[-1]


def test_a_month_past_several_alerts_at_once_hears_only_the_highest(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "phone.txt"
    add_sink(scenario, sink_script, "phone", out, format="text", events=["loop"])
    scenario.configures(spend={"monthly_budget_usd": 10, "budget_alerts": [50, 80]})
    scenario.tick()  # a new sink hears nothing from before it
    chore_cost(scenario.conn, 12.0)
    scenario.tick()
    [told] = messages(out)
    assert "! spend for " in told
    assert " reached its budget: $12.00 of $10" in told
    # An alert added below what the sink already heard of is not news.
    scenario.configures(spend={"budget_alerts": [30, 50, 80]})
    scenario.tick()
    assert len(messages(out)) == 1


def test_the_sessions_outside_canopy_count_toward_the_budget(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "phone.txt"
    add_sink(scenario, sink_script, "phone", out, format="text", events=["loop"])
    scenario.configures(spend={"monthly_budget_usd": 3})
    chore_cost(scenario.conn, 2.0)
    scenario.tick()
    assert messages(out) == []  # $2 of $3
    # The operator's own session, outside canopy, as canopy loop reads it between ticks.
    ms = int(datetime.now(UTC).timestamp() * 1000)
    mine = SessionSpend("ses_mine", None, "/home/me/notes", ms, ms, 1.5, 1, 1, 0, 0, 0)
    read = datetime(2026, 10, 28, 13, 5, tzinfo=UTC)
    page = SessionPage("found", (mine,), cursor=(ms, "ses_mine"))
    runtime_sessions.record(scenario.conn, page, now=db.format_time(read))
    scenario.tick()
    month = f"{datetime.now().astimezone():%Y-%m}"
    [over] = messages(out)
    assert over.startswith(f"canopy: 1 event\n! spend for {month} reached its budget: $3.50 of $3")
    # The message names both parts, and when canopy loop last read the runtime's sessions, in local time.
    at = f"{read.astimezone():%Y-%m-%d %H:%M}"
    assert f"; canopy's runs $2.00, outside canopy $1.50 (sessions read {at})\n" in over


def test_a_budget_alert_after_a_failed_read_of_the_sessions_says_it_failed(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "phone.txt"
    add_sink(scenario, sink_script, "phone", out, format="text", events=["loop"])
    scenario.configures(spend={"monthly_budget_usd": 3})
    chore_cost(scenario.conn, 2.0)
    scenario.tick()
    ms = int(datetime.now(UTC).timestamp() * 1000)
    mine = SessionSpend("ses_mine", None, "/home/me/notes", ms, ms, 1.5, 1, 1, 0, 0, 0)
    runtime_sessions.record(scenario.conn, SessionPage("found", (mine,), cursor=(ms, "ses_mine")))
    failed = datetime(2026, 10, 28, 14, 10, tzinfo=UTC)
    runtime_sessions.record(scenario.conn, SessionPage("failed", error="locked"), now=db.format_time(failed))
    scenario.tick()
    [over] = messages(out)
    # The part outside canopy is what the earlier read found, and the message says the latest read failed.
    at = f"{failed.astimezone():%Y-%m-%d %H:%M}"
    assert f"; canopy's runs $2.00, outside canopy $1.50 (the last read of sessions failed {at})\n" in over


def test_a_budget_alerts_parts_add_up_to_its_total() -> None:
    month = spend.Month("2026-10", "", "", 3, 2.01, 0.5, None, runs_usd=1.005, outside_usd=1.005)
    fields = outbox.budget_reached(month, 100).fields
    # Each part rounded on its own would read $1.00 and $1.00 of a $2.01 total.
    assert (fields["spent"], fields["runs"], fields["outside"]) == (2.01, 1.0, 1.01)


def chore_cost(conn: sqlite3.Connection, usd: float) -> None:
    """A chore run that started now and cost `usd`, as the month's spend counts it."""
    conn.execute(
        "INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path, cost_usd) "
        "VALUES (NULL, 'deps', ?, 'ok', 'l', ?)",
        (db.now(), usd),
    )


def test_a_digest_arrives_on_its_interval_even_when_quiet(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "digest.txt"
    add_sink(scenario, sink_script, "daily", out, format="text", events=[], digest_every_minutes=60)
    scenario.tick()
    [first] = messages(out)
    assert first.startswith("canopy digest\nDigest since ")
    assert (
        ": 1 ticks (ok 1)\n  nothing ran\n  spent: none reported\n  nothing needs you\n  workers running: 0\n" in first
    )
    scenario.tick()
    assert len(messages(out)) == 1  # not due again yet
    scenario.time_passes(minutes=61)
    [earlier] = scenario.conn.execute("SELECT last_digest_at FROM notify_sinks").fetchone()
    scenario.tick()
    second = messages(out)[1]
    assert f"Digest since {earlier}: 2 ticks (ok 2)" in second


def test_a_batching_sink_holds_what_is_not_urgent_until_its_window_ends(
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "slack.txt"
    add_sink(scenario, sink_script, "slack", out, events=["attention", "runs"], batch_minutes=30)
    scenario.tick(*needing_reviewers("PROJ-9"))  # the first delivery goes at once
    assert len(messages(out)) == 1
    scenario.run(worker=worker_does())
    scenario.tick(*needing_reviewers("PROJ-9"), *waits("PROJ-1"))
    assert len(messages(out)) == 1  # held: a run started and ended, and nothing needs the operator
    assert "  slack  last delivered " in scenario.operator("status").out

    scenario.run(dispatches("PROJ-2"), worker=worker_does())
    scenario.time_passes(minutes=31)
    # PROJ-9 resolved meanwhile: resolving is not urgent either, but the window is over.
    scenario.tick(*waits("PROJ-1", "PROJ-2", "PROJ-9"))
    [_, batch] = json_messages(out)
    assert [(e["kind"], e["ticket"]) for e in batch["events"]] == [
        ("run.started", "PROJ-1"),
        ("run.ended", "PROJ-1"),
        ("run.started", "PROJ-2"),
        ("run.ended", "PROJ-2"),
    ]
    assert [r["ticket"] for r in batch["attention"]["resolved"]] == ["PROJ-9"]
    scenario.tick(*waits("PROJ-1", "PROJ-2", "PROJ-9"))
    assert len(messages(out)) == 2  # nothing new, and the cursor moved past what the batch sent


@pytest.mark.parametrize("urgent", ["attention", "blocked"])
def test_a_batching_sink_sends_what_needs_the_operator_at_once_with_what_it_held(
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
    urgent: str,
) -> None:
    out = tmp_path / "slack.txt"
    add_sink(scenario, sink_script, "slack", out, events=["attention", "runs"], batch_minutes=30)
    scenario.tick(*needing_reviewers("PROJ-9"))
    scenario.run(worker=worker_does())
    scenario.tick(*needing_reviewers("PROJ-9"), *waits("PROJ-1"))
    assert len(messages(out)) == 1
    attention = needing_reviewers("PROJ-9")
    if urgent == "blocked":
        scenario.run(dispatches("PROJ-2"), worker=asks("Which?"))
    else:
        scenario.run(dispatches("PROJ-2"), worker=worker_does())
        attention.append(raises("PROJ-8", "multi_repo"))
    scenario.tick(*attention, *waits("PROJ-1", "PROJ-2"))
    [_, sent] = json_messages(out)
    assert [(e["kind"], e["ticket"]) for e in sent["events"]] == [
        ("run.started", "PROJ-1"),
        ("run.ended", "PROJ-1"),
        ("run.started", "PROJ-2"),
        ("run.ended", "PROJ-2"),
    ]
    assert [a["ticket"] for a in sent["attention"]["added"]] == ([] if urgent == "blocked" else ["PROJ-8"])


def test_a_batching_sink_hears_the_loop_failing_at_once_with_what_it_held(
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "desk.txt"
    add_sink(scenario, sink_script, "desk", out, events=["attention", "loop", "runs"], batch_minutes=30)
    scenario.tick(*needing_reviewers("PROJ-9"))
    scenario.run(worker=worker_does())
    scenario.tick(result=GAVE_UP, code=1)
    scenario.tick(result=GAVE_UP, code=1)
    assert len(messages(out)) == 1  # the runs are held
    scenario.tick(result=GAVE_UP, code=1)
    [_, sent] = json_messages(out)
    assert [e["kind"] for e in sent["events"]] == ["run.started", "run.ended", "loop.failing"]


def test_a_batching_sink_hears_another_sink_failing_at_once_with_what_it_held(
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    down, desk = tmp_path / "alerts.txt", tmp_path / "desk.txt"
    add_sink(scenario, sink_script, "alerts", down)  # before desk in name order, so desk hears it the same tick
    add_sink(scenario, sink_script, "desk", desk, events=["attention", "loop", "runs"], batch_minutes=30)
    Path(f"{down}.exit").write_text("1")
    scenario.tick(*needing_reviewers("PROJ-9"))
    scenario.run(worker=worker_does())
    scenario.tick(*needing_reviewers("PROJ-9"), *waits("PROJ-1"))
    assert len(messages(desk)) == 1  # the runs are held
    scenario.tick(*needing_reviewers("PROJ-9"), *waits("PROJ-1"))  # alerts' third failure in a row
    [_, sent] = json_messages(desk)
    assert [e["kind"] for e in sent["events"]] == ["run.started", "run.ended", "loop.sink_failing"]


def test_a_json_digest_names_each_ticket_by_its_title(
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "digest.txt"
    add_sink(scenario, sink_script, "daily", out, events=[], digest_every_minutes=60)
    titled("PROJ-1", "Retry failed checkouts", scenario)
    scenario.run(worker=worker_does(result=json.dumps({"status": "blocked", "summary": "x", "question": "Which?"})))
    scenario.tick(*waits("PROJ-1"))

    [message] = json_messages(out)
    assert message["digest"]["blocked"] == [{"ticket": "PROJ-1", "title": "Retry failed checkouts", "run": 1}]
    assert "  blocked PROJ-1\n" in message["text"]  # the text format shows the key alone


def test_a_digest_says_what_its_runs_cost_by_kind(
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "digest.txt"
    add_sink(scenario, sink_script, "daily", out, events=[], digest_every_minutes=60)
    with_events(scenario.env, "canopy-worker")
    scenario.run(worker=worker_does())  # two model calls at 0.125
    scenario.tick(*waits("PROJ-1"))

    [message] = json_messages(out)
    spent = message["digest"]["spend"]
    assert (spent["total"], spent["workers"], spent["overseer"], spent["chores"]) == (0.25, 0.25, None, None)
    assert "  spent: $0.25 (workers $0.25)\n" in message["text"]


def test_a_digest_names_the_sessions_outside_canopy_last(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "digest.txt"
    add_sink(scenario, sink_script, "daily", out, events=[], digest_every_minutes=60)
    ms = int(datetime.now(UTC).timestamp() * 1000)
    mine = SessionSpend("ses_mine", None, "/home/me/notes", ms, ms, 1.5, 1, 1, 0, 0, 0)
    runtime_sessions.record(scenario.conn, SessionPage("found", (mine,), cursor=(ms, "ses_mine")))
    chore_cost(scenario.conn, 0.5)
    scenario.tick()

    [message] = json_messages(out)
    spent = message["digest"]["spend"]
    assert (spent["total"], spent["chores"], spent["outside"]) == (2.0, 0.5, 1.5)
    assert "  spent: $2.00 (chores $0.50, outside canopy $1.50)\n" in message["text"]


def test_a_digest_under_a_spend_floor_waits_until_the_runs_since_the_last_cost_that_much(
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "digest.txt"
    add_sink(scenario, sink_script, "spend", out, events=[], digest_every_minutes=60, digest_min_usd=0.5)
    with_events(scenario.env, "canopy-worker")
    scenario.tick()
    assert messages(out) == []  # nothing spent: no heartbeat either
    scenario.run(worker=worker_does())  # $0.25
    scenario.tick(*waits("PROJ-1"))
    assert messages(out) == []
    scenario.run(dispatches("PROJ-2"), worker=worker_does())  # $0.25 more: the floor, added up across ticks
    scenario.tick(*waits("PROJ-1", "PROJ-2"))

    [message] = json_messages(out)
    assert message["digest"]["spend"]["workers"] == 0.5
    scenario.time_passes(minutes=61)
    # The operator's own session outside canopy is no run of the loop's: however dear, it meets no floor.
    ms = int(datetime.now(UTC).timestamp() * 1000)
    mine = SessionSpend("ses_mine", None, "/home/me/notes", ms, ms, 9.0, 1, 1, 0, 0, 0)
    runtime_sessions.record(scenario.conn, SessionPage("found", (mine,), cursor=(ms, "ses_mine")))
    scenario.tick(*waits("PROJ-1", "PROJ-2"))
    assert len(messages(out)) == 1  # due again, but no run of canopy's spent anything since


def test_bounds_count_what_they_leave_out(scenario: Scenario, sink_script: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    add_sink(scenario, sink_script, "s", out, format="text")
    scenario.tick(*needing_reviewers(*(f"PROJ-{n:02}" for n in range(25))))
    [message] = messages(out)
    lines = message.splitlines()
    assert lines[0] == "canopy attention: 25 new, 0 resolved"
    assert sum(line.startswith("+ ") for line in lines) == 20
    assert lines[-2] == f"... and 5 more: see {scenario.env.state_dir / 'attention.md'} and `canopy status`"
    assert scenario.conn.execute("SELECT count(*) FROM notifications WHERE sink = 's'").fetchone()[0] == 25


def test_stale_events_are_counted_not_listed_and_a_new_sink_gets_no_backlog(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    conn = scenario.conn
    old = tmp_path / "old.txt"
    add_sink(scenario, sink_script, "old", old, events=["runs"])
    scenario.tick()  # creates the sink's row at the newest event
    day_ago = db.format_time(datetime.now(UTC) - timedelta(hours=25))
    for n in range(3):
        event = db.Event("runs", "run.started", {"ticket": f"PROJ-{n}", "run": n, "run_kind": "implement"})
        db.record_event(conn, event)
    # Only the first of the three is a day old. An event's time is its `at`.
    conn.execute("UPDATE notify_events SET at = ? WHERE id = 1", (day_ago,))
    new = tmp_path / "new.txt"
    add_sink(scenario, sink_script, "new", new, events=["runs"])
    scenario.tick()
    [message] = json_messages(old)
    assert [e["ticket"] for e in message["events"]] == ["PROJ-1", "PROJ-2"]
    assert message["omitted"] == 1
    assert messages(new) == []


def test_removed_sinks_are_forgotten_and_passed_events_pruned(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    conn = scenario.conn
    add_sink(scenario, sink_script, "s", tmp_path / "s.txt", events=["attention", "runs"])
    scenario.tick(*needing_reviewers("PROJ-1"))
    db.record_event(conn, db.Event("runs", "run.started", {"ticket": "PROJ-1"}))
    scenario.tick(*needing_reviewers("PROJ-1"))
    # The events alone age past pruning. An event's time is its `at`.
    week_ago = db.format_time(datetime.now(UTC) - timedelta(days=8))
    conn.execute("UPDATE notify_events SET at = ?", (week_ago,))
    scenario.tick(*needing_reviewers("PROJ-1"))
    assert conn.execute("SELECT count(*) FROM notify_events").fetchone()[0] == 0
    scenario.configures(notify={"sinks": {"s": None}})
    scenario.tick(*needing_reviewers("PROJ-1"))
    assert conn.execute("SELECT count(*) FROM notify_sinks").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM notifications").fetchone()[0] == 0


def test_notify_test_sends_now_and_changes_nothing(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    add_sink(scenario, sink_script, "a", a)
    add_sink(scenario, sink_script, "b", b, format="text")
    Path(f"{b}.exit").write_text("3")
    assert scenario.operator("notify", "test", code=1).out == "a: delivered\nb: failed: exited 3: sink down\n"
    [message] = json_messages(a)
    assert message["events"][0]["kind"] == "test"
    assert message["attention"] is None
    assert messages(b)[0].startswith("canopy: 1 event\n* canopy test message for ")
    scenario.operator("notify", "test", "a")
    assert "no sink named 'nope'; configured: a, b" in scenario.operator("notify", "test", "nope", code=1).err
    assert scenario.conn.execute("SELECT count(*) FROM notify_sinks").fetchone()[0] == 0
    # Neither the overseer nor a worker, review, or chore it started may page the operator: not the operator's shell.
    for name in ("CANOPY_TICK_ID", "CANOPY_RUN_ID"):
        with mock.patch.dict(os.environ, {name: "1"}):
            assert main(["notify", "test"]) == 1
            assert f"notify test refused (inside_run): {name} is set" in capsys.readouterr().err
    assert (len(messages(a)), len(messages(b))) == (2, 1)


def test_chore_runs_reach_a_sink_that_takes_chores(scenario: Scenario, sink_script: Path, tmp_path: Path) -> None:
    prompt = scenario.env.home / "chore.md"
    prompt.write_text("Check.\n")
    chore_cmd = "agent run --agent canopy-chore {prompt}"
    # With a `when`, the overseer's to run or hold off (DESIGN §37).
    check = {"prompt": str(prompt), "every_minutes": 60, "cmd": chore_cmd, "when": "Weekdays only."}
    scenario.configures(chores={"check": check})
    out = tmp_path / "chores.txt"
    add_sink(scenario, sink_script, "s", out, format="text", events=["chores"])
    scenario.tick(canopy("chore", "wait", "check", "--rationale", "not needed yet"))
    chore: dict[str, object] = {"status": "ok", "summary": "all clear", "findings": []}
    # The chore's result stays set through the next tick, as the overseer's does.
    with chore_reports(chore):
        with in_tick(scenario.conn, ends_ok=True):
            assert main(["chore", "run", "check"], runner=InlineRunner()) == 0
            tick_starts(InlineRunner())
            assert main(["_chore", "1"], runner=InlineRunner()) == 0
        scenario.tick()
    [message] = messages(out)
    assert "< chore:check run 1 ended ok (0 findings): all clear\n" in message


def test_a_finding_the_operator_dismissed_is_marked_so_in_both_formats() -> None:
    gone = notify_journal.Diff([], [("chore:deps", "lodash")], ["fp"], [("chore:deps", "lodash", None)], [True])
    sent = message.Message("log", "/r", Path("/r/attention.md"), gone, 0)
    assert "- chore:deps lodash (dismissed)\n" in sent.text()
    [resolved] = json.loads(sent.json())["attention"]["resolved"]
    assert resolved["dismissed"] is True


UI = "http://localhost:9000/canopy/"


def test_a_json_message_links_each_subject_to_its_page_in_the_web_ui() -> None:
    since = "2026-10-19T12:00:00Z"
    pr = "https://github.test/o/r/pull/7"
    added = [
        Item("PROJ-1", "needs_author", "d", since),
        Item("chore:deps", "lodash", "d", since, finding=True),
        Item(f"pr:{pr}", "review_requested", "d", since),
        Item(None, "repo_missing", "d", since, repo="web"),
    ]
    events = [
        message.Event(1, "run.started", since, {"ticket": "PROJ-1", "run": 3}),
        message.Event(2, "run.ended", since, {"ticket": "PROJ-1", "run": 3, "ui": "http://evil.test/"}),
        message.Event(3, "plan.proposed", since, {"ticket": "PROJ-1", "run": 3, "plan": 1}),
        message.Event(4, "chore.ended", since, {"chore": "deps", "run": 5}),
        message.Event(5, "review.ended", since, {"pr": pr, "run": 6}),
        message.Event(6, "loop.failing", since, {"tick": 9}),
        message.Event(7, "loop.recovered", since, {"failed": 3}),
        message.Event(8, "loop.budget_reached", since, {"month": "2026-10", "budget": 30, "percent": 100}),
        message.Event(9, "reply.recorded", since, {"ticket": "PROJ-1", "message": 4, "ts": "1.2", "body": "go"}),
        message.Event(10, "reply.refused", since, {"ticket": None, "ts": "1.3", "guard": "no_ticket", "reason": "r"}),
    ]
    change = notify_journal.Diff(added, [], [], [])
    sent = message.Message("slack", "/r", Path("/r/attention.md"), change, 4, events, ui=UI)
    body = json.loads(sent.json())
    assert body["ui"] == UI
    assert body["attention"]["ui"] == f"{UI}attention"
    assert [a["ui"] for a in body["attention"]["added"]] == [
        f"{UI}tickets/PROJ-1",
        f"{UI}chores/deps",
        f"{UI}pull-requests/pr?url=https%3A%2F%2Fgithub.test%2Fo%2Fr%2Fpull%2F7",
        f"{UI}attention",
    ]
    # An event's own field named `ui` is dropped: the link is canopy's.
    assert [e["ui"] for e in body["events"]] == [
        f"{UI}runs/3",
        f"{UI}runs/3",
        f"{UI}tickets/PROJ-1/plan",
        f"{UI}chores/deps/runs/5",
        f"{UI}reviews/6",
        f"{UI}ticks/9",
        None,
        f"{UI}spend",
        f"{UI}tickets/PROJ-1",
        None,
    ]
    # The text format links nothing, so `notify.cmd` sees no change.
    assert sent.text() == dataclasses.replace(sent, ui=None).text()
    assert "http://localhost" not in sent.text()


def test_a_page_encodes_each_part_whole() -> None:
    assert message.page(UI, "tickets", "a/../b?c#d") == f"{UI}tickets/a%2F..%2Fb%3Fc%23d"
    assert message.page(None, "tickets", "PROJ-1") is None


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("localhost:9000", "must be an http:// or https:// URL"),
        ("ftp://localhost/", "must be an http:// or https:// URL"),
        ("http://localhost/<x>", "must be an http:// or https:// URL"),
        ("http://localhost/a|b", "must be an http:// or https:// URL"),
        ("http://user@localhost/", "no user part"),
        ("http://localhost/?a=1", "no user part, query, or fragment"),
        ("http://localhost/#top", "no user part, query, or fragment"),
        ("http:///canopy", "must name a host"),
        ("http://localhost:port/", "port that is not a number"),
        ("http://localhost/" + "x" * 200, "must be an http:// or https:// URL"),
    ],
)
def test_serve_url_is_checked(canopy_env: CanopyEnv, url: str, error: str) -> None:
    canopy_env.append_user(f'\n[serve]\nurl = "{url}"\n')
    with pytest.raises(ConfigError, match=re.escape(error)):
        load(canopy_env.root, canopy_env.user_file)


def test_serve_url_ends_in_a_slash_and_is_private(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user('\n[serve]\nurl = "https://canopy.home.test/canopy"\n')
    assert load(canopy_env.root, canopy_env.user_file).serve.url == "https://canopy.home.test/canopy/"
    canopy_env.append_shared('\n[serve]\nurl = "https://evil.test/"\n')
    with pytest.raises(ConfigError, match="is private"):
        load(canopy_env.root, canopy_env.user_file)


def test_what_came_of_a_reply_from_slack_reads_as_a_line() -> None:
    recorded = {"ticket": "PROJ-1", "message": 4, "ts": "1.2", "body": "use the staging config"}
    refused = {"ticket": "PROJ-9", "ts": "1.3", "guard": "unknown", "reason": "canopy has no record of PROJ-9"}
    unnamed = {"ticket": None, "ts": "1.4", "guard": "no_ticket", "reason": "it names no ticket"}
    assert (
        message.event_line("reply.recorded", recorded)
        == "+ PROJ-1 your reply from Slack recorded: use the staging config"
    )
    assert message.event_line("reply.refused", refused) == (
        "! your reply from Slack on PROJ-9 not recorded (unknown): canopy has no record of PROJ-9"
    )
    assert message.event_line("reply.refused", unnamed) == (
        "! your reply from Slack not recorded (no_ticket): it names no ticket"
    )
