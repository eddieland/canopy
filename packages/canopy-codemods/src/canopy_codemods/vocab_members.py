"""Compare a status, kind, or phase with its `core/vocab.py` member, not with a bare string.

A member of a `StrEnum` is the string it holds, so `run.status == "running"` type-checks and works, and nothing catches
a bare string where canopy's code is meant to name the member. Here it becomes `run.status == RunStatus.RUNNING`, and
the vocabulary is imported for the module to run with.

It rewrites a string compared by `==`, `!=`, `in`, or `not in` (a tuple, list, or set of strings), or matched by a
`case`, when what it is compared with can be tied to one vocabulary without inferring a type:

- a name annotated with the vocabulary in the same function, as a parameter or an annotated assignment
  (`status: RunStatus`), or `self.name` in a method of a class that annotates the field so;
- an attribute of a name annotated with a row type of `core/records` in the same function (`run: records.Run`, so
  `run.status` is a `RunStatus`), where the row type's field holds the vocabulary;
- a name or attribute called `status`, `kind`, or `phase` compared with strings that one vocabulary alone holds, one
  whose name ends with the word (`*Status`, `*Kind`, `Phase`) and that the module imports already.

It leaves alone:

- a string several vocabularies hold, where nothing ties the comparison to one (`"running"`, `"done"`, `"failed"`);
- a name or field annotated with anything else, such as `str`, a `Literal`, or a union of vocabularies;
- a string no vocabulary holds, or one the tied vocabulary does not: it changes nothing and reports nothing;
- a string anywhere but a comparison: SQL clause text, a prompt, a log message, a dict key;
- every module but canopy's own, under `src/canopy` (`covers`): the tests assert on the string on purpose, and the
  other programs in the workspace import nothing from canopy.

A vocabulary the module imports only for the type checker is moved out of its `if TYPE_CHECKING:` block, since the
comparison reads it as the program runs. The vocabularies and the row types are read from canopy's source by the
stdlib's `ast`, never imported. Which strings to rewrite is decided from the stdlib's syntax tree of the module too, so
a module with none is never parsed by libcst (`Command.wants`).
"""

from __future__ import annotations

import ast
import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, override

import libcst as cst
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor

from canopy_codemods.command import Command
from canopy_codemods.final_constants import last_name

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence
    from collections.abc import Set as AbstractSet

#: canopy's package in the repository the codemods sit in, whose vocabularies and row types are read.
PACKAGE: Final = Path(__file__).resolve().parents[4] / "src" / "canopy"
#: The module that holds the vocabularies, as canopy imports it.
VOCAB: Final = "canopy.core.vocab"
#: The package that holds the row types, as canopy imports it.
RECORDS: Final = "canopy.core.records"
#: The names a vocabulary's column goes by, each with how its vocabularies' names end: a `status` is a `*Status`.
WORDS: Final[Mapping[str, str]] = {"status": "Status", "kind": "Kind", "phase": "Phase"}

#: A function's, a lambda's, or a comprehension's node, each of which opens a scope.
type _Scoped = (
    ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp
)


class VocabMembers(Command):
    """Compare a status, kind, or phase with its vocabulary's member, not with a bare string."""

    DESCRIPTION = "Compare a status, kind, or phase with its `core/vocab.py` member, not with a bare string."

    @classmethod
    @override
    def covers(cls, filename: str | None) -> bool:
        """Whether a file is one of canopy's own modules, under `src/canopy`, other than the vocabularies.

        Returns:
            True for one of canopy's modules, or for text with no file.
        """
        if filename is None:
            return True
        # Anchored to this repository's package, not to a `src/canopy` anywhere in the path: a clone at `~/src/canopy`
        # would otherwise cover its tests and other programs too.
        path = Path(filename).resolve()
        return PACKAGE in path.parents and path != PACKAGE / "core" / "vocab.py"

    @classmethod
    @override
    def wants(cls, source: str) -> bool:
        """Whether a module with this text has a string to rewrite as a vocabulary's member.

        Returns:
            True when it has one, or may have one and does not parse, which is then libcst's to report.
        """
        found = vocabularies()
        if found is None or "canopy.core" not in source or found.compared.search(source) is None:
            return False
        try:
            return bool(rewrites(source).strings)
        except SyntaxError:
            return True

    @override
    def transform_module_impl(self, tree: cst.Module) -> cst.Module:
        """Rewrite the module's strings that are a vocabulary's member, and import each vocabulary it then names.

        Returns:
            The module rewritten, or as it was when it has no string to rewrite.
        """
        found = rewrites(tree.code)
        if not found.strings:
            return tree
        tree = cst.parse_module(_edit(tree.code, found.strings), tree.config_for_parsing)
        if found.unhidden:
            tree = tree.visit(_Unhide(found.unhidden))
            RemoveImportsVisitor.remove_unused_import(self.context, "typing", "TYPE_CHECKING")
        for name in sorted(found.imported):
            AddImportsVisitor.add_needed_import(self.context, VOCAB, name)
        return tree


@dataclass(frozen=True)
class Rewrites:
    """What a module's rewrite is: the strings to name as members, and the imports that then need."""

    #: Each string to rewrite, with the expression that names its member, in the module's order.
    strings: Sequence[tuple[ast.expr, str]]
    #: The vocabularies to import by name at run time.
    imported: AbstractSet[str]
    #: Those of them the module imports only for the type checker now, to take out of its `if TYPE_CHECKING:` block.
    unhidden: AbstractSet[str]


def rewrites(source: str) -> Rewrites:
    """Find a module's strings to rewrite as a vocabulary's member, from its text.

    Returns:
        The strings, and the imports they need; none when canopy's vocabularies cannot be read.

    Raises:
        SyntaxError: When the text is not Python.
    """
    module = ast.parse(source)
    found = vocabularies()
    if found is None:
        return Rewrites((), frozenset(), frozenset())
    imports = Imports.of(module)
    finder = _Finder(found, row_types(), imports)
    finder.visit(module)
    strings = sorted(finder.strings, key=lambda found: (found[0].lineno, found[0].col_offset))
    unhidden = {name for name in finder.imported if name in imports.vocabularies}
    return Rewrites(strings, frozenset(finder.imported), frozenset(unhidden))


@dataclass(frozen=True)
class Vocabularies:
    """canopy's closed vocabularies, as `core/vocab.py` spells them."""

    #: Each vocabulary's members, by its name: each value to its member's name.
    members: Mapping[str, Mapping[str, str]]
    #: Each value, to the names of the vocabularies that hold it.
    holders: Mapping[str, AbstractSet[str]]
    #: Matches a quoted value of any vocabulary written where a comparison or a `case` reads it.
    compared: re.Pattern[str]


@functools.cache
def vocabularies(package: Path = PACKAGE) -> Vocabularies | None:
    """Read canopy's vocabularies from its source: each `StrEnum` of `core/vocab.py`.

    Args:
        package: canopy's package directory.

    Returns:
        The vocabularies, or None when the module cannot be read.
    """
    try:
        module = ast.parse((package / "core" / "vocab.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    members = {
        statement.name: _members(statement)
        for statement in module.body
        if isinstance(statement, ast.ClassDef) and any(last_name(base) == "StrEnum" for base in statement.bases)
    }
    holders: dict[str, set[str]] = {}
    for name, values in members.items():
        for value in values:
            holders.setdefault(value, set()).add(name)
    quoted = "|".join(re.escape(value) for value in sorted(holders, key=len, reverse=True))
    value = rf"""["'](?:{quoted})["']"""
    compared = re.compile(rf"(?:[=!]=|\bin\b|\bcase\b)[\s(\[{{|,]*{value}|{value}\s*[=!]=")
    return Vocabularies(members, {value: frozenset(names) for value, names in holders.items()}, compared)


@functools.cache
def row_types(package: Path = PACKAGE) -> Mapping[str, Mapping[str, str]]:
    """Read which fields of canopy's row types hold a vocabulary, from each module of `core/records`.

    Args:
        package: canopy's package directory.

    Returns:
        Each row type with such a field, by its name: each such field to its vocabulary's name.
    """
    found = vocabularies(package)
    if found is None:
        return {}
    rows: dict[str, Mapping[str, str]] = {}
    for path in sorted((package / "core" / "records").glob("*.py")):
        try:
            module = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for statement in module.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            fields = {
                line.target.id: name
                for line in statement.body
                if isinstance(line, ast.AnnAssign)
                and isinstance(line.target, ast.Name)
                and (name := last_name(_optional(line.annotation))) is not None
                and name in found.members
            }
            if fields:
                rows[statement.name] = fields
    return rows


@dataclass(frozen=True)
class Imports:
    """What a module imports from canopy's vocabularies and row types, among its own statements."""

    #: Each vocabulary imported by its own name, to whether the import is at run time, not only for the type checker.
    vocabularies: Mapping[str, bool]
    #: Whether the module imports the vocabularies' module, `vocab`, at run time.
    vocab_module: bool
    #: Whether it imports `vocab` at all, at run time or only for the type checker.
    vocab_annotations: bool
    #: Whether it imports the row types' package, `records`.
    records_module: bool
    #: The row types it imports by their own names.
    rows: AbstractSet[str]
    #: Every other name an import binds, which a vocabulary's name must not be.
    others: AbstractSet[str]

    @classmethod
    def of(cls, module: ast.Module) -> Imports:
        """Read a module's imports: its own, and those in an `if TYPE_CHECKING:` block among them.

        Returns:
            What it imports.
        """
        vocabularies: dict[str, bool] = {}
        modules: dict[str, bool] = {}
        rows: set[str] = set()
        others: set[str] = set()
        for statement, runtime in _imports(module):
            source = None if statement.level else statement.module
            for alias in statement.names:
                if alias.asname is not None:
                    others.add(alias.asname)
                elif source == VOCAB:
                    vocabularies[alias.name] = vocabularies.get(alias.name, False) or runtime
                elif source == "canopy.core" and alias.name in {"vocab", "records"}:
                    modules[alias.name] = modules.get(alias.name, False) or runtime
                elif source is not None and (source == RECORDS or source.startswith(f"{RECORDS}.")):
                    rows.add(alias.name)
                else:
                    others.add(alias.name)
        return cls(
            vocabularies=vocabularies,
            vocab_module=modules.get("vocab", False),
            vocab_annotations="vocab" in modules,
            records_module="records" in modules,
            rows=frozenset(rows),
            others=frozenset(others),
        )


@dataclass(frozen=True)
class _Typed:
    """What an annotation says a name holds: a vocabulary's member, a row of a table, or neither."""

    #: The vocabulary's name, when it holds one's member.
    vocabulary: str | None = None
    #: The row type's name, when it holds a row.
    row: str | None = None


@dataclass(frozen=True)
class _Scope:
    """A scope the finder is in: a function's, a lambda's, a comprehension's, or a class body's."""

    #: The names the scope binds: each to what its annotation says, or to None when it has none.
    names: Mapping[str, _Typed | None]
    #: The fields of the class `self` is an instance of, when the scope is in a method; None elsewhere.
    fields: Mapping[str, _Typed] | None
    #: Whether it is a class body, whose names a function in it does not see.
    is_class: bool = False


@dataclass
class _Finder(ast.NodeVisitor):
    """Finds each string compared with something it can tie to one vocabulary that holds the string."""

    found: Vocabularies
    rows: Mapping[str, Mapping[str, str]]
    imports: Imports
    #: Each string to rewrite, with the expression that names its member.
    strings: list[tuple[ast.expr, str]] = field(default_factory=list[tuple[ast.expr, str]])
    #: The vocabularies the rewritten module names that it must import by name at run time.
    imported: set[str] = field(default_factory=set[str])
    #: The scopes the node being visited is in, innermost last.
    scopes: list[_Scope] = field(default_factory=list[_Scope])

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        fields = {
            line.target.id: self._typed(line.annotation)
            for line in node.body
            if isinstance(line, ast.AnnAssign) and isinstance(line.target, ast.Name)
        }
        self.scopes.append(_Scope({}, fields, is_class=True))
        self.generic_visit(node)
        self.scopes.pop()

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._scoped(node, dict.fromkeys(_parameters(node.args)))

    @override
    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._scoped(node, dict.fromkeys(_comprehension_names(node.generators)))

    @override
    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._scoped(node, dict.fromkeys(_comprehension_names(node.generators)))

    @override
    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._scoped(node, dict.fromkeys(_comprehension_names(node.generators)))

    @override
    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._scoped(node, dict.fromkeys(_comprehension_names(node.generators)))

    @override
    def visit_Compare(self, node: ast.Compare) -> None:
        match node:
            case ast.Compare(left=left, ops=[ast.Eq() | ast.NotEq()], comparators=[right]):
                if _string(right) is not None and _string(left) is None:
                    self._compared(left, [right])
                elif _string(left) is not None and _string(right) is None:
                    self._compared(right, [left])
            case ast.Compare(
                left=left,
                ops=[ast.In() | ast.NotIn()],
                comparators=[ast.Tuple(elts=elements) | ast.List(elts=elements) | ast.Set(elts=elements)],
            ):
                strings = [element for element in elements if _string(element) is not None]
                if elements and _string(left) is None and len(strings) == len(elements):
                    self._compared(left, strings)
            case _:
                pass
        self.generic_visit(node)

    @override
    def visit_Match(self, node: ast.Match) -> None:
        strings = [string for case in node.cases for string in _matched(case.pattern)]
        if strings:
            self._compared(node.subject, strings)
        self.generic_visit(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Visit a function in a scope of its own, which binds its parameters and the names its body binds."""
        arguments = node.args
        names: dict[str, _Typed | None] = dict.fromkeys(_parameters(arguments))
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
            if argument.annotation is not None:
                names[argument.arg] = self._typed(argument.annotation)
        bound = _Bound()
        for statement in node.body:
            bound.visit(statement)
        names.update({name: self._typed(annotation) for name, annotation in bound.annotated.items()})
        for name in bound.assigned:
            names.setdefault(name, None)
        self._scoped(node, names)

    def _scoped(self, node: _Scoped, names: Mapping[str, _Typed | None]) -> None:
        """Visit a node inside a scope that binds `names`."""
        self.scopes.append(self._scope(names))
        self.generic_visit(node)
        self.scopes.pop()

    def _scope(self, names: Mapping[str, _Typed | None]) -> _Scope:
        """A function's, a lambda's, or a comprehension's scope, which binds `names`; `self` stays as it was.

        Returns:
            The scope.
        """
        return _Scope(names, self.scopes[-1].fields if self.scopes else None)

    def _compared(self, subject: ast.expr, strings: Sequence[ast.expr]) -> None:
        """Rewrite the strings compared with `subject` when it is tied to one vocabulary that holds each of them."""
        values = [text for string in strings if (text := _string(string)) is not None]
        vocabulary = self._vocabulary(subject, values)
        if vocabulary is None or vocabulary in self.imports.others:
            return
        members = self.found.members[vocabulary]
        if any(value not in members for value in values):
            return
        owner = vocabulary
        if vocabulary not in self.imports.vocabularies and self.imports.vocab_module:
            owner = f"vocab.{vocabulary}"
        elif not self.imports.vocabularies.get(vocabulary):
            # Imported for the type checker alone, or not at all: the comparison reads it as the program runs.
            self.imported.add(vocabulary)
        self.strings.extend(
            (string, f"{owner}.{members[value]}") for string, value in zip(strings, values, strict=True)
        )

    def _vocabulary(self, subject: ast.expr, values: Sequence[str]) -> str | None:
        """The one vocabulary the subject of a comparison with `values` holds, by the rules the module states.

        Returns:
            The vocabulary's name, or None when nothing ties the subject to one.
        """
        match subject:
            case ast.Name(id=name) if (typed := self._lookup(name)) is not None:
                return typed.vocabulary
            case ast.Attribute(value=ast.Name(id="self"), attr=name) if (
                self.scopes and (fields := self.scopes[-1].fields) is not None and name in fields
            ):
                return fields[name].vocabulary
            case ast.Attribute(value=ast.Name(id=base), attr=name) if (
                typed := self._lookup(base)
            ) is not None and typed.row is not None:
                return self.rows[typed.row].get(name)
            case ast.Name(id=word) | ast.Attribute(attr=word):
                return self._called(word, values)
            case _:
                return None

    def _called(self, word: str, values: Sequence[str]) -> str | None:
        """The one vocabulary a name or attribute called `word`, and compared with `values`, holds, by its name alone.

        Returns:
            The only vocabulary that holds every value, when the module imports it and its name ends with the word
            (`status`, a `*Status`); None otherwise.
        """
        if word not in WORDS:
            return None
        holders = set(self.found.members)
        for value in values:
            holders &= self.found.holders.get(value, frozenset())
        only = holders.pop() if len(holders) == 1 else ""
        return only if only.endswith(WORDS[word]) and only in self.imports.vocabularies else None

    def _lookup(self, name: str) -> _Typed | None:
        """What the scopes the finder is in say a name holds: the innermost that binds it, past class bodies.

        Returns:
            What its annotation says, or None when no scope annotates it.
        """
        for scope in reversed(self.scopes):
            if not scope.is_class and name in scope.names:
                return scope.names[name]
        return None

    def _typed(self, annotation: ast.expr) -> _Typed:
        """Read what an annotation says a name holds, by the module's imports.

        Returns:
            The vocabulary or the row type it names, or neither.
        """
        match _optional(annotation):
            case ast.Name(id=name) if name in self.imports.vocabularies and name in self.found.members:
                return _Typed(vocabulary=name)
            case ast.Name(id=name) if name in self.imports.rows and name in self.rows:
                return _Typed(row=name)
            case ast.Attribute(value=ast.Name(id="vocab"), attr=name) if (
                self.imports.vocab_annotations and name in self.found.members
            ):
                return _Typed(vocabulary=name)
            case ast.Attribute(value=ast.Name(id="records"), attr=name) if (
                self.imports.records_module and name in self.rows
            ):
                return _Typed(row=name)
            case _:
                return _Typed()


class _Bound(ast.NodeVisitor):
    """Collects the names a function's body binds in its own scope, those annotated with their annotations."""

    def __init__(self) -> None:
        """Start with no name bound."""
        #: Each name the body annotates, with the annotation.
        self.annotated: dict[str, ast.expr] = {}
        #: Each name it binds any other way: an assignment, a loop, a `with`, an import, a nested definition.
        self.assigned: set[str] = set()

    @override
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.annotated[node.target.id] = node.annotation
        self.generic_visit(node)

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            self.assigned.add(node.id)

    @override
    def visit_alias(self, node: ast.alias) -> None:
        self.assigned.add(node.asname or node.name.partition(".")[0])

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
    def visit_Global(self, node: ast.Global) -> None:
        self.assigned.update(node.names)

    @override
    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.assigned.update(node.names)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.assigned.add(node.name)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.assigned.add(node.name)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.assigned.add(node.name)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def _bind(self, name: str | None) -> None:
        if name is not None:
            self.assigned.add(name)


class _Unhide(cst.CSTTransformer):
    """Takes the vocabularies a module now reads at run time out of the imports of its `if TYPE_CHECKING:` blocks."""

    def __init__(self, names: AbstractSet[str]) -> None:
        super().__init__()
        self._names = names

    @override
    def leave_If(self, original_node: cst.If, updated_node: cst.If) -> cst.If | cst.RemovalSentinel:
        if not _is_type_checking(updated_node.test) or not isinstance(updated_node.body, cst.IndentedBlock):
            return updated_node
        body = [kept for line in updated_node.body.body if (kept := self._kept(line)) is not None]
        if not body:
            return cst.RemoveFromParent() if updated_node.orelse is None else updated_node
        return updated_node.with_changes(body=updated_node.body.with_changes(body=body))

    def _kept(self, line: cst.BaseStatement) -> cst.BaseStatement | None:
        """A line of the block without the vocabularies to take out of it, when it imports them.

        Returns:
            The line, or None when it imported nothing else.
        """
        match line:
            case cst.SimpleStatementLine(body=[cst.ImportFrom(module=module, names=[*aliases]) as statement]) if (
                module is not None and _dotted(module) == VOCAB
            ):
                kept = [
                    alias for alias in aliases if alias.asname is not None or _dotted(alias.name) not in self._names
                ]
                if not kept:
                    return None
                kept[-1] = kept[-1].with_changes(comma=aliases[-1].comma)
                return line.with_changes(body=[statement.with_changes(names=kept)])
            case _:
                return line


def _edit(source: str, strings: Iterable[tuple[ast.expr, str]]) -> str:
    """Replace each string in a module's text with what names its member.

    Args:
        source: The module's text.
        strings: Each string, by where the syntax tree puts it, in the module's order, and its replacement.

    Returns:
        The text rewritten.
    """
    text = source.encode()
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    pieces: list[bytes] = []
    done = 0
    for string, replacement in strings:
        if string.end_lineno is None or string.end_col_offset is None:
            continue
        # The syntax tree counts columns in UTF-8 bytes.
        start = starts[string.lineno - 1] + string.col_offset
        pieces += [text[done:start], replacement.encode()]
        done = starts[string.end_lineno - 1] + string.end_col_offset
    pieces.append(text[done:])
    return b"".join(pieces).decode()


def _members(vocabulary: ast.ClassDef) -> Mapping[str, str]:
    """A vocabulary's members, from its class statement.

    Returns:
        Each value it holds, to its member's name.
    """
    return {
        member.value.value: target.id
        for member in vocabulary.body
        if isinstance(member, ast.Assign) and isinstance(member.value, ast.Constant)
        for target in member.targets[:1]
        if isinstance(target, ast.Name) and isinstance(member.value.value, str)
    }


def _imports(module: ast.Module) -> Iterator[tuple[ast.ImportFrom, bool]]:
    """The module's own `from` imports, and those in its `if TYPE_CHECKING:` blocks.

    Yields:
        Each import, and whether it is made at run time.
    """
    for statement in module.body:
        match statement:
            case ast.ImportFrom():
                yield statement, True
            case ast.If(test=ast.Name(id="TYPE_CHECKING") | ast.Attribute(attr="TYPE_CHECKING"), body=body):
                yield from ((line, False) for line in body if isinstance(line, ast.ImportFrom))
            case _:
                pass


def _optional(annotation: ast.expr) -> ast.expr:
    """An annotation without the `| None` it may end with, or open with.

    Returns:
        What it is optional of, or itself.
    """
    match annotation:
        case ast.BinOp(left=inner, op=ast.BitOr(), right=ast.Constant(value=None)):
            return inner
        case ast.BinOp(left=ast.Constant(value=None), op=ast.BitOr(), right=inner):
            return inner
        case _:
            return annotation


def _string(node: ast.expr) -> str | None:
    """The text of a string literal.

    Returns:
        The text, or None for any other expression.
    """
    match node:
        case ast.Constant(value=str(text)):
            return text
        case _:
            return None


def _parameters(arguments: ast.arguments) -> Iterator[str]:
    """The names a function's or a lambda's parameters bind.

    Yields:
        Each name.
    """
    for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
        yield argument.arg
    for star in (arguments.vararg, arguments.kwarg):
        if star is not None:
            yield star.arg


def _comprehension_names(generators: Iterable[ast.comprehension]) -> Iterator[str]:
    """The names a comprehension's `for` clauses bind.

    Yields:
        Each name.
    """
    for generator in generators:
        yield from (node.id for node in ast.walk(generator.target) if isinstance(node, ast.Name))


def _matched(pattern: ast.pattern) -> Iterator[ast.Constant]:
    """The strings a `case` pattern matches directly: alone, as one of several (`|`), or under `as`.

    Yields:
        Each string's node.
    """
    match pattern:
        case ast.MatchValue(value=ast.Constant(value=str()) as value):
            yield value
        case ast.MatchOr(patterns=patterns):
            for inner in patterns:
                yield from _matched(inner)
        case ast.MatchAs(pattern=ast.pattern() as inner):
            yield from _matched(inner)
        case _:
            pass


def _is_type_checking(test: cst.BaseExpression) -> bool:
    """Whether an `if` statement's test is `TYPE_CHECKING`, or `typing.TYPE_CHECKING`.

    Returns:
        True when it is.
    """
    match test:
        case cst.Name(value="TYPE_CHECKING") | cst.Attribute(attr=cst.Name(value="TYPE_CHECKING")):
            return True
        case _:
            return False


def _dotted(node: cst.BaseExpression) -> str | None:
    """The dotted name an expression spells: `canopy.core.vocab`.

    Returns:
        The name, or None for an expression that is no name.
    """
    match node:
        case cst.Name(value=name):
            return name
        case cst.Attribute(value=value, attr=cst.Name(value=name)):
            head = _dotted(value)
            return None if head is None else f"{head}.{name}"
        case _:
            return None
