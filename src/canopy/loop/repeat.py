"""`canopy loop`: run ticks one after another in the foreground, waiting between them (DESIGN §6, D042).

Each iteration is an ordinary tick (`tick.run`), which takes and releases the tick lock itself, so a `canopy tick` run
by hand still fits in between. The loop also holds its own lock, `<state_dir>/loop.lock`, for as long as it runs: two
loops on one state dir would run the overseer twice as often.

How long to wait after a tick is `pacing`'s decision: the configured interval, longer after idle ticks in a row, and
never past a harness gate (DESIGN §6, Idle pacing); it does not read what a tick cost (ROADMAP, Deferred). The
operator's acts since the last tick read the journal end the wait early (DESIGN §22): a message to a ticket, such as a
`canopy reply`; a ticket started or stopped; attempts or reviews granted; a notice to workers set or cleared. With idle
pacing on, a run ending after the tick read the journal does too. A config reload does not: it applies at the wait's
next step and leaves its deadline as it was. Nothing but the operator asking for a tick now, with `TICK_NOW_KEY` on a
terminal or from the web UI (`tick_now`), starts a tick sooner than `loop.min_gap_minutes` after the last one ended:
not a gate, not an early wake. A deferred start waits the same way before the first tick, from when the loop started.
Each tick's row records whether it was idle and what ended the wait before it (`ticks.idle`, `ticks.woken_by`), so
spend can be split by what it bought (ROADMAP M33).

A tick is the overseer's turn; between ticks the loop also polls the connectors, every `connect.every_minutes` from the
last read, whatever `loop.*` paces the ticks at (`poll`, DESIGN §6). A poll reads the world into the journal and ends
no wait, and none runs while the loop is paused. The wait after a live tick also reads which models served the runs
left unread (`models`), one at a time, which ends no wait either.

While the operator has paused the loop (`core.pause`), the wait does not end at its deadline: it holds until they
resume, then ticks at once if the deadline has passed. `PAUSE_KEY` pauses and resumes from the terminal; the web UI and
`canopy pause` and `canopy resume` write the same journal row, which the wait reads at every step.

SIGHUP, or the web UI's settings page, asks the loop to read its config again (`reread`). The wait applies it at its
next step; a tick running when it is asked for finishes first, on the config it started with. A config that does not
load leaves the loop on the one it had, and says why. A terminal hanging up still ends the loop (`signals`).

Output is for a person at a terminal, drawn with rich (D043). The spinner and the countdown are drawn only on a
terminal. With output sent to a file, as the daemon's is, the loop writes a log instead: a logfmt line for each event,
each with its time and `msg`, and no rules, tables, or hints about keys. A tick writes a line for itself, with what its
overseer cost when the runtime reported it, then one for each decision that changes something and for each change to
the attention list. Between ticks it writes one for each poll of the connectors, for what ended a wait early, and for
the loop paused or resumed, through whichever channel. `tick_report` draws what a tick did, and `loop_view` the rest.
"""

from __future__ import annotations

import os
import signal
import time
from collections import Counter
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from canopy.core import config, db, notice, pause, tasks
from canopy.infra import lock, logs, procs, resources
from canopy.loop import loop_view, models, pacing, phases, poll, reread, tick, tick_now, tick_report

if TYPE_CHECKING:
    import sqlite3
    from types import FrameType

    from rich.console import Console

    from canopy.core.config import Config
    from canopy.core.context import Context
    from canopy.loop.tick import Woken, WokenBy
    from canopy.serve.backend import Backend

LOCK_FILE_NAME = "loop.lock"
# How often the wait wakes to redraw the countdown and to notice a stop or an operator message.
_WAIT_STEP_SECONDS = 0.5
# A second stop signal this soon after the first is the same Ctrl-C, not a second one. `uv run` forwards the
# SIGINT it gets to its child about 200 ms after the terminal already sent it to the child; a person reading "Ctrl-C
# again aborts it" and pressing it again takes longer than this.
SAME_SIGNAL_SECONDS = 1.0


@dataclass
class Stop:
    """Whether the operator asked the loop to stop. Set by `signals`, read between and during ticks."""

    requested: bool = False
    requested_at: float | None = None  # `signals`' clock at the first stop signal
    # The first stop signal was SIGINT, a Ctrl-C: the loop waits for the runs still running to end before it exits.
    awaits_runs: bool = False


@contextmanager
def signals(
    stop: Stop,
    reload: reread.Reload | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
    hung_up: Callable[[], bool] = lambda: False,
) -> Generator[None]:
    """Make SIGINT and SIGTERM ask the loop to stop once the current tick ends, instead of killing it.

    A first SIGINT, a Ctrl-C or `canopy daemon stop --wait`, also asks the loop to wait for the runs still running to
    end (`Stop.awaits_runs`); a first SIGTERM, as `canopy daemon stop` sends, does not. A second signal raises
    KeyboardInterrupt, which aborts the tick in progress: `procs` kills the overseer's process group, and the next tick
    closes the tick row as `abandoned`. During the wait for runs, it ends the wait instead. Runs are detached and keep
    going either way. A signal within `SAME_SIGNAL_SECONDS` of the first counts as the first again, not as a second.

    With `reload`, SIGHUP asks the loop to read its config again instead of ending it. A terminal hanging up sends
    SIGHUP too: when `hung_up()` says it did, the loop ends as SIGHUP always ended it, unless SIGHUP was ignored on
    entry, as under `nohup`, where the loop is meant to outlive its terminal and a reload does no harm.
    """

    def handle(signum: int, _frame: FrameType | None) -> None:
        now = clock()
        if stop.requested_at is None:
            stop.requested, stop.requested_at = True, now
            stop.awaits_runs = signum == signal.SIGINT
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
    reload: reread.Reload,
    hung_up: Callable[[], bool],
    *,
    ignored: bool,
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
    asked: tick_now.TickNow | None = None,
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
    config again between ticks: the next tick, the pace, and the web UI run on it, and `--every` still holds. A tick
    asked for through `asked`, by the web UI, ends the wait as `TICK_NOW_KEY` does.

    Returns:
        How many ticks ended in each status.

    Raises:
        lock.LockBusyError: another loop holds `<state_dir>/loop.lock`.
    """
    log = logs.for_tick(None)
    statuses: Counter[str] = Counter()
    settings = _Settings(
        ctx,
        _pace(ctx.config, interval_minutes),
        interval_minutes,
        reload or reread.Reload(),
        asked or tick_now.TickNow(),
        console,
    )
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

            serving = web.start(ctx, log, settings.reload, settings.asked, interval_minutes)
            settings.backend = serving.backend
            settings.ui = serving.links
        try:
            loop_view.header(
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
            if stop.awaits_runs:
                # Inside the `try`: the web UI stays up while the runs end, so the operator can watch them there.
                _await_runs(console, settings.ctx, sleep=sleep, clock=clock, log=log)
        finally:
            if serving is not None and serving.server is not None:
                serving.server.stop()
        log.info("loop stopped", extra={"ticks": statuses.total(), "statuses": dict(statuses)})
    counts = ", ".join(f"{status}={n}" for status, n in sorted(statuses.items())) or "none"
    ticks = statuses.total()
    if not console.is_terminal:
        loop_view.record(console, "loop stopped", ticks=ticks, statuses=counts)
        return statuses
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
    asked: tick_now.TickNow  # a tick the web UI asked for, which the next wait takes
    console: Console
    backend: Backend | None = None  # the web UI's, which serves the new config too
    # Where notifications' links open the web UI this loop serves; None when it serves none. `serve.` keys take
    # effect at a restart (`reread.RESTART_PREFIX`), so a reload keeps it.
    ui: str | None = None

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
            if not self.console.is_terminal:
                loop_view.record(self.console, "config not reloaded", error=str(e))
                return
            self.console.print(
                loop_view.stamped(Text("config not reloaded", style="bold red"), f"; kept the one it had: {e}"),
            )
            return
        pace = _pace(found.config, self.every)
        self.ctx = replace(self.ctx, config=found.config, ws=found.ws)
        if self.backend is not None:
            self.backend.use(found.config, found.ws)
        log.info("config reloaded", extra={"changed": list(found.changed), "restart": list(found.restart)})
        self.pace, before = pace, self.pace
        if not self.console.is_terminal:
            loop_view.record(
                self.console,
                "config reloaded",
                changed=", ".join(found.changed) or None,
                restart=", ".join(found.restart) or None,
                **(loop_view.pace_fields(pace) if pace != before else {}),
            )
            return
        what = f"{', '.join(found.changed)} changed" if found.changed else "nothing changed"
        self.console.print(loop_view.stamped(Text("config reloaded", style="bold green"), f"  {what}"))
        if found.restart:
            later = f"  {', '.join(found.restart)} take{'s' if len(found.restart) == 1 else ''} effect on a restart"
            self.console.print(Text(later, style="yellow"))
        if pace != before:
            self.console.print(Text(f"  pace  {loop_view.pace_note(pace)}", style="dim"))


@dataclass
class _Polls:
    """When the wait after a tick polls the connectors (`poll.run`): `connect.every_minutes` after the last read.

    The wait also reads which models served the runs left unread, through `backlog`, between its polls.
    """

    settings: _Settings
    clock: Callable[[], float]
    log: logs.TickAdapter
    #: The runs' sessions left unread; None in a dry run, which reads none.
    backlog: models.Backlog | None
    #: When the connectors last ran, a tick's or a poll's, on `clock`.
    last: float = 0.0

    def ticked(self) -> float:
        """Note that a tick has just ended: it ran the connectors, unless its reconcile failed, so the next poll waits.

        Returns:
            The time, on `clock`.
        """
        self.last = self.clock()
        if self.backlog is not None:
            self.backlog.ticked()
        return self.last

    def step(self) -> None:
        """Read the config again if asked to, as every step of a wait does, then poll if one is due and not paused.

        Before the poll, read a run's session if one is due (`models.Backlog.step`).
        """
        self.settings.apply()
        ctx = self.settings.ctx
        if self.backlog is not None:
            self.backlog.step(ctx)
        if self.clock() - self.last < ctx.config.connect.every_minutes * 60 or pause.paused(ctx.conn) is not None:
            return
        self.last = self.clock()
        polled = poll.run(ctx, self.log)
        if not self.settings.console.is_terminal:
            loop_view.record_poll(self.settings.console, polled)


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
            console,
            ctx,
            stop,
            clock(),
            sleep=sleep,
            clock=clock,
            keys=keys,
            asked=settings.asked.take,
            log=log,
            each_step=settings.apply,
        )
        _log_woken(console, log, woken, seen=0, since=None, read_at=None)
        woken_by = woken or "start"
    idle_count = 0
    # A dry run reads no session, as its tick reads none.
    polls = _Polls(settings, clock, log, None if dry_run else models.Backlog(clock, log))
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
                outcome = _tick(ctx, dry_run=dry_run, woken_by=woken_by, ui=settings.ui, log=log)
        finally:
            settings.reload.ticking = False
        ended = polls.ticked()
        if keys is not None:
            # Keys pressed during the tick are dropped, all but a pause, which holds the next tick.
            _toggle_pause(ctx, keys(), log)
        statuses[outcome.status] += 1
        # Classified with idle pacing off too: the journal records it for spend, though only pacing counts it.
        idle = pacing.idle(ctx, outcome)
        # Measured for the prompt, not acted on (ROADMAP M28): what the tick changed with nothing new to see.
        churn = pacing.churn(ctx, outcome, before)
        idle_count = pacing.count(ctx, outcome, idle_count, idle=idle, on=pace.on)
        if outcome.tick_id is not None:
            db.set_tick_loop(ctx.conn, outcome.tick_id, idle=idle, woken_by=woken_by)
        last = max_ticks is not None and statuses.total() >= max_ticks
        wait = None if last or stop.requested else _wait_after(ctx, pace, idle_count)
        # The derivation in shadow, against what the overseer did (DESIGN §30): measured, never acted on.
        derived = phases.tally(ctx.conn, outcome.tick_id) if outcome.tick_id is not None else Counter[phases.Verdict]()
        _log_wait(outcome, wait, idle=idle, idle_count=idle_count, churn=churn, derived=derived)
        # The wait runs from the end of the tick, so reporting it is part of the wait, not added to it.
        tick_report.report(
            console,
            ctx,
            outcome,
            before.attention,
            elapsed=ended - started,
            wait=wait,
            idle_count=idle_count,
            derived=derived,
        )
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
            earliest=ended + _gap_seconds(ctx),
            keys=keys,
            asked=settings.asked.take,
            log=log,
            each_step=polls.step,
        )
        _log_woken(console, log, woken, seen=seen, since=since, read_at=read_at)
        woken_by = woken or ("gate" if wait < pace.after(idle_count) else "timer")


def _log_wait(
    outcome: tick.Outcome,
    wait: float | None,
    *,
    idle: bool,
    idle_count: int,
    churn: Sequence[str],
    derived: Counter[phases.Verdict],
) -> None:
    """Log the `loop waits` line for the wait after a tick, with the tickets the derivation disagreed on."""
    if wait is None:
        return
    logs.for_tick(outcome.tick_id).info(
        "loop waits",
        extra={
            "idle": idle,
            "idle_count": idle_count,
            "wait_seconds": round(wait),
            "churn": churn,
            "disagreements": derived["disagrees"],
            "derived_stale": derived["stale"],
        },
    )


def _wait_after(ctx: Context, pace: pacing.Pace, idle_count: int) -> float:
    """Seconds to wait after a tick ends: `pacing`'s, but at least `loop.min_gap_minutes`.

    Returns:
        The longer of `pacing.wait` and the gap.
    """
    return max(pacing.wait(ctx, pace, idle_count, datetime.now(UTC)), _gap_seconds(ctx))


def _gap_seconds(ctx: Context) -> float:
    """The least time from one tick's end to the next's start, or from the loop's start to its first tick.

    Returns:
        The gap in seconds.
    """
    return ctx.config.loop.min_gap_minutes * 60.0


def _operator_acted(settings: _Settings, seen: int, since: str) -> Woken | None:
    """What the operator did that ends a wait, if anything: every channel records it the same way (DESIGN §22).

    A message to a ticket newer than `seen`; a ticket started or stopped, attempts or reviews granted, a task submitted,
    replied to, or stopped (DESIGN §36), or a notice to workers set or cleared, after `since`. A note to a chore waits
    for the chore's next run, and a config reload waits for the next tick.

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
    if tasks.moved_after(conn, since):
        return "task"
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
    """Wait `seconds` before the first tick. The operator's acts or a tick asked for end it early, as between ticks.

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
        asked=settings.asked.take,
        log=log,
        note="first tick in ",
        each_step=settings.apply,
    )
    _log_woken(console, log, woken, seen=seen, since=since, read_at=None)
    return woken


def _log_woken(
    console: Console,
    log: logs.TickAdapter,
    woken: Woken | None,
    *,
    seen: int,
    since: str | None,
    read_at: str | None,
) -> None:
    if woken is not None and not console.is_terminal:
        loop_view.record(console, "wait ended", by=woken)
    if woken == "message":
        log.info("an operator message ended the wait", extra={"after_message": seen})
    elif woken == "starts":
        log.info("a ticket started or stopped ended the wait", extra={"after": since})
    elif woken == "grant":
        log.info("a grant ended the wait", extra={"after": since})
    elif woken == "task":
        log.info("a task submitted, replied to, or stopped ended the wait", extra={"after": since})
    elif woken == "notice":
        log.info("a notice to workers set or cleared ended the wait", extra={"after": since})
    elif woken == "run":
        log.info("a run ending ended the wait", extra={"after": read_at})
    elif woken == "key":
        log.info("the operator asked for a tick now")
    elif woken == "web":
        log.info("the operator asked for a tick now", extra={"channel": "web"})


def _await_runs(
    console: Console,
    ctx: Context,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    log: logs.TickAdapter,
) -> None:
    """Wait for every run still running, a worker's, a review's, or a chore's, to end, drawing which ones are left.

    Only runs whose own process is alive count: one whose process is gone never ends by itself, and the next tick's
    reconcile closes it. A second Ctrl-C raises KeyboardInterrupt in `signals`, which ends the wait and leaves the runs
    running, detached, as they always are.
    """
    running = _live_runs(ctx.conn)
    if not running:
        return
    log.info("loop waits for runs to end", extra={"runs": running})
    if console.is_terminal:
        console.print(loop_view.stamped(Text("waiting for runs", style="bold"), f"  {loop_view.runs_note(running)}"))
    else:
        loop_view.record(console, "waiting for runs", runs=", ".join(running))
    started = clock()
    try:
        with Live(console=console, transient=True, auto_refresh=False) as live:
            while running:
                live.update(loop_view.draining(running, clock() - started), refresh=True)
                sleep(_WAIT_STEP_SECONDS)
                running = _live_runs(ctx.conn)
    except KeyboardInterrupt:
        log.info("loop left runs running", extra={"runs": running})
        if console.is_terminal:
            console.print(
                loop_view.stamped(Text("left runs running", style="bold yellow"), f"  {loop_view.runs_note(running)}"),
            )
        else:
            loop_view.record(console, "left runs running", runs=", ".join(running))
        return
    log.info("runs ended", extra={"wait_seconds": round(clock() - started)})
    if console.is_terminal:
        console.print(
            loop_view.stamped(
                Text("runs ended", style="bold green"),
                f"  after {loop_view.duration(clock() - started)}",
            ),
        )
    else:
        loop_view.record(console, "runs ended", wait_seconds=round(clock() - started))


def _live_runs(conn: sqlite3.Connection) -> list[str]:
    """Every table's running runs whose own process is alive, as the operator reads them.

    Returns:
        A label for each run, workers first, then chores, then reviews, then tasks, oldest first within each.
    """
    return [
        _run_label(table, r)
        for table in db.RUN_TABLES
        for r in db.running_runs(conn, table)
        if procs.running(Path(r["log_path"]), r["pid"])
    ]


def _run_label(table: db.RunTable, row: sqlite3.Row) -> str:
    match table:
        case "runs":
            return f"{row['ticket_key']} {row['kind']}"
        case "chore_runs":
            return f"chore {row['chore']}"
        case "review_runs":
            return f"review {row['ticket_key'] or row['pr_url']}"
        case "task_runs":
            return f"task:{row['task_id']}"
        case _:
            assert_never(table)


def _tick(ctx: Context, *, dry_run: bool, woken_by: WokenBy, ui: str | None, log: logs.TickAdapter) -> tick.Outcome:
    """Run one tick, which `woken_by` started. An unexpected error ends that tick, not the loop, as a scheduler would.

    `ui` is where its notifications' links open the web UI, when the loop serves one.

    Returns:
        The tick's outcome, or an `error` outcome naming the exception when the tick raised one.
    """
    try:
        return tick.run(ctx, dry_run=dry_run, woken_by=woken_by, ui=ui)
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
        text = Text.assemble(("tick running ", "bold"), (loop_view.duration(self._clock() - self._started), "dim"))
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
    asked: Callable[[], bool] = lambda: False,
    log: logs.TickAdapter,
    note: str = "next tick in ",
    each_step: Callable[[], None] = lambda: None,
) -> Woken | None:
    """Wait until `clock()` reaches `deadline`, drawing a countdown, or less if a stop is requested.

    Once `wake()` names a reason, the wait ends at `earliest` instead, or at once if that has passed: an operator
    message or a run ending runs the next tick sooner. `TICK_NOW_KEY` among `keys()`, or `asked()` saying the web UI
    asked for a tick, ends it at once, with no floor: the operator asked for this tick, as they could with
    `canopy tick`. While the loop is paused, the wait does not end at its deadline but holds until the pause is lifted;
    `PAUSE_KEY` pauses and resumes. `each_step` runs first at every step, as a reload does.

    Returns:
        What ended the wait early, if anything did.
    """
    woken: Woken | None = None
    # The line before the wait, a tick's or the loop's first, says whether it began paused; a log notes each change.
    was = pause.paused(ctx.conn)
    with Live(console=console, transient=True, auto_refresh=False) as live:
        while not stop.requested:
            each_step()
            pressed = keys() if keys is not None else ""
            _toggle_pause(ctx, pressed, log)
            if loop_view.TICK_NOW_KEY in pressed.lower():
                asked()  # one tick for both: a web request this wait would take is the same ask
                return "key"
            if asked():
                return "web"
            held = pause.paused(ctx.conn)
            if (held is None) != (was is None) and not console.is_terminal:
                loop_view.record_pause(console, held)
            was = held
            remaining = deadline - clock()
            if remaining <= 0 and held is None:
                break
            if woken is None and (woken := wake()) is not None:
                deadline = min(deadline, max(earliest, clock()))
                continue
            shown = (
                loop_view.held(held, keys=keys is not None)
                if held
                else loop_view.countdown(note, woken, remaining, keys=keys is not None)
            )
            live.update(shown, refresh=True)
            sleep(_WAIT_STEP_SECONDS if held else min(_WAIT_STEP_SECONDS, remaining))
    return woken


def _toggle_pause(ctx: Context, pressed: str, log: logs.TickAdapter) -> None:
    """Pause the loop, or resume it, once for each `PAUSE_KEY` in `pressed`."""
    if pressed.lower().count(loop_view.PAUSE_KEY) % 2 == 0:
        return
    if pause.paused(ctx.conn) is None:
        pause.pause(ctx.conn, channel=pause.LOOP)
        log.info("loop paused", extra={"channel": pause.LOOP})
    else:
        pause.resume(ctx.conn)
        log.info("loop resumed", extra={"channel": pause.LOOP})
