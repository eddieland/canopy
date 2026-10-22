"""OpenCode's own config in a directory an agent starts in, where it could loosen canopy's agents (D044).

OpenCode merges a repository's definition of an agent into canopy's, and a repository that repeats one of canopy's
permission patterns can put its own rules after it. So a run refuses to start in a directory whose OpenCode config
defines one of canopy's agents: `shadowing` finds those files. A private run also refuses one whose config names the
tracker server's tools (`naming_tools`): a rule merged after canopy's could reopen a write tool (DESIGN §22). And a run
canopy gives one of its own MCP servers refuses one whose config names that server or its tools (`naming_server`): an
entry merged into canopy's inline config could change how the server starts, and a rule after canopy's, which of its
tools the agent may call (DESIGN §27).

Each matches the files as text, not parsed: JSONC and substitutions are not read (a TRUST_MODEL T7 residual), and a
comment naming an agent is a false positive, which only asks the operator to reword it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime.opencode import definitions

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from pathlib import Path

#: The directory of a repository's OpenCode config, the patterns of the agent files in it, and its JSON config files.
CONFIG_DIR = ".opencode"
_AGENT_PATTERNS = ("agent/**/*.md", "agents/**/*.md", "mode/*.md", "modes/*.md")
_CONFIG_FILES = ("opencode.json", "opencode.jsonc")


def shadowing(root: Path, names: Collection[str] | None = None) -> list[Path]:
    """Return the files in `root`'s OpenCode config that define, or may define, one of canopy's agents.

    That is an agent or mode file with a canopy agent's name under `.opencode/`, and an `opencode.json` or
    `opencode.jsonc` that mentions one.
    """
    names = definitions.agent_names() if names is None else names
    found: list[Path] = []
    config_dir = root / CONFIG_DIR
    for path in _agent_files(config_dir):
        # OpenCode names an agent by its path below `agent/`, without `.md`.
        name = path.relative_to(config_dir).with_suffix("").as_posix().split("/", 1)[1]
        if name in names:
            found.append(path)
    found.extend(
        p for p in _config_files(root) if p.is_file() and any(n in p.read_text(errors="replace") for n in names)
    )
    return found


def shadowing_message(found: Iterable[Path]) -> str:
    """Explain what `shadowing` found and what to do about it.

    Returns:
        A message for the operator naming every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here defines one of canopy's agents ({files}). canopy's agents come from its own definitions "
        "directory (D040), and a definition here could loosen their permissions (D044). Remove it, or rename the agent."
    )


def naming_tools(root: Path, server: str) -> list[Path]:
    """Return the files in `root`'s OpenCode config that may name a tool of MCP server `server` (DESIGN §22, D044).

    OpenCode names a server's tools `<server>_<tool>`, and a `permission` or `tools` entry for one, merged after
    canopy's rules, could reopen a write tool a private worker is denied.
    """
    return _naming(root, f"{server}_")


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


def naming_server(root: Path, server: str) -> list[Path]:
    """Return the files in `root`'s OpenCode config that may name canopy's own MCP server `server`, or its tools.

    A server entry of that name merges into the one canopy gives the run, and every tool of it is named
    `<server>_<tool>`, so the server's name is matched alone.
    """
    return _naming(root, server)


def naming_server_message(servers: Iterable[str], found: Iterable[Path]) -> str:
    """Explain what `naming_server` found for `servers` and what to do about it.

    Returns:
        A message for the operator naming each of `servers` and every file in `found`.
    """
    names = [repr(s) for s in servers]
    named = f"servers {' and '.join(names)}, or their tools" if len(names) > 1 else f"server {names[0]}, or its tools"
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here names canopy's own MCP {named} ({files}). canopy gives a run such a server in its "
        "inline config, and an entry here merges into it, so it could change how the server starts or which of its "
        "tools the agent may call (DESIGN §27, D044). Remove it, or rename the server."
    )


# The files in `root`'s OpenCode config, agent files and JSON config, whose text holds `needle`.
def _naming(root: Path, needle: str) -> list[Path]:
    candidates = [*_agent_files(root / CONFIG_DIR), *_config_files(root)]
    return [p for p in candidates if p.is_file() and needle in p.read_text(errors="replace")]


# The agent and mode files under a repository's `.opencode/`, in name order by pattern; none when it has none.
def _agent_files(config_dir: Path) -> list[Path]:
    if not config_dir.is_dir():
        return []
    return [path for pattern in _AGENT_PATTERNS for path in sorted(config_dir.glob(pattern))]


# The JSON config files OpenCode reads in `root` and its `.opencode/`, whether or not they exist.
def _config_files(root: Path) -> list[Path]:
    return [d / f for d in (root, root / CONFIG_DIR) for f in _CONFIG_FILES]
