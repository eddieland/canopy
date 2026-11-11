"""The outline of a repository's code (DESIGN §46, ROADMAP M70 stage 1): its tree, opened where the work is.

The renderer is given a tree's paths and what the work is about, and reads nothing itself; `listed` and `changed` read
git's objects, here a repository made by hand.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.core import code_outline
from canopy.core.code_outline import About, Listing
from canopy.infra import procs
from tests.conftest import HERMETIC_GIT, git

#: A repository's tree, written by hand: a service with two packages, their tests, and some docs.
TREE = Listing(
    (
        "README.md",
        "pyproject.toml",
        "docs/billing.md",
        "docs/guide/install.md",
        "docs/guide/upgrade.md",
        "services/billing/__init__.py",
        "services/billing/invoices/__init__.py",
        "services/billing/invoices/render.py",
        "services/billing/invoices/totals.py",
        "services/billing/ledger.py",
        "services/shipping/__init__.py",
        "services/shipping/labels.py",
        "services/shipping/rates/tables.py",
        "tests/billing/test_invoices.py",
        "tests/shipping/test_labels.py",
    ),
)


def lines(outline: str | None) -> list[str]:
    """The tree's own lines of `outline`, each without its quote mark."""
    assert outline is not None
    return [line.removeprefix("> ") for line in outline.splitlines() if line.startswith("> ")]


def test_the_outline_of_a_tree_opened_by_a_tickets_words(markdown_snapshot: SnapshotAssertion) -> None:
    about = About(words=code_outline.words("Invoice totals round the wrong way\n\nSee `InvoiceRenderer`."))

    assert code_outline.render(TREE, about, bound=330) == markdown_snapshot


def test_a_tickets_words_open_the_directory_they_name_before_any_other() -> None:
    about = About(words=code_outline.words("Shipping labels print the wrong rate"))

    shown = lines(code_outline.render(TREE, about, bound=300))

    # The directory is open to its files, and the one beside it is a name and a count.
    assert "    labels.py" in shown
    assert "  billing/ (5 files)" in shown


def test_text_is_split_as_identifiers_are() -> None:
    found = code_outline.words("Fix `InvoiceRenderer.render_totals` in HTTPServer v2: the 404s, and the desks")

    # Lowercased, a plural made its singular, the short and the common left out, and no number.
    assert found == {"fix", "invoice", "renderer", "render", "total", "http", "server", "desk"}


def test_a_tree_with_no_words_for_it_is_opened_by_size_outermost_first() -> None:
    shown = lines(code_outline.render(TREE, About(), bound=250))

    # Every top directory is expanded before any below it, and one still closed says how many files it holds.
    assert shown == [
        "docs/",
        "  guide/",
        "    install.md",
        "    upgrade.md",
        "  billing.md",
        "services/",
        "  billing/ (5 files)",
        "  shipping/ (3 files)",
        "tests/",
        "  billing/ (1 file)",
        "  shipping/ (1 file)",
        "README.md",
        "pyproject.toml",
    ]
    # Words that name no path leave the tree opened the same way.
    assert lines(code_outline.render(TREE, About(words=frozenset({"zebra"})), bound=250)) == shown


def test_the_bound_is_kept_and_the_outline_counts_the_files_it_does_not_name() -> None:
    about = About(words=frozenset({"invoice"}))

    outline = code_outline.render(TREE, about, bound=300)

    assert outline is not None
    assert len(outline) <= 300
    named = [line for line in lines(outline) if not line.endswith(("/", "files)", "file)")) and "..." not in line]
    assert outline.splitlines()[-1] == f"15 files in all, {15 - len(named)} not listed by name."
    assert 0 < len(named) < 15


def test_a_branchs_changed_paths_open_their_directories_whatever_the_words_say() -> None:
    about = About(words=frozenset({"invoice"}), changed=frozenset({"docs/guide/upgrade.md"}))

    shown = lines(code_outline.render(TREE, about, bound=250))

    assert shown[:4] == ["docs/", "  guide/", "    install.md", "    upgrade.md"]
    assert "  billing/ (5 files)" in shown


def test_a_large_directory_names_the_files_the_work_is_about_and_counts_the_rest() -> None:
    files = [f"src/module_{n:03}.py" for n in range(100)]
    about = About(changed=frozenset({"src/module_077.py"}))

    shown = lines(code_outline.render(Listing(tuple(files)), about, bound=5000))

    assert "  module_077.py" in shown
    assert shown[-1] == "  ... 60 files more"
    assert len(shown) == 1 + code_outline.MAX_FILES_SHOWN + 1


@pytest.mark.parametrize(
    "path",
    [
        "docs/ignore\u202eprevious.md",  # a bidi override, which shows a name backwards
        "docs/zero\u200bwidth.md",
        "docs/line\nbreak.md",
        "docs/" + "a" * code_outline.MAX_PATH,
    ],
)
def test_a_path_that_hides_text_or_is_too_long_is_dropped_never_rendered(path: str) -> None:
    outline = code_outline.render(Listing((*TREE.paths, path)), About(words=frozenset({"docs"})), bound=2000)

    assert outline is not None
    assert path.rsplit("/", 1)[-1][:20] not in outline
    assert outline.splitlines()[-1].startswith("15 files in all, ")
    assert "1 more left out" in outline


def test_excluded_paths_are_neither_shown_nor_counted() -> None:
    outline = code_outline.render(TREE, About(), bound=2000, exclude=("docs/", "**/__init__.py", "tests/*/test_*.py"))

    assert outline is not None
    assert "docs" not in outline
    assert "__init__" not in outline
    assert "tests" not in outline
    assert outline.splitlines()[-1].startswith("7 files in all, ")


def test_a_tree_with_no_file_to_show_has_no_outline() -> None:
    assert code_outline.render(Listing(()), About(), bound=2000) is None
    assert code_outline.render(TREE, About(), bound=2000, exclude=("**",)) is None


def test_a_tree_wider_than_its_bound_is_cut_to_it() -> None:
    wide = Listing(tuple(f"package_{n:04}/BUILD" for n in range(400)))

    outline = code_outline.render(wide, About(), bound=600)

    assert outline is not None
    assert len(outline) <= 600
    assert outline.splitlines()[-1] == "400 files in all, 400 not listed by name."


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[Path]:
    """A repository with a commit on `main`, and a branch `work` that changes one file and adds another."""
    repo = tmp_path / "outlined"
    # An author of the tests' own, as `git_pool` sets one: a runner's git may have none.
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        repo.mkdir()
        git("init", "--quiet", "--initial-branch=main", cwd=repo)
        for name in ("src/app.py", "src/pkg/util.py", "docs/Überblick.md"):
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text("one\n")
        git("add", ".", cwd=repo)
        git("commit", "--quiet", "-m", "initial", cwd=repo)
        git("checkout", "--quiet", "-b", "work", cwd=repo)
        (repo / "src/app.py").write_text("two\n")
        (repo / "src/pkg/new.py").write_text("new\n")
        git("add", ".", cwd=repo)
        git("commit", "--quiet", "-m", "work", cwd=repo)
        # What the working tree holds is never read: the outline is of what git holds.
        (repo / "untracked.py").write_text("stray\n")
        yield repo


def test_a_tree_is_listed_from_gits_objects_never_the_working_tree(repository: Path) -> None:
    runner = procs.SubprocessRunner()

    assert code_outline.listed(runner, repository, "main") == Listing(
        ("docs/Überblick.md", "src/app.py", "src/pkg/util.py"),
    )
    assert "src/pkg/new.py" in code_outline.listed(runner, repository, "work").paths


def test_the_paths_a_branch_changed_since_its_base(repository: Path) -> None:
    runner = procs.SubprocessRunner()

    assert code_outline.changed(runner, repository, "main", "work") == {"src/app.py", "src/pkg/new.py"}


def test_a_ref_git_does_not_hold_is_unlisted(repository: Path, tmp_path: Path) -> None:
    runner = procs.SubprocessRunner()

    assert code_outline.holds(runner, repository, "work")
    assert not code_outline.holds(runner, repository, "refs/remotes/origin/gone")
    with pytest.raises(code_outline.Unlisted, match="git ls-tree failed"):
        code_outline.listed(runner, repository, "refs/remotes/origin/gone")
    # A directory that is no repository reads none above it.
    with pytest.raises(code_outline.Unlisted):
        code_outline.listed(runner, tmp_path, "main")
