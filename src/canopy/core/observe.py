"""What canopy's connectors saw of the world (DESIGN §29, §30, ROADMAP M36), recorded from each whole read.

A connector is a command of the operator's config, `canopy-connect-github` for the `vcs` source unless they name
another, run through `procs` with a request on stdin naming what to observe. It prints one JSON line per observation
and last an `end` line naming the subjects it read whole: tickets, PRs, and repositories. Each line is validated and
bounded here before anything is written. A line of a kind its source does not own, or of no kind canopy reads, is
skipped; one that does not validate is refused and counted, and its subject is not whole this run, whatever `end` says.
A subject read whole has its rows replaced in one transaction; one not read whole keeps its old rows and their age, so
a cut-off read never looks like a check, review, or branch gone. Each completed check run is also kept by its run id
across reads, so a re-run at the same head is told from the run it repeats (§35). Each comment, review, review
comment, and completed check run takes its journal number when first observed, and keeps it across reads
(`item_numbers`): what a cursor passes. A run with no `end` line records nothing.

An observation is a dated copy of what a connector saw, never authority (DESIGN §22): in M36 it decides which thread a
draft answers and what the PR's page shows, and nothing the overseer or a worker is told to do. Each comment is also
recorded in its ticket's conversation when first observed, as data (§35).

A backfill asks the `vcs` source again about PRs observed before canopy kept GitHub's times, and takes only those times
from what it prints, so the reports can time PRs a tick will never read again.
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

from canopy.core import contract, conversation, db, item_numbers, records, sql
from canopy.core.config import REPO_NAME_RE, notify_words
from canopy.core.vocab import (
    CheckConclusion,
    CheckStatus,
    ConnectorRunStatus,
    MergeState,
    NumberedItem,
    PrState,
    ReviewItem,
    ReviewState,
    SourceKind,
    TicketState,
)
from canopy.infra import logs, procs

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

    from canopy.core.config import Config, Source

#: How much of a connector's stderr a run keeps.
MAX_STDERR = 300
#: A connector's stdout past this is cut off: the run fails and records nothing.
MAX_OUTPUT = 16 * 1024 * 1024
#: PRs one run of a backfill asks the `vcs` source about, so each run finishes within the source's timeout.
BACKFILL_BATCH = 50
#: A line longer than this is refused unread.
MAX_LINE = 1024 * 1024
#: A title is cut to this, on one line; a body, as a comment's is, to `conversation.MAX_COMMENT`.
MAX_TITLE = 200
#: More labels or blockers than this refuse the line: a list cut short would read as one removed.
MAX_LIST = 100
#: The longest name, path, or URL a line may carry; a longer one refuses the line, since a cut would change it.
MAX_NAME = 200
MAX_PATH = 1000
MAX_URL = 2000
#: The kinds each kind of source owns: a line of another kind is skipped, so one source never writes another's facts.
#: An `artifacts` source owns none of these: its feed is read past a cursor, in `artifact_feed`, never whole. Nor
#: does a `slack` source: what it reads is the operator's messages, recorded in `slack_replies`.
OWNS: Mapping[SourceKind, frozenset[str]] = {
    SourceKind.TRACKER: frozenset({"ticket", "comment"}),
    SourceKind.VCS: frozenset({"pr", "review", "check", "branch"}),
    SourceKind.ARTIFACTS: frozenset(),
    SourceKind.SLACK: frozenset(),
}
#: How a completed CI context ends red: what holds a unit at `ci_red`, and what makes a failed check a feedback plan's
#: item (DESIGN §32).
FAILED: AbstractSet[CheckConclusion] = frozenset(
    {
        CheckConclusion.FAILURE,
        CheckConclusion.ERROR,
        CheckConclusion.CANCELLED,
        CheckConclusion.TIMED_OUT,
        CheckConclusion.ACTION_REQUIRED,
        CheckConclusion.STARTUP_FAILURE,
    },
)
#: How a completed CI context passes. One `stale` neither passes nor fails: GitHub left it for a newer run.
PASSED: AbstractSet[CheckConclusion] = frozenset(
    {CheckConclusion.SUCCESS, CheckConclusion.NEUTRAL, CheckConclusion.SKIPPED},
)


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
    #: For a `slack` source, the workspace as canopy's messages to the sink name it, which files the sink's threads.
    repo: str | None = None
    #: For a `slack` source, its `operators`: the only Slack user ids whose replies the connector is asked to print.
    operators: Sequence[str] | None = None

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
        if self.repo is not None:
            found["repo"] = self.repo
        if self.operators is not None:
            found["operators"] = list(self.operators)
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
        case SourceKind.ARTIFACTS | SourceKind.SLACK:
            # A feed is read past a cursor (`artifact_feed`), and replies are messages (`slack_replies`): neither has a
            # subject read whole.
            whole = Whole()
        case _:
            assert_never(kind)
    recorded = _record(conn, config, kind, read, whole, operators=frozenset(source.operators))
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


def missing_times(conn: sqlite3.Connection) -> list[str]:
    """The merged and closed PRs observed with none of GitHub's times, as one read before canopy kept them.

    An open PR is read again every tick, which fills its times in; a merged or closed one whose ticket is done is never
    read again (§30), so only a backfill does.

    Returns:
        Their URLs, sorted.
    """
    found = (
        records.select(records.ObservedPr)
        .where("created_at IS NULL AND state IN (?, ?)", PrState.MERGED, PrState.CLOSED)
        .order_by("url")
        .all(conn)
    )
    return [pr.url for pr in found if is_pr_url(pr.url)]


@dataclass(frozen=True)
class Backfilled:
    """What a backfill of PRs' times did: the PRs it asked about, those it filled in, and those it could not read."""

    asked: int
    #: The PRs given at least one time.
    filled: int
    #: The PRs not read whole, in the order asked.
    unread: Sequence[str]
    #: Why a run read nothing, once per run that failed.
    failures: Sequence[str]


def backfill_times(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    prs: Sequence[str],
    *,
    log: logs.TickAdapter,
) -> Backfilled:
    """Ask the `vcs` source about `prs` again, `BACKFILL_BATCH` at a time, and fill in only the times each PR lacks.

    Nothing else the source prints is recorded: a PR's reviews, checks, state, and the time it was last observed are
    left as they were, so a merged PR's threads are not replaced, no check run is first observed today, and no comment
    reaches a conversation late. A time already held is kept. Each `pr` line is validated as a tick's is, and one whose
    PR is not read whole is not used.

    Returns:
        What it asked, filled, and could not read.
    """
    source = config.connect.vcs()
    filled = 0
    unread: list[str] = []
    failures: list[str] = []
    for start in range(0, len(prs), BACKFILL_BATCH):
        batch = prs[start : start + BACKFILL_BATCH]
        ran = run(runner, source, Request(prs=batch), log=log)
        if isinstance(ran, Observed):
            unread.extend(batch)
            failures.append(ran.missed or "the reader failed")
            continue
        found = _read(ran.stdout, SourceKind.VCS, config.trust.branch_prefix)
        if found.end is None:
            unread.extend(batch)
            failures.append("the reader ended without its end line")
            continue
        whole = found.whole(found.end).prs & frozenset(batch)
        unread.extend(pr for pr in batch if pr not in whole)
        lines = {line.url: line for line in found.lines if isinstance(line, _Pr) and line.url in whole}
        with db.transaction(conn):
            filled += sum(_fill_times(conn, line) for line in lines.values())
    log.info("backfilled PR times", extra={"asked": len(prs), "filled": filled, "unread": len(unread)})
    return Backfilled(asked=len(prs), filled=filled, unread=unread, failures=failures)


def _fill_times(conn: sqlite3.Connection, line: _Pr) -> bool:
    """Set each time of `line`'s PR that the journal does not hold and the line carries.

    Returns:
        Whether any was set.
    """
    held = records.select(records.ObservedPr).where("url = ?", line.url).one(conn)
    if held is None:
        return False
    pairs = (
        ("created_at", held.created_at, line.created_at),
        ("ready_at", held.ready_at, line.ready_at),
        ("review_requested_at", held.review_requested_at, line.review_requested_at),
        ("merged_at", held.merged_at, line.merged_at),
        ("closed_at", held.closed_at, line.closed_at),
    )
    times: dict[str, sql.Arg] = {name: read for name, kept, read in pairs if kept is None and read is not None}
    if not times:
        return False
    records.update(records.ObservedPr).set(**times).where("url = ?", line.url).run(conn)
    return True


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


def conflicts(pr: records.ObservedPr) -> bool | None:
    """Whether an observed PR conflicts with its base, as its host says: what holds a unit at `conflicted`.

    Returns:
        True when it conflicts, False when the host says it does not, and None while the host has not said.
    """
    if pr.mergeable == "conflicting" or pr.mergeable_state is MergeState.DIRTY:
        return True
    if pr.mergeable == "mergeable" or pr.mergeable_state not in (None, MergeState.UNKNOWN):
        return False
    return None


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
_Body = Annotated[str, contract.bounded(conversation.MAX_COMMENT)]


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
    # Cut where it is recorded, and marked truncated there.
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
    created_at: Time | None = None
    ready_at: Time | None = None
    review_requested_at: Time | None = None
    merged_at: Time | None = None
    closed_at: Time | None = None

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


def _record(
    conn: sqlite3.Connection,
    config: Config,
    kind: SourceKind,
    read: _Output,
    whole: Whole,
    *,
    operators: AbstractSet[str],
) -> dict[str, int]:
    """Replace what the journal holds of each subject read whole with what the run read of it, in one transaction.

    `operators` are the source's: the tracker accounts whose comments on a private ticket are the operator's messages.

    Returns:
        The lines recorded of each kind.
    """
    recorded: Counter[str] = Counter()
    now = db.now()
    with db.transaction(conn):
        if kind is SourceKind.TRACKER:
            for key in sorted(whole.tickets):
                records.delete(records.ObservedTicket).where("key = ?", key).run(conn)
            known = {str(r[0]) for r in sql.execute(conn, sql.select("key").from_("tickets"))}
        else:
            known = set[str]()
            for url in sorted(whole.prs):
                records.delete(records.ObservedReview).where("pr_url = ?", url).run(conn)
                records.delete(records.ObservedCheck).where("pr_url = ?", url).run(conn)
                records.delete(records.ObservedPr).where("url = ?", url).run(conn)
            for repo in sorted(whole.repositories):
                records.delete(records.ObservedBranch).where("repository = ?", repo).run(conn)
        for line in read.lines:
            if line.of not in (whole.tickets | whole.prs | whole.repositories):
                continue
            if _insert(conn, config, line, now, known, operators=operators):
                recorded[line.kind] += 1
    return dict(recorded)


def _insert(
    conn: sqlite3.Connection,
    config: Config,
    line: _Observation,
    now: str,
    known: Collection[str],
    *,
    operators: AbstractSet[str],
) -> bool:
    """Record one line of a subject read whole.

    Returns:
        Whether it was recorded: a comment already in the journal, or on a ticket the journal does not hold, is not.
    """
    match line:
        case _Ticket():
            labels = [{"name": label.name, "added_at": label.added_at} for label in line.labels]
            records.insert(
                records.ObservedTicket,
                key=line.key,
                title=line.title,
                body=line.body,
                state=line.state,
                labels=json.dumps(labels),
                updated_at=line.updated_at,
                blockers=json.dumps(line.blockers),
                observed_at=now,
            ).or_replace().run(conn)
        case _Comment():
            if line.ticket not in known:
                return False
            return _record_comment(conn, config, line, now, operators=operators)
        case _Pr():
            records.insert(
                records.ObservedPr,
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
                created_at=line.created_at,
                ready_at=line.ready_at,
                review_requested_at=line.review_requested_at,
                merged_at=line.merged_at,
                closed_at=line.closed_at,
            ).or_replace().run(conn)
        case _Review():
            _insert_review(conn, line, now)
        case _Check():
            number = _keep_check_run(conn, line, now)
            records.insert(
                records.ObservedCheck,
                pr_url=line.pr,
                name=line.name,
                head_sha=line.head_sha,
                status=line.status,
                conclusion=line.conclusion,
                run_id=line.run_id,
                url=line.url,
                observed_at=now,
                number=number,
            ).or_replace().run(conn)
        case _Branch():
            records.insert(
                records.ObservedBranch,
                repository=line.repository,
                name=line.name,
                head_sha=line.head_sha,
                observed_at=now,
            ).or_replace().run(conn)
    return True


def _record_comment(
    conn: sqlite3.Connection,
    config: Config,
    line: _Comment,
    now: str,
    *,
    operators: AbstractSet[str],
) -> bool:
    """Record a comment the tracker connector read in `observed_comments`, once per ticket and comment id.

    One new to the journal is recorded in its ticket's conversation too, in the same transaction and with the same text,
    source `worker` when it carries the workers' marks, else `tracker` (DESIGN §35). Its body is cut and marked, and an
    edit after is not followed, here or in the conversation. One by an account in `operators` on a private ticket, with
    none of the workers' marks, is the operator's message instead, its text whole (§22,
    `conversation.record_operator_comment`).

    Returns:
        True if the comment was new to the journal.
    """
    text = line.body.strip() or "(no text)"
    body, truncated = text[: conversation.MAX_COMMENT], len(text) > conversation.MAX_COMMENT
    source = (
        "worker"
        if conversation.worker_marked(line.body, config.trust.comment_prefix, config.trust.comment_suffix)
        else "tracker"
    )
    cursor = (
        records.insert(
            records.ObservedComment,
            ticket=line.ticket,
            id=line.id,
            author=line.author,
            commented_at=line.time,
            body=body,
            truncated=truncated,
            source=source,
            observed_at=now,
        )
        .or_ignore()
        .run(conn)
    )
    if cursor.rowcount != 1:
        return False
    number = item_numbers.take(conn, NumberedItem.COMMENT, line.ticket, line.id, at=now)
    the_comment = records.update(records.ObservedComment).where("ticket = ? AND id = ?", line.ticket, line.id)
    the_comment.set(number=number).run(conn)
    comment = db.Comment(id=line.id, author=line.author, at=line.time, truncated=truncated)
    if source == "tracker" and line.author in operators:
        whole = db.Comment(id=line.id, author=line.author, at=line.time, truncated=False)
        if conversation.record_operator_comment(conn, line.ticket, whole, line.body.strip()):
            return True
    conversation.record_comment(conn, line.ticket, comment, source=source, body=body, channel=conversation.TRACKER)
    return True


def _insert_review(conn: sqlite3.Connection, line: _Review, now: str) -> None:
    thread = line.thread if line.item is ReviewItem.COMMENT else None
    kind = NumberedItem.REVIEW if line.item is ReviewItem.REVIEW else NumberedItem.REVIEW_COMMENT
    records.insert(
        records.ObservedReview,
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
        # Kept across reads, which replace the row: what is newer than the `review` cursor (DESIGN §35).
        number=item_numbers.take(conn, kind, line.pr, line.id, at=now),
    ).or_replace().run(conn)


def _keep_check_run(conn: sqlite3.Connection, line: _Check, now: str) -> int | None:
    """Keep a completed check run in `observed_check_runs`, once per run id, as it was first observed (DESIGN §35).

    A later read replaces the PR's `observed_checks` with the newest run of each context, so this is what tells a
    re-run at the same head from the run it repeats. A commit status has no run to keep. The run takes its journal
    number when first observed completed, what a `ci` cursor passes: a run still going is no failure to hand a worker.

    Returns:
        The run's number; None for a run still going, or a commit status.
    """
    if line.status is not CheckStatus.COMPLETED or line.run_id is None or line.conclusion is None:
        return None
    number = item_numbers.take(conn, NumberedItem.CHECK_RUN, line.pr, line.run_id, at=now)
    records.insert(
        records.ObservedCheckRun,
        pr_url=line.pr,
        run_id=line.run_id,
        name=line.name,
        head_sha=line.head_sha,
        conclusion=line.conclusion,
        observed_at=now,
        number=number,
    ).or_ignore().run(conn)
    return number


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
