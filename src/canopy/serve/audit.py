"""Records the web UI's write requests in the journal's `web_writes` (TRUST_MODEL T8): what a holder of the secret did.

A write is any method but GET and HEAD, as auth.py has it. One is recorded when it carried a signed-in session or signed
one in, however it was answered: a refusal by the guard, a write without its token, or a refusal by a verb's guard. A
request with no valid session is not recorded, so nobody without the listener secret can grow the journal; the mock
server, which signs nobody in, records every write. The row is written once the response is sent, on a thread, so it
never holds up the answer; one the journal cannot take, held too long by another writer, goes to canopy's log instead.

What is kept is the method, the path, the status, the peer's address, and the session's fingerprint. Never the body,
the headers, the query, the cookie, or the token: a body holds the operator's words, which a forget must be able to
delete, and the rest are credentials.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from typing import TYPE_CHECKING

from starlette.requests import Request

from canopy.core import db, web_writes
from canopy.infra import logs
from canopy.serve.auth import READ_METHODS

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from canopy.serve.auth import Sessions, Signed
    from canopy.serve.backend import Backend

#: The longest path kept; a longer one is cut to this many characters.
MAX_PATH = 512

_log = logs.for_tick(None)


class Audit:
    """ASGI middleware: records each write request of a signed-in session, or one that signs in, once it is answered."""

    def __init__(self, app: ASGIApp, *, backend: Backend, sessions: Sessions) -> None:
        """Wrap `app`, recording in `backend`'s journal the writes of the sessions `sessions` signs."""
        self.app = app
        self.backend = backend
        self.sessions = sessions

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, then record it if it is a write of a signed-in session."""
        if scope["type"] != "http" or scope["method"] in READ_METHODS:
            await self.app(scope, receive, send)
            return
        at = db.now()
        carried = self.sessions.of(Request(scope))
        code = 500
        issued: Signed | None = None

        async def watching(message: Message) -> None:
            nonlocal code, issued
            if message["type"] == "http.response.start":
                code = int(message["status"])
                issued = self._issued(message.get("headers"))
            await send(message)

        try:
            await self.app(scope, receive, watching)
        finally:
            session = issued or carried
            if session is not None or self.sessions.open:
                client = scope.get("client")
                write = web_writes.Write(
                    at=at,
                    method=str(scope["method"])[:16],
                    path=str(scope["path"])[:MAX_PATH],
                    code=code,
                    client=str(client[0]) if client else None,
                    session=session.fingerprint if session is not None else None,
                )
                await asyncio.to_thread(self._record, write)

    def _issued(self, headers: object) -> Signed | None:
        # The session a response signed in: its Set-Cookie for this server's cookie. Signing out sets an empty one.
        if not isinstance(headers, list):
            return None
        prefix = f"{self.sessions.cookie_name}="
        for name, value in headers:
            text = value.decode("latin-1") if name == b"set-cookie" else ""
            if text.startswith(prefix):
                return self.sessions.check(text.partition(";")[0].removeprefix(prefix))
        return None

    def _record(self, write: web_writes.Write) -> None:
        try:
            with self.backend.open() as ctx:
                web_writes.record(ctx.conn, write)
        except sqlite3.Error as e:
            _log.warning(
                "web UI write not recorded: %s %s",
                write.method,
                write.path,
                extra={**dataclasses.asdict(write), "error": f"{type(e).__name__}: {e}"},
            )
