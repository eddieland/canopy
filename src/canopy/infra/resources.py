"""Where canopy's own files are: migrations, prompts, agent definitions, skills, the operator's skill, the web UI.

In a source checkout they sit at the repository root (`migrations/`, `.agents/`). In an installed wheel they are
bundled inside the package (`canopy/_data/`, see `[tool.hatch.build.targets.wheel.force-include]` in pyproject.toml).
"""

from __future__ import annotations

from datetime import UTC, datetime
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


def agents_dir() -> Path:
    """Return the directory of OpenCode agent definitions."""
    return _find("agents", ".agents/agents")


def skills_dir() -> Path:
    """Return the directory of shipped skills."""
    return _find("skills", ".agents/skills")


def operator_skill() -> Path:
    """Return the skill for the operator's own agent sessions, which `canopy skill` prints. Agent runs never load it."""
    return _find("operator-skill", ".agents/operator-skill") / "SKILL.md"


def ui_dir() -> Path | None:
    """Return the built web UI, or None when this installation has none (built without Node, or not yet built)."""
    for candidate in (_BUNDLED / "ui", _SOURCE / "ui" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def ui_built_before_source(served: Path) -> datetime | None:
    """Return when `served` was built, if it is a checkout's `ui/dist` and a file under `ui/src` changed since.

    An installed wheel bundles its own build, so only a checkout's can fall behind: after a pull, until `make ui-build`.
    Modification times are enough, as git writes each file a pull changes.

    Returns:
        The build's time, in local time, or None when `served` is bundled, or is as new as every source file.
    """
    if served != _SOURCE / "ui" / "dist":
        return None
    # A file can go between the scan and its stat (an editor's swap file, a branch switch): a hint never stops the loop.
    try:
        built = (served / "index.html").stat().st_mtime
        if not any(p.is_file() and p.stat().st_mtime > built for p in (_SOURCE / "ui" / "src").rglob("*")):
            return None
    except OSError:
        return None
    return datetime.fromtimestamp(built, tz=UTC).astimezone()
