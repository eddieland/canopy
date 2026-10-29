"""Which models served an OpenCode session (DESIGN §13), read from `opencode export` as OpenCode 1.19.3 prints it.

`opencode export ID --sanitize` prints the session and its messages as one JSON object, their text, reasoning, tool
output, and paths redacted. Each assistant message names the provider and model that wrote it, the variant it ran at
when not the model's default, and what it cost; only those, its id, and the session's `version`, the OpenCode that made
it, are read. A model run at a variant is named
with it, `anthropic/claude-opus@high`, so each variant counts on its own. The id is the `messageID` each event of the
model call that wrote the message carries (`canopy.runtime.opencode.transcript`), so a session more than one model
served names the model of each call in its transcript. OpenCode looks a session up by its id alone, in the one
database that holds every project's sessions, so any directory finds it. One it does not have it names on stderr,
`Session not found: ID`, and exits 1.

A sandboxed run's session is not there: its OpenCode keeps its data in its role's own directory (DESIGN §24). The
export is never pointed there, since OpenCode would act on what a run wrote, so a session it does not have is looked
for in each role's database instead, read as `canopy.runtime.opencode.sessions` reads it: its messages as the export
prints them, each one's info and id, and the session's version.

Its stdout is captured through a file, not a pipe. With stderr a pipe too, OpenCode exits having written only what a
pipe's buffer holds, 64 KiB, and most sessions' exports are longer.

A plugin OpenCode loads may print to stdout too, before the export or after it: each line that starts with `{` is read
as the start of one JSON value, and the first that holds an export is the export (`printed`).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

from canopy.infra import procs
from canopy.runtime.opencode import printed as printed_json
from canopy.runtime.opencode import sessions
from canopy.runtime.report import (
    MAX_COST_USD,
    MAX_MODEL_NAME,
    MAX_MODELS,
    MAX_REPLIES,
    MESSAGE_ID_RE,
    OTHER_MODELS,
    ModelUse,
    SessionModels,
    runtime_version,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

#: How long one export may take: it starts OpenCode, which reads its config and plugins, then the session.
TIMEOUT_SECONDS = 60
#: The command, as canopy's words for a failure name it.
COMMAND = "opencode export --sanitize"
#: What OpenCode prints on stderr for a session it does not have.
NOT_FOUND = "Session not found"
#: In a sandbox role's database, the version of OpenCode that made a session, by its id.
SESSION_SQL = "SELECT version FROM session WHERE id = ?"
#: Its messages, by its id and at most how many, in the order OpenCode wrote them: each one's id, and its info as JSON.
MESSAGES_SQL = "SELECT id, data FROM message WHERE session_id = ? ORDER BY time_created, id LIMIT ?"
# Where a JSON object starts a line.
_OBJECT_RE = re.compile(r"^\{", re.MULTILINE)


class _Info(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    id: StrictStr | None = None
    role: StrictStr
    # A user message names the model it asked for; only an assistant's names the one that wrote it.
    provider: StrictStr | None = Field(default=None, alias="providerID")
    model: StrictStr | None = Field(default=None, alias="modelID")
    # Left out for the model's default.
    variant: StrictStr | None = None
    cost: Annotated[StrictFloat | StrictInt, Field(ge=0, le=MAX_COST_USD, allow_inf_nan=False)] = 0


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    info: _Info


class _Session(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    # The version of OpenCode that made the session: anything but a string is no version canopy keeps, and fails no
    # read of the models.
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
    exported = printed_json.among(printed, _OBJECT_RE, _Export.model_validate_json)
    if exported is None:
        return SessionModels("failed", error=f"`{COMMAND}` printed what canopy cannot read")
    models, replies = _models(exported.messages)
    named = exported.info.version if exported.info is not None else None
    version = runtime_version(named if isinstance(named, str) else None)
    return SessionModels("found", models, replies=replies if len(models) > 1 else {}, runtime_version=version)


class _FailedError(Exception):
    """The export could not be run, or failed for another reason than a session OpenCode does not have."""


# The session as a sandbox role's database holds it, read as its export would be. A message canopy cannot read is left
# out, as the session reader leaves out a reply it cannot read.
def _from_sandbox(session_id: str) -> SessionModels:
    found = sessions.sandbox_session(session_id, SESSION_SQL, MESSAGES_SQL)
    if found is None:
        return SessionModels("missing")
    named, rows = found
    models, replies = _models(tuple(m for row in rows if (m := _message(row)) is not None))
    version = runtime_version(named if isinstance(named, str) else None)
    return SessionModels("found", models, replies=replies if len(models) > 1 else {}, runtime_version=version)


# A message's row, its id and its info as JSON, as the export prints the message; None for one canopy cannot read.
def _message(row: Sequence[object]) -> _Message | None:
    message_id, data = row
    if not isinstance(data, str):
        return None
    try:
        info: object = json.loads(data)
    except (ValueError, RecursionError):
        return None
    if not isinstance(info, dict):
        return None
    try:
        return _Message.model_validate({"info": {**info, "id": message_id}})
    except ValidationError:
        return None


# What the export printed, or None for a session OpenCode does not have.
def _export(runner: procs.Runner, cwd: Path, session_id: str) -> str | None:
    if session_id.startswith("-"):
        # Read as an option, not the session: no session OpenCode names starts so.
        raise _FailedError("not a session id OpenCode names")
    try:
        argv = ["opencode", "export", session_id, "--sanitize"]
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


# Each model's replies, the most costly first, and the model of each reply whose id is a message's, by its id.
def _models(messages: tuple[_Message, ...]) -> tuple[tuple[ModelUse, ...], dict[str, str]]:
    found: dict[str, ModelUse] = {}
    replies: dict[str, str] = {}
    for message in messages:
        info = message.info
        if info.role != "assistant" or info.provider is None or info.model is None:
            continue
        variant = f"@{info.variant}" if info.variant else ""
        name = _name(f"{info.provider}/{info.model}{variant}")
        if name not in found and len(found) >= MAX_MODELS:
            name = OTHER_MODELS
        was = found.get(name, ModelUse(name, 0, 0.0))
        found[name] = ModelUse(name, was.replies + 1, was.cost_usd + float(info.cost))
        if info.id is not None and MESSAGE_ID_RE.fullmatch(info.id) and len(replies) < MAX_REPLIES:
            replies[info.id] = name
    return tuple(sorted(found.values(), key=lambda m: (-m.cost_usd, m.model))), replies


# Shown on a terminal, so printable, with no space in it; `?` when nothing is left.
def _name(model: str) -> str:
    return "".join(c for c in model if c.isprintable() and not c.isspace())[:MAX_MODEL_NAME] or "?"
