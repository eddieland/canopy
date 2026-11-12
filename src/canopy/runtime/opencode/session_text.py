"""The text of every OpenCode 1 session (ROADMAP M72), which `canopy sessions` does not read.

OpenCode 2 reads the sessions OpenCode 1 left, and keeps every new one in tables of its own, which
`canopy.runtime.opencode2.session_text` reads. OpenCode 1 is deprecated, so its record's text has no reader: under it,
the measurement says so, and reads nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.report import SessionRecord

if TYPE_CHECKING:
    from collections.abc import Collection, Generator, Sequence

    from canopy.runtime.report import TextPart, TextRow

#: Why nothing is read, in canopy's words.
UNSUPPORTED = (
    "runtime.version 1 is deprecated, and its sessions' text has no reader: canopy sessions reads OpenCode 2's record"
)


def record() -> SessionRecord:
    """Read nothing: OpenCode 1's sessions are not measured.

    Returns:
        `unsupported`, with why.
    """
    return SessionRecord("unsupported", error=UNSUPPORTED)


def rows() -> Generator[TextRow | None]:
    """Read no part of any session's text.

    Yields:
        Nothing.
    """
    yield from ()


def scan(words: Sequence[str], parts: Collection[TextPart]) -> list[tuple[str, TextPart]]:  # noqa: ARG001 # the surface's
    """Find nothing: no text of OpenCode 1's is read.

    Returns:
        No part.
    """
    return []
