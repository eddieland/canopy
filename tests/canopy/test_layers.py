"""The package layers of DESIGN §5 (D041), checked on every import in `src/canopy`, `TYPE_CHECKING` ones included;
and the tests' one rule of the same kind: a test module imports from no other."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "canopy"
TESTS = Path(__file__).resolve().parents[1]

# Top to bottom. A module may import from its own package and from any package in a lower layer. It may not import
# from a higher layer or from another package in its own layer: features stay independent of each other, and shared
# code moves down a layer instead.
LAYERS: tuple[frozenset[str], ...] = (
    frozenset({"__main__"}),
    frozenset({"cli"}),
    frozenset({"loop"}),
    frozenset({"runs", "setup", "chores", "notify", "reviews", "serve"}),
    frozenset({"core"}),
    frozenset({"infra"}),
)
# Third-party packages only one canopy package may import.
CONFINED = {
    "anyio": "serve",
    "click": "cli",
    "fastapi": "serve",
    "starlette": "serve",
    "tomlkit": "serve",
    "uvicorn": "serve",
}
# Programs canopy ships as separate distributions and runs only as commands (D041): the Slack sink holds a secret and
# opens connections, which the harness never does (DESIGN §20).
SEPARATE = frozenset({"canopy_notify_slack"})


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
        if top in CONFINED and CONFINED[top] != own:
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

if TYPE_CHECKING:
    from canopy.loop.tick import Outcome
"""
    found = violations(PACKAGE / "runs" / "example.py", source)
    assert [v.split(": ", 1)[1] for v in found] == [
        "imports click, which only canopy.cli may import",
        "canopy.runs imports canopy.cli, which is not in a lower layer",
        "canopy.runs imports canopy.setup.init, which is not in a lower layer",
        "imports canopy_notify_slack, a separate program canopy runs only as a command",
        "canopy.runs imports canopy.loop.tick, which is not in a lower layer",
    ]


def test_no_test_module_imports_another() -> None:
    """What two test modules share lives in a helpers module (`tests/canopy/helpers.py`) or a conftest, not in one."""
    found = [v for path in sorted(TESTS.rglob("*.py")) for v in imported_tests(path, path.read_text())]
    assert not found, "\n".join(found)


def imported_tests(path: Path, source: str) -> list[str]:
    """Each import in `source`, the text of the module at `path`, of a test module."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
        where = f"{path.relative_to(TESTS.parent)}:{getattr(node, 'lineno', 0)}"
        found.extend(f"{where}: imports {n}, a test module" for n in names if n.rpartition(".")[2].startswith("test_"))
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
