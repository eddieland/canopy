"""An epic plan's ids and breakdown, read in the outline's shape, and what an approval changed (DESIGN §43)."""

import pytest

from canopy.core import epic_outline
from canopy.core.epic_outline import Change, Outline, OutlineError

PLAN = """\
# Sessions in the new store

## Goal

Sessions survive a restart of the API, and the web app reads them from the new store.

## Requirements

Traced to the operator's words.

- **R1.** Sessions survive a restart of the API.
- **R2.** The web app reads a session from the new store,
  never from the old one.

## Contracts

- **C1.** The store's read interface: `get(id) -> Session | None`. Provided by B1; used by B2.

## Breakdown

### B1. Move the store

- Covers: R1
- Provides: C1
- Uses: none
- Repositories: api
- After: none
- Trivial: no

The store moves behind C1.

### B2. Read from the new store

- Covers: R2
- Provides: none
- Uses: C1
- Repositories: web
- After: B1
- Trivial: yes, a one-line change of the client's endpoint

```markdown
### B9. Not an entry: a code block
- **R9.** Nor a requirement.
```

## Decisions

## Out of scope

- **R7.** An id outside the sections canopy reads is prose.
"""


def read(text: str = PLAN, **kwargs: frozenset[str]) -> Outline:
    return epic_outline.read(text, **kwargs)


def edited(old: str, new: str, text: str = PLAN) -> str:
    assert old in text
    return text.replace(old, new)


# Reading


def test_a_plan_in_the_outline_s_shape_is_read() -> None:
    """Each id with its text, and each entry's fields, are read; a code block and other sections are not."""
    outline = read(repos=frozenset({"api", "web"}))
    assert outline.requirements == {
        "R1": "Sessions survive a restart of the API.",
        "R2": "The web app reads a session from the new store, never from the old one.",
    }
    assert list(outline.contracts) == ["C1"]
    assert list(outline.entries) == ["B1", "B2"]
    first, second = outline.entries["B1"], outline.entries["B2"]
    assert (first.title, first.covers, first.provides, first.uses) == ("Move the store", {"R1"}, {"C1"}, set())
    assert (first.repos, first.after, first.trivial) == ({"api"}, set(), None)
    assert (second.uses, second.after) == ({"C1"}, {"B1"})
    assert second.trivial == "a one-line change of the client's endpoint"
    assert "B9" not in outline.entries
    assert outline.ids() == {"R1", "R2", "C1", "B1", "B2"}


@pytest.mark.parametrize(
    ("old", "new", "said"),
    [
        ("## Contracts\n", "## Agreements\n", "the plan has no `## Contracts` section"),
        ("## Decisions\n", "## Requirements\n", "the plan has `## Requirements` twice"),
        ("- **R2.** The web", "- The web", "an item under ## Requirements has no id"),
        ("- **R2.** The web", "- **C2.** The web", "C2 is under ## Requirements, whose ids are R<n>"),
        ("- **R2.** The web", "- **R1.** The web", "R1 appears twice"),
        ("### B2. Read", "### Read", "a heading under ## Breakdown is no entry's B<n>. Title"),
        ("### B2. Read", "### B1. Read", "B1 appears twice"),
        ("- Uses: C1\n", "", "B2 has no Uses: each entry gives every field"),
        ("- Uses: C1\n", "- Uses: C1\n- Uses: C1\n", "B2 gives Uses twice"),
        ("- Covers: R2", "- Covers: R2, C1", "B2's Covers names 'C1', which is no R<n>"),
        ("- Covers: R2", "- Covers: R3", "B2's Covers names R3, which the plan does not hold"),
        ("- After: B1", "- After: B2", "B2 comes after itself"),
        ("- Repositories: web", "- Repositories: none", "B2 names no repository"),
        ("- Repositories: web", "- Repositories: ../web", "B2's Repositories names '../web'"),
        ("- Trivial: yes, a one-line", "- Trivial: maybe, a one-line", "B2's Trivial is \"maybe, a one-line"),
        (
            "- Trivial: yes, a one-line change of the client's endpoint",
            "- Trivial: yes",
            "B2 is marked trivial with no reason",
        ),
    ],
)
def test_a_plan_canopy_cannot_read_in_the_outline_s_shape_is_refused_whole(old: str, new: str, said: str) -> None:
    """A section, an id, a field, or a reference canopy cannot read refuses the plan, saying where."""
    with pytest.raises(OutlineError) as caught:
        read(edited(old, new))
    assert said in caught.value.reason


def test_an_entry_in_a_repository_not_the_epic_s_is_refused() -> None:
    """Given the epic's repositories, an entry naming another is refused."""
    with pytest.raises(OutlineError, match="B2 names web, which is not the epic's repository"):
        read(repos=frozenset({"api"}))


def test_a_heading_below_an_entry_s_is_part_of_it() -> None:
    """A level-four heading inside an entry is its text, not an entry of its own."""
    outline = read(edited("The store moves behind C1.", "#### Steps\n\nThe store moves behind C1."))
    assert list(outline.entries) == ["B1", "B2"]
    assert "Steps" in outline.entries["B1"].text


def test_a_diagram_before_the_first_entry_is_no_entry_s_text() -> None:
    """The breakdown's order drawn before its first entry, as the epic planner's prompt asks, is read as nothing."""
    diagram = "```mermaid\nflowchart LR\n  B1[B1. Move the store] -->|C1| B2[B2. Read from it]\n```\n\n"
    outline = read(edited("## Breakdown\n\n", f"## Breakdown\n\n{diagram}"))
    assert outline == read()


# Comparing approvals


def test_a_rewrap_changes_nothing_and_an_edit_changes_its_id() -> None:
    """Whitespace is no change; an id whose text changed, one added, and one removed are each named."""
    before = read()
    rewrapped = read(edited("from the new store,\n  never", "from the new store, never"))
    assert epic_outline.compare(before, rewrapped) == Change()
    after = read(
        edited(
            "- **R1.** Sessions survive a restart of the API.\n",
            "- **R1.** Sessions survive a restart of the API and a deploy.\n- **R3.** Sessions expire.\n",
            edited("- Uses: C1\n", "- Uses: none\n", edited("Provided by B1; used by B2.", "Provided by B1.")),
        ),
    )
    change = epic_outline.compare(before, after)
    assert change == Change(added={"R3"}, changed={"R1", "C1", "B2"})
    removed = read(
        edited(
            "- **C1.** The store's read interface: `get(id) -> Session | None`. Provided by B1; used by B2.\n",
            "",
            edited("- Provides: C1\n", "- Provides: none\n", edited("- Uses: C1\n", "- Uses: none\n")),
        ),
    )
    assert epic_outline.compare(before, removed).removed == {"C1"}


def test_an_edit_inside_a_code_block_changes_the_id_it_sits_under() -> None:
    """A code block is never structure, but it is part of its entry's text: a sketch that changes reaches its member."""
    before = read()
    after = read(edited("- **R9.** Nor a requirement.", "- **R9.** Nor a requirement, still."))
    assert epic_outline.compare(before, after) == Change(changed={"B2"})
    assert "B9" not in after.entries
    assert "R9" not in after.requirements


def test_an_id_an_earlier_approval_removed_is_never_used_again() -> None:
    """A plan that holds an id retired by an earlier approval names it."""
    assert epic_outline.reused(read(), frozenset({"R2", "C4", "B1"})) == ["B1", "R2"]
    assert epic_outline.reused(read(), frozenset({"R3"})) == []


@pytest.mark.parametrize(
    ("entries", "touched", "reached"),
    [
        (frozenset({"B1"}), Change(changed={"B1"}), True),
        (frozenset({"B2"}), Change(changed={"C1"}), True),
        (frozenset({"B2"}), Change(changed={"R1"}), False),
        (frozenset({"B1", "B2"}), Change(changed={"R2"}), True),
        (frozenset(), Change(added={"R3"}), True),
        (frozenset(), Change(), False),
        (frozenset({"B1"}), Change(), False),
    ],
    ids=[
        "its entry changed",
        "an id it uses changed",
        "an id it does not cite changed",
        "one of its entries cites it",
        "a member of no entry, by any change",
        "a member of no entry, by no change",
        "no change",
    ],
)
def test_a_change_reaches_a_member_whose_entries_cite_what_changed(
    entries: frozenset[str],
    touched: Change,
    reached: bool,  # noqa: FBT001  (a parametrized case)
) -> None:
    """A member is reached by its entries, and a member of no entry by every change (DESIGN §43)."""
    outline = read()
    assert epic_outline.reaches(touched, entries, before=outline, after=outline) is reached


def test_a_change_reaches_a_member_by_what_its_entry_cited_before() -> None:
    """An entry that stopped citing a changed id is still reached by it: the member was planned against it."""
    before = read()
    after = read(edited("- Uses: C1\n", "- Uses: none\n", edited("Provided by B1; used by B2.", "Provided by B1.")))
    change = Change(changed={"C1"})
    assert epic_outline.reaches(change, frozenset({"B2"}), before=before, after=after)


def test_a_member_is_named_the_ids_that_reached_it_and_one_of_no_entry_every_id() -> None:
    """What a member is told is what reached it: its entries and the ids they cite, or the whole change."""
    outline = read()
    change = Change(added={"R2"}, removed={"B1"}, changed={"C1", "R1"})
    assert epic_outline.reaching(change, frozenset({"B2"}), before=outline, after=outline) == {"C1", "R2"}
    assert epic_outline.reaching(change, frozenset({"B1"}), before=outline, after=outline) == {"B1", "C1", "R1"}
    assert epic_outline.reaching(change, frozenset(), before=outline, after=outline) == change.ids()
    assert epic_outline.ordered(change.ids()) == ["B1", "C1", "R1", "R2"]


@pytest.mark.parametrize(
    ("entries", "trivial"),
    [
        (frozenset({"B2"}), True),
        (frozenset({"B1", "B2"}), False),
        (frozenset({"B1"}), False),
        (frozenset(), False),
        (frozenset({"B9"}), False),
    ],
    ids=["its one entry trivial", "one entry not", "its entry not", "a member of no entry", "an entry the plan lacks"],
)
def test_a_member_is_trivial_only_when_every_entry_it_fulfils_is(
    entries: frozenset[str],
    trivial: bool,  # noqa: FBT001  (a parametrized case)
) -> None:
    """A trivial member skips its own plan only when every entry it fulfils is marked trivial (DESIGN §43)."""
    assert epic_outline.trivial(read(), entries) is trivial
