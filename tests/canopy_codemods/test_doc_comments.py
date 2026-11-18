"""The `doc-comments` codemod: the comments it writes as `#:`, those it leaves alone, and that it does nothing twice."""

from typing import Final

import pytest
from canopy_codemods import run
from canopy_codemods.doc_comments import DocComments, comments

from tests.canopy_codemods.helpers import cases

NAME: Final = "doc-comments"
CASES: Final = cases(NAME)


def rewrite(source: str) -> str:
    return run.rewrite(source, [NAME])


@pytest.mark.parametrize(("before", "after"), CASES.rewritten)
def test_the_comment_above_a_constant_or_a_field_becomes_a_doc_comment(before: str, after: str) -> None:
    assert rewrite(before) == after
    assert rewrite(after) == after
    assert not DocComments.wants(after)


@pytest.mark.parametrize("source", CASES.left_alone)
def test_any_other_comment_is_left_alone(source: str) -> None:
    assert not comments(source)
    assert not DocComments.wants(source)
    assert rewrite(source) == source


def test_a_module_that_does_not_parse_is_wanted_so_that_it_is_reported() -> None:
    assert DocComments.wants("A = (\n")
    with pytest.raises(run.CodemodError, match="doc-comments"):
        rewrite("A = (\n")
