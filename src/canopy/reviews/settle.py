"""When a PR's head commit may be reviewed: once it has been seen for `review.settle_minutes` (DESIGN §21, Settling).

The clock starts the first time the overseer asks `canopy review run` for a head, which it does once the head's checks
pass. A push is a new head and starts over, so a PR pushed to again and again is reviewed once it goes quiet, not at
every commit. A dry run reads the clock but never starts it (D036).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Config


@dataclass(frozen=True)
class Head:
    """A PR's head commit, when it was first seen, and when a review of it may start."""

    pr: str
    sha: str
    seen_at: datetime
    settles_at: datetime


def on(config: Config) -> bool:
    """Return whether reviews wait for a head to settle: `review.settle_minutes` above 0."""
    return config.review.settle_minutes > 0


def see(conn: sqlite3.Connection, config: Config, pr: str, sha: str, *, record: bool, now: datetime) -> Head | None:
    """The PR's head `sha` as seen now: recorded first if `record` and it is new, else as it would be.

    Returns:
        The head with its settle time, or None when settling is off; then nothing is recorded.
    """
    if not on(config):
        return None
    at = db.format_time(now)
    stamp = db.see_review_head(conn, pr, sha, at) if record else db.review_head_seen_at(conn, pr, sha)
    return _head(config, pr, sha, db.parse_time(stamp or at))


def settling(conn: sqlite3.Connection, config: Config, now: datetime) -> list[Head]:
    """The PR heads still settling at `now`, newest first: seen less than the settle time ago and not reviewed `done`.

    Returns:
        The heads; none when settling is off.
    """
    if not on(config):
        return []
    since = db.format_time(now - timedelta(minutes=config.review.settle_minutes))
    rows = db.review_heads_seen_after(conn, since)
    return [_head(config, str(r["pr_url"]), str(r["sha"]), db.parse_time(str(r["seen_at"]))) for r in rows]


def next_settle(conn: sqlite3.Connection, config: Config, now: datetime) -> datetime | None:
    """When the first head still settling at `now` settles: a gate for idle pacing (DESIGN §6).

    Returns:
        The earliest settle time after `now`, or None if no head is settling.
    """
    return min((h.settles_at for h in settling(conn, config, now)), default=None)


def _head(config: Config, pr: str, sha: str, seen_at: datetime) -> Head:
    return Head(pr, sha, seen_at, seen_at + timedelta(minutes=config.review.settle_minutes))
