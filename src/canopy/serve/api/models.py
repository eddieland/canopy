"""The models the runtime lists to run an agent on (DESIGN §13), as `canopy models` prints them.

They are what the operator may choose a ticket's agent's model from, which only the operator does, from a ticket's
page; this reads the list from the runtime and changes nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.model import ModelList

TAG = "models"
router = APIRouter(tags=[TAG])


@router.get("/models", operation_id="listModels", summary="List the models")
def model_list(
    backend: BackendDep,
    *,
    refresh: Annotated[bool, Query(description="Ask the runtime now rather than serve the list it gave last.")] = False,
) -> ModelList:
    """Every model the runtime lists, with each one's variants, read from it in the workspace root, or why not.

    Read when the operator opens a ticket's Model panel, not on the stream: a read starts the runtime, for up to 30
    seconds, so the server serves the list it read for 5 minutes, or until the loop reads its config again. A list
    that could not be read is never served again. A model on the list can still fail when called, since the runtime
    reads it from its cache or its catalog, and a run's model is checked against a list read for it as it starts.
    """
    with backend.open() as ctx:
        found = backend.model_list(ctx, refresh=refresh)
    # Each model's variants in the order the runtime lists them, as a picker offers them.
    variants = {model: list(found.variants[model]) for model in sorted(found.variants) if found.variants[model]}
    return ModelList(models=sorted(found.models), variants=variants, error=found.error)
