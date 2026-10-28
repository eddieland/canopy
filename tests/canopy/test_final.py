"""Each module-level constant in canopy, its programs, and its tests is annotated `Final` (AGENTS.md).

A constant is a name spelled in capitals, `MAX_TEXT` or `_PATTERN`, bound at a module's top level, in an `if` or `try`
there included. `Final` lets the type checker refuse a rebinding of it anywhere, a test's included, so the name keeps
the one value its readers assume. A tuple of names cannot be annotated, so each constant gets a line of its own. No
linter has the rule, so this test reads each module's tree, as `test_frozen.py` does.
"""

import ast
import re
import tomllib
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Final

#: The repository's root in a checkout.
ROOT: Final = Path(__file__).resolve().parents[2]
#: Where canopy's own code is: the harness, its separate programs, and the tests.
SOURCES: Final = (ROOT / "src", ROOT / "packages", ROOT / "tests")
#: The extensionless fakes ruff lints as Python, as its config names them.
FAKES: Final[Sequence[str]] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"][
    "extend-include"
]
#: A constant's name, as PEP 8 spells it.
CONSTANT: Final = re.compile(r"_?[A-Z][A-Z0-9_]*")


def test_a_module_level_constant_is_final() -> None:
    found = [
        f"{path.relative_to(ROOT)}:{node.lineno}: {name}"
        for path in _modules()
        for node, name in _unfinal(ast.parse(path.read_bytes()))
    ]
    assert not found, "a module-level constant is not annotated Final:\n" + "\n".join(found)


def test_the_check_finds_a_bare_constant_and_passes_a_final_one() -> None:
    source = """
BARE = 1
TYPED: int = 2
FIRST, SECOND = 3, 4
DONE: Final = 5
WRAPPED: Final[Mapping[str, int]] = {}
QUALIFIED: typing.Final = 6
_PRIVATE = 7
lower = 8
type Alias = int
if TYPE_CHECKING:
    GUARDED = 9

def f() -> None:
    LOCAL = 10

class C:
    ATTRIBUTE = 11
"""
    assert [name for _, name in _unfinal(ast.parse(source))] == [
        "BARE",
        "TYPED",
        "FIRST",
        "SECOND",
        "_PRIVATE",
        "GUARDED",
    ]


def _modules() -> Iterator[Path]:
    for root in SOURCES:
        yield from sorted(path for path in root.rglob("*.py") if "node_modules" not in path.parts)
    yield from (ROOT / fake for fake in FAKES)


def _unfinal(tree: ast.Module) -> Iterator[tuple[ast.stmt, str]]:
    """Each module-level binding of a constant's name that is not annotated `Final`, with the name."""
    for node in _top_level(tree.body):
        yield from ((node, name) for name in _bound(node) if CONSTANT.fullmatch(name))


def _bound(node: ast.stmt) -> Iterator[str]:
    """Each name the statement binds without a `Final` annotation."""
    match node:
        case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation) if not _final(annotation):
            yield name
        case ast.Assign(targets=targets):
            yield from (n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name))
        case _:
            pass


def _top_level(body: Iterable[ast.stmt]) -> Iterator[ast.stmt]:
    """Each statement of a module's body, and of the `if`, `try`, and `with` blocks there, which bind at its level."""
    for node in body:
        yield node
        match node:
            case ast.If(body=then, orelse=orelse):
                yield from _top_level(then)
                yield from _top_level(orelse)
            case ast.Try(body=tried, handlers=handlers, orelse=orelse, finalbody=final):
                for block in (tried, *(handler.body for handler in handlers), orelse, final):
                    yield from _top_level(block)
            case ast.With(body=inside):
                yield from _top_level(inside)
            case _:
                pass


def _final(annotation: ast.expr) -> bool:
    match annotation:
        case ast.Subscript(value=value):
            return _final(value)
        case ast.Name(id="Final") | ast.Attribute(attr="Final"):
            return True
        case _:
            return False
