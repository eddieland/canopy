"""How an installed example chore and the one canopy ships have moved apart since it was installed (DESIGN §19).

`canopy chore install` keeps, beside the copies it writes, the prompt and the agent canopy shipped then, and canopy's
version (`install.Origin`). Against that record, `Drift.standing` says whether canopy ships something else now, and
`diff` shows both sides a merge by hand needs: what canopy changed since, and what the operator changed in the copies.
A chore installed before the record was kept is compared as installed against shipped now, which cannot tell the two
apart, and says so.

The model canopy writes into an installed agent each time the chore runs (`install.write_model`) is canopy's, not an
edit, so it is taken out of the copy before any comparison.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, assert_never

from pydantic import ValidationError

from canopy.chores import install
from canopy.core import db
from canopy.infra import resources
from canopy.runtime import definitions
from canopy.runtime.agents import DefinitionsError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from canopy.core.workspace import Workspace

#: What `diff` says for a side that changed nothing.
_UNCHANGED: Final = "(no change)\n"
#: The label of the side of a diff that is what canopy ships now.
_SHIPPED: Final = "shipped"


class Standing(StrEnum):
    """Where an installed example chore stands against the one canopy ships now."""

    #: canopy ships what it was installed from; the operator's edits, if any, are theirs.
    CURRENT = "current"
    #: canopy ships a prompt or an agent other than the one it was installed from.
    CHANGED = "changed"
    #: It was installed before canopy kept a record, and its copies differ from what canopy ships now.
    DIFFERS = "differs"


@dataclass(frozen=True)
class File:
    """One file of an installed example chore, three ways: as installed from, as shipped now, and the copy."""

    #: The file's name: the prompt's, `<name>.md`, or the agent's.
    name: str
    #: As canopy shipped it when the chore was installed, or None when no record says, or the example had none.
    installed_from: str | None
    #: As canopy ships it now, or None when it ships none.
    shipped: str | None
    #: The workspace's copy, without the model canopy writes into an agent, or None when there is none.
    installed: str | None
    #: The name canopy ships it under now, when that is not `name`: an agent the example renamed.
    shipped_name: str | None = None


@dataclass(frozen=True)
class Drift:
    """An installed example chore's prompt and agent, as installed from, as canopy ships them now, and as copied."""

    #: The chore's name, which is the example's.
    name: str
    #: The version of canopy that installed it, or None when it was installed before canopy kept a record.
    installed_by: str | None
    #: The prompt, then the agent when any of the three ways has one.
    files: Sequence[File]

    @property
    def standing(self) -> Standing:
        """Where the chore stands against what canopy ships now: the copies stand for the record when there is none."""
        renamed = any(f.shipped_name is not None for f in self.files)
        if self.installed_by is None:
            same = not renamed and all(f.installed == f.shipped for f in self.files)
            return Standing.CURRENT if same else Standing.DIFFERS
        same = not renamed and all(f.installed_from == f.shipped for f in self.files)
        return Standing.CURRENT if same else Standing.CHANGED


def of(ws: Workspace, name: str) -> Drift | None:
    """Return how example chore `name`, installed in `ws`, and the one canopy ships have moved apart.

    Returns:
        Its three ways, or None when the chore is not installed: `ws` has no copy of its prompt.

    Raises:
        OSError: a copy or the record is there but cannot be read.
    """
    prompt = _text(ws.state_dir / install.PROMPTS_DIR / f"{name}.md")
    if prompt is None:
        return None
    origin = _origin(ws.state_dir / install.ORIGINS_DIR / f"{name}.json")
    shipped = name in install.available()
    shipped_prompt = _text(resources.example_chores_dir() / f"{name}.md") if shipped else None
    files = [File(f"{name}.md", origin.prompt if origin else None, shipped_prompt, prompt)]
    shipped_agent = install.shipped_agent(name)
    copied = sorted((ws.state_dir / install.AGENTS_DIR / name / definitions.AGENTS_SUBDIR).glob("*.md"))
    agent_names = [path.name for path in copied[:1]]
    if origin is not None and origin.agent_file is not None:
        agent_names.append(origin.agent_file)
    if shipped_agent is not None:
        agent_names.append(shipped_agent.name)
    if agent_names:
        # Named as installed: the copy's name, else the record's; canopy may ship it under another now.
        named = agent_names[0]
        files.append(
            File(
                named,
                origin.agent if origin else None,
                _text(shipped_agent) if shipped_agent is not None else None,
                _without_model(copied[0]) if copied else None,
                shipped_name=shipped_agent.name if shipped_agent is not None and shipped_agent.name != named else None,
            ),
        )
    return Drift(name, origin.version if origin else None, tuple(files))


def diff(drift: Drift) -> str:
    """Return the unified diffs a merge by hand needs: what canopy changed since the install, and what the operator did.

    With no record, the copies against what canopy ships now, saying that is all it can show.

    Returns:
        The diffs, each side under a line that says which it is.
    """
    now = db.CANOPY_VERSION
    by = drift.installed_by
    if by is None:
        return (
            f"chore {drift.name} was installed before canopy kept what it installed it from, so this is only your copy "
            f"against what canopy {now} ships; it cannot tell your edits from canopy's changes.\n"
            + _diffs(drift.files, ("yours", lambda f: f.installed), (_SHIPPED, lambda f: f.shipped))
        )
    return (
        f"What canopy changed since chore {drift.name} was installed: canopy {by}'s against canopy {now}'s.\n"
        + _diffs(drift.files, ("installed-from", lambda f: f.installed_from), (_SHIPPED, lambda f: f.shipped))
        + f"\nWhat you changed: canopy {by}'s against your copy.\n"
        + _diffs(drift.files, ("installed-from", lambda f: f.installed_from), ("yours", lambda f: f.installed))
    )


def describe(standing: Standing, name: str) -> str:
    """Return `standing` as `canopy chore install` lists it beside chore `name`.

    Returns:
        A few words, with the command that shows more when the chore has moved apart from canopy's.
    """
    match standing:
        case Standing.CURRENT:
            return "installed"
        case Standing.CHANGED:
            return f"installed; canopy ships a newer version, see `canopy chore diff {name}`"
        case Standing.DIFFERS:
            return f"installed; differs from the version canopy ships, see `canopy chore diff {name}`"
        case _:
            assert_never(standing)


def _text(path: Path) -> str | None:
    """Return `path`'s text, or None when there is no such file; a byte that is not UTF-8 reads as a replacement."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None


def _origin(path: Path) -> install.Origin | None:
    """Return the record of what the chore was installed from, or None when there is none, or it does not parse."""
    text = _text(path)
    if text is None:
        return None
    try:
        return install.Origin.model_validate_json(text)
    except ValidationError:
        return None


def _without_model(path: Path) -> str | None:
    """Return the agent copy at `path` without the model canopy writes into it, as canopy shipped it."""
    text = _text(path)
    if text is None:
        return None
    try:
        return definitions.set_model(text, path.name, None)
    except DefinitionsError:
        return text


def _diffs(
    files: Sequence[File],
    old: tuple[str, Callable[[File], str | None]],
    new: tuple[str, Callable[[File], str | None]],
) -> str:
    """Return each of `files` as a unified diff from its `old` side to its `new`, each side a label and its text.

    Returns:
        The diffs, or a line saying nothing changed.
    """
    out: list[str] = []
    for file in files:
        before, after = old[1](file), new[1](file)
        # The shipped side carries the name canopy ships it under, so a rename shows though the text is the same.
        renamed = file.shipped_name is not None and new[0] == _SHIPPED
        after_name = file.shipped_name if renamed and file.shipped_name is not None else file.name
        if before == after and not renamed:
            continue
        if before == after:
            out.append(f"renamed: {old[0]}/{file.name} -> {new[0]}/{after_name}, the text unchanged\n")
            continue
        lines = difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile=f"{old[0]}/{file.name}" if before is not None else "/dev/null",
            tofile=f"{new[0]}/{after_name}" if after is not None else "/dev/null",
        )
        out += (line if line.endswith("\n") else f"{line}\n\\ No newline at end of file\n" for line in lines)
    return "".join(out) or _UNCHANGED
