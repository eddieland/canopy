"""A review's impact as the harness holds it (DESIGN §21), and what it ranks (§14).

The reviewer judges a change's impact from the PR's text, which its author wrote (TRUST_MODEL T1), so a change to a
high-impact path is `high` whatever the reviewer says: CI's workflows in every repository, and the paths the map lists
for the PR's repository. The harness reads the paths from git, over the range the review's kept diff covers, and raises
the impact, never lowers it. `high` ranks attention only: an item about a PR, or its ticket, whose latest reviewed
commit has a `high` review comes first.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import records, sql
from canopy.core import review_result as result
from canopy.core.vocab import ReviewRunStatus
from canopy.infra.text import printable

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Set as AbstractSet

    from canopy.core.workspace import Repo


#: The paths whose change makes a review of every repository `high`: CI's workflows. A repository's entry in the map
#: adds to them and cannot remove them, so a commit to the shared workspace file cannot take CI off (TRUST_MODEL T7).
ALWAYS = (".github/workflows/",)
#: How much of a matched path a note shows: its name is the PR author's text.
MAX_SHOWN_PATH = 200


@dataclass(frozen=True)
class Match:
    """A path a change touches that a high-impact path covers."""

    #: The path the change touches, as git names it.
    path: str
    #: The high-impact path that covers it, as `paths_for` gives it.
    entry: str

    def note(self, reported: str) -> str:
        """The harness's note on a review it recorded `high` over the reviewer's `reported` impact.

        Returns:
            The note, naming the path on one line, without control characters, and cut to `MAX_SHOWN_PATH`.
        """
        shown = printable(self.path).replace("\n", " ")[:MAX_SHOWN_PATH]
        return (
            f"reported {reported} impact, but the change touches {shown}, which the high-impact path {self.entry} "
            "covers; recorded as high"
        )


@dataclass(frozen=True)
class High:
    """The PRs whose latest reviewed commit has a `high` review, and their tickets."""

    prs: AbstractSet[str]
    tickets: AbstractSet[str]


def paths_for(repo: Repo | None) -> tuple[str, ...]:
    """The high-impact paths of a review of a PR in `repo`: `ALWAYS`, then the repository's own `high_impact_paths`.

    Returns:
        The paths, each once; only `ALWAYS` for a PR in no repository the map lists.
    """
    own = () if repo is None else repo.high_impact_paths
    return (*ALWAYS, *(entry for entry in own if entry not in ALWAYS))


def matched(entries: Iterable[str], changed: Iterable[str]) -> Match | None:
    """The first of `changed`, in order, that one of `entries` covers.

    An entry covers the paths it matches and everything under them, compared by whole components: `.agents/` and
    `.agents` both cover `.agents/x.md`, and neither `.agentsrc`. Within a component `*` matches any run of characters
    and `?` one; a component `**` matches any number of components, none included, so `**/OWNERS` covers `OWNERS` and
    `services/billing/OWNERS`, and `services/*/migrations/` covers `services/billing/migrations/0001.py`.

    Returns:
        The path and the entry that covers it, or None when no entry covers any of `changed`.
    """
    patterns = [(entry, entry.removesuffix("/").split("/")) for entry in entries]
    for path in sorted(changed):
        components = path.split("/")
        for entry, parts in patterns:
            if _covers(parts, components):
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
            records.select(records.ReviewRun)
            .where("{}", named)
            .where("revises IS NULL AND status = ?", ReviewRunStatus.DONE)
        )
        runs.update((run.id, run) for run in query.all(conn))
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


def _covers(parts: Sequence[str], components: Sequence[str]) -> bool:
    # Walks the parts once, keeping every count of components they can have matched so far, so a pattern with many
    # wildcards costs parts times components, never the backtracking of one regular expression over the whole path.
    # Any count left at the end is a prefix the pattern matches, and an entry covers everything under what it matches.
    reached = {0}
    for part in parts:
        if part == "**":
            reached = set(range(min(reached), len(components) + 1))
        else:
            reached = {n + 1 for n in reached if n < len(components) and fnmatch.fnmatchcase(components[n], part)}
        if not reached:
            return False
    return True
