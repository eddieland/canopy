"""What an `artifacts` source read of an artifact store's comment feed (DESIGN §30, §38, ROADMAP M62).

The source is a command of the operator's config, `canopy-artifacts feed` for the local store, run as every connector
is (`observe.run`) with `{"since": SEQ}` on stdin: the cursor its last run's `end` line named, 0 at first. It prints
each change to a comment or a thread after the cursor, oldest first, and last `{"kind": "end", "through": SEQ}`.
Unlike a ticket or a PR, the feed is never read whole: each change is read once, past a cursor that only goes up, and a
thread and a comment are each kept as the newest change read of it left it.

Each line is validated and bounded before anything is written: text is cut and marked, and a field whose cut would
change what it says, such as an id, a `seq`, or a time, refuses the line. The run records the changes before the first
line refused and moves the cursor to the last of them, never past it, so the next run reads the refused change again
and none is missed; the run is `partial`. A run with no `end` line records nothing and leaves the cursor where it was.

An observation is a dated copy of what the store said, never authority (DESIGN §22). A comment on an artifact whose
origin names a ticket the journal holds reaches that ticket's conversation, quoting its passage, once, as a tracker
comment does (§35). Whose comment counts is not decided here but in `artifact_authority`, from that message.

Which ticket an artifact names is canopy's word on a store that takes it: each run whose agent may publish is given its
workspace, ticket, and run in `ORIGIN_ENV` (`origin_env`), which the local store sets over the worker's own pairs.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Literal, cast

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from canopy.core import contract, conversation, db, observe, records, sql
from canopy.core.vocab import AnchorStatus, AuthorKind, ConnectorRunStatus, ThreadState

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    from canopy.core.config import Config, Source
    from canopy.infra import logs, procs

#: The kinds of change the feed prints: a line of any other kind is skipped, as an unknown kind is (DESIGN §30).
CHANGES = frozenset({"comment_created", "comment_edited", "comment_deleted", "thread_resolved", "thread_reopened"})
#: The changes to a comment, which carry the comment; a thread's carry none.
COMMENT_CHANGES = frozenset({"comment_created", "comment_edited", "comment_deleted"})
#: The origin key whose value names the ticket an artifact is for.
TICKET_KEY = "canopy.ticket"
#: The origin keys whose values name the workspace and the run an artifact was made in.
WORKSPACE_KEY = "canopy.workspace"
RUN_KEY = "canopy.run"
#: The variable a publishing run's agent is given its origin pairs in, a JSON object, which its store's MCP server
#: inherits and sets over the worker's: so the worker does not choose the ticket its artifact's comments reach.
ORIGIN_ENV = "CANOPY_ARTIFACT_ORIGIN"
#: The most origin pairs, and characters of a pair's key and value, as the contract bounds them: past them, a line is
#: refused rather than cut, since a pair cut short would name another origin.
MAX_ORIGIN = 16
MAX_ORIGIN_KEY = 64
MAX_ORIGIN_VALUE = 256
#: The most characters kept of a passage, cut and marked as a tracker comment's body is, and of the text either side.
MAX_PASSAGE = conversation.MAX_COMMENT
MAX_CONTEXT = 200
#: The most characters kept of an author's name, on one line.
MAX_AUTHOR_NAME = 200
#: The most characters of its passage a comment's message quotes: enough to find it, short of the comment it heads.
MAX_QUOTE = 300
#: The source of a comment's message in its ticket's conversation, unless it carries the workers' marks.
SOURCE = "artifact"
#: What starts a comment's id in its ticket's conversation, so it never meets a tracker comment's id.
COMMENT_ID_PREFIX = "artifact:"


def read(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    source: Source,
    request: observe.Request,
    *,
    name: str,
    log: logs.TickAdapter,
) -> observe.Observed:
    """Run source `name`'s connector for `request`, past its cursor, and record each change it read, moving it on.

    Returns:
        How the run ended.
    """
    ran = observe.run(runner, source, request, log=log)
    if isinstance(ran, observe.Observed):
        return ran
    since = request.since or 0
    found = _read(ran.stdout, since)
    if found.end is None:
        return observe.failed(log, ran.started_at, "it ended without its end line", ran.stderr, found.refused)
    last = found.changes[-1].seq if found.changes else since
    if found.end.through < last:
        why = f"its end line names change {found.end.through}, before change {last} it had read to"
        return observe.failed(log, ran.started_at, why, ran.stderr, found.refused)
    through = last if found.stopped else found.end.through
    recorded = _record(conn, config, name, found.changes, through, whole=not found.stopped)
    missed = None
    if found.stopped:
        missed = f"did not read the feed past change {through}: the line after it was refused"
        log.warning("artifact feed read short", extra={"missed": missed, "refused": found.refused})
    return observe.Observed(
        status=ConnectorRunStatus.OK if missed is None else ConnectorRunStatus.PARTIAL,
        started_at=ran.started_at,
        ended_at=db.now(),
        recorded=recorded,
        refused=dict(found.refused),
        missed=missed,
        stderr=ran.stderr,
    )


def cursor(conn: sqlite3.Connection, name: str) -> int:
    """The cursor source `name`'s next run reads from: the `through` its last run moved it to, or 0.

    Returns:
        The cursor.
    """
    row = sql.execute(conn, sql.select("through").from_("observed_feeds").where("source = ?", name)).fetchone()
    return 0 if row is None else int(row[0])


def origin_env(workspace: str, ticket: str, run_id: int) -> dict[str, str]:
    """The variable that names run `run_id`'s origin, of ticket `ticket` in workspace `workspace`, to its store.

    Returns:
        `ORIGIN_ENV`, to set on the run's agent.
    """
    pairs = {WORKSPACE_KEY: workspace, TICKET_KEY: ticket, RUN_KEY: str(run_id)}
    return {ORIGIN_ENV: json.dumps(pairs, ensure_ascii=False)}


# What a line carries

_Id = Annotated[str, observe.text_of(conversation.MAX_AUTHOR, conversation.COMMENT_ID_RE)]
_AuthorId = Annotated[str, observe.text_of(conversation.MAX_AUTHOR, re.compile(r"\S+"))]


def _origin(value: dict[str, str]) -> dict[str, str]:
    if len(value) > MAX_ORIGIN:
        raise ValueError(f"at most {MAX_ORIGIN} origin pairs")
    if any(not 0 < len(k) <= MAX_ORIGIN_KEY or len(v) > MAX_ORIGIN_VALUE for k, v in value.items()):
        raise ValueError(f"an origin key is 1 to {MAX_ORIGIN_KEY} characters, a value at most {MAX_ORIGIN_VALUE}")
    return value


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)


class _Anchor(_Line):
    exact: Annotated[str, contract.bounded(MAX_PASSAGE)]
    prefix: Annotated[str, contract.bounded(MAX_CONTEXT)] = ""
    suffix: Annotated[str, contract.bounded(MAX_CONTEXT)] = ""


class _Author(_Line):
    id: _AuthorId
    display_name: Annotated[str, contract.one_line, contract.bounded(MAX_AUTHOR_NAME)] = ""
    kind: AuthorKind
    on_behalf_of: _AuthorId | None = None


class _Change(_Line):
    kind: Literal["comment_created", "comment_edited", "comment_deleted", "thread_resolved", "thread_reopened"]
    seq: Annotated[int, Field(ge=1)]
    at: observe.Time
    artifact_id: _Id
    origin: Annotated[dict[str, str], AfterValidator(_origin)] = {}
    thread_id: _Id
    anchor: _Anchor | None = None
    anchored_version: Annotated[int, Field(ge=1)]
    state: ThreadState
    anchor_status: AnchorStatus | None = None
    comment_id: _Id | None = None
    author: _Author
    via: Literal["web", "mcp"]
    # Cut where it is recorded, and marked truncated there, as a tracker comment is.
    body: str | None = None
    created_at: observe.Time | None = None
    edited_at: observe.Time | None = None
    deleted_at: observe.Time | None = None

    @model_validator(mode="after")
    def _a_comments_change_carries_it(self) -> _Change:
        if self.kind in COMMENT_CHANGES and (self.comment_id is None or self.body is None or self.created_at is None):
            raise ValueError("a change to a comment carries the comment's id, body, and time")
        return self

    @property
    def ticket(self) -> str | None:
        """The ticket the artifact's origin names, where that is a ticket's key."""
        key = self.origin.get(TICKET_KEY, "")
        return key if len(key) <= conversation.MAX_KEY and conversation.KEY_RE.fullmatch(key) else None


class _End(_Line):
    kind: Literal["end"]
    through: Annotated[int, Field(ge=0)]


@dataclass
class _Output:
    """A feed's output as validated: the changes before the first line refused, the last `end` line, and the refused."""

    changes: list[_Change] = field(default_factory=list[_Change])
    end: _End | None = None
    refused: Counter[str] = field(default_factory=Counter[str])
    #: Whether a line was refused, so no change after it was taken.
    stopped: bool = False


def _read(stdout: str, since: int) -> _Output:
    """Validate each line of a feed's output, taking changes in `seq` order until one is refused.

    Returns:
        The changes taken, the last `end` line, and what was refused.
    """
    found = _Output()
    for text in stdout.splitlines():
        if len(text) > observe.MAX_LINE:
            found.refused["unread"] += 1
            found.stopped = True
            continue
        try:
            raw: object = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            _take(found, cast("dict[str, object]", raw), since)
    return found


def _take(found: _Output, raw: Mapping[str, object], since: int) -> None:
    """Validate one JSON object of a feed's output into `found`; a change refused stops the changes taken."""
    kind = str(raw.get("kind"))
    if kind == "end":
        try:
            found.end = _End.model_validate(raw)
        except ValidationError:
            found.refused["end"] += 1
        return
    if kind not in CHANGES:
        return
    try:
        change = _Change.model_validate(raw)
    except ValidationError:
        change = None
    last = found.changes[-1].seq if found.changes else since
    if change is None or change.seq <= last:
        # A change out of order is one the store's contract says never comes: it is refused, as one unread is.
        found.refused[kind] += 1
        found.stopped = True
    elif not found.stopped:
        found.changes.append(change)


def _record(
    conn: sqlite3.Connection,
    config: Config,
    name: str,
    changes: Sequence[_Change],
    through: int,
    *,
    whole: bool,
) -> dict[str, int]:
    """Record each change, then move source `name`'s cursor to `through`, in one transaction.

    `whole` says the run read the feed to its `end` line with nothing refused, which dates the cursor.

    Returns:
        The changes recorded of each kind.
    """
    recorded: Counter[str] = Counter()
    now = db.now()
    with db.transaction(conn):
        for change in changes:
            _record_thread(conn, change, now)
            if change.kind in COMMENT_CHANGES:
                _record_comment(conn, config, change, now)
                _to_conversation(conn, change)
            recorded[change.kind] += 1
        moved = sql.insert("observed_feeds", source=name, through=through, read_at=now if whole else None)
        conflict = "(source) DO UPDATE SET through = max(through, excluded.through), read_at = coalesce(?, read_at)"
        sql.execute(conn, moved.on_conflict(conflict, now if whole else None))
    return dict(recorded)


def _record_thread(conn: sqlite3.Connection, change: _Change, now: str) -> None:
    """Record the thread as `change` left it, unless a newer change is recorded."""
    anchor = change.anchor
    sql.execute(
        conn,
        sql.insert(
            "observed_artifact_threads",
            id=change.thread_id,
            artifact_id=change.artifact_id,
            origin=json.dumps(change.origin, sort_keys=True),
            ticket=change.ticket,
            exact=None if anchor is None else anchor.exact,
            prefix=None if anchor is None else anchor.prefix,
            suffix=None if anchor is None else anchor.suffix,
            anchored_version=change.anchored_version,
            state=change.state,
            anchor_status=None if anchor is None else change.anchor_status,
            seq=change.seq,
            observed_at=now,
        ).on_conflict(
            "(id) DO UPDATE SET artifact_id = excluded.artifact_id, origin = excluded.origin,"
            " ticket = excluded.ticket, exact = excluded.exact, prefix = excluded.prefix, suffix = excluded.suffix,"
            " anchored_version = excluded.anchored_version, state = excluded.state,"
            " anchor_status = excluded.anchor_status, seq = excluded.seq, observed_at = excluded.observed_at"
            " WHERE excluded.seq > seq",
        ),
    )


def _record_comment(conn: sqlite3.Connection, config: Config, change: _Change, now: str) -> None:
    """Record the comment as `change` left it, unless a newer change is recorded.

    Its author and how it arrived are the first change's read of it: a later change's author is whoever edited or
    deleted it. Its body is cut and marked as a tracker comment's is, and whether it carries the workers' marks is read
    here.
    """
    text = (change.body or "").strip()
    marked = conversation.worker_marked(text, config.trust.comment_prefix, config.trust.comment_suffix)
    sql.execute(
        conn,
        sql.insert(
            "observed_artifact_comments",
            id=change.comment_id,
            thread_id=change.thread_id,
            author=change.author.id,
            author_name=change.author.display_name,
            author_kind=change.author.kind,
            on_behalf_of=change.author.on_behalf_of,
            via=change.via,
            body=text[: conversation.MAX_COMMENT],
            truncated=len(text) > conversation.MAX_COMMENT,
            marked=marked,
            created_at=change.created_at,
            edited_at=change.edited_at,
            deleted_at=change.deleted_at,
            seq=change.seq,
            observed_at=now,
        ).on_conflict(
            "(id) DO UPDATE SET body = excluded.body, truncated = excluded.truncated, marked = excluded.marked,"
            " edited_at = excluded.edited_at, deleted_at = excluded.deleted_at, seq = excluded.seq,"
            " observed_at = excluded.observed_at WHERE excluded.seq > seq",
        ),
    )


def _to_conversation(conn: sqlite3.Connection, change: _Change) -> None:
    """Record the comment `change` carries in its artifact's ticket's conversation, quoting its passage (DESIGN §38).

    Once per comment, as it was first read, as a tracker comment is (§35): an edit after is not followed, and a comment
    first read deleted is not recorded. Only for a ticket the journal holds, since the origin is the worker's word. Its
    source is `worker` when the comment carries the workers' marks, else `artifact`; what it counts for is
    `artifact_authority`'s to decide.
    """
    observed = records.fetch_one(
        conn,
        records.ObservedArtifactComment,
        sql.select("*").from_("observed_artifact_comments").where("id = ?", change.comment_id),
    )
    key = change.ticket
    if observed is None or observed.deleted_at is not None or key is None or db.get_ticket(conn, key) is None:
        return
    text = _quoting(change.anchor, observed.body or "(no text)")
    body = text[: conversation.MAX_COMMENT]
    comment = db.Comment(
        id=f"{COMMENT_ID_PREFIX}{observed.id}",
        author=observed.author,
        at=observed.created_at,
        truncated=observed.truncated or len(text) > len(body),
    )
    source = "worker" if observed.marked else SOURCE
    conversation.record_comment(conn, key, comment, source=source, body=body, channel=conversation.ARTIFACTS)


def _quoting(anchor: _Anchor | None, body: str) -> str:
    """A comment's body under the passage it is on, quoted and cut to `MAX_QUOTE`, or as it is on a whole artifact.

    Returns:
        The text its message records.
    """
    if anchor is None:
        return body
    passage = anchor.exact if len(anchor.exact) <= MAX_QUOTE else anchor.exact[: MAX_QUOTE - 3] + "..."
    quoted = "\n".join(f"> {line}" if line else ">" for line in passage.splitlines())
    return f"{quoted}\n\n{body}"
