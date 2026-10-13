"""The event stream (serve/live.py): the lists a page shows, sent whole when the journal changes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse

from canopy.serve import live
from canopy.serve.schema import StreamEvent

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def router(backend: Backend) -> APIRouter:
    """Return the stream's route, reading through `backend`."""
    api = APIRouter()

    # FastAPI's SSE support sends `Cache-Control: no-cache` and `X-Accel-Buffering: no`, so a proxy or an SSH forward
    # streams it, and a keepalive comment after 15 idle seconds. Nothing may compress this route: gzip buffers.
    @api.get("/events", operation_id="streamEvents", response_class=EventSourceResponse)
    async def events() -> AsyncIterator[StreamEvent]:
        async for event in live.events(backend):
            yield event

    return api
