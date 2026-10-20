"""Which models served an agent's session, as the runtime's own record of it says (DESIGN §13, Each agent's model).

No event a run prints names the model a call went to, so canopy asks the runtime after the run, by the session id the
run printed. What the session says is what served: a template's model option, the runtime's default, or a model canopy
chose. How the runtime is asked, and how its answer is read, is the implementation's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.implementation import session_models as implementation

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.infra import procs
    from canopy.runtime.report import SessionModels


def read(runner: procs.Runner, *, cwd: Path, session_id: str) -> SessionModels:
    """Ask the runtime, started in `cwd`, which models served session `session_id`.

    Returns:
        Its models, the most costly first; `missing` when the runtime keeps no such session; `failed`, with why, when
        it could not be asked or its answer could not be read.
    """
    return implementation.read(runner, cwd=cwd, session_id=session_id)
