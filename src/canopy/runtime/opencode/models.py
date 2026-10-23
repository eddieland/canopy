"""The models OpenCode lists to run an agent on (DESIGN §13), read from `opencode models` as OpenCode 1.19.3 prints it.

`opencode models` prints one `provider/model` a line, for each provider with a key, a login, or config: the list a
run's model is looked up in, which OpenCode refuses a model outside of before the first call, exiting 1. It reads
OpenCode's cache or the catalog built into it and reaches no provider, so it works offline, and a listed model can
still fail when it is called. A line that is not a model, such as a plugin's, is passed over: only a model the list
names can be found in it.

Its stdout is captured through a file, not a pipe, as the export's is (`canopy.runtime.opencode.session_models`): with
stderr a pipe too, OpenCode exits having written only what a pipe's buffer holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.infra import procs
from canopy.runtime.opencode.definitions import MODEL_RE
from canopy.runtime.report import ModelList

if TYPE_CHECKING:
    from pathlib import Path

#: How long the list may take: it starts OpenCode, which reads its config and plugins, then its catalog.
TIMEOUT_SECONDS = 30
#: The command, as canopy's words for a failure name it.
COMMAND = "opencode models"


def listed(runner: procs.Runner, *, cwd: Path) -> ModelList:
    """Ask OpenCode, started in `cwd`, which models it can run an agent on.

    Returns:
        The models it listed; or none, with why, when OpenCode could not be run or failed.
    """
    try:
        result = runner.run(["opencode", "models"], cwd=cwd, timeout=TIMEOUT_SECONDS, stdout_to_file=True)
    except procs.CommandNotFoundError:
        return ModelList(error="opencode is not on PATH")
    except procs.ProcError as e:
        return ModelList(error=f"`{COMMAND}` could not start: {e}")
    if result.timed_out:
        return ModelList(error=f"`{COMMAND}` took over {TIMEOUT_SECONDS} seconds")
    if not result.ok:
        return ModelList(error=f"`{COMMAND}` exited {result.returncode}")
    lines = (line.strip() for line in result.stdout.splitlines())
    return ModelList(frozenset(line for line in lines if MODEL_RE.fullmatch(line)))
