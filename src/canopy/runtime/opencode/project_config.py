"""OpenCode's own config in a directory an agent starts in, where it could loosen canopy's agents (D044).

OpenCode merges a repository's definition of an agent into canopy's, and a repository that repeats one of canopy's
permission patterns can put its own rules after it. So a run refuses to start in a directory whose OpenCode config
defines one of canopy's agents: `shadowing` finds those files. A private run also refuses one whose config names the
tracker server's tools (`naming_tools`): a rule merged after canopy's could reopen a write tool (DESIGN §22).

Both match each file's text, so a comment naming an agent is a false positive, which only asks the operator to reword
it. An `opencode.json` or `opencode.jsonc` is also read as OpenCode reads it, JSONC with its escapes resolved, so a name
spelled in escapes is found. OpenCode substitutes `{env:...}` and `{file:...}` in the text before it parses it, and
canopy does not read what they put in: a key with one in it counts as naming an agent or a tool, and so does a file
that does not parse. What a substitution puts in, and an agent file's YAML, are a TRUST_MODEL T7 residual.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, NamedTuple

from canopy.runtime.opencode import definitions

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
    from pathlib import Path

#: The directory of a repository's OpenCode config, the patterns of the agent files in it, and its JSON config files.
CONFIG_DIR = ".opencode"
_AGENT_PATTERNS = ("agent/**/*.md", "agents/**/*.md", "mode/*.md", "modes/*.md")
_CONFIG_FILES = ("opencode.json", "opencode.jsonc")
#: The keys of a JSON config whose maps define agents by name.
_AGENT_MAPS = ("agent", "mode")
#: OpenCode's substitutions, as its `config/variable.ts` matches them (1.19.3): each `{env:...}`, then each
#: `{file:...}` in the text that leaves, but one on a line that starts `//`.
_ENV = re.compile(r"\{env:[^}]+\}")
_FILE = re.compile(r"\{file:[^}]+\}")
#: What canopy reads in place of a variable OpenCode substitutes, whose value it does not know: nothing, as for one
#: unset, or a marker of one, so a key built from it still shows a substitution.
_UNKNOWN_ENV = ("", "{env:}")
#: And in place of a file: a marker too. OpenCode puts in the file's text JSON-escaped, so it stays in its string.
_UNKNOWN_FILE = "{file:}"
#: Where a `//` comment may end: canopy ends one at any line break, so it reads as much as OpenCode does, or more.
_LINE_BREAKS = re.compile(r"[\n\r\u2028\u2029]")


def shadowing(root: Path, names: Collection[str] | None = None) -> list[Path]:
    """Return the files in `root`'s OpenCode config that define, or may define, one of canopy's agents.

    That is an agent or mode file under `.opencode/` with a canopy agent's name, or one whose text names one (its
    frontmatter's `name` renames it), and an `opencode.json` or `opencode.jsonc` that names one, in its text or as an
    agent's key once read, or that canopy cannot rule out: one with a substitution in such a key, or that is not JSONC.
    """
    names = definitions.agent_names() if names is None else names
    found: list[Path] = []
    config_dir = root / CONFIG_DIR
    for path in _agent_files(config_dir):
        # OpenCode names an agent by its path below `agent/`, without `.md`.
        name = path.relative_to(config_dir).with_suffix("").as_posix().split("/", 1)[1]
        if name in names or _mentions(path.read_text(errors="replace"), names):
            found.append(path)
    found.extend(p for p in _config_files(root) if _reads_as_naming(p, names, _agent_keys, lambda key: key in names))
    return found


def shadowing_message(found: Iterable[Path]) -> str:
    """Explain what `shadowing` found and what to do about it.

    Returns:
        A message for the operator naming every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here defines one of canopy's agents ({files}), or may: canopy counts an agent's name built "
        "by a {env:...} or {file:...} substitution, and a file it cannot read as JSONC, as one. canopy's agents come "
        "from its own definitions directory (D040), and a definition here could loosen their permissions (D044). "
        "Remove it, or rename the agent."
    )


def naming_tools(root: Path, server: str) -> list[Path]:
    """Return the files in `root`'s OpenCode config that may name a tool of MCP server `server` (DESIGN §22, D044).

    OpenCode names a server's tools `<server>_<tool>`, and a `permission` or `tools` entry for one, merged after
    canopy's rules, could reopen a write tool a private worker is denied. A JSON config is also read for a key at any
    depth that names one, and one that canopy cannot rule out: with a substitution in a key, or that is not JSONC.
    """
    needle = f"{server}_"
    found = [p for p in _agent_files(root / CONFIG_DIR) if needle in p.read_text(errors="replace")]
    found.extend(p for p in _config_files(root) if _reads_as_naming(p, (needle,), _all_keys, lambda key: needle in key))
    return found


def naming_tools_message(server: str, found: Iterable[Path]) -> str:
    """Explain what `naming_tools` found and what to do about it.

    Returns:
        A message for the operator naming `server` and every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here names tools of the tracker's MCP server {server!r} ({files}), or may: canopy counts a "
        "key built by a {env:...} or {file:...} substitution, and a file it cannot read as JSONC, as one. "
        "A private ticket's worker may call only the tracker's read tools, and a rule here could reopen a write tool "
        "(DESIGN §22). Remove it, or work this ticket publicly."
    )


# The agent and mode files under a repository's `.opencode/`, in name order by pattern; none when it has none.
def _agent_files(config_dir: Path) -> list[Path]:
    if not config_dir.is_dir():
        return []
    return [path for pattern in _AGENT_PATTERNS for path in sorted(config_dir.glob(pattern))]


# Whether `text` holds any of `needles` as it is written.
def _mentions(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


# The JSON config files OpenCode reads in `root` and its `.opencode/`, whether or not they exist.
def _config_files(root: Path) -> list[Path]:
    return [d / f for d in (root, root / CONFIG_DIR) for f in _CONFIG_FILES]


# Whether the JSON config at `path` exists and may name what canopy looks for: its text mentions one of `needles`, or
# a key `keys` finds in one of its readings matches `wanted` or holds a substitution, or a reading does not parse,
# which OpenCode refuses too, so a parse only canopy fails is a difference between the two that canopy cannot see past.
def _reads_as_naming(
    path: Path,
    needles: Iterable[str],
    keys: Callable[[object], Iterator[str]],
    wanted: Callable[[str], bool],
) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(errors="replace")
    if _mentions(text, needles):
        return True
    try:
        documents = [_parse_jsonc(reading) for reading in _readings(text)]
    except (ValueError, RecursionError):
        return True
    return any(wanted(key) or _substituted(key) for document in documents for key in keys(document))


# The keys where a config names an agent: its top level's, which a substitution could make `agent`, and those of its
# `agent` and `mode` maps.
def _agent_keys(document: object) -> Iterator[str]:
    if not isinstance(document, _Object):
        return
    for key, value in document.pairs:
        yield key
        if key in _AGENT_MAPS and isinstance(value, _Object):
            yield from (name for name, _ in value.pairs)


class _Object(NamedTuple):
    """A JSON object read as its pairs, in order and with any key given twice kept."""

    #: Each key and its value.
    pairs: Sequence[tuple[str, object]]


# Every key in `value`, at any depth.
def _all_keys(value: object) -> Iterator[str]:
    if isinstance(value, _Object):
        for key, item in value.pairs:
            yield key
            yield from _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_keys(item)


# The texts canopy reads `text` as: as written, where a substitution outside a string fails the parse and one in a key
# shows; and as OpenCode substitutes it, each variable unset or unknown, for a substitution that runs past a quote and
# so changes what is a string after it.
def _readings(text: str) -> list[str]:
    substituted = (_substitute_files(_ENV.sub(env, text)) for env in _UNKNOWN_ENV)
    return list(dict.fromkeys((text, *substituted)))


# `text` with each `{file:...}` made unknown, but one on a line that starts `//`, which OpenCode leaves as it is.
def _substitute_files(text: str) -> str:
    def unknown(match: re.Match[str]) -> str:
        line = text[text.rfind("\n", 0, match.start()) + 1 : match.start()]
        return match.group() if line.lstrip().startswith("//") else _UNKNOWN_FILE

    return _FILE.sub(unknown, text)


# Whether `key` holds a substitution, or canopy's marker of one.
def _substituted(key: str) -> bool:
    return "{env:" in key or "{file:" in key


# `text` read as JSONC, as OpenCode's parser reads it: comments and trailing commas allowed, and every object kept as
# its pairs, so a key given twice is seen both times. Raises ValueError for text that is not JSONC.
def _parse_jsonc(text: str) -> object:
    plain = _strip_jsonc(text.removeprefix("\ufeff"))
    return json.loads(plain, object_pairs_hook=_Object, strict=False) if plain.strip() else _Object(())


# `text` without its comments and trailing commas, strings untouched. Raises ValueError on an unterminated block
# comment.
def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    comma = -1  # Where in `out` a comma is that no value has followed yet.
    i = 0
    while i < len(text):
        if text[i] == '"':
            end = _string_end(text, i)
            out.append(text[i:end])
            comma, i = -1, end
        elif text.startswith("//", i):
            line_break = _LINE_BREAKS.search(text, i)
            i = len(text) if line_break is None else line_break.start()
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                msg = "unterminated comment"
                raise ValueError(msg)
            out.append(" ")
            i = end + 2
        else:
            char = text[i]
            if char in "}]" and comma >= 0:
                out[comma] = " "
            if char == ",":
                comma = len(out)
            elif not char.isspace():
                comma = -1
            out.append(char)
            i += 1
    return "".join(out)


# The index just past the string that opens at `start`, or the end of `text` when it does not close.
def _string_end(text: str, start: int) -> int:
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return i + 1
        else:
            i += 1
    return len(text)
