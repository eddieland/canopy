"""Which models served an OpenCode session (DESIGN §13), read from `opencode export` as OpenCode 1.19.3 prints it.

`opencode export ID --sanitize` prints the session and its messages as one JSON object, their text, reasoning, tool
output, and paths redacted. Each assistant message names the provider and model that wrote it, and what it cost; only
those are read. OpenCode looks a session up by its id alone, in the one database that holds every project's sessions,
so any directory finds it. One it does not have it names on stderr, `Session not found: ID`, and exits 1.

A plugin OpenCode loads may print to stdout too, before the export or after it, and the operator may not be free to
remove it. The export starts a line, so each line that starts with `{` is read as the start of one JSON value, and the
first that holds an export is the export.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.infra import procs
from canopy.runtime.report import MAX_COST_USD, MAX_MODEL_NAME, MAX_MODELS, OTHER_MODELS, ModelUse, SessionModels

if TYPE_CHECKING:
    from pathlib import Path

#: How long one export may take: it starts OpenCode, which reads its config and plugins, then the session.
TIMEOUT_SECONDS = 60
#: The command, as canopy's words for a failure name it.
COMMAND = "opencode export --sanitize"
#: What OpenCode prints on stderr for a session it does not have.
NOT_FOUND = "Session not found"
# Where a JSON object starts a line.
_OBJECT_RE = re.compile(r"^\{", re.MULTILINE)


class _Info(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    role: StrictStr
    # A user message names the model it asked for; only an assistant's names the one that wrote it.
    provider: StrictStr | None = Field(default=None, alias="providerID")
    model: StrictStr | None = Field(default=None, alias="modelID")
    cost: Annotated[StrictFloat | StrictInt, Field(ge=0, le=MAX_COST_USD, allow_inf_nan=False)] = 0


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    info: _Info


class _Export(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    messages: tuple[_Message, ...]


def read(runner: procs.Runner, *, cwd: Path, session_id: str) -> SessionModels:
    """Export session `session_id` with OpenCode started in `cwd`, and read which models wrote its replies.

    Returns:
        Its models, the most costly first; `missing` when OpenCode has no such session; `failed`, with why, when
        OpenCode could not be run or printed what canopy cannot read.
    """
    try:
        printed = _export(runner, cwd, session_id)
    except _FailedError as e:
        return SessionModels("failed", error=str(e))
    if printed is None:
        return SessionModels("missing")
    exported = _parse(printed)
    if exported is None:
        return SessionModels("failed", error=f"`{COMMAND}` printed what canopy cannot read")
    return SessionModels("found", _models(exported.messages))


class _FailedError(Exception):
    """The export could not be run, or failed for another reason than a session OpenCode does not have."""


# What the export printed, or None for a session OpenCode does not have.
def _export(runner: procs.Runner, cwd: Path, session_id: str) -> str | None:
    if session_id.startswith("-"):
        # Read as an option, not the session: no session OpenCode names starts so.
        raise _FailedError("not a session id OpenCode names")
    try:
        result = runner.run(["opencode", "export", session_id, "--sanitize"], cwd=cwd, timeout=TIMEOUT_SECONDS)
    except procs.CommandNotFoundError:
        raise _FailedError("opencode is not on PATH") from None
    except procs.ProcError as e:
        raise _FailedError(f"`{COMMAND}` could not start: {e}") from None
    if result.timed_out:
        raise _FailedError(f"`{COMMAND}` took over {TIMEOUT_SECONDS} seconds")
    if result.ok:
        return result.stdout
    if NOT_FOUND in result.stderr:
        return None
    raise _FailedError(f"`{COMMAND}` exited {result.returncode}")


# The export among what else OpenCode's plugins printed, or None when none of it is one. Not the errors: they quote
# what was printed.
def _parse(printed: str) -> _Export | None:
    try:
        return _Export.model_validate_json(printed)
    except ValidationError:
        pass
    decoder = json.JSONDecoder()
    for start in _OBJECT_RE.finditer(printed):
        try:
            _, end = decoder.raw_decode(printed, start.start())
            return _Export.model_validate_json(printed[start.start() : end])
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


def _models(messages: tuple[_Message, ...]) -> tuple[ModelUse, ...]:
    found: dict[str, ModelUse] = {}
    for message in messages:
        info = message.info
        if info.role != "assistant" or info.provider is None or info.model is None:
            continue
        name = _name(f"{info.provider}/{info.model}")
        if name not in found and len(found) >= MAX_MODELS:
            name = OTHER_MODELS
        was = found.get(name, ModelUse(name, 0, 0.0))
        found[name] = ModelUse(name, was.replies + 1, was.cost_usd + float(info.cost))
    return tuple(sorted(found.values(), key=lambda m: (-m.cost_usd, m.model)))


# Shown on a terminal, so printable, with no space in it; `?` when nothing is left.
def _name(model: str) -> str:
    return "".join(c for c in model if c.isprintable() and not c.isspace())[:MAX_MODEL_NAME] or "?"
