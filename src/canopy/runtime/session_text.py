"""The text of every session the runtime keeps, canopy's runs' and the operator's own alike (ROADMAP M72).

`canopy sessions --sizes` measures what a full-text index of the runtime's record would cost before one is built: how
many sessions it keeps, how much text each part of them holds, and how long a plain scan takes to find words in it.
The record is read whole, read-only, as spend reads it (`canopy.runtime.sessions`). Where it is, and how its text is
taken apart, is the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import one, pick, two

if TYPE_CHECKING:
    from collections.abc import Collection, Generator, Sequence

    from canopy.runtime.implementation import Version
    from canopy.runtime.report import SessionRecord, TextPart, TextRow


def record(*, version: Version) -> SessionRecord:
    """Read every session the runtime `version` runs keeps, and what its record is.

    Returns:
        The sessions; `missing` when the runtime has kept none yet; `failed`, with why, when its record could not be
        read; `unsupported`, with why, when this runtime's record is not measured.
    """
    return pick(version, one.session_text, two.session_text).record()


def rows(*, version: Version) -> Generator[TextRow | None]:
    """Read every part of every session's text, one at a time, so the record is never held whole.

    Returns:
        Each part, or None for a row canopy cannot read. Iterating raises `sqlite3.Error` when the operator's own
        record could not be read.
    """
    return pick(version, one.session_text, two.session_text).rows()


def scan(words: Sequence[str], parts: Collection[TextPart], *, version: Version) -> list[tuple[str, TextPart]]:
    """Find the parts among `parts` that hold every one of `words`, by a plain scan of the record, with no index.

    Returns:
        Each session and part found, once each.
    """
    return pick(version, one.session_text, two.session_text).scan(words, parts)
