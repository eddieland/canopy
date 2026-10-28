"""Text from another program made safe to show: on a terminal, in a log, or on a page."""

from __future__ import annotations

from typing import Final

#: Agent-written text is cut to this many characters to fit one terminal line.
SUMMARY_WIDTH: Final = 160


def printable(text: str) -> str:
    """`text` without control characters, line breaks kept: a message shown on a terminal cannot move the cursor.

    Returns:
        `text` with CRLF made LF and every other unprintable character made a space.
    """
    return "".join(c if c.isprintable() or c == "\n" else " " for c in text.replace("\r\n", "\n"))


def quoted(text: str) -> str:
    """`text` as a Markdown quote for a prompt: untrusted text that cannot pass for the prompt's own (TRUST_MODEL T1).

    Every line starts `> `, so no line of it can be a heading, a fence, or a label the harness writes outside it.

    Returns:
        `printable(text)` with `> ` before each line, or a lone `> ` for empty text.
    """
    return "\n".join(f"> {line}" for line in printable(text).splitlines() or [""])


def one_line(text: str) -> str:
    """Agent-written text, fit for one terminal line: control characters dropped, whitespace collapsed, and cut.

    Returns:
        The flattened text, cut to `SUMMARY_WIDTH` characters and ended with "..." when longer.
    """
    flat = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return flat if len(flat) <= SUMMARY_WIDTH else flat[: SUMMARY_WIDTH - 3] + "..."
