"""Notifications and their outbox.

The outbox the sinks read, each sink's place in it, and what each was sent (DESIGN §20).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row


@dataclass(frozen=True)
class Notification(Row):
    """A notification a sink was sent (DESIGN §20), kept so the same one is not sent twice."""

    TABLE: ClassVar[LiteralString] = "notifications"

    sink: str
    fingerprint: str
    ticket_key: str | None
    reason: str
    repo: str | None
    sent_at: str


@dataclass(frozen=True)
class NotifyEvent(Row):
    """An event in the outbox the notification sinks read (DESIGN §20)."""

    TABLE: ClassVar[LiteralString] = "notify_events"

    id: int
    grp: str
    kind: str
    at: str
    #: A JSON object of the event's fields.
    fields: str


@dataclass(frozen=True)
class NotifySink(Row):
    """A notification sink's place in the outbox (DESIGN §20), and how its deliveries have gone."""

    TABLE: ClassVar[LiteralString] = "notify_sinks"

    name: str
    #: The newest event it was delivered.
    cursor: int
    created_at: str
    last_delivery_at: str | None
    last_digest_at: str | None
    failures: int
    last_error: str | None
