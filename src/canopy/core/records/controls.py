"""The operator's tables: what they set, granted, and said, and what the web UI let them write.

Starts, forgets, attachments, what they have seen, conversations, notices, the pause, grants past a limit, and the
web UI's record of each write it let through (DESIGN §22, TRUST_MODEL T8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    RunKind,
    SeenKind,
    StartStatus,
)


@dataclass(frozen=True)
class Forget(Row):
    """One time the operator forgot a ticket's work (DESIGN §22), and what it dropped; its row holds the latest."""

    TABLE: ClassVar[LiteralString] = "forgets"

    id: int
    ticket_key: str
    at: str
    # `cli` or `web`; None, with `prs`, for a forget made before forgets were recorded.
    channel: str | None
    # The ticket's newest run and message then: the loop reads only later ones.
    run_id: int | None
    message_id: int | None
    branch: str | None
    # A JSON array of its units' PR URLs.
    prs: str | None


@dataclass(frozen=True)
class Attachment(Row):
    """A text file the operator attached to a ticket or a task, for its runs to read as data (DESIGN §22)."""

    TABLE: ClassVar[LiteralString] = "attachments"

    id: int
    #: `ticket` and the ticket's key, or `task` and its id.
    subject_kind: str
    subject_id: str
    #: What runs see it as: a plain file name, unique among the subject's attachments not removed.
    name: str
    #: The bytes of its text as kept, and their SHA-256, hex.
    size: int
    sha256: str
    #: `cli` or `web`: where the operator attached it.
    channel: str
    added_at: str
    #: When the operator removed it, and through which channel; both None while it is attached.
    removed_at: str | None
    removed_channel: str | None


@dataclass(frozen=True)
class Start(Row):
    """The operator's start of a subject worked privately (DESIGN §22): the authorization, written only by them."""

    TABLE: ClassVar[LiteralString] = "starts"

    subject_kind: str
    subject_id: str
    status: StartStatus
    started_at: str
    # When the operator stopped it; None while it is started.
    stopped_at: str | None
    # The channel of the latest start or stop.
    channel: str


@dataclass(frozen=True)
class TicketGrant(Row):
    """Runs the operator granted a ticket past its limit for a kind counted per ticket (DESIGN §22, §25)."""

    TABLE: ClassVar[LiteralString] = "ticket_grants"

    id: int
    ticket_key: str
    kind: RunKind
    runs: int
    granted_at: str


@dataclass(frozen=True)
class Message(Row):
    """A message in a subject's conversation (DESIGN §22): a worker's report or question, or a reply to one."""

    TABLE: ClassVar[LiteralString] = "messages"

    id: int
    #: `ticket` and the ticket's key, `chore` and its name, or `task` and its id.
    subject_kind: str
    subject_id: str
    at: str
    #: `worker`, `operator`, or `tracker`.
    source: str
    #: `report` or `question`, a worker's; `reply`, the operator's; `comment`, a tracker comment a source observed.
    kind: str
    #: `run`, `cli`, `web`, `slack`, or `tracker`.
    channel: str
    run_id: int | None
    body: str
    #: The message a reply answers, when the channel knows it.
    answers: int | None
    submission: str | None
    comment_id: str | None
    author: str | None
    commented_at: str | None
    truncated: bool
    #: A task's run that reported it, as `run_id` names a ticket's (DESIGN §36).
    task_run_id: int | None


@dataclass(frozen=True)
class Notice(Row):
    """A notice the operator set for the overseer, until it lapses or is ended."""

    TABLE: ClassVar[LiteralString] = "notices"

    id: int
    body: str
    set_at: str
    channel: str
    lapses_at: str
    ended_at: str | None
    ended_channel: str | None


@dataclass(frozen=True)
class Pause(Row):
    """The loop's pause, while the operator has it paused."""

    TABLE: ClassVar[LiteralString] = "pause"

    id: int
    paused_at: str
    channel: str


@dataclass(frozen=True)
class Seen(Row):
    """A subject whose result the operator has seen (DESIGN §22), named as its reference names it."""

    TABLE: ClassVar[LiteralString] = "seen"

    #: The kind of subject: a reference's kind, such as `review` for `review:4`.
    kind: SeenKind
    #: The subject's id within its kind: a review run's id, as text.
    subject: str
    #: When the operator first saw it; for a review that had ended before the table, when it ended.
    at: str
    #: Where they saw it, `cli` or `web`; None for what was taken as seen when the table was made.
    channel: str | None


@dataclass(frozen=True)
class AttemptGrant(Row):
    """Attempts the operator granted a ticket's runs of one kind past its limit."""

    TABLE: ClassVar[LiteralString] = "attempt_grants"

    id: int
    ticket_key: str
    repo: str
    kind: RunKind
    runs: int
    granted_at: str


@dataclass(frozen=True)
class WebWrite(Row):
    """A write request the web UI's server let through, or a sign-in, as it answered it (TRUST_MODEL T8)."""

    TABLE: ClassVar[LiteralString] = "web_writes"

    id: int
    #: When the request came in.
    at: str
    method: str
    #: The request's path, without its query, at most 512 characters.
    path: str
    #: The HTTP status it was answered with.
    code: int
    #: The peer's address, as the server saw it.
    client: str | None
    #: A fingerprint of the session it was let through as or signed in; None on the mock server, which signs nobody in.
    session: str | None
