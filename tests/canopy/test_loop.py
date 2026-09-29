"""`canopy loop`: ticks in a row with a wait between them, against the fake treehouse and a fake overseer.

The wait runs on a fake clock, so no test sleeps. Signals are real: the tests and the fake overseer send SIGINT to this
process, and `repeat.signals` handles it as it would a Ctrl-C.
"""

import io
import json
import os
import signal
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import override

import pytest
from rich.console import Console

from canopy.cli.main import main
from canopy.core import config, db
from canopy.core.context import Context
from canopy.infra import lock, logs, procs
from canopy.loop import repeat
from tests.conftest import CanopyEnv


@dataclass
class FakeTime:
    """A monotonic clock that only `sleep` moves. `on_sleep` runs after each sleep, to act during the wait."""

    now: float = 0.0
    slept: list[float] = field(default_factory=list)
    woke: list[float] = field(default_factory=list)  # the clock after each sleep
    on_sleep: Callable[[], None] | None = None

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        self.woke.append(self.now)
        if self.on_sleep is not None:
            self.on_sleep()


@dataclass
class RaisingRunner:
    """Raises a plain RuntimeError, the kind no tick code expects, on the first `raises` runs; then runs for real."""

    raises: int = 1

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,
    ) -> procs.Result:
        if self.raises:
            self.raises -= 1
            raise RuntimeError("a bug in tick code")
        return procs.SubprocessRunner().run(args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        return procs.SubprocessRunner().spawn(args, cwd=cwd, log_path=log_path)


def context(env: CanopyEnv, runner: procs.Runner | None = None) -> Context:
    cfg = config.load(env.repo, env.user_file)
    cfg.paths.state_dir.mkdir(parents=True, exist_ok=True)
    logs.configure(cfg.paths.state_dir)
    conn = db.connect(env.state_dir / db.DB_FILE_NAME)
    return Context(config=cfg, repo_root=env.repo, conn=conn, runner=runner or procs.SubprocessRunner())


def overseer_does(monkeypatch: pytest.MonkeyPatch, *commands: list[str]) -> None:
    monkeypatch.setenv("FAKE_OVERSEER_COMMANDS", json.dumps(commands))
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")


def canopy(*args: str) -> list[str]:
    return ["canopy", *args]


def interrupt_me() -> list[str]:
    """A command that sends SIGINT to this test process, the way a Ctrl-C at the terminal would."""
    return [sys.executable, "-c", f"import os, signal; os.kill({os.getpid()}, signal.SIGINT)"]


def console() -> tuple[Console, io.StringIO]:
    out = io.StringIO()
    return Console(file=out, width=200, highlight=False), out


def tick_statuses(env: CanopyEnv) -> list[str]:
    conn = db.connect(env.state_dir / db.DB_FILE_NAME)
    return [str(r["status"]) for r in conn.execute("SELECT status FROM ticks ORDER BY id")]


def test_loop_waits_the_interval_after_each_tick_and_reports_what_changed(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(
        monkeypatch,
        canopy("decide", "PROJ-1", "wait", "--rationale", "checks pending"),
        canopy("dispatch", "PROJ-2", "--label", "agent-ready-tester", "--kind", "implement", "--slug", "login"),
        canopy("attention", "PROJ-3", "needs_reviewer", "--detail", "https://example.test/pr/3"),
    )
    time = FakeTime()
    # Between the ticks, the reviewer approves PROJ-3: the second tick's overseer no longer lists it.
    time.on_sleep = lambda: overseer_does(monkeypatch, canopy("decide", "PROJ-3", "wait", "--rationale", "approved"))
    term, out = console()

    statuses = repeat.run(
        context(canopy_env),
        dry_run=True,
        interval_minutes=5,
        max_ticks=2,
        console=term,
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )

    assert statuses == {"ok": 2}
    assert tick_statuses(canopy_env) == ["ok", "ok"]
    assert sum(time.slept) == 300  # one wait, between the two ticks, and none after the last
    assert max(time.slept) <= 0.5  # the wait wakes often enough to notice a stop
    text = out.getvalue()
    assert "canopy loop" in text
    assert "wait 5 minutes after each tick ends" in text
    assert "dry run: the overseer plans, nothing is dispatched" in text
    tick1, tick2 = text.split("tick 1  ok")[1].split("tick 2  ok")
    assert "PROJ-2  dispatch:implement  dry run: not dispatched; would work on agent/PROJ-2-login" in tick1
    assert "+   PROJ-3  needs_reviewer      https://example.test/pr/3" in tick1
    assert "attention 1  ·  next tick at" in tick1
    assert "checks pending" not in text  # waits are counted in the summary, not listed
    assert "-   PROJ-3  needs_reviewer  resolved" in tick2
    assert "attention 0" in tick2
    assert "next tick" not in tick2
    assert "stopped after 2 ticks: ok=2" in tick2


def test_a_narrow_terminal_shortens_only_the_rationale(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = "docs-readme-add-troubleshooting-section"
    overseer_does(
        monkeypatch,
        canopy("dispatch", "PROJ-2", "--label", "agent-ready-tester", "--kind", "implement", "--slug", slug),
        canopy("attention", "PROJ-3", "needs_reviewer", "--detail", "https://example.test/pr/3/" + "x" * 80),
    )
    time = FakeTime()
    time.on_sleep = lambda: overseer_does(monkeypatch, canopy("decide", "PROJ-3", "wait", "--rationale", "approved"))
    out = io.StringIO()
    term = Console(file=out, width=80, highlight=False)

    repeat.run(
        context(canopy_env),
        dry_run=True,
        interval_minutes=1,
        max_ticks=2,
        console=term,
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )

    text = out.getvalue()
    assert all(len(line) <= 80 for line in text.splitlines())
    tick1, tick2 = text.split("tick 1  ok")[1].split("tick 2  ok")
    assert "    PROJ-2  dispatch:implement  dry run: not dispatched; would work on" in tick1
    assert slug not in tick1  # the rationale is what gives way
    assert "…" in tick1
    assert "+   PROJ-3  needs_reviewer      https://example.test/pr/3/" in tick1
    assert "-   PROJ-3  needs_reviewer  resolved" in tick2


class SlowOutput(io.StringIO):
    """Output that takes a second of fake time per write, and notes when tick 1's report line was written."""

    def __init__(self, time: FakeTime) -> None:
        super().__init__()
        self.time = time
        self.written_at: dict[str, float] = {}

    @override
    def write(self, s: str, /) -> int:
        if "tick 1  " in s:
            self.written_at.setdefault("tick 1", self.time.now)
        self.time.now += 1
        return super().write(s)


def test_the_wait_runs_from_the_end_of_the_tick_not_the_end_of_its_report(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(monkeypatch, canopy("attention", "PROJ-3", "needs_reviewer", "--detail", "https://example.test/3"))
    time = FakeTime()
    out = SlowOutput(time=time)
    repeat.run(
        context(canopy_env),
        dry_run=True,
        interval_minutes=5,
        max_ticks=2,
        console=Console(file=out, width=200, highlight=False),
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )
    # Tick 1 ended just before its report line was written. Printing the rest of the report took fake time, and the
    # wait still ends exactly the interval after the tick did.
    assert time.woke[-1] == out.written_at["tick 1"] + 300


def test_the_overseer_text_is_printed_as_text_not_rich_markup(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(
        monkeypatch,
        canopy("decide", "PROJ-1", "done", "--rationale", "merged [/oops] [red]not red[/red] :fire:"),
        canopy("attention", "PROJ-2", "needs_reviewer", "--detail", "[link=https://evil.test]click[/link]"),
    )
    term, out = console()
    repeat.run(context(canopy_env), dry_run=True, interval_minutes=1, max_ticks=1, console=term, stop=repeat.Stop())
    assert "merged [/oops] [red]not red[/red] :fire:" in out.getvalue()
    assert "[link=https://evil.test]click[/link]" in out.getvalue()


def test_loop_holds_its_own_lock_and_a_second_loop_is_refused(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with lock.hold(canopy_env.state_dir / repeat.LOCK_FILE_NAME):
        assert main(["loop", "--ticks", "1"]) == 1
    assert "another canopy loop is running" in capsys.readouterr().err
    assert not agent_log.exists()  # no tick ran

    overseer_does(monkeypatch)  # records nothing, ends with "tick complete"
    assert main(["loop", "--dry-run", "--ticks", "1", "--every", "3"]) == 0
    out = capsys.readouterr().out
    assert "wait 3 minutes after each tick ends" in out
    assert "tick 1  ok" in out
    assert "stopped after 1 tick: ok=1" in out
    assert tick_statuses(canopy_env) == ["ok"]


def test_ctrl_c_during_the_wait_stops_the_loop_without_another_tick(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(monkeypatch)
    time = FakeTime(on_sleep=lambda: os.kill(os.getpid(), signal.SIGINT))
    term, out = console()
    stop = repeat.Stop()
    with repeat.signals(stop):
        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=15,
            max_ticks=None,
            console=term,
            stop=stop,
            sleep=time.sleep,
            clock=time.clock,
        )
    assert statuses == {"ok": 1}
    assert len(time.slept) == 1
    assert "stopped after 1 tick" in out.getvalue()
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler  # restored


def test_ctrl_c_during_a_tick_lets_it_finish_then_stops(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(
        monkeypatch,
        interrupt_me(),
        canopy("decide", "PROJ-1", "done", "--rationale", "merged"),
    )
    time = FakeTime()
    term, _ = console()
    stop = repeat.Stop()
    with repeat.signals(stop):
        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=15,
            max_ticks=None,
            console=term,
            stop=stop,
            sleep=time.sleep,
            clock=time.clock,
        )
    assert statuses == {"ok": 1}
    assert time.slept == []  # stopped without waiting
    assert tick_statuses(canopy_env) == ["ok"]
    conn = db.connect(canopy_env.state_dir / db.DB_FILE_NAME)
    assert [str(d["action"]) for d in db.decisions_for_tick(conn, 1)] == ["done"]  # the overseer ran to its end


def seconds_apart(seconds: float) -> Callable[[], float]:
    """A clock for `repeat.signals` that moves on by `seconds` each time it is read: one read per signal."""
    now = [0.0]

    def clock() -> float:
        now[0] += seconds
        return now[0]

    return clock


def test_a_second_ctrl_c_aborts_the_tick_and_the_next_tick_closes_it(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(monkeypatch, interrupt_me(), interrupt_me(), canopy("decide", "PROJ-1", "done", "--rationale", "x"))
    term, _ = console()
    stop = repeat.Stop()
    clock = seconds_apart(repeat.SAME_SIGNAL_SECONDS + 0.5)
    with repeat.signals(stop, clock=clock), pytest.raises(KeyboardInterrupt):
        repeat.run(context(canopy_env), dry_run=True, interval_minutes=15, max_ticks=None, console=term, stop=stop)
    assert tick_statuses(canopy_env) == ["running"]

    overseer_does(monkeypatch)
    assert main(["tick", "--dry-run"]) == 0  # both locks were released
    assert tick_statuses(canopy_env) == ["abandoned", "ok"]


def test_two_signals_from_one_ctrl_c_let_the_tick_finish(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under `uv run`, one Ctrl-C reaches canopy twice: from the terminal, then forwarded by uv about 200 ms later."""
    overseer_does(monkeypatch, interrupt_me(), interrupt_me(), canopy("decide", "PROJ-1", "done", "--rationale", "x"))
    term, _ = console()
    stop = repeat.Stop()
    with repeat.signals(stop, clock=seconds_apart(0.2)):
        statuses = repeat.run(
            context(canopy_env), dry_run=True, interval_minutes=15, max_ticks=None, console=term, stop=stop
        )
    assert statuses == {"ok": 1}
    conn = db.connect(canopy_env.state_dir / db.DB_FILE_NAME)
    assert [str(d["action"]) for d in db.decisions_for_tick(conn, 1)] == ["done"]  # the overseer ran to its end


@pytest.mark.parametrize(
    ("gap", "aborts"),
    [(0.0, False), (repeat.SAME_SIGNAL_SECONDS - 0.01, False), (repeat.SAME_SIGNAL_SECONDS, True), (60.0, True)],
)
def test_a_second_signal_aborts_only_after_the_window(gap: float, aborts: bool) -> None:  # noqa: FBT001
    stop = repeat.Stop()
    with repeat.signals(stop, clock=seconds_apart(gap)):
        os.kill(os.getpid(), signal.SIGTERM)
        assert stop.requested
        if aborts:
            with pytest.raises(KeyboardInterrupt):
                os.kill(os.getpid(), signal.SIGINT)
        else:
            os.kill(os.getpid(), signal.SIGINT)
    assert stop.requested


def test_a_tick_that_raises_ends_that_tick_not_the_loop(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(monkeypatch)
    time = FakeTime()
    term, out = console()
    statuses = repeat.run(
        context(canopy_env, RaisingRunner()),
        dry_run=True,
        interval_minutes=1,
        max_ticks=2,
        console=term,
        stop=repeat.Stop(),
        sleep=time.sleep,
        clock=time.clock,
    )
    assert statuses == {"error": 1, "ok": 1}
    assert "tick  error" in out.getvalue()
    assert "RuntimeError: a bug in tick code" in out.getvalue()
    # The raising tick left its row running; the next one closed it.
    assert tick_statuses(canopy_env) == ["abandoned", "ok"]
    log_lines = [json.loads(line) for line in (canopy_env.state_dir / "canopy.log").read_text().splitlines()]
    assert any(line["msg"] == "tick raised; the loop goes on" and "exc" in line for line in log_lines)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (44.6, "45s"), (60, "1m 00s"), (185, "3m 05s"), (7800, "2h 10m"), (-3, "0s")],
)
def test_duration(seconds: float, text: str) -> None:
    assert repeat.duration(seconds) == text
