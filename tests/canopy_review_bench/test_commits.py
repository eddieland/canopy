"""Building a case's commits in the source clone: a replay on its history, an undone fix with none, and overlays."""

from pathlib import Path
from typing import Final

import pytest
from canopy_review_bench import bench, commits
from canopy_review_bench.bench import BenchError, Case, Side, Spot

from tests.canopy_review_bench.helpers import Source, source_repo
from tests.conftest import git

TITLE: Final = "Wait between attempts, a little"


def replay(source: Source, **keys: object) -> Case:
    """Return a replay case of the source's PR."""
    return Case.model_validate(
        {
            "name": "retry-delay",
            "kind": "bug",
            "title": TITLE,
            "replay": {"base": source.base, "head": source.head},
            "lines": ["src/retry.py:11"],
            **keys,
        },
    )


def undo(source: Source, paths: tuple[str, ...] = ("src",)) -> Case:
    """Return an `undo_fix` case of the source's fix."""
    return Case.model_validate(
        {
            "name": "zero-attempts",
            "kind": "bug",
            "title": TITLE,
            "undo_fix": {"fix": source.fix, "paths": paths},
        },
    )


def test_a_replay_is_the_prs_change_as_one_commit_on_its_base(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    built = commits.build(source.path, replay(source), commits.NO_OVERLAY)
    assert built.base == source.base
    assert git("rev-parse", f"{built.head}^", cwd=source.path) == source.base
    assert git("rev-parse", f"{built.head}^{{tree}}", cwd=source.path) == git(
        "rev-parse",
        f"{source.head}^{{tree}}",
        cwd=source.path,
    )
    assert git("log", "-1", "--format=%s", built.head, cwd=source.path) == TITLE
    assert built.spots == (Spot("src/retry.py", 11, 11, Side.HEAD),)
    assert "src/retry.py" in built.stat


def test_building_changes_no_branch_or_index_of_the_source(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    before = git("status", "--porcelain", cwd=source.path), git("for-each-ref", cwd=source.path)
    commits.build(source.path, replay(source), commits.NO_OVERLAY)
    commits.build(source.path, undo(source), commits.NO_OVERLAY)
    assert (git("status", "--porcelain", cwd=source.path), git("for-each-ref", cwd=source.path)) == before


def test_an_overlay_is_in_both_trees_and_not_in_the_diff(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    (tmp_path / "overlay" / ".reviewbot").mkdir(parents=True)
    (tmp_path / "overlay" / ".reviewbot" / "rules.md").write_text("Flag retries without a bound.\n")
    overlay = commits.read_overlay(tmp_path / "overlay")
    built = commits.build(source.path, replay(source), overlay)
    for commit in (built.base, built.head):
        assert git("show", f"{commit}:.reviewbot/rules.md", cwd=source.path) == "Flag retries without a bound."
    assert git("rev-parse", f"{built.base}^", cwd=source.path) == source.base
    assert git("diff", "--name-only", built.base, built.head, cwd=source.path) == "src/retry.py"


def test_an_undone_fix_has_no_history_and_brings_the_bug_back(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    built = commits.build(source.path, undo(source), commits.NO_OVERLAY)
    assert git("rev-list", "--count", built.base, cwd=source.path) == "1"
    assert git("log", "-1", "--format=%s", built.base, cwd=source.path) == commits.BASE_MESSAGE
    assert git("show", f"{built.head}:src/retry.py", cwd=source.path) == git(
        "show",
        f"{source.head}:src/retry.py",
        cwd=source.path,
    )
    # Only `paths` is undone, so the fix's test stays and the PR does not delete what names the bug.
    assert git("diff", "--name-only", built.base, built.head, cwd=source.path) == "src/retry.py"
    # The guard was lines 5 and 6: deleted, so the head marks the line before them and the base the lines themselves.
    assert built.spots == (Spot("src/retry.py", 4, 4, Side.HEAD), Spot("src/retry.py", 5, 6, Side.BASE))


def test_stripped_paths_are_in_neither_tree_and_not_in_the_diff(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    overlay = commits.Overlay({}, (".github/CODEOWNERS", ".github/workflows"))
    for case in (replay(source), undo(source, paths=())):
        built = commits.build(source.path, case, overlay)
        for commit in (built.base, built.head):
            assert ".github" not in git("ls-tree", "--name-only", commit, cwd=source.path).splitlines()
        assert "src/retry.py" in git("diff", "--name-only", built.base, built.head, cwd=source.path)
        assert ".github" not in git("diff", "--name-only", built.base, built.head, cwd=source.path)
    # The replay's base is a commit on the original, so the stripped files are only gone from the branch's tip.
    assert git("rev-parse", f"{commits.build(source.path, replay(source), overlay).base}^", cwd=source.path) == (
        source.base
    )
    assert overlay.digest != commits.NO_OVERLAY.digest


def test_an_undone_fix_leaves_its_part_of_a_stripped_path_alone(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    built = commits.build(source.path, undo(source, paths=()), commits.Overlay({}, ("tests",)))
    assert git("diff", "--name-only", built.base, built.head, cwd=source.path) == "src/retry.py"


def test_an_undone_fix_with_no_paths_undoes_all_of_it(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    built = commits.build(source.path, undo(source, paths=()), commits.NO_OVERLAY)
    changed = git("diff", "--name-only", built.base, built.head, cwd=source.path).splitlines()
    assert changed == ["src/retry.py", "tests/test_retry.py"]


def test_a_case_whose_commits_are_not_in_the_source_is_refused(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    case = replay(source, replay={"base": source.base, "head": "c" * 40})
    with pytest.raises(BenchError, match=f"{'c' * 40} is not a commit in .*; fetch it first"):
        commits.build(source.path, case, commits.NO_OVERLAY)


def test_undoing_a_root_commit_or_nothing_is_refused(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    root = undo(source).model_copy(update={"undo_fix": bench.UndoFix(fix=source.base)})
    with pytest.raises(BenchError, match="has no parent, so it cannot be undone"):
        commits.build(source.path, root, commits.NO_OVERLAY)
    with pytest.raises(BenchError, match="its PR changes nothing"):
        commits.build(source.path, undo(source, paths=("docs",)), commits.NO_OVERLAY)


def test_an_overlay_names_what_it_holds_and_refuses_a_link(tmp_path: Path) -> None:
    (tmp_path / "overlay").mkdir()
    (tmp_path / "overlay" / "rules.md").write_text("one\n")
    first = commits.read_overlay(tmp_path / "overlay").digest
    (tmp_path / "overlay" / "rules.md").write_text("two\n")
    assert commits.read_overlay(tmp_path / "overlay").digest != first
    (tmp_path / "overlay" / "link.md").symlink_to(tmp_path / "overlay" / "rules.md")
    with pytest.raises(BenchError, match="is a link"):
        commits.read_overlay(tmp_path / "overlay")
