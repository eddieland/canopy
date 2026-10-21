"""The operator's standing instructions (DESIGN §12): `paths.worker_instructions` is rendered into every worker prompt,
and a file that cannot be used refuses the dispatch instead of dropping them."""

import sqlite3
from pathlib import Path

import pytest

from canopy.core import prompts
from canopy.core.config import load
from tests.canopy.helpers import IMPLEMENT, PROMPT_VALUES, dispatch_in_tick
from tests.conftest import CanopyEnv, GitPool, user_toml

FIXUP = "Commit a change that corrects an earlier commit on the branch with `git commit --fixup=<sha>`."
SECTION = "## Standing instructions from the operator\n\n"


def instruct(canopy_env: CanopyEnv, text: str | bytes) -> Path:
    """Write the operator's standing instructions and point `paths.worker_instructions` at them."""
    path = canopy_env.user_file.parent / "worker-instructions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)
    canopy_env.write_user(user_toml() + f"worker_instructions = '{path}'\n")
    return path


def prompt_of(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> str:
    run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
    return (canopy_env.state_dir / "runs" / f"{run_id}.prompt").read_text()


def section_of(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> str:
    return prompt_of(canopy_env, conn).split(SECTION, 1)[1].split("\n\nThe operator set these", 1)[0]


def test_the_operators_standing_instructions_reach_the_worker(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    instruct(canopy_env, f"\n{FIXUP}\n\n")
    code, decisions = dispatch_in_tick(conn, *IMPLEMENT)
    assert code == 0, decisions
    assert section_of(canopy_env, conn) == FIXUP


def test_without_standing_instructions_there_is_no_section(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection
) -> None:
    code, decisions = dispatch_in_tick(conn, *IMPLEMENT)
    assert code == 0, decisions
    prompt = prompt_of(canopy_env, conn)
    assert SECTION not in prompt
    # With no notice in force either, the section before both runs straight into the obligations.
    assert "data\nabout the task.\n\n## Obligations\n" in prompt


def test_an_override_with_the_old_placeholder_gets_the_text_alone(canopy_env: CanopyEnv) -> None:
    # One written before `{{STANDING_SECTION}}` holds its own heading and framing around `{{STANDING_INSTRUCTIONS}}`.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    (overrides / "worker-implement.md").write_text(
        "Implement {{KEY}} if it carries {{LABELS}}.\n{{STANDING_INSTRUCTIONS}}\n"
    )
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert prompts.render_worker(cfg, "implement", PROMPT_VALUES).endswith("\nNone.\n")
    instruct(canopy_env, FIXUP)
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert prompts.render_worker(cfg, "implement", PROMPT_VALUES).endswith(f"\n{FIXUP}\n")


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (None, "cannot read worker instructions"),
        (b"\xff\xfe not UTF-8\n", "cannot read worker instructions"),
        ("x" * (prompts.MAX_STANDING_BYTES + 1), f"over {prompts.MAX_STANDING_BYTES}"),
    ],
    ids=["missing", "not-utf8", "too-large"],
)
def test_instructions_that_cannot_be_used_refuse_the_dispatch(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    text: str | bytes | None,
    error: str,
) -> None:
    # The operator set them for every worker; a worker that ran without them would work as if they were never written.
    path = instruct(canopy_env, text if text is not None else "")
    if text is None:
        path.unlink()
    code, decisions = dispatch_in_tick(conn, *IMPLEMENT)
    assert code == 1
    [(action, rationale)] = decisions
    assert action == "refused:bad_prompt"
    assert error in rationale
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize("instructed", [False, True])
def test_an_override_without_the_placeholder_fails_closed_once_instructions_are_set(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    instructed: bool,  # noqa: FBT001  (a parametrized fixture)
) -> None:
    # An override written before the placeholder existed keeps serving an operator who sets no instructions.
    if instructed:
        instruct(canopy_env, FIXUP)
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    (overrides / "worker-implement.md").write_text("Implement {{KEY}} if it carries {{LABELS}}.\n{{DRAFTS}}\n")
    code, decisions = dispatch_in_tick(conn, *IMPLEMENT)
    if not instructed:
        assert code == 0, decisions
        return
    assert code == 1
    [(action, rationale)] = decisions
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{STANDING_SECTION}} or {{STANDING_INSTRUCTIONS}}" in rationale


@pytest.mark.parametrize("kind", ["implement", "resume"])
def test_every_shipped_private_prompt_carries_the_instructions(canopy_env: CanopyEnv, kind: str) -> None:
    instruct(canopy_env, FIXUP)
    cfg = load(canopy_env.root, canopy_env.user_file)
    text = prompts.render_worker(cfg, kind, {**PROMPT_VALUES, "CONVERSATION": "No messages yet."}, private=True)
    assert f"{SECTION}{FIXUP}\n" in text


def test_blank_instructions_read_as_none(canopy_env: CanopyEnv) -> None:
    instruct(canopy_env, " \n\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert prompts.standing_instructions(cfg) == "None."
    assert SECTION not in prompts.render_worker(cfg, "implement", PROMPT_VALUES)
