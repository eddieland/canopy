"""The mock journal's connector runs (DESIGN §30), for the Connectors page of `python -m canopy.serve --mock`.

Four days of the two sources that read, `jira` and canopy's own `github`: a poll every half hour, and the runs ticks 1
and 2 made. Most read everything. Three read less than asked: a `jira` poll on Oct 5 had a comment of ABC-101's
refused, one on Oct 7 met a 503 from the tracker for ABC-102, and an Oct 8 `github` poll had two check lines of PR 88
refused. A `github` poll on Oct 6 timed out and recorded nothing. `jira`'s latest run asked about two tickets the mock
never observed, so it reads stale; `github`'s asked about two PRs `reviews` and `drafts` observed within the half hour.
"""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from canopy.core import db, records
from canopy.core.vocab import ConnectorRunStatus, SourceKind
from canopy.serve.mock.reviews import PR_14, PR_88

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Iterator, Mapping

#: The tracker source the mock's config names.
JIRA = "jira"
#: canopy's own GitHub reader, the `vcs` source when none is configured.
GITHUB = "github"
#: A run as `seed` inserts it: its tick, source, start, end, kind, status, request, recorded and refused lines, what it
#: missed, and its stderr.
type _Row = tuple[int | None, str, str, str, SourceKind, ConnectorRunStatus, str, str, str, str | None, str]

# How far back the polls go, in minutes before T0, and how often they ran.
_FROM = -4 * 24 * 60
_EVERY = 30
# The ticks' runs: the tick and when it started, in minutes after T0 (the mock's `_fixtures`).
_TICKS = ((1, -121), (2, -60))
# What each source asked: the tracker its query and two tickets' comments, the reader the PRs canopy holds.
_JIRA_ASKED = {"query": "project = ABC", "tickets": [{"key": "ABC-101"}, {"key": "ABC-104"}]}
_GITHUB_ASKED = {"prs": [PR_88, PR_14]}
# A poll the tracker answered 503 for one ticket, and one that timed out, in their connectors' words.
_JIRA_503 = "ABC-102: the tracker answered 503 Service Unavailable; its comments were not read"
_TIMED_OUT = "httpx.ReadTimeout: timed out reading https://api.github.com/graphql after 120s"


@dataclass(frozen=True)
class _Short:
    """A run that read less than it was asked."""

    status: ConnectorRunStatus
    missed: str
    stderr: str = ""
    #: The lines canopy refused, by kind.
    refused: Mapping[str, int] | None = None
    #: How long it ran, in seconds, when not its source's usual; a timed-out run ran its whole timeout.
    seconds: int | None = None


# The polls that read less than asked, by source and minutes after T0.
_SHORT: Mapping[tuple[str, int], _Short] = {
    (JIRA, -4 * 24 * 60 + 18 * 60): _Short(
        ConnectorRunStatus.PARTIAL,
        "did not read 1 ticket (ABC-101) whole",
        refused={"comment": 1},
    ),
    (GITHUB, -2 * 24 * 60 - 9 * 60): _Short(
        ConnectorRunStatus.FAILED,
        f"it did not finish in 2 minutes: {_TIMED_OUT}",
        _TIMED_OUT,
        seconds=120,
    ),
    (JIRA, -24 * 60 - 3 * 60): _Short(ConnectorRunStatus.PARTIAL, "did not read 1 ticket (ABC-102) whole", _JIRA_503),
    (GITHUB, -4 * 60 - 30): _Short(
        ConnectorRunStatus.PARTIAL,
        f"did not read 1 PR ({PR_88}) whole",
        refused={"check": 2},
    ),
}


def seed(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """Insert the runs, oldest first, `at` turning minutes after T0 into a journal time."""
    # Oldest first, so a source's latest run has the highest id, as `canopy status` reads it.
    for tick_id, source, started, ended, kind, status, request, recorded, refused, missed, stderr in sorted(
        _runs(at),
        key=operator.itemgetter(2),
    ):
        records.insert(
            records.ConnectorRun,
            tick_id=tick_id,
            source=source,
            kind=kind,
            started_at=started,
            ended_at=ended,
            status=status,
            request=request,
            recorded=recorded,
            refused=refused,
            missed=missed,
            stderr=stderr,
        ).run(conn)


# Every run: each source's polls, then the ticks' runs, the reader a few seconds after the tracker.
def _runs(at: Callable[[int], str]) -> Iterator[_Row]:
    for n, minutes in enumerate(range(_FROM, 0, _EVERY)):
        for source in (JIRA, GITHUB):
            yield _row(at(minutes), source, n, short=_SHORT.get((source, minutes)))
    for tick_id, minutes in _TICKS:
        for source in (JIRA, GITHUB):
            yield _row(at(minutes), source, tick_id, tick_id=tick_id)


# One run of `source` that started on the minute `at`, the `n`th of its kind, read whole unless `short` says not.
def _row(at: str, source: str, n: int, *, tick_id: int | None = None, short: _Short | None = None) -> _Row:
    jira = source == JIRA
    started = db.parse_time(at) + timedelta(seconds=0 if jira else 15)
    # A tracker read is quick, the reader's longer, a few seconds apart from one run to the next.
    took = (4 + n * 7 % 11) if jira else (18 + n * 13 % 29)
    recorded: dict[str, int] = (
        {"comment": n % 3, "ticket": 6} if jira else {"check": n % 4 * 3, "pr": 2, "review": n % 2}
    )
    if short is not None and short.status is ConnectorRunStatus.FAILED:
        recorded = {}
    if short is not None and short.seconds is not None:
        took = short.seconds
    return (
        tick_id,
        source,
        db.format_time(started),
        db.format_time(started + timedelta(seconds=took)),
        SourceKind.TRACKER if jira else SourceKind.VCS,
        ConnectorRunStatus.OK if short is None else short.status,
        json.dumps(_JIRA_ASKED if jira else _GITHUB_ASKED),
        json.dumps({k: v for k, v in sorted(recorded.items()) if v}),
        json.dumps(dict(sorted((short.refused or {}).items())) if short is not None else {}),
        None if short is None else short.missed,
        "" if short is None else short.stderr,
    )
