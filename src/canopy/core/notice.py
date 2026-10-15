"""The operator's notice to workers (DESIGN §8, §22, ROADMAP M35): a passing condition every run that builds hears.

A notice is a journal fact, like the pause: its text, when and through which channel it was set, and when it lapses.
One is in force at a time; setting another ends the one before it, and a lapsed one reads as none, so nothing has to
delete it. `canopy notice`, and the web UI through the same functions, set and clear it; both refuse inside canopy's
own ticks and runs (`conversation.check_operator`), since a notice reaches every later run's prompt. Its text is
bounded when it is set, so no dispatch fails on a notice's size.

`implement`, `fix-ci`, and `resume` workers, reviews, and chores hear the one in force (`for_prompt`); a split hears
none. The overseer reads the recent ones (`recent`) to hold a failed check that ran while one was in force (§7).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core.conversation import Refused

if TYPE_CHECKING:
    import sqlite3

# A notice's own bound, apart from the standing instructions' (`prompts.MAX_STANDING_BYTES`): a sentence or two about
# an outage, in every prompt while it lasts.
MAX_BYTES = 1024
# How long a notice lasts without `--for`, and the longest it may: an outage is hours, and one that outlasts a week
# belongs in the standing instructions.
DEFAULT_MINUTES = 4 * 60
MAX_MINUTES = 7 * 24 * 60
# The overseer reads the notices in force or ended within this long, at most `RECENT_LIMIT` of them, newest first: a
# failed check from an outage stays held after the notice ends until a newer run of it exists (§7).
RECENT_DAYS = 7
RECENT_LIMIT = 5
# What a prompt's `{{NOTICE}}` says with none in force.
NONE = "None."
# `--for`'s form: a whole number of minutes, hours, or days.
_DURATION_RE = re.compile(r"([1-9][0-9]{0,5})([mhd])")
_UNIT_MINUTES = {"m": 1, "h": 60, "d": 24 * 60}


@dataclass(frozen=True)
class Notice:
    """A notice the operator set: its text, when and how it was set, when it lapses, and when it was ended early."""

    id: int
    text: str
    set_at: str
    channel: str
    lapses_at: str
    ended_at: str | None
    ended_channel: str | None

    @property
    def until(self) -> str:
        """When it stopped, or will stop, being in force: cleared or replaced, else when it lapses."""
        return self.ended_at if self.ended_at is not None and self.ended_at < self.lapses_at else self.lapses_at

    def in_force(self, now: datetime) -> bool:
        """Whether it is in force at `now`.

        Returns:
            True if it was neither cleared nor replaced, and has not yet lapsed.
        """
        return self.ended_at is None and db.parse_time(self.lapses_at) > now


def current(conn: sqlite3.Connection, now: datetime | None = None) -> Notice | None:
    """The notice in force at `now`, or None.

    Returns:
        The one notice that is neither ended nor lapsed, or None.
    """
    moment = db.format_time(now or datetime.now(UTC))
    row = conn.execute(
        "SELECT * FROM notices WHERE ended_at IS NULL AND lapses_at > ? ORDER BY id DESC LIMIT 1", (moment,)
    ).fetchone()
    return _notice(row) if row is not None else None


def for_prompt(conn: sqlite3.Connection) -> str | None:
    """The text of the notice in force, for a prompt's `{{NOTICE}}` or a chore's `## Run` object, or None without one.

    Returns:
        The notice's text, or None.
    """
    held = current(conn)
    return held.text if held is not None else None


def set_notice(conn: sqlite3.Connection, text: str, *, minutes: int | None, channel: str) -> Notice:
    """Set a notice for `minutes` (`DEFAULT_MINUTES` when None), ending the one in force, if any.

    Returns:
        The notice now in force.

    Raises:
        Refused: (`empty`) the text is blank; (`too_long`) it is over `MAX_BYTES` in UTF-8; (`bad_duration`) `minutes`
            is under 1 or over `MAX_MINUTES`.
    """
    body = text.strip()
    if not body:
        raise Refused("empty", "a notice needs text")
    size = len(body.encode("utf-8"))
    if size > MAX_BYTES:
        raise Refused("too_long", f"the notice is {size} bytes, over {MAX_BYTES}")
    lasts = DEFAULT_MINUTES if minutes is None else minutes
    if not 1 <= lasts <= MAX_MINUTES:
        raise Refused("bad_duration", f"a notice lasts 1 minute to {_duration(MAX_MINUTES)}, not {lasts} minutes")
    # One transaction, so two notices set at once cannot both be in force.
    with db.transaction(conn):
        moment = datetime.now(UTC)
        stamp = db.format_time(moment)
        conn.execute(
            "UPDATE notices SET ended_at = ?, ended_channel = ? WHERE ended_at IS NULL AND lapses_at > ?",
            (stamp, channel, stamp),
        )
        cur = conn.execute(
            "INSERT INTO notices (body, set_at, channel, lapses_at) VALUES (?, ?, ?, ?)",
            (body, stamp, channel, db.format_time(moment + timedelta(minutes=lasts))),
        )
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _notice(row)


def clear(conn: sqlite3.Connection, *, channel: str) -> Notice | None:
    """End the notice in force now.

    Returns:
        The notice it ended, or None if none was in force.
    """
    with db.transaction(conn):
        held = current(conn)
        if held is None:
            return None
        conn.execute("UPDATE notices SET ended_at = ?, ended_channel = ? WHERE id = ?", (db.now(), channel, held.id))
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (held.id,)).fetchone()
    return _notice(row)


def recent(conn: sqlite3.Connection, now: datetime) -> list[Notice]:
    """The notices in force at `now` or ended within `RECENT_DAYS` of it, newest first, at most `RECENT_LIMIT`.

    Returns:
        Those notices; none when the operator set none lately.
    """
    since = db.format_time(now - timedelta(days=RECENT_DAYS))
    rows = conn.execute(
        "SELECT * FROM notices WHERE lapses_at > ? AND (ended_at IS NULL OR ended_at > ?) "
        "AND set_at <= ? ORDER BY id DESC LIMIT ?",
        (since, since, db.format_time(now), RECENT_LIMIT),
    )
    return [_notice(r) for r in rows]


def moved_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether the operator set or cleared a notice after `since`, a time the journal wrote (§6, Idle pacing).

    A lapse is not a move: it is a gate (`lapses`).

    Returns:
        True if a notice was set, cleared, or replaced after `since`.
    """
    row = conn.execute("SELECT 1 FROM notices WHERE set_at > ? OR ended_at > ? LIMIT 1", (since, since))
    return row.fetchone() is not None


def lapses(conn: sqlite3.Connection, now: datetime) -> datetime | None:
    """When the notice in force at `now` lapses, a gate the loop's wait ends at (§6), or None without one.

    Returns:
        The lapse time, or None.
    """
    held = current(conn, now)
    return db.parse_time(held.lapses_at) if held is not None else None


def parse_duration(text: str) -> int:
    """Read `--for`'s duration: a whole number of minutes, hours, or days, such as `90m`, `4h`, or `2d`.

    Returns:
        The duration in minutes.

    Raises:
        Refused: (`bad_duration`) it is not in that form.
    """
    m = _DURATION_RE.fullmatch(text.strip())
    if m is None:
        raise Refused("bad_duration", f"{text!r} is not a duration such as 90m, 4h, or 2d")
    return int(m.group(1)) * _UNIT_MINUTES[m.group(2)]


def describe(held: Notice, now: datetime) -> str:
    """One terminal line on a notice for `canopy status` and `canopy notice`: its text, how set, and its time left.

    Returns:
        The line.
    """
    # Rounded up, so a notice just set for 4h says 4h left.
    left = max(0, math.ceil((db.parse_time(held.lapses_at) - now).total_seconds() / 60))
    # Control characters become spaces: the text may come from the web channel, and goes to the operator's terminal.
    text = " ".join("".join(c if c.isprintable() else " " for c in held.text).split())
    return f"Notice to workers ({held.channel}, {_duration(left)} left): {text}"


def _notice(row: sqlite3.Row) -> Notice:
    return Notice(
        id=int(row["id"]),
        text=str(row["body"]),
        set_at=str(row["set_at"]),
        channel=str(row["channel"]),
        lapses_at=str(row["lapses_at"]),
        ended_at=row["ended_at"],
        ended_channel=row["ended_channel"],
    )


def _duration(minutes: int) -> str:
    days, rest = divmod(minutes, _UNIT_MINUTES["d"])
    hours, rest = divmod(rest, _UNIT_MINUTES["h"])
    parts = [f"{n}{unit}" for n, unit in ((days, "d"), (hours, "h"), (rest, "m")) if n]
    return "".join(parts) or "0m"
