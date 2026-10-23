"""The models OpenCode 2 lists to run an agent on (DESIGN §13): not read yet.

canopy has not checked how OpenCode 2.1.2 lists its models, or in what form, so it reads no list. A run whose model the
operator chose is then refused as one whose list could not be read, never run on a model nobody checked is there; a run
with no model chosen reads no list, and runs as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.report import ModelList

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.infra import procs


def listed(runner: procs.Runner, *, cwd: Path) -> ModelList:
    """Say that canopy reads no list of OpenCode 2's models yet.

    Returns:
        No models, and why.
    """
    del runner, cwd
    return ModelList(error="canopy does not read OpenCode 2's list of models yet")
