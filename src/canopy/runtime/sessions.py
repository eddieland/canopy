"""What every session the runtime keeps cost, canopy's runs' and the operator's own alike (DESIGN §13, §11).

A run's events say what canopy's own runs cost; the runtime's record says what every session cost, whoever started it,
so that the two together tell spend in canopy from spend outside it. The record is read a page at a time, in the order
the sessions were last updated, from where the read before stopped, so a session updated since is read again. Where
the record is, and how it is read, is the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import sessions as implementation
from canopy.runtime.report import MAX_SESSIONS

if TYPE_CHECKING:
    from canopy.runtime.report import SessionCursor, SessionPage


def updated_after(cursor: SessionCursor | None, *, limit: int = MAX_SESSIONS) -> SessionPage:
    """Read the sessions the runtime keeps, updated after `cursor`, or every one from the first when it is None.

    Returns:
        At most `limit` sessions, capped at `MAX_SESSIONS`, the least recently updated first, and the cursor to read on
        from; `missing` when the runtime has kept no session yet; `failed`, with why, when its record could not be read.
    """
    return implementation.updated_after(cursor, limit=min(limit, MAX_SESSIONS))
