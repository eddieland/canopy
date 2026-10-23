"""The models OpenCode lists to run an agent on, read from `opencode models` as OpenCode 1.19.3 prints it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from canopy.infra import procs
from canopy.runtime.opencode import models
from canopy.runtime.report import ModelList

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


@dataclass
class Models:
    """Plays `opencode models`, answering with `result`, and records what it was run with."""

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


def printing(stdout: str = "", *, code: int = 0, timed_out: bool = False) -> Models:
    return Models(lambda args: procs.Result(tuple(args), code, stdout, "", timed_out=timed_out))


def test_each_model_listed_is_read_and_any_other_line_passed_over() -> None:
    runner = printing(
        "[corp-plugin] loaded\nanthropic/claude-x\nopenrouter/vendor/model-y:free\n\n  local/qwen@2b  \nnot a model\n",
    )
    assert models.listed(runner, cwd=Path("/ws")) == ModelList(
        frozenset({"anthropic/claude-x", "openrouter/vendor/model-y:free", "local/qwen@2b"}),
    )
    # Started where the caller says, bounded in time, and its stdout read from a file, as OpenCode cuts what it prints
    # to a pipe short.
    assert runner.ran == [(("opencode", "models"), Path("/ws"), models.TIMEOUT_SECONDS, True)]


def test_an_opencode_with_no_provider_lists_no_model() -> None:
    assert models.listed(printing(""), cwd=Path("/ws")) == ModelList()


@pytest.mark.parametrize(
    ("runner", "error"),
    [
        (printing(code=1), "`opencode models` exited 1"),
        (printing("anthropic/claude-x\n", timed_out=True, code=-9), "`opencode models` took over 30 seconds"),
    ],
)
def test_a_list_that_cannot_be_read_says_why_in_canopy_s_words(runner: Models, error: str) -> None:
    assert models.listed(runner, cwd=Path("/ws")) == ModelList(error=error)


def test_opencode_missing_from_path_fails() -> None:
    def missing(args: Sequence[str]) -> procs.Result:
        raise procs.CommandNotFoundError(args[0])

    assert models.listed(Models(missing), cwd=Path("/ws")) == ModelList(error="opencode is not on PATH")
