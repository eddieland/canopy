"""The web UI's record of its write requests (TRUST_MODEL T8): what a holder of the listener secret did with it.

The server records a write once it has answered it (`canopy.serve.audit`); nothing else writes a row, and none is
deleted (DESIGN §26). A row holds no request body, header, query, cookie, or token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import records

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True)
class Write:
    """A write request the server answered, as `web_writes` keeps it."""

    #: When the request came in.
    at: str
    method: str
    #: The request's path, without its query, cut to the length the server keeps.
    path: str
    #: The HTTP status it was answered with.
    code: int
    #: The peer's address, as the server saw it.
    client: str | None
    #: A fingerprint of the session it carried or signed in; None on the mock server, which signs nobody in.
    session: str | None


def record(conn: sqlite3.Connection, write: Write) -> None:
    """Add `write` to the journal's `web_writes`."""
    records.insert(
        records.WebWrite,
        at=write.at,
        method=write.method,
        path=write.path,
        code=write.code,
        client=write.client,
        session=write.session,
    ).run(conn)
