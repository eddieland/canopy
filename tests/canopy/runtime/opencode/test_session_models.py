"""Which models served an OpenCode session, read from `opencode export` as OpenCode 1.19.3 prints it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from canopy.infra import procs
from canopy.runtime.opencode import session_models
from canopy.runtime.report import MAX_MODELS, OTHER_MODELS, ModelUse, SessionModels

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


def assistant(provider: str, model: str, cost: float) -> dict[str, object]:
    """An assistant message as `opencode export --sanitize` prints it, its parts redacted."""
    return {
        "info": {
            "id": "msg_2",
            "role": "assistant",
            "providerID": provider,
            "modelID": model,
            "cost": cost,
            "tokens": {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 0, "write": 0}},
            "path": {"cwd": "[redacted:cwd:msg_2]", "root": "[redacted:root:msg_2]"},
        },
        "parts": [{"type": "text", "text": "[redacted:text:prt_1]"}],
    }


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
            assistant("anthropic", "claude-haiku", 0.125),
            assistant("openrouter", "anthropic/claude-sonnet", 0.25),
            assistant("anthropic", "claude-haiku", 0.25),
            # OpenCode prints a cost of 0 as an integer.
            assistant("local", "free", 0),
        ),
    )
    assert read(export) == SessionModels(
        "found",
        (
            ModelUse("anthropic/claude-haiku", 2, 0.375),
            ModelUse("openrouter/anthropic/claude-sonnet", 1, 0.25),
            ModelUse("local/free", 1, 0.0),
        ),
    )
    # Sanitized, so canopy reads no transcript text; started where the caller says, bounded in time, and its stdout
    # read from a file, as OpenCode cuts what it prints to a pipe short.
    assert export.ran == [
        (("opencode", "export", "ses_1", "--sanitize"), Path("/ws"), session_models.TIMEOUT_SECONDS, True),
    ]


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
