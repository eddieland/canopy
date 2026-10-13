"""Notification sinks (DESIGN §20, ROADMAP M10): per-sink delivery of the attention diff, events, and digests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.config import ConfigError, load
from canopy.core.items import fingerprint
from tests.canopy.helpers import InlineRunner, in_tick, journal, worker_does
from tests.conftest import CanopyEnv, GitPool

LABEL = "agent-ready-tester"


@pytest.fixture
def sink_script(tmp_path: Path) -> Path:
    """A sink command: `sink OUT [EXIT_FILE]` appends what it reads on stdin, then a separator, to OUT, and exits with
    the number in EXIT_FILE if there is one."""
    script = tmp_path / "sink"
    script.write_text(
        '#!/bin/sh\ncat >> "$1"\necho "--" >> "$1"\n'
        'if [ -n "$2" ] && [ -f "$2" ]; then echo "sink down" >&2; exit "$(cat "$2")"; fi\n'
    )
    script.chmod(0o755)
    return script


def add_sink(env: CanopyEnv, script: Path, name: str, out: Path, *, extra: str = "") -> None:
    env.write_user(env.user_file.read_text() + f"\n[notify.sinks.{name}]\ncmd = '{script} {out} {out}.exit'\n{extra}")


def messages(out: Path) -> list[str]:
    return out.read_text().split("--\n")[:-1] if out.exists() else []


def json_messages(out: Path) -> list[dict[str, Any]]:
    return [json.loads(m) for m in messages(out)]


def overseer_records(monkeypatch: pytest.MonkeyPatch, *items: tuple[str, str]) -> None:
    commands = [["canopy", "attention", key, reason, "--detail", f"{key} detail"] for key, reason in items]
    monkeypatch.setenv("FAKE_OVERSEER_COMMANDS", json.dumps(commands))
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")


def tick(*, ok: bool = True) -> None:
    assert main(["tick"]) == (0 if ok else 1)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("[notify]\ncmd = 'x'\n[notify.sinks.default]\ncmd = 'y'\n", "set notify.cmd or \\[notify.sinks.default\\]"),
        ("[notify.sinks.slack]\ncmd = 'post {prompt}'\n", r"must not contain \{prompt\}"),
        ("[notify.sinks.slack]\ncmd = ''\n", "must not be empty"),
        ("[notify.sinks.slack]\ncmd = 'x'\nevents = ['everything']\n", "events"),
        ("[notify.sinks.slack]\ncmd = 'x'\ndigest_every_minutes = 30\n", "greater than or equal to 60"),
        ("[notify.sinks.Slack]\ncmd = 'x'\n", "sink name 'Slack'"),
        ("".join(f"[notify.sinks.s{i}]\ncmd = 'x'\n" for i in range(6)), "at most 5 sinks"),
    ],
)
def test_sink_config_is_checked(canopy_env: CanopyEnv, extra: str, message: str) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n" + extra)
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.root, canopy_env.user_file)


def test_notify_cmd_is_the_default_sink(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(
        canopy_env.user_file.read_text() + "\n[notify]\ncmd = 'notify-me'\n[notify.sinks.b]\ncmd = 'b'\n"
    )
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
    canopy_env.write_shared(canopy_env.shared_file.read_text() + "\n[notify.sinks.x]\ncmd = 'curl evil'\n")
    with pytest.raises(ConfigError, match=r"notify\.sinks is user-only"):
        load(canopy_env.root, canopy_env.user_file)


def test_notify_cmd_is_the_sink_named_default(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`notify.cmd` is the sink `default`: what was notified as `default` is not notified again."""
    conn = journal(canopy_env)
    conn.execute(
        "INSERT INTO notifications (sink, fingerprint, ticket_key, reason, repo, sent_at) "
        "VALUES ('default', ?, 'PROJ-3', 'needs_reviewer', NULL, 'x')",
        (fingerprint("PROJ-3", "needs_reviewer"),),
    )
    out = tmp_path / "notified.txt"
    canopy_env.write_user(canopy_env.user_file.read_text() + f"\n[notify]\ncmd = '{sink_script} {out}'\n")
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"))
    tick()
    assert messages(out) == []
    rows = [tuple(r) for r in conn.execute("SELECT sink, ticket_key, reason FROM notifications")]
    assert rows == [("default", "PROJ-3", "needs_reviewer")]

    # Renamed to a sink of its own, it is new there and hears about every open item once.
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[notify]\ncmd", "[notify.sinks.mine]\nformat = 'text'\ncmd")
    )
    tick()
    [message] = messages(out)
    assert "+ PROJ-3 needs_reviewer: PROJ-3 detail\n" in message
    assert [tuple(r) for r in conn.execute("SELECT sink FROM notifications")] == [("mine",)]


def test_a_json_sink_hears_about_runs(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "slack.txt"
    add_sink(canopy_env, sink_script, "slack", out, extra='events = ["attention", "loop", "runs"]\n')
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    tick()  # the sink's first publish: from here on it hears every event
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    assert main(["ticket", "set", "PROJ-1", "--title", "Retry failed checkouts"]) == 0
    question = "Should the retry be per request or per session?\nThe ticket says both."
    worker_does(
        monkeypatch,
        result=json.dumps({"status": "blocked", "branch": "agent/PROJ-1-work", "summary": "x", "question": question}),
    )
    runner = InlineRunner()
    assert main(["dispatch", "PROJ-1", "--repo", "repo", "--label", LABEL, "--kind", "implement"], runner=runner) == 0
    assert main(["_run", "1"], runner=runner) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID", raising=False)
    overseer_records(monkeypatch, ("PROJ-9", "needs_reviewer"))
    tick()

    [message] = json_messages(out)
    assert message["version"] == 1
    assert message["sink"] == "slack"
    assert message["repo"] == str(canopy_env.root)
    assert message["attention"]["added"] == [
        {
            "ticket": "PROJ-9",
            "title": None,  # not named yet
            "repo": None,
            "reason": "needs_reviewer",
            "detail": "PROJ-9 detail",
            "since": message["attention"]["added"][0]["since"],
        }
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
    assert message["text"].startswith("canopy attention: 1 new, 0 resolved\n+ PROJ-9 needs_reviewer: PROJ-9 detail\n> ")

    # Delivered events are not sent again.
    tick()
    assert len(messages(out)) == 1


def test_without_sinks_no_event_is_recorded(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = journal(canopy_env)
    in_tick(conn, monkeypatch)
    worker_does(monkeypatch)
    runner = InlineRunner()
    assert main(["dispatch", "PROJ-1", "--repo", "repo", "--label", LABEL, "--kind", "implement"], runner=runner) == 0
    assert main(["_run", "1"], runner=runner) == 0
    assert conn.execute("SELECT count(*) FROM notify_events").fetchone()[0] == 0


def test_a_failing_sink_does_not_hold_back_another_and_catches_up(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M10's acceptance against the fakes: one sink down for several ticks, the other reports it, then it catches up."""
    slack, desk = tmp_path / "slack.txt", tmp_path / "desk.txt"
    add_sink(canopy_env, sink_script, "desk", desk, extra="format = 'text'\n")
    add_sink(canopy_env, sink_script, "slack", slack)
    (Path(f"{slack}.exit")).write_text("1")
    for i in range(1, 5):
        overseer_records(monkeypatch, *((f"PROJ-{n}", "needs_reviewer") for n in range(1, i + 1)))
        tick()
    # Every delivery to slack failed, so it was told nothing; desk heard each change and, once, that slack is failing.
    conn = journal(canopy_env)
    assert conn.execute("SELECT count(*) FROM notifications WHERE sink = 'slack'").fetchone()[0] == 0
    desk_messages = messages(desk)
    assert len(desk_messages) == 4
    failing = [m for m in desk_messages if "! sink slack has failed 3 deliveries in a row" in m]
    assert len(failing) == 1
    assert "exited 1: sink down" in failing[0]
    capsys.readouterr()
    assert main(["status"]) == 0
    status = capsys.readouterr().out
    assert "  slack  never delivered; 1 events waiting; 4 failed in a row: exited 1: sink down\n" in status
    assert "  desk  last delivered " in status

    # Back up: one message with the net change, all four items.
    Path(f"{slack}.exit").unlink()
    tick()
    *_, caught_up = json_messages(slack)
    assert [a["ticket"] for a in caught_up["attention"]["added"]] == ["PROJ-1", "PROJ-2", "PROJ-3", "PROJ-4"]
    # It takes `loop`, so it hears that it was failing.
    assert [e["kind"] for e in caught_up["events"]] == ["loop.sink_failing"]
    row = conn.execute("SELECT failures, last_error FROM notify_sinks WHERE name = 'slack'").fetchone()
    assert tuple(row) == (0, None)


def test_loop_failing_and_recovered_are_sent_once_each(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "phone.txt"
    add_sink(canopy_env, sink_script, "phone", out, extra='format = "text"\nevents = ["loop"]\n')
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "gave up")
    for _ in range(5):
        tick(ok=False)
    [failing] = messages(out)
    assert failing.startswith("canopy: 1 event\n! loop failing: 3 ticks in a row ended other than ok; latest tick 3 ")
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    tick()
    tick()
    listing = f"Full list: {canopy_env.state_dir / 'attention.md'}\n"
    assert messages(out)[1] == f"canopy: 1 event\n! loop recovered after 5 failed ticks\n{listing}"
    assert len(messages(out)) == 2


def test_a_long_failing_streak_is_one_streak(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pruning keeps the streak's `loop.failing`, and the recovery counts every failed tick, however many."""
    out = tmp_path / "phone.txt"
    add_sink(canopy_env, sink_script, "phone", out, extra='format = "text"\nevents = ["loop"]\n')
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "gave up")
    for _ in range(3):
        tick(ok=False)
    assert len(messages(out)) == 1
    conn = journal(canopy_env)
    conn.execute("UPDATE notify_events SET at = ?", (db.format_time(datetime.now(UTC) - timedelta(days=8)),))
    conn.executemany(
        "INSERT INTO ticks (started_at, ended_at, status) VALUES (?, ?, 'overseer_failed')",
        [(db.now(), db.now())] * 1100,
    )
    tick(ok=False)
    tick(ok=False)
    assert len(messages(out)) == 1
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    tick()
    assert "! loop recovered after 1105 failed ticks\n" in messages(out)[1]


def test_a_digest_arrives_on_its_interval_even_when_quiet(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "digest.txt"
    add_sink(canopy_env, sink_script, "daily", out, extra='format = "text"\nevents = []\ndigest_every_minutes = 60\n')
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    tick()
    [first] = messages(out)
    assert first.startswith("canopy digest\nDigest since ")
    assert ": 1 ticks (ok 1)\n  nothing ran\n  nothing needs you\n  workers running: 0\n" in first
    tick()
    assert len(messages(out)) == 1  # not due again yet
    conn = journal(canopy_env)
    earlier = db.format_time(datetime.now(UTC) - timedelta(minutes=61))
    conn.execute("UPDATE notify_sinks SET last_digest_at = ?", (earlier,))
    tick()
    second = messages(out)[1]
    assert f"Digest since {earlier}: 3 ticks (ok 3)" in second


def test_a_json_digest_names_each_ticket_by_its_title(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "digest.txt"
    add_sink(canopy_env, sink_script, "daily", out, extra="events = []\ndigest_every_minutes = 60\n")
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    assert main(["ticket", "set", "PROJ-1", "--title", "Retry failed checkouts"]) == 0
    worker_does(monkeypatch, result=json.dumps({"status": "blocked", "summary": "x", "question": "Which?"}))
    runner = InlineRunner()
    assert main(["dispatch", "PROJ-1", "--repo", "repo", "--label", LABEL, "--kind", "implement"], runner=runner) == 0
    assert main(["_run", "1"], runner=runner) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID", raising=False)
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    tick()

    [message] = json_messages(out)
    assert message["digest"]["blocked"] == [{"ticket": "PROJ-1", "title": "Retry failed checkouts", "run": 1}]
    assert "  blocked PROJ-1\n" in message["text"]  # the text format shows the key alone


def test_bounds_count_what_they_leave_out(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "out.txt"
    add_sink(canopy_env, sink_script, "s", out, extra='format = "text"\n')
    overseer_records(monkeypatch, *((f"PROJ-{n:02}", "needs_reviewer") for n in range(25)))
    tick()
    [message] = messages(out)
    lines = message.splitlines()
    assert lines[0] == "canopy attention: 25 new, 0 resolved"
    assert sum(line.startswith("+ ") for line in lines) == 20
    assert lines[-2] == f"... and 5 more: see {canopy_env.state_dir / 'attention.md'} and `canopy status`"
    conn = journal(canopy_env)
    assert conn.execute("SELECT count(*) FROM notifications WHERE sink = 's'").fetchone()[0] == 25


def test_stale_events_are_counted_not_listed_and_a_new_sink_gets_no_backlog(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = journal(canopy_env)
    old = tmp_path / "old.txt"
    add_sink(canopy_env, sink_script, "old", old, extra='events = ["runs"]\n')
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    tick()  # creates the sink's row at the newest event
    day_ago = db.format_time(datetime.now(UTC) - timedelta(hours=25))
    for n in range(3):
        event = db.Event("runs", "run.started", {"ticket": f"PROJ-{n}", "run": n, "run_kind": "implement"})
        db.record_event(conn, event)
    conn.execute("UPDATE notify_events SET at = ? WHERE id = 1", (day_ago,))
    new = tmp_path / "new.txt"
    add_sink(canopy_env, sink_script, "new", new, extra='events = ["runs"]\n')
    tick()
    [message] = json_messages(old)
    assert [e["ticket"] for e in message["events"]] == ["PROJ-1", "PROJ-2"]
    assert message["omitted"] == 1
    assert messages(new) == []


def test_removed_sinks_are_forgotten_and_passed_events_pruned(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = journal(canopy_env)
    before = canopy_env.user_file.read_text()
    add_sink(canopy_env, sink_script, "s", tmp_path / "s.txt", extra='events = ["attention", "runs"]\n')
    overseer_records(monkeypatch, ("PROJ-1", "needs_reviewer"))
    tick()
    db.record_event(conn, db.Event("runs", "run.started", {"ticket": "PROJ-1"}))
    tick()
    week_ago = db.format_time(datetime.now(UTC) - timedelta(days=8))
    conn.execute("UPDATE notify_events SET at = ?", (week_ago,))
    tick()
    assert conn.execute("SELECT count(*) FROM notify_events").fetchone()[0] == 0
    canopy_env.write_user(before)
    tick()
    assert conn.execute("SELECT count(*) FROM notify_sinks").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM notifications").fetchone()[0] == 0


def test_notify_test_sends_now_and_changes_nothing(
    canopy_env: CanopyEnv,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    add_sink(canopy_env, sink_script, "a", a)
    add_sink(canopy_env, sink_script, "b", b, extra="format = 'text'\n")
    Path(f"{b}.exit").write_text("3")
    assert main(["notify", "test"]) == 1
    assert capsys.readouterr().out == "a: delivered\nb: failed: exited 3: sink down\n"
    [message] = json_messages(a)
    assert message["events"][0]["kind"] == "test"
    assert message["attention"] is None
    assert messages(b)[0].startswith("canopy: 1 event\n* canopy test message for ")
    assert main(["notify", "test", "a"]) == 0
    assert main(["notify", "test", "nope"]) == 1
    assert "no sink named 'nope'; configured: a, b" in capsys.readouterr().err
    conn = journal(canopy_env)
    assert conn.execute("SELECT count(*) FROM notify_sinks").fetchone()[0] == 0
    monkeypatch.setenv("CANOPY_TICK_ID", "1")
    assert main(["notify", "test"]) == 1
    assert "refuses inside a tick" in capsys.readouterr().err


def test_chore_runs_reach_a_sink_that_takes_chores(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    sink_script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = canopy_env.home / "chore.md"
    prompt.write_text("Check.\n")
    canopy_env.write_user(
        canopy_env.user_file.read_text()
        + f"\n[chores.check]\nprompt = '{prompt}'\nevery_minutes = 60\n"
        + "cmd = 'agent run --agent canopy-chore {prompt}'\n"
    )
    out = tmp_path / "chores.txt"
    add_sink(canopy_env, sink_script, "s", out, extra='format = "text"\nevents = ["chores"]\n')
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    tick()
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    monkeypatch.setenv("FAKE_CHORE_RESULT", json.dumps({"status": "ok", "summary": "all clear", "findings": []}))
    assert main(["chore", "run", "check"], runner=InlineRunner()) == 0
    assert main(["_chore", "1"], runner=InlineRunner()) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID", raising=False)
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    tick()
    [message] = messages(out)
    assert "< chore:check run 1 ended ok (0 findings): all clear\n" in message
