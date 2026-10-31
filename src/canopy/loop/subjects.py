"""The subjects a tick runs the overseer once for each of (DESIGN §40, ROADMAP M40): in §7's order, and their capacity.

With `loop.overseer_per_subject` on, a tick runs the overseer once for each subject the harness left to it (§37): each
ticket owed a decision, each PR whose review is still the overseer's to start, and the due chores with a `when`
together, last. A ticket's PRs are its own subject's, not subjects of their own. The runs go one at a time in §7's
order, each subject by the first row it holds (`harness_dispatches.Rank`): a review the operator asked for, or a draft's
revision their note asks for, first; then a ticket by its highest row, with what holds no row that dispatches after
`ready`; a PR the review query found among the loop's own reviews; and the chores last.

Each run is told the capacity left to it: the workers free after the harness's dispatches ranked above it and the runs
those before it recorded. Once none is left, a ticket every row of which is new work, `ready` or a `blocked` to stack,
gets the harness's `wait`, naming capacity, and no run (`wait`): a run that cannot start buys nothing. The rest still
run, since their answer may be attention rather than a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, overseer_runs, recorded_runs
from canopy.core.vocab import Decider, Phase, ReviewRunStatus
from canopy.loop import duties, harness_dispatches, phases
from canopy.loop.harness_dispatches import Rank

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from collections.abc import Set as AbstractSet

    from canopy.core.context import Context
    from canopy.loop.state import CapacityState, OverseerState
    from canopy.reviews.view import ReviewedPR
    from canopy.runs.reconcile import Capacity

#: Where a ticket that holds no row that dispatches goes: after every one that does.
UNRANKED = len(Rank)
#: Where the due chores go: after every other subject.
CHORES_RANK = UNRANKED + 1
#: The rows that are new work: a run for one only starts work, so with no worker free it waits (DESIGN §40).
NEW_WORK = frozenset({Phase.READY, Phase.BLOCKED})


@dataclass(frozen=True)
class Subject:
    """What one run of the overseer is given (DESIGN §40): a ticket, a PR to review, or the due chores."""

    #: Its name, as its run records it: a ticket's key, `pr:<url>`, or `overseer_runs.CHORES`.
    name: str
    #: Its place in §7's order, a lower one first.
    rank: int
    #: The ticket, for a ticket's.
    ticket: str | None = None
    #: The PRs it holds: a ticket's units', or the PR's own.
    prs: AbstractSet[str] = frozenset()
    #: Whether every row it holds is new work: with no worker free, the harness waits it and it gets no run.
    new_work: bool = False

    @property
    def chores(self) -> bool:
        """Whether it is the due chores'."""
        return self.name == overseer_runs.CHORES

    @property
    def label(self) -> str:
        """What its run's session title names it by, first: its ticket, its PR's URL, or `chores`."""
        if self.ticket is not None:
            return self.ticket
        return "chores" if self.chores else self.name.removeprefix(overseer_runs.PR_PREFIX)


def listed(ctx: Context, tick_id: int, block: OverseerState, owed: duties.Duties) -> list[Subject]:
    """The subjects tick `tick_id` runs the overseer for, from the state block `block` and what it owes, `owed`.

    Each ticket owed a decision; each PR in `block`'s reviews still to start that no such ticket holds; and the due
    chores with a `when`, if any.

    Returns:
        Them, in the order their runs go.
    """
    derived: dict[str, list[Phase]] = {}
    for d in phases.recorded(ctx.conn, tick_id):
        derived.setdefault(d.ticket_key, []).extend(d.phases)
    listed_prs = {t["key"]: {u["pr_url"] for u in t["units"] if u["pr_url"]} for t in block["tickets"]}
    found: list[Subject] = []
    for key in duties.owed_tickets(ctx.conn, tick_id, owed):
        prs = listed_prs.get(key)
        if prs is None:
            prs = {u.pr_url for u in db.units(ctx.conn, key) if u.pr_url}
        rows = derived.get(key, [])
        found.append(Subject(key, _rank(rows), key, frozenset(prs), new_work=bool(rows) and set(rows) <= NEW_WORK))
    held = {pr for s in found for pr in s.prs}
    found += [
        Subject(f"{overseer_runs.PR_PREFIX}{url}", rank, prs=frozenset({url}))
        for url, rank in _reviews(block).items()
        if url not in held
    ]
    if owed.chores:
        found.append(Subject(overseer_runs.CHORES, CHORES_RANK))
    return sorted(found, key=lambda s: (s.rank, s.name))


def capacity(ctx: Context, tick_id: int, base: Capacity, subject: Subject) -> CapacityState:
    """The capacity left to `subject`'s run in tick `tick_id`, of `base`, what reconcile left (DESIGN §40).

    The workers the runs recorded so far this tick hold are running; those the harness's dispatches ranked above the
    subject hold are not available to it.

    Returns:
        Its `capacity`, as the state block says it.
    """
    held = len(recorded_runs.workers(recorded_runs.of_tick(ctx.conn, tick_id)))
    above = sum(r.rank < subject.rank for r in harness_dispatches.runs(ctx, tick_id))
    running = base.running + held
    return {
        "max_workers": base.max_workers,
        "running": running,
        "available": max(0, base.max_workers - running - above),
    }


def waits(subject: Subject, left: CapacityState) -> bool:
    """Whether `subject` gets the harness's `wait` and no run, with `left` the capacity left to it.

    Returns:
        True for a ticket of new work alone once no worker is free.
    """
    return subject.new_work and left["available"] == 0


def wait(ctx: Context, tick_id: int, subject: Subject, left: CapacityState) -> None:
    """Record the harness's `wait` on `subject`'s ticket in tick `tick_id`, naming the capacity `left` (DESIGN §40)."""
    why = (
        f"capacity: no worker is free for new work ({left['running']} of {left['max_workers']} running or recorded); "
        "it waits for one"
    )
    db.record_decision(ctx.conn, tick_id, subject.ticket, "wait", why, decider=Decider.HARNESS)


def _rank(rows: Iterable[Phase]) -> int:
    """Where a ticket holding `rows` goes in §7's order: by its highest row that dispatches.

    Returns:
        That row's rank, or `UNRANKED` when it holds none.
    """
    return min(
        (harness_dispatches.PHASE_RANKS[p] for p in rows if p in harness_dispatches.PHASE_RANKS),
        default=UNRANKED,
    )


def _reviews(block: OverseerState) -> dict[str, int]:
    """The PRs in `block` whose review is still the overseer's to start, each with its rank (DESIGN §21, §34).

    Each with the operator's open request, and each draft a note asks to revise whose revision is not running, first;
    then each the review query found fresh whose head is not already reviewed, nor under review now.

    Returns:
        Their URLs, each with its rank, in that order.
    """
    reviews = block.get("reviews")
    if reviews is None:
        return {}
    found = dict.fromkeys([r["url"] for r in reviews["requests"]], int(Rank.REQUESTED))
    for wanted in reviews.get("revisions", []):
        latest = wanted["latest"]
        if latest is None or latest["status"] != ReviewRunStatus.RUNNING:
            found.setdefault(wanted["pr"], int(Rank.REQUESTED))
    query = block["observations"].get("review_query")
    if query is None or query["observed"] != "fresh":
        return found
    heads = {p["url"]: p["pr"]["head"] for p in block["observations"].get("review_prs", []) if "pr" in p}
    running = {r["pr"] for r in reviews["running"]}
    reviewed = _reviewed(reviews["prs"])
    for url in query.get("result", []):
        head = heads.get(url)
        if url not in running and (head is None or reviewed.get(url) != head):
            found.setdefault(url, int(Rank.REVIEW))
    return found


def _reviewed(prs: Sequence[ReviewedPR]) -> dict[str, str]:
    """The commit each of `prs` has a `done` review of, none owed by a persona still: one needs no decision (§21).

    Returns:
        By PR, that commit.
    """
    return {
        pr["url"]: pr["latest"]["sha"]
        for pr in prs
        if pr["latest"]["status"] == ReviewRunStatus.DONE and not pr.get("owed")
    }
