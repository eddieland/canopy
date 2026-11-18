"""The `final-constants` codemod: what it annotates, what it leaves alone, and that it has nothing to do twice."""

from typing import Final

import pytest
from canopy_codemods import run
from canopy_codemods.final_constants import FinalConstants, constants

from tests.canopy_codemods.helpers import cases

NAME: Final = "final-constants"
CASES: Final = cases(NAME)


def rewrite(source: str) -> str:
    return run.rewrite(source, [NAME])


@pytest.mark.parametrize(("before", "after"), CASES.rewritten)
def test_a_module_constant_is_annotated_final(before: str, after: str) -> None:
    assert rewrite(before) == after
    assert rewrite(after) == after
    assert not FinalConstants.wants(after)


@pytest.mark.parametrize("source", CASES.left_alone)
def test_what_is_not_a_constant_is_left_alone(source: str) -> None:
    assert not constants(source)
    assert not FinalConstants.wants(source)
    assert rewrite(source) == source


def test_a_module_that_does_not_parse_is_wanted_so_that_it_is_reported() -> None:
    assert FinalConstants.wants("A = (\n")
    with pytest.raises(run.CodemodError, match="final-constants"):
        rewrite("A = (\n")
