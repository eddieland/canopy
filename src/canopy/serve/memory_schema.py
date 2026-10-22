"""The API's types for agent memory (DESIGN §28): notes, proposals, and lessons, and what a run wrote and read of them.

Also the operator's promotes, edits, and forgets. Built on `schema.Model`, as every API type is; memory's tiers, which
the loop's state carries, are shared (schema.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import MemoryModeName, MemoryState, Model

type MemoryScopeName = Annotated[
    Literal["ticket", "proposal", "lesson"],
    Field(description="What a memory is: a ticket's note, a worker's proposal, or the operator's lesson."),
]
type MemoryStatusName = Annotated[
    Literal["active", "pending", "superseded", "invalid"],
    Field(description="Where a memory stands: in force, waiting on the operator, replaced, or no longer in force."),
]


class MemoryOrigin(Model):
    """What a lesson was promoted from (DESIGN §28): a proposal, or a ticket's note, past every edit of the lesson."""

    id: int
    """The source's id."""
    scope: MemoryScopeName
    """What the source is."""
    ticket_key: str | None
    """The ticket whose run wrote it."""
    run_id: int | None
    """The run that wrote it."""


class MemoryEntry(Model):
    """One note, proposal, or lesson (DESIGN §28). Its text is a worker's, or the operator's for a lesson."""

    id: int
    """Its id, as the CLI and a run's result name it."""
    scope: MemoryScopeName
    """What it is."""
    ticket_key: str | None
    """A note's ticket, or a proposal's source ticket; None for a lesson."""
    repo: str | None
    """The repository a proposal or lesson is about; None for every repository, and for a note."""
    key: str
    """Its key: lowercase words joined by hyphens."""
    text: str | None
    """What it says, untrusted and shown as plain text with hidden characters named; None once forgotten or purged."""
    status: MemoryStatusName
    """Where it stands."""
    why: str | None
    """The harness's words for its latest change of status, such as `superseded by note 41`."""
    run_id: int | None
    """The run that wrote it; None for a lesson."""
    head: str | None
    """The commit the run's branch was at when its worker ended, `repo@commit` each for a joint run."""
    created_at: datetime
    """When it was written."""
    read_count: int
    """How many runs' prompts carried it, whether or not they cited it."""
    last_read_at: datetime | None
    """When the latest of those runs started; None if no run has read it."""
    use_count: int
    """How many runs cited it as relied on, in their result's `memory_used`, which a worker may leave unsaid."""
    last_used_at: datetime | None
    """When a run last cited it; None if none has."""
    used_by: list[int] = []
    """The latest runs that cited it as relied on, newest first, at most five. A run from before canopy named them
    counts in `use_count` but is not here."""
    review_at: datetime | None
    """A lesson's next review; None for a pinned one, which is never due."""
    pinned_at: datetime | None
    """When the operator pinned a lesson, which runs are served before every lesson not pinned; None if not pinned."""
    wrong_at: datetime | None
    """When a run last reported a lesson wrong, until the operator renews it."""
    wrong_run_id: int | None
    """The run that reported it."""
    promoted_from: int | None
    """What a lesson was made from: the proposal or note it was promoted from, or the lesson it was edited from."""
    origin: MemoryOrigin | None = None
    """A lesson's source, as the CLI names it, past every edit; None for a note or a proposal, or a source no longer in
    the journal."""
    version: int = 1
    """Which version of its memory it is: 1 for one that replaced none, one more for each a lesson's edit or promote,
    or a note under the same key, replaced before it. `GET /api/memory/{id}/history` lists them."""
    edited: bool = False
    """Whether it is a lesson the operator made by editing the version before it."""
    private: bool = False
    """Whether the run that wrote it worked a private ticket: its text may hold what the operator kept off the
    tracker."""


class MemoryProposal(Model):
    """A proposal waiting on the operator, with where it came from (DESIGN §28)."""

    entry: MemoryEntry
    """The proposal."""
    run_kind: str | None
    """The kind of the run that proposed it."""
    run_status: str | None
    """How that run ended."""
    private: bool
    """Whether that run was on a private ticket, whose text may hold what the operator kept off the tracker."""
    ticket_done: bool
    """Whether its ticket is marked done: its work merged or closed, as far as the journal knows."""
    expires_at: datetime
    """When it lapses unless the operator decides it, `PROPOSAL_DAYS` after it was written: the first tick after
    invalidates it."""


class MemoryDigest(Model):
    """What a run would be served of one tier, as its prompt would carry it (DESIGN §28)."""

    text: str
    """The section, as plain text."""
    ids: list[int]
    """The memories in it."""
    left_out: int
    """How many the cap left out."""
    served: bool
    """True while its tier is at `use`: the next run gets it. False while recording: what `use` would serve."""


class TicketNotes(Model):
    """One ticket's notes in force, counted, for the list across tickets; its page lists them (DESIGN §28)."""

    ticket_key: str
    """The ticket."""
    count: int
    """How many of its notes are in force."""
    used: int
    """How many of those a run cited as relied on, in its `memory_used`."""
    latest_at: datetime
    """When the newest of them was written."""
    title: str | None
    """The ticket's title, as the overseer named it; None while it has named none."""


class MemoryOverview(Model):
    """Every tier's memory (DESIGN §28): the tickets with notes in force, the proposals waiting, and the lessons."""

    state: MemoryState | None
    """The tiers; None while both are off."""
    tickets: list[TicketNotes]
    """Every ticket with notes in force, counted, the one with the newest note first."""
    proposals: list[MemoryProposal]
    """The proposals waiting on the operator, oldest first."""
    lessons: list[MemoryEntry]
    """The lessons in force: any a run reported wrong first, then by review date, the one due first."""
    lessons_digest: MemoryDigest | None
    """What every run would be served of the lessons; None while proposals are off."""
    repos: list[str]
    """The workspace's repositories, by name: one a promoted lesson may be served to alone."""
    past_proposals: list[MemoryEntry] = []
    """With `history`, the proposals no longer pending, rejected, lapsed, promoted, or forgotten, the latest to leave
    first, at most 50; else none."""
    past_lessons: list[MemoryEntry] = []
    """With `history`, the lessons no longer in force, replaced or forgotten, the latest to leave first, at most 50;
    else none."""


class MemoryFound(Model):
    """What `canopy memory search` finds as the operator (DESIGN §28, Search): every memory that keeps its text."""

    entries: list[MemoryEntry]
    """The memories whose key or text holds any of the words, best match first, at most 50."""


class TicketMemory(Model):
    """One ticket's notes (DESIGN §28): every one its runs wrote, and what its next run would be served."""

    state: MemoryState | None
    """The tiers; None while both are off."""
    notes: list[MemoryEntry]
    """Every note of the ticket, in force or not, by key and newest first."""
    digest: MemoryDigest | None
    """What its next run would be served; None while ticket notes are off."""


class MemoryRefusal(Model):
    """An entry a run sent that `_run` did not write, in the harness's words; never its text (DESIGN §28)."""

    field: str
    """The result field it was in: `notes` or `proposals`."""
    key: str | None
    """Its key, when it had a valid one."""
    why: str
    """Why it was refused."""


class RunMemoryModes(Model):
    """The mode of each memory tier a run's prompt was rendered under: `off` for a tier its kind does not hear."""

    ticket_notes: MemoryModeName
    """Ticket notes' mode for this run."""
    lessons: MemoryModeName
    """Lessons' mode for this run."""


class RunMemory(Model):
    """What a run wrote of agent memory, what was rendered into its prompt, and what it had refused (DESIGN §28)."""

    rendered: RunMemoryModes | None
    """The modes it was rendered under; None for a run rendered with memory off, which wrote and read nothing."""
    wrote: list[MemoryEntry]
    """What it wrote, in order."""
    read: list[MemoryEntry]
    """What was rendered into its prompt. Empty while recording: then nothing was served."""
    used: list[int] = []
    """The ids of what it read that it said it relied on, its `memory_used`."""
    wrong: list[int] = []
    """The ids of what it read that it said was wrong, its `memory_wrong`."""
    refused: list[MemoryRefusal]
    """What it sent that was not written."""


class PromoteRequest(Model):
    """A promote, as `canopy memory promote ID [--text TEXT] [--repo NAME]` takes it (DESIGN §28)."""

    text: Annotated[str | None, Field(max_length=4000)] = None
    """The lesson in the operator's words; None keeps the source's own. Bounded again in code, as the CLI's is."""
    repo: Annotated[str | None, Field(max_length=200)] = None
    """The one repository whose runs are served the lesson; None keeps a proposal's, and a note's every one."""


class MemoryPromoted(Model):
    """What a promote made: the lesson, what it came from, the lesson it superseded, and whether runs read it now."""

    lesson: MemoryEntry
    """The new lesson, the operator's."""
    source: MemoryEntry
    """The proposal or note it came from, as it was."""
    superseded: int | None
    """The lesson under the same key it replaced, if there was one."""
    served: bool
    """Whether runs are served lessons now, `memory.proposals` at `use`; False while recording."""
    private: bool
    """Whether its text is still a private ticket's run's own words, which may hold what the operator kept off the
    tracker: the warning `canopy memory promote` gives."""


class LessonEditRequest(Model):
    """An edit, as `canopy memory edit ID [--text TEXT] [--repo NAME | --every-repo]` takes it (DESIGN §28)."""

    text: Annotated[str | None, Field(max_length=4000)] = None
    """The lesson's new words; None keeps its own. Bounded again in code, as the CLI's are."""
    repo: Annotated[str | None, Field(max_length=200)] = None
    """The one repository whose runs are served the lesson; None keeps the lesson's, unless `every_repo`."""
    every_repo: bool = False
    """Serve the lesson to runs in every repository; refused `bad_request` with `repo`."""


class MemoryEdited(Model):
    """What an edit made: the lesson's new version, the one it replaced, and whether runs read it now."""

    lesson: MemoryEntry
    """The new version, in force under the key."""
    replaced: MemoryEntry
    """The version it replaced, as it is now: superseded, its text kept as the lesson's history."""
    served: bool
    """Whether runs are served lessons now, `memory.proposals` at `use`; False while recording."""


class MemoryHistory(Model):
    """Every version of a lesson or a note, newest first (DESIGN §28): each edit of a lesson, each note under a key."""

    versions: list[MemoryEntry]
    """The versions, the newest first, each with its `version`."""


class MemoryRejected(Model):
    """A proposal the operator rejected: no lesson is made of it."""

    id: int
    """The proposal's id."""


class MemoryRenewed(Model):
    """A lesson the operator renewed: it comes up for review again later, and a run's report it is wrong is cleared."""

    id: int
    """The lesson's id."""
    review_at: datetime | None
    """When it is next due for review; None for a pinned lesson, which never is."""


class MemoryPinned(Model):
    """A lesson the operator pinned: never due for review, and served before every lesson not pinned."""

    id: int
    """The lesson's id."""
    pinned_at: datetime
    """When it was pinned."""


class MemoryUnpinned(Model):
    """A lesson the operator unpinned: it comes up for review again later, and is served as any other."""

    id: int
    """The lesson's id."""
    review_at: datetime
    """When it is next due for review."""


class MemoryForgetRequest(Model):
    """A forget, and the memory's ref as the operator typed it: the challenge, checked again in code (DESIGN §22)."""

    confirm: Annotated[str, Field(max_length=200)]
    """The memory's ref, `memory:42`, typed by the operator; anything else is refused `not_confirmed`."""


class MemoryForgotten(Model):
    """A memory whose text a forget deleted: its row stays, without the text. A forgotten lesson is retired."""

    id: int
    """The memory's id."""
    scope: MemoryScopeName
    """What it was."""
    key: str
    """Its key."""
    checkpointed: bool
    """Whether the journal's write-ahead log was checkpointed after; False while a reader held it open, when the text
    may stay in the log until SQLite's next checkpoint."""
