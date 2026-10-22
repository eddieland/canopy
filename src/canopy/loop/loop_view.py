"""What `canopy loop` draws between ticks: its header, the wait's countdown, and its lines to a file (DESIGN §6, D043).

On a terminal it draws rich text, with hints about the keys it reads (`TICK_NOW_KEY`, `PAUSE_KEY`). With output sent
to a file, as the daemon's is, it writes a logfmt line for each event instead (`record`), each with its time and `msg`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from canopy.core import db, pause
from canopy.infra import logfmt, logs

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rich.console import Console

    from canopy.core import observe
    from canopy.core.context import Context
    from canopy.loop import pacing, web
    from canopy.loop.tick import Woken

#: Pressed during the wait, this key runs the next tick now, as `canopy tick` by hand would.
TICK_NOW_KEY = "t"
#: Pressed during a tick or the wait, this key pauses the loop, or resumes it when paused.
PAUSE_KEY = "p"

#: What the countdown says ended the wait early, before the time left.
_WOKEN_NOTES: dict[Woken | None, str] = {
    "message": "operator message; next tick in ",
    "starts": "a ticket started or stopped; next tick in ",
    "task": "a task submitted, replied to, or stopped; next tick in ",
    "grant": "a grant; next tick in ",
    "notice": "a notice to workers set or cleared; next tick in ",
    "run": "a run ended; next tick in ",
}


def header(
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
    """Print what the loop runs on before its first tick: on a terminal a grid and hints about keys, else one line."""
    held = pause.paused(ctx.conn)
    if not console.is_terminal:
        # No hints: a loop writing to a file is stopped by `canopy daemon stop` or a signal, never by a key.
        record(
            console,
            "loop started",
            pid=os.getpid(),
            repository=ctx.repo_root,
            dry_run=dry_run,
            **pace_fields(pace),
            first_tick_in_seconds=round(defer_seconds) or None,
            max_workers=ctx.config.capacity.max_workers,
            max_ticks=max_ticks,
            log=ctx.state_dir / logs.LOG_FILE_NAME,
            web_ui=serving.note if serving is not None else None,
            paused_since=held.since if held is not None else None,
        )
        return
    console.rule("[bold]canopy loop[/]", style="dim")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("repository", Text(str(ctx.repo_root)))
    grid.add_row("pace", pace_note(pace))
    if defer_seconds:
        grid.add_row("first tick", f"in {duration(defer_seconds)} at {clock_time(defer_seconds)}")
    mode = Text("dry run: the overseer plans, nothing is dispatched", style="yellow") if dry_run else Text("live")
    grid.add_row("mode", mode)
    grid.add_row("workers", f"up to {ctx.config.capacity.max_workers}")
    if max_ticks is not None:
        grid.add_row("stops", f"after {max_ticks} tick{'' if max_ticks == 1 else 's'}")
    grid.add_row("log", Text(str(ctx.state_dir / logs.LOG_FILE_NAME)))
    if serving is not None:
        grid.add_row("web UI", Text(serving.note, style="" if serving.server is not None else "yellow"))
    if held is not None:
        since = f"since {_local_time(held.since)} ({held.channel}); no tick until resumed"
        grid.add_row("paused", Text(since, style="yellow"))
    console.print(grid)
    console.print(
        Text(
            "Ctrl-C stops after the current tick and waits for running runs to end; a second Ctrl-C aborts the tick,"
            " or stops waiting and leaves the runs running.",
            style="dim",
        ),
    )
    if keys:
        console.print(
            Text(f"Press {TICK_NOW_KEY} during the wait to tick now, {PAUSE_KEY} to pause or resume.", style="dim"),
        )
    console.print()


def countdown(note: str, woken: Woken | None, remaining: float, *, keys: bool) -> Text:
    """The wait's line: what ended it early, or `note`, then the time left, with hints about the keys if they are read.

    Returns:
        The line, to draw in place.
    """
    hint = f"  ·  {TICK_NOW_KEY} to tick now  ·  {PAUSE_KEY} to pause" if keys else ""
    return Text.assemble(
        (_WOKEN_NOTES.get(woken, note), "dim"),
        (duration(remaining), "bold"),
        (f" at {clock_time(remaining)}{hint}  ·  Ctrl-C to stop", "dim"),
    )


def held(held: pause.Paused, *, keys: bool) -> Text:
    """The wait's line while the loop is paused: since when, through which channel, and how to resume.

    Returns:
        The line, to draw in place.
    """
    hint = f"{PAUSE_KEY} to resume  ·  {TICK_NOW_KEY} to tick once" if keys else "`canopy resume` or the web UI resumes"
    return Text.assemble(
        ("paused", "bold yellow"),
        (
            f" since {_local_time(held.since)} ({held.channel}); no tick until resumed  ·  {hint}  ·  Ctrl-C to stop",
            "dim",
        ),
    )


def draining(labels: Sequence[str], elapsed: float) -> Text:
    """The line drawn while the loop waits for runs to end: which are left, and how long it has waited.

    Returns:
        The line, to draw in place.
    """
    return Text.assemble(
        ("waiting for ", "dim"),
        (runs_note(labels), "bold"),
        (f"  {duration(elapsed)}  ·  Ctrl-C again leaves them running", "dim"),
    )


def runs_note(labels: Sequence[str]) -> str:
    """How many runs, and which.

    Returns:
        The count, then the labels.
    """
    return f"{len(labels)} run{'' if len(labels) == 1 else 's'}: {', '.join(labels)}"


def pace_note(pace: pacing.Pace) -> str:
    """The pace for a person: minutes after each tick, and the most when idle, if idle pacing is on.

    Returns:
        The note.
    """
    base, cap = round(pace.base_seconds / 60), round(pace.cap_seconds / 60)
    note = f"wait {base} minute{'' if base == 1 else 's'} after each tick ends"
    return f"{note}, up to {cap} minutes when idle" if pace.on else note


def pace_fields(pace: pacing.Pace) -> dict[str, object]:
    """The pace as a log line's fields: minutes after each tick, and the most when idle, if idle pacing is on.

    Returns:
        `every_minutes`, and `idle_max_minutes` or None.
    """
    return {
        "every_minutes": round(pace.base_seconds / 60),
        "idle_max_minutes": round(pace.cap_seconds / 60) if pace.on else None,
    }


def stamped(label: Text, rest: str) -> Text:
    """A line of the loop's own, outside any tick's block: the time, `label`, and `rest` as plain text.

    Returns:
        The line, the local time dimmed.
    """
    return Text.assemble((datetime.now(UTC).astimezone().strftime("%H:%M:%S"), "dim"), "  ", label, rest)


def record(console: Console, msg: str, **fields: object) -> None:
    """Write one logfmt line to a file: the time, `msg`, and `fields` in their order, a None among them left out."""
    stamp = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    # As Text, never str, so rich reads no markup in what the overseer wrote; soft_wrap keeps the line whole.
    console.print(Text(logfmt.line({"time": stamp, "msg": msg, **fields})), soft_wrap=True)


def record_poll(console: Console, polled: Mapping[str, observe.Observed] | None) -> None:
    """Write a poll's line: how each source's run ended, what they recorded and refused, and what they missed."""
    if polled is None:
        record(console, "poll skipped", reason="a tick holds the lock")
        return
    if not polled:  # no source is configured
        return
    record(
        console,
        "polled",
        sources=", ".join(f"{name} {observed.status}" for name, observed in polled.items()),
        recorded=sum(n for observed in polled.values() for n in observed.recorded.values()),
        refused=sum(n for observed in polled.values() for n in observed.refused.values()),
        missed="; ".join(f"{name}: {o.missed}" for name, o in polled.items() if o.missed is not None) or None,
    )


def record_pause(console: Console, held: pause.Paused | None) -> None:
    """Write the line for the loop paused, with since when and through which channel, or for the loop resumed."""
    if held is None:
        record(console, "loop resumed")
    else:
        record(console, "loop paused", since=held.since, channel=held.channel)


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


def clock_time(seconds_from_now: float) -> str:
    """The terminal's clock `seconds_from_now` from now.

    Returns:
        The local time as `HH:MM`.
    """
    return (datetime.now(UTC).astimezone() + timedelta(seconds=seconds_from_now)).strftime("%H:%M")


def _local_time(stamp: str) -> str:
    """A time the journal wrote, as the terminal's clock shows it.

    Returns:
        The local time as `HH:MM`.
    """
    return db.parse_time(stamp).astimezone().strftime("%H:%M")
