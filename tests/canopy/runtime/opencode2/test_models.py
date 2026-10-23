"""OpenCode 2's list of models, which canopy does not read yet: a run on a chosen model is refused, never run blind."""

from pathlib import Path

from canopy.infra import procs
from canopy.runtime.opencode2 import models
from canopy.runtime.report import ModelList


def test_no_list_is_read_and_the_lookup_fails() -> None:
    runner = procs.SubprocessRunner()
    assert models.listed(runner, cwd=Path("/ws")) == ModelList(
        error="canopy does not read OpenCode 2's list of models yet",
    )
