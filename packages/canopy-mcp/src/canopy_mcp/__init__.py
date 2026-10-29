"""canopy's MCP server over stdio, for each server canopy ships (D124): the protocol, and how a tool is listed.

A server serves tools and nothing else: JSON-RPC 2.0, one message to a line, and five methods, `initialize`,
`notifications/initialized`, `ping`, `tools/list`, and `tools/call`. It opens no socket. Rejected: the `mcp` SDK, a
dependency with its own async stack and HTTP transports, for these few methods.

A server here is its tools and how it answers a call: what a refusal looks like, and what it catches, are its own.
A line it cannot read, a method it does not have, or a tool it does not list is a JSON-RPC error; a failure of its own
answers that request with one, and the server goes on serving.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

if TYPE_CHECKING:
    from pydantic.json_schema import JsonSchemaMode

#: The protocol versions a server speaks, newest first: a client that asks for one of them is answered in it, and any
#: other in the newest.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
#: JSON-RPC's error codes for a line that is not JSON, a message that is not a request, a method the server does not
#: have, parameters it cannot take, and a failure of its own.
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603

#: A JSON-RPC response, or None for a notification, which is never answered.
type Response = dict[str, object] | None


@dataclass(frozen=True)
class Hints:
    """What a tool does to the world, as MCP's tool annotations tell a client: hints for its prompts, never a guard.

    Every tool canopy ships works on canopy's own journal, a run's checkouts, or the local artifact store, never a world
    outside them, so none is open-world.
    """

    #: It changes nothing.
    read_only: bool
    #: It may overwrite or end what is already there, not only add to it. Only a tool that writes says.
    destructive: bool = False
    #: A second call with the same arguments changes nothing more. Only a tool that writes says.
    idempotent: bool = False

    def listed(self) -> dict[str, bool]:
        """Describe the hints as `tools/list` lists them, under the tool's `annotations`.

        Returns:
            MCP's hints: a tool that only reads says nothing of what a write would do.
        """
        hints = {"readOnlyHint": self.read_only, "openWorldHint": False}
        if not self.read_only:
            hints |= {"destructiveHint": self.destructive, "idempotentHint": self.idempotent}
        return hints


#: A tool that reads and changes nothing.
READS = Hints(read_only=True)
#: A tool that adds to what is there and removes nothing.
WRITES = Hints(read_only=False)


@dataclass(frozen=True)
class Tool[C, R]:
    """One tool: what the model reads of it, and the call, given what the server serves (`C`), answering with `R`."""

    #: Its name, as the runtime puts it after the server's.
    name: str
    #: What it does, when to use it, what it returns, and how it refuses, for the model.
    description: str
    #: Its request, whose schema is the tool's input schema.
    request: type[BaseModel]
    #: Validate its arguments, then do it with what the server serves.
    call: Callable[[Mapping[str, object], C], R]
    #: Its result, whose schema is the tool's output schema; None for a tool that answers with text alone.
    result: type[BaseModel] | None = None
    #: What it does to the world, for a client.
    hints: Hints = WRITES

    def listed(self) -> dict[str, object]:
        """Describe the tool as `tools/list` lists it.

        Returns:
            Its name, description, input schema, annotations, and output schema when it has a result.
        """
        listed: dict[str, object] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema(self.request),
            "annotations": self.hints.listed(),
        }
        if self.result is not None:
            listed["outputSchema"] = schema(self.result, "serialization")
        return listed


@dataclass(frozen=True)
class Server[C, R]:
    """One server: its name and version, its tools, and how it answers a call to one."""

    #: Its name, as `initialize` gives it.
    name: str
    #: Its version, as `initialize` gives it.
    version: str
    #: Every tool it serves.
    tools: Sequence[Tool[C, R]]
    #: Call a tool with its arguments: the `tools/call` result, `said`, with a refusal its tool error.
    call: Callable[[Tool[C, R], Mapping[str, object]], dict[str, object]]
    #: Report a failure of its own in a method, and say what the client is told of it.
    failed: Callable[[str, Exception], str]
    #: Whether it lists its tools now; one that lists none still answers each call, which checks for itself.
    listing: Callable[[], bool] = lambda: True


def serve[C, R](lines: Iterable[bytes], write: Callable[[str], object], server: Server[C, R]) -> None:
    """Answer each message in `lines` with `write`, one at a time, until `lines` ends."""
    for line in lines:
        if line.strip():
            response = answer(line, server)
            if response is not None:
                # Escaped to ASCII: a lone surrogate a client sent, echoed in a refusal, could not be written as UTF-8.
                write(json.dumps(response) + "\n")


def answer[C, R](line: bytes, server: Server[C, R]) -> Response:
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
    params = message.params
    result: dict[str, object]
    try:
        match message.method:
            case "initialize":
                result = _initialize(params, server)
            case "ping":
                result = {}
            case "tools/list":
                # One page: a server here lists few tools.
                result = {"tools": [t.listed() for t in server.tools] if server.listing() else []}
            case "tools/call":
                result = _call(params, server)
            case _:
                note = f"no method {message.method!r}: {server.name} serves tools only"
                return _error(message.id, METHOD_NOT_FOUND, note)
    except _Failed as e:
        return _error(message.id, e.code, str(e))
    except Exception as e:  # noqa: BLE001  (a bug answers this request, and the server goes on serving)
        return _error(message.id, INTERNAL_ERROR, server.failed(message.method, e))
    return {"jsonrpc": "2.0", "id": message.id, "result": result}


def said(text: str, *, error: bool = False, structured: BaseModel | None = None) -> dict[str, object]:
    """Answer a tool call with `text`, a tool error with `error`, and `structured` as its structured content.

    Returns:
        The `tools/call` result.
    """
    result: dict[str, object] = {"content": [{"type": "text", "text": text}], "isError": error}
    if structured is not None:
        result["structuredContent"] = structured.model_dump(mode="json")
    return result


def explain(error: ValidationError) -> str:
    """Say what was wrong with a request, as a model reads it from a tool's error.

    It names each field and what was wrong with it, never pydantic's copy of the input; a check echoes a value only for
    short, bounded fields, never free text, which may be a tracker's or a reviewer's, or a whole page.

    Returns:
        One line per problem: a rule across fields as its own sentence, a field's as `field: problem`.
    """
    lines: list[str] = []
    for problem in error.errors(include_url=False, include_input=False):
        where = ".".join(str(part) for part in problem["loc"])
        cause = (problem.get("ctx") or {}).get("error")
        what = str(cause) if problem["type"] == "value_error" and cause is not None else problem["msg"]
        lines.append(f"{where}: {what}" if where else what)
    return "\n".join(lines)


def schema(model: type[BaseModel], mode: JsonSchemaMode = "validation") -> dict[str, object]:
    """Return a model's JSON schema as a tool's: every reference inlined, and no titles.

    A request's, in `mode` "validation", is its tool's input schema; a result's, in "serialization", its output schema.
    Some models' providers take no `$ref`, and a title only repeats its field's name. What a docstring says is for the
    code's readers, so only the fields' own descriptions are kept.

    Returns:
        The schema, an object that holds no field the model does not.
    """
    whole = model.model_json_schema(mode=mode)
    # The model's docstring says what it is to the code's readers; the tool's description says what it does.
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
    params: Mapping[str, object] = Field(default_factory=dict[str, object])


class _Params(BaseModel):
    # A method's parameters keep a field the protocol adds in a later version, such as `_meta`, which a server here has
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
        raise _Failed(INVALID_REQUEST, explain(e), _id_of(raw)) from None
    return message if "id" in raw else None


def _initialize[C, R](params: Mapping[str, object], server: Server[C, R]) -> dict[str, object]:
    asked = _parsed(_Initialize, params)
    version = asked.protocol_version if asked.protocol_version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": server.name, "version": server.version},
    }


def _call[C, R](params: Mapping[str, object], server: Server[C, R]) -> dict[str, object]:
    asked = _parsed(_Call, params)
    found = next((t for t in server.tools if t.name == asked.name), None)
    if found is None:
        raise _Failed(INVALID_PARAMS, f"no tool named {asked.name!r}")
    return server.call(found, asked.arguments or {})


def _parsed[P: _Params](params_model: type[P], params: Mapping[str, object]) -> P:
    try:
        return params_model.model_validate(params)
    except ValidationError as e:
        raise _Failed(INVALID_PARAMS, explain(e)) from None


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
        # A definition's description is its class's docstring, for the code's readers; a field's own is kept.
        named = definitions.get(ref.rsplit("/", 1)[-1])
        defined = {k: v for k, v in named.items() if k != "description"} if isinstance(named, dict) else {}
        return _inlined({**defined, **{k: v for k, v in node.items() if k != "$ref"}}, definitions)
    return {
        key: _inlined(value, definitions, fields=key == "properties") for key, value in node.items() if key != "title"
    }
