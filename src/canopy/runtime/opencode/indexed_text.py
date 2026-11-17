"""What an index of every OpenCode 1 session's text reads (ROADMAP M72, stage 2): nothing.

OpenCode 1 is deprecated, and its record's text has no reader (`canopy.runtime.opencode.session_text`), so under it
`sessions.search = "text"` searches titles, as `titles` does, and says why (`unindexed`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.opencode.session_text import UNSUPPORTED
from canopy.runtime.report import HeadPage, KeptIds, SessionTexts

if TYPE_CHECKING:
    from canopy.runtime.report import MessageText, SessionCursor, SessionHead


def unindexed() -> str | None:
    """Say why OpenCode 1's text cannot be indexed.

    Returns:
        Why, in canopy's words.
    """
    return UNSUPPORTED


def heads(cursor: SessionCursor | None, *, newest_first: bool, limit: int) -> HeadPage:  # noqa: ARG001 # the surface's
    """Read no session.

    Returns:
        `failed`, with why.
    """
    return HeadPage("failed", error=UNSUPPORTED)


def texts(head: SessionHead, *, max_messages: int, max_chars: int, max_total: int) -> SessionTexts:  # noqa: ARG001
    """Read no session's text.

    Returns:
        `failed`.
    """
    return SessionTexts("failed")


def message(record: str, session: str, message_id: str, *, max_chars: int) -> list[MessageText] | None:  # noqa: ARG001
    """Read no message.

    Returns:
        None.
    """
    return None


def kept() -> KeptIds:
    """Read no session's id.

    Returns:
        `failed`.
    """
    return KeptIds("failed")
