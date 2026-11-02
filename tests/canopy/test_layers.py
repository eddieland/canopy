"""The package layers of DESIGN §5 (D041), and rules of the same kind for the runtime and the tests.

The layers are checked on every import in `src/canopy`, `TYPE_CHECKING` ones included; the runtime is confined to its
implementation, behind the runtime package's surface (D009); and the tests have two rules of the same kind: a test
module imports from no other, and sits parallel to what it tests.
"""

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "canopy"
TESTS = Path(__file__).resolve().parents[1]
# The workspace members' packages (D041), each `packages/NAME/src/PACKAGE`.
MEMBERS = Path(__file__).resolve().parents[2] / "packages"

# Top to bottom. A module may import from its own package and from any package in a lower layer. It may not import
# from a higher layer or from another package in its own layer: features stay independent of each other, and code two
# of them share moves down a layer instead. The web UI's server sits above the features, as the loop and the command
# line do, so what only those read stays in the feature that owns it.
LAYERS: tuple[frozenset[str], ...] = (
    frozenset({"__main__"}),
    frozenset({"cli"}),
    frozenset({"loop"}),
    frozenset({"serve"}),
    frozenset({"runs", "setup", "chores", "notify", "reviews", "memory"}),
    frozenset({"core"}),
    frozenset({"runtime"}),
    frozenset({"infra"}),
)
# Third-party packages only one canopy package may import.
CONFINED = {
    "anyio": "serve",
    "click": "cli",
    "fastapi": "serve",
    # Every span goes through `infra/tracing.py` (D132).
    "opentelemetry": "infra",
    "starlette": "serve",
    "tomlkit": "serve",
    "uvicorn": "serve",
}
# The programs canopy ships besides `canopy`, each a command line of its own and so free to import click: the desktop
# sink and the development server.
PROGRAMS = frozenset({"notify/desktop.py", "serve/__main__.py"})
# Programs canopy ships as separate distributions and runs only as commands (D041): the Slack sink, the GitHub
# programs, and the Jira connector hold secrets and open connections, which the harness never does (DESIGN §20, §29,
# §30), and the local artifact store holds what workers publish, which stays out of the journal (§38). The review bench
# is a dev tool canopy never runs, which scores another reviewer through git and gh.
SEPARATE = frozenset(
    {"canopy_artifacts", "canopy_github", "canopy_jira", "canopy_notify_slack", "canopy_review_bench"},
)
# The HTTP stack those programs share (D130), and its transport: the harness opens no connection (TRUST_MODEL T2), as
# ruff's ban on the stdlib's network modules keeps it from doing with those.
NETWORK = frozenset({"canopy_http", "httpx2"})
# The package that alone knows the agent runtime (D009), and the name that must appear in no string outside it.
RUNTIME = "runtime"
RUNTIME_NAME = re.compile(r"opencode", re.IGNORECASE)
# Within it, the implementations that alone name the runtime, OpenCode 1's and OpenCode 2's, each its own and importing
# neither the other nor the surface; the one module that imports them; and the modules of what any runtime reports, the
# only others of the package an implementation may import.
IMPLEMENTATIONS = (PACKAGE / RUNTIME / "opencode", PACKAGE / RUNTIME / "opencode2")
BINDING = PACKAGE / RUNTIME / "implementation.py"
NEUTRAL = frozenset({"canopy.runtime.report", "canopy.runtime.entries", "canopy.runtime.agents"})
# The modules an implementation may take from another: OpenCode 2 reads OpenCode 1's agent format through its
# compatibility layer, so canopy's definitions, and how config is rendered into them, are one for both; and it keeps its
# sessions in the same database, read by the same reader with queries of its own.
SHARED = {
    "canopy.runtime.opencode2": frozenset({"canopy.runtime.opencode.definitions", "canopy.runtime.opencode.sessions"}),
}
# Modules outside it allowed to name the runtime, with why: none knows how it behaves.
NAMES_RUNTIME = {
    # The web UI's demo: its made-up pools' slots run the runtime's process, and its made-up runs' transcripts print
    # what the runtime prints, which the runtime package reads.
    "serve/mock/__init__.py",
    "serve/mock/transcripts.py",
    # Its made-up machine's processes are the runtime's too, as a running run's agent is.
    "serve/mock/host.py",
}


def layer_of(package: str) -> int:
    for i, layer in enumerate(LAYERS):
        if package in layer:
            return i
    raise AssertionError(f"canopy.{package} is in no layer; add it to LAYERS in {Path(__file__).name}")


def package_of(path: Path) -> str:
    return path.relative_to(PACKAGE).parts[0].removesuffix(".py")


def imported(tree: ast.Module) -> list[tuple[int, str]]:
    """Every module an import statement names, with its line: `from canopy import db` names `canopy.db`."""
    names: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module == "canopy":
            names.extend((node.lineno, f"canopy.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append((node.lineno, node.module))
    return names


def modules() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if p != PACKAGE / "__init__.py")


def under_tests(pattern: str) -> list[Path]:
    """Each file under `tests/` that matches `pattern`, but for the npm packages `tests/plugins` installs."""
    return sorted(p for p in TESTS.rglob(pattern) if "node_modules" not in p.relative_to(TESTS).parts)


def test_every_module_is_in_a_layered_package() -> None:
    assert modules()
    for path in modules():
        layer_of(package_of(path))


def violations(path: Path, source: str) -> list[str]:
    """What in `source`, the text of the module at `path`, breaks the layering."""
    own = package_of(path)
    where = path.relative_to(PACKAGE.parent)
    found: list[str] = []
    for line, name in imported(ast.parse(source, filename=str(path))):
        top, _, rest = name.partition(".")
        if top in SEPARATE:
            found.append(f"{where}:{line}: imports {name}, a separate program canopy runs only as a command")
        if top in NETWORK:
            found.append(f"{where}:{line}: imports {name}, which opens connections the harness never opens")
        program = top == "click" and path.relative_to(PACKAGE).as_posix() in PROGRAMS
        if top in CONFINED and CONFINED[top] != own and not program:
            found.append(f"{where}:{line}: imports {name}, which only canopy.{CONFINED[top]} may import")
        if top != "canopy" or not rest:
            continue
        target = rest.partition(".")[0]
        if target != own and layer_of(target) <= layer_of(own):
            found.append(f"{where}:{line}: canopy.{own} imports {name}, which is not in a lower layer")
    return found


def test_imports_go_down_the_layers() -> None:
    found = [v for path in modules() for v in violations(path, path.read_text())]
    assert not found, "\n".join(found)


def test_the_check_catches_upward_sideways_and_confined_imports() -> None:
    source = """
from typing import TYPE_CHECKING

import click

from canopy import cli
from canopy.core import db
from canopy.setup.init import run
import canopy_notify_slack
import httpx2

if TYPE_CHECKING:
    from canopy.loop.tick import Outcome
"""
    found = violations(PACKAGE / "runs" / "example.py", source)
    assert [v.split(": ", 1)[1] for v in found] == [
        "imports click, which only canopy.cli may import",
        "canopy.runs imports canopy.cli, which is not in a lower layer",
        "canopy.runs imports canopy.setup.init, which is not in a lower layer",
        "imports canopy_notify_slack, a separate program canopy runs only as a command",
        "imports httpx2, which opens connections the harness never opens",
        "canopy.runs imports canopy.loop.tick, which is not in a lower layer",
    ]


def test_only_an_implementation_names_the_runtime() -> None:
    """No string outside an implementation, `canopy.runtime.opencode` or `opencode2`, names OpenCode (D009).

    Not its commands, variables, files, or events. Not even the rest of `canopy.runtime`, whose surface is what a new
    runtime implements. A docstring or comment may still say why code is so; what the code acts on comes from the
    implementation.
    """
    found = [
        v
        for path in modules()
        if _implementation_of(path) is None and path.relative_to(PACKAGE).as_posix() not in NAMES_RUNTIME
        for v in naming_runtime(path, path.read_text())
    ]
    assert not found, "\n".join(found)


def test_only_the_binding_imports_an_implementation() -> None:
    """Only `canopy.runtime.implementation` imports an implementation, which imports only what any runtime reports.

    So the rest of canopy reaches the runtime through the surface alone, and a new runtime is bound in one place.
    """
    found = [v for path in modules() for v in implementation_imports(path, path.read_text())]
    assert not found, "\n".join(found)


def implementation_imports(path: Path, source: str) -> list[str]:
    """Each import in `source`, the text of the module at `path`, that crosses the implementation's boundary."""
    where = path.relative_to(PACKAGE.parent)
    own = _implementation_of(path)
    found: list[str] = []
    for line, name in imported_modules(ast.parse(source, filename=str(path))):
        into = next((i for i in IMPLEMENTATIONS if _within(name, i)), None)
        if into is not None and own is None and path != BINDING:
            found.append(f"{where}:{line}: imports {name}, which only {BINDING.relative_to(PACKAGE.parent)} may")
        elif own is not None and into is not None and into != own and name not in _shared_with(own):
            found.append(f"{where}:{line}: imports {name}, another implementation's, which this one may not")
        elif own is not None and into is None and name.startswith(f"canopy.{RUNTIME}") and name not in NEUTRAL:
            found.append(f"{where}:{line}: imports {name}, which the implementation may not: it is the surface's")
    return found


def _shared_with(implementation: Path) -> frozenset[str]:
    return SHARED.get(".".join(("canopy", *implementation.relative_to(PACKAGE).parts)), frozenset())


def _implementation_of(path: Path) -> Path | None:
    return next((i for i in IMPLEMENTATIONS if path.is_relative_to(i)), None)


# Whether module `name` is implementation `implementation` or one of its modules.
def _within(name: str, implementation: Path) -> bool:
    prefix = ".".join(("canopy", *implementation.relative_to(PACKAGE).parts))
    return name == prefix or name.startswith(f"{prefix}.")


def imported_modules(tree: ast.Module) -> list[tuple[int, str]]:
    """Every canopy module an import statement names, with its line.

    `from canopy.runtime import report` names `canopy.runtime.report`, where `imported` names the package it is
    imported from.
    """
    names: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                below = PACKAGE.parent.joinpath(*node.module.split("."), alias.name)
                is_module = below.with_suffix(".py").is_file() or below.is_dir()
                names.append((node.lineno, f"{node.module}.{alias.name}" if is_module else node.module))
    return names


def test_the_check_catches_an_import_across_the_implementations_boundary() -> None:
    outside = """
from canopy.runtime import stdout
from canopy.runtime.opencode import events
import canopy.runtime.opencode.transcript
"""
    inside = """
from canopy.runtime import report, transcript
from canopy.runtime.entries import Text
from canopy.runtime.opencode import events
"""
    other = """
from canopy.runtime.opencode2 import events
from canopy.runtime.opencode import definitions, events
"""
    found = implementation_imports(PACKAGE / "runs" / "example.py", outside)
    found += implementation_imports(BINDING, outside)
    found += implementation_imports(IMPLEMENTATIONS[0] / "example.py", inside)
    found += implementation_imports(IMPLEMENTATIONS[1] / "example.py", other)
    assert [v.split(": ", 1)[1] for v in found] == [
        "imports canopy.runtime.opencode.events, which only canopy/runtime/implementation.py may",
        "imports canopy.runtime.opencode.transcript, which only canopy/runtime/implementation.py may",
        "imports canopy.runtime.transcript, which the implementation may not: it is the surface's",
        "imports canopy.runtime.opencode.events, another implementation's, which this one may not",
    ]


def naming_runtime(path: Path, source: str) -> list[str]:
    """Each string in `source`, the text of the module at `path`, that names the runtime, its docstrings left out."""
    tree = ast.parse(source, filename=str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    where = path.relative_to(PACKAGE.parent)
    return [
        f"{where}:{node.lineno}: names the runtime, which only its implementation may: {node.value[:60]!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and RUNTIME_NAME.search(node.value)
    ]


def test_the_check_catches_a_string_that_names_the_runtime() -> None:
    source = '''
"""Runs agents with OpenCode."""

ENV = "OPENCODE_CONFIG_DIR"


def run(command: str) -> str:
    """Run `opencode run`."""
    return f"env {ENV}=x opencode {command}"
'''
    found = naming_runtime(PACKAGE / "runs" / "example.py", source)
    assert [v.split(": ", 1)[0] for v in found] == ["canopy/runs/example.py:4", "canopy/runs/example.py:9"]


def test_no_test_module_imports_another() -> None:
    """What two test modules share lives in a helpers module (`tests/canopy/helpers.py`) or a conftest, not in one."""
    found = [v for path in under_tests("*.py") for v in imported_tests(path, path.read_text())]
    assert not found, "\n".join(found)


def imported_tests(path: Path, source: str) -> list[str]:
    """Each import in `source`, the text of the module at `path`, of a test module."""
    found: list[str] = []
    module = path.relative_to(TESTS.parent)
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
        else:
            continue
        found.extend(
            f"{module}:{node.lineno}: imports {n}, a test module"
            for n in names
            if n.rpartition(".")[2].startswith("test_")
        )
    return found


def test_the_check_catches_a_test_module_imported_either_way() -> None:
    source = """
from tests.canopy.helpers import in_tick
from tests.canopy.test_loop import context
from tests.canopy import test_web
"""
    found = imported_tests(TESTS / "canopy" / "test_example.py", source)
    assert [v.split(": ", 1)[1] for v in found] == [
        "imports tests.canopy.test_loop, a test module",
        "imports tests.canopy.test_web, a test module",
    ]


def test_the_tests_mirror_the_packages() -> None:
    """A test module sits in the directory parallel to the package it tests.

    `tests/canopy/runs/` for `canopy.runs`, and `tests/canopy_sandbox/` for the workspace member `canopy_sandbox`.
    Tests of canopy as a whole, such as this one, sit in `tests/canopy/`, and tests of the fakes in `tests/`.
    """
    packages = [PACKAGE, *(p.parent for p in PACKAGE.rglob("*/__init__.py"))]
    allowed = {TESTS, *(TESTS / "canopy" / p.relative_to(PACKAGE) for p in packages)}
    allowed |= {TESTS / p.parent.name for p in MEMBERS.glob("*/src/*/__init__.py")}
    found = [
        f"{path.relative_to(TESTS.parent)}: in no directory parallel to a package"
        for path in under_tests("test_*.py")
        if path.parent not in allowed
    ]
    assert not found, "\n".join(found)
