"""The protocol canopy's MCP servers share, through a server of two tools that answers as each test needs."""

import json
from collections.abc import Mapping
from typing import Annotated

import canopy_mcp
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

#: A tool's call: echoes its text, or fails as a bug would.
type Echo = canopy_mcp.Tool[None, str]


class _Inner(BaseModel):
    """A nested field's model, whose docstring is the code's and stays out of the schema."""

    word: Annotated[str, Field(description="One word.")]


class _Said(BaseModel):
    """The request: what to echo."""

    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(description="What to echo.")]
    inner: Annotated[_Inner | None, Field(description="Something nested.")] = None


def _echo(arguments: Mapping[str, object], served: None) -> str:
    return _Said.model_validate(arguments).text


def _breaks(arguments: Mapping[str, object], served: None) -> str:
    raise RuntimeError("a bug")


TOOLS: tuple[Echo, ...] = (
    canopy_mcp.Tool("echo", "Echo text.", _Said, _echo, hints=canopy_mcp.READS),
    canopy_mcp.Tool("breaks", "Fail.", _Said, _breaks),
)


def server(*, listing: bool = True, failures: list[str] | None = None) -> canopy_mcp.Server[None, str]:
    """A server of `TOOLS`, which lists them only with `listing`, and adds each failure's method to `failures`."""

    def failed(method: str, error: Exception) -> str:
        if failures is not None:
            failures.append(method)
        return f"test failed: {type(error).__name__}"

    return canopy_mcp.Server(
        "test",
        "1.0",
        TOOLS,
        call=lambda found, arguments: canopy_mcp.said(found.call(arguments, None)),
        failed=failed,
        listing=lambda: listing,
    )


def ask(method: str, params: Mapping[str, object] | None = None, *, to: canopy_mcp.Server[None, str]) -> object:
    """Send one request, and return its response."""
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    return canopy_mcp.answer(line, to)


def test_it_answers_in_the_version_asked_for_or_its_newest() -> None:
    """A client is answered in the version it asks for when the server speaks it, else in the newest."""
    for asked, answered in (("2024-11-05", "2024-11-05"), ("1999-01-01", canopy_mcp.PROTOCOL_VERSIONS[0])):
        assert ask("initialize", {"protocolVersion": asked, "capabilities": {}}, to=server()) == {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": answered,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        }


def test_each_tool_is_listed_with_its_schema_and_annotations_only_while_the_server_lists() -> None:
    """A tool's schema inlines every reference and drops every title, and a docstring stays out of it."""
    listed = ask("tools/list", to=server())
    assert isinstance(listed, dict)
    echo, breaks = listed["result"]["tools"]
    assert echo["annotations"] == {"readOnlyHint": True, "openWorldHint": False}
    assert breaks["annotations"] == {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    }
    text = json.dumps(echo["inputSchema"])
    assert ("$ref" in text, '"title"' in text, "docstring" in text) == (False, False, False)
    assert echo["inputSchema"]["properties"]["inner"]["anyOf"][0]["properties"]["word"]["description"] == "One word."
    assert ask("tools/list", to=server(listing=False)) == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}


def test_a_call_is_answered_by_the_server_even_when_it_lists_nothing() -> None:
    """A call checks for itself: a server that lists no tool still answers one, as its own call says."""
    called = ask("tools/call", {"name": "echo", "arguments": {"text": "hi"}}, to=server(listing=False))
    assert called == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": "hi"}], "isError": False},
    }


def test_what_it_cannot_answer_is_a_json_rpc_error_and_it_goes_on_serving() -> None:
    """A line that is not JSON, a batch, a method or tool it lacks, and a bug each answer as JSON-RPC errors."""
    failures: list[str] = []
    served = server(failures=failures)
    lines = [
        b"{not json",
        b"[]",
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "resources/list"}).encode(),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}}).encode(),
        json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "breaks"}}).encode(),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"}).encode(),
    ]
    written: list[str] = []
    canopy_mcp.serve(lines, written.append, served)
    answers = [json.loads(line) for line in written]
    assert [(a.get("id"), a.get("error", {}).get("code")) for a in answers] == [
        (None, canopy_mcp.PARSE_ERROR),
        (None, canopy_mcp.INVALID_REQUEST),
        (2, canopy_mcp.METHOD_NOT_FOUND),
        (3, canopy_mcp.INVALID_PARAMS),
        (4, canopy_mcp.INTERNAL_ERROR),
        (5, None),
    ]
    assert answers[2]["error"]["message"] == "no method 'resources/list': test serves tools only"
    assert answers[4]["error"]["message"] == "test failed: RuntimeError"
    assert failures == ["tools/call"]


def test_explain_names_each_field_and_never_echoes_pydantics_copy_of_the_input() -> None:
    """What was wrong is told by field, without pydantic's copy of the value, which may be a whole page."""
    with pytest.raises(ValidationError) as raised:
        _Said.model_validate({"text": 7, "secret": "a page of text"})
    said = canopy_mcp.explain(raised.value)
    assert said.splitlines() == ["text: Input should be a valid string", "secret: Extra inputs are not permitted"]
    assert "a page of text" not in said
