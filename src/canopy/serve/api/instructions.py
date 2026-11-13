"""The operator's standing instructions files (DESIGN §12): each agent's, read, saved, deleted, and its kept versions.

Only the text of an agent's file, never which file: the one `paths.<agent>_instructions` names, or its default in
`paths.instructions`, which a save makes and a delete removes; `paths.*` stays the config's (TRUST_MODEL T8, D134). A
file a key names is never deleted. A change is refused inside one of canopy's own runs, over a file changed since the
page read it, through a link, in a directory anyone else may write in, and past the bound a run takes. The file as it
was is kept among the agent's versions first, and each change is logged with both hashes, never the text. A run already
started keeps the prompt it read.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from canopy.core import conversation, prompts, standing
from canopy.infra import logs
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError
from canopy.serve.schema.instructions import (
    AgentInstructions,
    InstructionsAgent,
    InstructionsDelete,
    InstructionsList,
    InstructionsSave,
    InstructionsVersion,
    InstructionsVersions,
)

TAG = "instructions"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/instructions", operation_id="listInstructions", summary="List the standing instructions files")
def instructions_list(backend: BackendDep) -> InstructionsList:
    """Each agent's standing instructions file: its path, where that comes from, text, hash, any problem, versions."""
    with backend.open() as ctx:
        found = standing.read_all(ctx.config, ctx.ws.state_dir)
    return InstructionsList(files=[_shown(i) for i in found], max_bytes=prompts.MAX_STANDING_BYTES)


@router.put(
    "/instructions/{agent}",
    operation_id="saveInstructions",
    summary="Save an agent's standing instructions",
    responses=REFUSED,
)
def instructions_save(agent: InstructionsAgent, body: InstructionsSave, backend: BackendDep) -> AgentInstructions:
    """Write the text over the agent's file, or make it when it is not there, keeping the file as it was first.

    Refused, writing nothing: `inside_run`; `too_large` past `max_bytes`; `stale` when the agent's file is not `path`,
    or it changed since `sha256` was read; `unsafe_file` for a link, a file not the operator's, or a directory a group
    or others may write in.
    """
    with backend.open() as ctx:
        cfg, state_dir = ctx.config, ctx.ws.state_dir
    try:
        saved = standing.save(cfg, state_dir, agent, body.text, read_path=Path(body.path), read_sha256=body.sha256)
    except conversation.Refused as r:
        raise RefusedError(r) from None
    _logged("standing instructions saved", saved, body.sha256)
    return _shown(saved)


@router.post(
    "/instructions/{agent}/delete",
    operation_id="deleteInstructions",
    summary="Delete an agent's default standing instructions",
    responses=REFUSED,
)
def instructions_delete(agent: InstructionsAgent, body: InstructionsDelete, backend: BackendDep) -> AgentInstructions:
    """Delete the agent's default file, keeping it among its versions first: its runs then read none.

    Refused, deleting nothing: `inside_run`; `configured` when `paths.<agent>_instructions` names the file, which
    deleted would refuse every run; `stale` when it changed since `sha256` was read; `unsafe_file` as a save is.
    """
    with backend.open() as ctx:
        cfg, state_dir = ctx.config, ctx.ws.state_dir
    try:
        deleted = standing.delete(cfg, state_dir, agent, read_path=Path(body.path), read_sha256=body.sha256)
    except conversation.Refused as r:
        raise RefusedError(r) from None
    _logged("standing instructions deleted", deleted, body.sha256)
    return _shown(deleted)


@router.get(
    "/instructions/{agent}/versions",
    operation_id="listInstructionsVersions",
    summary="List an agent's kept versions",
)
def instructions_versions(agent: InstructionsAgent, backend: BackendDep) -> InstructionsVersions:
    """The agent's kept versions, newest first: each the file as it was before a change, with its text."""
    with backend.open() as ctx:
        state_dir = ctx.ws.state_dir
    return InstructionsVersions(
        versions=[
            InstructionsVersion(id=v.id, at=v.at, kind=v.kind, sha256=v.sha256, size=v.size, text=v.text)
            for v in standing.versions(state_dir, agent)
        ],
        keep=standing.KEEP_VERSIONS,
    )


def _logged(what: str, found: standing.Instructions, old: str | None) -> None:
    # Both hashes and the path, never the text: a forget must still be able to drop the operator's words.
    _log.info(
        what,
        extra={"channel": WEB, "agent": found.agent, "path": str(found.path), "old": old, "new": found.sha256},
    )


def _shown(found: standing.Instructions) -> AgentInstructions:
    return AgentInstructions(
        agent=found.agent,
        key=found.key,
        path=str(found.path),
        source=found.source,
        text=found.text,
        sha256=found.sha256,
        problem=found.problem,
        missing=found.missing,
        versions=found.versions,
    )
