"""The API's types for the operator's standing instructions files (DESIGN §12): each agent's, and a save of its text.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
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
    """The config key that would name the file, `paths.<agent>_instructions`."""
    path: str
    """The file: the one the key names, or the agent's default, `<paths.instructions>/<agent>.md`."""
    source: Literal["config", "default"]
    """`config` when the key names the file; `default` when it is unset: a run reads the default while it is there."""
    text: str | None = None
    """Its text, the operator's own words; None when there is no file or `problem` says why it cannot be shown."""
    sha256: str | None = None
    """The SHA-256, hex, of the file's bytes, which a change names as the version it replaces; None with no file."""
    problem: str | None = None
    """Why a run of the agent would refuse the file, or the page cannot show it; None when it is usable, or a default
    that is not there."""
    missing: bool = False
    """Whether there is no file: a run then reads none, or for a file the key names, is refused. A save makes it."""
    versions: int = 0
    """How many versions of it are kept: each the file as it was before a change."""


class InstructionsVersion(Model):
    """The file as it was before one change, kept among its agent's versions."""

    id: str
    """Its name among them."""
    at: datetime
    """When it was kept: when the change it went before was made."""
    kind: Literal["edit", "delete"]
    """What made it: a save over the file, or its deletion."""
    sha256: str
    """The SHA-256, hex, of its bytes."""
    size: int
    """Its size in bytes."""
    text: str | None = None
    """Its text, the operator's own words; None when it is not UTF-8 or too large to show."""


class InstructionsVersions(Model):
    """The kept versions of one agent's file, newest first."""

    versions: list[InstructionsVersion] = []
    """Each one, newest first."""
    keep: int
    """How many are kept: a change past them drops the oldest."""


class InstructionsDelete(Model):
    """A deletion of one agent's default file, over the file and version the page read."""

    path: str
    """The file the page read, `AgentInstructions.path`: the delete is refused if the agent's file is another now."""
    sha256: str
    """The hash the page read, `AgentInstructions.sha256`."""


class InstructionsList(Model):
    """Every agent's standing instructions file, and the most a run takes of one."""

    files: list[AgentInstructions] = []
    """One for each agent, in the order the page shows them."""
    max_bytes: int
    """The most bytes of a file a run takes: a longer one refuses every run of its agent."""


class InstructionsSave(Model):
    """The operator's new text for one agent's standing instructions file, over the file and version the page read."""

    # Bounded well past `max_bytes`, as a body, so text a little over it is the save's own `too_large` refusal.
    text: Annotated[str, Field(max_length=16 * prompts.MAX_STANDING_BYTES)]
    """The whole text; a save takes at most `max_bytes` bytes of it in UTF-8. Empty leaves the agent's runs none."""
    path: str
    """The file the page read, `AgentInstructions.path`: the save is refused if the agent's file is another now."""
    sha256: str | None = None
    """The hash the page read, `AgentInstructions.sha256`; None for a file that was not there, which the save makes."""
