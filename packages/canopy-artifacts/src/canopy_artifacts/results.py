"""What each of the store's tools returns, as a model: its schema is the tool's output schema (README, Records).

The store builds each result as JSON-ready values (`store`), and its tool's text is their JSON, as it always was. The
same values, validated into these models, are the tool's structured content, so the two never say different things,
and a result that strays from its schema fails its call instead of reaching a client that checks it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

#: When something happened, in ISO 8601, in UTC.
Time = Annotated[str, Field(description="ISO 8601, in UTC.")]
#: When something happened, or None if it never did.
MaybeTime = Annotated[str | None, Field(description="ISO 8601, in UTC; null if it has not happened.")]
#: Whether a thread's passage is in a version.
AnchorStatus = Annotated[
    Literal["found", "passage_gone"] | None,
    Field(description="found, or passage_gone when its words are not there; null for a thread on the whole artifact."),
]


class Result(BaseModel):
    """The base of every result: it holds every field the store gives, and no other."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Anchor(Result):
    """A passage, as a W3C Web Annotation TextQuoteSelector over a version's text."""

    exact: Annotated[str, Field(description="The passage's words.")]
    prefix: Annotated[str, Field(description="Up to 32 characters just before it.")]
    suffix: Annotated[str, Field(description="Up to 32 characters just after it.")]


class Author(Result):
    """Who wrote a comment or made a change."""

    id: Annotated[str, Field(description="Stable, from the store's sign-in.")]
    display_name: Annotated[str, Field(description="The name shown for them.")]
    kind: Annotated[Literal["person", "agent"], Field(description="A person, or an agent.")]
    on_behalf_of: Annotated[str | None, Field(description="Whom they write for; null when no one.")]


class Artifact(Result):
    """An artifact: a page people read and comment on, in versions."""

    id: Annotated[str, Field(description="The artifact's id.")]
    title: Annotated[str, Field(description="Its latest version's title.")]
    namespace: Annotated[str, Field(description="Where it was made.")]
    origin: Annotated[Mapping[str, str], Field(description="The string pairs set when it was made.")]
    latest_version: Annotated[int, Field(description="Its newest version's number.")]
    created_at: Time


class Version(Result):
    """One version of an artifact; immutable."""

    artifact_id: Annotated[str, Field(description="The artifact.")]
    n: Annotated[int, Field(description="The version's number, from 1.")]
    content_type: Annotated[Literal["text/html", "text/markdown"], Field(description="How its content is written.")]
    sha256: Annotated[str, Field(description="The SHA-256 of its content, in hex.")]
    created_at: Time


class Comment(Result):
    """A comment in a thread, as it is now."""

    id: Annotated[str, Field(description="The comment's id.")]
    thread_id: Annotated[str, Field(description="Its thread.")]
    seq: Annotated[int, Field(description="The seq of the latest change to it.")]
    author: Author
    body: Annotated[str, Field(description="What it says; empty once deleted.")]
    created_at: Time
    edited_at: MaybeTime
    deleted_at: MaybeTime
    via: Annotated[Literal["web", "mcp"], Field(description="Where it was written.")]


class Thread(Result):
    """A thread on a passage of an artifact, or on the whole artifact, with its comments."""

    id: Annotated[str, Field(description="The thread's id.")]
    artifact_id: Annotated[str, Field(description="Its artifact.")]
    anchor: Annotated[Anchor | None, Field(description="Its passage; null for the whole artifact.")]
    anchored_version: Annotated[int, Field(description="The version its passage was taken from.")]
    state: Annotated[Literal["open", "resolved"], Field(description="Whether it is open or resolved.")]
    anchor_status: AnchorStatus
    comments: Annotated[Sequence[Comment], Field(description="Its comments, oldest first.")]


class Change(Result):
    """One change to a comment or a thread, as the feed gives it, the comment and thread as they are now."""

    kind: Annotated[
        Literal["comment_created", "comment_edited", "comment_deleted", "thread_resolved", "thread_reopened"],
        Field(description="What changed."),
    ]
    seq: Annotated[int, Field(description="Its place in the store's one sequence of changes.")]
    at: Time
    artifact_id: Annotated[str, Field(description="The artifact.")]
    origin: Annotated[Mapping[str, str], Field(description="The artifact's origin.")]
    thread_id: Annotated[str, Field(description="The thread.")]
    anchor: Annotated[Anchor | None, Field(description="The thread's passage; null for the whole artifact.")]
    anchored_version: Annotated[int, Field(description="The version the thread's passage was taken from.")]
    state: Annotated[Literal["open", "resolved"], Field(description="The thread's state now.")]
    anchor_status: AnchorStatus
    comment_id: Annotated[str | None, Field(description="The comment; null for a change to the thread.")]
    author: Author
    via: Annotated[Literal["web", "mcp"], Field(description="Where the change was made.")]
    body: Annotated[str | None, Field(description="The comment's body now; null for a change to the thread.")]
    created_at: Annotated[str | None, Field(description="When the comment was written; null for a thread's change.")]
    edited_at: MaybeTime
    deleted_at: MaybeTime


class Published(Result):
    """`artifact_publish`: the version made."""

    artifact_id: Annotated[str, Field(description="The artifact.")]
    version: Annotated[int, Field(description="The new version's number.")]
    url: Annotated[str, Field(description="Where the version is read.")]


class Read(Result):
    """`artifact_read`: a version of an artifact, whole."""

    artifact: Artifact
    version: Version
    content: Annotated[str, Field(description="The page, as published.")]
    text: Annotated[str, Field(description="What a reader sees of it, whitespace collapsed: what anchors quote.")]


class ArtifactPage(Result):
    """`artifact_list`: a page of artifacts, newest first."""

    artifacts: Annotated[Sequence[Artifact], Field(description="The artifacts, newest first.")]
    next_cursor: Annotated[str | None, Field(description="Pass it as cursor for the next page; null on the last.")]


class Threads(Result):
    """`thread_list`: an artifact's threads, oldest first."""

    artifact_id: Annotated[str, Field(description="The artifact.")]
    version: Annotated[int, Field(description="The version each anchor was looked for in.")]
    threads: Annotated[Sequence[Thread], Field(description="Its threads, oldest first.")]


class FeedPage(Result):
    """`comment_feed`: a page of changes, oldest first, and where the next page reads from."""

    changes: Annotated[Sequence[Change], Field(description="The changes after since, oldest first.")]
    through: Annotated[int, Field(description="Pass it as since for the next page.")]


class Replied(Result):
    """`comment_reply`: the comment written."""

    comment_id: Annotated[str, Field(description="The new comment.")]
    seq: Annotated[int, Field(description="The seq of its change.")]


class Created(Result):
    """`comment_create`: the thread opened, and its first comment."""

    thread_id: Annotated[str, Field(description="The new thread.")]
    comment_id: Annotated[str, Field(description="Its first comment.")]
    seq: Annotated[int, Field(description="The seq of its change.")]


class Resolved(Result):
    """`thread_resolve`: the thread's state now."""

    state: Annotated[Literal["open", "resolved"], Field(description="Whether it is open or resolved.")]


def feed_page(lines: Sequence[object]) -> Mapping[str, object]:
    """A feed's lines as one object: its changes, and the `through` of its last line, the `end` line.

    Returns:
        What `FeedPage` validates; a page without its end line has no `through`, which it refuses.
    """
    *changes, end = lines
    return {"changes": changes, "through": end.get("through") if isinstance(end, Mapping) else None}
