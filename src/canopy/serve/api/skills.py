"""The skills the runtime finds (DESIGN §13), each with its file and its text.

Read when the operator opens the skills page, not on the stream: a read starts the runtime once, for its skills alone.
It changes nothing: a skill is added, denied, or removed in the runtime's own config and directories.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.serve import skills
from canopy.serve.api.deps import BackendDep
from canopy.serve.schema.skill import SkillList

TAG = "skills"
router = APIRouter(tags=[TAG])


@router.get("/skills", operation_id="listSkills", summary="List the skills")
def skill_list(backend: BackendDep) -> SkillList:
    """Every skill the runtime finds in the workspace root, with where its file is and its text."""
    with backend.open() as ctx:
        return skills.listed(backend, ctx)
