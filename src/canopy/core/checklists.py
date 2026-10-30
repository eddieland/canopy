"""The operator's checklists (DESIGN §42): a list per repository of rules no linter checks, asked of a worker's diff.

A list is a file, `<repo>.md`, in the operator's `paths.checklists` directory, for the mapped repository of that name;
a repository without one is never asked. Each item opens with a `## <id>` heading, then, before its rule, an optional
`paths:` line of the paths it is about, compared as `high_impact_paths` are, and an optional `severity:` line, which
only the checklist review reads. A list is instructions in every run it reaches, so it is bounded and holds none of the
characters a persona may not (DESIGN §31), and it is parsed here, so a run's answers can be held to its ids. A list
canopy cannot use refuses the run (`bad_prompt`), never runs it without the list.

Before a worker run that may push starts, the list of each of its repositories is written to its answers directory
(§41), a file to a repository, where canopy's `pre-push` hook in that repository's slot finds it, to hold the worker's
push and print it (`commit_hooks`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from canopy.core import memory_text, workspace
from canopy.core.vocab import RunKind
from canopy.infra import logs

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from canopy.core.config import Config

#: A list's file is its repository's name with this suffix.
SUFFIX = ".md"
#: The most bytes a list's file may hold: it reaches every worker run in its repository that pushes.
MAX_BYTES = 16 * 1024
#: The directory in a run's answers directory that holds its repositories' lists, `<repo>.md` each, for canopy's hook.
DIR = "checklists"
#: How much an item that fails weighs in the checklist review, as a review's finding does.
Severity = Literal["blocking", "major", "minor"]
#: Every severity an item may name, gravest first.
SEVERITIES: tuple[Severity, ...] = ("blocking", "major", "minor")
#: An item's severity unless its `severity:` line says another.
DEFAULT_SEVERITY: Severity = "minor"
#: The kinds of worker run that may push, and so hear their repositories' lists.
REMINDED: frozenset[RunKind] = frozenset({RunKind.IMPLEMENT, RunKind.RESUME})
#: An item's heading, which names its id.
_HEADING = re.compile(r"## (.*)")
#: An item's id: a word of letters, digits, `-`, `_`, and `.`, which a run's answer names as a key.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
#: A line an item may open with, before its rule: its key and its value.
_FIELD = re.compile(r"(paths|severity):[ \t]*(.*)")


class ChecklistError(Exception):
    """A repository's list cannot be used; the message says why, naming the file."""


@dataclass(frozen=True)
class Item:
    """One item of a list: a rule asked of a diff."""

    #: The item's id, unique in its list, which a run's answer names.
    id: str
    #: The paths it is about, each compared as a `high_impact_paths` entry is; empty for every path.
    paths: Sequence[str]
    severity: Severity
    #: The rule in the operator's words, with what passes and what fails.
    rule: str


@dataclass(frozen=True)
class Checklist:
    """A repository's list, as a run gets it."""

    repo: str
    items: Sequence[Item]
    #: The file's text without its surrounding blank lines, as the worker reads it.
    text: str

    def ids(self) -> list[str]:
        """Return the ids of the list's items, in its order."""
        return [item.id for item in self.items]


def reminded(kind: str) -> bool:
    """Return whether a worker run of `kind` hears its repositories' lists: one that may push, public or private."""
    return kind in REMINDED


def load(config: Config, repo: str) -> Checklist | None:
    """Return `repo`'s list, read now, or None when it has none.

    Returns:
        The list, or None when `paths.checklists` is unset or holds no file for `repo`.

    Raises:
        ChecklistError: its file is one canopy would not put in a run.
    """
    if config.paths.checklists is None:
        return None
    path = config.paths.checklists / f"{repo}{SUFFIX}"
    if not path.exists():
        return None
    return Checklist(repo, *parse(f"the checklist of {repo} at {path}", _read(repo, path)))


def for_repos(config: Config, repos: Iterable[str]) -> list[Checklist]:
    """Return the list of each of `repos` that has one, in their order.

    Returns:
        The lists; none when no repository has one.

    Raises:
        ChecklistError: a file is one canopy would not put in a run.
    """
    return [found for repo in repos if (found := load(config, repo)) is not None]


def parse(where: str, text: str) -> tuple[list[Item], str]:
    """Parse a list's text into its items, refusing one that is not a list.

    Returns:
        Its items, in order, and the text without its surrounding blank lines.

    Raises:
        ChecklistError: it holds no item, text before its first, an id that is not a word or is repeated, an item with
            no rule, a `paths:` entry that is not a path from the repository's root, or a severity a finding cannot
            take.
    """
    items: list[Item] = []
    heading: str | None = None
    body: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        matched = _HEADING.fullmatch(line.rstrip())
        if matched is not None:
            if heading is not None:
                items.append(_item(where, heading, body))
            heading = matched[1].strip()
            body = []
            if not _ID.fullmatch(heading):
                raise ChecklistError(f"{where}: line {number}: an item's id is a word, {_ID.pattern}, not {heading!r}")
            if heading in {item.id for item in items}:
                raise ChecklistError(f"{where}: line {number}: item {heading} is there twice")
        elif heading is None:
            if line.strip():
                raise ChecklistError(f"{where}: line {number}: each item opens with a '## <id>' heading")
        else:
            body.append(line)
    if heading is None:
        raise ChecklistError(f"{where}: no item, each opening with a '## <id>' heading")
    items.append(_item(where, heading, body))
    return items, text.strip()


def file_of(answers: Path, repo: str) -> Path:
    """Return where the answers directory at `answers` holds `repo`'s list, if the run has one."""
    return answers / DIR / f"{repo}{SUFFIX}"


def write(answers: Path, lists: Iterable[Checklist]) -> None:
    """Write each of `lists` to the answers directory at `answers`, for canopy's hook; nothing when there are none.

    Each file holds the list's text, which its bound holds to `MAX_BYTES` and a line feed.

    Raises:
        OSError: a file cannot be written.
    """
    for found in lists:
        target = file_of(answers, found.repo)
        target.parent.mkdir(mode=0o700, exist_ok=True)
        logs.write_private(target, f"{found.text}\n")


def given(answers: Path, repos: Iterable[str]) -> list[Checklist]:
    """Return the lists of `repos` the run whose answers directory is at `answers` was given, as `write` wrote them.

    Its answers are held to these, not to the operator's files as they are now, which may have changed since it began.

    Returns:
        Each list written for the run, in `repos`' order; none for a repository it got no list of, or whose file can no
        longer be read as one.
    """
    found: list[Checklist] = []
    for repo in repos:
        path = file_of(answers, repo)
        if not path.is_file():
            continue
        try:
            found.append(Checklist(repo, *parse(f"the checklist of {repo} at {path}", _read(repo, path))))
        except ChecklistError:
            continue
    return found


def _read(repo: str, path: Path) -> str:
    """Return a list's text, refusing a file canopy would not put in a run.

    Raises:
        ChecklistError: the file cannot be read, is not UTF-8, is over `MAX_BYTES`, or holds a character that hides
            text: one `memory_text.hidden_char` names, but a line feed or a tab.
    """
    where = f"the checklist of {repo} at {path}"
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ChecklistError(f"{where} cannot be read: {e}") from e
    if len(data) > MAX_BYTES:
        raise ChecklistError(f"{where} is {len(data)} bytes, over {MAX_BYTES}")
    hidden = next((c for c in text if memory_text.hidden_char(c) and c not in "\n\t"), None)
    if hidden is not None:
        raise ChecklistError(f"{where} holds U+{ord(hidden):04X}, a character that hides text")
    return text


def _item(where: str, id_: str, body: Sequence[str]) -> Item:
    """Return the item `id_` whose lines after its heading are `body`: its fields, then its rule.

    Raises:
        ChecklistError: a field is given twice or is not one, or the item has no rule.
    """
    fields: dict[str, str] = {}
    lines = list(body)
    while lines and (not lines[0].strip() or _FIELD.fullmatch(lines[0].strip())):
        matched = _FIELD.fullmatch(lines.pop(0).strip())
        if matched is None:
            continue
        if matched[1] in fields:
            raise ChecklistError(f"{where}: item {id_} has two '{matched[1]}:' lines")
        fields[matched[1]] = matched[2].strip()
    rule = "\n".join(lines).strip()
    if not rule:
        raise ChecklistError(f"{where}: item {id_} has no rule")
    paths: list[str] = []
    for entry in fields.get("paths", "").split(","):
        if not entry.strip():
            continue
        try:
            paths.append(workspace.impact_path(entry.strip()))
        except ValueError as e:
            raise ChecklistError(f"{where}: item {id_}: paths entry {entry.strip()!r} {e}") from e
    named = fields.get("severity", DEFAULT_SEVERITY)
    severity = next((s for s in SEVERITIES if s == named), None)
    if severity is None:
        raise ChecklistError(f"{where}: item {id_}: severity is one of {', '.join(SEVERITIES)}, not {named!r}")
    return Item(id_, tuple(paths), severity, rule)
