"""Write the comment above a constant or a field as a Sphinx doc comment, `#:`, which editors and tools attach to it.

The comment is the block of whole-line comments directly above the name, with no blank line between:

    # How many times a run is resumed before it is given up.
    MAX_RESUMES: Final = 3

becomes

    #: How many times a run is resumed before it is given up.
    MAX_RESUMES: Final = 3

The names are a module's constants and type aliases, among its own statements, and the fields of a `@dataclass`, a
`NamedTuple`, or an enum, its members among them.

It leaves alone:

- a field of any other class. A pydantic model's description is the docstring below the field, or its `Field`, and
  never a comment, so a `#` above one is a note kept out of the schema on purpose;
- a comment above anything else: a function, a statement inside one, an import, a lowercase module object such as a
  logger;
- a block with a `#:` line in it already, a directive to a tool (`# noqa`, `# type:`, `# fmt:`), or a section's
  banner (`# ---- Limits ----`);
- a comment a blank line separates from the name.

A comment is not syntax, so which lines to rewrite is decided from the stdlib's syntax tree and the module's text, and
a module with none is never parsed by libcst (`Command.wants`).
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final, override

import libcst as cst

from canopy_codemods.command import Command
from canopy_codemods.final_constants import last_name

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

#: A module's name that is no lowercase object: a constant, `LIMIT`, or a type alias or type variable, `Outcome`.
NAMED: Final = re.compile(r"_*[A-Z]\w*")
#: The base classes that make a class an enum, by their last names.
ENUMS: Final = frozenset({"Enum", "Flag", "IntEnum", "IntFlag", "ReprEnum", "StrEnum"})
#: A comment line that keeps its whole block as it is: a doc comment already, a shebang, or a directive to a tool.
_KEPT: Final = re.compile(
    r"#(?:[:!]|\s*(?:noqa|type|pyrefly|pyright|mypy|fmt|ruff|isort|pragma|pylint|coding)\b\s*:|\s*noqa\b)",
)
#: A section's banner: a comment that opens or closes with a rule, such as `# ---- Limits ----` or `# ====`.
_BANNER: Final = re.compile(r"#\s*(?:[-=#*~_]{3,}.*|.*[-=#*~_]{3,}\s*$)")


class DocComments(Command):
    """Write the comment above a constant or a field as a doc comment, `#:`."""

    DESCRIPTION = "Write the comment above a constant, a dataclass or NamedTuple field, or an enum member as `#:`."

    @classmethod
    @override
    def wants(cls, source: str) -> bool:
        """Whether a module with this text has a comment to rewrite.

        Returns:
            True when it has one, or does not parse, which is then libcst's to report.
        """
        try:
            return bool(comments(source))
        except SyntaxError:
            return True

    @override
    def transform_module_impl(self, tree: cst.Module) -> cst.Module:
        """Rewrite the module's comments above its constants and fields.

        Returns:
            The module rewritten, or as it was when it has no such comment.
        """
        source = tree.code
        rewrite = comments(source)
        if not rewrite:
            return tree
        lines = source.split("\n")
        for index in rewrite:
            lines[index] = lines[index].replace("#", "#:", 1)
        return cst.parse_module("\n".join(lines), tree.config_for_parsing)


def comments(source: str) -> frozenset[int]:
    """The comment lines of a module to rewrite as doc comments, from its text.

    Returns:
        The lines, as indexes into the text split at each newline.

    Raises:
        SyntaxError: When the text is not Python.
    """
    lines = source.split("\n")
    found: set[int] = set()
    for body, fields in _bodies(ast.parse(source)):
        above = 0
        for statement in body:
            if _named(statement, fields=fields):
                found.update(_block(lines, statement, above))
            above = statement.end_lineno or statement.lineno
    return frozenset(found)


def _bodies(module: ast.Module) -> Iterator[tuple[Sequence[ast.stmt], bool]]:
    """The bodies whose names take a doc comment: the module's own, and each class's whose assignments are fields.

    Yields:
        A body's statements, and whether they are a class's.
    """
    yield module.body, False
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef) and _has_fields(node):
            yield node.body, True


def _has_fields(node: ast.ClassDef) -> bool:
    """Whether a class statement says its assignments are fields: a `@dataclass`, a `NamedTuple`, or an enum.

    Returns:
        True for one of those; False for any other class, a pydantic model among them.
    """
    decorators = (d.func if isinstance(d, ast.Call) else d for d in node.decorator_list)
    return any(last_name(decorator) == "dataclass" for decorator in decorators) or any(
        last_name(base) in ENUMS | {"NamedTuple"} for base in node.bases
    )


def _named(statement: ast.stmt, *, fields: bool) -> bool:
    """Whether a statement binds a name that takes a doc comment.

    Args:
        statement: A statement of a module's or a class's body.
        fields: Whether the body is a class's, where every name is a field; a module's lowercase name is an object.

    Returns:
        True for an assignment to one such name, annotated or not, and for a `type` statement.
    """
    match statement:
        case ast.TypeAlias():
            return True
        case ast.Assign(targets=[ast.Name(id=name)]) | ast.AnnAssign(target=ast.Name(id=name)):
            return fields or NAMED.fullmatch(name) is not None
        case _:
            return False


def _block(lines: Sequence[str], statement: ast.stmt, above: int) -> Sequence[int]:
    """The comment block directly above a statement, when it is one to rewrite.

    Args:
        lines: The module's lines.
        statement: The statement the block is above.
        above: The number of the last line of the statement before it, which the block cannot reach into.

    Returns:
        The block's lines, as indexes into `lines`; none when a line of it keeps the block as it is.
    """
    block: list[int] = []
    index = statement.lineno - 2
    while index >= above and (comment := lines[index].lstrip()).startswith("#"):
        # A comment indented otherwise belongs to the block it closes, not to this name.
        if len(lines[index]) - len(comment) != statement.col_offset or _KEPT.match(comment) or _BANNER.match(comment):
            return ()
        block.append(index)
        index -= 1
    return block
