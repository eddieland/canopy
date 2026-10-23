"""The models OpenCode 2 lists to run an agent on, asked of a private server as OpenCode 2.1.4 answers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.infra import procs
from canopy.runtime.opencode2 import models
from canopy.runtime.report import ModelList

if TYPE_CHECKING:
    from collections.abc import Sequence

#: What OpenCode 2.1.4 listed in a workspace whose config adds a provider, `stub`, cut to three of its models: one of
#: its own with no variants, one whose `id` is not its `modelID`, and the config's, its key in its `settings`.
RECORDED = Path(__file__).parent / "recorded" / "model-list.json"
#: The command canopy asks the list with.
ARGV = ("opencode", "api", "--standalone", "model.list")


def runner(stdout: str = "", *, code: int = 0, timed_out: bool = False) -> mock.NonCallableMagicMock:
    def printed(args: Sequence[str], **_: object) -> procs.Result:
        return procs.Result(tuple(args), code, stdout, "", timed_out=timed_out)

    found = mock.create_autospec(procs.SubprocessRunner, instance=True)
    found.run.side_effect = printed
    return found


def listing(*entries: object) -> str:
    return json.dumps({"location": {"directory": "/ws"}, "data": entries})


def test_a_recorded_list_gives_each_model_by_its_provider_and_id() -> None:
    list_runner = runner(RECORDED.read_text())
    assert models.listed(list_runner, cwd=Path("/ws")) == ModelList(
        frozenset({"opencode/mimo-v2.6-flash-free", "github-copilot/claude-opus-4.8-fast", "stub/stub-1"}),
    )
    # Started where the caller says, on a private server, bounded in time, and its stdout read from a file, as OpenCode
    # cuts what it prints to a pipe short.
    list_runner.run.assert_called_once_with(
        list(ARGV),
        cwd=Path("/ws"),
        timeout=models.TIMEOUT_SECONDS,
        stdout_to_file=True,
    )


def test_with_variants_each_models_variants_are_read() -> None:
    assert models.listed(runner(RECORDED.read_text()), cwd=Path("/ws"), variants=True).variants == {
        "opencode/mimo-v2.6-flash-free": frozenset(),
        "github-copilot/claude-opus-4.8-fast": frozenset({"low", "medium", "high", "xhigh", "max"}),
        "stub/stub-1": frozenset({"deep"}),
    }


def test_an_entry_that_names_no_model_canopy_renders_is_passed_over() -> None:
    printed = listing(
        {"providerID": "anthropic", "id": "claude-x", "variants": [{"id": "high"}]},
        {"providerID": "", "id": "nameless"},
        {"providerID": "bad provider", "id": "x"},
    )
    assert models.listed(runner(printed), cwd=Path("/ws"), variants=True) == ModelList(
        frozenset({"anthropic/claude-x"}),
        {"anthropic/claude-x": frozenset({"high"})},
    )


def test_an_opencode_with_no_provider_lists_no_model() -> None:
    assert models.listed(runner(listing()), cwd=Path("/ws")) == ModelList()


@pytest.mark.parametrize(
    ("list_runner", "error"),
    [
        (runner(code=1), "`opencode api model.list` exited 1"),
        (runner(listing(), timed_out=True, code=-9), "`opencode api model.list` took over 60 seconds"),
        # What it printed is not quoted: a model's settings may hold a provider's key.
        (runner('{"data": [{"providerID": "x", "settings": {"apiKey": "sk-s3cret"}}]}'), "printed what canopy"),
        (runner("not json"), "printed what canopy cannot read"),
    ],
)
def test_a_list_that_cannot_be_read_says_why_in_canopy_s_words(
    list_runner: mock.NonCallableMagicMock,
    error: str,
) -> None:
    found = models.listed(list_runner, cwd=Path("/ws"))
    assert found.models == frozenset()
    assert found.error is not None
    assert error in found.error
    assert "s3cret" not in found.error


def test_opencode_missing_from_path_fails() -> None:
    missing = mock.create_autospec(procs.SubprocessRunner, instance=True)
    missing.run.side_effect = procs.CommandNotFoundError("opencode")
    assert models.listed(missing, cwd=Path("/ws")) == ModelList(error="opencode is not on PATH")
