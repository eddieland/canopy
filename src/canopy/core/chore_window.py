"""When a chore's `days` and `hours` let a run start (DESIGN §19): clock times are a guard in code.

A chore with neither may start at any time. The window governs only when a run starts; one running when it closes runs
to its end or its timeout. Times are wall-clock times in the chore's `timezone`, or this machine's local time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from canopy.core.config import CHORE_DAYS, chore_hours

if TYPE_CHECKING:
    from datetime import tzinfo

    from canopy.core.config import Chore

_DAY = 24 * 60


def limited(chore: Chore) -> bool:
    """Whether the chore has a window at all."""
    return bool(chore.days) or chore.hours is not None


def is_open(chore: Chore, at: datetime) -> bool:
    """Whether a run of `chore` may start at `at`, an aware time."""
    local = at.astimezone(_zone(chore))
    if chore.days and CHORE_DAYS[local.weekday()] not in chore.days:
        return False
    start, end = _hours(chore)
    return start <= local.hour * 60 + local.minute < end


def next_open(chore: Chore, at: datetime) -> datetime:
    """The earliest time at or after `at` when a run of `chore` may start, in UTC."""
    if is_open(chore, at):
        return at.astimezone(UTC)
    zone = _zone(chore)
    today = at.astimezone(zone).date()
    start, _ = _hours(chore)
    # A day's window opens at its start; the first allowed day whose start is still ahead is the next one. Eight days
    # reach the same weekday again even when today's window has passed.
    for ahead in range(8):
        day = today + timedelta(days=ahead)
        if chore.days and CHORE_DAYS[day.weekday()] not in chore.days:
            continue
        opens = _wall(day, start, zone)
        if opens > at:
            return opens
    raise AssertionError("a chore's window opens within a week")  # days is never empty when it is set


def describe(chore: Chore) -> str:
    """The window for a person, as `mon,tue 08:00-18:00 America/New_York`."""
    days = ",".join(chore.days) if chore.days else "every day"
    hours = chore.hours or "all day"
    return f"{days} {hours} {chore.timezone or 'local time'}"


def _hours(chore: Chore) -> tuple[int, int]:
    return chore_hours(chore.hours) if chore.hours is not None else (0, _DAY)


def _zone(chore: Chore) -> tzinfo | None:
    """The chore's zone. None is this machine's local time, which `astimezone` reads with its own DST rules."""
    return ZoneInfo(chore.timezone) if chore.timezone is not None else None


def _wall(day: date, minutes: int, zone: tzinfo | None) -> datetime:
    """The UTC time of a wall-clock time on `day` in `zone`, or in local time when `zone` is None."""
    wall = datetime.combine(day, time(minutes // 60, minutes % 60))
    local = wall.replace(tzinfo=zone) if zone is not None else wall.astimezone()
    return local.astimezone(UTC)
