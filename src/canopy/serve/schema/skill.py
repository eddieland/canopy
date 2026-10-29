"""The API's types for the skills page (DESIGN §13): every skill the runtime finds, and where its file is.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type SkillSource = Annotated[
    Literal["canopy", "workspace", "home", "built-in", "other"],
    Field(
        description="Where a skill's file is (DESIGN §13): `canopy` for the skills canopy ships, in its definitions "
        "snapshot; `workspace` for one under the workspace's root; `home` for one under the operator's home; "
        "`built-in` for one the runtime carries itself; `other` for any other file.",
    ),
]


class Skill(Model):
    """A skill the runtime finds where the loop starts its agents: where its file is, and what it says."""

    name: str
    """The skill's name, as an agent loads it and the runtime's rules match it."""
    description: str | None = None
    """What its front matter says it is for: what an agent reads to decide whether to load it; None when it says
    nothing."""
    source: SkillSource
    """Where its file is."""
    path: str
    """Its file: under the workspace's root relative to it, under the operator's home from `~/`, and otherwise as the
    runtime names it."""
    body: str
    """Its instructions, the file after its front matter: untrusted text, rendered as text."""


class SkillList(Model):
    """Every skill the runtime finds, as `canopy agents` asks it, with each one's file and text."""

    skills: list[Skill] = []
    """Each skill, by name; none when the runtime could not list them."""
    error: str | None = None
    """Why the runtime could not list its skills, in canopy's words; None when it did."""
