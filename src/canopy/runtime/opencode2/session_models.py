"""Which models served an OpenCode 2 session (DESIGN §13), read from `opencode session export` as 2.1.2 prints it.

`opencode session export ID --sanitize` prints the session and its messages as one JSON object, `{info, messages}`,
their text, reasoning, tool output, title, and paths redacted. Each assistant message names the model that wrote it,
`{providerID, id, variant}`, the variant only when not the model's default, and what it cost; only those are read, and
the session's `version` where it names the OpenCode that made it. A
model run at a variant is named as OpenCode 2 spells it, `anthropic/claude-opus#high`, so each variant counts on its
own. OpenCode looks a session up by its id alone, in the one database that holds every project's sessions, so any
directory finds it. One it does not have it names on stderr, `Session not found: ID`, and exits 1.

A sandboxed run's session is not there but in its role's own database (DESIGN §24), which the export is never pointed
at, so a session OpenCode does not have is looked for there, as OpenCode 1's reader looks
(`canopy.runtime.opencode.session_models`): each message's type and data, as the export prints the message.

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
from canopy.runtime.opencode import sessions
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
    from collections.abc import Sequence
    from pathlib import Path

#: How long one export may take: it starts OpenCode's server, which reads its config and plugins, then the session.
TIMEOUT_SECONDS = 60
#: The command, as canopy's words for a failure name it.
COMMAND = "opencode session export --sanitize"
#: What OpenCode prints on stderr for a session it does not have.
NOT_FOUND = "Session not found"
#: In a sandbox role's database, the version of OpenCode that made a session, by its id.
SESSION_SQL = "SELECT version FROM session_v2 WHERE id = ?"
#: Its messages, by its id and at most how many, in the order OpenCode wrote them: each one's type, and of its data, as
#: JSON, only the fields `_Message` reads, which SQLite takes out of each, as OpenCode 1's reader does
#: (`canopy.runtime.opencode.session_models.MESSAGES_SQL`): a reply's data holds its content, which may be long.
MESSAGES_SQL = """
SELECT type, data FROM (
    SELECT type, seq, json_object(
        'model', json_object(
            'providerID', json_extract(data, '$.model.providerID'),
            'id', json_extract(data, '$.model.id'),
            'variant', json_extract(data, '$.model.variant')
        ),
        'cost', coalesce(json_extract(data, '$.cost'), 0)
    ) AS data
    FROM session_message
    WHERE session_id = ? AND json_valid(data)
)
WHERE length(type) <= 64 AND length(data) <= 1024
ORDER BY seq
LIMIT ?
"""
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

    # The version of OpenCode that made the session, where the export names one: anything but a string is no version
    # canopy keeps, and fails no read of the models.
    version: object = None


class _Export(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    info: _Session | None = None
    messages: tuple[_Message, ...]


def read(runner: procs.Runner, *, cwd: Path, session_id: str) -> SessionModels:
    """Export session `session_id` with OpenCode started in `cwd`, and read which models wrote its replies.

    A session OpenCode does not have is read from the sandbox role's database that holds it, if one does.

    Returns:
        Its models, the most costly first; `missing` when neither OpenCode nor a sandbox role has such a session;
        `failed`, with why, when OpenCode could not be run or printed what canopy cannot read.
    """
    try:
        printed = _export(runner, cwd, session_id)
    except _FailedError as e:
        return SessionModels("failed", error=str(e))
    if printed is None:
        return _from_sandbox(session_id)
    exported = _parse(printed)
    if exported is None:
        return SessionModels("failed", error=f"`{COMMAND}` printed what canopy cannot read")
    named = exported.info.version if exported.info is not None else None
    version = runtime_version(named if isinstance(named, str) else None)
    return SessionModels("found", _models(exported.messages), runtime_version=version)


class _FailedError(Exception):
    """The export could not be run, or failed for another reason than a session OpenCode does not have."""


# The session as a sandbox role's database holds it, read as its export would be, leaving out a message canopy cannot
# read.
def _from_sandbox(session_id: str) -> SessionModels:
    found = sessions.sandbox_session(session_id, SESSION_SQL, MESSAGES_SQL)
    if found is None:
        return SessionModels("missing")
    named, rows = found
    models = _models(tuple(m for row in rows if (m := _message(row)) is not None))
    return SessionModels("found", models, runtime_version=runtime_version(named if isinstance(named, str) else None))


# A message's row, its type and its data as JSON, as the export prints the message; None for one canopy cannot read.
def _message(row: Sequence[object]) -> _Message | None:
    kind, data = row
    if not isinstance(data, str):
        return None
    try:
        fields: object = json.loads(data)
    except (ValueError, RecursionError):
        return None
    if not isinstance(fields, dict):
        return None
    try:
        return _Message.model_validate({**fields, "type": kind})
    except ValidationError:
        return None


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
