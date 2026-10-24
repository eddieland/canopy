"""Which models served an OpenCode session, read from `opencode export` as OpenCode 1.19.3 prints it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from canopy.infra import procs
from canopy.runtime.opencode import session_models
from canopy.runtime.report import MAX_MODELS, MAX_REPLIES, OTHER_MODELS, ModelUse, SessionModels

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


def assistant(
    provider: str,
    model: str,
    cost: float,
    *,
    variant: str | None = None,
    message: str = "msg_2",
) -> dict[str, object]:
    """An assistant message as `opencode export --sanitize` prints it, its parts redacted.

    OpenCode leaves `variant` out for the model's default.
    """
    info: dict[str, object] = {
        "id": message,
        "role": "assistant",
        "providerID": provider,
        "modelID": model,
        "cost": cost,
        "tokens": {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 0, "write": 0}},
        "path": {"cwd": "[redacted:cwd:msg_2]", "root": "[redacted:root:msg_2]"},
    }
    if variant is not None:
        info["variant"] = variant
    return {"info": info, "parts": [{"type": "text", "text": "[redacted:text:prt_1]"}]}


#: The user's message, which names the model it asked for rather than one that served.
USER: dict[str, object] = {
    "info": {"id": "msg_1", "role": "user", "model": {"providerID": "anthropic", "modelID": "asked"}},
    "parts": [],
}


def exported(*messages: Mapping[str, object]) -> str:
    return json.dumps({"info": {"id": "ses_1", "title": "[redacted:session-title:ses_1]"}, "messages": messages})


@dataclass
class Export:
    """Plays `opencode export`, answering with `result`, and records what it was run with."""

    result: Callable[[Sequence[str]], procs.Result]
    ran: list[tuple[tuple[str, ...], Path | None, float | None, bool]] = field(default_factory=list)

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,  # noqa: ARG002
        stdin: str | None = None,  # noqa: ARG002
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,  # noqa: ARG002
        on_line: Callable[[str], None] | None = None,  # noqa: ARG002
        stdout_to_file: bool = False,
    ) -> procs.Result:
        self.ran.append((tuple(args), cwd, timeout, stdout_to_file))
        return self.result(args)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002
        raise AssertionError(args)


def printing(stdout: str = "", *, code: int = 0, stderr: str = "", timed_out: bool = False) -> Export:
    return Export(lambda args: procs.Result(tuple(args), code, stdout, stderr, timed_out=timed_out))


def read(export: Export) -> SessionModels:
    return session_models.read(export, cwd=Path("/ws"), session_id="ses_1")


def test_each_model_s_replies_and_cost_are_summed_the_most_costly_first() -> None:
    export = printing(
        exported(
            USER,
            assistant("anthropic", "claude-haiku", 0.125, message="msg_2"),
            assistant("openrouter", "anthropic/claude-sonnet", 0.25, message="msg_3"),
            assistant("anthropic", "claude-haiku", 0.25, message="msg_4"),
            # OpenCode prints a cost of 0 as an integer.
            assistant("local", "free", 0, message="msg_5"),
        ),
    )
    # Each reply's model by its message, as the models are named, so a transcript names each call's.
    assert read(export) == SessionModels(
        "found",
        (
            ModelUse("anthropic/claude-haiku", 2, 0.375),
            ModelUse("openrouter/anthropic/claude-sonnet", 1, 0.25),
            ModelUse("local/free", 1, 0.0),
        ),
        replies={
            "msg_2": "anthropic/claude-haiku",
            "msg_3": "openrouter/anthropic/claude-sonnet",
            "msg_4": "anthropic/claude-haiku",
            "msg_5": "local/free",
        },
    )
    # Sanitized, so canopy reads no transcript text; started where the caller says, bounded in time, and its stdout
    # read from a file, as OpenCode cuts what it prints to a pipe short.
    assert export.ran == [
        (("opencode", "export", "ses_1", "--sanitize"), Path("/ws"), session_models.TIMEOUT_SECONDS, True),
    ]


def test_each_variant_of_a_model_is_counted_on_its_own() -> None:
    user: dict[str, object] = {
        "info": {
            "id": "msg_1",
            "role": "user",
            "model": {"providerID": "anthropic", "modelID": "claude-opus", "variant": "asked"},
        },
        "parts": [],
    }
    export = printing(
        exported(
            user,
            assistant("anthropic", "claude-opus", 0.5, variant="high", message="msg_2"),
            assistant("anthropic", "claude-opus", 0.25, message="msg_3"),
            assistant("anthropic", "claude-opus", 0.5, variant="high", message="msg_4"),
        ),
    )
    assert read(export) == SessionModels(
        "found",
        (ModelUse("anthropic/claude-opus@high", 2, 1.0), ModelUse("anthropic/claude-opus", 1, 0.25)),
        replies={
            "msg_2": "anthropic/claude-opus@high",
            "msg_3": "anthropic/claude-opus",
            "msg_4": "anthropic/claude-opus@high",
        },
    )


def test_a_session_one_model_served_keeps_no_reply_s_model() -> None:
    export = printing(
        exported(
            USER,
            assistant("anthropic", "claude-haiku", 0.125, message="msg_2"),
            assistant("anthropic", "claude-haiku", 0.25, message="msg_3"),
        ),
    )
    # Its models name them all.
    assert read(export) == SessionModels("found", (ModelUse("anthropic/claude-haiku", 2, 0.375),))


def test_a_reply_whose_message_canopy_would_not_keep_counts_without_its_model() -> None:
    export = printing(
        exported(
            assistant("anthropic", "claude-haiku", 0.25, message="msg_2"),
            assistant("anthropic", "claude-opus", 0.5, message="msg 3; rm -rf /"),
            assistant("anthropic", "claude-opus", 0.5, message="m" * 101),
        ),
    )
    found = read(export)
    assert found.models == (ModelUse("anthropic/claude-opus", 2, 1.0), ModelUse("anthropic/claude-haiku", 1, 0.25))
    assert found.replies == {"msg_2": "anthropic/claude-haiku"}


def test_past_the_limit_a_reply_s_model_is_not_kept() -> None:
    replies = [assistant("p", "a" if i % 2 else "b", 0.0, message=f"msg_{i}") for i in range(MAX_REPLIES + 3)]
    found = read(printing(exported(*replies)))
    assert sum(m.replies for m in found.models) == MAX_REPLIES + 3
    assert len(found.replies) == MAX_REPLIES
    assert "msg_0" in found.replies
    assert f"msg_{MAX_REPLIES}" not in found.replies


def test_a_session_that_made_no_model_call_has_no_models() -> None:
    assert read(printing(exported(USER))) == SessionModels("found")


def test_a_session_opencode_does_not_have_is_missing() -> None:
    export = printing(code=1, stderr="Exporting session: ses_1\nError: Session not found: ses_1\n")
    assert read(export) == SessionModels("missing")


@pytest.mark.parametrize(
    ("export", "error"),
    [
        (printing(code=1, stderr="Error: database is locked"), "`opencode export --sanitize` exited 1"),
        (printing(timed_out=True, code=-9), "`opencode export --sanitize` took over 60 seconds"),
        (printing("not json"), "`opencode export --sanitize` printed what canopy cannot read"),
        (printing(exported(assistant("a", "b", -1))), "`opencode export --sanitize` printed what canopy cannot read"),
    ],
)
def test_a_read_that_cannot_be_trusted_fails_in_canopy_s_words(export: Export, error: str) -> None:
    assert read(export) == SessionModels("failed", error=error)


#: The export as OpenCode prints it, indented, of a session one model served.
PRETTY = json.dumps(json.loads(exported(assistant("anthropic", "claude-haiku", 0.5))), indent=2)


@pytest.mark.parametrize(
    "stdout",
    [
        f"[corp-plugin] loaded v2.1\nhooks ready {{\n{PRETTY}\n",
        f"{PRETTY}\n[corp-plugin] flushed 3 events\n{{ unclosed\n",
        f'{{"level": "info", "msg": "corp-plugin up"}}\n{PRETTY}\n{{"messages": "not these"}}\n',
    ],
    ids=["before", "after", "json-lines-around"],
)
def test_the_export_is_read_from_among_what_a_plugin_prints(stdout: str) -> None:
    assert read(printing(stdout)) == SessionModels("found", (ModelUse("anthropic/claude-haiku", 1, 0.5),))


def test_a_plugin_s_output_alone_is_not_an_export() -> None:
    stdout = '[corp-plugin] loaded\n{"level": "info"}\n{"messages": [{"info": {}}]}\n'
    assert read(printing(stdout)) == SessionModels(
        "failed",
        error="`opencode export --sanitize` printed what canopy cannot read",
    )


def test_opencode_missing_from_path_fails() -> None:
    def missing(args: Sequence[str]) -> procs.Result:
        raise procs.CommandNotFoundError(args[0])

    assert read(Export(missing)) == SessionModels("failed", error="opencode is not on PATH")


def test_a_model_name_is_made_printable_and_past_the_limit_counted_together() -> None:
    names = [assistant("p", f"m{i}", 1.0) for i in range(MAX_MODELS + 2)]
    found = read(printing(exported(assistant("evil", "x\x1b[2J y", 5.0), *names)))
    assert found.models[0] == ModelUse("evil/x[2Jy", 1, 5.0)
    assert len(found.models) == MAX_MODELS + 1
    assert ModelUse(OTHER_MODELS, 3, 3.0) in found.models


def test_a_session_id_opencode_would_read_as_an_option_is_never_passed() -> None:
    export = printing(exported())
    assert session_models.read(export, cwd=Path("/ws"), session_id="--help") == SessionModels(
        "failed",
        error="not a session id OpenCode names",
    )
    assert export.ran == []
