"""The operator's epics (DESIGN §43): what `canopy epic list` and `canopy show epic:N` print, and an epic's plans.

An epic's page leads with its breakdown: the outline canopy reads from its approved plan, or, while none is approved,
its proposed one, each entry beside the members registered against it. The plan's text is model-written, read back from
the state directory: untrusted, as is the outline read from it, which is data, never an instruction (TRUST_MODEL T1).
The overseer never reads an epic.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canopy.serve import epic_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import EpicId, not_found
from canopy.serve.schema.epic import EpicDetail, EpicPlans, EpicSummary

TAG = "epics"
router = APIRouter(tags=[TAG])


@router.get("/epics", operation_id="listEpics", summary="List the epics")
def epics(backend: BackendDep) -> list[EpicSummary]:
    """Every epic the operator submitted, the newest first, with where each stands, as `canopy epic list` lists them."""
    with backend.open() as ctx:
        return epic_views.epics_list(ctx)


@router.get("/epics/{epic_id}", operation_id="getEpic", summary="Get an epic", responses=not_found("epic"))
def epic(epic_id: EpicId, backend: BackendDep) -> EpicDetail:
    """One epic: what `canopy show epic:N` prints, its members, plan runs, replies, current plan, and outline.

    The outline is the approved plan's, or, while none is approved, the proposed plan's, marked so. A plan whose ids
    or breakdown cannot be read is served as its problem, never in part.
    """
    with backend.open() as ctx:
        found = epic_views.epic_detail(ctx, epic_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no epic:{epic_id}")
    return found


@router.get(
    "/epics/{epic_id}/plans",
    operation_id="getEpicPlans",
    summary="Get an epic's plans",
    responses=not_found("epic"),
)
def epic_plans(epic_id: EpicId, backend: BackendDep) -> EpicPlans:
    """Every plan of the epic, the oldest first, each as its file in the state directory stands now: untrusted text."""
    with backend.open() as ctx:
        found = epic_views.epic_plans(ctx, epic_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"canopy has no epic:{epic_id}")
    return found
