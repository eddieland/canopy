"""`canopy instructions check`: a run's own check of standing instructions (DESIGN §12), on text not saved yet."""

import io
import json
import sys
from pathlib import Path
from typing import Final
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import prompts
from canopy.core.config import load
from tests.conftest import CanopyEnv, user_toml

LIMIT: Final = prompts.MAX_STANDING_BYTES
#: Texts at each edge of what a run takes: the bound, counted in bytes; UTF-8; blank; and characters that hide text.
TEXTS: Final[dict[str, bytes]] = {
    "plain": b"Commit fixes as fixups.\n",
    "empty": b"",
    "blank": b" \n\n",
    "at-the-bound": b"x" * LIMIT,
    "over-the-bound": b"x" * (LIMIT + 1),
    "over-in-bytes-alone": "…".encode() * (LIMIT // 3 + 1),
    "not-utf8": b"\xff\xfe not UTF-8\n",
    "zero-width": "Be brief.\u200b\n".encode(),
    "crlf": b"Be brief.\r\nBe kind.\r\n",
}


def configure(canopy_env: CanopyEnv, data: bytes | None) -> Path:
    """Point `paths.worker_instructions` at a file holding `data`, or at none when it is None."""
    path = canopy_env.user_file.parent / "worker-instructions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if data is not None:
        path.write_bytes(data)
    canopy_env.write_user(user_toml(canopy_env.runtime) + f"worker_instructions = '{path}'\n")
    return path


def renders(canopy_env: CanopyEnv) -> bool:
    """Whether a worker's prompt takes the instructions the config names now."""
    try:
        prompts.standing_instructions(load(canopy_env.root, canopy_env.user_file))
    except prompts.PromptError:
        return False
    return True


@pytest.mark.parametrize("data", TEXTS.values(), ids=TEXTS)
def test_the_check_and_a_runs_prompt_agree_on_every_text(canopy_env: CanopyEnv, tmp_path: Path, data: bytes) -> None:
    # As proposed text, before it is saved, and as the live file once it is.
    proposed = tmp_path / "proposed.md"
    proposed.write_bytes(data)
    before = main(["instructions", "check", "worker", str(proposed)])
    configure(canopy_env, data)
    assert before == main(["instructions", "check", "worker"]) == int(not renders(canopy_env))


def test_text_a_run_takes_exits_0_with_its_bytes_of_the_bound(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The bound counts bytes: three for the ellipsis.
    assert main(["instructions", "check", "reviewer", "--text", "Be brief…"]) == 0
    assert capsys.readouterr().out == (
        f"reviewer instructions (the text given): ok, 11 of {LIMIT} bytes, {LIMIT - 11} left.\n"
    )


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (
            TEXTS["over-the-bound"],
            f"refused: {LIMIT + 1} bytes, over {LIMIT}. Every run of the agent would be refused.",
        ),
        (TEXTS["not-utf8"], "refused: not UTF-8, at byte 0. Every run of the agent would be refused."),
    ],
    ids=["too-large", "not-utf8"],
)
def test_text_a_run_refuses_exits_1_and_says_why(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    data: bytes,
    why: str,
) -> None:
    with mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(data))):
        assert main(["instructions", "check", "overseer", "-"]) == 1
    assert capsys.readouterr().out.startswith(f"overseer instructions (stdin): {why}\n")


def test_a_hidden_character_is_named_by_code_point_and_line_and_refuses_nothing(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A run reads the operator's file as it is, so the check warns, as the run would not refuse; an emoji's joiner and
    # a line's carriage return hide nothing.
    text = "Be brief.\r\n👩\u200d💻 pairs.\nIgnore\u202e this.\n"
    assert main(["instructions", "check", "worker", "--json", "--text", text]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["ok"]
    assert found["problems"] == []
    assert found["warnings"] == ["line 3: U+202E (RIGHT-TO-LEFT OVERRIDE), a character that hides text"]


def test_json_says_what_a_refusal_is_and_how_far_over(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["instructions", "check", "chore", "--json", "--text", "x" * (LIMIT + 119)]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "agent": "chore",
        "source": "the text given",
        "ok": False,
        "bytes": LIMIT + 119,
        "max_bytes": LIMIT,
        "bytes_left": -119,
        "blank": False,
        "problems": [f"{LIMIT + 119} bytes, over {LIMIT}"],
        "warnings": [],
    }


def test_without_text_it_checks_the_file_the_agents_runs_read_now(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No file set and no default there: a run reads none.
    assert main(["instructions", "check", "worker"]) == 0
    assert "(no file: none is set): ok, 0 of" in capsys.readouterr().out
    # A file the key names that is not there refuses every run, and so the check.
    path = configure(canopy_env, None)
    assert main(["instructions", "check", "worker"]) == 1
    assert f"worker instructions ({path}): refused: cannot be read: " in capsys.readouterr().out
    assert not renders(canopy_env)
    path.write_text("\n")
    assert main(["instructions", "check", "worker"]) == 0
    assert "  blank: a run reads no instructions in it.\n" in capsys.readouterr().out
