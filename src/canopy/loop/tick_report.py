"""What `canopy loop` prints after each tick: its status and what it changed (DESIGN §6, D043).

The changes are the decisions that change something and how the attention list moved. On a terminal the report is a
line, a table of the changes, and a footer with the workers, the attention list, the cost, and the wait. With output
sent to a file it is a logfmt line for the tick, with what its overseer cost when the runtime reported it, then one for
each change (`loop_view.record`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, assert_never

from rich.table import Table
from rich.text import Text

from canopy.core import db, pause
from canopy.loop import attention, duties, loop_view, phases

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Collection

    from rich.console import Console

    from canopy.core.context import Context
    from canopy.loop import tick

#: Decisions every tick repeats, and copies of tracker comments. The tick's summary counts them; `canopy decisions`
#: lists them.
_QUIET_ACTIONS = ("wait", "mirror", duties.QUERIED_ACTION)
#: How a terminal draws each tick status.
_STATUS_STYLES = {
    "ok": "bold green",
    "skipped": "bold yellow",
    "lock_busy": "bold yellow",
    "canopy_unavailable": "bold red",
    "disk_low": "bold red",
    "overseer_failed": "bold red",
    "reconcile_failed": "bold red",
    "error": "bold red",
}


def report(
    console: Console,
    ctx: Context,
    outcome: tick.Outcome,
    before: Collection[attention.Item],
    *,
    elapsed: float,
    wait: float | None,
    idle_count: int = 0,
    derived: Counter[phases.Verdict] | None = None,
) -> None:
    """Print what one tick did: its status, the decisions that change something, and how the attention list moved.

    `derived` counts the tick's tickets by how the derivation compared with the overseer (DESIGN §30).
    """
    changes: list[_Change] = []
    if outcome.tick_id is not None:
        changes += _decisions(ctx, outcome.tick_id, failed=outcome.status == "overseer_failed")
    after = attention.listed(ctx)
    changes += _attention_changes(before, after)
    # Running reviews and tasks take worker capacity too (DESIGN §6, §36).
    running = db.busy_workers(ctx.conn)
    paused = wait is not None and pause.paused(ctx.conn) is not None
    if not console.is_terminal:
        usage = outcome.usage
        loop_view.record(
            console,
            "tick ended",
            tick=outcome.tick_id,
            status=outcome.status,
            elapsed_seconds=round(elapsed),
            summary=outcome.summary,
            workers=running,
            max_workers=ctx.config.capacity.max_workers,
            attention=len(after),
            cost_usd=f"{usage.cost_usd:.2f}" if usage is not None else None,
            tokens=usage.new_tokens if usage is not None else None,
            peak_context=usage.peak_context if usage is not None else None,
            **{f"derived_{verdict}": n for verdict, n in sorted((derived or {}).items())},
            paused=paused or None,
            idle_count=idle_count or None,
            wait_seconds=round(wait) if wait is not None and not paused else None,
        )
        for change in changes:
            msg, fields = _fields(change)
            loop_view.record(console, msg, tick=outcome.tick_id, **fields)
        return

    label = f"tick {outcome.tick_id}" if outcome.tick_id is not None else "tick"
    console.print(
        Text.assemble(
            (datetime.now(UTC).astimezone().strftime("%H:%M:%S"), "dim"),
            "  ",
            (label, "bold"),
            "  ",
            (outcome.status, _STATUS_STYLES.get(outcome.status, "bold")),
            "  ",
            (loop_view.duration(elapsed), "dim"),
            "  ",
            outcome.summary,
        ),
    )

    # Only the last column may give up width on a narrow terminal. rich shrinks wrappable columns first and, when every
    # column is no_wrap, shrinks them all alike, which drops the ticket key. So the last column is wrappable and its
    # cells (`_detail`) keep themselves to one line with an ellipsis.
    rows = Table.grid(padding=(0, 2))
    rows.add_column(width=2, no_wrap=True)
    rows.add_column(style="cyan", no_wrap=True)
    rows.add_column(no_wrap=True)
    rows.add_column(style="dim", ratio=1)
    for change in changes:
        rows.add_row(*_cells(change))
    if rows.row_count:
        console.print(rows)

    footer = Text("  ", style="dim")
    footer.append(f"workers {running}/{ctx.config.capacity.max_workers}")
    footer.append("  ·  ")
    footer.append(f"attention {len(after)}", style="bold yellow" if after else "dim")
    if outcome.usage is not None:
        footer.append(f"  ·  cost {outcome.usage.describe()}")
    if derived:
        footer.append(f"  ·  {phases.describe(derived)}", style="yellow" if derived["disagrees"] else "")
    if paused:
        footer.append("  ·  paused: no tick until resumed", style="yellow")
    elif wait is not None:
        idle = f"idle {idle_count}, " if idle_count else ""
        footer.append(f"  ·  {idle}next tick in {loop_view.duration(wait)} at {loop_view.clock_time(wait)}")
    console.print(footer)
    console.print()


@dataclass(frozen=True)
class _Change:
    """A line of a tick's report below its first: a decision that changes something, or the attention list's change."""

    #: A decision, an attention item added or resolved, or where a failed overseer's output was kept.
    kind: Literal["decision", "added", "resolved", "output"]
    #: The ticket or other subject it is about; empty for the output.
    subject: str = ""
    #: The decision's action, or the item's reason.
    what: str = ""
    #: The decision's rationale, the added item's detail, or the output's path. The overseer's text, unescaped.
    detail: str = ""


def _decisions(ctx: Context, tick_id: int, *, failed: bool) -> list[_Change]:
    """The tick's decisions that change something. Attention items are shown as the list's change instead.

    Returns:
        One for each, then where the overseer's output was kept when the tick `failed` and it was.
    """
    changes = [
        _Change("decision", attention.decided_about(d), d.action, d.rationale)
        for d in db.decisions_for_tick(ctx.conn, tick_id)
        if not d.action.startswith(attention.ACTION_PREFIX) and d.action not in _QUIET_ACTIONS
    ]
    output = ctx.state_dir / "ticks" / f"{tick_id}.log"
    if failed and output.exists():
        changes.append(_Change("output", detail=str(output)))
    return changes


def _attention_changes(before: Collection[attention.Item], after: Collection[attention.Item]) -> list[_Change]:
    """Items the tick added to the attention list, then items it resolved.

    Returns:
        A change for each.
    """
    had, has = attention.keys(before), attention.keys(after)
    added = [
        _Change("added", i.subject, i.reason, i.detail) for i in after if (i.ticket_key, i.reason, i.repo) not in had
    ]
    resolved = [_Change("resolved", i.subject, i.reason) for i in before if (i.ticket_key, i.reason, i.repo) not in has]
    return [*added, *resolved]


def _cells(change: _Change) -> tuple[Text, Text, Text, Text]:
    """A change as a terminal's row: a mark, its subject, what changed, and the detail.

    Returns:
        The row's cells. Text, never str: rich parses a str as markup, and rationales and details are the overseer's.
    """
    match change.kind:
        case "decision":
            action = change.what
            style = "red" if action.startswith("refused:") else "green" if action.startswith("dispatch:") else ""
            return Text(""), Text(change.subject), Text(action, style=style), _detail(change.detail)
        case "added":
            mark = Text("+", style="bold yellow")
            return mark, Text(change.subject), Text(change.what, style="yellow"), _detail(change.detail)
        case "resolved":
            mark = Text("-", style="bold green")
            return mark, Text(change.subject), Text(change.what, style="green"), _detail("resolved")
        case "output":
            # Not `_detail`: collapsing whitespace would print a path that does not exist.
            path = Text(change.detail, no_wrap=True, overflow="ellipsis")
            return Text(""), Text(""), Text("overseer output", style="red"), path
        case _:
            assert_never(change.kind)


def _fields(change: _Change) -> tuple[str, dict[str, object]]:
    """A change as a log line's `msg` and fields.

    Returns:
        The `msg`, and the fields after it.
    """
    match change.kind:
        case "decision":
            return "decision", {"subject": change.subject, "action": change.what, "rationale": change.detail}
        case "added":
            return "attention added", {"subject": change.subject, "reason": change.what, "detail": change.detail}
        case "resolved":
            return "attention resolved", {"subject": change.subject, "reason": change.what}
        case "output":
            return "overseer output", {"path": change.detail}
        case _:
            assert_never(change.kind)


def _detail(text: str) -> Text:
    """A last-column cell: one line, whitespace collapsed, cut with an ellipsis when the terminal is too narrow.

    Returns:
        The cell's text, set not to wrap.
    """
    return Text(" ".join(text.split()), no_wrap=True, overflow="ellipsis")
