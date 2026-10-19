"""Text from another program made safe to show: on a terminal, in a log, or on a page."""

from __future__ import annotations


def printable(text: str) -> str:
    """`text` without control characters, line breaks kept: a message shown on a terminal cannot move the cursor.

    Returns:
        `text` with CRLF made LF and every other unprintable character made a space.
    """
    return "".join(c if c.isprintable() or c == "\n" else " " for c in text.replace("\r\n", "\n"))
