"""The operator's checklists (DESIGN §42): each repository's list of rules, as the next worker run in it hears it.

Read from `paths.checklists` when asked, as each run reads it. It changes nothing: a list is the operator's file,
edited where it is. How runs answered the lists is under reports.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.serve import checklist_views
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.checklist import ChecklistList

TAG = "checklists"
router = APIRouter(tags=[TAG])


@router.get("/checklists", operation_id="listChecklists", summary="List the checklists")
def checklist_list(backend: BackendDep) -> ChecklistList:
    """Each mapped repository's list, its items in order, or why canopy cannot use its file."""
    with backend.open() as ctx:
        return checklist_views.lists(ctx)
