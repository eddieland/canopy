"""How long `canopy loop` waits after a tick: longer after idle ticks in a row, never past a gate (DESIGN §6, D083).

A tick is idle when the journal shows it found nothing new and changed nothing (`idle`). After the n-th idle tick in a
row the wait is `base * 2^n`, up to the cap and never below `base`; a `fix-ci` cooldown's end or a chore's `due_at`
still ahead ends it sooner (`gate`). While the loop waits, a run that ends after the tick read the journal (`read_at`)
wakes it, as an operator message does. With the cap not above `base`, idle pacing is off: the wait is `base`, no
gate shortens it, and only an operator message wakes it.

The count lives in the loop, not the journal, so a restarted loop starts at `base`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import chore_view, db
from canopy.loop import attention
from canopy.runs import policy

if TYPE_CHECKING:
    from datetime import datetime

    from canopy.core.context import Context
    from canopy.loop import tick

# Refusals that lift by themselves, so a tick that records only these may be idle: on a run or chore run ending
# (`running`, `capacity`, `chore_capacity`), at a gate (`cooldown`, `not_due`, `outside_hours`), or never
# (`attempt_limit`, which an attention item reports).
QUIET_REFUSALS = frozenset(
    {"running", "capacity", "chore_capacity", "cooldown", "not_due", "outside_hours", "attempt_limit"}
)
# Decisions that change nothing: a wait, and a ticket's skip (a tick-wide skip closes the tick `skipped`).
_QUIET_ACTIONS = frozenset({"wait", "skip"})


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
        """The wait after the `idle_count`-th idle tick in a row, before any gate shortens it."""
        if not self.on or idle_count <= 0:
            return self.base_seconds
        return max(self.base_seconds, min(self.base_seconds * 2**idle_count, self.cap_seconds))


@dataclass(frozen=True)
class Before:
    """What the loop read before a tick, to tell afterwards whether the tick changed anything."""

    attention: list[attention.Item]
    tickets: frozenset[tuple[object, ...]]


def before(ctx: Context) -> Before:
    """Read the attention list and every ticket's and unit's state, before a tick."""
    return Before(attention.listed(ctx), db.tickets_snapshot(ctx.conn))


def idle(ctx: Context, outcome: tick.Outcome, seen: Before) -> bool:
    """Whether the tick that ended with `outcome` was idle, read from the journal (DESIGN §6, Idle pacing).

    It closed `ok`; it decided nothing but waits, skips, attention items, and refusals that lift by themselves; the
    attention list and every ticket and unit are as `seen` before it; and no run started or ended and no operator
    message was recorded after the previous tick read the journal. Without a previous tick that read it, not idle.
    """
    if outcome.status != "ok" or outcome.tick_id is None:
        return False
    previous = db.previous_tick(ctx.conn, outcome.tick_id)
    if previous is None or previous["read_at"] is None or previous["message_id"] is None:
        return False
    return (
        all(_quiet(str(d["action"])) for d in db.decisions_for_tick(ctx.conn, outcome.tick_id))
        and attention.keys(attention.listed(ctx)) == attention.keys(seen.attention)
        and db.tickets_snapshot(ctx.conn) == seen.tickets
        and not db.runs_moved_after(ctx.conn, str(previous["read_at"]))
        and db.latest_message_id(ctx.conn, source="operator") <= int(previous["message_id"])
    )


def _quiet(action: str) -> bool:
    guard = action.removeprefix("refused:")
    return (
        action in _QUIET_ACTIONS
        or action.startswith(attention.ACTION_PREFIX)
        or (guard != action and guard in QUIET_REFUSALS)
    )


def gate(ctx: Context, now: datetime) -> datetime | None:
    """The earliest harness gate still ahead of `now`: a `fix-ci` cooldown's end or a configured chore's `due_at`.

    One already open sets none, so a chore the overseer passed over cannot make the loop spin.
    """
    cooldowns = policy.fix_ci_cooldowns(ctx.conn, ctx.config, now).values()
    dues = [d for s in chore_view.states(ctx.conn, ctx.config, ctx.workspace) if (d := s.due_at(now)) is not None]
    return min((t for t in (*cooldowns, *dues) if t > now), default=None)


def wait(ctx: Context, pace: Pace, idle_count: int, now: datetime) -> float:
    """Seconds to wait after a tick ending at `now`: `pace` after `idle_count`, ended sooner by a gate when it is on."""
    chosen = pace.after(idle_count)
    if not pace.on:
        return chosen
    opens = gate(ctx, now)
    return chosen if opens is None else min(chosen, (opens - now).total_seconds())


def read_at(ctx: Context, outcome: tick.Outcome) -> str | None:
    """When the tick read the journal, if it got that far; a run ending after it wakes the wait."""
    if outcome.tick_id is None:
        return None
    row = db.get_tick(ctx.conn, outcome.tick_id)
    return None if row is None or row["read_at"] is None else str(row["read_at"])
