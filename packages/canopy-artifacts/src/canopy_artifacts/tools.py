"""The eight tools of the artifacts contract (DESIGN §38), each a request and what the store does with it.

A tool's arguments are validated against its request, whose JSON schema is its input schema; the store then does the
call, held to its scope. What a tool returns is JSON: one object, or for `comment_feed` one change to a line, its
`end` line last, as a connector prints (DESIGN §30). A refusal is the store's `Refused`, which the server answers as a
tool error carrying its code.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from canopy_artifacts.store import CONTEXT, MAX_BODY, MAX_FEED, MAX_ORIGIN, Store
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


@dataclass(frozen=True)
class Tool:
    """One tool: its name, what it does, its request, and the call."""

    name: str
    #: What it does, for the model.
    description: str
    #: Its request, whose schema is the tool's input schema.
    request: type[BaseModel]
    #: Validate the arguments, and do the call in the store: what the tool returns, as text.
    call: Callable[[Mapping[str, object], Store], str]


def tool[R: BaseModel](name: str, description: str, request: type[R], do: Callable[[Store, R], object]) -> Tool:
    """Make `do` a tool, taking `request` as its arguments.

    Returns:
        The tool, which returns what `do` does as JSON: a list as one item to a line, anything else as one object.
    """

    def call(arguments: Mapping[str, object], store: Store) -> str:
        done = do(store, request.model_validate(arguments))
        if isinstance(done, list):
            return "\n".join(json.dumps(item, ensure_ascii=False) for item in done)
        return json.dumps(done, ensure_ascii=False)

    return Tool(name, description, request, call)


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

    artifact_id: StrictStr
    version: Annotated[StrictInt | None, Field(ge=1, description="The version; its latest when omitted.")] = None


class ListArtifacts(_Request):
    """List artifacts, newest first."""

    origin: OriginFilter = None
    cursor: Annotated[StrictStr | None, Field(description="The next_cursor of the page before.")] = None


class ThreadList(_Request):
    """List an artifact's threads."""

    artifact_id: StrictStr
    state: Annotated[Literal["open", "resolved"] | None, Field(description="Only threads in this state.")] = None
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

    thread_id: StrictStr
    body: Annotated[StrictStr, Field(description=f"At most {MAX_BODY} characters.")]


class AnchorRequest(_Request):
    """A passage: a W3C Web Annotation TextQuoteSelector over a version's text, whitespace collapsed."""

    exact: Annotated[StrictStr, Field(description="The passage's words, as the version's text has them.")]
    prefix: Annotated[StrictStr, Field(description=f"Up to {CONTEXT} characters just before it.")] = ""
    suffix: Annotated[StrictStr, Field(description=f"Up to {CONTEXT} characters just after it.")] = ""


class Create(_Request):
    """Open a thread on a passage, or on the whole artifact."""

    artifact_id: StrictStr
    anchor: Annotated[
        AnchorRequest | None,
        Field(description="The passage, in the artifact's latest version; the whole artifact when omitted."),
    ] = None
    body: Annotated[StrictStr, Field(description=f"At most {MAX_BODY} characters.")]


class Resolve(_Request):
    """Resolve a thread, or reopen it."""

    thread_id: StrictStr
    resolved: Annotated[StrictBool, Field(description="true to resolve it, false to reopen it.")]


TOOLS: Final = (
    tool(
        "artifact_publish",
        "Publish a page for people to read and comment on: a new artifact, or with artifact_id a new version of one, "
        "whose threads carry over by their passages' words.",
        Publish,
        lambda store, r: store.publish(
            title=r.title,
            content_type=r.content_type,
            content=r.content,
            origin=r.origin,
            artifact_id=r.artifact_id,
        ),
    ),
    tool(
        "artifact_read",
        "Read a version of an artifact: its metadata, its content, and its text, which anchors are taken from.",
        Read,
        lambda store, r: store.read(r.artifact_id, r.version),
    ),
    tool(
        "artifact_list",
        "List artifacts, newest first, a page at a time; pass next_cursor for the next page.",
        ListArtifacts,
        lambda store, r: store.artifacts(r.origin, r.cursor),
    ),
    tool(
        "thread_list",
        "List an artifact's threads with their comments, and whether each thread's passage is found in a version or "
        "gone from it (passage_gone).",
        ThreadList,
        lambda store, r: store.threads(r.artifact_id, state=r.state, version=r.version),
    ),
    tool(
        "comment_feed",
        "Read the changes to comments and threads after since, oldest first, one JSON object to a line, ending with "
        '{"kind": "end", "through": SEQ}: pass that SEQ as since for the next page. A page without its end line is '
        "incomplete.",
        Feed,
        lambda store, r: store.feed(r.origin, r.since, r.limit),
    ),
    tool(
        "comment_reply",
        "Reply in a thread.",
        Reply,
        lambda store, r: store.reply(r.thread_id, r.body),
    ),
    tool(
        "comment_create",
        "Comment on a passage of an artifact's latest version, quoted by its words and the text either side, or on "
        "the whole artifact: a new open thread.",
        Create,
        lambda store, r: store.comment(
            r.artifact_id,
            None if r.anchor is None else Anchor.of(r.anchor.exact, r.anchor.prefix, r.anchor.suffix),
            r.body,
        ),
    ),
    tool(
        "thread_resolve",
        "Resolve a thread, or reopen one.",
        Resolve,
        lambda store, r: store.resolve(r.thread_id, resolved=r.resolved),
    ),
)
