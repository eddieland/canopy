"""The system resources page's read: the machine the loop runs on, and the loop's own process (serve/host.py).

Not on the event stream: none of it is in the journal, so the page asks again every few seconds while it is open.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.host import HostResources

TAG = "host"
router = APIRouter(tags=[TAG])


@router.get("/host", operation_id="getHost", summary="Get the host's resources")
def host(backend: BackendDep) -> HostResources:
    """The machine the loop runs on, read now.

    Its processors and their load, its memory, the disks canopy writes to, and the loop's own process.
    """
    with backend.open() as ctx:
        return backend.host(ctx)
