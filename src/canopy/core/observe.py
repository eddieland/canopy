"""What canopy's connectors saw of the world (DESIGN §29, §30, ROADMAP M36), recorded from each whole read.

A connector is a command of the operator's config, `canopy-connect-github` for the `vcs` source unless they name
another, run through `procs` with a request on stdin naming what to observe. It prints one JSON line per observation
and last an `end` line naming the subjects it read whole: tickets, PRs, and repositories. Each line is validated and
bounded here before anything is written. A line of a kind its source does not own, or of no kind canopy reads, is
skipped; one that does not validate is refused and counted, and its subject is not whole this run, whatever `end` says.
A subject read whole has its rows replaced in one transaction; one not read whole keeps its old rows and their age, so
a cut-off read never looks like a check, review, or branch gone. A run with no `end` line records nothing.

An observation is a dated copy of what a connector saw, never authority (DESIGN §22): in M36 it decides which thread a
draft answers and what the PR's page shows, and nothing the overseer or a worker is told to do.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal, assert_never, cast

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from canopy.core import contract, conversation, db, sql
from canopy.core.config import REPO_NAME_RE, notify_words
from canopy.core.vocab import (
    CheckConclusion,
    CheckStatus,
    ConnectorRunStatus,
    MergeState,
    PrState,
    ReviewItem,
    ReviewState,
    SourceKind,
    TicketState,
)
from canopy.infra import logs, procs

if TYPE_CHECKING:
    from canopy.core.config import Config, Source

#: How much of a connector's stderr a run keeps.
MAX_STDERR = 300
#: A connector's stdout past this is cut off: the run fails and records nothing.
MAX_OUTPUT = 16 * 1024 * 1024
#: A line longer than this is refused unread.
MAX_LINE = 1024 * 1024
#: A title is cut to this, on one line; a body to `conversation.MAX_MIRRORED`, as a mirrored comment's is.
MAX_TITLE = 200
#: More labels or blockers than this refuse the line: a list cut short would read as one removed.
MAX_LIST = 100
#: The longest name, path, or URL a line may carry; a longer one refuses the line, since a cut would change it.
MAX_NAME = 200
MAX_PATH = 1000
MAX_URL = 2000
#: The kinds each kind of source owns: a line of another kind is skipped, so one source never writes another's facts.
#: An `artifacts` source owns none of these: its feed is read past a cursor, in `artifact_feed`, never whole.
OWNS: Mapping[SourceKind, frozenset[str]] = {
    SourceKind.TRACKER: frozenset({"ticket", "comment"}),
    SourceKind.VCS: frozenset({"pr", "review", "check", "branch"}),
    SourceKind.ARTIFACTS: frozenset(),
}


@dataclass(frozen=True)
class AskedTicket:
    """A ticket a `tracker` source is asked about, with the time of the newest tracker comment the journal holds."""

    key: str
    comments_since: str | None = None


@dataclass(frozen=True)
class Repository:
    """A repository of the map a `vcs` source is asked about: its name, and its clone URL without credentials."""

    name: str
    url: str | None = None


@dataclass(frozen=True)
class Request:
    """What one run of a source is asked to observe (DESIGN §30). A field left None is not asked, and not sent."""

    query: str | None = None
    tickets: Sequence[AskedTicket] | None = None
    prs: Sequence[str] | None = None
    repositories: Sequence[Repository] | None = None
    branch_prefix: str | None = None
    review_query: str | None = None
    #: For an `artifacts` source, the feed's cursor: the `through` its last run's `end` line named, 0 at first.
    since: int | None = None

    def to_json(self) -> dict[str, object]:
        """The request as the connector reads it on stdin.

        Returns:
            One JSON object, holding only the keys asked.
        """
        found: dict[str, object] = {}
        if self.query is not None:
            found["query"] = self.query
        if self.tickets is not None:
            found["tickets"] = [
                {"key": t.key, **({"comments_since": t.comments_since} if t.comments_since else {})}
                for t in self.tickets
            ]
        if self.prs is not None:
            found["prs"] = list(self.prs)
        if self.repositories is not None:
            found["repositories"] = [{"name": r.name, **({"url": r.url} if r.url else {})} for r in self.repositories]
        if self.branch_prefix is not None:
            found["branch_prefix"] = self.branch_prefix
        if self.review_query is not None:
            found["review_query"] = self.review_query
        if self.since is not None:
            found["since"] = self.since
        return found


@dataclass(frozen=True)
class Whole:
    """The subjects one run read whole: their old rows were replaced by what it read."""

    tickets: frozenset[str] = frozenset()
    prs: frozenset[str] = frozenset()
    repositories: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Observed:
    """How one run of a source ended: its status, what it read whole, and what it did not."""

    status: ConnectorRunStatus
    started_at: str
    ended_at: str
    whole: Whole = field(default_factory=Whole)
    #: The lines recorded, and refused, of each kind.
    recorded: Mapping[str, int] = field(default_factory=dict[str, int])
    refused: Mapping[str, int] = field(default_factory=dict[str, int])
    #: The harness's words for what the run did not read; None when it read everything asked.
    missed: str | None = None
    #: The last `MAX_STDERR` characters of its stderr.
    stderr: str = ""
    #: The query's and the review query's results, in order, when the run read them to the end.
    query_result: Sequence[str] | None = None
    review_query_result: Sequence[str] | None = None


def observe(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    source: Source,
    request: Request,
    *,
    log: logs.TickAdapter,
) -> Observed:
    """Run `source`'s connector for `request` and record each subject it read whole, replacing what was there.

    A connector that cannot start, times out, prints more than `MAX_OUTPUT`, or ends without its `end` line records
    nothing and is `failed`; one that read less than it was asked is `partial`. Either is logged.

    Returns:
        How the run ended.
    """
    ran = run(runner, source, request, log=log)
    if isinstance(ran, Observed):
        return ran
    started, stderr = ran.started_at, ran.stderr
    kind = SourceKind(source.kind)
    read = _read(ran.stdout, kind, request.branch_prefix or config.trust.branch_prefix)
    if read.end is None:
        return failed(log, started, "it ended without its end line", stderr, read.refused)
    named = read.whole(read.end)
    # A source reads whole only the subjects of the kinds it owns.
    match kind:
        case SourceKind.TRACKER:
            whole = Whole(tickets=named.tickets)
        case SourceKind.VCS:
            whole = Whole(prs=named.prs, repositories=named.repositories)
        case SourceKind.ARTIFACTS:
            # Its feed is read past a cursor (`artifact_feed`), so no subject of it is whole.
            whole = Whole()
        case _:
            assert_never(kind)
    recorded = _record(conn, config, kind, read, whole)
    query = list(read.end.query) if request.query is not None and read.end.query is not None else None
    review = (
        list(read.end.review_query) if request.review_query is not None and read.end.review_query is not None else None
    )
    missed = _missed(request, whole, query_read=query is not None, review_read=review is not None)
    status = ConnectorRunStatus.OK if missed is None else ConnectorRunStatus.PARTIAL
    if missed is not None:
        log.warning("connector read less than it was asked", extra={"missed": missed, "refused": read.refused})
    return Observed(
        status=status,
        started_at=started,
        ended_at=db.now(),
        whole=whole,
        recorded=recorded,
        refused=dict(read.refused),
        missed=missed,
        stderr=stderr,
        query_result=query,
        review_query_result=review,
    )


@dataclass(frozen=True)
class Printed:
    """What a connector printed, having run to its end within its timeout and `MAX_OUTPUT`."""

    started_at: str
    stdout: str
    #: The last `MAX_STDERR` characters of its stderr.
    stderr: str


def run(runner: procs.Runner, source: Source, request: Request, *, log: logs.TickAdapter) -> Printed | Observed:
    """Run `source`'s connector for `request`, the request on its stdin, under its timeout and `MAX_OUTPUT`.

    Returns:
        What it printed; or, when it did not start, timed out, or printed more than `MAX_OUTPUT`, the `failed` run,
        which records nothing.
    """
    started = db.now()
    printed = _Printed()
    try:
        result = runner.run(
            notify_words(source.cmd),
            stdin=json.dumps(request.to_json()),
            timeout=source.timeout_minutes * 60,
            on_line=printed.count,
        )
    except _TooMuchError:
        return failed(log, started, f"it printed more than {MAX_OUTPUT // (1024 * 1024)} MiB")
    except procs.ProcError as e:
        return failed(log, started, f"it did not start: {e}")
    stderr = result.stderr.strip()[-MAX_STDERR:]
    if result.timed_out:
        return failed(log, started, f"it did not finish in {source.timeout_minutes} minutes", stderr)
    if len(result.stdout) > MAX_OUTPUT:
        return failed(log, started, f"it printed more than {MAX_OUTPUT // (1024 * 1024)} MiB", stderr)
    return Printed(started, result.stdout, stderr)


def failed(
    log: logs.TickAdapter,
    started: str,
    why: str,
    stderr: str = "",
    refused: Mapping[str, int] | None = None,
) -> Observed:
    """Log a run that records nothing.

    Returns:
        The `failed` run, its `missed` saying why, with the tail of its stderr.
    """
    log.warning("connector failed", extra={"reason": why})
    missed = f"{why}: {stderr}" if stderr else why
    return Observed(
        ConnectorRunStatus.FAILED,
        started,
        db.now(),
        refused=dict(refused or {}),
        missed=missed,
        stderr=stderr,
    )


@dataclass(frozen=True)
class Read:
    """What one read of PRs read whole, and why it read less than it was asked to, if it did."""

    whole: frozenset[str]
    failure: str | None = None


def read(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    prs: Collection[str],
    log: logs.TickAdapter,
) -> Read:
    """Run the `vcs` source for `prs` alone, as §29's reads after a run and before a send do, and record what it read.

    Returns:
        The PRs read whole, and the failure when that is not every one.
    """
    wanted = sorted(set(prs))
    if not wanted:
        return Read(frozenset())
    found = observe(conn, config, runner, config.connect.vcs(), Request(prs=wanted), log=log)
    whole = found.whole.prs & frozenset(wanted)
    if found.status is ConnectorRunStatus.FAILED:
        return Read(whole, f"the reader failed: {found.missed}")
    if whole == frozenset(wanted):
        return Read(whole)
    said = f": {found.stderr}" if found.stderr else ""
    return Read(whole, f"the reader did not read it whole{said}")


class _TooMuchError(Exception):
    """A connector printed more than `MAX_OUTPUT`: raised from `on_line`, which kills it."""


class _Printed:
    """Counts what a connector prints, as it prints it, and stops it past `MAX_OUTPUT`."""

    def __init__(self) -> None:
        self.size = 0

    def count(self, line: str) -> None:
        self.size += len(line)
        if self.size > MAX_OUTPUT:
            raise _TooMuchError


# What a line carries


def text_of(limit: int, pattern: re.Pattern[str] | None = None) -> AfterValidator:
    """Refuse a string longer than `limit`, not printable, or not matching `pattern`: a cut would change what it says.

    Returns:
        A validator that passes such a string through unchanged.
    """

    def check(value: str) -> str:
        if not value or len(value) > limit or not value.isprintable():
            raise ValueError(f"must be printable, 1 to {limit} characters")
        if pattern is not None and not pattern.fullmatch(value):
            raise ValueError(f"must match {pattern.pattern}")
        return value

    return AfterValidator(check)


def _time(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value) if len(value) <= conversation.MAX_TIME else None
    except ValueError:
        moment = None
    if moment is None:
        raise ValueError("must be an ISO 8601 time")
    # A time with no offset is the source's UTC.
    return db.format_time(moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC))


def is_pr_url(value: str) -> bool:
    """Whether `value` is a PR's URL as a line names one: only such a PR is asked about, since no other can be read.

    Returns:
        True for a plain `https://HOST/OWNER/REPO/pull/N`.
    """
    return contract.plain_url(value, conversation.MAX_PR_URL) and conversation.PR_URL_RE.fullmatch(value) is not None


def _pr_url(value: str) -> str:
    if not is_pr_url(value):
        raise ValueError("must be a PR's URL")
    return value


_LOGIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\[\]-]*")
_SHA_RE = re.compile(r"[0-9a-f]{7,64}")
_HOST_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_REF_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
_NODE_RE = re.compile(r"[A-Za-z0-9_=-]+")
# Plain ref components, as the branch prefix is: nothing git reads specially.
_BRANCH_RE = re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9_.-]*/)*[A-Za-z0-9][A-Za-z0-9_.-]*")

_Key = Annotated[str, text_of(conversation.MAX_KEY, conversation.KEY_RE)]
#: An ISO 8601 time, as the journal writes one; a time with no offset is the source's UTC.
Time = Annotated[str, AfterValidator(_time)]
_PrUrl = Annotated[str, AfterValidator(_pr_url)]
_Url = Annotated[str, contract.url(MAX_URL)]
_Login = Annotated[str, text_of(MAX_NAME, _LOGIN_RE)]
_Sha = Annotated[str, text_of(64, _SHA_RE)]
_Name = Annotated[str, text_of(MAX_NAME)]
_Title = Annotated[str, contract.one_line, contract.bounded(MAX_TITLE)]
_Body = Annotated[str, contract.bounded(conversation.MAX_MIRRORED)]


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)


class _Label(_Line):
    name: _Name
    added_at: Time | None = None


class _Ticket(_Line):
    kind: Literal["ticket"]
    key: _Key
    title: _Title
    body: _Body = ""
    state: TicketState
    labels: Annotated[list[_Label], Field(max_length=MAX_LIST)] = []
    updated_at: Time | None = None
    blockers: Annotated[list[_Key], Field(max_length=MAX_LIST)] = []

    @property
    def of(self) -> str:
        return self.key


class _Comment(_Line):
    kind: Literal["comment"]
    ticket: _Key
    id: Annotated[str, text_of(200, conversation.COMMENT_ID_RE)]
    author: Annotated[str, text_of(conversation.MAX_AUTHOR, re.compile(r"\S+"))]
    time: Time
    # Cut where it is recorded, and marked truncated there, as a mirrored comment is.
    body: str = ""

    @property
    def of(self) -> str:
        return self.ticket


class _Pr(_Line):
    kind: Literal["pr"]
    url: _PrUrl
    repository: Annotated[str, text_of(MAX_NAME, _HOST_REPO_RE)]
    number: Annotated[int, Field(ge=1)]
    head_sha: _Sha | None = None
    base_ref: Annotated[str, text_of(255, _REF_RE)] | None = None
    state: PrState | None = None
    draft: bool = False
    mergeable: Literal["mergeable", "conflicting", "unknown"] | None = None
    mergeable_state: MergeState | None = None
    author: _Login | None = None
    labels: Annotated[list[_Name], Field(max_length=MAX_LIST)] = []
    title: _Title | None = None

    @property
    def of(self) -> str:
        return self.url


class _Thread(_Line):
    id: Annotated[str, text_of(MAX_NAME, _NODE_RE)]
    path: Annotated[str, text_of(MAX_PATH)] | None = None
    line: Annotated[int, Field(ge=0)] | None = None
    side: Literal["left", "right"] | None = None
    outdated: bool = False
    resolved: bool = False


class _Review(_Line):
    kind: Literal["review"]
    item: ReviewItem
    pr: _PrUrl
    id: Annotated[int, Field(ge=1)]
    author: _Login | None = None
    bot: bool = False
    state: ReviewState | None = None
    time: Time | None = None
    body: _Body = ""
    url: _Url | None = None
    review: Annotated[int, Field(ge=1)] | None = None
    thread: _Thread | None = None
    commit: _Sha | None = None

    @model_validator(mode="after")
    def _a_comment_has_its_thread(self) -> _Review:
        if self.item is ReviewItem.COMMENT and self.thread is None:
            raise ValueError("a review comment names its thread")
        return self

    @property
    def of(self) -> str:
        return self.pr


class _Check(_Line):
    kind: Literal["check"]
    pr: _PrUrl
    head_sha: _Sha
    name: _Name
    status: CheckStatus
    conclusion: CheckConclusion | None = None
    run_id: Annotated[int, Field(ge=0)] | None = None
    url: _Url | None = None

    @property
    def of(self) -> str:
        return self.pr


class _Branch(_Line):
    kind: Literal["branch"]
    repository: Annotated[str, text_of(MAX_NAME, REPO_NAME_RE)]
    name: Annotated[str, text_of(255, _BRANCH_RE)]
    head_sha: _Sha

    @property
    def of(self) -> str:
        return self.repository


class _End(_Line):
    kind: Literal["end"]
    tickets: list[str] = []
    prs: list[str] = []
    repositories: list[str] = []
    query: list[_Key] | None = None
    review_query: list[_PrUrl] | None = None


type _Observation = _Ticket | _Comment | _Pr | _Review | _Check | _Branch
_KINDS: Mapping[str, type[_Observation]] = {
    "ticket": _Ticket,
    "comment": _Comment,
    "pr": _Pr,
    "review": _Review,
    "check": _Check,
    "branch": _Branch,
}
# What each kind is about, and the field that names it: a refused line's subject is not whole this run.
_SUBJECTS: Mapping[str, tuple[Literal["tickets", "prs", "repositories"], str]] = {
    "ticket": ("tickets", "key"),
    "comment": ("tickets", "ticket"),
    "pr": ("prs", "url"),
    "review": ("prs", "pr"),
    "check": ("prs", "pr"),
    "branch": ("repositories", "repository"),
}


@dataclass
class _Output:
    """A connector's output as validated: its lines, its last `end` line, and what was refused."""

    lines: list[_Observation] = field(default_factory=list[_Observation])
    end: _End | None = None
    refused: Counter[str] = field(default_factory=Counter[str])
    #: The subjects a refused line was about, by what they are; a kind in `unread` had a line whose subject is unknown.
    tainted: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    unread: set[str] = field(default_factory=set[str])

    def whole(self, end: _End) -> Whole:
        """The subjects `end` names, less any a refused line was about.

        Returns:
            The subjects read whole.
        """

        def of(what: Literal["tickets", "prs", "repositories"], named: Iterable[str]) -> frozenset[str]:
            if what in self.unread:
                return frozenset()
            return frozenset(named) - self.tainted.get(what, set())

        return Whole(of("tickets", end.tickets), of("prs", end.prs), of("repositories", end.repositories))


def _read(stdout: str, kind: SourceKind, prefix: str) -> _Output:
    """Validate each line of a connector's output; a kind the source does not own, or no kind canopy reads, is skipped.

    Returns:
        The lines, the last `end` line, and what was refused.
    """
    found = _Output()
    for text in stdout.splitlines():
        if len(text) > MAX_LINE:
            found.refused["unread"] += 1
            found.unread.update(("tickets", "prs", "repositories"))
            continue
        try:
            raw: object = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            _take(found, cast("dict[str, object]", raw), kind, prefix)
    return found


def _take(found: _Output, raw: Mapping[str, object], kind: SourceKind, prefix: str) -> None:
    """Validate one JSON object of a connector's output into `found`, or count it refused and taint its subject."""
    line_kind = str(raw.get("kind"))
    if line_kind == "end":
        try:
            found.end = _End.model_validate(raw)
        except ValidationError:
            found.refused["end"] += 1
        return
    model = _KINDS.get(line_kind)
    if model is None or line_kind not in OWNS[kind]:
        return
    try:
        line = model.model_validate(raw)
    except ValidationError:
        line = None
    if line is not None and not (isinstance(line, _Branch) and not line.name.startswith(prefix)):
        found.lines.append(line)
        return
    found.refused[line_kind] += 1
    what, key = _SUBJECTS[line_kind]
    subject = raw.get(key)
    if isinstance(subject, str):
        found.tainted.setdefault(what, set()).add(subject)
    else:
        found.unread.add(what)


def _record(conn: sqlite3.Connection, config: Config, kind: SourceKind, read: _Output, whole: Whole) -> dict[str, int]:
    """Replace what the journal holds of each subject read whole with what the run read of it, in one transaction.

    Returns:
        The lines recorded of each kind.
    """
    recorded: Counter[str] = Counter()
    now = db.now()
    with db.transaction(conn):
        if kind is SourceKind.TRACKER:
            for key in sorted(whole.tickets):
                sql.execute(conn, sql.delete("observed_tickets").where("key = ?", key))
            known = {str(r[0]) for r in sql.execute(conn, sql.select("key").from_("tickets"))}
        else:
            known = set[str]()
            for url in sorted(whole.prs):
                sql.execute(conn, sql.delete("observed_reviews").where("pr_url = ?", url))
                sql.execute(conn, sql.delete("observed_checks").where("pr_url = ?", url))
                sql.execute(conn, sql.delete("observed_prs").where("url = ?", url))
            for repo in sorted(whole.repositories):
                sql.execute(conn, sql.delete("observed_branches").where("repository = ?", repo))
        for line in read.lines:
            if line.of not in (whole.tickets | whole.prs | whole.repositories):
                continue
            if _insert(conn, config, line, now, known):
                recorded[line.kind] += 1
    return dict(recorded)


def _insert(conn: sqlite3.Connection, config: Config, line: _Observation, now: str, known: Collection[str]) -> bool:
    """Record one line of a subject read whole.

    Returns:
        Whether it was recorded: a comment already in the journal, or on a ticket the journal does not hold, is not.
    """
    match line:
        case _Ticket():
            labels = [{"name": label.name, "added_at": label.added_at} for label in line.labels]
            sql.execute(
                conn,
                sql.insert(
                    "observed_tickets",
                    key=line.key,
                    title=line.title,
                    body=line.body,
                    state=line.state,
                    labels=json.dumps(labels),
                    updated_at=line.updated_at,
                    blockers=json.dumps(line.blockers),
                    observed_at=now,
                ).or_replace(),
            )
        case _Comment():
            if line.ticket not in known:
                return False
            return _record_comment(conn, config, line, now)
        case _Pr():
            sql.execute(
                conn,
                sql.insert(
                    "observed_prs",
                    url=line.url,
                    repository=line.repository,
                    number=line.number,
                    head_sha=line.head_sha,
                    base_ref=line.base_ref,
                    state=line.state,
                    draft=line.draft,
                    mergeable=line.mergeable,
                    author=line.author,
                    observed_at=now,
                    labels=json.dumps(line.labels),
                    mergeable_state=line.mergeable_state,
                    title=line.title,
                ).or_replace(),
            )
        case _Review():
            _insert_review(conn, line, now)
        case _Check():
            sql.execute(
                conn,
                sql.insert(
                    "observed_checks",
                    pr_url=line.pr,
                    name=line.name,
                    head_sha=line.head_sha,
                    status=line.status,
                    conclusion=line.conclusion,
                    run_id=line.run_id,
                    url=line.url,
                    observed_at=now,
                ).or_replace(),
            )
        case _Branch():
            sql.execute(
                conn,
                sql.insert(
                    "observed_branches",
                    repository=line.repository,
                    name=line.name,
                    head_sha=line.head_sha,
                    observed_at=now,
                ).or_replace(),
            )
    return True


def _record_comment(conn: sqlite3.Connection, config: Config, line: _Comment, now: str) -> bool:
    """Record a comment the tracker connector read in `observed_comments`, once per ticket and comment id.

    Not in `messages`: in M36 the observations are in shadow, so no worker's prompt or overseer's state block carries
    a comment the overseer did not mirror. It is cut and marked as `mirror` cuts one, and an edit after is not followed.

    Returns:
        True if the comment was new to the journal.
    """
    text = line.body.strip() or "(no text)"
    source = (
        "worker"
        if conversation.worker_marked(line.body, config.trust.comment_prefix, config.trust.comment_suffix)
        else "tracker"
    )
    cursor = sql.execute(
        conn,
        sql.insert(
            "observed_comments",
            ticket=line.ticket,
            id=line.id,
            author=line.author,
            commented_at=line.time,
            body=text[: conversation.MAX_MIRRORED],
            truncated=len(text) > conversation.MAX_MIRRORED,
            source=source,
            observed_at=now,
        ).or_ignore(),
    )
    return cursor.rowcount == 1


def _insert_review(conn: sqlite3.Connection, line: _Review, now: str) -> None:
    thread = line.thread if line.item is ReviewItem.COMMENT else None
    sql.execute(
        conn,
        sql.insert(
            "observed_reviews",
            pr_url=line.pr,
            item=line.item,
            id=line.id,
            author=line.author,
            bot=line.bot,
            state=line.state if line.item is ReviewItem.REVIEW else None,
            created_at=line.time,
            body=line.body,
            url=line.url,
            review_id=line.review,
            thread_id=None if thread is None else thread.id,
            path=None if thread is None else thread.path,
            line=None if thread is None else thread.line,
            side=None if thread is None else thread.side,
            outdated=None if thread is None else thread.outdated,
            resolved=None if thread is None else thread.resolved,
            observed_at=now,
            commit_sha=line.commit if line.item is ReviewItem.REVIEW else None,
        ).or_replace(),
    )


# How many subjects a run's `missed` names before it counts the rest.
_NAMED = 5


def _missed(request: Request, whole: Whole, *, query_read: bool, review_read: bool) -> str | None:
    """Say what the run was asked and did not read whole, or None when it read everything.

    Returns:
        The subjects not read, a few by name and the rest counted, or None.
    """
    gaps: list[str] = []
    for what, asked, read_whole in (
        ("ticket", [t.key for t in request.tickets or ()], whole.tickets),
        ("PR", list(request.prs or ()), whole.prs),
        ("repository", [r.name for r in request.repositories or ()], whole.repositories),
    ):
        missing = [subject for subject in asked if subject not in read_whole]
        if missing:
            more = f" and {len(missing) - _NAMED} more" if len(missing) > _NAMED else ""
            named = ", ".join(missing[:_NAMED]) + more
            gaps.append(f"{len(missing)} {what}{'s' if len(missing) != 1 else ''} ({named})")
    if request.query is not None and not query_read:
        gaps.append("the query")
    if request.review_query is not None and not review_read:
        gaps.append("the review query")
    return f"did not read {'; '.join(gaps)} whole" if gaps else None
