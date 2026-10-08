"""The API's types. The UI's TypeScript types are generated from the OpenAPI schema these produce (ui/AGENTS.md).

Sessions and leases have no endpoint backed by the journal yet: these shapes are the intended contract, served from
mock.py until M15 and M20 wire them (ROADMAP M20). Change them here, then regenerate the UI's types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

# What a session (an agent run) is doing. `blocked` waits on a person; `idle` is alive with nothing to do.
type SessionState = Literal["running", "blocked", "idle", "done", "failed"]
# What a worktree lease is doing. `expiring` is held but near its end.
type LeaseState = Literal["held", "expiring", "released"]
type SessionKind = Literal["worker", "split", "review", "chore"]


class _Model(BaseModel):
    # Fields with defaults are still always sent, so the generated TypeScript types mark them required.
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class Meta(_Model):
    """The server itself: what it runs and whether its data is real."""

    version: str
    mock: bool


class Session(_Model):
    """One agent run."""

    id: str
    # The subject's reference (D075): a ticket key, `repo#N`, `chore:NAME`.
    subject: str
    kind: SessionKind
    state: SessionState
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None
    cost_usd: float | None = None
    # The lease of the worktree the run works in, if it has one.
    lease_id: str | None = None


class Lease(_Model):
    """One worktree lease from the pool."""

    id: str
    repo: str
    path: str
    state: LeaseState
    # The session holding it, while held.
    session_id: str | None = None
    acquired_at: datetime | None = None
    expires_at: datetime | None = None


class SessionUpdated(_Model):
    """A session was created or changed. The payload is the whole session, not a patch."""

    type: Literal["session.updated"] = "session.updated"
    session: Session


class LeaseUpdated(_Model):
    """A lease was created or changed. The payload is the whole lease, not a patch."""

    type: Literal["lease.updated"] = "lease.updated"
    lease: Lease


class StreamEvent(RootModel[Annotated[SessionUpdated | LeaseUpdated, Field(discriminator="type")]]):
    """One message on the event stream, told apart by its `type`. A named model so the UI's types get its name."""

    model_config = ConfigDict(frozen=True)
