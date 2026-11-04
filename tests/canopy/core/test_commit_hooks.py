"""What canopy hands a worker's environment so that git puts its marks on its commits (TRUST_MODEL T5).

That is an entry for git's hooks directory after any the operator's environment holds, the trailers and prefix, and
the checklists its `pre-push` holds a push for, unless there is nothing to add or hold; the prefix names the run's
ticket, and a task, which has none, gets none that names it.
"""

from pathlib import Path
from unittest import mock

import pytest

from canopy.core import commit_hooks
from canopy.core.config import ConfigError, load
from canopy.infra import procs
from tests.conftest import CanopyEnv, executable

TRAILER = "Co-authored-by: canopy worker <noreply@canopy.invalid>"


def test_canopys_entry_comes_after_the_operators_own(tmp_path: Path) -> None:
    inherited = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_KEY_1": "c.d"}
    marks = commit_hooks.Marks((TRAILER, "Co-authored-by: x <y@z>"), "PROJ-1: ")
    real = tmp_path / "pool" / "1" / "api"
    real.mkdir(parents=True)
    (tmp_path / "linked").symlink_to(real)
    # The hook finds its slot by `pwd -P`, so each is resolved, and one no line can hold marks nothing.
    slots = [tmp_path / "linked", Path("/pool/web"), Path("/pool/a\nb")]
    assert commit_hooks.env(Path("/snap"), marks, inherited, slots=slots) == {
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_2": "core.hooksPath",
        "GIT_CONFIG_VALUE_2": "/snap/git-hooks",
        "CANOPY_SLOTS": f"{real.resolve()}\n/pool/web",
        "CANOPY_COMMIT_TRAILERS": f"{TRAILER}\nCo-authored-by: x <y@z>",
        "CANOPY_COMMIT_PREFIX": "PROJ-1: ",
    }


def test_a_count_git_would_refuse_is_replaced() -> None:
    found = commit_hooks.env(Path("/snap"), commit_hooks.Marks((TRAILER,)), {"GIT_CONFIG_COUNT": "many"}, slots=[])
    assert (found["GIT_CONFIG_COUNT"], found["GIT_CONFIG_KEY_0"]) == ("1", "core.hooksPath")
    assert commit_hooks.PREFIX_ENV not in found


def test_with_nothing_to_add_git_is_left_as_it_was() -> None:
    assert commit_hooks.env(Path("/snap"), commit_hooks.NONE, {"GIT_CONFIG_COUNT": "1"}, slots=[Path("/pool")]) == {}
    assert commit_hooks.env(Path("/snap"), commit_hooks.NONE, {}, {}, slots=[]) == {}


def test_a_run_with_a_list_and_no_mark_still_gets_the_hooks(tmp_path: Path) -> None:
    """The hooks' `pre-push` holds a push for the checklist (DESIGN §42), so git is pointed at them with no mark."""
    real = tmp_path / "pool" / "1" / "api"
    real.mkdir(parents=True)
    (tmp_path / "linked").symlink_to(real)
    answers = Path("/state/runs/7.answers/checklists")
    lists = {
        # The hook finds its slot by `pwd -P`, so the slot's path is resolved.
        tmp_path / "linked": answers / "api.md",
        Path("/pool/web"): answers / "web.md",
        # A path no line can hold is held by nothing.
        Path("/pool/a\tb"): answers / "ab.md",
    }
    # With no mark to add, no slot is named for one.
    assert commit_hooks.env(Path("/snap"), commit_hooks.NONE, {}, lists, slots=lists) == {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": "/snap/git-hooks",
        "CANOPY_CHECKLISTS": f"{real.resolve()}\t{answers}/api.md\n/pool/web\t{answers}/web.md",
    }


def test_a_hook_in_a_repository_git_cannot_read_yet_lets_git_go_on(tmp_path: Path) -> None:
    """As `git init` is when a recent git runs `reference-transaction` for the HEAD it writes, before HEAD exists."""
    snapshot = tmp_path / "snapshot"
    (snapshot / commit_hooks.HOOKS_DIR).mkdir(parents=True)
    for rel, data in commit_hooks.files().items():
        executable(snapshot / rel, data.decode())
    new = tmp_path / "new"
    (new / ".git" / "refs").mkdir(parents=True)
    env = {
        **commit_hooks.env(snapshot, commit_hooks.Marks((TRAILER,)), {}, slots=[new]),
        # So git does not look past the new repository for one around it.
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }
    hook = str(snapshot / commit_hooks.HOOKS_DIR / "reference-transaction")
    done = procs.SubprocessRunner().run([hook, "prepared"], cwd=new, env=env, stdin="", timeout=30)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_the_trailers_are_the_prompts_and_none_while_canopys_is_off(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert commit_hooks.marks(cfg, key="PROJ-1", model="p/m", planner_model="p/n") == commit_hooks.Marks(
        (
            "Co-authored-by: p/m (canopy worker) <noreply@canopy.invalid>",
            "Co-authored-by: p/n (canopy planner) <noreply@canopy.invalid>",
        ),
    )
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_trailer": False}})
    assert commit_hooks.marks(load(canopy_env.root, canopy_env.user_file), key="PROJ-1") == commit_hooks.NONE


def test_the_prefix_names_the_runs_ticket_and_a_task_gets_none_that_names_one(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_prefix": "[{key}] "}})
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert commit_hooks.marks(cfg, key="PROJ-1").prefix == "[PROJ-1] "
    assert commit_hooks.marks(cfg, key=None).prefix == ""
    # One that names no ticket is every run's, a task's too.
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_prefix": "agent: "}})
    assert commit_hooks.marks(load(canopy_env.root, canopy_env.user_file), key=None).prefix == "agent: "


@pytest.mark.parametrize(
    "prefix",
    ["`{key}` ", "{ticket}: ", "#{key} ", " {key}: ", "fixup! ", "{key}:\n", "x" * 61],
)
def test_a_prefix_that_would_break_a_subject_or_its_quoting_is_refused(canopy_env: CanopyEnv, prefix: str) -> None:
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_prefix": prefix}})
    with pytest.raises(ConfigError, match="commit_prefix"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_shared_file_cannot_set_the_prefix(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.shared_file, {"trust": {"commit_prefix": "{key}: "}})
    with pytest.raises(ConfigError, match="commit_prefix"):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    ("printed", "old"),
    [
        ("git version 2.30.9\n", "2.30"),
        ("git version 1.8.3.1\n", "1.8"),
        ("git version 2.31.0\n", None),
        ("git version 2.39.3 (Apple Git-145)\n", None),
        ("git version 2.45.1.windows.1\n", None),
        # A git that does not say its version is no finding: its runs' own git steps say what is wrong.
        ("not git\n", None),
    ],
)
def test_a_git_older_than_the_hooks_need_is_named(canopy_env: CanopyEnv, printed: str, old: str | None) -> None:
    runner = mock.create_autospec(procs.Runner, instance=True)
    runner.run.return_value = procs.Result(("git", "--version"), 0, printed, "")
    found = commit_hooks.git_too_old(load(canopy_env.root, canopy_env.user_file), runner)
    if old is None:
        assert found is None
    else:
        assert found == (
            f"git {old} on PATH is older than 2.31, which canopy's commit hooks need: workers' commits get no trailer "
            "or prefix, and each run's note names them; install git 2.31 or later"
        )


def test_a_git_that_cannot_run_is_no_finding(canopy_env: CanopyEnv) -> None:
    runner = mock.create_autospec(procs.Runner, instance=True)
    runner.run.side_effect = procs.CommandNotFoundError("git")
    assert commit_hooks.git_too_old(load(canopy_env.root, canopy_env.user_file), runner) is None


def test_with_no_marks_to_add_the_version_is_not_read(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_trailer": False}})
    runner = mock.create_autospec(procs.Runner, instance=True)
    assert commit_hooks.git_too_old(load(canopy_env.root, canopy_env.user_file), runner) is None
    runner.run.assert_not_called()


A = "a" * 40
B = "b" * 40
C = "c" * 64


def test_each_showing_of_the_list_is_paired_with_the_next_push_it_let_through(tmp_path: Path) -> None:
    """A list shown again before a push keeps the first commit: all that follows it came after the list."""
    notes = tmp_path / commit_hooks.PUSHES_LOG
    notes.write_text(f"shown 3 {A}\nsent 3 {B}\nsent 3 {A}\nshown 3 {B}\nshown 3 {A}\nsent 3 {C}\nshown 3 {C}\n")
    assert commit_hooks.pushes_after(tmp_path, "3") == [(A, B), (B, C), (C, None)]
    # Taken: a later run in the slot starts with none.
    assert not notes.exists()
    assert commit_hooks.pushes_after(tmp_path, "3") == []


def test_a_note_that_is_not_the_runs_or_not_a_commit_counts_for_nothing(tmp_path: Path) -> None:
    """The notes are in a directory the run may write, so what is not the hook's shape is skipped."""
    (tmp_path / commit_hooks.PUSHES_LOG).write_text(
        f"shown 4 {A}\nshown task-3 {A}\nshown 3 HEAD\nshown 3 {A[:12]}\nheld 3 {A}\nshown 3 {A} more\n"
        f"shown 3\nsent 3 {B.upper()}\n\0\nshown 3 {B}\nsent 30 {A}\nsent 3 {C}\n",
    )
    assert commit_hooks.pushes_after(tmp_path, "3") == [(B, C)]


def test_notes_past_the_bound_or_not_in_a_regular_file_are_not_read(tmp_path: Path) -> None:
    notes = tmp_path / commit_hooks.PUSHES_LOG
    line = f"shown 3 {A}\n"
    padding = "x" * (commit_hooks.MAX_PUSHES_BYTES - len(line) - 1) + "\n"
    # The line cut by the bound is dropped whole, not read in part.
    notes.write_text(f"{line}{padding}sent 3 {B}\n")
    assert commit_hooks.pushes_after(tmp_path, "3") == [(A, None)]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text(f"shown 3 {A}\nsent 3 {B}\n")
    notes.symlink_to(elsewhere)
    assert commit_hooks.pushes_after(tmp_path, "3") == []
    # The link is taken, not what it names.
    assert not notes.is_symlink()
    assert elsewhere.exists()
