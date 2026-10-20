"""Where canopy's own files are: migrations, prompts, personas, agents, skills (the operator's too), chores, the web UI.

In a source checkout they sit at the repository root (`migrations/`, `.agents/`, `examples/chores/`). In an installed
wheel they are bundled inside the package (`canopy/_data/`, see `[tool.hatch.build.targets.wheel.force-include]` in
pyproject.toml).
"""

from __future__ import annotations

from pathlib import Path

# This file is canopy/infra/resources.py; bundled files sit beside the top-level package.
_PACKAGE = Path(__file__).resolve().parent.parent
_BUNDLED = _PACKAGE / "_data"
_SOURCE = _PACKAGE.parent.parent


def _find(bundled: str, source: str) -> Path:
    for candidate in (_BUNDLED / bundled, _SOURCE / source):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"canopy's {bundled} directory is missing from this installation")


def migrations_dir() -> Path:
    """Return the directory of SQL migrations."""
    return _find("migrations", "migrations")


def prompts_dir() -> Path:
    """Return the directory of shipped prompts."""
    return _find("prompts", ".agents/prompts")


def personas_dir() -> Path:
    """Return the directory of shipped personas, each `<name>.md`, the voice a planner, reviewer, or worker uses."""
    return _find("personas", ".agents/personas")


def agents_dir() -> Path:
    """Return the directory of canopy's agent definitions, in the runtime's format (`canopy.runtime.definitions`)."""
    return _find("agents", ".agents/agents")


def skills_dir() -> Path:
    """Return the directory of shipped skills."""
    return _find("skills", ".agents/skills")


def operator_skill() -> Path:
    """Return the skill for the operator's own agent sessions, which `canopy skill` prints. Agent runs never load it."""
    return _find("operator-skill", ".agents/operator-skill") / "SKILL.md"


def example_chores_dir() -> Path:
    """Return the directory of example chores: each a prompt, `<name>.md`, and its config table, `<name>.toml`."""
    return _find("chores", "examples/chores")


def ui_dir() -> Path | None:
    """Return the built web UI, or None when this installation has none (built without Node, or not yet built)."""
    for candidate in (_BUNDLED / "ui", _SOURCE / "ui" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None
