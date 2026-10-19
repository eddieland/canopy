"""`canopy chore install`: one of the example chores canopy ships, set up for the operator (DESIGN §19).

An example is a prompt, `<name>.md`, and its config table, `<name>.toml`, in `examples/chores/`, and may come with the
agent its `cmd` names, `agents/<agent>.md`. Installing one copies the prompt into the workspace's state directory,
`chore-prompts/<name>.md`, and the agent to `chore-agents/<name>/agents/`, and writes the table to the workspace's
private file: `prompt` names the copy, `cmd` starts by pointing the runtime's config at the agent's directory, and
`cwd`, where the example has one, is the workspace root. All are the workspace's own: another workspace's copy of the
same example is filled in apart from it, and an upgraded canopy changes none of them until the chore is installed again.
The state directory is the operator's alone, as a prompt file must be (TRUST_MODEL T7), and neither copy is in
`chores/`, under which a chore with no `cwd` runs.

The command owns what it writes: installing again replaces the prompt, the agent, and the whole `[chores.<name>]` table
with the shipped ones, and an edit to any is lost. Every other line of the private file stays as it was, or nothing is
written. The table goes in the private file, since the last file that sets any chore replaces every other file's chores
whole (`config.load`). With chores in the user file and none in the private file, a table written there would hide them
all, so installing is refused.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import shlex
import shutil
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import config
from canopy.infra import logs, resources
from canopy.runtime import agents, invocation

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.core.workspace import Workspace

#: The directory of the state directory installed prompts are copied into.
PROMPTS_DIR = "chore-prompts"
#: The directory of the state directory each installed chore's runtime config directory is in, by the chore's name.
AGENTS_DIR = "chore-agents"
#: The comment above an installed table, which says who owns it.
MARKER = "# Written by `canopy chore install {name}`, which replaces this table whole when run again."
# A line that starts a table or an array of tables, and so ends the one before it.
_HEADER_RE = re.compile(r"[ \t]*\[")


class InstallError(Exception):
    """The example cannot be installed: there is none by that name, or the private file cannot take its table."""


@dataclass(frozen=True)
class Installed:
    """What installing an example chore wrote."""

    #: The chore's name, which is the example's.
    name: str
    #: The copy of the prompt the table names.
    prompt: Path
    #: The copy of the agent its command runs, or None when the example comes with none.
    agent: Path | None
    #: The private file the table is in.
    config_file: Path
    #: Whether the prompt, the agent, or the table was there before, and was replaced.
    replaced: bool
    #: What to do before the chore can run, from the example's comment, one line of it each.
    next_steps: tuple[str, ...]


def available() -> list[str]:
    """Return the names of the example chores canopy ships, sorted.

    Returns:
        Each name that has both a prompt and a table; empty when this installation has no examples.
    """
    try:
        directory = resources.example_chores_dir()
    except FileNotFoundError:
        return []
    return sorted(
        path.stem
        for path in directory.glob("*.toml")
        if config.CHORE_NAME_RE.fullmatch(path.stem) and path.with_suffix(".md").is_file()
    )


def install(ws: Workspace, name: str) -> Installed:
    """Install example chore `name` in `ws`: its prompt, its agent if it has one, and its table, replacing any there.

    The prompt and the agent go in the workspace's state directory, the table in its private file.

    Returns:
        What was written, and what the operator still has to do.

    Raises:
        InstallError: there is no such example, the config does not load, the user file's chores would be hidden, or
            the table cannot be replaced without changing anything else in the private file.
    """
    if name not in available():
        raise InstallError(f"no example chore named {name!r}; there are: {', '.join(available())}")
    shipped = resources.example_chores_dir() / f"{name}.toml"
    shipped_text = shipped.read_text(encoding="utf-8")
    try:
        # The workspace's config must load as it is, which also holds the private file to being the operator's own.
        config.load(ws.root)
    except config.ConfigError as e:
        raise InstallError(f"the config does not load, so nothing was written: {e}") from None
    private = config.private_config_path(ws.root)
    try:
        old_text = private.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InstallError(f"there is no private config at {private}; `canopy init` writes it") from None
    old = tomllib.loads(old_text)
    if "chores" not in old and "chores" in _read(config.user_config_path()):
        raise InstallError(
            f"your chores are in {config.user_config_path()}, and a chore in {private} would hide them all; move them "
            "there first"
        )
    prompt = ws.state_dir / PROMPTS_DIR / f"{name}.md"
    table = dict(tomllib.loads(shipped_text)["chores"][name])
    table["prompt"] = str(prompt)
    if "cwd" in table:
        table["cwd"] = str(ws.root.absolute())
    agent_dir = ws.state_dir / AGENTS_DIR / name
    agent = _agent(table.get("cmd"))
    if agent is not None:
        table["cmd"] = invocation.with_config_dir(shlex.quote(str(agent_dir)), table["cmd"])
    config.Chore.model_validate(table)
    new_text, replaced = _with_table(old_text, name, _render(name, table))
    _check(private, old, new_text, name, table)
    replaced = replaced or prompt.exists() or agent_dir.exists()
    prompt.parent.mkdir(mode=0o700, exist_ok=True)
    logs.write_private(prompt, (resources.example_chores_dir() / f"{name}.md").read_text(encoding="utf-8"))
    copied = _copy_agent(agent, agent_dir)
    _write(private, new_text)
    return Installed(name, prompt, copied, private, replaced, _next_steps(shipped_text))


def _read(path: Path) -> dict[str, object]:
    """Return `path` parsed, or empty when it is missing; `config.load` has already found it valid."""
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def _agent(cmd: object) -> Path | None:
    """Return the agent definition the example comes with for the agent `cmd` runs, or None when it comes with none."""
    name = invocation.agent_of(cmd) if isinstance(cmd, str) else None
    if name is None:
        return None
    path = resources.example_chores_dir() / agents.AGENTS_SUBDIR / f"{name}.md"
    return path if path.is_file() else None


def _copy_agent(agent: Path | None, agent_dir: Path) -> Path | None:
    """Replace `agent_dir` with a runtime config directory holding only a copy of `agent`; with no agent, remove it.

    The copy and its directories are readable by the operator alone.

    Returns:
        The copy, or None when there is no agent.
    """
    if agent_dir.exists() or agent_dir.is_symlink():
        shutil.rmtree(agent_dir)
    if agent is None:
        return None
    agent_dir.parent.mkdir(mode=0o700, exist_ok=True)
    agent_dir.mkdir(mode=0o700)
    (agent_dir / agents.AGENTS_SUBDIR).mkdir(mode=0o700)
    copied = agent_dir / agents.AGENTS_SUBDIR / agent.name
    logs.write_private(copied, agent.read_text(encoding="utf-8"))
    return copied


def _with_table(text: str, name: str, block: str) -> tuple[str, bool]:
    """Return `text` with `block` in place of its `[chores.<name>]` table, or after the rest when it has none.

    The table runs from its header, and the marker just above it, to the next table's header; comments and blank lines
    at its end stay, as the next table's.

    Returns:
        The new text, and whether a table was replaced.
    """
    lines = text.splitlines(keepends=True)
    quoted = re.escape(name)
    header = re.compile(
        rf"[ \t]*\[[ \t]*chores[ \t]*\.[ \t]*(?:{quoted}|\"{quoted}\"|'{quoted}')[ \t]*\][ \t]*(?:#.*)?"
    )
    found = next((i for i, line in enumerate(lines) if header.fullmatch(line.rstrip("\r\n"))), None)
    if found is None:
        rest = text.rstrip("\n")
        return (f"{rest}\n\n{block}" if rest else block), False
    start = found - 1 if found and lines[found - 1].rstrip("\r\n") == MARKER.format(name=name) else found
    end = next((i for i in range(found + 1, len(lines)) if _HEADER_RE.match(lines[i])), len(lines))
    while end > found + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return "".join(lines[:start]) + block + "".join(lines[end:]), True


def _render(name: str, table: Mapping[str, object]) -> str:
    """Return `table` as the TOML of a `[chores.<name>]` table, with the marker above it."""
    lines = [MARKER.format(name=name), f"[chores.{name}]"]
    lines += [f"{key} = {_value(value)}" for key, value in table.items()]
    return "\n".join(lines) + "\n"


def _value(value: object) -> str:
    """Return `value`, a string, integer, or list of strings as a chore's table holds them, as TOML.

    Raises:
        InstallError: it is something else, which no example's table holds.
    """
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise InstallError(f"an example's table holds {value!r}, which canopy cannot write")


def _string(value: str) -> str:
    """Return `value` as a TOML literal string, as the examples spell a command, or a basic one when it cannot be."""
    literal = f"'{value}'"
    with contextlib.suppress(tomllib.TOMLDecodeError):
        if tomllib.loads(f"v = {literal}")["v"] == value:
            return literal
    return json.dumps(value, ensure_ascii=False)


def _check(private: Path, old: Mapping[str, object], new_text: str, name: str, table: Mapping[str, object]) -> None:
    """Make sure `new_text` is `old` with only chore `name`'s table changed, to `table`.

    Raises:
        InstallError: it is not, as when the file defines the chore in some other form, such as dotted keys.
    """
    expected = copy.deepcopy(dict(old))
    chores = expected.setdefault("chores", {})
    if isinstance(chores, dict):
        chores[name] = dict(table)
    try:
        ok = tomllib.loads(new_text) == expected
    except tomllib.TOMLDecodeError:
        ok = False
    if not ok:
        raise InstallError(
            f"cannot replace [chores.{name}] in {private} without changing anything else in it; remove that table, "
            "then install again"
        )


def _write(path: Path, text: str) -> None:
    """Replace `path` with `text` in one step, readable only by the operator, as the private file must be."""
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        logs.write_private(temporary, text)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _next_steps(shipped_text: str) -> tuple[str, ...]:
    """Return the comment at the top of an example's table, which says what to do before it runs, one line each."""
    steps: list[str] = []
    for line in shipped_text.splitlines():
        if not line.startswith("#"):
            break
        steps.append(line.removeprefix("#").strip())
    return tuple(steps)
