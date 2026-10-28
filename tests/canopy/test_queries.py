"""Every query canopy runs is built with `core/sql.py` (D125), checked on every module in `src/canopy`.

No SQL run but through `sql.execute` and `sql.execute_many`, no fragment made but by that module, and no `noqa: S608`
left to vouch for SQL built some other way.
"""

import ast
from pathlib import Path
from typing import Final

PACKAGE: Final = Path(__file__).resolve().parents[2] / "src" / "canopy"
# The builder itself, which alone runs SQL on a connection and makes fragments.
BUILDER: Final = "core/sql.py"
# What runs SQL on a sqlite3 connection or cursor.
RUNS_SQL: Final = frozenset({"execute", "executemany", "executescript"})
# Calls that run SQL the builder does not make, with why: each is the only one of its kind.
EXEMPT: Final = {
    # The migrations are files of SQL, run whole as they shipped.
    ("core/db.py", "migrate", "executescript"),
    # The runtime's own database, not the journal, which the runtime's layer, below `core`, reads with its literal
    # queries and bound values alone (`canopy.runtime.opencode.sessions`).
    ("runtime/opencode/sessions.py", "read", "execute"),
}


def offences(source: str, module: str) -> list[str]:
    """What in `source`, the module at `module` under `src/canopy`, runs or makes SQL outside the builder."""
    if module == BUILDER:
        return []
    tree = ast.parse(source)
    found = [f"{module}:{n}: a `noqa: S608`" for n, line in enumerate(source.splitlines(), 1) if "S608" in line]
    modules = _canopy_modules(tree)
    for function, node in _calls(tree):
        callee = node.func
        if not isinstance(callee, ast.Attribute):
            if isinstance(callee, ast.Name) and callee.id == "Fragment":
                found.append(f"{module}:{node.lineno}: a Fragment made outside {BUILDER}")
            continue
        receiver = callee.value
        if callee.attr == "Fragment":
            found.append(f"{module}:{node.lineno}: a Fragment made outside {BUILDER}")
        elif callee.attr in RUNS_SQL:
            # `sql.execute`, and a function of another canopy module that is named so (`worker.execute`), run no SQL;
            # a name the module also binds itself, as a parameter or a variable, may be a connection, so it counts.
            if isinstance(receiver, ast.Name) and receiver.id in modules:
                continue
            if (module, function, callee.attr) in EXEMPT:
                continue
            found.append(f"{module}:{node.lineno}: `.{callee.attr}(...)` runs SQL outside the builder")
    found += [
        f"{module}:{node.lineno}: a `fragment` method outside {BUILDER} could render any text"
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "fragment"
    ]
    return found


def test_every_query_is_built_with_the_builder() -> None:
    found = [
        offence
        for path in sorted(PACKAGE.rglob("*.py"))
        for offence in offences(path.read_text(), path.relative_to(PACKAGE).as_posix())
    ]
    assert found == []


def test_sql_run_or_made_outside_the_builder_is_found() -> None:
    source = """
from canopy.core import sql
from canopy.runs import worker

def ok(conn, run_id):
    sql.execute(conn, sql.select("1"))
    worker.execute(conn, run_id)

def bad(conn, table):
    conn.execute(f"SELECT * FROM {table}")  # noqa: S608
    conn.cursor().executemany("INSERT INTO t VALUES (?)", [(1,)])
    sql.execute(conn, sql.Fragment("DROP TABLE ticks"))

class Sneaky:
    def fragment(self):
        return None
"""
    assert offences(source, "loop/sneaky.py") == [
        "loop/sneaky.py:10: a `noqa: S608`",
        "loop/sneaky.py:10: `.execute(...)` runs SQL outside the builder",
        "loop/sneaky.py:11: `.executemany(...)` runs SQL outside the builder",
        "loop/sneaky.py:12: a Fragment made outside core/sql.py",
        "loop/sneaky.py:15: a `fragment` method outside core/sql.py could render any text",
    ]


def test_a_connection_named_as_an_imported_module_is_still_found() -> None:
    source = """
import sqlite3 as db
from canopy.runs import worker
from json import tool

def shadowed(worker):
    worker.execute("DELETE FROM ticks")

def foreign(conn):
    db.connect(":memory:").execute("SELECT 1")
    tool.execute("SELECT 1")
"""
    assert offences(source, "loop/sneaky.py") == [
        "loop/sneaky.py:7: `.execute(...)` runs SQL outside the builder",
        "loop/sneaky.py:10: `.execute(...)` runs SQL outside the builder",
        "loop/sneaky.py:11: `.execute(...)` runs SQL outside the builder",
    ]


def _canopy_modules(tree: ast.Module) -> set[str]:
    """The names a module imports from canopy itself, less any it also binds, as a parameter or a variable."""
    names: set[str] = set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name for a in node.names if a.name.split(".")[0] == "canopy" and a.asname}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "canopy":
            names |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    return names - bound


def _calls(tree: ast.Module) -> list[tuple[str, ast.Call]]:
    """Each call, with the name of the function it is in, or "" at module level."""
    calls: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else function
            if isinstance(child, ast.Call):
                calls.append((function, child))
            visit(child, inner)

    visit(tree, "")
    return calls
