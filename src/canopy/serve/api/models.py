"""The models the runtime lists to run an agent on (DESIGN §13), as `canopy models` prints them.

They are what the operator may choose a ticket's agent's model from, which only the operator does, from a ticket's
page; this reads the list from the runtime and changes nothing.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.model import ModelList

TAG = "models"
router = APIRouter(tags=[TAG])


@router.get("/models", operation_id="listModels", summary="List the models")
def model_list(backend: BackendDep) -> ModelList:
    """Every model the runtime lists, with each one's variants, read from it now in the workspace root, or why not.

    Read when the operator opens a ticket's Model panel, not on the stream: each read starts the runtime, for up to 30
    seconds. A model on the list can still fail when called, since the runtime reads it from its cache or its catalog.
    """
    with backend.open() as ctx:
        found = backend.models(ctx)
    variants = {model: sorted(found.variants[model]) for model in sorted(found.variants) if found.variants[model]}
    return ModelList(models=sorted(found.models), variants=variants, error=found.error)
