"""What canopy's sources read of other systems: text, never authority.

PRs, reviews, checks, tickets, tracker comments, branches, and artifacts, each source's runs, and the journal
numbers of what they read (DESIGN §29, §30, §35).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    AnchorStatus,
    AuthorKind,
    CheckConclusion,
    CheckStatus,
    ConnectorRunStatus,
    MergeState,
    NumberedItem,
    PrState,
    ReviewItem,
    ReviewState,
    SourceKind,
    ThreadState,
    TicketState,
)


@dataclass(frozen=True)
class ObservedPr(Row):
    """A PR as canopy's GitHub reader last read it whole (DESIGN §29)."""

    TABLE: ClassVar[LiteralString] = "observed_prs"

    url: str
    repository: str
    number: int
    head_sha: str | None
    base_ref: str | None
    state: PrState | None
    draft: bool
    mergeable: str | None
    author: str | None
    observed_at: str
    #: Its labels' names, as a JSON list.
    labels: str
    mergeable_state: MergeState | None
    #: Its title, the PR author's text, cut and marked, for display only: None from a reader that printed none.
    title: str | None
    #: Its times, each None from a reader that printed none: when it was opened; when it last became ready for review,
    #: None while a draft; when a review was first asked for at or after that; and when it merged and when it closed.
    created_at: str | None
    ready_at: str | None
    review_requested_at: str | None
    merged_at: str | None
    closed_at: str | None


@dataclass(frozen=True)
class ObservedReview(Row):
    """A review or a review comment of a PR, as the reader last read it whole (DESIGN §29). Text, never authority."""

    TABLE: ClassVar[LiteralString] = "observed_reviews"

    pr_url: str
    item: ReviewItem
    id: int
    author: str | None
    bot: bool
    state: ReviewState | None
    created_at: str | None
    body: str
    url: str | None
    review_id: int | None
    thread_id: str | None
    path: str | None
    line: int | None
    side: str | None
    outdated: bool | None
    resolved: bool | None
    observed_at: str
    #: Its journal number, taken when a source first observed it (DESIGN §35).
    number: int | None


@dataclass(frozen=True)
class ItemNumber(Row):
    """An item's journal number (DESIGN §35): taken when a source first observed it, or a review run ended."""

    TABLE: ClassVar[LiteralString] = "item_numbers"

    number: int
    kind: NumberedItem
    #: A ticket's key for a comment; a PR's URL for the rest.
    subject: str
    #: The source's id for it, or canopy's own for a review run.
    id: str
    numbered_at: str


@dataclass(frozen=True)
class ObservedTicket(Row):
    """A ticket as the tracker connector last read it whole (DESIGN §30). Text, never authority."""

    TABLE: ClassVar[LiteralString] = "observed_tickets"

    key: str
    title: str
    body: str
    state: TicketState
    #: Its labels, as a JSON list of `{"name", "added_at"}`.
    labels: str
    updated_at: str | None
    #: The keys it names as blocking it, as a JSON list.
    blockers: str
    observed_at: str


@dataclass(frozen=True)
class ObservedComment(Row):
    """A tracker comment as the tracker connector first read it (DESIGN §30). Text, never authority."""

    TABLE: ClassVar[LiteralString] = "observed_comments"

    ticket: str
    id: str
    author: str
    commented_at: str
    #: The comment's text, cut at `conversation.MAX_COMMENT`.
    body: str
    truncated: bool
    #: `worker` when it carries the workers' marks (D069), else `tracker`.
    source: str
    observed_at: str
    #: Its journal number, taken when a source first observed it (DESIGN §35).
    number: int | None


@dataclass(frozen=True)
class ObservedBranch(Row):
    """A branch under the branch prefix, as the `vcs` connector last read its repository whole (DESIGN §30)."""

    TABLE: ClassVar[LiteralString] = "observed_branches"

    repository: str
    name: str
    head_sha: str
    observed_at: str


@dataclass(frozen=True)
class ObservedCheck(Row):
    """A named CI context at a PR's head, as the `vcs` connector last read the PR whole (DESIGN §30)."""

    TABLE: ClassVar[LiteralString] = "observed_checks"

    pr_url: str
    name: str
    head_sha: str
    status: CheckStatus
    conclusion: CheckConclusion | None
    run_id: int | None
    url: str | None
    observed_at: str
    #: Its completed run's journal number (DESIGN §35); None while it runs, and for a commit status, which has no run.
    number: int | None


@dataclass(frozen=True)
class ObservedCheckRun(Row):
    """A completed check run a `vcs` source observed, kept across later reads of its PR (DESIGN §35)."""

    TABLE: ClassVar[LiteralString] = "observed_check_runs"

    pr_url: str
    run_id: int
    #: Its context's name, as `observed_checks.name`.
    name: str
    head_sha: str
    conclusion: CheckConclusion
    #: When a source first observed it completed.
    observed_at: str
    #: Its journal number, taken when a source first observed it completed (DESIGN §35).
    number: int | None


@dataclass(frozen=True)
class ConnectorRun(Row):
    """One run of a source (DESIGN §30): what it was asked, how it ended, and what it read."""

    TABLE: ClassVar[LiteralString] = "connector_runs"

    id: int
    #: The tick that made it; None for the loop's poll between ticks (DESIGN §6).
    tick_id: int | None
    source: str
    kind: SourceKind
    started_at: str
    ended_at: str
    status: ConnectorRunStatus
    #: What it was sent, as JSON.
    request: str
    #: The lines it recorded of each kind, as a JSON object.
    recorded: str
    #: The lines it refused of each kind, as a JSON object.
    refused: str
    #: The harness's words for what it did not read; None for an `ok` run.
    missed: str | None
    #: The last of its stderr.
    stderr: str
    #: The query's result, the keys in order, as a JSON list, when it read the query to the end.
    query_result: str | None
    #: The review query's result, the URLs in order, as a JSON list, when it read it to the end.
    review_query_result: str | None


@dataclass(frozen=True)
class ObservedFeed(Row):
    """How far an `artifacts` source has read its store's comment feed (DESIGN §30, §38)."""

    TABLE: ClassVar[LiteralString] = "observed_feeds"

    source: str
    #: The cursor the next run reads from: the `seq` of the last change it read, or past changes filtered out.
    through: int
    #: When a run last read the feed to its `end` line with nothing refused; None until one has.
    read_at: str | None


@dataclass(frozen=True)
class ObservedArtifactThread(Row):
    """A thread on an artifact, as the newest change the `artifacts` source read of it left it. Never authority."""

    TABLE: ClassVar[LiteralString] = "observed_artifact_threads"

    id: str
    artifact_id: str
    #: The artifact's origin pairs, as a JSON object.
    origin: str
    #: The origin's `canopy.ticket`, where that is a ticket's key.
    ticket: str | None
    #: The passage's words and the text either side; None for a thread on the whole artifact.
    exact: str | None
    prefix: str | None
    suffix: str | None
    anchored_version: int
    state: ThreadState
    #: Whether the passage was in the artifact's latest version when the store printed the change.
    anchor_status: AnchorStatus | None
    #: The store's `seq` of the newest change read of it.
    seq: int
    observed_at: str


@dataclass(frozen=True)
class ObservedArtifactComment(Row):
    """A comment on an artifact, as the newest change the `artifacts` source read of it left it. Never authority."""

    TABLE: ClassVar[LiteralString] = "observed_artifact_comments"

    id: str
    thread_id: str
    #: The store's id for who wrote it, stable for the life of the account.
    author: str
    author_name: str
    author_kind: AuthorKind
    #: For an agent's comment, the person it wrote for.
    on_behalf_of: str | None
    via: str
    #: Its text, cut at `conversation.MAX_COMMENT`; empty once deleted.
    body: str
    truncated: bool
    #: Whether it carries every one of the workers' marks (D069).
    marked: bool
    created_at: str
    edited_at: str | None
    deleted_at: str | None
    #: The store's `seq` of the newest change read of it.
    seq: int
    observed_at: str


@dataclass(frozen=True)
class PrTitle(Row):
    """A PR's title, as canopy last read it."""

    TABLE: ClassVar[LiteralString] = "pr_titles"

    pr_url: str
    title: str
    updated_at: str
