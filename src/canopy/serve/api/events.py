"""The event stream (serve/live.py): the lists a page shows, sent whole when the journal changes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse

from canopy.serve import live
from canopy.serve.api.deps import BackendDep, OptionsDep
from canopy.serve.schema import StreamEvent

TAG = "events"
router = APIRouter(tags=[TAG])


async def provide_stream(backend: BackendDep) -> AsyncIterator[live.Stream]:
    """The request's stream, closed by the request's teardown, however its events' generator ended (`live.Stream`).

    Yields:
        The stream.
    """
    with closing(live.Stream(backend)) as stream:
        yield stream


# `request` is FastAPI's default for a dependency with `yield`, named here because the stream relies on it: the
# request's exit stack closes the stream after it cancels the SSE producer reading its events, which was entered on that
# stack later. With `function`, it would close before the response is sent, under a producer still reading. The
# provider is async, so the stream closes on the event loop, where its events run.
StreamDep = Annotated[live.Stream, Depends(provide_stream, scope="request")]


# FastAPI's SSE support sends `Cache-Control: no-cache` and `X-Accel-Buffering: no`, so a proxy or an SSH forward
# streams it, and a keepalive comment after 15 idle seconds. Nothing may compress this route: gzip buffers. A stream
# that `stream_seconds` ends says so last (`StreamEnding`), and the page opens the next one at once.
@router.get("/events", operation_id="streamEvents", summary="Stream the events", response_class=EventSourceResponse)
async def events(stream: StreamDep, options: OptionsDep) -> AsyncIterator[StreamEvent]:
    """Server-sent events: every list a page shows, first whole, then again whenever the journal changes it."""
    async for event in stream.events(lifetime=options.stream_seconds):
        yield event
