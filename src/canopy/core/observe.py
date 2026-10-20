"""What canopy's GitHub reader saw of a PR (DESIGN §29, ROADMAP M36), recorded from each whole read.

The reader is a command of the operator's config, `canopy-connect-github` unless they name another, run through `procs`
with the PRs to read on stdin. It prints one JSON line per observation and an `end` line naming the PRs it read whole.
Each line is validated here; one that does not validate is passed over, and so is every line about a PR the `end` line
does not name, which keeps its old rows and their age: a cut-off read never looks like a PR whose reviews vanished.

An observation is a dated copy of what the reader saw, never authority (DESIGN §22): it decides which thread a draft
answers and what the PR's page shows, and nothing the overseer or a worker is told to do.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from canopy.core import db, sql
from canopy.core.config import notify_words
from canopy.core.conversation import MAX_MIRRORED
from canopy.core.vocab import PrState, ReviewItem, ReviewState
from canopy.infra import logs, procs

if TYPE_CHECKING:
    from canopy.core.config import Config

# How much of the reader's stderr a failure says.
_MAX_STDERR = 300


@dataclass(frozen=True)
class Read:
    """What one run of the reader read whole, and why it read less than it was asked to, if it did."""

    whole: frozenset[str]
    failure: str | None = None


def read(
    conn: sqlite3.Connection, config: Config, runner: procs.Runner, prs: Collection[str], log: logs.TickAdapter
) -> Read:
    """Run the reader for `prs` and record each PR it read whole, replacing what an earlier read recorded of it.

    A reader that cannot start, times out, or ends without its `end` line records nothing, and is logged.

    Returns:
        The PRs read whole, and the failure when that is not every one.
    """
    wanted = sorted(set(prs))
    if not wanted:
        return Read(frozenset())
    source = config.connect.vcs()
    argv = notify_words(source.cmd)
    try:
        result = runner.run(argv, stdin=json.dumps({"prs": wanted}), timeout=source.timeout_minutes * 60)
    except procs.ProcError as e:
        return _failed(log, wanted, f"the reader did not start: {e}")
    if result.timed_out:
        return _failed(log, wanted, f"the reader did not finish in {source.timeout_minutes} minutes")
    lines = list(_lines(result.stdout))
    ends = [line for line in lines if isinstance(line, _End)]
    if not ends:
        said = result.stderr.strip()[-_MAX_STDERR:]
        return _failed(log, wanted, "the reader ended without its end line" + (f": {said}" if said else ""))
    whole = frozenset(ends[-1].prs) & frozenset(wanted)
    now = db.now()
    with db.transaction(conn):
        for url in sorted(whole):
            _record(conn, url, [line for line in lines if not isinstance(line, _End) and line.of == url], now)
    missed = [url for url in wanted if url not in whole]
    if not missed:
        return Read(whole)
    said = result.stderr.strip()[-_MAX_STDERR:]
    return _failed(log, missed, "the reader did not read it whole" + (f": {said}" if said else ""), whole)


def _failed(log: logs.TickAdapter, prs: Iterable[str], why: str, whole: frozenset[str] = frozenset()) -> Read:
    log.warning("PR not read whole", extra={"prs": list(prs), "reason": why})
    return Read(whole, why)


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)


class _Pr(_Line):
    kind: Literal["pr"]
    url: str
    repository: str
    number: int
    head_sha: str | None = None
    base_ref: str | None = None
    state: PrState | None = None
    draft: bool = False
    mergeable: str | None = None
    author: str | None = None

    @property
    def of(self) -> str:
        return self.url


class _Thread(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    id: str
    path: str | None = None
    line: int | None = None
    side: Literal["left", "right"] | None = None
    outdated: bool = False
    resolved: bool = False


class _Review(_Line):
    kind: Literal["review"]
    item: ReviewItem
    pr: str
    id: int
    author: str | None = None
    bot: bool = False
    state: ReviewState | None = None
    time: str | None = None
    body: str = ""
    url: str | None = None
    review: int | None = None
    thread: _Thread | None = None

    @property
    def of(self) -> str:
        return self.pr


class _End(_Line):
    kind: Literal["end"]
    prs: list[str]


_KINDS: dict[str, type[_Pr | _Review | _End]] = {"pr": _Pr, "review": _Review, "end": _End}


def _lines(stdout: str) -> Iterable[_Pr | _Review | _End]:
    """Each line of the reader's output that validates as one of the kinds canopy reads; unknown kinds are skipped.

    Yields:
        Each line, in order.
    """
    for text in stdout.splitlines():
        try:
            raw: object = json.loads(text)
        except json.JSONDecodeError:
            continue
        model = _KINDS.get(str(raw.get("kind"))) if isinstance(raw, dict) else None
        if model is None:
            continue
        try:
            yield model.model_validate(raw)
        except ValidationError:
            continue


def _record(conn: sqlite3.Connection, url: str, lines: Iterable[_Pr | _Review], now: str) -> None:
    """Replace what the journal holds of `url` with what one whole read returned."""
    sql.execute(conn, sql.delete("observed_reviews").where("pr_url = ?", url))
    for line in lines:
        if isinstance(line, _Pr):
            row = sql.insert(
                "observed_prs",
                url=url,
                repository=line.repository,
                number=line.number,
                head_sha=line.head_sha,
                base_ref=line.base_ref,
                state=line.state,
                draft=line.draft,
                mergeable=line.mergeable,
                author=line.author,
                observed_at=now,
            )
            sql.execute(conn, row.or_replace())
            continue
        thread = line.thread if line.item is ReviewItem.COMMENT else None
        if line.item is ReviewItem.COMMENT and thread is None:
            continue
        review = sql.insert(
            "observed_reviews",
            pr_url=url,
            item=line.item,
            id=line.id,
            author=line.author,
            bot=line.bot,
            state=line.state if line.item is ReviewItem.REVIEW else None,
            created_at=line.time,
            body=line.body[:MAX_MIRRORED],
            url=line.url,
            review_id=line.review,
            thread_id=None if thread is None else thread.id,
            path=None if thread is None else thread.path,
            line=None if thread is None else thread.line,
            side=None if thread is None else thread.side,
            outdated=None if thread is None else thread.outdated,
            resolved=None if thread is None else thread.resolved,
            observed_at=now,
        )
        sql.execute(conn, review.or_replace())
