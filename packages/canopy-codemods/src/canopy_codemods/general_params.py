"""Widen a parameter annotated `list`, `dict`, `set`, or `frozenset` that its function only reads to the abstract type.

A parameter takes the most general type its body needs (AGENTS.md, Code conventions), so a caller may pass a tuple, a
frozenset, or a mapping proxy. Here `def total(costs: list[float])` whose body only sums over `costs` once becomes
`def total(costs: Iterable[float])`. Each use of the parameter in the body says what it needs:

- one pass, by a `for`, a comprehension, a `", ".join`, or a builtin known to iterate its argument once and keep
  nothing of it (`sum`, `sorted`, `any`, `all`, `tuple`, `list`, `set`, `frozenset`, `dict`, `enumerate`, `zip`,
  `min`, `max`): `Iterable`;
- `len`, `in`, a test of its truth, or more than one pass, a loop inside a loop among them: `Collection`;
- indexing, slicing, `reversed`, `.index`, or `.count` of a `list`: `Sequence`;
- any of these of a `dict`, or `[]`, `.get`, `.items`, `.keys`, or `.values`: `Mapping`;
- `in` on a `set` or `frozenset`: `AbstractSet` (`collections.abc.Set`), never `Collection`, which would also take a
  bare `str`, where `in` is a substring test.

It is deliberately narrow, since a wrong widening fails the type checker at a call site or an override. It leaves alone:

- a parameter used in any other way: mutated, stored, returned, yielded, compared, formatted, unpacked, or passed to
  any other call (`json.dumps` and `isinstance` among them), whose needs it cannot see, or to a builtin's name the
  module binds anywhere, which is then no builtin;
- a parameter its function binds again, or that a nested function, lambda, or class names;
- a parameter its function never reads, which says nothing of what it needs, and one whose function returns the very
  type it is annotated with;
- every parameter of a function with a decorator other than `staticmethod`, `classmethod`, a context manager's, or
  pytest's: a click command, an overload, an override, and a route whose framework reads its annotations at run time;
- a method of a class with a base other than `object`, which may override or implement one declared elsewhere, or a
  protocol's, which its implementations must match, and one of a class the module derives another from, whose
  override may keep the concrete type; a method under an `if` or `try` in a class body is a method still;
- an annotation spelled any other way: quoted, a union, or a bare `list`.

The abstract type is imported from `collections.abc`: under the module's `if TYPE_CHECKING:` block when it has one
(on lines of its own) and postpones its annotations, else among the module's own imports; an import inside a
function, or under `TYPE_CHECKING` where annotations are read as the program runs, does not serve. A module that binds
the name otherwise anywhere, such as `Sequence` from `typing` or a class's `Mapping` attribute, keeps its parameters
of that type as they are.

Which parameters to widen is decided from the stdlib's syntax tree, and only for a module whose text subscripts one of
the four types, so a module with none to widen is never parsed by libcst (`Command.wants`).
"""

from __future__ import annotations

import ast
import re
from enum import Enum, auto
from typing import TYPE_CHECKING, Final, TypeGuard, override

import libcst as cst
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import CodeRange, PositionProvider

from canopy_codemods.command import Command
from canopy_codemods.final_constants import last_name

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from collections.abc import Set as AbstractSet

    from libcst.codemod import CodemodContext

#: What the text of a module with a parameter to widen must hold: one of the concrete types subscripted.
SUBSCRIPTED: Final = re.compile(r"\b(?:list|dict|set|frozenset)\[")
#: The concrete types a parameter is widened from.
CONCRETE: Final = frozenset({"dict", "frozenset", "list", "set"})
#: The builtins that read their first argument by iterating it once, and keep nothing of it but its items.
ITERATING: Final = frozenset({"all", "any", "dict", "enumerate", "frozenset", "list", "set", "sorted", "sum", "tuple"})
#: The decorators that leave a function's parameters as its callers see them, by their dotted names.
PLAIN: Final = frozenset(
    {
        "asynccontextmanager",
        "classmethod",
        "contextlib.asynccontextmanager",
        "contextlib.contextmanager",
        "contextmanager",
        "pytest.fixture",
        "staticmethod",
    },
)
#: Each abstract type, by the name a module calls it, and the name `collections.abc` gives it.
ABSTRACT: Final[Mapping[str, str]] = {
    "AbstractSet": "Set",
    "Collection": "Collection",
    "Iterable": "Iterable",
    "Mapping": "Mapping",
    "Sequence": "Sequence",
}
#: Where the abstract types are imported from.
_ABC: Final = "collections.abc"


class GeneralParams(Command):
    """Widen each parameter annotated with a concrete collection that its function only reads."""

    DESCRIPTION = "Widen a `list`, `dict`, `set`, or `frozenset` parameter only read to the abstract type it needs."
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, context: CodemodContext) -> None:
        """Start with no parameter to widen."""
        super().__init__(context)
        #: The parameters to widen in the module being rewritten, as `widened` finds them.
        self._found: Mapping[tuple[int, str], str] = {}

    @classmethod
    @override
    def wants(cls, source: str) -> bool:
        """Whether a module with this text has a parameter to widen.

        Returns:
            True when it has one, or may have one and does not parse, which is then libcst's to report.
        """
        if not SUBSCRIPTED.search(source):
            return False
        try:
            return bool(widened(source))
        except SyntaxError:
            return True

    @override
    def transform_module_impl(self, tree: cst.Module) -> cst.Module:
        """Widen the module's parameters, and import each abstract type it used.

        Returns:
            The module rewritten, or as it was when it has no parameter to widen.
        """
        found = widened(tree.code)
        if not found:
            return tree
        self._found = found
        rewritten = tree.visit(self)
        module = ast.parse(tree.code)
        postponed = _postponed(module)
        needed = sorted(set(found.values()) - _available(module, postponed=postponed))
        if not needed:
            return rewritten
        if postponed and (block := _type_checking(rewritten)) is not None:
            body = [_with_imports(block, needed) if statement is block else statement for statement in rewritten.body]
            return rewritten.with_changes(body=body)
        for name in needed:
            asname = None if ABSTRACT[name] == name else name
            AddImportsVisitor.add_needed_import(self.context, _ABC, ABSTRACT[name], asname)
        return AddImportsVisitor(self.context).transform_module(rewritten)

    @override
    def leave_Param(self, original_node: cst.Param, updated_node: cst.Param) -> cst.Param:
        """Write the abstract type in a parameter's annotation, when it is one to widen.

        Returns:
            The parameter rewritten, or as it was.
        """
        position = self.get_metadata(PositionProvider, original_node.name, None)
        line = position.start.line if isinstance(position, CodeRange) else None
        abstract = self._found.get((line, original_node.name.value)) if line is not None else None
        annotation = updated_node.annotation
        if abstract is None or annotation is None or not isinstance(annotation.annotation, cst.Subscript):
            return updated_node
        head = annotation.annotation.with_changes(value=cst.Name(abstract))
        return updated_node.with_changes(annotation=annotation.with_changes(annotation=head))


def widened(source: str) -> dict[tuple[int, str], str]:
    """The parameters of a module to widen, and the abstract type each takes, from its text.

    Returns:
        Each parameter's abstract type, by the line the parameter's name is on and that name.

    Raises:
        SyntaxError: When the text is not Python.
    """
    module = ast.parse(source)
    parents = {child: node for node in ast.walk(module) for child in ast.iter_child_nodes(node)}
    bound = _bound_anywhere(module)
    subclassed = _subclassed(module)
    found: dict[tuple[int, str], str] = {}
    for function in ast.walk(module):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not _plain(function, parents, subclassed):
            continue
        for argument in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]:
            abstract = _abstract(function, argument, parents, bound)
            if abstract is not None and abstract not in bound:
                found[argument.lineno, argument.arg] = abstract
    return found


class _Read(Enum):
    """How a function reads a parameter in one place, which says what the parameter's type must allow."""

    #: Iterated once: the iterable of a `for` or of a comprehension's first loop, or the argument of a builtin.
    PASS = auto()
    #: Iterated where it may be iterated again: in a loop, or in a comprehension past its first loop's iterable.
    PASSES = auto()
    #: Measured: `len`, or a test of its truth.
    SIZED = auto()
    #: Searched: the right operand of `in` or `not in`.
    CONTAINS = auto()
    #: Subscripted: `p[i]` of a list, `p[k]` of a dict.
    SUBSCRIPT = auto()
    #: In order: sliced, `reversed`, or its `.index` or `.count` called.
    ORDERED = auto()
    #: A dict's `.get`, `.items`, `.keys`, or `.values` called.
    LOOKUP = auto()


#: The reads each concrete type allows, beside a pass, a measure, and `in`, which every one allows.
_ALLOWED: Final[Mapping[str, frozenset[_Read]]] = {
    "dict": frozenset({_Read.SUBSCRIPT, _Read.LOOKUP}),
    "frozenset": frozenset(),
    "list": frozenset({_Read.SUBSCRIPT, _Read.ORDERED}),
    "set": frozenset(),
}
#: The methods of a list and of a dict that only read it.
_METHODS: Final[Mapping[str, _Read]] = {
    "count": _Read.ORDERED,
    "get": _Read.LOOKUP,
    "index": _Read.ORDERED,
    "items": _Read.LOOKUP,
    "keys": _Read.LOOKUP,
    "values": _Read.LOOKUP,
}


def _bound_anywhere(module: ast.Module) -> frozenset[str]:
    """Every name the module binds in any scope, but an abstract type imported from `collections.abc` as itself.

    A name bound anywhere is taken as bound everywhere: an abstract type bound so, such as a class's `Mapping`
    attribute, is no parameter's type, and a builtin bound so, such as `sorted` imported from elsewhere, is no read.

    Returns:
        The names.
    """
    found: set[str] = set()
    for node in ast.walk(module):
        match node:
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()) | ast.arg(arg=name):
                found.add(name)
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                found.add(name)
            case ast.ExceptHandler(name=str(name)) | ast.MatchAs(name=str(name)) | ast.MatchStar(name=str(name)):
                found.add(name)
            case ast.MatchMapping(rest=str(name)):
                found.add(name)
            case ast.Global(names=names) | ast.Nonlocal(names=names):
                found.update(names)
            case ast.Import(names=aliases):
                found.update(alias.asname or alias.name.partition(".")[0] for alias in aliases)
            case ast.ImportFrom(names=aliases):
                found.update(alias.asname or alias.name for alias in aliases if not _abstract_import(node, alias))
            case _:
                pass
    return frozenset(found)


def _abstract_import(statement: ast.ImportFrom, alias: ast.alias) -> bool:
    """Whether an import is of an abstract type from `collections.abc`, under the name this codemod writes.

    Returns:
        True when it is.
    """
    return statement.module == _ABC and not statement.level and ABSTRACT.get(alias.asname or alias.name) == alias.name


def _available(module: ast.Module, *, postponed: bool) -> frozenset[str]:
    """The abstract types a module's annotations can name already: imported among its own statements.

    An import under `if TYPE_CHECKING:` counts only where the module postpones its annotations, so that nothing reads
    them as the program runs; one inside a function counts not at all.

    Returns:
        The names.
    """
    statements = [*module.body]
    if postponed:
        statements += [inner for statement in module.body if _checking_only(statement) for inner in statement.body]
    return frozenset(
        alias.asname or alias.name
        for statement in statements
        if isinstance(statement, ast.ImportFrom)
        for alias in statement.names
        if _abstract_import(statement, alias)
    )


def _checking_only(statement: ast.stmt) -> TypeGuard[ast.If]:
    """Whether a module's statement is its `if TYPE_CHECKING:` block.

    Returns:
        True for one.
    """
    match statement:
        case ast.If(test=ast.Name(id="TYPE_CHECKING") | ast.Attribute(attr="TYPE_CHECKING")):
            return True
        case _:
            return False


def _subclassed(module: ast.Module) -> frozenset[str]:
    """The names of the classes the module's own classes derive from, whose methods another class may override.

    Returns:
        The last name of each base.
    """
    return frozenset(
        name
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef)
        for base in node.bases
        # A generic base, `Base[int]`, names `Base` as its subscript's value.
        if (name := last_name(base.value if isinstance(base, ast.Subscript) else base)) is not None
    )


def _plain(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: Mapping[ast.AST, ast.AST],
    subclassed: AbstractSet[str],
) -> bool:
    """Whether a function's parameters are its own to widen: no decorator reads them, and no other class declares them.

    Args:
        function: The function.
        parents: Each node of the module's tree by the node it is in.
        subclassed: The names of the classes the module derives others from.

    Returns:
        True for a function with only plain decorators, outside a class or in one with no base but `object` that no
        class of the module derives from.
    """
    for decorator in function.decorator_list:
        name = _dotted(decorator.func if isinstance(decorator, ast.Call) else decorator)
        if name is None or not (name in PLAIN or name.startswith("pytest.mark.")):
            return False
    match _scope(function, parents):
        case ast.ClassDef(name=name, bases=bases, keywords=keywords):
            plain = all(isinstance(base, ast.Name) and base.id == "object" for base in bases)
            return plain and not keywords and name not in subclassed
        case _:
            return True


def _scope(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ast.AST | None:
    """The function, class, or module a node is defined in, through any `if`, `try`, `with`, or loop around it.

    Returns:
        The scope.
    """
    parent = parents.get(node)
    scopes = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    while parent is not None and not isinstance(parent, scopes):
        parent = parents.get(parent)
    return parent


def _dotted(expression: ast.expr) -> str | None:
    """The dotted name an expression spells: `pytest.mark.parametrize`.

    Returns:
        The name, or None for an expression that is not one.
    """
    match expression:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            head = _dotted(value)
            return None if head is None else f"{head}.{attr}"
        case _:
            return None


def _abstract(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    argument: ast.arg,
    parents: Mapping[ast.AST, ast.AST],
    bound: AbstractSet[str],
) -> str | None:
    """The abstract type a parameter takes, when its function only reads it.

    Args:
        function: The function.
        argument: One of its parameters.
        parents: Each node of the module's tree by the node it is in.
        bound: The names the module binds anywhere, so that a builtin of the same name is no read.

    Returns:
        The type's name, of `ABSTRACT`, or None for a parameter to leave as it is.
    """
    match argument.annotation:
        case ast.Subscript(value=ast.Name(id=head)) as annotation if head in CONCRETE:
            pass
        case _:
            return None
    if function.returns is not None and ast.dump(function.returns) == ast.dump(annotation):
        return None
    uses = _uses(function, argument.arg)
    if not uses:
        return None
    reads: list[_Read] = []
    for use in uses:
        read = _read(use, parents)
        if read is None or _shadowed(use, parents, bound):
            return None
        reads.append(_Read.PASSES if read is _Read.PASS and _repeated(use, function, parents) else read)
    return _choose(head, reads)


def _shadowed(use: ast.Name, parents: Mapping[ast.AST, ast.AST], bound: AbstractSet[str]) -> bool:
    """Whether a read is a call of a name the module binds, which is then no builtin: `sorted` imported from elsewhere.

    Returns:
        True when it is.
    """
    match parents[use]:
        case ast.Call(func=ast.Name(id=name)):
            return name in bound
        case _:
            return False


def _uses(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> Sequence[ast.Name] | None:
    """Where a function's body reads a name, when it reads it only in its own scope and never binds it again.

    Returns:
        The reads, or None when the body binds the name, or a function, lambda, or class inside it names it.
    """
    found: list[ast.Name] = []
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        match node:
            case ast.Name(id=read, ctx=ast.Load()) if read == name:
                found.append(node)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.Lambda() | ast.ClassDef():
                if _names(node, name):
                    return None
                continue
            case ast.Global(names=names) | ast.Nonlocal(names=names) if name in names:
                return None
            case _ if name in _bound(node):
                return None
            case _:
                pass
        stack.extend(ast.iter_child_nodes(node))
    return found


def _names(scope: ast.AST, name: str) -> bool:
    """Whether a nested function, lambda, or class names `name` anywhere: as itself, a parameter, or a read.

    Returns:
        True when it does.
    """
    return any(
        (isinstance(node, ast.Name) and node.id == name)
        or (isinstance(node, ast.arg) and node.arg == name)
        or (isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.name == name)
        for node in ast.walk(scope)
    )


def _bound(node: ast.AST) -> Collection[str]:
    """The names a node binds where it stands, other than by `global` and `nonlocal`.

    Returns:
        The names; none for a node that binds nothing.
    """
    match node:
        case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
            return (name,)
        case ast.ExceptHandler(name=str(name)) | ast.MatchAs(name=str(name)) | ast.MatchStar(name=str(name)):
            return (name,)
        case ast.MatchMapping(rest=str(name)):
            return (name,)
        case ast.alias(name=name, asname=asname):
            return (asname or name.partition(".")[0],)
        case _:
            return ()


def _read(use: ast.expr, parents: Mapping[ast.AST, ast.AST]) -> _Read | None:
    """What one read of a parameter needs of its type.

    Returns:
        The read, or None for a use this codemod does not know to be only a read.
    """
    parent = parents[use]
    match parent:
        case ast.For(iter=iterated) | ast.AsyncFor(iter=iterated) | ast.comprehension(iter=iterated) if iterated is use:
            return _Read.PASS
        case ast.Call():
            return _argument(parent, use)
        case ast.Compare(ops=ops, comparators=comparators) if any(c is use for c in comparators):
            index = next(i for i, comparator in enumerate(comparators) if comparator is use)
            last = index == len(ops) - 1
            return _Read.CONTAINS if last and isinstance(ops[index], ast.In | ast.NotIn) else None
        case ast.Subscript(value=value, slice=index, ctx=ast.Load()) if value is use:
            return _sliced(parent, parents) if isinstance(index, ast.Slice) else _Read.SUBSCRIPT
        case ast.Attribute(value=value, attr=attr) if value is use and attr in _METHODS:
            called = isinstance(call := parents.get(parent), ast.Call) and call.func is parent
            return _METHODS[attr] if called else None
        case _:
            return _Read.SIZED if _tested(use, parents) else None


def _sliced(subscript: ast.Subscript, parents: Mapping[ast.AST, ast.AST]) -> _Read | None:
    """What slicing a parameter needs of its type, when the slice is itself only read.

    Returns:
        An ordered read, or None when the slice is used in any other way: what it makes is a list no longer.
    """
    return _Read.ORDERED if _read(subscript, parents) is not None else None


def _argument(call: ast.Call, use: ast.expr) -> _Read | None:
    """What a call needs of a parameter it is given: only a builtin's, or `str.join`'s, is known.

    Returns:
        The read, or None for any other call, or the parameter given as other than the argument it reads.
    """
    match call:
        case ast.Call(func=ast.Name(id="len"), args=[argument], keywords=[]) if argument is use:
            return _Read.SIZED
        case ast.Call(func=ast.Name(id="reversed"), args=[argument], keywords=[]) if argument is use:
            return _Read.ORDERED
        case _:
            return _Read.PASS if _iterates(call, use) else None


def _iterates(call: ast.Call, use: ast.expr) -> bool:
    """Whether a call only iterates a parameter it is given, once: a builtin of `ITERATING`, `zip`, or a `str.join`.

    Returns:
        True when it does.
    """
    match call:
        case ast.Call(func=ast.Name(id=builtin), args=[argument, *_]) if builtin in ITERATING:
            return argument is use
        case ast.Call(func=ast.Name(id="min" | "max"), args=[argument]):
            return argument is use
        case ast.Call(func=ast.Name(id="zip"), args=arguments):
            return any(argument is use for argument in arguments)
        case ast.Call(func=ast.Attribute(value=ast.Constant(value=str()), attr="join"), args=[argument]):
            return argument is use
        case _:
            return False


def _tested(node: ast.expr, parents: Mapping[ast.AST, ast.AST]) -> bool:
    """Whether an expression's value is only tested for its truth: by `if`, `while`, `assert`, or `not`.

    A boolean operator counts only where its own value is tested, since `p or []` is `p` itself.

    Returns:
        True when it is.
    """
    parent = parents.get(node)
    match parent:
        case ast.If(test=test) | ast.While(test=test) | ast.IfExp(test=test) | ast.Assert(test=test):
            return test is node
        case ast.UnaryOp(op=ast.Not()):
            return True
        case ast.comprehension(ifs=ifs):
            return any(condition is node for condition in ifs)
        case ast.BoolOp():
            return _tested(parent, parents)
        case _:
            return False


def _repeated(
    use: ast.Name,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Whether a pass over a parameter may be made more than once in a call: inside a loop of its function.

    Returns:
        True when a loop or a comprehension encloses it other than by its first iterable.
    """
    below: ast.AST | None = None
    child: ast.AST = use
    while (parent := parents.get(child)) is not None and parent is not function:
        match parent:
            case ast.For(iter=iterated) | ast.AsyncFor(iter=iterated) if child is not iterated:
                return True
            case ast.While():
                return True
            case (
                ast.ListComp(generators=[first, *_])
                | ast.SetComp(generators=[first, *_])
                | ast.GeneratorExp(
                    generators=[first, *_],
                )
                | ast.DictComp(generators=[first, *_])
            ) if child is not first or below is not first.iter:
                return True
            case _:
                pass
        below, child = child, parent
    return False


def _choose(head: str, reads: Sequence[_Read]) -> str | None:
    """The most general type a concrete one can become, given every read of the parameter.

    Returns:
        The abstract type's name, or None when a read is not one the concrete type allows.
    """
    kinds = set(reads) - {_Read.PASS, _Read.PASSES, _Read.SIZED, _Read.CONTAINS}
    if not kinds <= _ALLOWED[head]:
        return None
    if head == "dict":
        return "Mapping"
    if kinds:
        return "Sequence"
    if _Read.CONTAINS in reads and head != "list":
        return "AbstractSet"
    return "Iterable" if list(reads) == [_Read.PASS] else "Collection"


def _postponed(module: ast.Module) -> bool:
    """Whether a module postpones its annotations, so that a name only they read may be imported for the checker alone.

    Returns:
        True when it imports `annotations` from `__future__`.
    """
    return any(
        isinstance(statement, ast.ImportFrom)
        and statement.module == "__future__"
        and any(alias.name == "annotations" for alias in statement.names)
        for statement in module.body
    )


def _type_checking(module: cst.Module) -> cst.If | None:
    """The module's own `if TYPE_CHECKING:` block on lines of its own, whose imports are for the type checker alone.

    Returns:
        The first such block among the module's statements, or None; a one-line suite is not one.
    """
    for statement in module.body:
        match statement:
            case cst.If(
                test=cst.Name(value="TYPE_CHECKING") | cst.Attribute(attr=cst.Name(value="TYPE_CHECKING")),
                body=cst.IndentedBlock(),
            ):
                return statement
            case _:
                pass
    return None


def _with_imports(block: cst.If, names: Sequence[str]) -> cst.If:
    """A `TYPE_CHECKING` block with an import of each abstract type named first in it; ruff then sorts it in.

    Returns:
        The block.
    """
    aliases = [
        cst.ImportAlias(cst.Name(ABSTRACT[name]), asname=None if ABSTRACT[name] == name else cst.AsName(cst.Name(name)))
        for name in names
    ]
    statement = cst.SimpleStatementLine(
        [cst.ImportFrom(module=cst.Attribute(cst.Name("collections"), cst.Name("abc")), names=aliases)],
    )
    return block.with_changes(body=block.body.with_changes(body=[statement, *block.body.body]))
