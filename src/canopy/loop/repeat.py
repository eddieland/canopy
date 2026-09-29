"""`canopy loop`: run ticks one after another in the foreground, waiting between them (DESIGN §6, D042).

Each iteration is an ordinary tick (`tick.run`), which takes and releases the tick lock itself, so a `canopy tick` run
by hand still fits in between. The loop also holds its own lock, `<state_dir>/loop.lock`, for as long as it runs: two
loops on one state dir would run the overseer twice as often.

How long to wait after a tick is `pace`'s decision. Today that is the configured interval; it is where pacing by what a
tick cost will go (ROADMAP M13).

Output is for a person at a terminal, drawn with rich (D043). The spinner and the countdown are drawn only on a
terminal; with output sent to a file, the loop prints one block per tick and nothing in between.
"""

from __future__ import annotations

import signal
import time
from collections import Counter
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from canopy.core import db
from canopy.infra import lock, logs, resources
from canopy.loop import attention, tick

if TYPE_CHECKING:
    from types import FrameType

    from rich.console import Console

    from canopy.core.context import Context

LOCK_FILE_NAME = "loop.lock"
# How often the wait wakes to redraw the countdown and to notice a stop.
_WAIT_STEP_SECONDS = 0.5
# Decisions every tick repeats. The tick's summary counts them; `canopy decisions` lists them.
_QUIET_ACTIONS = ("wait",)
_STATUS_STYLES = {
    "ok": "bold green",
    "skipped": "bold yellow",
    "lock_busy": "bold yellow",
    "overseer_failed": "bold red",
    "reconcile_failed": "bold red",
    "error": "bold red",
}


@dataclass
class Stop:
    """Whether the operator asked the loop to stop. Set by `signals`, read between and during ticks."""

    requested: bool = False


@contextmanager
def signals(stop: Stop) -> Generator[None]:
    """Make SIGINT and SIGTERM ask the loop to stop once the current tick ends, instead of killing it.

    A second signal raises KeyboardInterrupt, which aborts the tick in progress: `procs` kills the overseer's process
    group, and the next tick closes the tick row as `abandoned`. Workers already dispatched are detached and keep going.
    """

    def handle(_signum: int, _frame: FrameType | None) -> None:
        if stop.requested:
            raise KeyboardInterrupt
        stop.requested = True

    previous = {s: signal.signal(s, handle) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def pace(outcome: tick.Outcome, interval_seconds: float) -> float:  # noqa: ARG001  (the seam for spend pacing, M13)
    """Return how many seconds to wait after a tick that ended with `outcome`. Today, the interval whatever happened."""
    return interval_seconds


def run(
    ctx: Context,
    *,
    dry_run: bool,
    interval_minutes: int,
    max_ticks: int | None,
    console: Console,
    stop: Stop,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Counter[str]:
    """Run ticks until `stop` is requested or `max_ticks` have run. Returns how many ticks ended in each status.

    Raises:
        lock.LockBusyError: another loop holds `<state_dir>/loop.lock`.
    """
    log = logs.for_tick(None)
    statuses: Counter[str] = Counter()
    with lock.hold(ctx.state_dir / LOCK_FILE_NAME):
        # The loop reads the journal before its first tick, which is what would otherwise migrate it.
        db.migrate(ctx.conn, resources.migrations_dir())
        log.info("loop started", extra={"dry_run": dry_run, "interval_minutes": interval_minutes, "repo": ctx.repo})
        _header(console, ctx, dry_run=dry_run, interval_minutes=interval_minutes, max_ticks=max_ticks)
        while not stop.requested:
            before = attention.current(ctx.conn)
            started = clock()
            with Live(_Ticking(stop, clock), console=console, transient=True, refresh_per_second=8):
                outcome = _tick(ctx, dry_run=dry_run, log=log)
            ended = clock()
            statuses[outcome.status] += 1
            last = max_ticks is not None and statuses.total() >= max_ticks
            wait = None if last or stop.requested else pace(outcome, interval_minutes * 60)
            # The wait runs from the end of the tick, so reporting it is part of the wait, not added to it.
            next_at = None if wait is None else _clock_time(wait)
            _report(console, ctx, outcome, before, elapsed=ended - started, next_at=next_at)
            if wait is None:
                break
            _wait(console, stop, ended + wait, sleep=sleep, clock=clock)
        log.info("loop stopped", extra={"ticks": statuses.total(), "statuses": dict(statuses)})
    counts = ", ".join(f"{status}={n}" for status, n in sorted(statuses.items())) or "none"
    ticks = statuses.total()
    console.rule(f"[bold]canopy loop[/] stopped after {ticks} tick{'' if ticks == 1 else 's'}: {counts}", style="dim")
    return statuses


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
) -> None:
    """Wait until `clock()` reaches `deadline`, drawing a countdown, or less if a stop is requested."""
    with Live(console=console, transient=True, auto_refresh=False) as live:
        while not stop.requested and (remaining := deadline - clock()) > 0:
            live.update(
                Text.assemble(
                    ("next tick in ", "dim"),
                    (duration(remaining), "bold"),
                    (f" at {_clock_time(remaining)}  ·  Ctrl-C to stop", "dim"),
                ),
                refresh=True,
            )
            sleep(min(_WAIT_STEP_SECONDS, remaining))


def _header(console: Console, ctx: Context, *, dry_run: bool, interval_minutes: int, max_ticks: int | None) -> None:
    console.rule("[bold]canopy loop[/]", style="dim")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("repository", Text(str(ctx.repo_root)))
    grid.add_row("pace", f"wait {interval_minutes} minute{'' if interval_minutes == 1 else 's'} after each tick ends")
    mode = Text("dry run: the overseer plans, nothing is dispatched", style="yellow") if dry_run else Text("live")
    grid.add_row("mode", mode)
    grid.add_row("workers", f"up to {ctx.config.capacity.max_workers}")
    if max_ticks is not None:
        grid.add_row("stops", f"after {max_ticks} tick{'' if max_ticks == 1 else 's'}")
    grid.add_row("log", Text(str(ctx.state_dir / logs.LOG_FILE_NAME)))
    console.print(grid)
    console.print(Text("Ctrl-C stops after the current tick; a second Ctrl-C aborts it.", style="dim"))
    console.print()


def _report(
    console: Console,
    ctx: Context,
    outcome: tick.Outcome,
    before: list[attention.Item],
    *,
    elapsed: float,
    next_at: str | None,
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
    after = attention.current(ctx.conn)
    _attention_rows(rows, before, after)
    if rows.row_count:
        console.print(rows)

    running = len(db.running_runs(ctx.conn))
    footer = Text("  ", style="dim")
    footer.append(f"workers {running}/{ctx.config.capacity.max_workers}")
    footer.append("  ·  ")
    footer.append(f"attention {len(after)}", style="bold yellow" if after else "dim")
    if next_at is not None:
        footer.append(f"  ·  next tick at {next_at}")
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
        rows.add_row("", Text(str(d["ticket_key"] or "-")), Text(action, style=style), rationale)
    output = ctx.state_dir / "ticks" / f"{tick_id}.log"
    if failed and output.exists():
        # Not `_detail`: collapsing whitespace would print a path that does not exist.
        rows.add_row("", "", Text("overseer output", style="red"), Text(str(output), no_wrap=True, overflow="ellipsis"))


def _attention_rows(rows: Table, before: list[attention.Item], after: list[attention.Item]) -> None:
    """Items the tick added to the attention list, then items it resolved."""
    had = {(i.ticket_key, i.reason) for i in before}
    has = {(i.ticket_key, i.reason) for i in after}
    for item in after:
        if (item.ticket_key, item.reason) not in had:
            detail = _detail(item.detail)
            rows.add_row(
                Text("+", style="bold yellow"), Text(item.ticket_key), Text(item.reason, style="yellow"), detail
            )
    for item in before:
        if (item.ticket_key, item.reason) not in has:
            rows.add_row(
                Text("-", style="bold green"),
                Text(item.ticket_key),
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
