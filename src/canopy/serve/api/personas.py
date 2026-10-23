"""The personas a run could get (DESIGN §31), as `canopy personas` lists them: what the operator may choose from.

Only the operator chooses one, from a ticket's page or a review request; this lists them and changes nothing.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.core import personas
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.persona import PersonaList

TAG = "personas"
router = APIRouter(tags=[TAG])


@router.get("/personas", operation_id="listPersonas", summary="List the personas")
def persona_list(backend: BackendDep) -> PersonaList:
    """Every persona a run could get, by name, the operator's in place of canopy's, and `[personas] reviewer`'s."""
    with backend.open() as ctx:
        found = [views.persona_choice(p) for p in personas.listed(ctx.config)]
        return PersonaList(personas=found, reviewer=ctx.config.personas.reviewer)
