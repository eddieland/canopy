"""Attention items: what needs a human, as the attention list, `attention.md`, and every notification name them.

The list itself is derived in `canopy.loop.attention` (DESIGN §14); this is the shape it has, shared with the features
that deliver it (`canopy.notify`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from canopy.core import db

#: An attention item is a decision whose action is this prefix and its reason (D020).
ACTION_PREFIX = "attention:"


@dataclass(frozen=True)
class Item:
    """One attention item: a ticket or a repository, why it needs a human, and since when.

    An item about a repository, such as `repo_missing`, has `repo` set and no ticket key. An item about a chore has
    `chore:<name>` as its ticket key; a chore's finding has the finding's id as its reason and `finding` set.
    """

    ticket_key: str | None
    reason: str
    detail: str
    since: str  # created_at of the first tick in the unbroken run of ticks that recorded this item
    repo: str | None = None
    finding: bool = False

    @property
    def subject(self) -> str:
        """What the item is about, for display: `PROJ-1`, `api`, or `PROJ-1 (api)`."""
        return subject(self.ticket_key, self.repo)


def subject(ticket_key: str | None, repo: str | None) -> str:
    """Name an item's ticket, its repository, or both, for display.

    Returns:
        The ticket key with the repository in parentheses when both are set, whichever one is set otherwise, or `-`
        when neither is.
    """
    if ticket_key is None:
        return repo or "-"
    return f"{ticket_key} ({repo})" if repo else ticket_key


def fingerprint(ticket_key: str | None, reason: str, repo: str | None = None) -> str:
    """Identify an item across ticks. The detail is left out: rewording it does not make a new item.

    An item without a repository has the fingerprint it had before items could have one, so none is notified again.

    Returns:
        The hex SHA-256 of the ticket key, reason, and repository.
    """
    text = f"{ticket_key or ''}\0{reason}" + (f"\0{repo}" if repo is not None else "")
    return hashlib.sha256(text.encode()).hexdigest()


def age(timestamp: str, now: datetime | None = None) -> str:
    """Return how long ago `timestamp` was, in its largest whole unit: `3d`, `2h`, `5m`, `40s`.

    Returns:
        The age as a whole number and a unit. A timestamp in the future is `0s`.
    """
    seconds = max(0, int(((now or datetime.now(UTC)) - db.parse_time(timestamp)).total_seconds()))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def one_line(text: str) -> str:
    """`text` with its whitespace, line breaks included, collapsed to single spaces.

    Returns:
        `text` on one line, with no leading or trailing whitespace.
    """
    return " ".join(text.split())
