"""The event stream (serve/live.py): the lists a page shows, sent whole when the journal changes."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse

from canopy.serve import live
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema import StreamEvent

TAG = "events"
router = APIRouter(tags=[TAG])


# FastAPI's SSE support sends `Cache-Control: no-cache` and `X-Accel-Buffering: no`, so a proxy or an SSH forward
# streams it, and a keepalive comment after 15 idle seconds. Nothing may compress this route: gzip buffers.
@router.get("/events", operation_id="streamEvents", summary="Stream the events", response_class=EventSourceResponse)
async def events(backend: BackendDep) -> AsyncIterator[StreamEvent]:
    """Server-sent events: every list a page shows, first whole, then again whenever the journal changes it."""
    async for event in live.events(backend):
        yield event
