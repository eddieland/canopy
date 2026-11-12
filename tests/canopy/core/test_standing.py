"""The operator's standing instructions files as the settings page reads and saves them (DESIGN §12, TRUST_MODEL T8).

Only the text of a file the config names is written, never which file; a save is the operator's alone, and refuses a
stale read, a link, and text past the bound a run takes, keeping the file as it was beside it.
"""

import hashlib
import os
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import conversation, prompts, standing
from canopy.core.config import Config
from canopy.core.context import Context

RULES = "Commit review fixes as new commits.\n"


def with_paths(ctx: Context, **paths: Path) -> Config:
    """`ctx`'s config with the `paths.<agent>_instructions` keys given."""
    update = {f"{agent}_instructions": path for agent, path in paths.items()}
    return ctx.config.model_copy(update={"paths": ctx.config.paths.model_copy(update=update)})


def sha(text: str) -> str:
    """The hash a read of a file holding `text` gives."""
    return hashlib.sha256(text.encode()).hexdigest()


def test_every_agent_is_read_in_order_and_one_with_no_file_set_says_so(ctx: Context, tmp_path: Path) -> None:
    worker = tmp_path / "worker.md"
    worker.write_text(RULES)
    found = standing.read_all(with_paths(ctx, worker=worker, overseer=tmp_path / "gone.md"))

    assert [i.agent for i in found] == ["worker", "overseer", "reviewer", "chore"]
    assert found[0] == standing.Instructions("worker", "paths.worker_instructions", worker, RULES, sha(RULES), None)
    # A path set to no file refuses every run of its agent, which the page says.
    assert found[1].text is None
    assert found[1].sha256 is None
    assert (found[1].problem or "").startswith("missing: ")
    assert found[1].missing
    assert found[2] == standing.Instructions("reviewer", "paths.reviewer_instructions", None, None, None, None)


def test_a_file_a_run_would_refuse_is_shown_with_why(ctx: Context, tmp_path: Path) -> None:
    long, binary = tmp_path / "long.md", tmp_path / "binary.md"
    long.write_text("x" * (prompts.MAX_STANDING_BYTES + 1))
    binary.write_bytes(b"\xff\xfe")
    found = standing.read_all(with_paths(ctx, worker=long, chore=binary))

    # Shown, so the operator can trim it from the page.
    assert found[0].text == "x" * (prompts.MAX_STANDING_BYTES + 1)
    assert (found[0].problem or "").startswith(f"{prompts.MAX_STANDING_BYTES + 1} bytes, over ")
    assert found[3].text is None
    assert (found[3].problem or "").startswith("not UTF-8")


def test_a_save_replaces_the_text_a_run_reads_and_keeps_the_old_beside_it(ctx: Context, tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    path = notes / "worker.md"
    path.write_text(RULES)
    path.chmod(0o640)
    cfg = with_paths(ctx, worker=path)

    saved = standing.save(cfg, ctx.ws.state_dir, "worker", "Run the linters first.", read_sha256=sha(RULES))

    # A line is ended, as an editor would.
    assert path.read_text() == "Run the linters first.\n"
    assert saved.sha256 == sha("Run the linters first.\n")
    assert saved.problem is None
    assert path.with_name("worker.md.bak").read_text() == RULES
    # Both keep the file's mode, and no temporary file is left.
    assert path.stat().st_mode & 0o777 == 0o640
    assert path.with_name("worker.md.bak").stat().st_mode & 0o777 == 0o640
    assert sorted(p.name for p in notes.iterdir()) == ["worker.md", "worker.md.bak"]
    assert prompts.standing_instructions(cfg) == "Run the linters first."


def test_a_save_makes_a_missing_file_the_config_names_for_the_operator_alone(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "reviewer.md"
    saved = standing.save(with_paths(ctx, reviewer=path), ctx.ws.state_dir, "reviewer", RULES, read_sha256=None)

    assert path.read_text() == RULES
    assert path.stat().st_mode & 0o777 == 0o600
    assert saved.sha256 == sha(RULES)
    assert not path.with_name("reviewer.md.bak").exists()


def test_an_empty_save_leaves_a_run_none(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "worker.md"
    path.write_text(RULES)
    cfg = with_paths(ctx, worker=path)

    standing.save(cfg, ctx.ws.state_dir, "worker", "", read_sha256=sha(RULES))

    assert path.read_text() == ""
    assert prompts.standing_instructions(cfg) == "None."


@pytest.mark.parametrize(
    ("given", "guard"),
    [
        pytest.param(sha("an older version\n"), "stale", id="changed since read"),
        pytest.param(None, "stale", id="read as missing, there now"),
    ],
)
def test_a_save_over_a_file_other_than_the_one_read_is_refused(
    ctx: Context,
    tmp_path: Path,
    given: str | None,
    guard: str,
) -> None:
    path = tmp_path / "worker.md"
    path.write_text(RULES)

    with pytest.raises(conversation.Refused) as refused:
        standing.save(with_paths(ctx, worker=path), ctx.ws.state_dir, "worker", "new", read_sha256=given)

    assert refused.value.guard == guard
    assert path.read_text() == RULES
    assert not path.with_name("worker.md.bak").exists()


def test_a_save_the_config_names_no_file_for_is_refused(ctx: Context) -> None:
    with pytest.raises(conversation.Refused) as refused:
        standing.save(ctx.config, ctx.ws.state_dir, "chore", RULES, read_sha256=None)

    assert refused.value.guard == "not_set"
    assert "paths.chore_instructions" in refused.value.reason


def test_a_save_past_the_bound_a_run_takes_is_refused(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "worker.md"
    # Counted in bytes, as a run counts them: each of these is three.
    text = "…" * (prompts.MAX_STANDING_BYTES // 3 + 1)

    with pytest.raises(conversation.Refused) as refused:
        standing.save(with_paths(ctx, worker=path), ctx.ws.state_dir, "worker", text, read_sha256=None)

    assert refused.value.guard == "too_large"
    assert not path.exists()


def test_a_save_through_a_link_is_refused_and_writes_nothing(ctx: Context, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.md"
    target.write_text(RULES)
    path = tmp_path / "worker.md"
    path.symlink_to(target)

    with pytest.raises(conversation.Refused) as refused:
        standing.save(with_paths(ctx, worker=path), ctx.ws.state_dir, "worker", "new", read_sha256=sha(RULES))

    assert refused.value.guard == "unsafe_file"
    assert target.read_text() == RULES
    assert path.is_symlink()
    assert (standing.read(with_paths(ctx, worker=path), "worker").problem or "").startswith(f"{path} is a symlink")


def test_a_save_in_a_directory_others_may_write_in_is_refused(ctx: Context, tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    path = shared / "worker.md"

    with pytest.raises(conversation.Refused) as refused:
        standing.save(with_paths(ctx, worker=path), ctx.ws.state_dir, "worker", RULES, read_sha256=None)

    assert refused.value.guard == "unsafe_file"
    assert not path.exists()


def test_a_save_inside_a_run_is_refused(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "overseer.md"

    with (
        mock.patch.dict(os.environ, {conversation.RUN_ID_ENV: "7"}),
        pytest.raises(conversation.Refused) as refused,
    ):
        standing.save(with_paths(ctx, overseer=path), ctx.ws.state_dir, "overseer", RULES, read_sha256=None)

    assert refused.value.guard == "inside_run"
    assert not path.exists()
