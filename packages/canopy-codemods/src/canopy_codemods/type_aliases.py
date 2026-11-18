"""Spell an implicit type alias as a `type` statement, the one piece of 3.12 typing syntax ruff cannot hold.

ruff rewrites an alias annotated `TypeAlias` (UP040), but a bare `Name = <type expression>` is an assignment like any
other to it. Here `Outcome = Literal["packed", "skipped"]` becomes `type Outcome = Literal["packed", "skipped"]`.

An alias is a `CamelCase` name bound once, by an assignment among the module's own statements, to a `Literal`, a
`tuple`, a `Callable`, or a union of types. A `type` statement makes a `TypeAliasType`, which is not the type it names
when the program runs, so the rewrite is kept to where that cannot show. It leaves alone:

- a name the module reads outside an annotation: passed to `get_args`, `isinstance`, or any other call, subscripted,
  called, subclassed, or assigned to another name. A read inside another alias this codemod rewrites, or inside a
  `type` statement, is not one, since neither is evaluated until asked for;
- an `Annotated[...]` alias, whose metadata frameworks read at run time, and any other subscript (`dict[str, int]`),
  which may be a class the module calls;
- a union that may be arithmetic on values: one with no `None`, no subscript, and no builtin type among its members;
- a generic alias, one that names a `TypeVar` the module declares, which a `type` statement spells another way;
- a name the module binds again, an `UPPER_CASE` name, which is a constant (`final-constants`), and an assignment
  nested in an `if`, `try`, or `with`.

It sees one module at a time. An alias another module reads at run time is rewritten all the same, and that reader
then reads its `__value__`.

Which names are aliases is decided from the stdlib's syntax tree, which is quick to build, and only for a module whose
text has a capitalised name assigned at the margin, so a module with none to rewrite is never parsed by libcst
(`Command.wants`).
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from typing import Final, override

import libcst as cst

from canopy_codemods.command import Command
from canopy_codemods.final_constants import CONSTANT, DECLARES, Bindings, last_name

#: What the text of a module with an alias to rewrite must hold: a capitalised name assigned at the margin.
ASSIGNED: Final = re.compile(r"^_*[A-Z]\w*[ \t]*=[^=]", re.MULTILINE)
#: The subscripts taken as an alias whatever they hold, by the last name of what is subscripted.
HEADS: Final = frozenset({"Callable", "Literal", "tuple"})
#: The builtin types whose presence in a union says it is a union of types, not arithmetic on values.
BUILTINS: Final = frozenset({"bool", "bytes", "complex", "dict", "float", "int", "list", "object", "set", "str"})
#: Who reads a name when it is not another alias: the program as it runs.
_RUNTIME: Final = ""


class TypeAliases(Command):
    """Rewrite every implicit type alias as a `type` statement."""

    DESCRIPTION = "Rewrite an implicit type alias (`Name = Literal[...]`) as a `type` statement."

    @classmethod
    @override
    def wants(cls, source: str) -> bool:
        """Whether a module with this text has an alias to rewrite.

        Returns:
            True when it has one, or may have one and does not parse, which is then libcst's to report.
        """
        if not ASSIGNED.search(source):
            return False
        try:
            return bool(aliases(source))
        except SyntaxError:
            return True

    @override
    def transform_module_impl(self, tree: cst.Module) -> cst.Module:
        """Rewrite the module's aliases.

        Returns:
            The module rewritten, or as it was when it has no alias to rewrite.
        """
        names = aliases(tree.code)
        if not names:
            return tree
        body = [
            statement.with_changes(body=[_typed(small, names) for small in statement.body])
            if isinstance(statement, cst.SimpleStatementLine)
            else statement
            for statement in tree.body
        ]
        return tree.with_changes(body=body)


def aliases(source: str) -> frozenset[str]:
    """The names of a module's implicit type aliases that can become `type` statements, from its text.

    Returns:
        The names, each bound once in the module by the assignment to rewrite.

    Raises:
        SyntaxError: When the text is not Python.
    """
    module = ast.parse(source)
    bindings = Bindings()
    bindings.visit(module)
    variables = {
        name
        for statement in module.body
        if (assigned := _assigned(statement)) is not None
        and isinstance(assigned[1], ast.Call)
        and last_name(assigned[1].func) in DECLARES
        for name in [assigned[0]]
    }
    found = {
        name
        for statement in module.body
        if (assigned := _assigned(statement)) is not None
        and bindings.counts[assigned[0]] == 1
        and _is_alias(*assigned)
        and not variables & {node.id for node in ast.walk(assigned[1]) if isinstance(node, ast.Name)}
        for name in [assigned[0]]
    }
    if not found:
        return frozenset()
    readers = _Readers(found)
    readers.visit(module)
    # An alias read at run time stays an assignment, and so reads the aliases it names at run time itself.
    kept = {_RUNTIME}
    while late := {name for name in found if readers.of[name] & kept}:
        found -= late
        kept |= late
    return frozenset(found)


class _Readers(ast.NodeVisitor):
    """Finds who reads each candidate: another candidate's value, or the program as it runs (`_RUNTIME`).

    A read in an annotation or a `type` statement is neither: nothing there needs the alias to be the type it names.
    A name is taken as the module's wherever it is read, so a local of the same name only leaves an alias unwritten.
    """

    def __init__(self, candidates: set[str]) -> None:
        self.of: defaultdict[str, set[str]] = defaultdict(set)
        self._candidates = candidates
        #: Who reads the names being visited; None inside an annotation or a `type` statement.
        self._reader: str | None = _RUNTIME
        #: How many functions and classes enclose the node being visited: 0 among the module's own statements.
        self._depth = 0

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in self._candidates and self._reader is not None:
            self.of[node.id].add(self._reader)

    @override
    def visit_Assign(self, node: ast.Assign) -> None:
        assigned = None if self._depth else _assigned(node)
        if assigned is not None and assigned[0] in self._candidates:
            self._read_by(assigned[0], node.value)
        else:
            self.generic_visit(node)

    @override
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._read_by(None, node.annotation)
        if node.value is not None:
            self.visit(node.value)

    @override
    def visit_TypeAlias(self, node: ast.TypeAlias) -> None:
        self._read_by(None, node.value)

    @override
    def visit_arg(self, node: ast.arg) -> None:
        if node.annotation is not None:
            self._read_by(None, node.annotation)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._nested(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.returns is not None:
            self._read_by(None, node.returns)
        returns, node.returns = node.returns, None
        self._nested(node)
        node.returns = returns

    def _nested(self, node: ast.AST) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    def _read_by(self, reader: str | None, node: ast.expr) -> None:
        before, self._reader = self._reader, reader
        self.visit(node)
        self._reader = before


def _assigned(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    """The name a statement assigns and its value, when it is a plain assignment to one name.

    Returns:
        The two, or None for any other statement.
    """
    match statement:
        case ast.Assign(targets=[ast.Name(id=name)], value=value):
            return name, value
        case _:
            return None


def _is_alias(name: str, value: ast.expr) -> bool:
    """Whether an assignment reads as a type alias this codemod rewrites.

    Returns:
        True for a `CamelCase` name given a `Literal`, `tuple`, or `Callable`, or a union that is one of types.
    """
    if not name.lstrip("_")[:1].isupper() or CONSTANT.fullmatch(name):
        return False
    match value:
        case ast.Subscript(value=head):
            return last_name(head) in HEADS and _is_type(value)
        case ast.BinOp(op=ast.BitOr()):
            return _is_type(value) and any(_marks_a_union(member) for member in _members(value))
        case _:
            return False


def _members(union: ast.expr) -> list[ast.expr]:
    """The members of a union, `A | B | C`, however it nests.

    Returns:
        The members in order; the expression itself when it is no union.
    """
    match union:
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return [*_members(left), *_members(right)]
        case _:
            return [union]


def _marks_a_union(member: ast.expr) -> bool:
    """Whether a union's member can only be a type: `None`, a subscript, or a builtin type.

    Returns:
        True when it can; False for a name that may as well be a flag.
    """
    match member:
        case ast.Constant(value=None) | ast.Subscript():
            return True
        case ast.Name(id=name):
            return name in BUILTINS
        case _:
            return False


def _is_type(expression: ast.expr) -> bool:
    """Whether an expression is spelled as a type: names, subscripts of them, `None`, and unions of those.

    Returns:
        True when every part of it is.
    """
    match expression:
        case ast.Name() | ast.Constant(value=None | str()):
            return True
        case ast.Attribute(value=value):
            return _is_type(value)
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return _is_type(left) and _is_type(right)
        case ast.Subscript(value=head, slice=inner):
            if last_name(head) == "Literal":
                return True
            arguments = inner.elts if isinstance(inner, ast.Tuple) else [inner]
            return _is_type(head) and all(_is_argument(argument) for argument in arguments)
        case _:
            return False


def _is_argument(expression: ast.expr) -> bool:
    """Whether an expression can stand inside a type's brackets: a type, `...`, or a `Callable`'s list of them.

    Returns:
        True when it can.
    """
    match expression:
        case ast.Constant(value=value) if value is ...:
            return True
        case ast.List(elts=parameters):
            return all(_is_type(parameter) for parameter in parameters)
        case _:
            return _is_type(expression)


def _typed(small: cst.BaseSmallStatement, names: frozenset[str]) -> cst.BaseSmallStatement:
    """Rewrite a statement as a `type` statement when it assigns one of `names`.

    Returns:
        The statement rewritten, or as it was.
    """
    match small:
        case cst.Assign(targets=[cst.AssignTarget(target=cst.Name(value=name) as target)]) if name in names:
            return cst.TypeAlias(target, small.value, semicolon=small.semicolon)
        case _:
            return small
