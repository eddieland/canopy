"""What the operator has seen (DESIGN §22): a review whose result they opened is no longer new to them."""

from __future__ import annotations

from fastapi import APIRouter

from canopy.core import conversation
from canopy.infra import logs
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError
from canopy.serve.review_schema import SeenMarked, SeenRequest

TAG = "seen"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.post("/seen", operation_id="markSeen", summary="Mark subjects seen", responses=REFUSED)
def mark_seen(body: SeenRequest, backend: BackendDep) -> SeenMarked:
    """Each subject's result is no longer new to the operator, as `canopy review show ID` marks one. All, or none."""
    with backend.open() as ctx:
        try:
            subjects = [conversation.parse_ref(ref) for ref in body.refs]
            new = conversation.see(ctx.conn, subjects, channel=WEB)
        except conversation.Refused as r:
            raise RefusedError(r) from None
    named = [str(s) for s in dict.fromkeys(subjects)]
    _log.info("seen", extra={"subjects": named, "new": [str(s) for s in new], "channel": WEB})
    return SeenMarked(refs=named, new=[str(s) for s in new])
