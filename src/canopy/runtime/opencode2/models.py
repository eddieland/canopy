"""The models OpenCode 2 lists to run an agent on (DESIGN §13), asked of a private server as OpenCode 2.1.4 answers.

`opencode api --standalone model.list` starts a private server in the directory it runs in, reads that directory's
config as a run started there would, and prints `{location, data}`: each model in `data` as an object whose
`providerID` and `id` name it, `provider/model`, and whose `variants` are the variants a run on it may use, each an
object with an `id`, those OpenCode derives for the model and the provider's config adds. It is the same list
`opencode models` prints a line each, `providerID/id`, which has no option to print the variants. A run's agent is
looked up in it: OpenCode 2 refuses a variant the model lacks before the first call, but tries a model the list lacks
on the provider, so canopy looks the model up first. A plugin that adds a provider may not have loaded when the list
is read, so a model of its is refused as missing rather than run unchecked.

Only `providerID`, `id`, and the variants' `id` are read: a model's `settings` and `headers` may hold a provider's key,
so no failure quotes what was printed. An entry that does not name a model canopy renders is passed over.

OpenCode 2.1.2 ran a primary agent on the default model, whatever its definition named; 2.1.4 runs it on the
definition's model and variant, so a model chosen in config needs 2.1.4 or later.

Its stdout is captured through a file, not a pipe, as the other questions of OpenCode 2 are
(`canopy.runtime.opencode2.offerings`): OpenCode exits having written only what a pipe's buffer holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from canopy.infra import procs
from canopy.runtime.opencode2.definitions import MODEL_RE
from canopy.runtime.opencode2.invocation import STANDALONE
from canopy.runtime.report import ModelList

if TYPE_CHECKING:
    from pathlib import Path

#: How long the list may take: it starts OpenCode's server, which reads its config, then its catalog.
TIMEOUT_SECONDS: Final = 60
#: The command, as canopy's words for a failure name it.
COMMAND: Final = "opencode api model.list"


class _Variant(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    id: StrictStr


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    provider: StrictStr = Field(alias="providerID")
    id: StrictStr
    variants: tuple[_Variant, ...] = ()


class _Models(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    data: tuple[_Model, ...]


def listed(runner: procs.Runner, *, cwd: Path, variants: bool = False) -> ModelList:
    """Ask OpenCode 2, started in `cwd`, which models it can run an agent on, and with `variants` each one's variants.

    Returns:
        The models it listed, with their variants when asked for; or none, with why, when OpenCode could not be run,
        failed, or printed what canopy cannot read.
    """
    argv = ["opencode", "api", STANDALONE, "model.list"]
    try:
        result = runner.run(argv, cwd=cwd, timeout=TIMEOUT_SECONDS, stdout_to_file=True)
    except procs.CommandNotFoundError:
        return ModelList(error="opencode is not on PATH")
    except procs.ProcError as e:
        return ModelList(error=f"`{COMMAND}` could not start: {e}")
    if result.timed_out:
        return ModelList(error=f"`{COMMAND}` took over {TIMEOUT_SECONDS} seconds")
    if not result.ok:
        return ModelList(error=f"`{COMMAND}` exited {result.returncode}")
    try:
        printed = _Models.model_validate_json(result.stdout)
    except ValidationError:
        # Not the error itself: it quotes what was printed, which may hold a provider's key.
        return ModelList(error=f"`{COMMAND}` printed what canopy cannot read")
    found = {
        name: frozenset(v.id for v in model.variants)
        for model in printed.data
        if MODEL_RE.fullmatch(name := f"{model.provider}/{model.id}")
    }
    return ModelList(frozenset(found), found if variants else {})
