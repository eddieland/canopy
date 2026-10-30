"""The models the runtime lists to run an agent on (DESIGN §13), as `canopy models` prints them, and the overrides.

They are what the operator may choose a ticket's agent's model from, which only the operator does, from a ticket's
page; this reads the list from the runtime, and the overrides from the journal, and changes nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from canopy.core import agent_models, ticket_models
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.model import ModelList, ModelOverride

if TYPE_CHECKING:
    from canopy.core.records import TicketOverride

TAG = "models"
router = APIRouter(tags=[TAG])


@router.get("/models", operation_id="listModels", summary="List the models")
def model_list(
    backend: BackendDep,
    *,
    refresh: Annotated[bool, Query(description="Ask the runtime now rather than serve the list it gave last.")] = False,
) -> ModelList:
    """Every model the runtime lists, with each one's variants, read from it in the workspace root, or why not.

    Read when a ticket's page shows a model its agents run on, or a Model menu opens, not on the stream: a read starts
    the runtime, for up to 30 seconds, so the server serves the list it read for 5 minutes, or until the loop reads its
    config again. A list that could not be read is never served again. A model on the list can still fail when called,
    since the runtime reads it from its cache or its catalog, and a run's model is checked against a list read for it
    as it starts.
    """
    with backend.open() as ctx:
        found = backend.model_list(ctx, refresh=refresh)
    # Each model's variants in the order the runtime lists them, as a picker offers them.
    variants = {model: list(found.variants[model]) for model in sorted(found.variants) if found.variants[model]}
    return ModelList(models=sorted(found.models), variants=variants, error=found.error)


@router.get("/models/overrides", operation_id="listModelOverrides", summary="List the tickets' model overrides")
def model_overrides(backend: BackendDep) -> list[ModelOverride]:
    """Every ticket with a model the operator chose for one of its agents, by ticket, then agent.

    An override outlasts `canopy forget` and covers each run of its agent until it is cleared, so the settings page
    lists them all: a canary left on a costly model spends where no other page shows it.
    """
    with backend.open() as ctx:
        found = ticket_models.overrides(ctx.conn)
    return [_override(o) for o in found]


def _override(found: TicketOverride) -> ModelOverride:
    chosen = agent_models.parse(found.value)
    # The journal's agent is one `ticket_models.choose` wrote, which the API's type checks again.
    return ModelOverride.model_validate(
        {
            "ticket": found.ticket_key,
            "agent": found.agent,
            "model": chosen.id,
            "variant": chosen.variant,
            "set_at": found.set_at,
        },
    )
