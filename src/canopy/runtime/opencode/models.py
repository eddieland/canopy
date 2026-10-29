"""The models OpenCode lists to run an agent on (DESIGN §13), read from `opencode models` as OpenCode 1.19.3 prints it.

`opencode models` prints one `provider/model` a line, for each provider with a key, a login, or config: the list a
run's model is looked up in, which OpenCode refuses a model outside of before the first call, exiting 1. It reads
OpenCode's cache or the catalog built into it and reaches no provider, so it works offline, and a listed model can
still fail when it is called. A line that is not a model, such as a plugin's, is passed over: only a model the list
names can be found in it.

With `--verbose` it prints each model's line followed by the model as JSON, indented over several lines, whose
`variants` are the variants a run on it may use, each by name: those OpenCode derives for the model and the provider's
config adds, less those it disables. OpenCode drops an agent's variant the model does not list without a word, so the
variants are read when one was chosen; only `variants` is read of the JSON.

Its stdout is captured through a file, not a pipe, as the export's is (`canopy.runtime.opencode.session_models`): with
stderr a pipe too, OpenCode exits having written only what a pipe's buffer holds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, StrictStr

from canopy.infra import procs
from canopy.runtime.opencode.definitions import MODEL_RE
from canopy.runtime.report import ModelList

if TYPE_CHECKING:
    from pathlib import Path

#: How long the list may take: it starts OpenCode, which reads its config and plugins, then its catalog.
TIMEOUT_SECONDS = 30
#: The command, as canopy's words for a failure name it.
COMMAND = "opencode models"
#: The option that prints each model's JSON after its line, its variants among it.
VERBOSE = "--verbose"
# The blank space between a model's line and its JSON.
_SPACE_RE = re.compile(r"\s*")


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    # Each variant by name, to the options it sends, which canopy does not read.
    variants: Mapping[StrictStr, object] | None = None


def listed(runner: procs.Runner, *, cwd: Path, variants: bool = False) -> ModelList:
    """Ask OpenCode, started in `cwd`, which models it can run an agent on, and with `variants` each one's variants.

    Returns:
        The models it listed, with their variants when asked for; or none, with why, when OpenCode could not be run or
        failed.
    """
    command = f"{COMMAND} {VERBOSE}" if variants else COMMAND
    argv = ["opencode", "models", VERBOSE] if variants else ["opencode", "models"]
    try:
        result = runner.run(argv, cwd=cwd, timeout=TIMEOUT_SECONDS, stdout_to_file=True)
    except procs.CommandNotFoundError:
        return ModelList(error="opencode is not on PATH")
    except procs.ProcError as e:
        return ModelList(error=f"`{command}` could not start: {e}")
    if result.timed_out:
        return ModelList(error=f"`{command}` took over {TIMEOUT_SECONDS} seconds")
    if not result.ok:
        return ModelList(error=f"`{command}` exited {result.returncode}")
    if variants:
        found = _verbose(result.stdout)
        return ModelList(frozenset(found), found)
    lines = (line.strip() for line in result.stdout.splitlines())
    return ModelList(frozenset(line for line in lines if MODEL_RE.fullmatch(line)))


def _verbose(text: str) -> dict[str, tuple[str, ...]]:
    """Return each model `opencode models --verbose` printed in `text`, with the variants its JSON lists, in its order.

    A model whose line is not followed by JSON canopy can read lists none. The JSON is skipped whole, so no line of it
    is read as a model's.
    """
    decoder = json.JSONDecoder()
    found: dict[str, tuple[str, ...]] = {}
    pos = 0
    while pos < len(text):
        end = text.find("\n", pos)
        end = len(text) if end < 0 else end
        line = text[pos:end].strip()
        pos = end + 1
        if not MODEL_RE.fullmatch(line):
            continue
        found[line] = ()
        start = _SPACE_RE.match(text, pos)
        start_at = start.end() if start is not None else pos
        if not text.startswith("{", start_at):
            continue
        try:
            value, pos = decoder.raw_decode(text, start_at)
            model = _Model.model_validate(value)
        # Not JSON, or not a model's: pydantic's error is a ValueError too.
        except ValueError:
            continue
        found[line] = tuple(model.variants or ())
    return found
