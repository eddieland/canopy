"""`canopy loop`: run ticks one after another in the foreground, waiting between them (DESIGN §6, D042).

Each iteration is an ordinary tick (`tick.run`), which takes and releases the tick lock itself, so a `canopy tick` run
by hand still fits in between. The loop also holds its own lock, `<state_dir>/loop.lock`, for as long as it runs: two
loops on one state dir would run the overseer twice as often.

How long to wait after a tick is `pacing`'s decision: the configured interval, longer after idle ticks in a row, and
never past a harness gate (DESIGN §6, Idle pacing); pacing by what a tick cost will join it (ROADMAP M13). An operator
message recorded since the last tick began, such as a `canopy reply`, ends the wait early, at most once a minute (DESIGN
§22), and so, with idle pacing on, does a run ending after the tick read the journal. On a terminal, pressing
`TICK_NOW_KEY` ends it at once. A deferred start waits the same way before the first tick, from when the loop started.

Output is for a person at a terminal, drawn with rich (D043). The spinner and the countdown are drawn only on a
terminal; with output sent to a file, the loop prints one block per tick and nothing in between. Each tick's block ends
with what its overseer cost, when the runtime reported it.
"""

from __future__ import annotations

import signal
import time
from collections import Counter
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from canopy.core import db
from canopy.infra import lock, logs, resources
from canopy.loop import attention, pacing, tick, web

if TYPE_CHECKING:
    from types import FrameType

    from rich.console import Console

    from canopy.core.context import Context

LOCK_FILE_NAME = "loop.lock"
# How often the wait wakes to redraw the countdown and to notice a stop or an operator message.
_WAIT_STEP_SECONDS = 0.5
# An operator message or a run ending starts the next tick early, but no sooner than this after the last one began.
WAKE_MIN_SECONDS = 60.0
# A second stop signal this soon after the first is the same Ctrl-C, not a second one. `uv run` forwards the
# SIGINT it gets to its child about 200 ms after the terminal already sent it to the child; a person reading "Ctrl-C
# again aborts it" and pressing it again takes longer than this.
SAME_SIGNAL_SECONDS = 1.0
# Pressed during the wait, this key runs the next tick now, as `canopy tick` by hand would (D088).
TICK_NOW_KEY = "t"
# Decisions every tick repeats, and copies of tracker comments. The tick's summary counts them; `canopy decisions` lists
# them.
_QUIET_ACTIONS = ("wait", "mirror")
_STATUS_STYLES = {
    "ok": "bold green",
    "skipped": "bold yellow",
    "lock_busy": "bold yellow",
    "overseer_failed": "bold red",
    "reconcile_failed": "bold red",
    "error": "bold red",
}


# What ended a wait before its deadline: an operator message, a run ending, or the operator pressing `TICK_NOW_KEY`.
type Woken = Literal["message", "run", "key"]
_WOKEN_NOTES: dict[Woken | None, str] = {
    "message": "operator message; next tick in ",
    "run": "a run ended; next tick in ",
}


@dataclass
class Stop:
    """Whether the operator asked the loop to stop. Set by `signals`, read between and during ticks."""

    requested: bool = False
    requested_at: float | None = None  # `signals`' clock at the first stop signal


@contextmanager
def signals(stop: Stop, *, clock: Callable[[], float] = time.monotonic) -> Generator[None]:
    """Make SIGINT and SIGTERM ask the loop to stop once the current tick ends, instead of killing it.

    A second signal raises KeyboardInterrupt, which aborts the tick in progress: `procs` kills the overseer's process
    group, and the next tick closes the tick row as `abandoned`. Workers already dispatched are detached and keep going.
    A signal within `SAME_SIGNAL_SECONDS` of the first counts as the first again, not as a second.
    """

    def handle(_signum: int, _frame: FrameType | None) -> None:
        now = clock()
        if stop.requested_at is None:
            stop.requested, stop.requested_at = True, now
        elif now - stop.requested_at >= SAME_SIGNAL_SECONDS:
            raise KeyboardInterrupt

    previous = {s: signal.signal(s, handle) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def run(
    ctx: Context,
    *,
    dry_run: bool,
    interval_minutes: int,
    max_ticks: int | None,
    console: Console,
    stop: Stop,
    serve: bool = False,
    keys: Callable[[], str] | None = None,
    defer_minutes: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Counter[str]:
    """Run ticks until `stop` is requested or `max_ticks` have run. Returns how many ticks ended in each status.

    With `serve`, the web UI is served from a thread for as long as the loop runs (DESIGN §22). `keys` returns the keys
    pressed since it was last called (`infra.keys.listen`); with it, `TICK_NOW_KEY` during the wait ticks at once.
    With `defer_minutes`, the first tick waits that long, as the wait between ticks does.

    Raises:
        lock.LockBusyError: another loop holds `<state_dir>/loop.lock`.
    """
    log = logs.for_tick(None)
    statuses: Counter[str] = Counter()
    idle_max_minutes = ctx.config.loop.idle_max_minutes
    pace = pacing.Pace(base_seconds=interval_minutes * 60, cap_seconds=idle_max_minutes * 60)
    with lock.hold(ctx.state_dir / LOCK_FILE_NAME):
        # The loop reads the journal before its first tick, which is what would otherwise migrate it.
        db.migrate(ctx.conn, resources.migrations_dir())
        log.info(
            "loop started",
            extra={
                "dry_run": dry_run,
                "interval_minutes": interval_minutes,
                "idle_max_minutes": idle_max_minutes,
                "defer_minutes": defer_minutes,
                "repo": ctx.repo,
            },
        )
        serving = web.start(ctx, log) if serve else None
        try:
            _header(
                console,
                ctx,
                dry_run=dry_run,
                pace=pace,
                max_ticks=max_ticks,
                serving=serving,
                keys=keys is not None,
                defer_seconds=(defer_minutes or 0) * 60,
            )
            _ticks(
                ctx,
                statuses,
                dry_run=dry_run,
                pace=pace,
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


def _ticks(
    ctx: Context,
    statuses: Counter[str],
    *,
    dry_run: bool,
    pace: pacing.Pace,
    max_ticks: int | None,
    console: Console,
    stop: Stop,
    keys: Callable[[], str] | None,
    defer_seconds: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    log: logs.TickAdapter,
) -> None:
    """Tick, report, and wait, until `stop` is requested or `max_ticks` have run, counting each tick's status."""
    if defer_seconds:
        _defer(console, ctx, stop, defer_seconds, keys=keys, sleep=sleep, clock=clock, log=log)
    idle_count = 0
    while not stop.requested:
        before = pacing.before(ctx)
        # Operator messages to a ticket newer than this wake the wait after this tick: every channel records one the
        # same way. A note to a chore waits for the chore's next run.
        seen = db.latest_message_id(ctx.conn, source="operator", subject_kind=db.SUBJECT_TICKET)
        started = clock()
        with Live(_Ticking(stop, clock), console=console, transient=True, refresh_per_second=8):
            outcome = _tick(ctx, dry_run=dry_run, log=log)
        ended = clock()
        statuses[outcome.status] += 1
        idle = pace.on and pacing.idle(ctx, outcome, before)
        idle_count = idle_count + 1 if idle else 0
        last = max_ticks is not None and statuses.total() >= max_ticks
        wait = None if last or stop.requested else pacing.wait(ctx, pace, idle_count, datetime.now(UTC))
        if wait is not None:
            logs.for_tick(outcome.tick_id).info(
                "loop waits", extra={"idle": idle, "idle_count": idle_count, "wait_seconds": round(wait)}
            )
        # The wait runs from the end of the tick, so reporting it is part of the wait, not added to it.
        _report(console, ctx, outcome, before.attention, elapsed=ended - started, wait=wait, idle_count=idle_count)
        if wait is None:
            break
        # With idle pacing on, a run that ends after the tick read the journal wakes the wait too.
        read_at = pacing.read_at(ctx, outcome) if pace.on else None

        def wake(seen: int = seen, read_at: str | None = read_at) -> Woken | None:
            if db.latest_message_id(ctx.conn, source="operator", subject_kind=db.SUBJECT_TICKET) > seen:
                return "message"
            return "run" if read_at is not None and db.runs_ended_after(ctx.conn, read_at) else None

        woken = _wait(
            console,
            stop,
            ended + wait,
            sleep=sleep,
            clock=clock,
            wake=wake,
            earliest=started + WAKE_MIN_SECONDS,
            keys=keys,
        )
        _log_woken(log, woken, seen=seen, read_at=read_at)


def _defer(
    console: Console,
    ctx: Context,
    stop: Stop,
    seconds: float,
    *,
    keys: Callable[[], str] | None,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    log: logs.TickAdapter,
) -> None:
    """Wait `seconds` before the first tick. An operator message or `TICK_NOW_KEY` ends it early, as between ticks."""
    seen = db.latest_message_id(ctx.conn, source="operator", subject_kind=db.SUBJECT_TICKET)
    started = clock()
    log.info("loop defers its first tick", extra={"wait_seconds": round(seconds)})

    def wake() -> Woken | None:
        return (
            "message"
            if db.latest_message_id(ctx.conn, source="operator", subject_kind=db.SUBJECT_TICKET) > seen
            else None
        )

    woken = _wait(
        console,
        stop,
        started + seconds,
        sleep=sleep,
        clock=clock,
        wake=wake,
        earliest=started + WAKE_MIN_SECONDS,
        keys=keys,
        note="first tick in ",
    )
    _log_woken(log, woken, seen=seen, read_at=None)


def _log_woken(log: logs.TickAdapter, woken: Woken | None, *, seen: int, read_at: str | None) -> None:
    if woken == "message":
        log.info("an operator message ended the wait", extra={"after_message": seen})
    elif woken == "run":
        log.info("a run ending ended the wait", extra={"after": read_at})
    elif woken == "key":
        log.info("the operator asked for a tick now")


def _tick(ctx: Context, *, dry_run: bool, log: logs.TickAdapter) -> tick.Outcome:
    """Run one tick. An unexpected error ends that tick, not the loop, as with a scheduler that starts each tick."""
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
    stop: Stop,
    deadline: float,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    wake: Callable[[], Woken | None] = lambda: None,
    earliest: float = 0.0,
    keys: Callable[[], str] | None = None,
    note: str = "next tick in ",
) -> Woken | None:
    """Wait until `clock()` reaches `deadline`, drawing a countdown, or less if a stop is requested.

    Once `wake()` names a reason, the wait ends at `earliest` instead, or at once if that has passed: an operator
    message or a run ending runs the next tick sooner. `TICK_NOW_KEY` among `keys()` ends it at once, with no floor:
    the operator asked for this tick, as they could with `canopy tick`. Returns what ended the wait early, if anything
    did.
    """
    woken: Woken | None = None
    hint = f"  ·  {TICK_NOW_KEY} to tick now  ·  Ctrl-C to stop" if keys is not None else "  ·  Ctrl-C to stop"
    if keys is not None:
        keys()  # keys pressed during the tick were not meant for this wait
    with Live(console=console, transient=True, auto_refresh=False) as live:
        while not stop.requested and (remaining := deadline - clock()) > 0:
            if keys is not None and TICK_NOW_KEY in keys().lower():
                return "key"
            if woken is None and (woken := wake()) is not None:
                deadline = min(deadline, max(earliest, clock()))
                continue
            live.update(
                Text.assemble(
                    (_WOKEN_NOTES.get(woken, note), "dim"),
                    (duration(remaining), "bold"),
                    (f" at {_clock_time(remaining)}{hint}", "dim"),
                ),
                refresh=True,
            )
            sleep(min(_WAIT_STEP_SECONDS, remaining))
    return woken


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
    console.print(grid)
    console.print(Text("Ctrl-C stops after the current tick; a second Ctrl-C aborts it.", style="dim"))
    if keys:
        console.print(Text(f"Press {TICK_NOW_KEY} during the wait to tick now.", style="dim"))
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

    # Running reviews take worker capacity too (D065).
    running = len(db.running_runs(ctx.conn)) + len(db.running_review_runs(ctx.conn))
    footer = Text("  ", style="dim")
    footer.append(f"workers {running}/{ctx.config.capacity.max_workers}")
    footer.append("  ·  ")
    footer.append(f"attention {len(after)}", style="bold yellow" if after else "dim")
    if outcome.usage is not None:
        footer.append(f"  ·  cost {outcome.usage.describe()}")
    if wait is not None:
        idle = f"idle {idle_count}, " if idle_count else ""
        footer.append(f"  ·  {idle}next tick in {duration(wait)} at {_clock_time(wait)}")
    console.print(footer)
    console.print()


def _decision_rows(rows: Table, ctx: Context, tick_id: int, *, failed: bool) -> None:
    """The tick's decisions that change something. Attention items are shown as the list's change instead."""
    for d in db.decisions_for_tick(ctx.conn, tick_id):
        action = str(d["action"])
        if action.startswith(attention.ACTION_PREFIX) or action in _QUIET_ACTIONS:
            continue
        style = "red" if action.startswith("refused:") else "green" if action.startswith("dispatch:") else ""
        rationale = _detail(str(d["rationale"]))
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
    """A last-column cell: one line, whitespace collapsed, cut with an ellipsis when the terminal is too narrow."""
    return Text(" ".join(text.split()), no_wrap=True, overflow="ellipsis")


def duration(seconds: float) -> str:
    """Render a length of time for a person: `45s`, `3m 05s`, `2h 10m`."""
    total = max(0, round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _clock_time(seconds_from_now: float) -> str:
    return (datetime.now(UTC).astimezone() + timedelta(seconds=seconds_from_now)).strftime("%H:%M")
