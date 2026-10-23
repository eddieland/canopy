"""OpenCode 2's own config where an agent starts, or above it, where it could loosen canopy's agents (D044).

OpenCode 2 reads config from the directory it starts in and from every directory above it, up to the filesystem's
root and not only the repository's: in each, `opencode.json`, `opencode.jsonc`, and `.opencode/`, with its own JSON
files and its agent and mode files. All of it ranks above canopy's definitions directory, and a definition of an agent
there merges into canopy's: its body replaces canopy's prompt, and its permission rules come after canopy's, where the
last matching rule wins. So a run refuses to start where any of those files defines one of canopy's agents, or names an
MCP server `canopy`, which canopy gives the overseer in its inline config and whose keys a merge could reach, such as
the environment of canopy's own interpreter (DESIGN §27, TRUST_MODEL T7): `shadowing` finds them. A private run also
refuses one whose config names the tracker server's tools (`naming_tools`): a rule merged after canopy's could reopen a
write tool (DESIGN §22).

Both match the files as text, not parsed: JSONC and substitutions are not read (a TRUST_MODEL T7 residual), and a
comment naming an agent is a false positive, which only asks the operator to reword it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from canopy.runtime.opencode2 import definitions

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from pathlib import Path

#: The directory of a project's OpenCode config, the patterns of the agent files in it, and its JSON config files.
CONFIG_DIR = ".opencode"
_AGENT_PATTERNS = ("agent/**/*.md", "agents/**/*.md", "mode/*.md", "modes/*.md")
_CONFIG_FILES = ("opencode.json", "opencode.jsonc")
#: A key named `canopy` in a JSON config file, which is how one names an MCP server `canopy`, canopy's own (DESIGN §27).
_CANOPY_KEY_RE = re.compile(r'"canopy"\s*:')


def shadowing(root: Path, names: Collection[str] | None = None) -> list[Path]:
    """Return the files OpenCode reads starting in `root` that define, or may define, canopy's agents or its server.

    That is, in `root` and each directory above it, an agent or mode file with a canopy agent's name under
    `.opencode/`, and an `opencode.json` or `opencode.jsonc` that mentions one, or has a key named `canopy`, as an MCP
    server of that name does.
    """
    names = definitions.agent_names() if names is None else names
    found: list[Path] = []
    for directory in _searched(root):
        config_dir = directory / CONFIG_DIR
        for path in _agent_files(config_dir):
            # OpenCode names an agent by its path below `agent/`, without `.md`.
            name = path.relative_to(config_dir).with_suffix("").as_posix().split("/", 1)[1]
            if name in names:
                found.append(path)
        found.extend(p for p in _config_files(directory) if _mentions(p, names) or _names_canopy(p))
    return found


def shadowing_message(found: Iterable[Path]) -> str:
    """Explain what `shadowing` found and what to do about it.

    Returns:
        A message for the operator naming every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here or above defines one of canopy's agents or its MCP server `canopy` ({files}). canopy's "
        "agents come from its own definitions directory (D040), and a definition here could loosen their permissions "
        "(D044); the server is canopy's own, which config here could change (DESIGN §27). Remove it, or rename it."
    )


def naming_tools(root: Path, server: str) -> list[Path]:
    """Return the files OpenCode reads starting in `root` that may name a tool of MCP server `server` (DESIGN §22).

    OpenCode names a server's tools `<server>_<tool>`, and a `permission` or `tools` entry for one, merged after
    canopy's rules, could reopen a write tool a private worker is denied.
    """
    needle = f"{server}_"
    return [
        p
        for directory in _searched(root)
        for p in (*_agent_files(directory / CONFIG_DIR), *_config_files(directory))
        if _mentions(p, (needle,))
    ]


def naming_tools_message(server: str, found: Iterable[Path]) -> str:
    """Explain what `naming_tools` found and what to do about it.

    Returns:
        A message for the operator naming `server` and every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here or above names tools of the tracker's MCP server {server!r} ({files}). A private "
        "ticket's worker may call only the tracker's read tools, and a rule here could reopen a write tool (DESIGN "
        "§22). Remove it, or work this ticket publicly."
    )


# `root` and every directory above it, as OpenCode walks them: from the path it was started with, which `PWD` names with
# any links in it, and from the one they lead to, which it may read instead.
def _searched(root: Path) -> list[Path]:
    absolute, resolved = root.absolute(), root.resolve()
    return list(dict.fromkeys([absolute, *absolute.parents, resolved, *resolved.parents]))


# The agent and mode files under a `.opencode/`, in name order by pattern; none when it has none.
def _agent_files(config_dir: Path) -> list[Path]:
    if not config_dir.is_dir():
        return []
    return [path for pattern in _AGENT_PATTERNS for path in sorted(config_dir.glob(pattern))]


# The JSON config files OpenCode reads in `directory` and its `.opencode/`, whether or not they exist.
def _config_files(directory: Path) -> list[Path]:
    return [d / f for d in (directory, directory / CONFIG_DIR) for f in _CONFIG_FILES]


def _names_canopy(path: Path) -> bool:
    return path.is_file() and _CANOPY_KEY_RE.search(path.read_text(errors="replace")) is not None


def _mentions(path: Path, needles: Iterable[str]) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(errors="replace")
    return any(n in text for n in needles)
