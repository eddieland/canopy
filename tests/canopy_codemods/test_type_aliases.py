"""The `type-aliases` codemod: what it rewrites, what it leaves alone, and that it has nothing to do twice."""

from typing import Final

import pytest
from canopy_codemods import run
from canopy_codemods.type_aliases import TypeAliases, aliases

from tests.canopy_codemods.helpers import cases

NAME: Final = "type-aliases"
CASES: Final = cases(NAME)


def rewrite(source: str) -> str:
    return run.rewrite(source, [NAME])


@pytest.mark.parametrize(("before", "after"), CASES.rewritten)
def test_an_implicit_type_alias_becomes_a_type_statement(before: str, after: str) -> None:
    assert rewrite(before) == after
    assert rewrite(after) == after
    assert not TypeAliases.wants(after)


@pytest.mark.parametrize("source", CASES.left_alone)
def test_what_is_not_an_alias_safe_to_rewrite_is_left_alone(source: str) -> None:
    assert not aliases(source)
    assert not TypeAliases.wants(source)
    assert rewrite(source) == source


def test_a_module_with_no_capitalised_name_assigned_is_never_parsed() -> None:
    assert not TypeAliases.wants("x = (\n")


def test_a_module_that_does_not_parse_is_wanted_so_that_it_is_reported() -> None:
    assert TypeAliases.wants("Unit = tuple[\n")
    with pytest.raises(run.CodemodError, match="type-aliases"):
        rewrite("Unit = tuple[\n")
