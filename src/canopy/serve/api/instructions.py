"""The operator's standing instructions files (DESIGN §12): each agent's, read, and its text saved.

Only the text of a file the config already names, never which file: `paths.*` stays the config's (TRUST_MODEL T8,
D134). A save is refused inside one of canopy's own runs, over a file changed since the page read it, through a link,
and past the bound a run takes. The file as it was is kept beside it as `<name>.bak`, and each save is logged with
both hashes, never the text. A run already started keeps the prompt it read.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.core import conversation, prompts, standing
from canopy.infra import logs
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError
from canopy.serve.schema.instructions import AgentInstructions, InstructionsAgent, InstructionsList, InstructionsSave

TAG = "instructions"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/instructions", operation_id="listInstructions", summary="List the standing instructions files")
def instructions_list(backend: BackendDep) -> InstructionsList:
    """Each agent's standing instructions file as the loop's config names it: its path, text, hash, and any problem."""
    with backend.open() as ctx:
        found = standing.read_all(ctx.config)
    return InstructionsList(files=[_shown(i) for i in found], max_bytes=prompts.MAX_STANDING_BYTES)


@router.put(
    "/instructions/{agent}",
    operation_id="saveInstructions",
    summary="Save an agent's standing instructions",
    responses=REFUSED,
)
def instructions_save(agent: InstructionsAgent, body: InstructionsSave, backend: BackendDep) -> AgentInstructions:
    """Write the text over the agent's file, or make the file the config names when it is missing.

    Refused, writing nothing: `inside_run`; `not_set` when the config names no file for the agent; `too_large` past
    `max_bytes`; `stale` when the file changed since `sha256` was read; `unsafe_file` for a link, a file not the
    operator's, or a directory others may write in.
    """
    with backend.open() as ctx:
        cfg, state_dir = ctx.config, ctx.ws.state_dir
    old = body.sha256
    try:
        saved = standing.save(cfg, state_dir, agent, body.text, read_sha256=old)
    except conversation.Refused as r:
        raise RefusedError(r) from None
    _log.info(
        "standing instructions saved",
        extra={"channel": WEB, "agent": agent, "path": str(saved.path), "old": old, "new": saved.sha256},
    )
    return _shown(saved)


def _shown(found: standing.Instructions) -> AgentInstructions:
    return AgentInstructions(
        agent=found.agent,
        key=found.key,
        path=None if found.path is None else str(found.path),
        text=found.text,
        sha256=found.sha256,
        problem=found.problem,
        missing=found.missing,
    )
