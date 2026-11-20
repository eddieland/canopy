"""What the tests of canopy's own codemods share: each codemod's cases, read from a Markdown file of Python snippets.

`cases/<codemod>.md` holds a case under each `###` heading, as fenced `python` blocks: two for a module's text before
and after the codemod, one for text it must leave as it is. Anything else in the file is prose for its reader. A case
is written there, where it reads as the code it is, rather than as an escaped string in a test module.
"""

from pathlib import Path
from typing import Final, NamedTuple

import pytest
from _pytest.mark import ParameterSet

#: Where each codemod's cases are, in a file named for it.
CASES: Final = Path(__file__).parent / "cases"
_FENCE: Final = "```"


class Cases(NamedTuple):
    """A codemod's cases, each a `pytest.param` with its heading as its id."""

    #: A module's text before and after: `("before", "after")`.
    rewritten: list[ParameterSet]
    #: A module's text the codemod leaves as it is: `"source"`.
    left_alone: list[ParameterSet]


def cases(codemod: str) -> Cases:
    """Read a codemod's cases from `cases/<codemod>.md`.

    Returns:
        The cases, in the file's order.

    Raises:
        ValueError: When a heading has no snippet under it, or more than two, or a snippet has no heading.
    """
    rewritten: list[ParameterSet] = []
    left_alone: list[ParameterSet] = []
    found = Cases(rewritten, left_alone)
    title: str | None = None
    snippets: list[str] = []
    snippet: list[str] | None = None
    path = CASES / f"{codemod}.md"
    for number, line in enumerate([*path.read_text(encoding="utf-8").splitlines(), "### "], start=1):
        if snippet is not None:
            if line == _FENCE:
                snippets.append("".join(f"{inner}\n" for inner in snippet))
                snippet = None
            else:
                snippet.append(line)
        elif line == f"{_FENCE}python":
            snippet = []
        elif line.startswith("#"):
            if title is not None or snippets:
                _add(found, title, snippets, f"{path}:{number}")
            title = line.removeprefix("### ") if line.startswith("### ") else None
            snippets = list[str]()
    return found


def _add(found: Cases, title: str | None, snippets: list[str], where: str) -> None:
    match title, snippets:
        case str(), [source]:
            found.left_alone.append(pytest.param(source, id=title))
        case str(), [before, after]:
            found.rewritten.append(pytest.param(before, after, id=title))
        case _:
            raise ValueError(f"{where}: the case above ({title}) holds {len(snippets)} snippets, not one or two")
