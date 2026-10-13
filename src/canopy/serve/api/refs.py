"""What the routes share: the channel their writes go through, the refs a path names, and a refusal as a 409."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from canopy.core import conversation
from canopy.serve.schema import RefusalResponse

if TYPE_CHECKING:
    from canopy.core.conversation import Ref

WEB = "web"
# A write route's `responses`, so the schema names the 409 a guard's refusal is.
REFUSED: dict[int | str, dict[str, Any]] = {409: {"model": RefusalResponse, "description": "A guard refused it."}}


def refusal(r: conversation.Refused) -> HTTPException:
    """A guard's refusal as the 409 the UI shows."""
    return HTTPException(status_code=409, detail={"guard": r.guard, "reason": r.reason})


def ticket_ref(key: str, verb: str) -> Ref:
    """The ticket `key` names, refused as the CLI refuses it: `bad_ref`, or `unsupported` for another kind."""
    try:
        ref = conversation.parse_ref(key)
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise refusal(r) from None
    if ref.kind != conversation.TICKET:
        raise refusal(conversation.Refused("unsupported", f"{ref} is not a ticket"))
    return ref


def chore_ref(name: str, verb: str) -> Ref:
    """The chore `name` names, refused as `canopy reply chore:NAME` refuses it: `bad_ref` for a name no chore has."""
    try:
        ref = conversation.parse_ref(f"{conversation.CHORE}:{name}")
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise refusal(r) from None
    return ref
