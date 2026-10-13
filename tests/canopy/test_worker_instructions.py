"""The operator's standing instructions (DESIGN §12): `paths.worker_instructions` is rendered into every worker prompt
but a split's, and a file that cannot be used refuses the dispatch instead of dropping them."""

import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, prompts
from canopy.core.config import load
from tests.canopy.helpers import InlineRunner, in_tick, journal
from tests.canopy.test_prompts import VALUES
from tests.conftest import CanopyEnv, GitPool, user_toml

KEY = "PROJ-1"
FIXUP = "Commit a change that corrects an earlier commit on the branch with `git commit --fixup=<sha>`."
SECTION = "## Standing instructions from the operator\n\n"


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


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


def dispatch(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> tuple[int, list[sqlite3.Row]]:
    """Dispatch an `implement` of PROJ-1 in a tick, and return the exit code and the tick's decisions."""
    tick_id = in_tick(conn, monkeypatch)
    code = main(
        ["dispatch", KEY, "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
        runner=InlineRunner(),
    )
    return code, db.decisions_for_tick(conn, tick_id)


def section_of(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> str:
    run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
    prompt = (canopy_env.state_dir / "runs" / f"{run_id}.prompt").read_text()
    return prompt.split(SECTION, 1)[1].split("\n\nThe operator set these", 1)[0]


def test_the_operators_standing_instructions_reach_the_worker(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    instruct(canopy_env, f"\n{FIXUP}\n\n")
    code, decisions = dispatch(conn, monkeypatch)
    assert code == 0, [dict(d) for d in decisions]
    assert section_of(canopy_env, conn) == FIXUP


def test_without_standing_instructions_the_section_says_none(
    canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, decisions = dispatch(conn, monkeypatch)
    assert code == 0, [dict(d) for d in decisions]
    assert section_of(canopy_env, conn) == "None."


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
    monkeypatch: pytest.MonkeyPatch,
    text: str | bytes | None,
    error: str,
) -> None:
    # The operator set them for every worker; a worker that ran without them would work as if they were never written.
    path = instruct(canopy_env, text if text is not None else "")
    if text is None:
        path.unlink()
    code, decisions = dispatch(conn, monkeypatch)
    assert code == 1
    [decision] = decisions
    assert decision["action"] == "refused:bad_prompt"
    assert error in decision["rationale"]
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize("instructed", [False, True])
def test_an_override_without_the_placeholder_fails_closed_once_instructions_are_set(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    instructed: bool,  # noqa: FBT001  (a parametrized fixture)
) -> None:
    # An override written before the placeholder existed keeps serving an operator who sets no instructions.
    if instructed:
        instruct(canopy_env, FIXUP)
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    (overrides / "worker-implement.md").write_text("Implement {{KEY}} if it carries {{LABELS}}.\n")
    code, decisions = dispatch(conn, monkeypatch)
    if not instructed:
        assert code == 0, [dict(d) for d in decisions]
        return
    assert code == 1
    [decision] = decisions
    assert decision["action"] == "refused:bad_prompt"
    assert "missing required placeholder {{STANDING_INSTRUCTIONS}}" in decision["rationale"]


@pytest.mark.parametrize("kind", ["implement", "fix-ci", "resume"])
def test_every_shipped_private_prompt_carries_the_instructions(canopy_env: CanopyEnv, kind: str) -> None:
    instruct(canopy_env, FIXUP)
    cfg = load(canopy_env.root, canopy_env.user_file)
    text = prompts.render_worker(cfg, kind, {**VALUES, "CONVERSATION": "No messages yet."}, private=True)
    assert f"{SECTION}{FIXUP}\n" in text


def test_a_split_neither_needs_nor_carries_the_instructions(canopy_env: CanopyEnv) -> None:
    # A splitter files child tickets and writes no code, so habits for workers have no place in its prompt, and a file
    # it would not use cannot refuse it either.
    instruct(canopy_env, FIXUP).unlink()
    cfg = load(canopy_env.root, canopy_env.user_file)
    text = prompts.render_worker(cfg, "split", VALUES, required=prompts.REQUIRED_SPLIT)
    assert "Standing instructions" not in text


def test_blank_instructions_read_as_none(canopy_env: CanopyEnv) -> None:
    instruct(canopy_env, " \n\n")
    assert prompts.standing_instructions(load(canopy_env.root, canopy_env.user_file)) == "None."
