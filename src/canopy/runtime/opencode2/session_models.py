"""Which models served an OpenCode 2 session (DESIGN §13), read from `opencode session export` as 2.1.2 prints it.

`opencode session export ID --sanitize` prints the session and its messages as one JSON object, `{info, messages}`,
their text, reasoning, tool output, title, and paths redacted. Each assistant message names the model that wrote it,
`{providerID, id, variant}`, the variant only when not the model's default, and what it cost; only those are read, and
the session's `version` where it names the OpenCode that made it. A
model run at a variant is named as OpenCode 2 spells it, `anthropic/claude-opus#high`, so each variant counts on its
own. OpenCode looks a session up by its id alone, in the one database that holds every project's sessions, so any
directory finds it. One it does not have it names on stderr, `Session not found: ID`, and exits 1.

The export runs `--standalone`, as canopy's runs do (`canopy.runtime.opencode2.invocation`): a private server for the
one command, rather than starting the shared background service and leaving it running.

Its stdout is captured through a file, not a pipe: OpenCode 1's export stopped at what a pipe's buffer holds, and a
session's export is longer. Each line that starts with `{` is read as the start of one JSON value, and the first that
holds an export is the export, so that anything else printed before or after it is passed over.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.infra import procs
from canopy.runtime.opencode2.invocation import STANDALONE
from canopy.runtime.report import (
    MAX_COST_USD,
    MAX_MODEL_NAME,
    MAX_MODELS,
    OTHER_MODELS,
    ModelUse,
    SessionModels,
    runtime_version,
)

if TYPE_CHECKING:
    from pathlib import Path

#: How long one export may take: it starts OpenCode's server, which reads its config and plugins, then the session.
TIMEOUT_SECONDS = 60
#: The command, as canopy's words for a failure name it.
COMMAND = "opencode session export --sanitize"
#: What OpenCode prints on stderr for a session it does not have.
NOT_FOUND = "Session not found"
# Where a JSON object starts a line.
_OBJECT_RE = re.compile(r"^\{", re.MULTILINE)


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    provider: StrictStr = Field(alias="providerID")
    id: StrictStr
    # Left out for the model's default.
    variant: StrictStr | None = None


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    # Besides the replies, a session holds the prompts, agent and model switches, and its idle marks.
    type: StrictStr
    model: _Model | None = None
    cost: Annotated[StrictFloat | StrictInt, Field(ge=0, le=MAX_COST_USD, allow_inf_nan=False)] = 0


class _Session(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    # The version of OpenCode that made the session, where the export names one.
    version: StrictStr | None = None


class _Export(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    info: _Session | None = None
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
    version = runtime_version(exported.info.version if exported.info is not None else None)
    return SessionModels("found", _models(exported.messages), runtime_version=version)


class _FailedError(Exception):
    """The export could not be run, or failed for another reason than a session OpenCode does not have."""


# What the export printed, or None for a session OpenCode does not have.
def _export(runner: procs.Runner, cwd: Path, session_id: str) -> str | None:
    if session_id.startswith("-"):
        # Read as an option, not the session: no session OpenCode names starts so.
        raise _FailedError("not a session id OpenCode names")
    try:
        argv = ["opencode", "session", "export", STANDALONE, "--sanitize", session_id]
        result = runner.run(argv, cwd=cwd, timeout=TIMEOUT_SECONDS, stdout_to_file=True)
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


# The export among whatever else was printed, or None when none of it is one. Not the errors: they quote what was
# printed.
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
        model = message.model
        if message.type != "assistant" or model is None:
            continue
        variant = f"#{model.variant}" if model.variant else ""
        name = _name(f"{model.provider}/{model.id}{variant}")
        if name not in found and len(found) >= MAX_MODELS:
            name = OTHER_MODELS
        was = found.get(name, ModelUse(name, 0, 0.0))
        found[name] = ModelUse(name, was.replies + 1, was.cost_usd + float(message.cost))
    return tuple(sorted(found.values(), key=lambda m: (-m.cost_usd, m.model)))


# Shown on a terminal, so printable, with no space in it; `?` when nothing is left.
def _name(model: str) -> str:
    return "".join(c for c in model if c.isprintable() and not c.isspace())[:MAX_MODEL_NAME] or "?"
