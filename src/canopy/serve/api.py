"""The JSON and SSE API under `{base_path}/api`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from importlib.metadata import version
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from fastapi.sse import EventSourceResponse

from canopy.serve import mock
from canopy.serve.schema import Lease, Meta, Session, StreamEvent

if TYPE_CHECKING:
    from canopy.serve.options import ServeOptions

# What a real-mode endpoint says until the journal backs it (ROADMAP M20).
_NOT_WIRED = "not implemented: served only with mock data until the journal backs it (ROADMAP M20)"


def router(options: ServeOptions) -> APIRouter:
    """Return the API's routes for a server set up with `options`."""
    api = APIRouter(prefix=f"{options.base_path}/api")

    # A dependency, so it refuses before a stream's headers are sent, not from inside it.
    def mock_only() -> None:
        if not options.mock:
            raise HTTPException(status_code=501, detail=_NOT_WIRED)

    unwired = [Depends(mock_only)]

    @api.get("/meta", operation_id="getMeta")
    def meta() -> Meta:
        return Meta(version=version("canopy"), mock=options.mock)

    @api.get("/sessions", operation_id="listSessions", dependencies=unwired)
    def sessions() -> list[Session]:
        return list(mock.SESSIONS)

    @api.get("/leases", operation_id="listLeases", dependencies=unwired)
    def leases() -> list[Lease]:
        return list(mock.LEASES)

    # FastAPI's SSE support sends `Cache-Control: no-cache` and `X-Accel-Buffering: no`, so a proxy or an SSH forward
    # streams it, and a keepalive comment after 15 idle seconds. Nothing may compress this route: gzip buffers.
    @api.get("/events", operation_id="streamEvents", response_class=EventSourceResponse, dependencies=unwired)
    async def events() -> AsyncIterator[StreamEvent]:
        async for event in mock.paced(options.mock_event_seconds):
            yield event

    return api
