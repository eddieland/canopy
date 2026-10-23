"""The models the runtime lists to run an agent on (DESIGN §13, Each agent's model).

Models come and go, so canopy holds no list of its own: it asks the runtime for the one a run's model is looked up in,
before a run on a model the operator chose starts. How the runtime is asked, and how its answer is read, is the
implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import models as implementation

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.infra import procs
    from canopy.runtime.report import ModelList


def listed(runner: procs.Runner, *, cwd: Path) -> ModelList:
    """Ask the runtime, started in `cwd`, which models it can run an agent on.

    Returns:
        The models it listed; or none, with why, when it could not be asked or failed.
    """
    return implementation.listed(runner, cwd=cwd)
