"""An epic plan's ids and breakdown, read from its Markdown, and what one approval changed from the last (§43).

The ids and the breakdown are the one part of an epic's plan canopy reads, from the file as the operator approved
it, in the shape its outline fixes: each requirement a list item `- **R<n>.** ...` under `## Requirements`, each
contract `- **C<n>.** ...` under `## Contracts`, and each entry a `### B<n>. Title` under `## Breakdown`, whose body
holds one line for each field:

    - Covers: R1, R2
    - Provides: C1
    - Uses: none
    - Repositories: api, web
    - After: B1
    - Trivial: no

`Trivial` is `no`, or `yes` with its reason after a comma. The plan is model text (TRUST_MODEL T1), edited by the
operator until approved: these are data, used only to compare one approval with the next and to route entries to
members, never an instruction to the harness. A file canopy cannot read in this shape is refused whole, never read in
part, so no entry is routed on a guess. Everything else in the plan, its goal, decisions, and prose, is never read here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from collections.abc import Set as AbstractSet

#: The most ids of one kind a plan may name: a plan is bounded, and an epic's breakdown is shallow by rule.
MAX_IDS = 200
#: The longest a trivial entry's reason may be.
MAX_REASON = 300
#: An id's kind, the letter it starts with: a requirement, a contract, or a breakdown entry.
type Kind = Literal["R", "C", "B"]

#: The sections canopy reads, by their headings, lower-cased.
REQUIREMENTS = "requirements"
CONTRACTS = "contracts"
BREAKDOWN = "breakdown"
#: The fields of a breakdown entry, each on its own line, in any order, each once.
FIELDS = ("covers", "provides", "uses", "repositories", "after", "trivial")


class OutlineError(Exception):
    """The plan's ids or breakdown cannot be read in the outline's shape; `reason` says where."""

    def __init__(self, reason: str) -> None:
        """Say what is wrong, naming the section or id."""
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Entry:
    """A breakdown entry: a ticket the plan proposes, what it covers, and what it comes after."""

    id: str
    title: str
    #: The requirements it covers.
    covers: AbstractSet[str]
    #: The contracts it provides and those it uses.
    provides: AbstractSet[str]
    uses: AbstractSet[str]
    #: The repositories it works in, by their names in the map.
    repos: AbstractSet[str]
    #: The entries it comes after.
    after: AbstractSet[str]
    #: Why the plan marks it trivial; None when it does not.
    trivial: str | None
    #: Its whole text, whitespace collapsed: what a later approval compares.
    text: str

    def cites(self) -> AbstractSet[str]:
        """Return the requirements and contracts it covers, provides, or uses."""
        return self.covers | self.provides | self.uses


@dataclass(frozen=True)
class Outline:
    """What canopy reads of an epic's plan: each id with its text, and the breakdown's entries."""

    #: Each requirement's and contract's text, whitespace collapsed, by id.
    requirements: Mapping[str, str]
    contracts: Mapping[str, str]
    #: The breakdown's entries, by id, in the plan's order.
    entries: Mapping[str, Entry]

    def ids(self) -> AbstractSet[str]:
        """Return every id the plan holds, of every kind."""
        return frozenset(self.requirements) | frozenset(self.contracts) | frozenset(self.entries)

    def text_of(self, id_: str) -> str | None:
        """Return the text an id holds in this plan, or None when it holds no such id."""
        if id_ in self.entries:
            return self.entries[id_].text
        return self.requirements.get(id_, self.contracts.get(id_))


@dataclass(frozen=True)
class Change:
    """What one approved plan changed from the one approved before it: ids added, removed, or whose text changed."""

    added: AbstractSet[str] = field(default_factory=frozenset)
    removed: AbstractSet[str] = field(default_factory=frozenset)
    changed: AbstractSet[str] = field(default_factory=frozenset)

    def ids(self) -> AbstractSet[str]:
        """Return every id the change touched."""
        return self.added | self.removed | self.changed


def read(text: str, *, repos: AbstractSet[str] | None = None) -> Outline:
    """Read an epic plan's ids and breakdown from its Markdown `text`, in the outline's shape (DESIGN §43).

    `repos`, when given, are the epic's repositories, the only ones an entry may name.

    Returns:
        The outline.

    Raises:
        OutlineError: a section is missing or repeated, an id is malformed, repeated, or of the wrong kind for its
            section, an entry's field is missing, repeated, or unreadable, or a reference names an id the plan does not
            hold or a repository not in `repos`.
    """
    sections = _sections(text)
    requirements = _items(sections[REQUIREMENTS], "R")
    contracts = _items(sections[CONTRACTS], "C")
    entries = _entries(sections[BREAKDOWN])
    _check_references(requirements, contracts, entries, repos)
    return Outline(requirements=requirements, contracts=contracts, entries=entries)


def compare(before: Outline, after: Outline) -> Change:
    """Return what `after`, a plan being approved, changed from `before`, the plan approved before it (DESIGN §43).

    Returns:
        The ids `after` adds, those it removes, and those whose text it changed.
    """
    old, new = before.ids(), after.ids()
    changed = frozenset(i for i in old & new if before.text_of(i) != after.text_of(i))
    return Change(added=frozenset(new - old), removed=frozenset(old - new), changed=changed)


def reused(after: Outline, retired: AbstractSet[str]) -> list[str]:
    """Return the ids `after` holds that an earlier approved plan removed: an id is never used again (DESIGN §43).

    `retired` holds every id some approved plan held that the latest approved one does not.

    Returns:
        Those ids, sorted.
    """
    return sorted(after.ids() & retired, key=_order)


def reaches(change: Change, entries: AbstractSet[str], *, before: Outline, after: Outline) -> bool:
    """Whether `change` reaches a member that fulfils `entries`, by the plans `before` and `after` it (DESIGN §43).

    A member is reached when one of its entries changed, or covers, provides, or uses a changed id, as either plan
    says. A member of no entry is reached by every change, since canopy cannot tell which ids it relies on.

    Returns:
        True when it is reached; never for a change that touched nothing.
    """
    touched = change.ids()
    if not touched:
        return False
    if not entries:
        return True
    for entry_id in entries:
        if entry_id in touched:
            return True
        for plan in (before, after):
            entry = plan.entries.get(entry_id)
            if entry is not None and entry.cites() & touched:
                return True
    return False


def trivial(outline: Outline, entries: AbstractSet[str]) -> bool:
    """Whether a member that fulfils `entries` is trivial: it fulfils one or more, and the plan marks each (§43).

    Returns:
        True only when every entry is in the plan and marked trivial; a member of no entry never is.
    """
    return bool(entries) and all(e in outline.entries and outline.entries[e].trivial is not None for e in entries)


# The outline's shapes. A fence opens and closes a code block, whose lines are never read as structure.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^[-*+]\s+(.*)$")
_ID_ITEM = re.compile(r"^\*\*([RCB])([1-9][0-9]{0,3})\.?\*\*\.?\s*(.*)$")
_ENTRY = re.compile(r"^B([1-9][0-9]{0,3})\.?\s+(\S.*)$")
_FIELD = re.compile(r"^[-*+]\s+([A-Za-z]+)\s*:\s*(.*)$")
_LIST_SEPARATOR = re.compile(r"\s*,\s*")
_NONE = frozenset({"none", "-", "—", "n/a"})
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _sections(text: str) -> dict[str, list[str]]:
    """Split the plan into its level-two sections, outside code blocks, keeping the three canopy reads.

    Returns:
        Each read section's lines, by its heading lower-cased.

    Raises:
        OutlineError: one of the three is missing or appears twice.
    """
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in _outside_code(text):
        heading = _HEADING.match(line)
        if heading is None or len(heading.group(1)) > 2:  # noqa: PLR2004  (a level-one or level-two heading)
            if current is not None:
                current.append(line)
            continue
        name = heading.group(2).strip().lower()
        if name not in (REQUIREMENTS, CONTRACTS, BREAKDOWN):
            current = None
        elif name in found:
            raise OutlineError(f"the plan has `## {heading.group(2).strip()}` twice")
        else:
            current = []
            found[name] = current
    for name in (REQUIREMENTS, CONTRACTS, BREAKDOWN):
        if name not in found:
            raise OutlineError(f"the plan has no `## {name.capitalize()}` section")
    return found


def _outside_code(text: str) -> list[str]:
    """Return `text`'s lines with each line of a fenced code block, its fences included, made blank.

    So nothing a plan quotes in a code block reads as a heading, an id, or a field.
    """
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        opened = _FENCE.match(line)
        if fence is None and opened is not None:
            fence = opened.group(1)
            lines.append("")
        elif fence is not None:
            if opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
            lines.append("")
        else:
            lines.append(line)
    return lines


def _items(lines: Sequence[str], kind: Kind) -> dict[str, str]:
    """Read a section of ids, each a top-level list item opening with its bold id.

    Prose before the list is allowed; every top-level item must carry an id of `kind`. An item's text runs until the
    next top-level item or the section's end.

    Returns:
        Each id's text, whitespace collapsed, in the plan's order.

    Raises:
        OutlineError: an item has no id, one of another kind, an id repeats, or there are more than `MAX_IDS`.
    """
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        item = _ITEM.match(line)
        if item is None:
            if current is not None and line.strip():
                current.append(line.strip())
            continue
        marked = _ID_ITEM.match(item.group(1))
        if marked is None:
            raise OutlineError(f"an item under {_section_of(kind)} has no id: {_cut(item.group(1))!r}")
        id_ = f"{marked.group(1)}{marked.group(2)}"
        if marked.group(1) != kind:
            raise OutlineError(f"{id_} is under {_section_of(kind)}, whose ids are {kind}<n>")
        if id_ in found:
            raise OutlineError(f"{id_} appears twice")
        if len(found) == MAX_IDS:
            raise OutlineError(f"{_section_of(kind)} holds more than {MAX_IDS} ids")
        current = found[id_] = [marked.group(3)]
    return {id_: _collapse(parts) for id_, parts in found.items()}


def _entries(lines: Sequence[str]) -> dict[str, Entry]:
    """Read the breakdown's entries, each a level-three heading `B<n>. Title` and its fields.

    Returns:
        The entries, by id, in the plan's order.

    Raises:
        OutlineError: a level-three heading is not an entry's, an entry repeats or has an unreadable field, or there
            are more than `MAX_IDS`.
    """
    bodies: dict[str, tuple[str, list[str]]] = {}
    current: list[str] | None = None
    for line in lines:
        heading = _HEADING.match(line)
        # A level-three heading opens an entry; a deeper one is part of the entry it is in.
        if heading is None or len(heading.group(1)) != 3:  # noqa: PLR2004
            if current is not None:
                current.append(line)
            continue
        entry = _ENTRY.match(heading.group(2))
        if entry is None:
            raise OutlineError(f"a heading under ## Breakdown is no entry's B<n>. Title: {_cut(heading.group(2))!r}")
        id_ = f"B{entry.group(1)}"
        if id_ in bodies:
            raise OutlineError(f"{id_} appears twice")
        if len(bodies) == MAX_IDS:
            raise OutlineError(f"## Breakdown holds more than {MAX_IDS} entries")
        current = []
        bodies[id_] = (entry.group(2).strip(), current)
    return {id_: _entry(id_, title, body) for id_, (title, body) in bodies.items()}


def _entry(id_: str, title: str, body: Sequence[str]) -> Entry:
    """Read entry `id_`'s fields from its `body`.

    Returns:
        The entry.

    Raises:
        OutlineError: a field is missing, repeated, or unreadable.
    """
    values: dict[str, str] = {}
    for line in body:
        found = _FIELD.match(line.strip())
        if found is None or found.group(1).lower() not in FIELDS:
            continue
        name = found.group(1).lower()
        if name in values:
            raise OutlineError(f"{id_} gives {name.capitalize()} twice")
        values[name] = found.group(2).strip()
    missing = [name.capitalize() for name in FIELDS if name not in values]
    if missing:
        raise OutlineError(f"{id_} has no {', '.join(missing)}: each entry gives every field, `none` for an empty one")
    return Entry(
        id=id_,
        title=title,
        covers=_ids(id_, "Covers", values["covers"], "R"),
        provides=_ids(id_, "Provides", values["provides"], "C"),
        uses=_ids(id_, "Uses", values["uses"], "C"),
        repos=_repos(id_, values["repositories"]),
        after=_ids(id_, "After", values["after"], "B"),
        trivial=_trivial(id_, values["trivial"]),
        text=_collapse([title, *body]),
    )


def _ids(id_: str, name: str, value: str, kind: Kind) -> frozenset[str]:
    """Read a field's list of ids of `kind`, or none.

    Returns:
        The ids.

    Raises:
        OutlineError: a value is not an id of `kind`.
    """
    found: set[str] = set()
    for part in _parts(value):
        if not re.fullmatch(rf"{kind}[1-9][0-9]{{0,3}}", part):
            raise OutlineError(f"{id_}'s {name} names {_cut(part)!r}, which is no {kind}<n>")
        found.add(part)
    return frozenset(found)


def _repos(id_: str, value: str) -> frozenset[str]:
    """Read an entry's repositories, at least one.

    Returns:
        Their names.

    Raises:
        OutlineError: it names none, or one that is not a plain name.
    """
    names = _parts(value)
    if not names:
        raise OutlineError(f"{id_} names no repository")
    for name in names:
        if not _REPO.fullmatch(name):
            raise OutlineError(f"{id_}'s Repositories names {_cut(name)!r}, which is no repository's name")
    return frozenset(names)


def _trivial(id_: str, value: str) -> str | None:
    """Read an entry's `Trivial`: `no`, or `yes` with its reason after a comma.

    Returns:
        The reason when it is trivial; None when it is not.

    Raises:
        OutlineError: it is neither, or `yes` without a reason, or a reason past `MAX_REASON` characters.
    """
    answer, _, reason = value.partition(",")
    answer = answer.strip().lower()
    if answer == "no":
        return None
    if answer != "yes":
        raise OutlineError(f"{id_}'s Trivial is {_cut(value)!r}: it is `no`, or `yes, ` and the reason")
    reason = " ".join(reason.split())
    if not reason:
        raise OutlineError(f"{id_} is marked trivial with no reason")
    if len(reason) > MAX_REASON:
        raise OutlineError(f"{id_}'s reason for being trivial is over {MAX_REASON} characters")
    return reason


def _check_references(
    requirements: Mapping[str, str],
    contracts: Mapping[str, str],
    entries: Mapping[str, Entry],
    repos: AbstractSet[str] | None,
) -> None:
    """Refuse a reference to an id the plan does not hold, or a repository not the epic's.

    Raises:
        OutlineError: one names an id missing from its section, an entry comes after itself, or names a repository
            outside `repos`.
    """
    for entry in entries.values():
        for name, refs, known in (
            ("Covers", entry.covers, requirements),
            ("Provides", entry.provides, contracts),
            ("Uses", entry.uses, contracts),
            ("After", entry.after, entries),
        ):
            missing = sorted((r for r in refs if r not in known), key=_order)
            if missing:
                raise OutlineError(f"{entry.id}'s {name} names {', '.join(missing)}, which the plan does not hold")
        if entry.id in entry.after:
            raise OutlineError(f"{entry.id} comes after itself")
        if repos is not None:
            outside = sorted(entry.repos - repos)
            if outside:
                raise OutlineError(f"{entry.id} names {', '.join(outside)}, which is not the epic's repository")


def _parts(value: str) -> list[str]:
    """Split a field's comma-separated value; `none` and the like are an empty list.

    Returns:
        Its parts, each stripped, in order, without repeats.
    """
    if value.strip().lower() in _NONE:
        return []
    return list(dict.fromkeys(p for p in _LIST_SEPARATOR.split(value.strip()) if p))


def _collapse(parts: Iterable[str]) -> str:
    """Return `parts` joined with their whitespace collapsed, so a rewrap is no change."""
    return " ".join(" ".join(parts).split())


def _section_of(kind: Kind) -> str:
    """Return the heading of the section whose ids are of `kind`."""
    return "## Requirements" if kind == "R" else "## Contracts" if kind == "C" else "## Breakdown"


def _order(id_: str) -> tuple[str, int]:
    """Return the key that sorts ids by kind, then number, so `R2` comes before `R10`."""
    return id_[0], int(id_[1:])


def _cut(text: str, limit: int = 60) -> str:
    """Return `text` cut for a reason, so a long line of model text does not fill it."""
    return text if len(text) <= limit else f"{text[:limit]}..."
