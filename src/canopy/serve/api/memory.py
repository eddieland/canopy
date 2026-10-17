"""Agent memory (DESIGN §28): every tier's notes, proposals, and lessons, a ticket's notes, and a run's memory.

Reads only: promoting, rejecting, renewing, forgetting, and purging are the CLI's, in the operator's shell.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.serve import memory_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, RunId, TicketKey, not_found, ticket_ref
from canopy.serve.schema import MemoryOverview, RunMemory, TicketMemory

TAG = "memory"
router = APIRouter(tags=[TAG])


@router.get("/memory", operation_id="getMemory", summary="Get agent memory")
def overview(backend: BackendDep) -> MemoryOverview:
    """Each tier's mode, every ticket's notes in force, the proposals waiting, and the lessons and what they serve."""
    with backend.open() as ctx:
        return memory_views.overview(ctx)


@router.get(
    "/tickets/{key}/memory",
    operation_id="getTicketMemory",
    summary="Get a ticket's notes",
    responses={**REFUSED, **not_found("ticket")},
)
def ticket_memory(key: TicketKey, backend: BackendDep) -> TicketMemory:
    """Every note the ticket's runs wrote, and what its next run would be served.

    A key that is not a ticket's is refused `bad_ref` or `unsupported`; one canopy has no record of is a 404.
    """
    ref = ticket_ref(key, "show")
    with backend.open() as ctx:
        found = memory_views.ticket_memory(ctx, ref.id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no record of {ref}")
    return found


@router.get(
    "/runs/{run_id}/memory", operation_id="getRunMemory", summary="Get a run's memory", responses=not_found("run")
)
def run_memory(run_id: RunId, backend: BackendDep) -> RunMemory:
    """The modes the run's prompt was rendered under, what it wrote and read of memory, and what it had refused."""
    with backend.open() as ctx:
        found = memory_views.run_memory(ctx, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return found
