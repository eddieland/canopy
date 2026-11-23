"""How an installed example chore and the one canopy ships have moved apart since it was installed (DESIGN §19).

`canopy chore install` keeps, beside the copies it writes, the prompt and the agent canopy shipped then, and canopy's
version (`install.Origin`). Against that record, `Drift.standing` says whether canopy ships something else now, and
`diff` shows both sides a merge by hand needs: what canopy changed since, and what the operator changed in the copies.
`merge` makes that merge where git can, three ways, and writes nothing where any file conflicts. A chore installed
before the record was kept is compared as installed against shipped now, which cannot tell the two apart, and says so.

The model canopy writes into an installed agent each time the chore runs (`install.write_model`) is canopy's, not an
edit, so it is taken out of the copy before any comparison.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, assert_never

from pydantic import ValidationError

from canopy.chores import install
from canopy.core import db, hostgit
from canopy.infra import resources
from canopy.runtime import definitions
from canopy.runtime.agents import DefinitionsError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from canopy.core.workspace import Workspace
    from canopy.infra import procs

#: What `diff` says for a side that changed nothing.
_UNCHANGED: Final = "(no change)\n"
#: The label of the side of a diff that is what canopy ships now.
_SHIPPED: Final = "shipped"


class MergeError(Exception):
    """An installed example chore cannot be merged with the one canopy ships: there is nothing to merge it from."""


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
    if origin is not None and origin.agent_file is not None:
        # The copy the record names, where it is there, ahead of any other file the operator put beside it.
        copied.sort(key=lambda path: path.name != origin.agent_file)
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


@dataclass(frozen=True)
class Merged:
    """What merging canopy's change into an installed example chore did."""

    #: The copies the merge rewrote, none when canopy changed nothing since the install.
    written: Sequence[Path]
    #: Each file whose merge conflicts, by name, with how many conflicts, as `git merge-file` counts them; when any
    #: does, nothing was written.
    conflicts: Mapping[str, int]
    #: Whether the record now names what canopy ships, where it named an older version: false when canopy changed
    #: nothing since the install, or a file conflicts.
    advanced: bool = False


def merge(ws: Workspace, name: str, runner: procs.Runner) -> Merged:
    """Merge what canopy changed in example chore `name` since it was installed in `ws` into the copies there.

    Each file canopy changed is merged three ways: from the record of what it was installed from, to what canopy ships
    now, into the copy, keeping the operator's edits. A copy the operator left alone becomes canopy's whole. Only when
    every file merges cleanly are the copies written, and the record then names what canopy ships now. The chore's
    table is left as it is: the record does not keep the table it was installed with, so there is no change to merge.

    Returns:
        What was written, or the files that conflict, with nothing written.

    Raises:
        MergeError: the chore is not installed, was installed before canopy kept a record, canopy no longer ships it,
            canopy changed which agent it runs, the operator removed its agent, or git cannot merge a file.
        OSError: a copy or the record cannot be read or written.
    """
    drift = _mergeable(ws, name)
    agents = ws.state_dir / install.AGENTS_DIR / name / definitions.AGENTS_SUBDIR
    if drift.standing is Standing.CURRENT:
        return Merged((), {})
    merged: dict[Path, str] = {}
    conflicts: dict[str, int] = {}
    for i, file in enumerate(drift.files):
        text = _merged(file, runner)
        if isinstance(text, int):
            conflicts[file.name] = text
        elif text is not None and text != file.installed:
            merged[(ws.state_dir / install.PROMPTS_DIR if i == 0 else agents) / file.name] = text
    if conflicts:
        return Merged((), conflicts)
    for path in merged:
        _check_utf8(path)
    for path, text in merged.items():
        install.replace_private(path, text)
    prompt, agent = drift.files[0], drift.files[1] if len(drift.files) > 1 else None
    install.write_origin(
        ws,
        name,
        install.Origin(
            version=db.CANOPY_VERSION,
            prompt=prompt.shipped or "",
            agent_file=agent.name if agent is not None and agent.shipped is not None else None,
            agent=agent.shipped if agent is not None else None,
        ),
    )
    return Merged(tuple(merged), {}, advanced=True)


def moved(ws: Workspace, name: str) -> Drift | None:
    """Return how example chore `name`, installed in `ws`, has moved apart from the one canopy ships, if it has.

    For a reader that lists every chore, `canopy status` and the chore's page, which must not fail on one: a copy or
    record that cannot be read is as good as unknown.

    Returns:
        Its three ways when it stands other than current, or None: current, not installed, not readable, or no longer
        shipped by canopy, which has no newer version to point at and whose `canopy chore diff` refuses it.
    """
    if name not in install.available():
        return None
    try:
        found = of(ws, name)
    except OSError:
        return None
    return found if found is not None and found.standing is not Standing.CURRENT else None


def describe(standing: Standing, name: str) -> str:
    """Return `standing` as `canopy chore install` lists it beside chore `name`.

    Returns:
        A few words, with the command that shows more when the chore has moved apart from canopy's.
    """
    said = moved_text(standing, name)
    return "installed" if said is None else f"installed; {said}"


def moved_text(standing: Standing, name: str) -> str | None:
    """Return how chore `name` has moved apart from canopy's, as `canopy status` says it after the chore's line.

    Returns:
        A few words with the command that shows more, or None when it stands current.
    """
    match standing:
        case Standing.CURRENT:
            return None
        case Standing.CHANGED:
            return f"canopy ships a newer version, see `canopy chore diff {name}`"
        case Standing.DIFFERS:
            return f"differs from the version canopy ships, see `canopy chore diff {name}`"
        case _:
            assert_never(standing)


def _mergeable(ws: Workspace, name: str) -> Drift:
    """Return installed example chore `name`'s three ways, once it is sure there is something a merge can start from.

    Raises:
        MergeError: the chore is not installed, was installed before canopy kept a record, or the agent copy the record
            names is gone.
    """
    drift = of(ws, name)
    if drift is None:
        raise MergeError(f"chore {name} is not installed here; `canopy chore install {name}` installs it")
    if drift.installed_by is None:
        raise MergeError(
            f"chore {name} was installed before canopy kept what it installed it from, so there is nothing to merge "
            f"from; `canopy chore diff {name}` shows your copy against canopy's",
        )
    origin = _origin(ws.state_dir / install.ORIGINS_DIR / f"{name}.json")
    agents = ws.state_dir / install.AGENTS_DIR / name / definitions.AGENTS_SUBDIR
    if origin is not None and origin.agent_file is not None and not (agents / origin.agent_file).is_file():
        # Said before anything else: another file beside it would otherwise read as an agent canopy renamed.
        raise MergeError(f"your copy of {origin.agent_file} is gone; installing again puts canopy's back")
    return drift


def _merged(file: File, runner: procs.Runner) -> str | int | None:
    """Return `file`'s copy with canopy's change since the install merged in, or how many conflicts that merge has.

    Returns:
        The merged text; the number of conflicts; or None when canopy changed nothing and there is no copy to keep.

    Raises:
        MergeError: canopy ships it under another name now, or has started or stopped shipping it, the operator removed
            a copy canopy changed, or git cannot merge it.
    """
    base, theirs, ours = file.installed_from, file.shipped, file.installed
    if file.shipped_name is not None or (base is None) != (theirs is None):
        raise MergeError(
            f"canopy changed which agent the chore runs ({file.name}), which a merge does not carry; `canopy chore "
            "diff` shows both sides, and installing again puts canopy's back",
        )
    if ours is None:
        if base is None:
            return None
        raise MergeError(f"your copy of {file.name} is gone; installing again puts canopy's back")
    if base is None or theirs is None or base == theirs:
        return ours
    if ours in {base, theirs}:
        return theirs
    result = hostgit.merge_file(runner, ours, base, theirs, labels=("yours", "installed-from", _SHIPPED))
    if result is None:
        raise MergeError(f"git could not merge {file.name}")
    return result.conflicts or result.text


def _check_utf8(path: Path) -> None:
    """Make sure the copy at `path`, which a merge is about to replace, is UTF-8, as its text was read to merge.

    Raises:
        MergeError: it is not, so a merge would write the replacement characters it was read with over its bytes.
    """
    try:
        path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise MergeError(f"your copy of {path.name} is not UTF-8, so a merge would change bytes you wrote") from None


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
