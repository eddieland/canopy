"""Every implementation of the runtime has what the surface takes from either (D009).

The surface reaches an implementation as `canopy.runtime.implementation`'s `one` or `two`, the version config's
`runtime.version` names, and each name it reads of one's module is a name every implementation's must have, so that
either runs whatever the surface calls. Read from the surface's own source, so a name it starts to use is checked with
no list to keep.
"""

import ast
import importlib
from pathlib import Path
from typing import Final

import pytest

from canopy.runtime import implementation
from canopy.runtime.implementation import Version, pick

RUNTIME: Final = Path(implementation.__file__).parent
#: Each runtime canopy can run: OpenCode 1's, the default, and OpenCode 2's.
IMPLEMENTATIONS: Final = ("canopy.runtime.opencode", "canopy.runtime.opencode2")
#: The names the binding gives the implementations.
BOUND: Final = frozenset({"one", "two"})


def used() -> set[tuple[str, str]]:
    """Each module of an implementation the surface reads, with each name it reads of it."""
    found: set[tuple[str, str]] = set()
    for path in RUNTIME.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        found |= {
            (node.value.attr, node.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id in BOUND
        }
        # A module the surface reads names of later, as `pick(version, one.models, two.models).listed(...)`.
        found |= {
            (arg.attr, node.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call)
            for arg in node.value.args
            if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id in BOUND
        }
    return found


def test_the_surface_reads_names_of_every_module_of_an_implementation() -> None:
    assert {module for module, _ in used()} == set(implementation.one.__all__) == set(implementation.two.__all__)


@pytest.mark.parametrize("package", IMPLEMENTATIONS)
def test_an_implementation_has_every_name_the_surface_reads(package: str) -> None:
    missing = [
        f"{module}.{name}"
        for module, name in sorted(used())
        if not hasattr(importlib.import_module(f"{package}.{module}"), name)
    ]
    assert not missing, f"{package} lacks {', '.join(missing)}"


def test_each_version_runs_its_own_implementation() -> None:
    assert pick(Version.ONE, implementation.one, implementation.two) is implementation.one
    assert pick(Version.TWO, implementation.one, implementation.two) is implementation.two
