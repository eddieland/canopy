"""`canopy loop`: run ticks one after another in the foreground, waiting between them (DESIGN §6, D042).

Each iteration is an ordinary tick (`tick.run`), which takes and releases the tick lock itself, so a `canopy tick` run
by hand still fits in between. The loop also holds its own lock, `<state_dir>/loop.lock`, for as long as it runs: two
loops on one state dir would run the overseer twice as often.

How long to wait after a tick is `pacing`'s decision: the configured interval, longer after idle ticks in a row, and
never past a harness gate (DESIGN §6, Idle pacing); pacing by what a tick cost will join it (ROADMAP M13). The
operator's acts since the last tick read the journal end the wait early (DESIGN §22): a message to a ticket, such as a
`canopy reply`; a ticket started or stopped; attempts or reviews granted; a notice to workers set or cleared. With idle
pacing on, a run ending after the tick read the journal does too. A config reload does not: it applies at the wait's
next step and leaves its deadline as it was. Nothing but the operator pressing `TICK_NOW_KEY` on a terminal starts a
tick sooner than `loop.min_gap_minutes` after the last one began: not a gate, not an early wake. A deferred start waits
the same way before the first tick, from when the loop started. Each tick's row records whether it was idle and what
ended the wait before it (`ticks.idle`, `ticks.woken_by`), so spend can be split by what it bought (ROADMAP M33).

While the operator has paused the loop (`core.pause`), the wait does not end at its deadline: it holds until they
resume, then ticks at once if the deadline has passed. `PAUSE_KEY` pauses and resumes from the terminal; the web UI and
`canopy pause` and `canopy resume` write the same journal row, which the wait reads at every step.

SIGHUP, or the web UI's settings page, asks the loop to read its config again (`reread`). The wait applies it at its
next step; a tick running when it is asked for finishes first, on the config it started with. A config that does not
load leaves the loop on the one it had, and says why. A terminal hanging up still ends the loop (`signals`).

Output is for a person at a terminal, drawn with rich (D043). The spinner and the countdown are drawn only on a
terminal; with output sent to a file, the loop prints one block per tick and nothing in between. Each tick's block ends
with what its overseer cost, when the runtime reported it.
"""

from __future__ import annotations

import os
import signal
import time
from collections import Counter
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from canopy.core import config, db, notice, pause
from canopy.infra import lock, logs, resources
from canopy.loop import attention, pacing, reread, tick

if TYPE_CHECKING:
    from types import FrameType

    from rich.console import Console

    from canopy.core.config import Config
    from canopy.core.context import Context
    from canopy.loop import web
    from canopy.serve.backend import Backend

LOCK_FILE_NAME = "loop.lock"
# How often the wait wakes to redraw the countdown and to notice a stop or an operator message.
_WAIT_STEP_SECONDS = 0.5
# A second stop signal this soon after the first is the same Ctrl-C, not a second one. `uv run` forwards the
# SIGINT it gets to its child about 200 ms after the terminal already sent it to the child; a person reading "Ctrl-C
# again aborts it" and pressing it again takes longer than this.
SAME_SIGNAL_SECONDS = 1.0
# Pressed during the wait, this key runs the next tick now, as `canopy tick` by hand would.
TICK_NOW_KEY = "t"
# Pressed during a tick or the wait, this key pauses the loop, or resumes it when paused.
PAUSE_KEY = "p"
# Decisions every tick repeats, and copies of tracker comments. The tick's summary counts them; `canopy decisions` lists
# them.
_QUIET_ACTIONS = ("wait", "mirror")
_STATUS_STYLES = {
    "ok": "bold green",
    "skipped": "bold yellow",
    "lock_busy": "bold yellow",
    "canopy_unavailable": "bold red",
    "overseer_failed": "bold red",
    "reconcile_failed": "bold red",
    "error": "bold red",
}


# What ended a wait before its deadline: the operator's act (a message, a ticket started or stopped, a grant, a notice
# set or cleared), a run ending, or the operator pressing `TICK_NOW_KEY`.
type Woken = Literal["message", "starts", "grant", "notice", "run", "key"]
# What started a tick, recorded on its row (`ticks.woken_by`): the loop starting, a wait that ran its length, one a gate
# shortened, or what ended one early.
type WokenBy = Woken | Literal["start", "timer", "gate"]
_WOKEN_NOTES: dict[Woken | None, str] = {
    "message": "operator message; next tick in ",
    "starts": "a ticket started or stopped; next tick in ",
    "grant": "a grant; next tick in ",
    "notice": "a notice to workers set or cleared; next tick in ",
    "run": "a run ended; next tick in ",
}


@dataclass
class Stop:
    """Whether the operator asked the loop to stop. Set by `signals`, read between and during ticks."""

    requested: bool = False
    requested_at: float | None = None  # `signals`' clock at the first stop signal


@contextmanager
def signals(
    stop: Stop,
    reload: reread.Reload | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
    hung_up: Callable[[], bool] = lambda: False,
) -> Generator[None]:
    """Make SIGINT and SIGTERM ask the loop to stop once the current tick ends, instead of killing it.

    A second signal raises KeyboardInterrupt, which aborts the tick in progress: `procs` kills the overseer's process
    group, and the next tick closes the tick row as `abandoned`. Workers already dispatched are detached and keep going.
    A signal within `SAME_SIGNAL_SECONDS` of the first counts as the first again, not as a second.

    With `reload`, SIGHUP asks the loop to read its config again instead of ending it. A terminal hanging up sends
    SIGHUP too: when `hung_up()` says it did, the loop ends as SIGHUP always ended it, unless SIGHUP was ignored on
    entry, as under `nohup`, where the loop is meant to outlive its terminal and a reload does no harm.
    """

    def handle(_signum: int, _frame: FrameType | None) -> None:
        now = clock()
        if stop.requested_at is None:
            stop.requested, stop.requested_at = True, now
        elif now - stop.requested_at >= SAME_SIGNAL_SECONDS:
            raise KeyboardInterrupt

    handlers: dict[signal.Signals, Callable[[int, FrameType | None], None]] = {
        signal.SIGINT: handle,
        signal.SIGTERM: handle,
    }
    if reload is not None:
        ignored = signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
        handlers[signal.SIGHUP] = _on_hangup(reload, hung_up, ignored=ignored)
    previous = {s: signal.signal(s, handler) for s, handler in handlers.items()}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def _on_hangup(
    reload: reread.Reload, hung_up: Callable[[], bool], *, ignored: bool
) -> Callable[[int, FrameType | None], None]:
    """SIGHUP's handler: a reload, unless the terminal hung up and SIGHUP was not `ignored` before the loop started.

    Returns:
        The handler, to install with `signal.signal`.
    """

    def handle(_signum: int, _frame: FrameType | None) -> None:
        if not ignored and hung_up():
            # No one is left to read the loop's output. End at once, as SIGHUP did before the loop handled it.
            signal.signal(signal.SIGHUP, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGHUP)
            return
        reload.request()

    return handle


def run(
    ctx: Context,
    *,
    dry_run: bool,
    interval_minutes: int | None,
    max_ticks: int | None,
    console: Console,
    stop: Stop,
    reload: reread.Reload | None = None,
    serve: bool = False,
    keys: Callable[[], str] | None = None,
    defer_minutes: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Counter[str]:
    """Run ticks until `stop` is requested or `max_ticks` have run.

    `interval_minutes` is `--every`'s; None waits `loop.interval_minutes`. With `serve`, the web UI is served from a
    thread for as long as the loop runs (DESIGN §22). `keys` returns the keys pressed since it was last called
    (`infra.keys.listen`); with it, `TICK_NOW_KEY` during the wait ticks at once and `PAUSE_KEY` pauses or resumes. With
    `defer_minutes`, the first tick waits that long, as the wait between ticks does. While the loop is paused, no tick
    starts but one `TICK_NOW_KEY` asks for. A reload asked for through `reload`, by `signals` or the web UI, reads the
    config again between ticks: the next tick, the pace, and the web UI run on it, and `--every` still holds.

    Returns:
        How many ticks ended in each status.

    Raises:
        lock.LockBusyError: another loop holds `<state_dir>/loop.lock`.
    """
    log = logs.for_tick(None)
    statuses: Counter[str] = Counter()
    settings = _Settings(ctx, _pace(ctx.config, interval_minutes), interval_minutes, reload or reread.Reload(), console)
    with lock.hold(ctx.state_dir / LOCK_FILE_NAME):
        # The loop reads the journal before its first tick, which is what would otherwise migrate it.
        db.migrate(ctx.conn, resources.migrations_dir())
        log.info(
            "loop started",
            extra={
                "dry_run": dry_run,
                "interval_minutes": round(settings.pace.base_seconds / 60),
                "idle_max_minutes": ctx.config.loop.idle_max_minutes,
                "min_gap_minutes": ctx.config.loop.min_gap_minutes,
                "defer_minutes": defer_minutes,
                "repo": ctx.repo,
                "pid": os.getpid(),
            },
        )
        serving = None
        if serve:
            # Imported here: the web server pulls in fastapi and uvicorn, which double the start-up time of every
            # other `canopy` command, the ones the overseer and workers run included.
            from canopy.loop import web  # noqa: PLC0415

            serving = web.start(ctx, log, settings.reload)
            settings.backend = serving.backend
        try:
            _header(
                console,
                ctx,
                dry_run=dry_run,
                pace=settings.pace,
                max_ticks=max_ticks,
                serving=serving,
                keys=keys is not None,
                defer_seconds=(defer_minutes or 0) * 60,
            )
            _ticks(
                settings,
                statuses,
                dry_run=dry_run,
                max_ticks=max_ticks,
                console=console,
                stop=stop,
                keys=keys,
                defer_seconds=(defer_minutes or 0) * 60,
                sleep=sleep,
                clock=clock,
                log=log,
            )
        finally:
            if serving is not None and serving.server is not None:
                serving.server.stop()
        log.info("loop stopped", extra={"ticks": statuses.total(), "statuses": dict(statuses)})
    counts = ", ".join(f"{status}={n}" for status, n in sorted(statuses.items())) or "none"
    ticks = statuses.total()
    console.rule(f"[bold]canopy loop[/] stopped after {ticks} tick{'' if ticks == 1 else 's'}: {counts}", style="dim")
    return statuses


def _pace(cfg: Config, every: int | None) -> pacing.Pace:
    """What the loop waits after a tick: `--every`, else `loop.interval_minutes`, and the idle cap.

    Returns:
        The base wait and the idle cap, in seconds.
    """
    return pacing.Pace(
        base_seconds=(every or cfg.loop.interval_minutes) * 60,
        cap_seconds=cfg.loop.idle_max_minutes * 60,
    )


@dataclass
class _Settings:
    """What the loop runs on, its context and its pace, replaced when the operator asks it to read its config again."""

    ctx: Context
    pace: pacing.Pace
    every: int | None  # `--every`, which a reload keeps
    reload: reread.Reload
    console: Console
    backend: Backend | None = None  # the web UI's, which serves the new config too

    def apply(self) -> None:
        """Read the config again, if asked to. A config that does not load leaves everything as it was, and says why."""
        if not self.reload.requested:
            return
        self.reload.requested = False
        log = logs.for_tick(None)
        try:
            found = reread.load(self.ctx)
        except config.ConfigError as e:
            log.warning("config not reloaded", extra={"error": str(e)})
            self.console.print(_stamped(Text("config not reloaded", style="bold red"), f"; kept the one it had: {e}"))
            return
        pace = _pace(found.config, self.every)
        self.ctx = replace(self.ctx, config=found.config, ws=found.ws)
        if self.backend is not None:
            self.backend.use(found.config, found.ws)
        log.info("config reloaded", extra={"changed": list(found.changed), "restart": list(found.restart)})
        what = f"{', '.join(found.changed)} changed" if found.changed else "nothing changed"
        self.console.print(_stamped(Text("config reloaded", style="bold green"), f"  {what}"))
        if found.restart:
            later = f"  {', '.join(found.restart)} take{'s' if len(found.restart) == 1 else ''} effect on a restart"
            self.console.print(Text(later, style="yellow"))
        if pace != self.pace:
            self.console.print(Text(f"  pace  {_pace_note(pace)}", style="dim"))
        self.pace = pace


def _stamped(label: Text, rest: str) -> Text:
    """A line of the loop's own, outside any tick's block: the time, `label`, and `rest` as plain text.

    Returns:
        The line, the local time dimmed.
    """
    return Text.assemble((datetime.now(UTC).astimezone().strftime("%H:%M:%S"), "dim"), "  ", label, rest)


def _ticks(
    settings: _Settings,
    statuses: Counter[str],
    *,
    dry_run: bool,
    max_ticks: int | None,
    console: Console,
    stop: Stop,
    keys: Callable[[], str] | None,
    defer_seconds: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    log: logs.TickAdapter,
) -> None:
    """Tick, report, and wait, until `stop` is requested or `max_ticks` have run, counting each tick's status.

    The context and the pace are `settings`', read at the start of each tick: a reload during the wait applies to the
    next tick and the waits after it, not to the wait it happens in.
    """
    ctx = settings.ctx
    conn = ctx.conn  # a reload keeps the journal's connection
    woken_by: WokenBy = "start"
    if defer_seconds:
        woken_by = (
            _defer(console, settings, stop, defer_seconds, keys=keys, sleep=sleep, clock=clock, log=log) or "start"
        )
    elif pause.paused(ctx.conn) is not None:
        # Paused before the loop started: hold the first tick as a wait already due holds.
        woken = _wait(
            console, ctx, stop, clock(), sleep=sleep, clock=clock, keys=keys, log=log, each_step=settings.apply
        )
        _log_woken(log, woken, seen=0, since=None, read_at=None)
        woken_by = woken or "start"
    idle_count = 0
    while not stop.requested:
        settings.apply()
        ctx, pace = settings.ctx, settings.pace
        before = pacing.before(ctx)
        # Operator messages to a ticket newer than this wake the wait after this tick: every channel records one the
        # same way. A note to a chore waits for the chore's next run.
        seen = db.latest_message_id(ctx.conn, source="operator", subject_kind=db.SUBJECT_TICKET)
        begun = db.now()
        started = clock()
        settings.reload.ticking = True
        try:
            with Live(_Ticking(stop, clock), console=console, transient=True, refresh_per_second=8):
                outcome = _tick(ctx, dry_run=dry_run, log=log)
        finally:
            settings.reload.ticking = False
        ended = clock()
        if keys is not None:
            # Keys pressed during the tick are dropped, all but a pause, which holds the next tick.
            _toggle_pause(ctx, keys(), log)
        statuses[outcome.status] += 1
        # Classified with idle pacing off too: the journal records it for spend, though only pacing counts it.
        idle = pacing.idle(ctx, outcome, before)
        # Measured for the prompt, not acted on (ROADMAP M28): what the tick changed with nothing new to see.
        churn = pacing.churn(ctx, outcome, before)
        idle_count = idle_count + 1 if pace.on and idle else 0
        if outcome.tick_id is not None:
            db.set_tick_loop(ctx.conn, outcome.tick_id, idle=idle, woken_by=woken_by)
        last = max_ticks is not None and statuses.total() >= max_ticks
        wait = None if last or stop.requested else _wait_after(ctx, pace, idle_count, ended - started)
        if wait is not None:
            logs.for_tick(outcome.tick_id).info(
                "loop waits",
                extra={"idle": idle, "idle_count": idle_count, "wait_seconds": round(wait), "churn": churn},
            )
        # The wait runs from the end of the tick, so reporting it is part of the wait, not added to it.
        _report(console, ctx, outcome, before.attention, elapsed=ended - started, wait=wait, idle_count=idle_count)
        if wait is None:
            break
        # The operator's starts, stops, and grants after the tick read the journal wake the wait, or after it began if
        # it read nothing. With idle pacing on, a run that ends after the tick read the journal wakes it too.
        read = pacing.read_at(ctx, outcome)
        since = read or begun
        read_at = read if pace.on else None

        def wake(seen: int = seen, since: str = since, read_at: str | None = read_at) -> Woken | None:
            if (acted := _operator_acted(settings, seen, since)) is not None:
                return acted
            return "run" if read_at is not None and db.runs_ended_after(conn, read_at) else None

        woken = _wait(
            console,
            ctx,
            stop,
            ended + wait,
            sleep=sleep,
            clock=clock,
            wake=wake,
            earliest=started + _gap_seconds(ctx),
            keys=keys,
            log=log,
            each_step=settings.apply,
        )
        _log_woken(log, woken, seen=seen, since=since, read_at=read_at)
        woken_by = woken or ("gate" if wait < pace.after(idle_count) else "timer")


def _wait_after(ctx: Context, pace: pacing.Pace, idle_count: int, elapsed: float) -> float:
    """Seconds to wait after a tick that ran `elapsed`: `pacing`'s, but at least what is left of `loop.min_gap_minutes`.

    Returns:
        The longer of `pacing.wait` and what is left of the gap.
    """
    return max(pacing.wait(ctx, pace, idle_count, datetime.now(UTC)), _gap_seconds(ctx) - elapsed)


def _gap_seconds(ctx: Context) -> float:
    """The least time from one tick's start to the next's, `loop.min_gap_minutes`.

    Returns:
        The gap in seconds.
    """
    return ctx.config.loop.min_gap_minutes * 60.0


def _operator_acted(settings: _Settings, seen: int, since: str) -> Woken | None:
    """What the operator did that ends a wait, if anything: every channel records it the same way (DESIGN §22).

    A message to a ticket newer than `seen`; a ticket started or stopped, attempts or reviews granted, or a notice to
    workers set or cleared, after `since`. A note to a chore waits for the chore's next run, and a config reload waits
    for the next tick.

    Returns:
        The first of those that happened, or None.
    """
    conn = settings.ctx.conn
    if db.latest_message_id(conn, source="operator", subject_kind=db.SUBJECT_TICKET) > seen:
        return "message"
    if db.starts_moved_after(conn, since):
        return "starts"
    if db.granted_after(conn, since):
        return "grant"
    return "notice" if notice.moved_after(conn, since) else None


def _defer(
    console: Console,
    settings: _Settings,
    stop: Stop,
    seconds: float,
    *,
    keys: Callable[[], str] | None,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    log: logs.TickAdapter,
) -> Woken | None:
    """Wait `seconds` before the first tick. The operator's acts or `TICK_NOW_KEY` end it early, as between ticks.

    Returns:
        What ended it early, if anything did.
    """
    ctx = settings.ctx
    seen = db.latest_message_id(ctx.conn, source="operator", subject_kind=db.SUBJECT_TICKET)
    since = db.now()
    started = clock()
    log.info("loop defers its first tick", extra={"wait_seconds": round(seconds)})

    woken = _wait(
        console,
        ctx,
        stop,
        started + seconds,
        sleep=sleep,
        clock=clock,
        wake=lambda: _operator_acted(settings, seen, since),
        earliest=started + _gap_seconds(ctx),
        keys=keys,
        log=log,
        note="first tick in ",
        each_step=settings.apply,
    )
    _log_woken(log, woken, seen=seen, since=since, read_at=None)
    return woken


def _log_woken(
    log: logs.TickAdapter, woken: Woken | None, *, seen: int, since: str | None, read_at: str | None
) -> None:
    if woken == "message":
        log.info("an operator message ended the wait", extra={"after_message": seen})
    elif woken == "starts":
        log.info("a ticket started or stopped ended the wait", extra={"after": since})
    elif woken == "grant":
        log.info("a grant ended the wait", extra={"after": since})
    elif woken == "notice":
        log.info("a notice to workers set or cleared ended the wait", extra={"after": since})
    elif woken == "run":
        log.info("a run ending ended the wait", extra={"after": read_at})
    elif woken == "key":
        log.info("the operator asked for a tick now")


def _tick(ctx: Context, *, dry_run: bool, log: logs.TickAdapter) -> tick.Outcome:
    """Run one tick. An unexpected error ends that tick, not the loop, as with a scheduler that starts each tick.

    Returns:
        The tick's outcome, or an `error` outcome naming the exception when the tick raised one.
    """
    try:
        return tick.run(ctx, dry_run=dry_run)
    # Logged with its traceback. The journal is in autocommit mode, so the next tick starts clean.
    except Exception as e:
        log.exception("tick raised; the loop goes on", extra={"error": str(e)})
        return tick.Outcome(None, "error", f"{type(e).__name__}: {e}")


class _Ticking:
    """The spinner shown while a tick runs, with its elapsed time, redrawn by rich's refresh thread."""

    def __init__(self, stop: Stop, clock: Callable[[], float]) -> None:
        self._stop = stop
        self._clock = clock
        self._started = clock()
        self._spinner = Spinner("dots", style="cyan")

    def __rich__(self) -> Spinner:
        text = Text.assemble(("tick running ", "bold"), (duration(self._clock() - self._started), "dim"))
        if self._stop.requested:
            text.append("  stopping after this tick; Ctrl-C again aborts it", style="yellow")
        self._spinner.update(text=text)
        return self._spinner


def _wait(
    console: Console,
    ctx: Context,
    stop: Stop,
    deadline: float,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    wake: Callable[[], Woken | None] = lambda: None,
    earliest: float = 0.0,
    keys: Callable[[], str] | None = None,
    log: logs.TickAdapter,
    note: str = "next tick in ",
    each_step: Callable[[], None] = lambda: None,
) -> Woken | None:
    """Wait until `clock()` reaches `deadline`, drawing a countdown, or less if a stop is requested.

    Once `wake()` names a reason, the wait ends at `earliest` instead, or at once if that has passed: an operator
    message or a run ending runs the next tick sooner. `TICK_NOW_KEY` among `keys()` ends it at once, with no floor:
    the operator asked for this tick, as they could with `canopy tick`. While the loop is paused, the wait does not end
    at its deadline but holds until the pause is lifted; `PAUSE_KEY` pauses and resumes. `each_step` runs first at
    every step, as a reload does.

    Returns:
        What ended the wait early, if anything did.
    """
    woken: Woken | None = None
    with Live(console=console, transient=True, auto_refresh=False) as live:
        while not stop.requested:
            each_step()
            pressed = keys() if keys is not None else ""
            _toggle_pause(ctx, pressed, log)
            if TICK_NOW_KEY in pressed.lower():
                return "key"
            held = pause.paused(ctx.conn)
            remaining = deadline - clock()
            if remaining <= 0 and held is None:
                break
            if woken is None and (woken := wake()) is not None:
                deadline = min(deadline, max(earliest, clock()))
                continue
            shown = (
                _held(held, keys=keys is not None)
                if held
                else _countdown(note, woken, remaining, keys=keys is not None)
            )
            live.update(shown, refresh=True)
            sleep(_WAIT_STEP_SECONDS if held else min(_WAIT_STEP_SECONDS, remaining))
    return woken


def _toggle_pause(ctx: Context, pressed: str, log: logs.TickAdapter) -> None:
    """Pause the loop, or resume it, once for each `PAUSE_KEY` in `pressed`."""
    if pressed.lower().count(PAUSE_KEY) % 2 == 0:
        return
    if pause.paused(ctx.conn) is None:
        pause.pause(ctx.conn, channel=pause.LOOP)
        log.info("loop paused", extra={"channel": pause.LOOP})
    else:
        pause.resume(ctx.conn)
        log.info("loop resumed", extra={"channel": pause.LOOP})


def _countdown(note: str, woken: Woken | None, remaining: float, *, keys: bool) -> Text:
    hint = f"  ·  {TICK_NOW_KEY} to tick now  ·  {PAUSE_KEY} to pause" if keys else ""
    return Text.assemble(
        (_WOKEN_NOTES.get(woken, note), "dim"),
        (duration(remaining), "bold"),
        (f" at {_clock_time(remaining)}{hint}  ·  Ctrl-C to stop", "dim"),
    )


def _held(held: pause.Paused, *, keys: bool) -> Text:
    hint = f"{PAUSE_KEY} to resume  ·  {TICK_NOW_KEY} to tick once" if keys else "`canopy resume` or the web UI resumes"
    return Text.assemble(
        ("paused", "bold yellow"),
        (
            f" since {_local_time(held.since)} ({held.channel}); no tick until resumed  ·  {hint}  ·  Ctrl-C to stop",
            "dim",
        ),
    )


def _header(
    console: Console,
    ctx: Context,
    *,
    dry_run: bool,
    pace: pacing.Pace,
    max_ticks: int | None,
    serving: web.Serving | None = None,
    keys: bool = False,
    defer_seconds: float = 0,
) -> None:
    console.rule("[bold]canopy loop[/]", style="dim")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("repository", Text(str(ctx.repo_root)))
    grid.add_row("pace", _pace_note(pace))
    if defer_seconds:
        grid.add_row("first tick", f"in {duration(defer_seconds)} at {_clock_time(defer_seconds)}")
    mode = Text("dry run: the overseer plans, nothing is dispatched", style="yellow") if dry_run else Text("live")
    grid.add_row("mode", mode)
    grid.add_row("workers", f"up to {ctx.config.capacity.max_workers}")
    if max_ticks is not None:
        grid.add_row("stops", f"after {max_ticks} tick{'' if max_ticks == 1 else 's'}")
    grid.add_row("log", Text(str(ctx.state_dir / logs.LOG_FILE_NAME)))
    if serving is not None:
        grid.add_row("web UI", Text(serving.note, style="" if serving.server is not None else "yellow"))
    if (held := pause.paused(ctx.conn)) is not None:
        since = f"since {_local_time(held.since)} ({held.channel}); no tick until resumed"
        grid.add_row("paused", Text(since, style="yellow"))
    console.print(grid)
    console.print(Text("Ctrl-C stops after the current tick; a second Ctrl-C aborts it.", style="dim"))
    if keys:
        console.print(
            Text(f"Press {TICK_NOW_KEY} during the wait to tick now, {PAUSE_KEY} to pause or resume.", style="dim")
        )
    console.print()


def _pace_note(pace: pacing.Pace) -> str:
    base, cap = round(pace.base_seconds / 60), round(pace.cap_seconds / 60)
    note = f"wait {base} minute{'' if base == 1 else 's'} after each tick ends"
    return f"{note}, up to {cap} minutes when idle" if pace.on else note


def _report(
    console: Console,
    ctx: Context,
    outcome: tick.Outcome,
    before: list[attention.Item],
    *,
    elapsed: float,
    wait: float | None,
    idle_count: int = 0,
) -> None:
    """Print what one tick did: its status, the decisions that change something, and how the attention list moved."""
    label = f"tick {outcome.tick_id}" if outcome.tick_id is not None else "tick"
    console.print(
        Text.assemble(
            (datetime.now(UTC).astimezone().strftime("%H:%M:%S"), "dim"),
            "  ",
            (label, "bold"),
            "  ",
            (outcome.status, _STATUS_STYLES.get(outcome.status, "bold")),
            "  ",
            (duration(elapsed), "dim"),
            "  ",
            outcome.summary,
        )
    )

    # Cells are Text, never str: rich parses a str as markup, and rationales and details are the overseer's text.
    # Only the last column may give up width on a narrow terminal. rich shrinks wrappable columns first and, when every
    # column is no_wrap, shrinks them all alike, which drops the ticket key. So the last column is wrappable and its
    # cells (`_detail`) keep themselves to one line with an ellipsis.
    rows = Table.grid(padding=(0, 2))
    rows.add_column(width=2, no_wrap=True)
    rows.add_column(style="cyan", no_wrap=True)
    rows.add_column(no_wrap=True)
    rows.add_column(style="dim", ratio=1)
    if outcome.tick_id is not None:
        _decision_rows(rows, ctx, outcome.tick_id, failed=outcome.status == "overseer_failed")
    after = attention.listed(ctx)
    _attention_rows(rows, before, after)
    if rows.row_count:
        console.print(rows)

    # Running reviews take worker capacity too (DESIGN §6).
    running = len(db.running_runs(ctx.conn)) + len(db.running_review_runs(ctx.conn))
    footer = Text("  ", style="dim")
    footer.append(f"workers {running}/{ctx.config.capacity.max_workers}")
    footer.append("  ·  ")
    footer.append(f"attention {len(after)}", style="bold yellow" if after else "dim")
    if outcome.usage is not None:
        footer.append(f"  ·  cost {outcome.usage.describe()}")
    if wait is not None and pause.paused(ctx.conn) is not None:
        footer.append("  ·  paused: no tick until resumed", style="yellow")
    elif wait is not None:
        idle = f"idle {idle_count}, " if idle_count else ""
        footer.append(f"  ·  {idle}next tick in {duration(wait)} at {_clock_time(wait)}")
    console.print(footer)
    console.print()


def _decision_rows(rows: Table, ctx: Context, tick_id: int, *, failed: bool) -> None:
    """The tick's decisions that change something. Attention items are shown as the list's change instead."""
    for d in db.decisions_for_tick(ctx.conn, tick_id):
        action = d.action
        if action.startswith(attention.ACTION_PREFIX) or action in _QUIET_ACTIONS:
            continue
        style = "red" if action.startswith("refused:") else "green" if action.startswith("dispatch:") else ""
        rationale = _detail(d.rationale)
        rows.add_row("", Text(attention.decided_about(d)), Text(action, style=style), rationale)
    output = ctx.state_dir / "ticks" / f"{tick_id}.log"
    if failed and output.exists():
        # Not `_detail`: collapsing whitespace would print a path that does not exist.
        rows.add_row("", "", Text("overseer output", style="red"), Text(str(output), no_wrap=True, overflow="ellipsis"))


def _attention_rows(rows: Table, before: list[attention.Item], after: list[attention.Item]) -> None:
    """Items the tick added to the attention list, then items it resolved."""
    had, has = attention.keys(before), attention.keys(after)
    for item in after:
        if (item.ticket_key, item.reason, item.repo) not in had:
            detail = _detail(item.detail)
            rows.add_row(Text("+", style="bold yellow"), Text(item.subject), Text(item.reason, style="yellow"), detail)
    for item in before:
        if (item.ticket_key, item.reason, item.repo) not in has:
            rows.add_row(
                Text("-", style="bold green"),
                Text(item.subject),
                Text(item.reason, style="green"),
                _detail("resolved"),
            )


def _detail(text: str) -> Text:
    """A last-column cell: one line, whitespace collapsed, cut with an ellipsis when the terminal is too narrow.

    Returns:
        The cell's text, set not to wrap.
    """
    return Text(" ".join(text.split()), no_wrap=True, overflow="ellipsis")


def duration(seconds: float) -> str:
    """Render a length of time for a person: `45s`, `3m 05s`, `1m`, `2h 10m`, `2h`.

    Returns:
        Hours and minutes, minutes and seconds, or seconds alone, rounded to the second, with a zero second unit left
        off (`1m`, not `1m 00s`). A negative length is `0s`.
    """
    total = max(0, round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m {secs:02d}s" if secs else f"{minutes}m"
    return f"{secs}s"


def _clock_time(seconds_from_now: float) -> str:
    return (datetime.now(UTC).astimezone() + timedelta(seconds=seconds_from_now)).strftime("%H:%M")


def _local_time(stamp: str) -> str:
    """A time the journal wrote, as the terminal's clock shows it.

    Returns:
        The local time as `HH:MM`.
    """
    return db.parse_time(stamp).astimezone().strftime("%H:%M")
