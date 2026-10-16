"""How long `canopy loop` waits after a tick: longer after idle ticks in a row, never past a gate (DESIGN §6).

A tick is idle when the journal shows it found nothing new and changed nothing (`idle`). After the n-th idle tick in a
row the wait is `base * 2^n`, up to the cap and never below `base`; a `fix-ci` cooldown's end or a chore's `due_at`
still ahead, or the lapse of the operator's notice to workers, ends it sooner (`gate`). While the loop waits, a run that
ends after the tick read the journal (`read_at`) wakes it, as the operator's own acts do. With the cap not above
`base`, idle pacing is off: the wait is `base`, no gate shortens it, and only the operator's acts wake it: a message,
a start or stop, a grant, or a notice set or cleared.

The count lives in the loop, not the journal, so a restarted loop starts at `base`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import chore_view, db, notice
from canopy.core.items import subject
from canopy.loop import attention, duties
from canopy.runs import policy

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from canopy.core.context import Context
    from canopy.loop import tick

# Refusals that lift by themselves, so a tick that records only these may be idle: on a run or chore run ending
# (`running`, `capacity`, `chore_capacity`), at a gate (`cooldown`, `not_due`, `outside_hours`), or never
# (`attempt_limit`, which an attention item reports).
QUIET_REFUSALS = frozenset(
    {"running", "capacity", "chore_capacity", "cooldown", "not_due", "outside_hours", "attempt_limit"}
)
# Decisions that change nothing: a wait, a ticket's skip (a tick-wide skip closes the tick `skipped`), and the record
# that the query ran, which a tick makes whenever it is due.
_QUIET_ACTIONS = frozenset({"wait", "skip", duties.QUERIED_ACTION})


@dataclass(frozen=True)
class Pace:
    """The pacing rule: `base` after a tick that is not idle, doubling per idle tick in a row up to `cap`."""

    base_seconds: float
    cap_seconds: float

    @property
    def on(self) -> bool:
        """Whether idle pacing is on: only with a cap above `base`."""
        return self.cap_seconds > self.base_seconds

    def after(self, idle_count: int) -> float:
        """The wait after the `idle_count`-th idle tick in a row, before any gate shortens it.

        Returns:
            Seconds: `base` with pacing off or no idle tick, else `base * 2^idle_count` held between `base` and `cap`.
        """
        if not self.on or idle_count <= 0:
            return self.base_seconds
        return max(self.base_seconds, min(self.base_seconds * 2**idle_count, self.cap_seconds))


@dataclass(frozen=True)
class Before:
    """What the loop read before a tick, to tell afterwards whether the tick changed anything."""

    attention: list[attention.Item]
    tickets: frozenset[tuple[object, ...]]
    phases: dict[tuple[str, str | None], str | None]


def before(ctx: Context) -> Before:
    """Read the attention list and every ticket's and unit's state, before a tick.

    Returns:
        What `idle` and `churn` compare the journal with after the tick.
    """
    return Before(attention.listed(ctx), db.tickets_snapshot(ctx.conn), db.phases(ctx.conn))


def idle(ctx: Context, outcome: tick.Outcome, seen: Before) -> bool:
    """Whether the tick that ended with `outcome` was idle, read from the journal (DESIGN §6, Idle pacing).

    It closed `ok`; it decided nothing but waits, skips, attention items, and refusals that lift by themselves; the
    attention list and every ticket and unit are as `seen` before it; and no run started or ended, and the operator
    recorded no message, started or stopped no ticket, granted nothing, and set or cleared no notice, after the previous
    tick read the journal.
    Without a previous tick that read it, not idle.

    Returns:
        True if the tick was idle.
    """
    if outcome.status != "ok" or outcome.tick_id is None:
        return False
    previous = db.previous_tick(ctx.conn, outcome.tick_id)
    if previous is None or previous["read_at"] is None or previous["message_id"] is None:
        return False
    return (
        all(_quiet(d.action) for d in db.decisions_for_tick(ctx.conn, outcome.tick_id))
        and attention.keys(attention.listed(ctx)) == attention.keys(seen.attention)
        and db.tickets_snapshot(ctx.conn) == seen.tickets
        and _nothing_since(ctx, previous)
    )


def churn(ctx: Context, outcome: tick.Outcome, seen: Before) -> list[str]:
    """What the tick changed with nothing new in the journal to change it for (DESIGN §6, Idle pacing; ROADMAP M28).

    Measured, not acted on: an `ok` tick that changed a ticket's or unit's phase, or the attention list, when no run
    started or ended, the operator neither wrote, started, stopped, nor granted anything, and no gate opened since the
    previous tick read the journal. The world may still have changed, or the config, which the journal does not hold:
    only the decisions table tells a flap from a real change.

    Returns:
        A line per phase changed and per attention item added (`+`) or dropped (`-`); none when the tick is not churn.
    """
    if outcome.status != "ok" or outcome.tick_id is None:
        return []
    previous, row = db.previous_tick(ctx.conn, outcome.tick_id), db.get_tick(ctx.conn, outcome.tick_id)
    if previous is None or previous["read_at"] is None or previous["message_id"] is None or row is None:
        return []
    if not _nothing_since(ctx, previous) or row["read_at"] is None:
        return []
    opens = gate(ctx, db.parse_time(str(previous["read_at"])))
    if opens is not None and opens <= db.parse_time(str(row["read_at"])):
        return []
    now = db.phases(ctx.conn)
    lines = [
        f"{subject(key, repo)} phase {seen.phases[key, repo]} -> {phase}"
        for (key, repo), phase in sorted(now.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
        if (key, repo) in seen.phases and seen.phases[key, repo] != phase
    ]
    after, earlier = attention.keys(attention.listed(ctx)), attention.keys(seen.attention)
    lines += [f"+{subject(k, repo)} {reason}" for k, reason, repo in sorted(after - earlier, key=_item_order)]
    lines += [f"-{subject(k, repo)} {reason}" for k, reason, repo in sorted(earlier - after, key=_item_order)]
    return lines


def _item_order(item: tuple[str | None, str, str | None]) -> tuple[str, str, str]:
    return (item[0] or "", item[1], item[2] or "")


def _nothing_since(ctx: Context, previous: sqlite3.Row) -> bool:
    """Whether nothing the journal holds for a tick to act on happened after `previous` read it.

    No run, chore run, or review run started or ended, and the operator recorded no message, started or stopped no
    ticket, granted nothing, and set or cleared no notice.

    Returns:
        True if nothing did.
    """
    since = str(previous["read_at"])
    return (
        not db.runs_moved_after(ctx.conn, since)
        and db.latest_message_id(ctx.conn, source="operator") <= int(previous["message_id"])
        and not db.starts_moved_after(ctx.conn, since)
        and not db.granted_after(ctx.conn, since)
        and not notice.moved_after(ctx.conn, since)
    )


def _quiet(action: str) -> bool:
    guard = action.removeprefix("refused:")
    return (
        action in _QUIET_ACTIONS
        or action.startswith(attention.ACTION_PREFIX)
        or (guard != action and guard in QUIET_REFUSALS)
    )


def gate(ctx: Context, now: datetime) -> datetime | None:
    """The earliest harness gate still ahead of `now`: a cooldown's end, a chore's `due_at`, or a notice's lapse.

    A `fix-ci` cooldown's end, a configured chore's `due_at`, and the lapse of the notice in force, so work held for the
    notice resumes when it lapses. One already open sets none, so a chore the overseer passed over cannot make the loop
    spin.

    Returns:
        The time the earliest gate opens, or None if none is still ahead.
    """
    cooldowns = policy.fix_ci_cooldowns(ctx.conn, ctx.config, now).values()
    dues = [d for s in chore_view.states(ctx.conn, ctx.config, ctx.workspace) if (d := s.due_at(now)) is not None]
    lapse = notice.lapses(ctx.conn, now)
    return min((t for t in (*cooldowns, *dues, *([lapse] if lapse else [])) if t > now), default=None)


def wait(ctx: Context, pace: Pace, idle_count: int, now: datetime) -> float:
    """Seconds to wait after a tick ending at `now`: `pace` after `idle_count`, ended sooner by a gate when it is on.

    Returns:
        The wait in seconds, at most `pace`'s and no later than the next gate opens when pacing is on.
    """
    chosen = pace.after(idle_count)
    if not pace.on:
        return chosen
    opens = gate(ctx, now)
    return chosen if opens is None else min(chosen, (opens - now).total_seconds())


def read_at(ctx: Context, outcome: tick.Outcome) -> str | None:
    """When the tick read the journal, if it got that far; a run ending after it wakes the wait.

    Returns:
        The journal's timestamp of the read, or None if the tick recorded none.
    """
    if outcome.tick_id is None:
        return None
    row = db.get_tick(ctx.conn, outcome.tick_id)
    return None if row is None or row["read_at"] is None else str(row["read_at"])
