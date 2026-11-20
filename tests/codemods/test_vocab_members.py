"""The `vocab-members` codemod: the strings it names as members, those it leaves alone, and the modules it covers."""

from pathlib import Path
from typing import Final

import pytest
from brash import registry, run

from codemods.vocab_members import PACKAGE, VocabMembers, rewrites
from tests.codemods.helpers import cases

NAME: Final = "vocab-members"
CASES: Final = cases(NAME)
#: The repository the codemods sit in.
REPO: Final = PACKAGE.parents[1]
#: A comparison the codemod rewrites in one of canopy's modules.
COMPARED: Final = """\
from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> bool:
    return status == "done"
"""


def rewrite(source: str, filename: str | None = None) -> str:
    return run.rewrite(source, [NAME], filename=filename, codemods={NAME: VocabMembers})


def test_brash_runs_it_after_its_own_from_anywhere_in_the_repository() -> None:
    found = registry.registered(REPO / "src" / "canopy")

    assert list(found)[-1] == NAME
    assert found[NAME] is VocabMembers


@pytest.mark.parametrize(("before", "after"), CASES.rewritten)
def test_a_string_tied_to_one_vocabulary_becomes_its_member(before: str, after: str) -> None:
    assert rewrite(before) == after
    assert rewrite(after) == after
    assert not VocabMembers.wants(after)


@pytest.mark.parametrize("source", CASES.left_alone)
def test_a_string_nothing_ties_to_one_vocabulary_that_holds_it_is_left_alone(source: str) -> None:
    assert not rewrites(source).strings
    assert not VocabMembers.wants(source)
    assert rewrite(source) == source


@pytest.mark.parametrize("filename", [PACKAGE / "core" / "outbox.py", PACKAGE / "runs" / "worker.py"])
def test_canopys_own_modules_are_rewritten(filename: Path) -> None:
    assert VocabMembers.covers(str(filename))
    assert rewrite(COMPARED, str(filename)) != COMPARED


@pytest.mark.parametrize(
    "filename",
    [
        REPO / "tests" / "canopy" / "core" / "test_outbox.py",
        REPO / "packages" / "canopy-github" / "src" / "canopy_github" / "__init__.py",
        PACKAGE / "core" / "vocab.py",
        REPO / "scripts" / "status.py",
        # A clone at `~/src/canopy` holds a `src/canopy` above every file, its tests' too.
        Path("/home/me/src/canopy/tests/canopy/core/test_outbox.py"),
    ],
)
def test_the_tests_the_other_programs_and_the_vocabularies_themselves_are_left_alone(filename: Path) -> None:
    assert not VocabMembers.covers(str(filename))
    assert rewrite(COMPARED, str(filename)) == COMPARED


def test_a_module_that_does_not_parse_is_wanted_so_that_it_is_reported() -> None:
    broken = 'from canopy.core import records\nif run.status == "running" (\n'

    assert VocabMembers.wants(broken)
    with pytest.raises(run.CodemodError, match=NAME):
        rewrite(broken)
