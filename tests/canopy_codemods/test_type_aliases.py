"""The `type-aliases` codemod: what it rewrites, what it leaves alone, and that it has nothing to do twice."""

from typing import Final

import pytest
from canopy_codemods import run
from canopy_codemods.type_aliases import TypeAliases, aliases

NAME: Final = "type-aliases"
LITERAL: Final = "from typing import Literal\n\n"


def rewrite(source: str) -> str:
    return run.rewrite(source, [NAME])


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param(
            f'{LITERAL}Outcome = Literal["packed", "skipped"]\n',
            f'{LITERAL}type Outcome = Literal["packed", "skipped"]\n',
            id="literal",
        ),
        pytest.param(
            "import typing\n\n_Kind = typing.Literal[1, 2]\n",
            "import typing\n\ntype _Kind = typing.Literal[1, 2]\n",
            id="private-and-dotted",
        ),
        pytest.param("Unit = tuple[str, str | None]\n", "type Unit = tuple[str, str | None]\n", id="tuple"),
        pytest.param("Many = tuple[int, ...]\n", "type Many = tuple[int, ...]\n", id="tuple-of-any-length"),
        pytest.param(
            "from collections.abc import Callable\n\nEndpoint = Callable[[str], 'Reply']\n",
            "from collections.abc import Callable\n\ntype Endpoint = Callable[[str], 'Reply']\n",
            id="callable",
        ),
        pytest.param("Value = int | str | None\n", "type Value = int | str | None\n", id="union-of-builtins"),
        pytest.param("Found = Row | None\n", "type Found = Row | None\n", id="union-with-none"),
        pytest.param("Rows = Row | list[Row]\n", "type Rows = Row | list[Row]\n", id="union-with-a-subscript"),
        pytest.param(
            '"""Doc."""\n\n#: What it is.\nUnit = tuple[\n    str,  # one\n    int,\n]  # why\n',
            '"""Doc."""\n\n#: What it is.\ntype Unit = tuple[\n    str,  # one\n    int,\n]  # why\n',
            id="keeps-comments-and-layout",
        ),
        pytest.param(
            "Unit = tuple[int]; Pair = tuple[str]\n",
            "type Unit = tuple[int]; type Pair = tuple[str]\n",
            id="one-line",
        ),
        pytest.param(
            "Unit = tuple[str, int]\n\n\ndef f(unit: Unit, *more: Unit, key: Unit) -> list[Unit]:\n"
            "    found: dict[str, Unit] = {}\n    return [unit, *more, key, *found.values()]\n",
            "type Unit = tuple[str, int]\n\n\ndef f(unit: Unit, *more: Unit, key: Unit) -> list[Unit]:\n"
            "    found: dict[str, Unit] = {}\n    return [unit, *more, key, *found.values()]\n",
            id="read-in-annotations",
        ),
        pytest.param(
            "Unit = tuple[str, int]\nUnits = tuple[Unit, ...]\ntype Found = Unit | None\n",
            "type Unit = tuple[str, int]\ntype Units = tuple[Unit, ...]\ntype Found = Unit | None\n",
            id="read-by-another-alias",
        ),
        pytest.param(
            f"{LITERAL}Kind = Literal[1, 2]\nUnit = tuple[str, int]\nprint(Kind)\n",
            f"{LITERAL}Kind = Literal[1, 2]\ntype Unit = tuple[str, int]\nprint(Kind)\n",
            id="beside-one-read-at-run-time",
        ),
    ],
)
def test_an_implicit_type_alias_becomes_a_type_statement(before: str, after: str) -> None:
    assert rewrite(before) == after
    assert rewrite(after) == after
    assert not TypeAliases.wants(after)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(f"{LITERAL}Kind = Literal[1, 2]\nKINDS = get_args(Kind)\n", id="passed-to-get-args"),
        pytest.param(
            f"{LITERAL}Kind = Literal[1, 2]\n\n\ndef f(x: object) -> bool:\n    return x in args(Kind)\n",
            id="read-in-a-function",
        ),
        pytest.param(
            "Unit = tuple[str, int]\n\n\ndef f(x: object) -> bool:\n    return isinstance(x, Unit)\n",
            id="isinstance",
        ),
        pytest.param("Unit = tuple[str, int]\nEMPTY = Unit(('', 0))\n", id="called"),
        pytest.param("Unit = tuple[str, int]\n\n\nclass Named(Unit):\n    pass\n", id="subclassed"),
        pytest.param("Unit = tuple[str, int]\nADAPTER = TypeAdapter(list[Unit])\n", id="subscripted-at-run-time"),
        pytest.param(
            f"{LITERAL}Kind = Literal[1, 2]\nField = Annotated[Kind, 'which']\n",
            id="read-by-an-alias-left-alone",
        ),
        pytest.param(
            f"{LITERAL}Kind = Literal[1, 2]\nKinds = tuple[Kind, ...]\nprint(Kinds)\n",
            id="read-by-an-alias-read-at-run-time",
        ),
        pytest.param("Key = Annotated[str, Field(description='A key.')]\n", id="annotated"),
        pytest.param("Dep = Annotated[Options, Depends(options)]\n", id="dependency"),
        pytest.param("Index = dict[str, int]\nRows = list[Row]\n", id="another-subscript"),
        pytest.param("Both = Color.RED | Color.BLUE\nEither = Left | Right\n", id="union-that-may-be-of-values"),
        pytest.param("Total = int | 3\nSpan = tuple[int, 1 + 2]\n", id="not-a-type-expression"),
        pytest.param("Row = records.Run\nMake = make_row\n", id="a-class-used-as-a-value"),
        pytest.param("from typing import TypeVar\n\nT = TypeVar('T')\nPair = tuple[T, T]\n", id="generic"),
        pytest.param("from typing import NewType\n\nUserId = NewType('UserId', int)\n", id="new-type"),
        pytest.param("Point = namedtuple('Point', ['x', 'y'])\n", id="namedtuple"),
        pytest.param("from typing import TypeAlias\n\nUnit: TypeAlias = tuple[str, int]\n", id="explicit-type-alias"),
        pytest.param("type Unit = tuple[str, int]\n", id="type-statement-already"),
        pytest.param("UNIT = tuple[str, int]\nT = tuple[int]\n", id="upper-case"),
        pytest.param("unit = tuple[str, int]\n", id="lowercase"),
        pytest.param("Unit = tuple[str, int]\nUnit = tuple[str, str]\n", id="assigned-twice"),
        pytest.param("Unit = Other = tuple[str, int]\n", id="chained"),
        pytest.param(
            "import sys\n\nif sys.platform == 'darwin':\n    Unit = tuple[str, int]\nelse:\n    Unit = tuple[str]\n",
            id="nested",
        ),
        pytest.param(
            "class C:\n    Unit = tuple[str, int]\n\n\ndef f() -> None:\n    Unit = tuple[str]\n",
            id="not-module",
        ),
    ],
)
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
