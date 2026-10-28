"""OpenCode's own config in a directory an agent starts in, where it could loosen canopy's agents (D044).

OpenCode merges a repository's definition of an agent into canopy's, and a repository that repeats one of canopy's
permission patterns can put its own rules after it. So a run refuses to start in a directory whose OpenCode config
defines one of canopy's agents, or names an MCP server `canopy`: `shadowing` finds those files. canopy gives the
overseer a server of that name in its inline config, and a merge keeps the keys canopy's entry leaves out, such as the
environment of canopy's own interpreter (DESIGN §27, TRUST_MODEL T7). A private run also refuses one whose config names
the tracker server's tools (`naming_tools`): a rule merged after canopy's could reopen a write tool (DESIGN §22).

Both match the files as text, not parsed: JSONC and substitutions are not read (a TRUST_MODEL T7 residual), and a
comment naming an agent is a false positive, which only asks the operator to reword it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from canopy.runtime.agents import CHORE_COPY_PREFIX
from canopy.runtime.opencode import definitions

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from pathlib import Path

#: The directory of a repository's OpenCode config, the patterns of the agent files in it, and its JSON config files.
CONFIG_DIR: Final = ".opencode"
_AGENT_PATTERNS: Final = ("agent/**/*.md", "agents/**/*.md", "mode/*.md", "modes/*.md")
_CONFIG_FILES: Final = ("opencode.json", "opencode.jsonc")
#: A key named `canopy` in a JSON config file, which is how one names an MCP server `canopy`, canopy's own (DESIGN §27).
_CANOPY_KEY_RE: Final = re.compile(r'"canopy"\s*:')


def shadowing(root: Path, names: Collection[str] | None = None) -> list[Path]:
    """Return the files in `root`'s OpenCode config that define, or may define, one of canopy's agents or its server.

    That is an agent or mode file with a canopy agent's name under `.opencode/`, and an `opencode.json` or
    `opencode.jsonc` that mentions one, or has a key named `canopy`, as an MCP server of that name does.
    """
    names = definitions.agent_names() if names is None else names
    found: list[Path] = []
    config_dir = root / CONFIG_DIR
    for path in _agent_files(config_dir):
        # OpenCode names an agent by its path below `agent/`, without `.md`.
        name = path.relative_to(config_dir).with_suffix("").as_posix().split("/", 1)[1]
        # A chore's own copy of canopy's chore agent is named for the chore: every name a copy may take is canopy's.
        if name in names or name.startswith(CHORE_COPY_PREFIX):
            found.append(path)
    for path in _config_files(root):
        text = path.read_text(errors="replace") if path.is_file() else ""
        if any(n in text for n in names) or _CANOPY_KEY_RE.search(text):
            found.append(path)
    return found


def shadowing_message(found: Iterable[Path]) -> str:
    """Explain what `shadowing` found and what to do about it.

    Returns:
        A message for the operator naming every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here defines one of canopy's agents or its MCP server `canopy` ({files}). canopy's agents "
        "come from its own definitions directory (D040), and a definition here could loosen their permissions (D044); "
        "the server is canopy's own, which config here could change (DESIGN §27). Remove it, or rename it."
    )


def naming_tools(root: Path, server: str) -> list[Path]:
    """Return the files in `root`'s OpenCode config that may name a tool of MCP server `server` (DESIGN §22, D044).

    OpenCode names a server's tools `<server>_<tool>`, and a `permission` or `tools` entry for one, merged after
    canopy's rules, could reopen a write tool a private worker is denied.
    """
    needle = f"{server}_"
    candidates = [*_agent_files(root / CONFIG_DIR), *_config_files(root)]
    return [p for p in candidates if p.is_file() and needle in p.read_text(errors="replace")]


def naming_tools_message(server: str, found: Iterable[Path]) -> str:
    """Explain what `naming_tools` found and what to do about it.

    Returns:
        A message for the operator naming `server` and every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here names tools of the tracker's MCP server {server!r} ({files}). A private ticket's worker "
        "may call only the tracker's read tools, and a rule here could reopen a write tool (DESIGN §22). Remove it, or "
        "work this ticket publicly."
    )


# The agent and mode files under a repository's `.opencode/`, in name order by pattern; none when it has none.
def _agent_files(config_dir: Path) -> list[Path]:
    if not config_dir.is_dir():
        return []
    return [path for pattern in _AGENT_PATTERNS for path in sorted(config_dir.glob(pattern))]


# The JSON config files OpenCode reads in `root` and its `.opencode/`, whether or not they exist.
def _config_files(root: Path) -> list[Path]:
    return [d / f for d in (root, root / CONFIG_DIR) for f in _CONFIG_FILES]
