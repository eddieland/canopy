"""A review's impact as the harness holds it (DESIGN §21), and what it ranks (§14).

The reviewer judges a change's impact from the PR's text, which its author wrote (TRUST_MODEL T1), so a change to a path
in `review.high_impact_paths` is `high` whatever the reviewer says: the harness reads the paths from git, over the
range the review's kept diff covers, and raises the impact, never lowers it. `high` ranks attention only: an item
about a PR, or its ticket, whose latest reviewed commit has a `high` review comes first.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import records, sql
from canopy.core import review_result as result
from canopy.core.vocab import ReviewRunStatus
from canopy.infra.text import printable

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Set as AbstractSet


#: How much of a matched path a note shows: its name is the PR author's text.
MAX_SHOWN_PATH = 200


@dataclass(frozen=True)
class Match:
    """A path a change touches that an entry of `review.high_impact_paths` covers."""

    path: str
    entry: str

    def note(self, reported: str) -> str:
        """The harness's note on a review it recorded `high` over the reviewer's `reported` impact.

        Returns:
            The note, naming the path on one line, without control characters, and cut to `MAX_SHOWN_PATH`.
        """
        shown = printable(self.path).replace("\n", " ")[:MAX_SHOWN_PATH]
        return (
            f"reported {reported} impact, but the change touches {shown}, which review.high_impact_paths covers as "
            f"{self.entry}; recorded as high"
        )


@dataclass(frozen=True)
class High:
    """The PRs whose latest reviewed commit has a `high` review, and their tickets."""

    prs: AbstractSet[str]
    tickets: AbstractSet[str]


def matched(entries: Iterable[str], changed: Iterable[str]) -> Match | None:
    """The first of `changed`, in order, that one of `entries` covers.

    An entry covers the path it names and everything under it, compared by whole components: `.agents/` and `.agents`
    both cover `.agents/x.md`, and neither `.agentsrc`. There are no globs.

    Returns:
        The path and the entry that covers it, or None when no entry covers any of `changed`.
    """
    bases = [(entry, entry.removesuffix("/")) for entry in entries]
    for path in sorted(changed):
        for entry, base in bases:
            if path == base or path.startswith(f"{base}/"):
                return Match(path, entry)
    return None


def high(conn: sqlite3.Connection, tickets: Collection[str], prs: Collection[str]) -> High:
    """Which of the PRs and tickets named have a `high` review at the latest commit reviewed `done`.

    A ticket's PRs are those its reviews name. Of reviews of one commit in several personas (DESIGN §31), one `high`
    is enough, as the gravest of them stands for all.

    Returns:
        The PRs among `prs`, or reviewed for one of `tickets`, whose latest `done` review's commit has a `high` review,
        and the tickets among `tickets` with such a PR.
    """
    # One lookup per index, ticket and PR, merged here: an OR of the two lets SQLite walk the whole table for the order.
    runs: dict[int, records.ReviewRun] = {}
    for named in (sql.in_("ticket_key", tickets), sql.in_("pr_url", prs)):
        query = (
            sql.select("*")
            .from_("review_runs")
            .where("{}", named)
            .where("revises IS NULL AND status = ?", ReviewRunStatus.DONE)
        )
        runs.update((run.id, run) for run in records.fetch_all(conn, records.ReviewRun, query))
    latest: dict[str, str] = {}
    found_prs: set[str] = set()
    found_tickets: set[str] = set()
    for run in sorted(runs.values(), key=lambda r: r.id, reverse=True):
        if latest.setdefault(run.pr_url, run.sha) != run.sha:
            continue
        stored = result.stored(run.result_json)
        if stored is None or stored.impact != "high":
            continue
        found_prs.add(run.pr_url)
        if run.ticket_key is not None and run.ticket_key in tickets:
            found_tickets.add(run.ticket_key)
    return High(frozenset(found_prs), frozenset(found_tickets))
