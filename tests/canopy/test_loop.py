"""`canopy loop`: ticks in a row with a wait between them, against the fake treehouse and a fake overseer.

The wait runs on a fake clock, so no test sleeps. Signals are real: the tests and the fake overseer send SIGINT to this
process, and `repeat.signals` handles it as it would a Ctrl-C.
"""

import contextlib
import io
import json
import os
import signal
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import override
from unittest import mock

import pytest
from rich.console import Console

from canopy.cli.main import main
from canopy.core import conversation, db, pause
from canopy.core.vocab import TickStatus
from canopy.infra import lock, procs, resources
from canopy.loop import repeat, reread
from tests.canopy.helpers import FakeKeys, FakeTime, canopy, console, context, overseer_does, with_events
from tests.conftest import CanopyEnv, user_toml


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
        on_line: Callable[[str], None] | None = None,
    ) -> procs.Result:
        if self.raises:
            self.raises -= 1
            raise RuntimeError("a bug in tick code")
        return procs.SubprocessRunner().run(
            args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start, on_line=on_line
        )

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        return procs.SubprocessRunner().spawn(args, cwd=cwd, log_path=log_path)


def interrupt_me() -> list[str]:
    """A command that sends SIGINT to this test process, the way a Ctrl-C at the terminal would."""
    return [sys.executable, "-c", f"import os, signal; os.kill({os.getpid()}, signal.SIGINT)"]


def woken_by(env: CanopyEnv) -> list[str | None]:
    """What started each tick, as its row records it (`ticks.woken_by`)."""
    conn = env.journal(migrate=False)
    return [r["woken_by"] for r in conn.execute("SELECT woken_by FROM ticks ORDER BY id")]


def tick_statuses(env: CanopyEnv) -> list[str]:
    conn = env.journal(migrate=False)
    return [str(r["status"]) for r in conn.execute("SELECT status FROM ticks ORDER BY id")]


def test_loop_waits_the_interval_after_each_tick_and_reports_what_changed(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with (
        overseer_does(
            canopy("decide", "PROJ-1", "wait", "--rationale", "checks pending"),
            canopy(
                "dispatch",
                "PROJ-2",
                "--repo",
                "repo",
                "--label",
                "agent-ready-tester",
                "--kind",
                "implement",
                "--slug",
                "login",
            ),
            canopy("attention", "PROJ-3", "needs_reviewer", "--detail", "https://example.test/pr/3"),
        ),
        contextlib.ExitStack() as later,
    ):
        time = FakeTime()
        # Between the ticks, the reviewer approves PROJ-3: the second tick's overseer no longer lists it.
        second = (
            canopy("decide", "PROJ-1", "wait", "--rationale", "checks pending"),
            canopy("decide", "PROJ-2", "wait", "--rationale", "would be running"),
            canopy("decide", "PROJ-3", "wait", "--rationale", "approved"),
        )
        time.on_sleep = lambda: later.enter_context(overseer_does(*second)) if len(time.slept) == 1 else None
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
        assert "attention 1  ·  next tick in 5m at" in tick1
        assert "checks pending" not in text  # waits are counted in the summary, not listed
        assert "-   PROJ-3  needs_reviewer  resolved" in tick2
        assert "attention 0" in tick2
        assert "next tick" not in tick2
        assert "stopped after 2 ticks: ok=2" in tick2


def test_each_tick_block_shows_what_its_overseer_cost(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with_events(canopy_env, "canopy-overseer")
    with overseer_does(), contextlib.ExitStack() as later:
        # The second tick's overseer reports a cost that does not validate: it reports none, so there is none to show.
        time = FakeTime()
        time.on_sleep = lambda: (
            later.enter_context(overseer_does(step_cost='"a lot"')) if len(time.slept) == 1 else None
        )
        term, out = console()

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

        tick1, tick2 = out.getvalue().split("tick 1  ok")[1].split("tick 2  ok")
        assert "attention 0  ·  cost $0.25, 3.5k tokens, 5.5k peak context  ·  next tick in 1m at" in tick1
        assert "cost" not in tick2


def test_a_narrow_terminal_shortens_only_the_rationale(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    slug = "docs-readme-add-troubleshooting-section"
    with (
        overseer_does(
            canopy(
                "dispatch",
                "PROJ-2",
                "--repo",
                "repo",
                "--label",
                "agent-ready-tester",
                "--kind",
                "implement",
                "--slug",
                slug,
            ),
            canopy("attention", "PROJ-3", "needs_reviewer", "--detail", "https://example.test/pr/3/" + "x" * 80),
        ),
        contextlib.ExitStack() as later,
    ):
        time = FakeTime()
        second = (
            canopy("decide", "PROJ-2", "wait", "--rationale", "would be running"),
            canopy("decide", "PROJ-3", "wait", "--rationale", "approved"),
        )
        time.on_sleep = lambda: later.enter_context(overseer_does(*second)) if len(time.slept) == 1 else None
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
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does(canopy("attention", "PROJ-3", "needs_reviewer", "--detail", "https://example.test/3")):
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


def test_the_footer_counts_running_reviews_as_workers(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    conn = canopy_env.journal()
    tick_id = db.start_tick(conn, dry_run=True)
    db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    run_id = db.insert_review_run(
        conn,
        tick_id=tick_id,
        pr_url="https://example.test/pr/1",
        sha="a" * 40,
        ticket=None,
        repo=None,
        purpose="query",
        logs_dir=canopy_env.state_dir,
    )
    assert db.claim_run(conn, "review_runs", run_id, os.getpid())  # alive, so reconcile leaves it running
    with overseer_does():
        term, out = console()
        repeat.run(context(canopy_env), dry_run=True, interval_minutes=1, max_ticks=1, console=term, stop=repeat.Stop())
        assert "workers 1/" in out.getvalue()


def test_the_overseer_text_is_printed_as_text_not_rich_markup(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does(
        canopy("decide", "PROJ-1", "done", "--rationale", "merged [/oops] [red]not red[/red] :fire:"),
        canopy("attention", "PROJ-2", "needs_reviewer", "--detail", "[link=https://evil.test]click[/link]"),
    ):
        term, out = console()
        repeat.run(context(canopy_env), dry_run=True, interval_minutes=1, max_ticks=1, console=term, stop=repeat.Stop())
        assert "merged [/oops] [red]not red[/red] :fire:" in out.getvalue()
        assert "[link=https://evil.test]click[/link]" in out.getvalue()


def test_loop_holds_its_own_lock_and_a_second_loop_is_refused(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with lock.hold(canopy_env.state_dir / repeat.LOCK_FILE_NAME):
        assert main(["loop", "--ticks", "1"]) == 1
    assert "another canopy loop is running" in capsys.readouterr().err
    assert not agent_log.exists()  # no tick ran

    with overseer_does():  # records nothing, ends with "CANOPY_TICK_DONE"
        assert main(["loop", "--dry-run", "--ticks", "1", "--every", "3"]) == 0
        out = capsys.readouterr().out
        assert "wait 3 minutes after each tick ends" in out
        assert "tick 1  ok" in out
        assert "stopped after 1 tick: ok=1" in out
        assert tick_statuses(canopy_env) == ["ok"]


def test_ctrl_c_during_the_wait_stops_the_loop_without_another_tick(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
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
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does(
        interrupt_me(),
        canopy("decide", "PROJ-1", "done", "--rationale", "merged"),
    ):
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
        conn = canopy_env.journal(migrate=False)
        assert [d.action for d in db.decisions_for_tick(conn, 1)] == ["queried", "done"]  # the overseer ran to its end


def seconds_apart(seconds: float) -> Callable[[], float]:
    """A clock for `repeat.signals` that moves on by `seconds` each time it is read: one read per signal."""
    now = [0.0]

    def clock() -> float:
        now[0] += seconds
        return now[0]

    return clock


def test_a_second_ctrl_c_aborts_the_tick_and_the_next_tick_closes_it(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does(interrupt_me(), interrupt_me(), canopy("decide", "PROJ-1", "done", "--rationale", "x")):
        term, _ = console()
        stop = repeat.Stop()
        clock = seconds_apart(repeat.SAME_SIGNAL_SECONDS + 0.5)
        with repeat.signals(stop, clock=clock), pytest.raises(KeyboardInterrupt):
            repeat.run(context(canopy_env), dry_run=True, interval_minutes=15, max_ticks=None, console=term, stop=stop)
        assert tick_statuses(canopy_env) == ["running"]

    with overseer_does():
        assert main(["tick", "--dry-run"]) == 0  # both locks were released
        assert tick_statuses(canopy_env) == ["abandoned", "ok"]


def test_two_signals_from_one_ctrl_c_let_the_tick_finish(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    """Under `uv run`, one Ctrl-C reaches canopy twice: from the terminal, then forwarded by uv about 200 ms later."""
    with overseer_does(interrupt_me(), interrupt_me(), canopy("decide", "PROJ-1", "done", "--rationale", "x")):
        term, _ = console()
        stop = repeat.Stop()
        with repeat.signals(stop, clock=seconds_apart(0.2)):
            statuses = repeat.run(
                context(canopy_env), dry_run=True, interval_minutes=15, max_ticks=None, console=term, stop=stop
            )
        assert statuses == {"ok": 1}
        conn = canopy_env.journal(migrate=False)
        assert [d.action for d in db.decisions_for_tick(conn, 1)] == ["queried", "done"]  # the overseer ran to its end


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
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
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


def test_the_tick_now_key_ends_the_wait_at_once(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    with overseer_does():
        keys = FakeKeys()
        # Typed during the first tick: not meant for the wait that follows it, so it is dropped.
        keys.type(repeat.TICK_NOW_KEY)
        time = FakeTime()
        # Another key first, then the tick-now key in capitals, as with Caps Lock on.
        time.on_sleep = lambda: keys.type("x" if len(time.slept) == 1 else repeat.TICK_NOW_KEY.upper())
        term, out = console()

        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=15,
            max_ticks=2,
            console=term,
            stop=repeat.Stop(),
            keys=keys.pressed,
            sleep=time.sleep,
            clock=time.clock,
        )

        assert statuses == {"ok": 2}
        # Two steps of the wait, then the second tick: no one-minute floor, unlike an operator message.
        assert time.slept == [0.5, 0.5]
        assert (
            f"Press {repeat.TICK_NOW_KEY} during the wait to tick now, {repeat.PAUSE_KEY} to pause or resume."
            in out.getvalue()
        )
        log_lines = [json.loads(line) for line in (canopy_env.state_dir / "canopy.log").read_text().splitlines()]
        assert any(line["msg"] == "the operator asked for a tick now" for line in log_lines)
        assert woken_by(canopy_env) == ["start", "key"]


def test_without_keys_the_loop_does_not_offer_them(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        time = FakeTime()
        term, out = console()
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
        assert sum(time.slept) == 60
        assert "tick now" not in out.getvalue()


def deferred(
    env: CanopyEnv, time: FakeTime, keys: FakeKeys | None = None, stop: repeat.Stop | None = None
) -> tuple[Counter[str], str]:
    """One tick, the first deferred ten minutes, on `time`'s clock."""
    term, out = console()
    statuses = repeat.run(
        context(env),
        dry_run=True,
        interval_minutes=15,
        max_ticks=1,
        console=term,
        stop=stop or repeat.Stop(),
        keys=keys.pressed if keys is not None else None,
        defer_minutes=10,
        sleep=time.sleep,
        clock=time.clock,
    )
    return statuses, out.getvalue()


def test_a_deferred_start_waits_before_the_first_tick(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        ticked: list[bool] = []
        time = FakeTime(on_sleep=lambda: ticked.append(agent_log.exists()))

        statuses, text = deferred(canopy_env, time)

        assert statuses == {"ok": 1}
        assert sum(time.slept) == 600  # the deferral, and no wait after the only tick
        assert not any(ticked)  # the overseer ran after the wait, not before it
        assert "first tick  in 10m at" in text
        assert text.index("first tick") < text.index("tick 1  ok")
        log_lines = [json.loads(line) for line in (canopy_env.state_dir / "canopy.log").read_text().splitlines()]
        assert any(line["msg"] == "loop defers its first tick" and line["wait_seconds"] == 600 for line in log_lines)
        assert woken_by(canopy_env) == ["start"]


def test_the_tick_now_key_ends_a_deferred_start(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    with overseer_does():
        keys = FakeKeys()
        time = FakeTime(on_sleep=lambda: keys.type(repeat.TICK_NOW_KEY))
        statuses, _ = deferred(canopy_env, time, keys)
        assert statuses == {"ok": 1}
        assert time.slept == [0.5]
        assert woken_by(canopy_env) == ["key"]


def test_an_operator_message_ends_a_deferred_start_after_a_minute(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does(canopy("decide", "PROJ-1", "wait", "--rationale", "answered the operator")):
        ctx = context(canopy_env)
        db.migrate(ctx.conn, resources.migrations_dir())
        db.touch_ticket(ctx.conn, "PROJ-1", "/r")
        time = FakeTime()

        def reply_once() -> None:
            if len(time.slept) == 1:
                assert main(["reply", "PROJ-1", "Go ahead."]) == 0

        time.on_sleep = reply_once
        statuses, _ = deferred(canopy_env, time)
        assert statuses == {"ok": 1}
        assert sum(time.slept) == pytest.approx(60)  # loop.min_gap_minutes, by default
        assert woken_by(canopy_env) == ["message"]


def test_ctrl_c_during_a_deferred_start_stops_without_a_tick(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        time = FakeTime(on_sleep=lambda: os.kill(os.getpid(), signal.SIGINT))
        stop = repeat.Stop()
        with repeat.signals(stop):
            statuses, text = deferred(canopy_env, time, stop=stop)
        assert statuses == Counter()
        assert len(time.slept) == 1
        assert not agent_log.exists()
        assert "stopped after 0 ticks: none" in text


def test_loop_passes_defer_through(canopy_env: CanopyEnv) -> None:
    with mock.patch.object(repeat, "run", autospec=True, return_value=Counter()) as run:
        assert main(["loop", "--defer", "30", "--no-serve"]) == 0
        seen = run.call_args.kwargs
        assert seen["defer_minutes"] == 30
        assert seen["interval_minutes"] is None  # left to loop.interval_minutes, which a reload reads again
        assert isinstance(seen["reload"], reread.Reload)
        assert main(["loop", "--every", "7", "--no-serve"]) == 0
        assert run.call_args.kwargs["interval_minutes"] == 7
        assert main(["loop", "--defer", "0"]) == 2  # at least a minute; to tick at once, leave it out


def log_messages(env: CanopyEnv) -> list[dict[str, object]]:
    return [json.loads(line) for line in (env.state_dir / "canopy.log").read_text().splitlines()]


def paused(env: CanopyEnv) -> pause.Paused | None:
    return pause.paused(env.journal(migrate=False))


def test_the_pause_key_holds_the_wait_past_its_deadline_until_pressed_again(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        keys = FakeKeys()
        time = FakeTime()
        ticks_seen: list[int] = []

        def operator() -> None:
            ticks_seen.append(len(tick_statuses(canopy_env)))
            if len(time.slept) == 1:
                keys.type(repeat.PAUSE_KEY)
            elif len(time.slept) == 400:  # 200 seconds in, well past the one-minute wait's deadline
                keys.type(repeat.PAUSE_KEY.upper())

        time.on_sleep = operator
        term, out = console()
        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=1,
            max_ticks=2,
            console=term,
            stop=repeat.Stop(),
            keys=keys.pressed,
            sleep=time.sleep,
            clock=time.clock,
        )

        assert statuses == {"ok": 2}
        # Held until resumed, then the second tick at once: the deadline had passed.
        assert sum(time.slept) == 200
        assert set(ticks_seen) == {1}
        assert paused(canopy_env) is None
        # The wait ran past its deadline: the pause does not change what the row says ended it.
        assert woken_by(canopy_env) == ["start", "timer"]
        lines = [(line["msg"], line.get("channel")) for line in log_messages(canopy_env)]
        assert ("loop paused", "loop") in lines
        assert ("loop resumed", "loop") in lines
        assert f"{repeat.PAUSE_KEY} to pause or resume" in out.getvalue()


def test_a_pause_key_pressed_during_a_tick_holds_the_next_one(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        keys = FakeKeys()
        keys.type(repeat.PAUSE_KEY)  # read when the first tick ends, unlike the tick-now key
        time = FakeTime()

        def resume_from_the_shell() -> None:
            if len(time.slept) == 10:
                assert main(["resume"]) == 0

        time.on_sleep = resume_from_the_shell
        term, out = console()
        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=15,
            max_ticks=2,
            console=term,
            stop=repeat.Stop(),
            keys=keys.pressed,
            sleep=time.sleep,
            clock=time.clock,
        )

        assert statuses == {"ok": 2}
        # Resumed five seconds in, before the deadline: the wait then runs out as it would have.
        assert sum(time.slept) == 15 * 60
        assert "attention 0  ·  paused: no tick until resumed" in out.getvalue()


def test_a_loop_started_paused_holds_its_first_tick_until_resumed(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        assert main(["pause"]) == 0
        ran: list[bool] = []
        time = FakeTime()

        def resume_later() -> None:
            ran.append(agent_log.exists())
            if len(time.slept) == 3:
                assert main(["resume"]) == 0

        time.on_sleep = resume_later
        term, out = console()
        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=15,
            max_ticks=1,
            console=term,
            stop=repeat.Stop(),
            sleep=time.sleep,
            clock=time.clock,
        )

        assert statuses == {"ok": 1}
        assert time.slept == [0.5, 0.5, 0.5]
        assert not any(ran)  # no overseer ran while paused
        assert woken_by(canopy_env) == ["start"]
        assert "no tick until resumed" in out.getvalue().split("tick 1  ok")[0]  # the header says so
        assert ("loop resumed", "cli") in [(line["msg"], line.get("channel")) for line in log_messages(canopy_env)]


def test_the_tick_now_key_ticks_once_while_paused_and_the_loop_stays_paused(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        assert main(["pause"]) == 0
        keys = FakeKeys()
        time = FakeTime(on_sleep=lambda: keys.type(repeat.TICK_NOW_KEY) if len(time.slept) == 2 else None)
        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=15,
            max_ticks=1,
            console=console()[0],
            stop=repeat.Stop(),
            keys=keys.pressed,
            sleep=time.sleep,
            clock=time.clock,
        )
        assert statuses == {"ok": 1}
        assert time.slept == [0.5, 0.5]
        held = paused(canopy_env)
        assert held is not None
        assert held.channel == "cli"
        assert woken_by(canopy_env) == ["key"]


def test_ctrl_c_while_paused_stops_the_loop_without_a_tick(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        assert main(["pause"]) == 0
        time = FakeTime(on_sleep=lambda: os.kill(os.getpid(), signal.SIGINT))
        stop = repeat.Stop()
        term, out = console()
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
        assert statuses == Counter()
        assert not agent_log.exists()
        assert "stopped after 0 ticks: none" in out.getvalue()


def test_canopy_pause_and_resume_say_what_they_did_and_status_shows_the_pause(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["resume"]) == 0
    assert "The loop was not paused." in capsys.readouterr().out
    assert main(["pause"]) == 0
    assert "Paused: the loop starts no tick until `canopy resume`." in capsys.readouterr().out
    assert main(["pause"]) == 0
    assert "The loop was already paused 0s ago (cli)." in capsys.readouterr().out
    assert main(["status"]) == 0
    assert "Loop paused " in capsys.readouterr().out
    assert main(["resume"]) == 0
    assert "Resumed" in capsys.readouterr().out
    assert main(["status"]) == 0
    assert "Loop paused" not in capsys.readouterr().out


@pytest.mark.parametrize("env", [conversation.TICK_ID_ENV, conversation.RUN_ID_ENV])
@pytest.mark.parametrize("verb", ["pause", "resume"])
def test_an_agent_can_neither_pause_nor_resume_the_loop(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str], env: str, verb: str
) -> None:
    if verb == "resume":
        assert main(["pause"]) == 0
    before = paused(canopy_env) if verb == "resume" else None
    with mock.patch.dict(os.environ, {env: "3"}):
        assert main([verb]) == 1
        assert f"{verb} refused (inside_run)" in capsys.readouterr().err
        if verb == "resume":
            assert paused(canopy_env) == before


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (44.6, "45s"), (60, "1m"), (185, "3m 05s"), (3600, "1h"), (7800, "2h 10m"), (-3, "0s")],
)
def test_duration(seconds: float, text: str) -> None:
    assert repeat.duration(seconds) == text


def hup_me() -> list[str]:
    """A command that sends SIGHUP to this test process, as `kill -HUP` from the operator's shell would."""
    return [sys.executable, "-c", f"import os, signal; os.kill({os.getpid()}, signal.SIGHUP)"]


def paced(env: CanopyEnv, minutes: int) -> None:
    """Write the user config with `loop.interval_minutes` at `minutes`, and idle pacing off."""
    env.write_user(user_toml() + f"\n[loop]\ninterval_minutes = {minutes}\nidle_max_minutes = {minutes}\n")


@dataclass
class Asked(reread.Reload):
    """A reload request that records whether a tick was running each time one was asked for."""

    during_tick: list[bool] = field(default_factory=list)

    @override
    def request(self) -> bool:
        self.during_tick.append(self.ticking)
        return super().request()


def test_sighup_during_the_wait_reads_the_config_again_for_the_waits_after_it(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    paced(canopy_env, 10)
    with overseer_does():
        stop, reload = repeat.Stop(), Asked()
        before = signal.getsignal(signal.SIGHUP)

        def change_then_hup() -> None:
            if not reload.during_tick:
                paced(canopy_env, 4)
                os.kill(os.getpid(), signal.SIGHUP)

        time = FakeTime(on_sleep=change_then_hup)
        term, out = console()
        with repeat.signals(stop, reload):
            statuses = repeat.run(
                context(canopy_env),
                dry_run=True,
                interval_minutes=None,
                max_ticks=3,
                console=term,
                stop=stop,
                reload=reload,
                sleep=time.sleep,
                clock=time.clock,
            )

        assert statuses == {"ok": 3}
        assert reload.during_tick == [False]
        assert not stop.requested  # SIGHUP is no stop
        assert signal.getsignal(signal.SIGHUP) == before  # restored
        # The wait it came in keeps the length it started with; the next one is the new interval's.
        assert sum(time.slept) == 600 + 240
        text = out.getvalue()
        assert "wait 10 minutes after each tick ends" in text
        assert "config reloaded  loop.interval_minutes, loop.idle_max_minutes changed" in text
        assert "pace  wait 4 minutes after each tick ends" in text
        assert text.index("tick 1  ok") < text.index("config reloaded") < text.index("tick 2  ok")
        assert [line["changed"] for line in log_messages(canopy_env) if line["msg"] == "config reloaded"] == [
            ["loop.interval_minutes", "loop.idle_max_minutes"]
        ]


def test_sighup_during_a_tick_lets_it_finish_on_the_config_it_started_with(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    paced(canopy_env, 10)
    ctx = context(canopy_env)
    paced(canopy_env, 4)  # changed after the loop read it, as an operator editing the file would
    with overseer_does(hup_me(), canopy("decide", "PROJ-1", "done", "--rationale", "merged")):
        stop, reload = repeat.Stop(), Asked()
        time = FakeTime()
        term, out = console()
        with repeat.signals(stop, reload):
            statuses = repeat.run(
                ctx,
                dry_run=True,
                interval_minutes=None,
                max_ticks=2,
                console=term,
                stop=stop,
                reload=reload,
                sleep=time.sleep,
                clock=time.clock,
            )

        assert statuses == {"ok": 2}
        assert reload.during_tick == [True, True]  # the web UI would have said: after the running tick
        conn = canopy_env.journal(migrate=False)
        assert [d.action for d in db.decisions_for_tick(conn, 1)] == ["queried", "done"]  # the overseer ran to its end
        assert sum(time.slept) == 600  # the wait after it was paced before the reload applied
        text = out.getvalue()
        assert text.index("tick 1  ok") < text.index("config reloaded") < text.index("tick 2  ok")


def test_a_config_that_does_not_load_leaves_the_loop_on_the_one_it_had(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    paced(canopy_env, 10)
    good = canopy_env.user_file.read_text()
    with overseer_does():
        stop, reload = repeat.Stop(), reread.Reload()
        sleeps: list[None] = []

        def break_then_mend() -> None:
            sleeps.append(None)
            if len(sleeps) == 1:
                canopy_env.write_user(good + "\n[capacity]\nmax_workers = 'many'\n")
                os.kill(os.getpid(), signal.SIGHUP)
            elif len(sleeps) == 2:
                canopy_env.write_user(good)  # mended, unasked: the loop reads it again only when asked

        time = FakeTime(on_sleep=break_then_mend)
        term, out = console()
        with repeat.signals(stop, reload):
            statuses = repeat.run(
                context(canopy_env),
                dry_run=True,
                interval_minutes=None,
                max_ticks=2,
                console=term,
                stop=stop,
                reload=reload,
                sleep=time.sleep,
                clock=time.clock,
            )

        assert statuses == {"ok": 2}
        assert sum(time.slept) == 600
        text = out.getvalue()
        assert "config not reloaded; kept the one it had:" in text
        assert "capacity.max_workers" in text
        assert "config reloaded" not in text
        [warning] = [line for line in log_messages(canopy_env) if line["msg"] == "config not reloaded"]
        assert "capacity.max_workers" in str(warning["error"])
