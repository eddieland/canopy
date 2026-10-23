"""How long `canopy loop` waits after a tick: longer after idle ticks in a row, never past a gate (DESIGN §6).

A tick is idle when it dispatched nothing and nothing reached the journal after the tick before read it (`idle`).
After the n-th idle tick in a row the wait is `base * 2^n`, up to the cap and never below `base`; the CI cooldown's end
or a chore's `due_at` still ahead, or the lapse of the operator's notice to workers, ends it sooner (`gate`). While the
loop waits, a run that ends after the tick read the journal (`read_at`) wakes it, as the operator's own acts do. With
the cap not above `base`, idle pacing is off: the wait is `base`, no gate shortens it, and only the operator's acts
wake it: a message, a start or stop, a grant, or a notice set or cleared.

The count lives in the loop, not the journal, so a restarted loop starts at `base`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import chore_view, db, notice, tasks
from canopy.core.items import subject
from canopy.core.vocab import TickStatus
from canopy.loop import attention
from canopy.runs import policy

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from canopy.core.context import Context
    from canopy.loop import tick

#: The prefix of a decision that starts a run: a worker's (`dispatch:<kind>`), a review's, or a chore's. A dry run
#: records these without starting the run, so `idle` reads the decision, not the run.
DISPATCH_PREFIX = "dispatch:"


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
    """What the loop read before a tick, to tell afterwards what the tick changed (`churn`)."""

    attention: Sequence[attention.Item]
    phases: Mapping[tuple[str, str | None], str | None]


def before(ctx: Context) -> Before:
    """Read the attention list and every ticket's and unit's phase, before a tick.

    Returns:
        What `churn` compares the journal with after the tick.
    """
    return Before(attention.listed(ctx), db.phases(ctx.conn))


def idle(ctx: Context, outcome: tick.Outcome) -> bool:
    """Whether the tick that ended with `outcome` was idle, read from the journal (DESIGN §6, Idle pacing).

    It closed `ok`, dispatched no run, and no run started or ended, and the operator recorded no message, started or
    stopped no ticket, granted nothing, and set or cleared no notice, after the previous tick read the journal. What it
    recorded besides (waits, refusals, `done`, mirrors, attention items, phases) does not count: none of it starts work.
    Without a previous tick that read it, not idle.

    Returns:
        True if the tick was idle.
    """
    if outcome.status != TickStatus.OK or outcome.tick_id is None:
        return False
    previous = db.previous_tick(ctx.conn, outcome.tick_id)
    if previous is None or previous.read_at is None or previous.message_id is None:
        return False
    return not any(
        d.action.startswith(DISPATCH_PREFIX) for d in db.decisions_for_tick(ctx.conn, outcome.tick_id)
    ) and _nothing_since(ctx, previous.read_at, previous.message_id)


def count(ctx: Context, outcome: tick.Outcome, idle_count: int, *, idle: bool, on: bool) -> int:
    """The idle ticks in a row after the tick that ended with `outcome`, `idle` or not, from `idle_count` before it.

    Idle pacing paces only the overseer's runs (DESIGN §39): an `ok` tick that ran none cost nothing and leaves the
    count as it was. Any other tick adds one when it was idle with pacing `on`, and starts the count again otherwise, a
    tick halted before its overseer among them, as one that failed does.

    Returns:
        The count.
    """
    if outcome.status == TickStatus.OK and outcome.tick_id is not None:
        row = db.get_tick(ctx.conn, outcome.tick_id)
        if row is not None and row.overseer_ran is False:
            return idle_count
    return idle_count + 1 if on and idle else 0


def churn(ctx: Context, outcome: tick.Outcome, seen: Before) -> list[str]:
    """What the tick changed with nothing new in the journal to change it for (DESIGN §6, Idle pacing; ROADMAP M28).

    Measured, not acted on: an `ok` tick that changed a ticket's or unit's phase, or the attention list, when no run
    started or ended, the operator neither wrote, started, stopped, nor granted anything, and no gate opened since the
    previous tick read the journal. The world may still have changed, or the config, which the journal does not hold:
    only the decisions table tells a flap from a real change.

    Returns:
        A line per phase changed and per attention item added (`+`) or dropped (`-`); none when the tick is not churn.
    """
    if outcome.status != TickStatus.OK or outcome.tick_id is None:
        return []
    previous, row = db.previous_tick(ctx.conn, outcome.tick_id), db.get_tick(ctx.conn, outcome.tick_id)
    if previous is None or previous.read_at is None or previous.message_id is None or row is None:
        return []
    if not _nothing_since(ctx, previous.read_at, previous.message_id) or row.read_at is None:
        return []
    opens = gate(ctx, db.parse_time(previous.read_at))
    if opens is not None and opens <= db.parse_time(row.read_at):
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


def _nothing_since(ctx: Context, read_at: str, message_id: int) -> bool:
    """Whether nothing the journal holds for a tick to act on happened after a tick read it, at `read_at`.

    No run of any table started or ended, and the operator recorded no message, started or stopped no ticket, granted
    nothing, set or cleared no notice, and submitted, replied to, or stopped no task, past `message_id`, the newest
    message that tick had read.

    Returns:
        True if nothing did.
    """
    return (
        not db.runs_moved_after(ctx.conn, read_at)
        and db.latest_message_id(ctx.conn, source="operator") <= message_id
        and not db.starts_moved_after(ctx.conn, read_at)
        and not db.granted_after(ctx.conn, read_at)
        and not notice.moved_after(ctx.conn, read_at)
        and not tasks.moved_after(ctx.conn, read_at)
    )


def gate(ctx: Context, now: datetime) -> datetime | None:
    """The earliest harness gate still ahead of `now`: a cooldown's end, a chore's `due_at`, or a notice's lapse.

    A CI cooldown's end, a configured chore's `due_at`, and the lapse of the notice in force, so work held for the
    notice resumes when it lapses. One already open sets none, so a chore the overseer passed over cannot make the loop
    spin.

    Returns:
        The time the earliest gate opens, or None if none is still ahead.
    """
    cooldowns = policy.ci_cooldowns(ctx.conn, ctx.config, now).values()
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
    return None if row is None else row.read_at
