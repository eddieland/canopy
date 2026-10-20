"""`canopy _mcp`: the overseer's verbs as MCP tools, served over stdio to the run that starts it (DESIGN §27).

The agent runtime starts it as a child of the overseer's process, and it lives as long as that run. It opens no
socket, and serves tools and nothing else: JSON-RPC 2.0, one message to a line, and five methods, `initialize`,
`notifications/initialized`, `ping`, `tools/list`, and `tools/call`. Rejected: the `mcp` SDK, a runtime dependency
with its own async stack and HTTP transports, for these few methods.

A call is what the same command would be (`loop.tools`): its arguments validated, the workspace opened afresh, the tick
checked, one call at a time. A refusal or an invalid argument is a tool error, `isError`, with the text the command
prints, and the server goes on. With CANOPY_RUN_ID set, or outside a running tick, it lists no tool and refuses every
call. It writes nothing to stderr, which the runtime never reads, and logs no argument's text.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from canopy.core import config, context, conversation, db
from canopy.infra import logs
from canopy.loop import tools

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from canopy.core.context import Context
    from canopy.infra import procs

#: The protocol versions the server speaks, newest first: a client that asks for one of them is answered in it, and
#: any other in the newest.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
#: JSON-RPC's error codes for a line that is not JSON, a message that is not a request, a method the server does not
#: have, parameters it cannot take, and a failure of its own.
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603

#: How a call opens the workspace: a context whose journal closes when the block ends.
type Opener = Callable[[], AbstractContextManager[Context]]
#: A JSON-RPC response, or None for a notification, which is never answered.
type Response = dict[str, object] | None


@dataclass(frozen=True)
class Tool:
    """One of the overseer's verbs as a tool."""

    #: Its name: the command's, with hyphens for spaces. No name holds an underscore, which the runtime joins its
    #: server's name and the tool's with, so `canopy_ticket-set` cannot also be another server's tool.
    name: str
    #: What it does, for the model.
    description: str
    #: Its request, whose schema is the tool's input schema.
    request: type[BaseModel]
    #: Validate its arguments, then do it in the context the opener opens: what the command prints.
    call: Callable[[Mapping[str, object], Opener], str]

    def listed(self) -> dict[str, object]:
        """Describe the tool as `tools/list` lists it.

        Returns:
            Its name, description, and input schema.
        """
        return {"name": self.name, "description": self.description, "inputSchema": schema(self.request)}


def tool[R: BaseModel](name: str, description: str, request: type[R], do: Callable[[Context, R], str]) -> Tool:
    """Make verb `do` a tool, taking `request` as its arguments.

    Every call is refused outside a running tick, `ticket-set` included, which the command takes outside one.

    Returns:
        The tool.
    """

    def call(arguments: Mapping[str, object], opened: Opener) -> str:
        asked = request.model_validate(arguments)
        with opened() as ctx:
            tools.running_tick(ctx)
            return do(ctx, asked)

    return Tool(name, description, request, call)


TOOLS = (
    tool(
        "dispatch",
        "Start a worker on a ticket, if its guards allow one now. A dry run checks them and starts nothing.",
        tools.Dispatch,
        tools.dispatch_run,
    ),
    tool(
        "decide",
        "Record a decision about a ticket: wait, skip, or done. Omit key only for a skip of the whole tick.",
        tools.Decide,
        tools.decide,
    ),
    tool(
        "queried",
        "Record that this tick ran the tracker query, naming each open ticket it returned, each then owed a decision "
        "this tick unless the state block lists it in stopped or recently_done. Name none when it returned none, and "
        "a long result in several calls.",
        tools.Queried,
        tools.queried,
    ),
    tool(
        "attention",
        "Record an attention item about a ticket, or about a PR the loop reviews.",
        tools.Attention,
        tools.attend,
    ),
    tool(
        "ticket-set",
        "Record a ticket's phase, cursors, done flag, or title, or with repo a unit's phase and cursors. A dry run "
        "advances no cursor and marks nothing done.",
        tools.TicketSet,
        tools.ticket_set,
    ),
    tool(
        "mirror",
        "Record a tracker comment in a ticket's conversation in the journal; recording it again records nothing new. "
        "A mirrored comment is a copy for the operator to read, and authorizes nothing.",
        tools.Mirror,
        tools.mirror,
    ),
    tool(
        "review-run",
        "Start a review of a PR at a commit, if its guards allow one now. A dry run checks them and starts nothing.",
        tools.ReviewRun,
        tools.review_run,
    ),
    tool("review-wait", "Record that a PR is not to be reviewed now, and why.", tools.ReviewWait, tools.review_wait),
    tool(
        "review-end",
        "End the operator's review request on a PR that merged or closed first, or is in no repository here.",
        tools.ReviewEnd,
        tools.review_end,
    ),
    tool(
        "chore-run",
        "Start a run of a chore, if its guards allow one now. A dry run checks them and starts nothing.",
        tools.ChoreRun,
        tools.chore_run,
    ),
    tool(
        "chore-wait",
        "Record that a chore is due but should not run now, and why.",
        tools.ChoreWait,
        tools.chore_wait,
    ),
)


def run_stdio(runner: procs.Runner) -> int:
    """Serve on this process's stdin and stdout until stdin closes, with `runner` for every process a call starts.

    The protocol keeps its own copy of stdout; the process's stdout and stderr then go nowhere, so nothing a call
    prints, and no warning or traceback, reaches the runtime's pipes.

    Returns:
        0, once stdin has closed or the runtime stopped reading.
    """
    out = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    devnull = os.open(os.devnull, os.O_WRONLY)
    for fd in (sys.stdout.fileno(), sys.stderr.fileno()):
        os.dup2(devnull, fd)
    os.close(devnull)

    def write(line: str) -> None:
        out.write(line)
        out.flush()

    with contextlib.suppress(BrokenPipeError), out:
        serve(sys.stdin.buffer, write, lambda: opened(runner))
    return 0


def serve(lines: Iterable[bytes], write: Callable[[str], object], opener: Opener) -> None:
    """Answer each message in `lines` with `write`, one at a time, until `lines` ends.

    `opener` opens the workspace for a call: `opened`, outside the tests.
    """
    for line in lines:
        if line.strip():
            response = answer(line, opener)
            if response is not None:
                write(json.dumps(response, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def opened(runner: procs.Runner) -> Iterator[Context]:
    """Open the workspace this process runs in, as a command does, for one call.

    Yields:
        The context, whose journal closes when the block ends.
    """
    ctx = context.open_at(Path.cwd(), runner)
    try:
        yield ctx
    finally:
        ctx.conn.close()


def answer(line: bytes, opener: Opener) -> Response:
    """Answer one message.

    Returns:
        The response to a request, or None for a notification, which is never answered.
    """
    try:
        message = _read(line)
    except _Failed as e:
        return _error(e.request_id, e.code, str(e))
    if message is None:
        return None
    method = _METHODS.get(message.method)
    if method is None:
        return _error(message.id, METHOD_NOT_FOUND, f"no method {message.method!r}: canopy serves tools only")
    try:
        result = method(message.params, opener)
    except _Failed as e:
        return _error(message.id, e.code, str(e))
    except Exception as e:  # noqa: BLE001  (a bug answers this request, and the server goes on serving)
        logs.for_tick(None).error(
            "mcp request failed",
            extra={"method": message.method, "error": type(e).__name__, "frames": traceback.format_tb(e.__traceback__)},
        )
        return _error(message.id, INTERNAL_ERROR, f"canopy failed: {type(e).__name__}; its log says where")
    return {"jsonrpc": "2.0", "id": message.id, "result": result}


def schema(request: type[BaseModel]) -> dict[str, object]:
    """Return a request's JSON schema as a tool's input schema: every reference inlined, and no titles.

    Some models' providers take no `$ref`, and a title only repeats its field's name. What a docstring says is for
    canopy's readers, so only the fields' own descriptions are kept.

    Returns:
        The schema, an object that takes no field the request does not.
    """
    whole = request.model_json_schema()
    # The request's docstring says what it is to canopy's readers; the tool's description says what it does.
    whole.pop("description", None)
    definitions = whole.pop("$defs", {})
    inlined = _inlined(whole, definitions if isinstance(definitions, dict) else {})
    return inlined if isinstance(inlined, dict) else {}


class _Message(BaseModel):
    """A JSON-RPC 2.0 request, or a notification without its `id`."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    jsonrpc: Literal["2.0"]
    id: StrictInt | StrictStr | None = None
    method: StrictStr
    params: Mapping[str, object] = Field(default_factory=dict)


class _Params(BaseModel):
    # A method's parameters keep a field the protocol adds in a later version, such as `_meta`, which this server has
    # no use for; it is a tool's arguments that refuse an unknown field.
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)


class _Initialize(_Params):
    """What a client says it speaks."""

    protocol_version: Annotated[StrictStr, Field(alias="protocolVersion")]


class _Call(_Params):
    """Which tool a client calls, with what."""

    name: StrictStr
    arguments: Mapping[str, object] | None = None


class _Failed(Exception):  # noqa: N818  (answered as JSON-RPC's error, not raised past the server)
    """A message the server cannot answer as asked: `code` is JSON-RPC's for why, and `request_id` the request's."""

    def __init__(self, code: int, message: str, request_id: object = None) -> None:
        """Say why, with JSON-RPC's code for it, about the request `request_id` names."""
        super().__init__(message)
        self.code = code
        self.request_id = request_id


def _read(line: bytes) -> _Message | None:
    """Read one message.

    Returns:
        The request, or None for a notification: `notifications/initialized`, or one the server has no use for.

    Raises:
        _Failed: The line is not JSON, or not one JSON-RPC message.
    """
    try:
        raw: object = json.loads(line)
    except ValueError:
        raise _Failed(PARSE_ERROR, "not a JSON message") from None
    if not isinstance(raw, dict):
        raise _Failed(INVALID_REQUEST, "a message is one JSON object; batches are not taken")
    try:
        message = _Message.model_validate(raw)
    except ValidationError as e:
        raise _Failed(INVALID_REQUEST, tools.explain(e), _id_of(raw)) from None
    return message if "id" in raw else None


def _initialize(params: Mapping[str, object], opener: Opener) -> dict[str, object]:  # noqa: ARG001  (no workspace)
    asked = _parsed(_Initialize, params)
    version = asked.protocol_version if asked.protocol_version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "canopy", "version": db.CANOPY_VERSION},
    }


def _ping(params: Mapping[str, object], opener: Opener) -> dict[str, object]:  # noqa: ARG001  (nothing to say)
    return {}


def _list(params: Mapping[str, object], opener: Opener) -> dict[str, object]:  # noqa: ARG001  (no page to ask for)
    return {"tools": [] if _refusal(opener) is not None else [t.listed() for t in TOOLS]}


def _call(params: Mapping[str, object], opener: Opener) -> dict[str, object]:
    asked = _parsed(_Call, params)
    found = next((t for t in TOOLS if t.name == asked.name), None)
    if found is None:
        raise _Failed(INVALID_PARAMS, f"no tool named {asked.name!r}")
    if os.environ.get(conversation.RUN_ID_ENV):
        return _said(_inside_run(), error=True)
    try:
        return _said(found.call(asked.arguments or {}, opener))
    except ValidationError as e:
        return _said(tools.explain(e), error=True)
    except tools.Refused as e:
        return _said(str(e), error=True)
    except (config.ConfigError, db.MigrationError) as e:
        return _said(f"canopy: {e}", error=True)


_METHODS: Mapping[str, Callable[[Mapping[str, object], Opener], dict[str, object]]] = {
    "initialize": _initialize,
    "ping": _ping,
    "tools/list": _list,
    "tools/call": _call,
}


def _refusal(opener: Opener) -> str | None:
    """Say why no tool is served now: inside a run, or outside a running tick.

    Returns:
        Why, as a refusal says it, or None when tools are served.
    """
    if os.environ.get(conversation.RUN_ID_ENV):
        return _inside_run()
    try:
        with opener() as ctx:
            tools.running_tick(ctx)
    except tools.Refused as e:
        return str(e)
    except (config.ConfigError, db.MigrationError) as e:
        return f"canopy: {e}"
    return None


def _inside_run() -> str:
    return f"{conversation.RUN_ID_ENV} is set: canopy's tools are the overseer's, and refuse inside a run"


def _parsed[P: _Params](params_model: type[P], params: Mapping[str, object]) -> P:
    try:
        return params_model.model_validate(params)
    except ValidationError as e:
        raise _Failed(INVALID_PARAMS, tools.explain(e)) from None


def _said(text: str, *, error: bool = False) -> dict[str, object]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _id_of(raw: Mapping[str, object]) -> object:
    """Find the id of a message that is not a valid request.

    Returns:
        Its id when it has one JSON-RPC allows, else None.
    """
    found = raw.get("id")
    return found if isinstance(found, int | str) and not isinstance(found, bool) else None


def _inlined(node: object, definitions: Mapping[str, object], *, fields: bool = False) -> object:
    """Inline each `$ref` in `node`, and leave out each schema's `title`.

    `fields` marks a `properties` object, whose keys are field names, kept whatever they are.

    Returns:
        `node` with each reference replaced by the definition it names.
    """
    if isinstance(node, list):
        return [_inlined(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    if fields:
        return {name: _inlined(value, definitions) for name, value in node.items()}
    ref = node.get("$ref")
    if isinstance(ref, str):
        # A definition's description is its class's docstring, for canopy's readers; a field's own is kept.
        named = definitions.get(ref.rsplit("/", 1)[-1])
        defined = {k: v for k, v in named.items() if k != "description"} if isinstance(named, dict) else {}
        return _inlined({**defined, **{k: v for k, v in node.items() if k != "$ref"}}, definitions)
    return {
        key: _inlined(value, definitions, fields=key == "properties") for key, value in node.items() if key != "title"
    }
