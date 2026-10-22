"""Every implementation of the runtime has what the surface takes from the one bound (D009).

The surface reaches its implementation as `canopy.runtime.implementation`'s modules, and each name it reads of one is a
name every implementation must have, so that binding another is a change of one import. Read from the surface's own
source, so a name it starts to use is checked with no list to keep.
"""

import ast
import importlib
from pathlib import Path

import pytest

from canopy.runtime import implementation

RUNTIME = Path(implementation.__file__).parent
#: Each runtime canopy can run: OpenCode 1's, bound, and OpenCode 2's.
IMPLEMENTATIONS = ("canopy.runtime.opencode", "canopy.runtime.opencode2")


def used() -> set[tuple[str, str]]:
    """Each module of the implementation the surface imports, with each name it reads of it."""
    found: set[tuple[str, str]] = set()
    for path in RUNTIME.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        aliases = {
            alias.asname or alias.name: alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == implementation.__name__
            for alias in node.names
        }
        found |= {
            (aliases[node.value.id], node.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases
        }
    return found


def test_the_surface_reads_names_of_every_bound_module() -> None:
    assert {module for module, _ in used()} == set(implementation.__all__)


@pytest.mark.parametrize("package", IMPLEMENTATIONS)
def test_an_implementation_has_every_name_the_surface_reads(package: str) -> None:
    missing = [
        f"{module}.{name}"
        for module, name in sorted(used())
        if not hasattr(importlib.import_module(f"{package}.{module}"), name)
    ]
    assert not missing, f"{package} lacks {', '.join(missing)}"
