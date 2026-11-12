"""The API's types for the operator's standing instructions files (DESIGN §12): each agent's, and a save of its text.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from canopy.core import prompts
from canopy.serve.schema import Model

type InstructionsAgent = Annotated[
    Literal["worker", "overseer", "reviewer", "chore"],
    Field(
        description="The agent a standing instructions file reaches (DESIGN §12): `worker` for every implement, "
        "resume, plan, and task run; `overseer` for each tick's; `reviewer` for every review; `chore` for every "
        "chore run.",
    ),
]


class AgentInstructions(Model):
    """One agent's standing instructions file as it stands: where it is, its text, and what a run would make of it."""

    agent: InstructionsAgent
    """The agent whose runs read it."""
    key: str
    """The config key that names the file, `paths.<agent>_instructions`."""
    path: str | None = None
    """The file; None when the key names none, so the agent's runs read no standing instructions."""
    text: str | None = None
    """Its text, the operator's own words; None when there is no file or `problem` says why it cannot be shown."""
    sha256: str | None = None
    """The SHA-256, hex, of the file's bytes, which a save names as the version it replaces; None when there is none."""
    problem: str | None = None
    """Why a run of the agent would refuse the file, or the page cannot show it; None when it is usable."""
    missing: bool = False
    """Whether the config names a file that is not there, which a save makes."""


class InstructionsList(Model):
    """Every agent's standing instructions file, and the most a run takes of one."""

    files: list[AgentInstructions] = []
    """One for each agent, in the order the page shows them."""
    max_bytes: int
    """The most bytes of a file a run takes: a longer one refuses every run of its agent."""


class InstructionsSave(Model):
    """The operator's new text for one agent's standing instructions file, over the version the page read."""

    text: Annotated[str, Field(max_length=prompts.MAX_STANDING_BYTES)]
    """The whole text, in UTF-8 at most `max_bytes` bytes; empty leaves the agent's runs no instructions to read."""
    sha256: str | None = None
    """The hash the page read, `AgentInstructions.sha256`; None for a file that was missing, which the save makes."""
