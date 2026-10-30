"""The system resources page's read: the machine the loop runs on, and the loop's own process (serve/host.py).

Not on the event stream: none of it is in the journal, so the page asks again every few seconds while it is open. Its
graphs' readings are kept by the server in memory (`host.Samples`).
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.host import HostHistory, HostProcesses, HostResources

TAG = "host"
router = APIRouter(tags=[TAG])


@router.get("/host", operation_id="getHost", summary="Get the host's resources")
def host(backend: BackendDep) -> HostResources:
    """The machine the loop runs on, read now.

    Its processors and their load, its memory, the disks canopy writes to, and the loop's own process.
    """
    return backend.read_host()


@router.get("/host/samples", operation_id="getHostSamples", summary="Get the host's readings over the last hour")
def samples(backend: BackendDep) -> HostHistory:
    """The readings of the machine the server has kept since it started, the last hour's at most, oldest first.

    Each is the load over a minute, the memory in use, the loop's own, and each disk's free space, read every
    `every_seconds` whether or not a page is open. They are kept in memory alone, so a server that restarts starts
    again with none.
    """
    return backend.samples.history()


@router.get("/host/processes", operation_id="getHostProcesses", summary="Get the host's processes")
def processes(backend: BackendDep) -> HostProcesses:
    """The processes on the machine the loop runs on, read now, the kernel's own threads left out.

    Each with the processors it kept busy since the read before, the last ask's while a page asks every few seconds,
    or a second's after none for a while; its memory, its state, and its command line. Off Linux, none are read.
    """
    return backend.processes()
