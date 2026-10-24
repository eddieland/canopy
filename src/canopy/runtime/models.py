"""The models the runtime lists to run an agent on (DESIGN §13, Each agent's model).

Models come and go, so canopy holds no list of its own: it asks the runtime for the one a run's model is looked up in,
before a run on a model the operator chose starts, and the variants of each when one was chosen, since a runtime may
drop a variant a model lacks without a word. How the runtime is asked, and how its answer is read, is the
implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import one, pick, two

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.infra import procs
    from canopy.runtime.implementation import Version
    from canopy.runtime.report import ModelList


def listed(runner: procs.Runner, *, version: Version, cwd: Path, variants: bool = False) -> ModelList:
    """Ask the runtime `version` runs, started in `cwd`, which models it can run an agent on, with `variants` each's.

    Returns:
        The models it listed, with their variants when asked for; or none, with why, when it could not be asked or
        failed.
    """
    return pick(version, one.models, two.models).listed(runner, cwd=cwd, variants=variants)
