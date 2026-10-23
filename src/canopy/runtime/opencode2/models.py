"""The models OpenCode 2 lists to run an agent on (DESIGN §13): not read yet.

canopy has not checked how OpenCode 2.1.2 lists its models, or in what form, so it reads no list. A run whose model the
operator chose is then refused as one whose list could not be read, never run on a model nobody checked is there; a run
with no model chosen reads no list, and runs as before. A variant is rendered into the definition as OpenCode 1's is,
in the format 2 reads through its compatibility layer, and a run on one is refused with its model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.report import ModelList

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.infra import procs


def listed(runner: procs.Runner, *, cwd: Path, variants: bool = False) -> ModelList:
    """Say that canopy reads no list of OpenCode 2's models yet, nor their variants.

    Returns:
        No models, and why.
    """
    del runner, cwd, variants
    return ModelList(error="canopy does not read OpenCode 2's list of models yet")
