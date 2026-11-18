"""The operator's checklists (DESIGN §42): a list per repository of rules no linter checks, asked of a worker's diff.

A list is a file, `<repo>.md`, in the operator's `paths.checklists` directory, for the mapped repository of that name;
a repository without one is never asked. Each item opens with a `## <id>` heading, then, before its rule, an optional
`paths:` line of the paths it is about, compared as `high_impact_paths` are, an optional `severity:` line, which only
the checklist review reads, an optional `status:` line, and an optional `note:` line for the operator. An item whose
status is `retired` stays in the file, and its past answers stay counted, but no run hears it: it is left out of the
text a run is given, and a list whose every item is retired is no list. A list is instructions in every run it
reaches, so it is bounded and holds none of the characters a persona may not (DESIGN §31), and it is parsed here, so a
run's answers can be held to its ids. A list canopy cannot use refuses the run (`bad_prompt`), never runs it without
the list.

Before a worker run that may push starts, or a one-off task's (§36), the list of each of its repositories is written
to its answers directory (§41), a file to a repository, where canopy's `pre-push` hook in that repository's slot finds
it, to hold the worker's push and print it (`commit_hooks`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from canopy.core import memory_text, workspace
from canopy.core.vocab import RunKind
from canopy.infra import logs

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from canopy.core.config import Config

#: A list's file is its repository's name with this suffix.
SUFFIX: Final = ".md"
#: The most bytes a list's file may hold: it reaches every worker run in its repository that pushes.
MAX_BYTES: Final = 16 * 1024
#: The directory in a run's answers directory that holds its repositories' lists, `<repo>.md` each, for canopy's hook.
DIR: Final = "checklists"
#: How much an item that fails weighs in the checklist review, as a review's finding does.
type Severity = Literal["blocking", "major", "minor"]
#: Every severity an item may name, gravest first.
SEVERITIES: Final[tuple[Severity, ...]] = ("blocking", "major", "minor")
#: An item's severity unless its `severity:` line says another.
DEFAULT_SEVERITY: Final[Severity] = "minor"
#: Whether an item is asked: an `active` one is, a `retired` one stays in its file, unasked, so its counts read on.
type Status = Literal["active", "retired"]
#: Every status an item may name.
STATUSES: Final[tuple[Status, ...]] = ("active", "retired")
#: The kinds of worker run that may push, and so hear their repositories' lists; a task's run, of no kind, hears its.
REMINDED: Final[frozenset[RunKind]] = frozenset({RunKind.IMPLEMENT, RunKind.RESUME})
#: An item's heading, which names its id.
_HEADING: Final = re.compile(r"## (.*)")
#: An item's id: a word of letters, digits, `-`, `_`, and `.`, which a run's answer names as a key.
_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
#: A line an item may open with, before its rule: its key and its value.
_FIELD: Final = re.compile(r"(paths|severity|status|note):[ \t]*(.*)")


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
    #: The rule in the operator's words, with what passes and what fails; a retired item's may be empty.
    rule: str
    #: Its `status:` line's, else `active`.
    status: Status = "active"
    #: The operator's own word on the item, such as why it was retired; empty when it has none.
    note: str = ""

    @property
    def retired(self) -> bool:
        """Whether the item is retired: kept in its file, asked of no run."""
        return self.status == "retired"


@dataclass(frozen=True)
class Checklist:
    """A repository's list, as a run gets it."""

    repo: str
    #: The items a run is asked, in the file's order: every one but the retired.
    items: Sequence[Item]
    #: The file's text without its surrounding blank lines or its retired items, as the worker reads it.
    text: str
    #: The items the operator retired, in the file's order, asked of no run.
    retired: Sequence[Item] = ()

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
    """Return the list of each of `repos` that has one with an item still asked, in their order.

    Returns:
        The lists; none when no repository has one, or every item of its list is retired.

    Raises:
        ChecklistError: a file is one canopy would not put in a run.
    """
    return [found for repo in repos if (found := load(config, repo)) is not None and found.items]


def retired_items(config: Config, repos: Iterable[str]) -> set[tuple[str, str]]:
    """Return the items of `repos`' lists the operator has retired, read now, by repository and id.

    For marking counts the journal holds, so a list canopy cannot use, or a repository without one, retires nothing.

    Returns:
        Each retired item's repository and id.
    """
    found: set[tuple[str, str]] = set()
    for repo in repos:
        try:
            loaded = load(config, repo)
        except ChecklistError:
            continue
        if loaded is not None:
            found.update((repo, item.id) for item in loaded.retired)
    return found


def parse(where: str, text: str) -> tuple[list[Item], str, list[Item]]:
    """Parse a list's text into its items, refusing one that is not a list.

    Returns:
        The items a run is asked, in order; the text without its surrounding blank lines or the retired items'
        sections, which is all a run reads; and the retired items, in order.

    Raises:
        ChecklistError: it holds no item, text before its first, an id that is not a word or is repeated, an item
            still asked with no rule, a `paths:` entry that is not a path from the repository's root, a severity a
            finding cannot take, or a status that is none of `STATUSES`.
    """
    items: list[Item] = []
    # Each item's lines, its heading's among them, so a retired one's can be left out of what a run reads.
    sections: list[list[str]] = []
    heading: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        matched = _HEADING.fullmatch(line.rstrip())
        if matched is not None:
            if heading is not None:
                items.append(_item(where, heading, sections[-1][1:]))
            heading = matched[1].strip()
            sections.append([line])
            if not _ID.fullmatch(heading):
                raise ChecklistError(f"{where}: line {number}: an item's id is a word, {_ID.pattern}, not {heading!r}")
            if heading in {item.id for item in items}:
                raise ChecklistError(f"{where}: line {number}: item {heading} is there twice")
        elif heading is None:
            if line.strip():
                raise ChecklistError(f"{where}: line {number}: each item opens with a '## <id>' heading")
        else:
            sections[-1].append(line)
    if heading is None:
        raise ChecklistError(f"{where}: no item, each opening with a '## <id>' heading")
    items.append(_item(where, heading, sections[-1][1:]))
    asked = [item for item in items if not item.retired]
    if len(asked) == len(items):
        return asked, text.strip(), []
    kept = [line for item, lines in zip(items, sections, strict=True) if not item.retired for line in lines]
    return asked, "\n".join(kept).strip(), [item for item in items if item.retired]


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
        ChecklistError: a field is given twice or is not one, or an item still asked has no rule.
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
    named_status = fields.get("status", "active")
    status = next((s for s in STATUSES if s == named_status), None)
    if status is None:
        raise ChecklistError(f"{where}: item {id_}: status is one of {', '.join(STATUSES)}, not {named_status!r}")
    # A retired item is asked of no run, so its rule may already be gone: only its id and its counts are left.
    if not rule and status != "retired":
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
    return Item(id_, tuple(paths), severity, rule, status, fields.get("note", ""))
