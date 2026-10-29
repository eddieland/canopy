"""The eight tools of the artifacts contract (DESIGN §38), each a request and what the store does with it.

A tool's arguments are validated against its request, whose JSON schema is its input schema; the store then does the
call, held to its scope. What a tool returns is JSON: one object, or for `comment_feed` one change to a line, its
`end` line last, as a connector prints (DESIGN §30). A refusal is the store's `Refused`, which the server answers as a
tool error carrying its code.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Annotated, Literal

import canopy_mcp
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from canopy_artifacts.store import CONTEXT, LIST_PAGE, MAX_BODY, MAX_FEED, MAX_ORIGIN, Store
from canopy_artifacts.text import Anchor, ContentType

#: Origin pairs, by key, set when an artifact is made. Plain aliases, not `type` statements: pydantic leaves out the
#: description of a field whose type is a `type` alias.
Origin = Annotated[
    Mapping[StrictStr, StrictStr] | None,
    Field(description=f"At most {MAX_ORIGIN} string pairs, such as canopy.ticket, which a reader filters on."),
]
#: An origin a reader filters on.
OriginFilter = Annotated[
    Mapping[StrictStr, StrictStr] | None,
    Field(description="Only artifacts whose origin holds every one of these pairs."),
]
#: An artifact's id, as the store gave it.
ArtifactId = Annotated[StrictStr, Field(description="The artifact's id, as artifact_publish or artifact_list gave it.")]
#: A thread's id, as the store gave it.
ThreadId = Annotated[
    StrictStr,
    Field(description="The thread's id, as thread_list, comment_feed, or comment_create gave it."),
]


#: One of the store's tools: called in the store, answering with the JSON it returns as text.
type Tool = canopy_mcp.Tool[Store, str]


def tool[R: BaseModel](
    name: str,
    description: str,
    request: type[R],
    do: Callable[[Store, R], object],
    hints: canopy_mcp.Hints,
) -> Tool:
    """Make `do` a tool, taking `request` as its arguments, with `hints` for a client.

    Returns:
        The tool, which returns what `do` does as JSON: a list as one item to a line, anything else as one object.
    """

    def call(arguments: Mapping[str, object], store: Store) -> str:
        done = do(store, request.model_validate(arguments))
        if isinstance(done, list):
            return "\n".join(json.dumps(item, ensure_ascii=False) for item in done)
        return json.dumps(done, ensure_ascii=False)

    return canopy_mcp.Tool(name, description, request, call, hints=hints)


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Publish(_Request):
    """Make an artifact, or add a version to one."""

    title: Annotated[StrictStr, Field(description="What the page is, in a few words.")]
    content_type: Annotated[ContentType, Field(description="text/html or text/markdown.")]
    content: Annotated[StrictStr, Field(description="The page, whole.")]
    origin: Origin = None
    artifact_id: Annotated[
        StrictStr | None,
        Field(description="To add a version to this artifact, which keeps its origin and its threads."),
    ] = None


class Read(_Request):
    """Read a version of an artifact."""

    artifact_id: ArtifactId
    version: Annotated[StrictInt | None, Field(ge=1, description="The version; its latest when omitted.")] = None


class ListArtifacts(_Request):
    """List artifacts, newest first."""

    origin: OriginFilter = None
    cursor: Annotated[StrictStr | None, Field(description="The next_cursor of the page before.")] = None


class ThreadList(_Request):
    """List an artifact's threads."""

    artifact_id: ArtifactId
    state: Annotated[
        Literal["open", "resolved"] | None,
        Field(description="Only threads in this state; every thread when omitted."),
    ] = None
    version: Annotated[
        StrictInt | None,
        Field(ge=1, description="The version each anchor is looked for in; its latest when omitted."),
    ] = None


class Feed(_Request):
    """Read the changes to comments and threads after a cursor."""

    origin: OriginFilter = None
    since: Annotated[StrictInt, Field(description="The through of the last end line read; 0 for every change.")] = 0
    limit: Annotated[StrictInt, Field(description=f"The most changes to return, at most {MAX_FEED}.")] = MAX_FEED


class Reply(_Request):
    """Reply in a thread."""

    thread_id: ThreadId
    body: Annotated[StrictStr, Field(description=f"At most {MAX_BODY} characters.")]


class AnchorRequest(_Request):
    """A passage: a W3C Web Annotation TextQuoteSelector over a version's text, whitespace collapsed."""

    exact: Annotated[StrictStr, Field(description="The passage's words, as the version's text has them.")]
    prefix: Annotated[StrictStr, Field(description=f"Up to {CONTEXT} characters just before it.")] = ""
    suffix: Annotated[StrictStr, Field(description=f"Up to {CONTEXT} characters just after it.")] = ""


class Create(_Request):
    """Open a thread on a passage, or on the whole artifact."""

    artifact_id: ArtifactId
    anchor: Annotated[
        AnchorRequest | None,
        Field(description="The passage, in the artifact's latest version; the whole artifact when omitted."),
    ] = None
    body: Annotated[StrictStr, Field(description=f"At most {MAX_BODY} characters.")]


class Resolve(_Request):
    """Resolve a thread, or reopen it."""

    thread_id: ThreadId
    resolved: Annotated[StrictBool, Field(description="true to resolve it, false to reopen it.")]


#: What a tool that writes says of a store it may not write to.
_READ_ONLY = "A store opened read-only refuses it (read_only)."

TOOLS = (
    tool(
        "artifact_publish",
        "Publish a page for people to read and comment on: a report, a design, a mock-up. Without artifact_id it makes "
        "a new artifact; with one it adds a version, whose threads carry over by their passages' words, so publish a "
        "revision as a new version rather than a new artifact. Returns the artifact's id, the version's number, and "
        f"its url. {_READ_ONLY}",
        Publish,
        lambda store, r: store.publish(
            title=r.title,
            content_type=r.content_type,
            content=r.content,
            origin=r.origin,
            artifact_id=r.artifact_id,
        ),
        canopy_mcp.WRITES,
    ),
    tool(
        "artifact_read",
        "Read a version of an artifact, its latest unless named: its metadata, its content as published, and its "
        "text, which comment_create's anchors are quoted from: an HTML page's words as a reader sees them, or a "
        "Markdown page's source, whitespace collapsed either way.",
        Read,
        lambda store, r: store.read(r.artifact_id, r.version),
        canopy_mcp.READS,
    ),
    tool(
        "artifact_list",
        f"List artifacts, newest first, {LIST_PAGE} to a page, each with its id, title, origin, and latest version; "
        "narrow it by origin. When next_cursor is not null, pass it as cursor for the next page.",
        ListArtifacts,
        lambda store, r: store.artifacts(r.origin, r.cursor),
        canopy_mcp.READS,
    ),
    tool(
        "thread_list",
        "List an artifact's threads, oldest first, each with its comments and its state, open or resolved. Each "
        "thread's anchor is looked for in a version, its latest unless named: found, or passage_gone when its words "
        "are no longer there; null for a thread on the whole artifact. Use it to read one artifact's discussion; "
        "comment_feed follows what changed across artifacts.",
        ThreadList,
        lambda store, r: store.threads(r.artifact_id, state=r.state, version=r.version),
        canopy_mcp.READS,
    ),
    tool(
        "comment_feed",
        "Read the changes to comments and threads after since, oldest first, one JSON object to a line, ending with "
        '{"kind": "end", "through": SEQ}: pass that SEQ as since for the next page. A page without its end line is '
        "incomplete. Use it to follow new comments across artifacts without reading every thread.",
        Feed,
        lambda store, r: store.feed(r.origin, r.since, r.limit),
        canopy_mcp.READS,
    ),
    tool(
        "comment_reply",
        "Reply in a thread, open or resolved, as a new comment at its end; it leaves the thread's state as it is. "
        f"Returns the comment's id and its seq. {_READ_ONLY}",
        Reply,
        lambda store, r: store.reply(r.thread_id, r.body),
        canopy_mcp.WRITES,
    ),
    tool(
        "comment_create",
        "Comment on a passage of an artifact's latest version, quoted by its words and the text either side, or on "
        "the whole artifact: a new open thread. A passage not in that version's text is refused (anchor_not_found). "
        "To answer a comment, reply in its thread instead. Returns the thread's id, its first comment's id, and that "
        f"comment's seq. {_READ_ONLY}",
        Create,
        lambda store, r: store.comment(
            r.artifact_id,
            None if r.anchor is None else Anchor.of(r.anchor.exact, r.anchor.prefix, r.anchor.suffix),
            r.body,
        ),
        canopy_mcp.WRITES,
    ),
    tool(
        "thread_resolve",
        f"Resolve a thread, or reopen one; a thread already so is left as it is. Returns its state. {_READ_ONLY}",
        Resolve,
        lambda store, r: store.resolve(r.thread_id, resolved=r.resolved),
        canopy_mcp.Hints(read_only=False, idempotent=True),
    ),
)
