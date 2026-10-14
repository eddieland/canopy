"""When a PR's head commit may be reviewed: once it has been seen for `review.settle_minutes` (DESIGN §21, Settling).

The clock starts the first time the overseer asks `canopy review run` for a head, which it does once the head's checks
pass, so the wait gives a human reviewer, and any later push, time to come first. A new push is a new head and starts
over, so a PR pushed to again and again is reviewed once it goes quiet, not at every commit. A dry run reads the clock
but never starts it (D036).
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


def heads(conn: sqlite3.Connection, config: Config, since: datetime, limit: int) -> list[Head]:
    """Each PR's newest head seen since `since` with no `done` review of it, newest first, at most `limit`.

    Returns:
        The heads, settled or not; none when settling is off.
    """
    if not on(config):
        return []
    rows = db.unreviewed_review_heads(conn, db.format_time(since), limit)
    return [_head(config, str(r["pr_url"]), str(r["sha"]), db.parse_time(str(r["seen_at"]))) for r in rows]


def next_settle(conn: sqlite3.Connection, config: Config, now: datetime) -> datetime | None:
    """When the first head still settling at `now` settles: a gate for idle pacing (DESIGN §6).

    Returns:
        The earliest settle time after `now`, or None if no head is settling.
    """
    window = timedelta(minutes=config.review.settle_minutes)
    # Every head still settling was seen within one settle time, and a PR has one newest head. SQLite's -1 is no limit.
    found = heads(conn, config, now - window, limit=-1)
    return min((h.settles_at for h in found if h.settles_at > now), default=None)


def _head(config: Config, pr: str, sha: str, seen_at: datetime) -> Head:
    return Head(pr, sha, seen_at, seen_at + timedelta(minutes=config.review.settle_minutes))
