"""`canopy loop`: run ticks one after another in the foreground, waiting between them (DESIGN §6, D042).

Each iteration is an ordinary tick (`tick.run`), which takes and releases the tick lock itself, so a `canopy tick` run
by hand still fits in between. The loop also holds its own lock, `<state_dir>/loop.lock`, for as long as it runs: two
loops on one state dir would run the overseer twice as often.

How long to wait after a tick is `pacing`'s decision: the configured interval, longer after idle ticks in a row, and
never past a harness gate (DESIGN §6, Idle pacing); pacing by what a tick cost will join it (ROADMAP M13). An operator
message recorded since the last tick began, such as a `canopy reply`, ends the wait early, at most once a minute (DESIGN
§22), and so, with idle pacing on, does a run ending after the tick read the journal. On a terminal, pressing
`TICK_NOW_KEY` ends it at once. A deferred start waits the same way before the first tick, from when the loop started.

While the operator has paused the loop (`core.pause`), the wait does not end at its deadline: it holds until they
resume, then ticks at once if the deadline has passed. `PAUSE_KEY` pauses and resumes from the terminal; the web UI and
`canopy pause` and `canopy resume` write the same journal row, which the wait reads at every step.

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

from canopy.core import db, pause
from canopy.infra import lock, logs, resources
from canopy.loop import attention, pacing, tick

if TYPE_CHECKING:
    from types import FrameType

    from rich.console import Console

    from canopy.core.context import Context
    from canopy.loop import web

LOCK_FILE_NAME = "loop.lock"
# How often the wait wakes to redraw the countdown and to notice a stop or an operator message.
_WAIT_STEP_SECONDS = 0.5
# An operator message or a run ending starts the next tick early, but no sooner than this after the last one began.
WAKE_MIN_SECONDS = 60.0
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
    pressed since it was last called (`infra.keys.listen`); with it, `TICK_NOW_KEY` during the wait ticks at once and
    `PAUSE_KEY` pauses or resumes. With `defer_minutes`, the first tick waits that long, as the wait between ticks does.
    While the loop is paused, no tick starts but one `TICK_NOW_KEY` asks for.

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
        serving = None
        if serve:
            # Imported here: the web server pulls in fastapi and uvicorn, which double the start-up time of every
            # other `canopy` command, the ones the overseer and workers run included.
            from canopy.loop import web  # noqa: PLC0415

            serving = web.start(ctx, log)
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
    elif pause.paused(ctx.conn) is not None:
        # Paused before the loop started: hold the first tick as a wait already due holds.
        woken = _wait(console, ctx, stop, clock(), sleep=sleep, clock=clock, keys=keys, log=log)
        _log_woken(log, woken, seen=0, read_at=None)
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
        if keys is not None:
            # Keys pressed during the tick are dropped, all but a pause, which holds the next tick.
            _toggle_pause(ctx, keys(), log)
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
            ctx,
            stop,
            ended + wait,
            sleep=sleep,
            clock=clock,
            wake=wake,
            earliest=started + WAKE_MIN_SECONDS,
            keys=keys,
            log=log,
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
        ctx,
        stop,
        started + seconds,
        sleep=sleep,
        clock=clock,
        wake=wake,
        earliest=started + WAKE_MIN_SECONDS,
        keys=keys,
        log=log,
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
) -> Woken | None:
    """Wait until `clock()` reaches `deadline`, drawing a countdown, or less if a stop is requested.

    Once `wake()` names a reason, the wait ends at `earliest` instead, or at once if that has passed: an operator
    message or a run ending runs the next tick sooner. `TICK_NOW_KEY` among `keys()` ends it at once, with no floor:
    the operator asked for this tick, as they could with `canopy tick`. While the loop is paused, the wait does not end
    at its deadline but holds until the pause is lifted; `PAUSE_KEY` pauses and resumes. Returns what ended the wait
    early, if anything did.
    """
    woken: Woken | None = None
    with Live(console=console, transient=True, auto_refresh=False) as live:
        while not stop.requested:
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


def _local_time(stamp: str) -> str:
    """A time the journal wrote, as the terminal's clock shows it."""
    return db.parse_time(stamp).astimezone().strftime("%H:%M")
