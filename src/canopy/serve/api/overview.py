"""What every page reads beside its own resource: the server's meta, the attention list, the spend, and its days."""

from __future__ import annotations

from importlib.metadata import version
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from canopy.core import spend as spending
from canopy.serve import spend_views, views
from canopy.serve.api.deps import BackendDep, SpaDep
from canopy.serve.schema import AttentionItem, Meta
from canopy.serve.schema.spend import Spend, SpendBreakdown

TAG = "overview"
router = APIRouter(tags=[TAG])


@router.get("/meta", operation_id="getMeta", summary="Get the server's meta")
def meta(backend: BackendDep, spa: SpaDep) -> Meta:
    """The server's version and UI build, whether its data is mock, its link templates, and the workspace.

    The workspace is its root and the names of its repositories.
    """
    return Meta(
        version=version("canopy"),
        build=spa.build(),
        mock=backend.mock,
        ticket_url=backend.config.tracker.ticket_url or None,
        branch_urls={r.name: r.branch_url for r in backend.workspace.repos if r.branch_url},
        workspace_root=str(backend.workspace.root),
        repos=[r.name for r in backend.workspace.repos],
    )


@router.get("/attention", operation_id="listAttention", summary="List the attention items")
def attention(backend: BackendDep) -> list[AttentionItem]:
    """The attention list, as `canopy status` shows it: what needs the operator, and since when."""
    with backend.open() as ctx:
        return views.attention(backend, ctx)


@router.get("/spend", operation_id="getSpend", summary="Get the spend")
def spend(backend: BackendDep) -> Spend:
    """What the last 24 hours and the last 30 days each cost, as the agent runtime reported it."""
    with backend.open() as ctx:
        return spend_views.spend(backend, ctx)


@router.get("/spend/breakdown", operation_id="getSpendBreakdown", summary="Get the spend by day and by what it bought")
def spend_breakdown(
    backend: BackendDep,
    days: Annotated[
        int | None,
        Query(
            ge=1,
            le=spending.MAX_DAYS,
            description=(
                f"How many local days to read, today's so far included: 1 to {spending.MAX_DAYS}; "
                f"{spending.DEFAULT_DAYS} when neither this nor hours is given."
            ),
        ),
    ] = None,
    hours: Annotated[
        int | None,
        Query(
            ge=1,
            le=spending.MAX_HOURS,
            description=(
                f"How many clock hours to read, by the hour, the current one so far included: 1 to "
                f"{spending.MAX_HOURS}. Not with days."
            ),
        ),
    ] = None,
    ticket: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=(
                "A ticket's key: its spend by model is that ticket's runs alone, each beside the workspace's. Every "
                "other figure is the workspace's still."
            ),
        ),
    ] = None,
) -> SpendBreakdown:
    """What each day, or hour, of the window cost, by kind; the ticks by what they bought; and the newest idle ticks."""
    if days is not None and hours is not None:
        raise HTTPException(status_code=422, detail="give days or hours, not both")
    with backend.open() as ctx:
        if hours is not None:
            return spend_views.spend_breakdown_hours(backend, ctx, hours, ticket=ticket)
        return spend_views.spend_breakdown(
            backend,
            ctx,
            spending.DEFAULT_DAYS if days is None else days,
            ticket=ticket,
        )
