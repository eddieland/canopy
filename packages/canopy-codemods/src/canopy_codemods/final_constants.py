"""Annotate every module constant `Final`, so the type checker refuses a second assignment to it.

A module constant is a name in `UPPER_CASE` bound once, by an assignment among the module's own statements:
`LIMIT = 3` becomes `LIMIT: Final = 3`, which keeps the type the checker inferred, and `NAMES: Sequence[str] = ()`
becomes `NAMES: Final[Sequence[str]] = ()`.

It leaves alone what is not a constant, or cannot be `Final`:

- a lowercase name, which is how a module spells an object with state of its own (`_log`, `router`);
- a name the module binds again, by a second assignment, `+=`, `del`, an import, a loop, or a function's `global`;
- an object made to hold state, whatever its name: a logger, a lock, a context variable (`STATEFUL`);
- what the type system reads as a declaration, not a value: a `TypeVar` and its kin, and an explicit `TypeAlias`;
- an assignment to several names at once, and one nested in an `if`, `try`, or `with`.

Which names are constants is decided from the stdlib's syntax tree, which is quick to build, so a module with none
left to annotate is never parsed by libcst (`Command.wants`).
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Set as AbstractSet
from typing import Final, override

import libcst as cst
from libcst.codemod.visitors import AddImportsVisitor

from canopy_codemods.command import Command

#: A constant's name: upper case, digits, and underscores, after any leading underscores.
CONSTANT: Final = re.compile(r"_*[A-Z][A-Z0-9_]*")
#: The calls that make an object whose job is to hold state, by the last name of what is called.
STATEFUL: Final = frozenset(
    {"BoundedSemaphore", "Condition", "ContextVar", "Event", "Lock", "RLock", "Semaphore", "getLogger", "local"},
)
#: The calls that declare a type, which a type checker reads only from a plain assignment.
DECLARES: Final = frozenset({"NewType", "ParamSpec", "TypeAliasType", "TypeVar", "TypeVarTuple", "namedtuple"})
#: The annotations a constant keeps as they are: already final, or a declaration of another kind.
_KEPT: Final = frozenset({"ClassVar", "Final", "TypeAlias"})


class FinalConstants(Command):
    """Annotate every module constant `Final`."""

    DESCRIPTION = "Annotate every UPPER_CASE module constant `Final`."

    @classmethod
    @override
    def wants(cls, source: str) -> bool:
        """Whether a module with this text has a constant to annotate.

        Returns:
            True when it has one, or does not parse, which is then libcst's to report.
        """
        try:
            return bool(constants(source))
        except SyntaxError:
            return True

    @override
    def transform_module_impl(self, tree: cst.Module) -> cst.Module:
        """Annotate the module's constants, and import `Final` when it annotated any.

        Returns:
            The module rewritten, or as it was when it has no constant to annotate.
        """
        names = constants(tree.code)
        if not names:
            return tree
        body = [
            statement.with_changes(body=[_final(small, names) for small in statement.body])
            if isinstance(statement, cst.SimpleStatementLine)
            else statement
            for statement in tree.body
        ]
        AddImportsVisitor.add_needed_import(self.context, "typing", "Final")
        return AddImportsVisitor(self.context).transform_module(tree.with_changes(body=body))


def constants(source: str) -> frozenset[str]:
    """The names of a module's constants that are not `Final` yet, from its text.

    Returns:
        The names, each bound once in the module by the assignment to annotate.

    Raises:
        SyntaxError: When the text is not Python.
    """
    module = ast.parse(source)
    bindings = Bindings()
    bindings.visit(module)
    return frozenset(
        name for statement in module.body if (name := _candidate(statement)) is not None and bindings.counts[name] == 1
    )


class Bindings(ast.NodeVisitor):
    """Counts how often each name is bound in a module's own scope; a name deleted or declared `global` counts twice."""

    def __init__(self) -> None:
        """Start with no name bound."""
        #: How often each name is bound.
        self.counts: Counter[str] = Counter()
        #: How many functions, classes, and lambdas enclose the node being visited: 0 in the module's own scope.
        self._depth = 0

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if not self._depth and not isinstance(node.ctx, ast.Load):
            self.counts[node.id] += 2 if isinstance(node.ctx, ast.Del) else 1

    @override
    def visit_Global(self, node: ast.Global) -> None:
        self.counts.update(node.names * 2)

    @override
    def visit_alias(self, node: ast.alias) -> None:
        self._bind(node.asname or node.name.partition(".")[0])

    @override
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._bind(node.name)
        self.generic_visit(node)

    @override
    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        self._bind(node.name)
        self.generic_visit(node)

    @override
    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        self._bind(node.name)

    @override
    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        self._bind(node.rest)
        self.generic_visit(node)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node, node.name)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope(node, node.name)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope(node, node.name)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._scope(node, None)

    def _scope(self, node: ast.AST, name: str | None) -> None:
        """Visit a node that binds `name` where it stands and opens a scope of its own, where only `global` counts.

        A comprehension is not one here: the name of a `:=` inside it is bound outside it, and counting its loop's
        names too only leaves a constant unannotated.
        """
        self._bind(name)
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    def _bind(self, name: str | None) -> None:
        if name is not None and not self._depth:
            self.counts[name] += 1


def _candidate(statement: ast.stmt) -> str | None:
    """The name a module's statement assigns, when it reads as a constant to annotate.

    Returns:
        The name, or None for any other statement.
    """
    match statement:
        case ast.Assign(targets=[ast.Name(id=name)], value=value):
            annotation = None
        case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation, value=ast.expr() as value):
            pass
        case _:
            return None
    if not CONSTANT.fullmatch(name):
        return None
    if isinstance(annotation, ast.Subscript):
        annotation = annotation.value
    if annotation is not None and last_name(annotation) in _KEPT:
        return None
    if isinstance(value, ast.Call) and last_name(value.func) in STATEFUL | DECLARES:
        return None
    return name


def last_name(expression: ast.expr) -> str | None:
    """The last name of a dotted one: `getLogger` of `logging.getLogger`.

    Returns:
        The name, or None for an expression that is not a name.
    """
    match expression:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Constant(value=str(text)):
            # A quoted annotation, `"Final[int]"`.
            return re.split(r"[\[\s]", text.strip(), maxsplit=1)[0].rpartition(".")[2]
        case _:
            return None


def _final(small: cst.BaseSmallStatement, names: AbstractSet[str]) -> cst.BaseSmallStatement:
    """Annotate a statement `Final`, around the annotation it has, when it assigns one of `names`.

    Returns:
        The statement annotated, or as it was.
    """
    match small:
        case cst.AnnAssign(target=cst.Name(value=name), annotation=annotation) if name in names:
            wrapped = cst.Subscript(cst.Name("Final"), [cst.SubscriptElement(cst.Index(annotation.annotation))])
            return small.with_changes(annotation=annotation.with_changes(annotation=wrapped))
        case cst.Assign(targets=[cst.AssignTarget(target=cst.Name(value=name) as target)]) if name in names:
            return cst.AnnAssign(target, cst.Annotation(cst.Name("Final")), small.value, semicolon=small.semicolon)
        case _:
            return small
