"""The attention list rendered to `attention.md`, and its diff piped to `notify.cmd` (DESIGN §6, §14)."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canopy import attention, db
from canopy.cli import main
from canopy.config import ConfigError, load
from tests.canopy.helpers import journal
from tests.conftest import CanopyEnv

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def item(key: str, reason: str, detail: str, age: timedelta) -> attention.Item:
    return attention.Item(key, reason, detail, db.format_time(NOW - age))


def test_render_groups_by_reason() -> None:
    items = [
        item("PROJ-1", "crashed", "run 3 ended crashed", timedelta(hours=2)),
        item("PROJ-2", "needs_reviewer", "https://example.test/pr/2\nsecond line", timedelta(days=1, hours=3)),
        item("PROJ-4", "crashed", "run 5 ended crashed", timedelta(seconds=40)),
    ]
    assert attention.render(items, NOW) == (
        "# canopy attention\n"
        "\n"
        "3 items, updated 2026-09-24 12:00 UTC. An item leaves this list when its cause is gone.\n"
        "\n"
        "## crashed\n"
        "\n"
        "- PROJ-1, 2h: run 3 ended crashed\n"
        "- PROJ-4, 40s: run 5 ended crashed\n"
        "\n"
        "## needs_reviewer\n"
        "\n"
        "- PROJ-2, 1d: https://example.test/pr/2 second line\n"
    )


def test_render_empty() -> None:
    assert attention.render([], NOW) == "# canopy attention\n\nNothing needs you. Updated 2026-09-24 12:00 UTC.\n"


def overseer_records(monkeypatch: pytest.MonkeyPatch, *items: tuple[str, str]) -> None:
    commands = [["canopy", "attention", key, reason, "--detail", f"{key} detail"] for key, reason in items]
    monkeypatch.setenv("FAKE_OVERSEER_COMMANDS", json.dumps(commands))
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")


@pytest.fixture
def notified(canopy_env: CanopyEnv, tmp_path: Path) -> Path:
    """Set notify.cmd to a script that appends what it reads, then a separator, to the returned file."""
    out = tmp_path / "notified.txt"
    script = tmp_path / "notify"
    script.write_text('#!/bin/sh\ncat >> "$1"\necho "--" >> "$1"\nexit "${NOTIFY_EXIT:-0}"\n')
    script.chmod(0o755)
    canopy_env.write_user(canopy_env.user_file.read_text() + f"\n[notify]\ncmd = '{script} {out}'\n")
    return out


def messages(out: Path) -> list[str]:
    return out.read_text().split("--\n")[:-1] if out.exists() else []


def test_every_tick_rewrites_attention_md(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = canopy_env.state_dir / "attention.md"
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"))
    assert main(["tick", "--dry-run"]) == 0
    text = path.read_text()
    assert "## needs_reviewer\n\n- PROJ-3, " in text
    assert text.endswith(": PROJ-3 detail\n")
    assert path.stat().st_mode & 0o777 == 0o600

    overseer_records(monkeypatch)
    assert main(["tick", "--dry-run"]) == 0
    assert "Nothing needs you." in path.read_text()


def test_notify_gets_new_and_resolved_items_once(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    notified: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = f"Full list: {canopy_env.state_dir / 'attention.md'}\n"
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"), ("PROJ-4", "ready_to_merge"))
    assert main(["tick"]) == 0
    assert messages(notified) == [
        "canopy attention: 2 new, 0 resolved\n"
        "+ PROJ-3 needs_reviewer: PROJ-3 detail\n"
        "+ PROJ-4 ready_to_merge: PROJ-4 detail\n" + listing
    ]

    # Still open, even with a reworded detail: nothing new to say.
    monkeypatch.setenv(
        "FAKE_OVERSEER_COMMANDS",
        json.dumps(
            [
                ["canopy", "attention", "PROJ-3", "needs_reviewer", "--detail", "reworded"],
                ["canopy", "attention", "PROJ-4", "ready_to_merge", "--detail", "PROJ-4 detail"],
            ]
        ),
    )
    assert main(["tick"]) == 0
    assert len(messages(notified)) == 1

    overseer_records(monkeypatch, ("PROJ-4", "ready_to_merge"))
    assert main(["tick"]) == 0
    assert messages(notified)[1] == "canopy attention: 0 new, 1 resolved\n- PROJ-3 needs_reviewer\n" + listing

    # An item that comes back after going away is new again.
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"), ("PROJ-4", "ready_to_merge"))
    assert main(["tick"]) == 0
    assert messages(notified)[2].startswith("canopy attention: 1 new, 0 resolved\n+ PROJ-3 needs_reviewer")
    assert sorted(str(r[0]) for r in conn.execute("SELECT ticket_key FROM notifications")) == ["PROJ-3", "PROJ-4"]


def test_failed_notify_is_retried_next_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    notified: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"))
    monkeypatch.setenv("NOTIFY_EXIT", "1")
    assert main(["tick"]) == 0  # a failed notification does not fail the tick
    assert conn.execute("SELECT count(*) FROM notifications").fetchone()[0] == 0
    log = (canopy_env.state_dir / "canopy.log").read_text()
    assert "notify command failed" in log

    monkeypatch.delenv("NOTIFY_EXIT")
    assert main(["tick"]) == 0
    assert [m.splitlines()[1] for m in messages(notified)] == ["+ PROJ-3 needs_reviewer: PROJ-3 detail"] * 2
    assert conn.execute("SELECT count(*) FROM notifications").fetchone()[0] == 1


def test_a_failed_tick_leaves_the_list_and_notifies_nothing_new(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, notified: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"))
    assert main(["tick"]) == 0
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "gave up")
    assert main(["tick"]) == 1
    assert "- PROJ-3, " in (canopy_env.state_dir / "attention.md").read_text()
    assert len(messages(notified)) == 1


def test_a_tick_wide_skip_leaves_the_list_and_notifies_nothing(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    notified: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"))
    assert main(["tick", "--dry-run"]) == 0
    skip = [["canopy", "decide", "skip", "--rationale", "mcp_unavailable: github"]]
    monkeypatch.setenv("FAKE_OVERSEER_COMMANDS", json.dumps(skip))
    capsys.readouterr()
    assert main(["tick", "--dry-run"]) == 1
    assert capsys.readouterr().out == "tick 2: skipped: dry run; overseer skipped the tick: mcp_unavailable: github\n"

    assert conn.execute("SELECT status FROM ticks WHERE id = 2").fetchone()[0] == "skipped"
    [still] = attention.current(conn)
    assert (still.ticket_key, still.reason) == ("PROJ-3", "needs_reviewer")
    assert "- PROJ-3, " in (canopy_env.state_dir / "attention.md").read_text()
    assert len(messages(notified)) == 1  # the first tick's; nothing resolved

    # The overseer sees the world again and still records the item: it was never gone, so it is not new.
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"))
    assert main(["tick", "--dry-run"]) == 0
    assert len(messages(notified)) == 1


def test_notify_cmd_takes_no_prompt_placeholder(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[notify]\ncmd = 'notify-send {prompt}'\n")
    with pytest.raises(ConfigError, match=r"notify\.cmd: Value error, must not contain \{prompt\}"):
        load(canopy_env.repo, canopy_env.user_file)


def test_notify_cmd_must_split_into_words(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + '\n[notify]\ncmd = "notify-send \'canopy"\n')
    with pytest.raises(ConfigError, match=r"notify\.cmd: Value error, No closing quotation"):
        load(canopy_env.repo, canopy_env.user_file)
