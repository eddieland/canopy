"""Lets an event stream end quietly when its client leaves, which FastAPI's SSE teardown does not.

FastAPI's SSE support (0.142.4 to 0.143.1) closes a stream's receiving end, on the request's exit stack, before it
cancels the task that feeds it. A client that leaves while that task is sending makes it raise anyio's
`BrokenResourceError`, in an exception group, and uvicorn logged `Exception in ASGI application` with its whole
traceback: in canopy.log, at ERROR, under the loop, for a closed tab. `QuietLeaving` absorbs that error only when it is
all there is: the response is an event stream, the server has told the app its client left, and every exception in the
group is a `BrokenResourceError`. Anything else is raised as it came, its traceback and context untouched, so a real
failure in a stream logs as it did and carries none of this noise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import anyio
from starlette.datastructures import Headers

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

_EVENT_STREAM: Final = "text/event-stream"


class QuietLeaving:
    """ASGI middleware: an event stream whose client left ends without the teardown error FastAPI raises for it."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap `app`."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, noting what the response is and whether its client left; absorb only that error.

        Raises:
            BrokenResourceError: The app's, unchanged, unless it is a stream's teardown after its client left.
            BaseExceptionGroup: The app's, unchanged, unless all it holds is that error.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        seen = _Seen(receive, send)
        try:
            await self.app(scope, seen.receive, seen.send)
        except (anyio.BrokenResourceError, BaseExceptionGroup) as error:
            if not (seen.streaming and seen.left and _only_broken(error)):
                raise


class _Seen:
    """What one request's response and client have shown: whether it is an event stream, and whether the client left."""

    def __init__(self, receive: Receive, send: Send) -> None:
        self._receive = receive
        self._send = send
        self.streaming = False
        self.left = False

    async def receive(self) -> Message:
        # uvicorn speaks ASGI 2.3, so Starlette learns a streaming client left from this message, and stops sending.
        message = await self._receive()
        if message["type"] == "http.disconnect":
            self.left = True
        return message

    async def send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = Headers(raw=list(message.get("headers", [])))
            self.streaming = headers.get("content-type", "").startswith(_EVENT_STREAM)
        await self._send(message)


def _only_broken(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        _, rest = error.split(anyio.BrokenResourceError)
        return rest is None
    return isinstance(error, anyio.BrokenResourceError)
