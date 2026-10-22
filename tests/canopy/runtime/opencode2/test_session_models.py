"""Which models served an OpenCode 2 session, read from `opencode session export` as OpenCode 2.1.2 prints it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.infra import procs
from canopy.runtime.opencode2 import session_models
from canopy.runtime.report import MAX_MODELS, OTHER_MODELS, ModelUse, SessionModels

if TYPE_CHECKING:
    from collections.abc import Sequence

#: What OpenCode 2.1.2 exported, sanitized, of the recorded run in `recorded/run.jsonl`: five replies of one model.
RECORDED = Path(__file__).parent / "recorded" / "export.json"


def assistant(provider: str, model: str, cost: float, *, variant: str | None = None) -> dict[str, object]:
    """A reply as `opencode session export --sanitize` prints it, its content redacted; no variant for the default."""
    ref: dict[str, object] = {"id": model, "providerID": provider}
    if variant is not None:
        ref["variant"] = variant
    return {"id": "msg_2", "type": "assistant", "agent": "canopy-worker", "model": ref, "content": [], "cost": cost}


#: The prompt and a model switch, which name no model that served.
OTHERS: tuple[dict[str, object], ...] = (
    {"id": "msg_0", "type": "model-switched", "model": {"id": "asked", "providerID": "anthropic"}},
    {"id": "msg_1", "type": "user", "text": "[redacted:text]", "files": []},
)


def exported(*messages: object) -> str:
    return json.dumps({"info": {"id": "ses_1", "title": "[redacted:session-title:ses_1]"}, "messages": messages})


def runner(stdout: str = "", *, code: int = 0, stderr: str = "", timed_out: bool = False) -> mock.NonCallableMagicMock:
    def printed(args: Sequence[str], **_: object) -> procs.Result:
        return procs.Result(tuple(args), code, stdout, stderr, timed_out=timed_out)

    found = mock.create_autospec(procs.SubprocessRunner, instance=True)
    found.run.side_effect = printed
    return found


def read(export: procs.Runner, session_id: str = "ses_1") -> SessionModels:
    return session_models.read(export, cwd=Path("/ws"), session_id=session_id)


def test_a_recorded_export_gives_its_one_model_and_what_its_replies_cost() -> None:
    found = read(runner(RECORDED.read_text()))
    assert found.outcome == "found"
    assert [(m.model, m.replies) for m in found.models] == [("anthropic/stand-in", 5)]
    assert found.models[0].cost_usd == pytest.approx(0.00548125)


def test_each_model_s_replies_and_cost_are_summed_the_most_costly_first_on_a_private_server() -> None:
    export = runner(
        exported(
            *OTHERS,
            assistant("anthropic", "claude-haiku", 0.125),
            assistant("openrouter", "anthropic/claude-sonnet", 0.25),
            assistant("anthropic", "claude-haiku", 0.25),
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
    # Sanitized, on a server of its own rather than the shared service, and its stdout read from a file.
    export.run.assert_called_once_with(
        ["opencode", "session", "export", "--standalone", "--sanitize", "ses_1"],
        cwd=Path("/ws"),
        timeout=session_models.TIMEOUT_SECONDS,
        stdout_to_file=True,
    )


def test_each_variant_of_a_model_is_counted_on_its_own_as_opencode_2_spells_it() -> None:
    export = runner(
        exported(
            assistant("anthropic", "claude-opus", 0.5, variant="high"),
            assistant("anthropic", "claude-opus", 0.25),
            assistant("anthropic", "claude-opus", 0.5, variant="high"),
        ),
    )
    assert read(export) == SessionModels(
        "found",
        (ModelUse("anthropic/claude-opus#high", 2, 1.0), ModelUse("anthropic/claude-opus", 1, 0.25)),
    )


def test_a_session_opencode_does_not_have_is_missing() -> None:
    assert read(runner(code=1, stderr="Session not found: ses_1\n")) == SessionModels("missing")


@pytest.mark.parametrize(
    ("export", "error"),
    [
        (runner(code=1, stderr="database is locked"), "`opencode session export --sanitize` exited 1"),
        (runner(timed_out=True, code=-9), "`opencode session export --sanitize` took over 60 seconds"),
        (runner("not json"), "`opencode session export --sanitize` printed what canopy cannot read"),
        (
            runner(exported(assistant("a", "b", -1))),
            "`opencode session export --sanitize` printed what canopy cannot read",
        ),
    ],
)
def test_a_read_that_cannot_be_trusted_fails_in_canopy_s_words(export: procs.Runner, error: str) -> None:
    assert read(export) == SessionModels("failed", error=error)


def test_the_export_is_read_from_among_what_else_was_printed() -> None:
    pretty = json.dumps(json.loads(exported(assistant("anthropic", "claude-haiku", 0.5))), indent=2)
    stdout = f'{{"level": "info", "msg": "corp-plugin up"}}\n{pretty}\n{{"messages": "not these"}}\n'
    assert read(runner(stdout)) == SessionModels("found", (ModelUse("anthropic/claude-haiku", 1, 0.5),))


def test_opencode_missing_from_path_fails() -> None:
    export = runner()
    export.run.side_effect = procs.CommandNotFoundError("opencode")
    assert read(export) == SessionModels("failed", error="opencode is not on PATH")


def test_a_model_name_is_made_printable_and_past_the_limit_counted_together() -> None:
    names = [assistant("p", f"m{i}", 1.0) for i in range(MAX_MODELS + 2)]
    found = read(runner(exported(assistant("evil", "x\x1b[2J y", 5.0), *names)))
    assert found.models[0] == ModelUse("evil/x[2Jy", 1, 5.0)
    assert len(found.models) == MAX_MODELS + 1
    assert ModelUse(OTHER_MODELS, 3, 3.0) in found.models


def test_a_session_id_opencode_would_read_as_an_option_is_never_passed() -> None:
    export = runner(exported())
    assert read(export, "--help") == SessionModels("failed", error="not a session id OpenCode names")
    export.run.assert_not_called()
