"""What every page reads beside its own resource: the server's meta, the attention list, and the spend."""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING

from fastapi import APIRouter

from canopy.serve import views
from canopy.serve.schema import AttentionItem, Meta, Spend

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def router(backend: Backend) -> APIRouter:
    """Return the overview's routes, reading through `backend`."""
    api = APIRouter()

    @api.get("/meta", operation_id="getMeta")
    def meta() -> Meta:
        return Meta(version=version("canopy"), mock=backend.mock, ticket_url=backend.config.tracker.ticket_url or None)

    @api.get("/attention", operation_id="listAttention")
    def attention() -> list[AttentionItem]:
        with backend.open() as ctx:
            return views.attention(backend, ctx)

    @api.get("/spend", operation_id="getSpend")
    def spend() -> Spend:
        with backend.open() as ctx:
            return views.spend(backend, ctx)

    return api
