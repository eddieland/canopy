"""The `general-params` codemod: what it widens, what it leaves alone, and that it has nothing to do twice."""

from typing import Final

import pytest
from canopy_codemods import run
from canopy_codemods.general_params import GeneralParams, widened

from tests.canopy_codemods.helpers import cases

NAME: Final = "general-params"
CASES: Final = cases(NAME)


def rewrite(source: str) -> str:
    return run.rewrite(source, [NAME])


@pytest.mark.parametrize(("before", "after"), CASES.rewritten)
def test_a_parameter_only_read_takes_the_abstract_type_its_reads_need(before: str, after: str) -> None:
    assert rewrite(before) == after
    assert rewrite(after) == after
    assert not GeneralParams.wants(after)


@pytest.mark.parametrize("source", CASES.left_alone)
def test_a_parameter_not_known_to_be_only_read_is_left_alone(source: str) -> None:
    assert not widened(source)
    assert not GeneralParams.wants(source)
    assert rewrite(source) == source


def test_a_parameter_is_found_by_the_line_of_its_name() -> None:
    source = "def total(\n    tax: float,\n    costs: list[float],\n) -> float:\n    return sum(costs) * tax\n"

    assert widened(source) == {(3, "costs"): "Iterable"}


def test_a_module_that_subscripts_no_concrete_collection_is_never_parsed() -> None:
    assert not GeneralParams.wants("def f(x: tuple[int, ...]) -> (\n")


def test_a_module_that_does_not_parse_is_wanted_so_that_it_is_reported() -> None:
    assert GeneralParams.wants("def f(x: list[int]) -> (\n")
    with pytest.raises(run.CodemodError, match="general-params"):
        rewrite("def f(x: list[int]) -> (\n")
