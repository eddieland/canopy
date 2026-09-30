"""The directory agent runs load canopy's agent definitions and skills from (DESIGN §13, D040, D044).

canopy snapshots its bundled `agents/` and `skills/` into `<state_dir>/runtime/<digest>/`, named for a digest of their
contents. A snapshot is written to a temporary directory and renamed into place, so a run never sees a partial one.
Command templates name it with `{definitions_dir}`, and OpenCode reads it through `OPENCODE_CONFIG_DIR`.

OpenCode merges a repository's definition of an agent into canopy's, and a repository that repeats one of canopy's
permission patterns can put its own rules after it (D044). So a run refuses to start in a directory whose OpenCode
config defines one of canopy's agents: `shadowing` finds those files.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path

from canopy.infra import logs, resources

RUNTIME_DIR = "runtime"
_TMP_PREFIX = ".tmp-"
# A temporary directory this old belongs to a process that died mid-copy; a copy takes well under a second.
_STALE_TMP_SECONDS = 3600


class DefinitionsError(Exception):
    """The snapshot for this canopy exists but is not one canopy made, so no run may load it."""


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def digest() -> str:
    """Return a digest of the bundled agent definitions and skills: their relative paths and contents."""
    h = hashlib.sha256()
    for name, root in (("agents", resources.agents_dir()), ("skills", resources.skills_dir())):
        for path in _files(root):
            rel = f"{name}/{path.relative_to(root).as_posix()}"
            data = path.read_bytes()
            h.update(f"{rel}\0{len(data)}\0".encode())
            h.update(data)
    return h.hexdigest()[:16]


def agent_names() -> list[str]:
    """Return the names of the agents canopy ships, as OpenCode names them: the file name without `.md`."""
    return sorted(p.stem for p in resources.agents_dir().glob("*.md"))


def ensure(state_dir: Path) -> Path:
    """Return the snapshot for the installed canopy, creating it if missing. Safe to call from concurrent processes.

    canopy creates a snapshot readable only by the operator. One that is not was put there by something else, such as a
    checkout of a shared workspace (DESIGN §18), and could loosen canopy's agents, so it is refused, never loaded.

    Raises:
        DefinitionsError: the snapshot's directory exists and is not private to the operator.
    """
    runtime = state_dir / RUNTIME_DIR
    final = runtime / digest()
    if final.is_dir() or final.is_symlink():
        return _checked(final)
    runtime.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=_TMP_PREFIX, dir=runtime))
    try:
        shutil.copytree(resources.agents_dir(), tmp / "agents")
        shutil.copytree(resources.skills_dir(), tmp / "skills")
        os.rename(tmp, final)  # noqa: PTH104  (os.rename, unlike Path.replace, never replaces a non-empty directory)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        # Another process renamed its copy into place first; theirs has the same contents.
        if final.is_dir():
            return _checked(final)
        raise
    return final


def _checked(snapshot: Path) -> Path:
    if not logs.private_dir(snapshot):
        raise DefinitionsError(
            f"{snapshot} is not a snapshot canopy made: canopy creates it readable only by you, and this one is a "
            "symlink, someone else's, or open to others. Remove it; canopy recreates it."
        )
    return snapshot


def prune(state_dir: Path, keep: Path) -> list[Path]:
    """Remove snapshots other than `keep`, and temporary directories a dead process left. Returns what was removed.

    Call it only when no run is live: a run of an earlier canopy may still be loading its snapshot.
    """
    runtime = state_dir / RUNTIME_DIR
    if not runtime.is_dir():
        return []
    removed: list[Path] = []
    now = time.time()
    for entry in sorted(runtime.iterdir()):
        if entry == keep or not entry.is_dir():
            continue
        if entry.name.startswith(_TMP_PREFIX) and now - entry.stat().st_mtime < _STALE_TMP_SECONDS:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry)
    return removed


def shadowing(root: Path, names: list[str] | None = None) -> list[Path]:
    """Return the files in `root`'s OpenCode config that define, or may define, one of canopy's agents.

    That is an agent or mode file with a canopy agent's name under `.opencode/`, and an `opencode.json` or
    `opencode.jsonc` that mentions one. The JSON files are matched as text, not parsed: a comment naming an agent is a
    false positive, which only asks the operator to reword it.
    """
    names = agent_names() if names is None else names
    found: list[Path] = []
    config_dir = root / ".opencode"
    if config_dir.is_dir():
        for pattern in ("agent/**/*.md", "agents/**/*.md", "mode/*.md", "modes/*.md"):
            for path in sorted(config_dir.glob(pattern)):
                # OpenCode names an agent by its path below `agent/`, without `.md`.
                name = path.relative_to(config_dir).with_suffix("").as_posix().split("/", 1)[1]
                if name in names:
                    found.append(path)
    configs = (d / f for d in (root, config_dir) for f in ("opencode.json", "opencode.jsonc"))
    found.extend(p for p in configs if p.is_file() and any(n in p.read_text(errors="replace") for n in names))
    return found


def shadowing_message(found: list[Path]) -> str:
    """Explain what `shadowing` found and what to do about it."""
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here defines one of canopy's agents ({files}). canopy's agents come from its own definitions "
        "directory (D040), and a definition here could loosen their permissions (D044). Remove it, or rename the agent."
    )
