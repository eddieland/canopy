"""Records the web UI's write requests in the journal's `web_writes` (TRUST_MODEL T8): what a holder of the secret did.

A write is any method but GET and HEAD, as auth.py has it. One is recorded when it signed a session in, or carried a
signed-in session and that session's token, however it was answered: a refusal by the guard or by a verb's guard. A
request without both is not recorded: a page on another port of this host is sent the operator's cookie but cannot read
the token, so only a page of this server or a holder of the listener secret can grow the journal. The mock server,
which signs nobody in, records every write.

The row is written once the response is sent, on a thread, so the answer never waits on it; the request's own task does,
for at most `db.BUSY_SECONDS` on a busy journal. A row the journal cannot take, or that fails any other way, goes to
canopy's log instead.

What is kept is the method, the path, the status, the peer's address, and the session's fingerprint. Never the body,
the headers, the query, the cookie, or the token: a body holds the operator's words, which a forget must be able to
delete, and the rest are credentials.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import TYPE_CHECKING

from starlette.requests import Request

from canopy.core import db, web_writes
from canopy.infra import logs
from canopy.serve.auth import READ_METHODS, SIGNED_IN, Signed

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from canopy.serve.auth import Sessions
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
        carried = self.sessions.writer(Request(scope))
        # Shared with every Request built on this scope, so the sign-in route's state is read back here.
        state = scope.setdefault("state", {})
        code = 500

        async def watching(message: Message) -> None:
            nonlocal code
            if message["type"] == "http.response.start":
                code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, watching)
        finally:
            issued = state.get(SIGNED_IN)
            session = issued if isinstance(issued, Signed) else carried
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

    def _record(self, write: web_writes.Write) -> None:
        try:
            with self.backend.open() as ctx:
                web_writes.record(ctx.conn, write)
        except Exception as e:  # noqa: BLE001  (a best-effort record: logged, and the request was already answered)
            _log.warning(
                "web UI write not recorded: %s %s",
                write.method,
                write.path,
                extra={**dataclasses.asdict(write), "error": f"{type(e).__name__}: {e}"},
            )
