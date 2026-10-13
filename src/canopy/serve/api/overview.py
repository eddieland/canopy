"""What every page reads beside its own resource: the server's meta, the attention list, and the spend."""

from __future__ import annotations

from importlib.metadata import version

from fastapi import APIRouter

from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema import AttentionItem, Meta, Spend

router = APIRouter()


@router.get("/meta", operation_id="getMeta")
def meta(backend: BackendDep) -> Meta:
    return Meta(version=version("canopy"), mock=backend.mock, ticket_url=backend.config.tracker.ticket_url or None)


@router.get("/attention", operation_id="listAttention")
def attention(backend: BackendDep) -> list[AttentionItem]:
    with backend.open() as ctx:
        return views.attention(backend, ctx)


@router.get("/spend", operation_id="getSpend")
def spend(backend: BackendDep) -> Spend:
    with backend.open() as ctx:
        return views.spend(backend, ctx)
