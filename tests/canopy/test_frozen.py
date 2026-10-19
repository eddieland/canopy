"""Each frozen dataclass in canopy, its programs, and its tests holds no mutable collection (AGENTS.md).

A frozen dataclass is a value: nothing changes it once made. A `list`, `dict`, or `set` field would let anything that
reads it change it anyway, so a field is typed by what its readers need, `Sequence` or `Mapping`, and the type checker
refuses a change through it. A class that keeps state it changes, such as a stack of open blocks, is not frozen. The
test reads the annotations, as the type checker does, so a field typed `Sequence` that holds a list passes.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

#: The repository's root in a checkout.
ROOT = Path(__file__).resolve().parents[2]
#: Where canopy's own code is: the harness, its separate programs, and the tests.
SOURCES = (ROOT / "src", ROOT / "packages", ROOT / "tests")
#: The names of the collections a frozen dataclass's field may not be, wherever in its annotation they appear.
MUTABLE = frozenset(
    {
        "list",
        "dict",
        "set",
        "bytearray",
        "defaultdict",
        "deque",
        "Counter",
        "OrderedDict",
        "MutableSequence",
        "MutableMapping",
        "MutableSet",
    }
)


def test_a_frozen_dataclass_holds_no_mutable_collection() -> None:
    found = [
        f"{path.relative_to(ROOT)}:{node.lineno}: {cls}.{ast.unparse(node.target)}: {ast.unparse(node.annotation)}"
        for root in SOURCES
        for path in sorted(root.rglob("*.py"))
        for cls, node in _frozen_fields(ast.parse(path.read_text(encoding="utf-8")))
        if any(name in MUTABLE for name in _named(node.annotation))
    ]
    assert not found, "a frozen dataclass's field is a mutable collection:\n" + "\n".join(found)


def test_the_check_finds_a_mutable_field_and_passes_an_immutable_one() -> None:
    source = """
@dataclass(frozen=True)
class Value:
    names: list[str]
    by_key: Mapping[str, tuple[int, ...]]
    nested: tuple[dict[str, int], ...]
    later: Callable[[int], list[str]]

@dataclasses.dataclass
class State:
    stack: list[str]
"""
    flagged = [
        ast.unparse(node.target)
        for _, node in _frozen_fields(ast.parse(source))
        if any(name in MUTABLE for name in _named(node.annotation))
    ]
    assert flagged == ["names", "nested"]


def _frozen_fields(tree: ast.Module) -> Iterator[tuple[str, ast.AnnAssign]]:
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and any(_freezes(d) for d in cls.decorator_list):
            for node in cls.body:
                if isinstance(node, ast.AnnAssign):
                    yield cls.name, node


def _freezes(decorator: ast.expr) -> bool:
    return isinstance(decorator, ast.Call) and any(
        k.arg == "frozen" and isinstance(k.value, ast.Constant) and k.value.value is True for k in decorator.keywords
    )


def _named(annotation: ast.expr) -> Iterator[str]:
    """Each name the annotation spells, except in what a callable takes and returns: a call returns a new list."""
    match annotation:
        case ast.Subscript(value=value) if _last(value) == "Callable":
            yield "Callable"
        case ast.Name(id=name):
            yield name
        case ast.Attribute(attr=name):
            yield name
        case ast.Constant(value=str(text)):
            yield from _named(ast.parse(text, mode="eval").body)
        case _:
            for child in ast.iter_child_nodes(annotation):
                if isinstance(child, ast.expr):
                    yield from _named(child)


def _last(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None
