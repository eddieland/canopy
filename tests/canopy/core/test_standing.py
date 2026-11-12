"""The operator's standing instructions files as the settings' instructions page reads and changes them (DESIGN §12).

An agent's file is the one its key names, else its default in `paths.instructions`, which a run reads only while it is
there. The page writes text, makes and deletes a default, never a file a key names, and never chooses which file
(TRUST_MODEL T8); each change keeps the file as it was among the agent's versions, the newest ten.
"""

import hashlib
import os
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import conversation, prompts, standing
from canopy.core.config import Config, StandingAgent
from canopy.core.context import Context

RULES = "Commit review fixes as new commits.\n"


def with_paths(ctx: Context, **paths: Path) -> Config:
    """`ctx`'s config with the `paths.<agent>_instructions` keys given, and `instructions` for the default directory."""
    update = {(k if k == "instructions" else f"{k}_instructions"): v for k, v in paths.items()}
    return ctx.config.model_copy(update={"paths": ctx.config.paths.model_copy(update=update)})


def sha(text: str) -> str:
    """The hash a read of a file holding `text` gives."""
    return hashlib.sha256(text.encode()).hexdigest()


def kept(ctx: Context, agent: StandingAgent) -> list[tuple[str, str | None]]:
    """Each kept version of `agent`'s file, newest first, as what made it and its text."""
    return [(v.kind, v.text) for v in standing.versions(ctx.ws.state_dir, agent)]


def test_an_agent_reads_the_file_its_key_names_else_its_default_while_there(ctx: Context, tmp_path: Path) -> None:
    worker = tmp_path / "worker.md"
    worker.write_text(RULES)
    defaults = tmp_path / "instructions"
    defaults.mkdir()
    (defaults / "reviewer.md").write_text("Flag a change with no test.\n")
    cfg = with_paths(ctx, worker=worker, overseer=tmp_path / "gone.md", instructions=defaults)

    found = standing.read_all(cfg, ctx.ws.state_dir)

    assert [(i.agent, i.source, i.path) for i in found] == [
        ("worker", "config", worker),
        ("overseer", "config", tmp_path / "gone.md"),
        ("reviewer", "default", defaults / "reviewer.md"),
        ("chore", "default", defaults / "chore.md"),
    ]
    assert (found[0].text, found[0].sha256, found[0].problem, found[0].missing) == (RULES, sha(RULES), None, False)
    # A file the key names that is not there refuses every run; a default not there is no instructions at all.
    assert found[1].missing
    assert (found[1].problem or "").startswith("missing: ")
    assert found[3].missing
    assert found[3].problem is None
    assert prompts.reviewer_instructions(cfg) == "Flag a change with no test."
    assert prompts.chore_instructions(cfg) == "None."
    with pytest.raises(prompts.PromptError):
        prompts.overseer_instructions(cfg)


def test_the_default_directory_is_instructions_in_the_user_config_directory(ctx: Context) -> None:
    assert ctx.config.paths.instructions.name == "instructions"
    assert ctx.config.paths.instructions_file("worker") == ctx.config.paths.instructions / "worker.md"


def test_a_file_a_run_would_refuse_is_shown_with_why(ctx: Context, tmp_path: Path) -> None:
    long, binary = tmp_path / "long.md", tmp_path / "binary.md"
    long.write_text("x" * (prompts.MAX_STANDING_BYTES + 1))
    binary.write_bytes(b"\xff\xfe")
    found = standing.read_all(with_paths(ctx, worker=long, chore=binary), ctx.ws.state_dir)

    # Shown, so the operator can trim it from the page.
    assert found[0].text == "x" * (prompts.MAX_STANDING_BYTES + 1)
    assert (found[0].problem or "").startswith(f"{prompts.MAX_STANDING_BYTES + 1} bytes, over ")
    assert found[3].text is None
    assert (found[3].problem or "").startswith("not UTF-8")


def test_a_save_replaces_the_text_a_run_reads_and_keeps_the_old_as_a_version(ctx: Context, tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    path = notes / "worker.md"
    path.write_text(RULES)
    path.chmod(0o640)
    cfg = with_paths(ctx, worker=path)

    saved = standing.save(cfg, ctx.ws.state_dir, "worker", "Run the linters first.", read_sha256=sha(RULES))

    # A line is ended, as an editor would.
    assert path.read_text() == "Run the linters first.\n"
    assert (saved.sha256, saved.problem, saved.versions) == (sha("Run the linters first.\n"), None, 1)
    assert prompts.standing_instructions(cfg) == "Run the linters first."
    # The file keeps its mode, and nothing else is left beside it: the old text is a version, in the state directory.
    assert path.stat().st_mode & 0o777 == 0o640
    assert sorted(p.name for p in notes.iterdir()) == ["worker.md"]
    assert kept(ctx, "worker") == [("edit", RULES)]
    versions = ctx.ws.state_dir / standing.VERSIONS_DIR
    assert versions.stat().st_mode & 0o777 == 0o700
    assert all(v.stat().st_mode & 0o777 == 0o600 for v in (versions / "worker").iterdir())


def test_a_save_makes_an_agents_default_and_its_directory_for_the_operator_alone(ctx: Context, tmp_path: Path) -> None:
    defaults = tmp_path / "instructions"
    cfg = with_paths(ctx, instructions=defaults)
    assert prompts.chore_instructions(cfg) == "None."

    saved = standing.save(cfg, ctx.ws.state_dir, "chore", "Name a CI job by its workflow file.", read_sha256=None)

    assert defaults.stat().st_mode & 0o777 == 0o700
    assert (defaults / "chore.md").stat().st_mode & 0o777 == 0o600
    assert (saved.source, saved.missing, saved.versions) == ("default", False, 0)
    assert prompts.chore_instructions(cfg) == "Name a CI job by its workflow file."


def test_a_save_makes_a_missing_file_a_key_names(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "reviewer.md"
    saved = standing.save(with_paths(ctx, reviewer=path), ctx.ws.state_dir, "reviewer", RULES, read_sha256=None)

    assert path.read_text() == RULES
    assert path.stat().st_mode & 0o777 == 0o600
    assert (saved.sha256, saved.problem) == (sha(RULES), None)


def test_a_delete_removes_a_default_so_its_runs_read_none_and_keeps_it(ctx: Context, tmp_path: Path) -> None:
    defaults = tmp_path / "instructions"
    defaults.mkdir(mode=0o700)
    (defaults / "overseer.md").write_text(RULES)
    cfg = with_paths(ctx, instructions=defaults)

    gone = standing.delete(cfg, ctx.ws.state_dir, "overseer", read_sha256=sha(RULES))

    assert not (defaults / "overseer.md").exists()
    assert (gone.missing, gone.problem, gone.versions) == (True, None, 1)
    assert prompts.overseer_instructions(cfg) == "None."
    assert kept(ctx, "overseer") == [("delete", RULES)]


def test_a_file_a_key_names_is_never_deleted(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "worker.md"
    path.write_text(RULES)

    with pytest.raises(conversation.Refused) as refused:
        standing.delete(with_paths(ctx, worker=path), ctx.ws.state_dir, "worker", read_sha256=sha(RULES))

    assert refused.value.guard == "configured"
    assert "paths.worker_instructions" in refused.value.reason
    assert path.read_text() == RULES


def test_the_newest_ten_versions_are_kept_newest_first(ctx: Context, tmp_path: Path) -> None:
    cfg = with_paths(ctx, instructions=tmp_path / "instructions")
    read: str | None = None
    for n in range(12):
        read = standing.save(cfg, ctx.ws.state_dir, "worker", f"Version {n}.", read_sha256=read).sha256

    found = kept(ctx, "worker")
    assert len(found) == standing.KEEP_VERSIONS
    # Each is the file before a save: the last save went over version 10, the oldest kept was over version 1.
    assert found[0] == ("edit", "Version 10.\n")
    assert found[-1] == ("edit", "Version 1.\n")
    assert standing.read(cfg, ctx.ws.state_dir, "worker").versions == standing.KEEP_VERSIONS


@pytest.mark.parametrize(
    "given",
    [pytest.param(sha("an older version\n"), id="changed since read"), pytest.param(None, id="read as missing")],
)
def test_a_change_to_a_file_other_than_the_one_read_is_refused(ctx: Context, tmp_path: Path, given: str | None) -> None:
    defaults = tmp_path / "instructions"
    defaults.mkdir(mode=0o700)
    path = defaults / "worker.md"
    path.write_text(RULES)
    cfg = with_paths(ctx, instructions=defaults)

    with pytest.raises(conversation.Refused) as saving:
        standing.save(cfg, ctx.ws.state_dir, "worker", "new", read_sha256=given)
    with pytest.raises(conversation.Refused) as deleting:
        standing.delete(cfg, ctx.ws.state_dir, "worker", read_sha256=given or sha("never read\n"))

    assert (saving.value.guard, deleting.value.guard) == ("stale", "stale")
    assert path.read_text() == RULES
    assert kept(ctx, "worker") == []


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
    cfg = with_paths(ctx, worker=path)

    with pytest.raises(conversation.Refused) as refused:
        standing.save(cfg, ctx.ws.state_dir, "worker", "new", read_sha256=sha(RULES))

    assert refused.value.guard == "unsafe_file"
    assert target.read_text() == RULES
    assert path.is_symlink()
    assert (standing.read(cfg, ctx.ws.state_dir, "worker").problem or "").startswith(f"{path} is a symlink")


@pytest.mark.parametrize("mode", [pytest.param(0o777, id="others"), pytest.param(0o770, id="its group")])
def test_a_save_in_a_directory_others_may_write_in_is_refused(ctx: Context, tmp_path: Path, mode: int) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(mode)
    path = shared / "worker.md"

    with pytest.raises(conversation.Refused) as refused:
        standing.save(with_paths(ctx, worker=path), ctx.ws.state_dir, "worker", RULES, read_sha256=None)

    assert refused.value.guard == "unsafe_file"
    assert not path.exists()


def test_a_change_inside_a_run_is_refused(ctx: Context, tmp_path: Path) -> None:
    defaults = tmp_path / "instructions"
    defaults.mkdir(mode=0o700)
    (defaults / "chore.md").write_text(RULES)
    cfg = with_paths(ctx, instructions=defaults)

    with mock.patch.dict(os.environ, {conversation.RUN_ID_ENV: "7"}):
        with pytest.raises(conversation.Refused) as saving:
            standing.save(cfg, ctx.ws.state_dir, "overseer", RULES, read_sha256=None)
        with pytest.raises(conversation.Refused) as deleting:
            standing.delete(cfg, ctx.ws.state_dir, "chore", read_sha256=sha(RULES))

    assert (saving.value.guard, deleting.value.guard) == ("inside_run", "inside_run")
    assert not (defaults / "overseer.md").exists()
    assert (defaults / "chore.md").read_text() == RULES
