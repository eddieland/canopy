"""The local store's MCP server, over stdio (DESIGN §38): the agent runtime starts it, and it lives as long as the run.

It opens no socket, and serves tools and nothing else: JSON-RPC 2.0, one message to a line, and the methods
`initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`, as canopy's own server does (D124).
Rejected: the `mcp` SDK, a dependency with its own async stack and HTTP transports, for these few methods.

A refusal, or arguments a tool's schema refuses, is a tool error, `isError`, whose text is one JSON object,
`{"code": ..., "message": ...}`; the server goes on serving. Nothing but the protocol is written to stdout.
"""

from __future__ import annotations

import contextlib
import json
import sys
import traceback
from collections.abc import Callable, Iterable, Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from canopy_artifacts.store import Code, Refused, Store
from canopy_artifacts.tools import TOOLS, Tool

#: The protocol versions the server speaks, newest first: a client that asks for one of them is answered in it, and
#: any other in the newest.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
#: The server's name, as `initialize` gives it.
NAME = "canopy-artifacts"
#: JSON-RPC's error codes for a line that is not JSON, a message that is not a request, a method the server does not
#: have, parameters it cannot take, and a failure of its own.
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603

#: A JSON-RPC response, or None for a notification, which is never answered.
type Response = dict[str, object] | None


def run_stdio(store: Store) -> int:
    """Serve `store` on this process's stdin and stdout until stdin closes.

    Returns:
        0, once stdin has closed or the client stopped reading.
    """

    def write(line: str) -> None:
        sys.stdout.write(line)
        sys.stdout.flush()

    with contextlib.suppress(BrokenPipeError):
        serve(sys.stdin.buffer, write, store)
    return 0


def serve(lines: Iterable[bytes], write: Callable[[str], object], store: Store) -> None:
    """Answer each message in `lines` with `write`, one at a time, until `lines` ends."""
    for line in lines:
        if line.strip():
            response = answer(line, store)
            if response is not None:
                # Escaped to ASCII: a lone surrogate a client sent, echoed back, could not be written as UTF-8.
                write(json.dumps(response) + "\n")


def answer(line: bytes, store: Store) -> Response:
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
        return _error(message.id, METHOD_NOT_FOUND, f"no method {message.method!r}: {NAME} serves tools only")
    try:
        result = method(message.params, store)
    except _Failed as e:
        return _error(message.id, e.code, str(e))
    except Exception as e:  # noqa: BLE001  (a bug answers this request, and the server goes on serving)
        traceback.print_exception(e, file=sys.stderr)
        return _error(message.id, INTERNAL_ERROR, f"{NAME} failed: {type(e).__name__}")
    return {"jsonrpc": "2.0", "id": message.id, "result": result}


def listed(found: Tool) -> dict[str, object]:
    """Describe a tool as `tools/list` lists it.

    Returns:
        Its name, description, and input schema, every reference inlined and no title, since some models' providers
        take no `$ref`, and a title only repeats its field's name.
    """
    whole = found.request.model_json_schema()
    # The request's docstring is for the store's readers; the tool's description says what it does.
    whole.pop("description", None)
    definitions = whole.pop("$defs", {})
    schema = _inlined(whole, definitions if isinstance(definitions, dict) else {})
    return {"name": found.name, "description": found.description, "inputSchema": schema}


class _Message(BaseModel):
    """A JSON-RPC 2.0 request, or a notification without its `id`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    jsonrpc: Literal["2.0"]
    id: StrictInt | StrictStr | None = None
    method: StrictStr
    params: Mapping[str, object] = Field(default_factory=dict[str, object])


class _Params(BaseModel):
    # A method's parameters keep a field a later protocol version adds, such as `_meta`; a tool's arguments do not.
    model_config = ConfigDict(extra="ignore", frozen=True)


class _Initialize(_Params):
    protocol_version: Annotated[StrictStr, Field(alias="protocolVersion")]


class _Call(_Params):
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
        The request, or None for a notification.

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
        found = raw.get("id")
        request_id = found if isinstance(found, int | str) and not isinstance(found, bool) else None
        raise _Failed(INVALID_REQUEST, _explain(e), request_id) from None
    return message if "id" in raw else None


def _initialize(params: Mapping[str, object], store: Store) -> dict[str, object]:  # noqa: ARG001
    asked = _parsed(_Initialize, params)
    version = asked.protocol_version if asked.protocol_version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": NAME, "version": _version()},
    }


def _ping(params: Mapping[str, object], store: Store) -> dict[str, object]:  # noqa: ARG001
    return {}


def _list(params: Mapping[str, object], store: Store) -> dict[str, object]:  # noqa: ARG001  (one page)
    return {"tools": [listed(t) for t in TOOLS]}


def _call(params: Mapping[str, object], store: Store) -> dict[str, object]:
    asked = _parsed(_Call, params)
    found = next((t for t in TOOLS if t.name == asked.name), None)
    if found is None:
        raise _Failed(INVALID_PARAMS, f"no tool named {asked.name!r}")
    try:
        return _said(found.call(asked.arguments or {}, store))
    except ValidationError as e:
        return _refused(Code.INVALID, _explain(e))
    except Refused as e:
        return _refused(e.code, str(e))
    except OverflowError:
        # SQLite's integers are 64 bits; a JSON number need not be.
        return _refused(Code.INVALID, "a number is past the most the store holds")


_METHODS: Mapping[str, Callable[[Mapping[str, object], Store], dict[str, object]]] = {
    "initialize": _initialize,
    "ping": _ping,
    "tools/list": _list,
    "tools/call": _call,
}


def _parsed[P: _Params](params_model: type[P], params: Mapping[str, object]) -> P:
    try:
        return params_model.model_validate(params)
    except ValidationError as e:
        raise _Failed(INVALID_PARAMS, _explain(e)) from None


def _explain(error: ValidationError) -> str:
    """Say what is wrong with arguments, without echoing them: a value may be a whole page.

    Returns:
        Each problem, `where: what`, joined by semicolons.
    """
    return "; ".join(
        f"{'.'.join(str(at) for at in problem['loc']) or 'arguments'}: {problem['msg']}" for problem in error.errors()
    )


def _said(text: str) -> dict[str, object]:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _refused(code: Code, message: str) -> dict[str, object]:
    text = json.dumps({"code": code.value, "message": message}, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _version() -> str:
    from importlib import metadata  # noqa: PLC0415  (read once, at initialize)

    try:
        return metadata.version(NAME)
    except metadata.PackageNotFoundError:
        return "0.0.0"


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
        # A definition's description is its class's docstring; a field's own is kept.
        named = definitions.get(ref.rsplit("/", 1)[-1])
        defined = {k: v for k, v in named.items() if k != "description"} if isinstance(named, dict) else {}
        return _inlined({**defined, **{k: v for k, v in node.items() if k != "$ref"}}, definitions)
    return {
        key: _inlined(value, definitions, fields=key == "properties") for key, value in node.items() if key != "title"
    }
