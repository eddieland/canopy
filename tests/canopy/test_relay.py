"""Mailbox sinks and `canopy-notify-relay` (DESIGN §20): notifications shown on a machine canopy does not run on."""

import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import canopy_notify_relay as relay
import pytest
import uvicorn
from fastapi.testclient import TestClient

from canopy.cli.main import main
from canopy.core import db, mailbox
from canopy.core.config import ConfigError, load
from canopy.serve import mock
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.backend import Backend
from canopy.serve.options import ServeOptions
from tests.canopy.helpers import journal
from tests.conftest import CanopyEnv

SECRET = "s3cret-" + "x" * 40
MAILBOX = "\n[notify.sinks.remote]\nmailbox = true\nevents = ['attention']\n"


def with_mailbox(env: CanopyEnv, extra: str = "") -> None:
    env.write_user(env.user_file.read_text() + MAILBOX + extra)


def overseer_records(monkeypatch: pytest.MonkeyPatch, *items: tuple[str, str]) -> None:
    commands = [["canopy", "attention", key, reason, "--detail", f"{key} detail"] for key, reason in items]
    monkeypatch.setenv("FAKE_OVERSEER_COMMANDS", json.dumps(commands))
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")


def read(capsys: pytest.CaptureFixture[str], *args: str) -> list[dict[str, object]]:
    assert main(["notify", "read", "remote", *args]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["sink"] == "remote"
    return out["messages"]


# The mailbox sink


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ("[notify.sinks.remote]\nevents = ['attention']\n", "set one of cmd and mailbox = true"),
        ("[notify.sinks.remote]\ncmd = 'x'\nmailbox = true\n", "set one of cmd and mailbox = true"),
        ("[notify.sinks.remote]\nmailbox = 'yes'\n", "mailbox"),
    ],
)
def test_a_sink_has_a_command_or_a_mailbox(canopy_env: CanopyEnv, table: str, message: str) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n" + table)
    with pytest.raises(ConfigError, match=message):
        load(canopy_env.repo, canopy_env.user_file)


def test_a_mailbox_sink_keeps_each_message_for_the_relay(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with_mailbox(canopy_env)
    overseer_records(monkeypatch, ("PROJ-3", "needs_reviewer"))
    assert main(["tick"]) == 0
    capsys.readouterr()
    [first] = read(capsys, "--after", "0")
    message = json.loads(str(first["message"]))
    assert message["sink"] == "remote"
    assert [a["ticket"] for a in message["attention"]["added"]] == ["PROJ-3"]
    conn = journal(canopy_env)
    assert [tuple(r) for r in conn.execute("SELECT sink, ticket_key FROM notifications")] == [("remote", "PROJ-3")]

    # Told once: the same list keeps nothing new. A resolved item is a second message.
    assert main(["tick"]) == 0
    overseer_records(monkeypatch)
    assert main(["tick"]) == 0
    capsys.readouterr()
    kept = read(capsys, "--after", "0")
    assert len(kept) == 2
    assert json.loads(str(kept[1]["message"]))["attention"]["resolved"] == [
        {"ticket": "PROJ-3", "repo": None, "reason": "needs_reviewer"}
    ]
    # With no place yet, a reader gets the newest alone; after it, nothing.
    assert read(capsys) == [kept[1]]
    assert read(capsys, "--after", str(kept[1]["id"])) == []


def test_reading_needs_a_mailbox_sink_and_refuses_inside_a_tick(
    canopy_env: CanopyEnv, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[notify.sinks.desk]\ncmd = 'x'\n")
    assert main(["notify", "read", "desk"]) != 0
    assert "no mailbox sink named 'desk'; configured: none" in capsys.readouterr().err
    with_mailbox(canopy_env)
    monkeypatch.setenv("CANOPY_TICK_ID", "1")
    assert main(["notify", "read", "remote"]) != 0
    assert "refuses inside a tick" in capsys.readouterr().err


def test_a_test_message_waits_in_the_mailbox(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    with_mailbox(canopy_env)
    assert main(["notify", "test", "remote"]) == 0
    assert "remote: delivered: kept in the mailbox" in capsys.readouterr().out
    [kept] = read(capsys)
    assert "canopy test message" in json.loads(str(kept["message"]))["events"][0]["line"]
    assert main(["status"]) == 0
    assert "1 kept in its mailbox" in capsys.readouterr().out


def test_kept_messages_go_after_a_week_or_with_their_sink(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_mailbox(canopy_env)
    conn = journal(canopy_env)
    old = db.format_time(datetime.now(UTC) - timedelta(days=8))
    conn.execute("INSERT INTO notify_mailbox (sink, at, message) VALUES ('remote', ?, 'old')", (old,))
    mailbox.put(conn, "remote", "new")
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick"]) == 0
    assert [m.message for m in mailbox.after(conn, "remote", 0)] == ["new"]

    canopy_env.write_user(canopy_env.user_file.read_text().replace(MAILBOX, ""))
    assert main(["tick"]) == 0
    assert mailbox.count(conn, "remote") == 0


# The web UI's route


@pytest.fixture
def backend(tmp_path: Path) -> Backend:
    return mock.seed(tmp_path / "mock")


def test_the_mailbox_route_needs_a_session_and_a_mailbox_sink(backend: Backend) -> None:
    opts = ServeOptions.model_validate({"ui_dir": None, "mock": True, "mock_event_seconds": None})
    sessions = Sessions(SECRET, port=opts.port, base_path="", hosts=opts.hosts)
    c = TestClient(create_app(opts, backend, sessions), base_url="http://127.0.0.1:8765")
    assert c.get("/api/mailbox/remote").status_code == 401
    assert c.post("/api/session", json={"secret": SECRET}).status_code == 200
    body = c.get("/api/mailbox/remote").json()
    [kept] = body["messages"]
    assert body["sink"] == "remote"
    assert "ABC-100" in kept["message"]
    assert c.get(f"/api/mailbox/remote?after={kept['id']}").json()["messages"] == []
    assert c.get("/api/mailbox/nope").status_code == 404
    assert c.get("/api/mailbox/remote?after=-1").status_code == 422


# The relay


@pytest.fixture
def local_sink(tmp_path: Path) -> tuple[Path, Path]:
    """A local sink command: appends what it reads on stdin, then a separator, to the first path, and exits with the
    number in the second if there is one."""
    out = tmp_path / "shown.txt"
    script = tmp_path / "show"
    script.write_text(
        f'#!/bin/sh\ncat >> {out}\necho "--" >> {out}\n'
        f'if [ -f {out}.exit ]; then echo "no display" >&2; exit "$(cat {out}.exit)"; fi\n'
    )
    script.chmod(0o755)
    return script, out


def shown(out: Path) -> list[str]:
    return out.read_text().split("--\n")[:-1] if out.exists() else []


@pytest.fixture
def fake_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`ssh` on PATH: records its argv as a JSON line, then runs the remote command here, as the other machine would."""
    calls = tmp_path / "ssh.jsonl"
    bin_dir = tmp_path / "ssh-bin"
    bin_dir.mkdir()
    tool = bin_dir / "ssh"
    tool.write_text(
        "#!/usr/bin/env python3\nimport json, subprocess, sys\n"
        f"open({str(calls)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "print('a shell startup file may print this')\n"
        "sys.stdout.flush()\n"
        "sys.exit(subprocess.run(['sh', '-c', sys.argv[-1]]).returncode)\n"
    )
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return calls


def test_the_relay_shows_each_message_once_over_ssh(
    canopy_env: CanopyEnv,
    fake_ssh: Path,
    local_sink: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with_mailbox(canopy_env)
    script, out = local_sink
    state = tmp_path / "relay-state"
    remote = f"cd {canopy_env.repo} && {sys.executable} -m canopy notify read"
    argv = ["--ssh", "devbox", "--remote-cmd", remote, "--state-file", str(state), "--once", "--", str(script)]

    assert relay.run(argv) == 0  # nothing kept yet
    assert shown(out) == []
    assert main(["notify", "test", "remote"]) == 0
    assert relay.run(argv) == 0
    [message] = shown(out)
    assert json.loads(message)["sink"] == "remote"
    assert relay.run(argv) == 0
    assert len(shown(out)) == 1

    conn = journal(canopy_env)
    mailbox.put(conn, "remote", "second")
    mailbox.put(conn, "remote", "third")
    assert relay.run(argv) == 0
    assert shown(out)[1:] == ["second", "third"]

    calls = [json.loads(line) for line in fake_ssh.read_text().splitlines()]
    assert calls[0] == ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "--", "devbox", f"{remote} remote"]
    assert calls[-1][-1] == f"{remote} remote --after 1"  # two after the test message: a short read, the end
    assert state.read_text() == "3\n"
    capsys.readouterr()


def test_a_failed_local_command_is_tried_again_and_a_stale_message_skipped(
    canopy_env: CanopyEnv, fake_ssh: Path, local_sink: tuple[Path, Path], tmp_path: Path
) -> None:
    with_mailbox(canopy_env)
    script, out = local_sink
    state = tmp_path / "relay-state"
    remote = f"cd {canopy_env.repo} && {sys.executable} -m canopy notify read"
    argv = ["--ssh", "devbox", "--remote-cmd", remote, "--state-file", str(state), "--once", "--", str(script)]
    conn = journal(canopy_env)
    first = mailbox.put(conn, "remote", "first")
    state.write_text(f"{first}\n")
    old = db.format_time(datetime.now(UTC) - timedelta(hours=30))
    conn.execute("INSERT INTO notify_mailbox (sink, at, message) VALUES ('remote', ?, 'stale')", (old,))
    mailbox.put(conn, "remote", "fresh")

    Path(f"{out}.exit").write_text("1")
    assert relay.run(argv) == 1
    assert shown(out) == ["fresh"]  # the stale one was skipped, the fresh one failed
    Path(f"{out}.exit").unlink()
    assert relay.run(argv) == 0
    assert shown(out) == ["fresh", "fresh"]
    assert relay.run(argv) == 0
    assert len(shown(out)) == 2


def test_the_relay_says_when_ssh_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ssh").write_text("#!/bin/sh\necho 'Permission denied (publickey).' >&2\nexit 255\n")
    (bin_dir / "ssh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    result = relay.poll(
        relay.Ssh("devbox", "canopy notify read", "remote"),
        tmp_path / "state",
        ["true"],
        max_age=timedelta(hours=24),
    )
    assert result.error == "ssh devbox exited 255: Permission denied (publickey)."


@pytest.fixture
def served(backend: Backend) -> Iterator[int]:
    """The mock journal behind a real listener with a secret, on a port the OS picks."""
    options = ServeOptions(ui_dir=None, mock=True, mock_event_seconds=None)
    sessions = Sessions(SECRET, port=options.port, base_path="", hosts=options.hosts)
    config = uvicorn.Config(create_app(options, backend, sessions), host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def secret_file(tmp_path: Path, value: str = SECRET, mode: int = 0o600) -> Path:
    path = tmp_path / "relay-secret"
    path.write_text(value + "\n")
    path.chmod(mode)
    return path


def test_the_relay_signs_in_and_reads_over_http(
    served: int, backend: Backend, local_sink: tuple[Path, Path], tmp_path: Path
) -> None:
    script, out = local_sink
    state = tmp_path / "relay-state"
    url, secret = f"http://127.0.0.1:{served}/", str(secret_file(tmp_path))
    argv = ["--url", url, "--secret-file", secret, "--state-file", str(state), "--once", str(script)]

    # A message two days old is skipped, but the relay's place moves past it.
    with backend.open() as ctx:
        old = db.format_time(datetime.now(UTC) - timedelta(days=2))
        ctx.conn.execute("UPDATE notify_mailbox SET at = ?", (old,))
    assert relay.run(argv) == 0
    assert shown(out) == []
    assert state.read_text().strip()
    with backend.open() as ctx:
        mailbox.put(ctx.conn, "remote", "now")
    assert relay.run(argv) == 0
    assert shown(out) == ["now"]


def test_the_relay_over_http_needs_the_right_secret_in_a_private_file(served: int, tmp_path: Path) -> None:
    url = f"http://127.0.0.1:{served}"
    state = ["--state-file", str(tmp_path / "state"), "--once", "true"]
    open_file = secret_file(tmp_path, mode=0o644)
    assert relay.run(["--url", url, "--secret-file", str(open_file), *state]) == 2
    wrong = secret_file(tmp_path, value="y" * 40)
    source = relay.Http(url, wrong, "remote")
    with pytest.raises(relay.ReadError, match="refused the secret"):
        source.read(None)
    right = secret_file(tmp_path)
    with pytest.raises(relay.ReadError, match="no mailbox sink named 'desk'"):
        relay.Http(url, right, "desk").read(None)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--url", "ftp://host"], "must be http:// or https://"),
        (["--url", "http://user@host"], "must not carry a user"),
        (["--ssh=-oProxyCommand=x"], "must be a host"),
        (["--ssh", "devbox", "--sink", "Remote; rm"], "--sink"),
        (["--ssh", "devbox", "--every", "1"], "--every"),
    ],
)
def test_the_relay_checks_its_arguments(
    args: list[str], message: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert relay.run([*args, "--state-file", str(tmp_path / "state"), "--once"]) == 2
    assert message in capsys.readouterr().err


def test_plain_http_off_this_machine_is_warned_about(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state-home"))
    assert relay.check_url("http://127.0.0.1:8765/") == ("http://127.0.0.1:8765", False)
    assert relay.check_url("http://[::1]:8765") == ("http://[::1]:8765", False)
    assert relay.check_url("http://10.0.0.5:8765") == ("http://10.0.0.5:8765", True)
    assert relay.check_url("https://devbox.internal") == ("https://devbox.internal", False)
    setup = relay.setup(["--url", "http://10.0.0.5:8765", "--secret-file", str(secret_file(tmp_path))])
    assert setup.warning is not None
    assert "plain HTTP" in setup.warning
    assert setup.command == relay.DEFAULT_COMMAND
    assert setup.state_file.name == "remote@10.0.0.5_8765"
