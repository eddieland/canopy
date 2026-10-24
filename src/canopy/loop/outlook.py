"""What a tick would record and list, read without recording it, for the loop's poll to compare (DESIGN §39).

After a poll that read every source whole, the loop reads what a tick would now record and list to the overseer, and
ends its wait when that holds something the latest tick left without: a decision of the harness's, or a ticket, a row
of §7 on one, an item past a cursor, or a due chore. Each is a fact named by what it is, never by its text, so a poll
that reads again what the latest tick saw, or an edit to an item it saw, finds nothing new. What drops out, such as a
ticket marked done or a comment a cursor passed, is no news: it leaves nothing to judge.

The latest tick is read the same way, as it ends (`loop.repeat`), so what that tick itself did, such as a dispatch
whose worker the harness then waits on, is no news to the polls after it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import chore_view, conversation, db
from canopy.core.vocab import SourceKind
from canopy.loop import harness, harness_dispatches, observations, phases

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Set as AbstractSet
    from datetime import datetime

    from canopy.core.context import Context

#: One thing a tick would record or list, named by what it is: its kind, then its subject, such as
#: `("comment", "PROJ-1", "10001")` or `("row", "PROJ-1", "api", "ci_red")`.
type Fact = tuple[str, ...]


def read(ctx: Context, now: datetime) -> frozenset[Fact]:
    """Read what a tick would record and list at `now`, from the journal and the observations, recording nothing.

    The harness's decisions and its dispatches to come; each ticket the state block would list to the overseer, with
    the rows of §7 the derivation finds on it and its units, and the comments and review items past their cursors that
    it would show; each due chore; and the review query's PRs, when a source read it fresh.

    Returns:
        The facts.
    """
    derived = phases.derive(ctx, now)
    decisions = harness.decide(ctx, derived)
    runs = harness_dispatches.runs_of(ctx, derived)
    decided = {d.key for d in decisions} | {r.key for r in runs}
    facts: set[Fact] = {("decision", d.key, d.action) for d in decisions}
    facts.update(("dispatch", r.key, r.repo) for r in runs)
    states = chore_view.states(ctx.conn, ctx.config, ctx.workspace)
    facts.update(("chore", c["name"]) for c in chore_view.state_section(states, now) if c["due"] and not c["running"])
    stopped = set(conversation.stopped(ctx.conn))
    tickets = [t for t in db.open_tickets(ctx.conn) if t.key not in stopped and t.key not in decided]
    reader = observations.Reader.read(ctx, derived, now, tickets)
    for key in reader.keys:
        if key not in decided:
            facts.update(_listed(reader.ticket(key)))
    if ctx.config.review.query.strip():
        query = reader.query(SourceKind.VCS)
        if query["observed"] == "fresh":
            facts.update(("review_query", url) for url in query.get("result", []))
    return frozenset(facts)


def news(before: AbstractSet[Fact], now: AbstractSet[Fact]) -> list[Fact]:
    """What `now` holds that `before`, the latest tick's, did not: what ends the loop's wait (DESIGN §39).

    Returns:
        The facts, in order.
    """
    return sorted(now - before)


def _listed(ticket: observations.TicketObservation) -> Iterator[Fact]:
    """The facts of one ticket as the state block would list it: its key, its rows, and its new items.

    Yields:
        Each fact.
    """
    key = ticket["key"]
    yield ("ticket", key)
    yield from (("row", key, "", phase) for phase in ticket.get("derived", []))
    yield from (("comment", key, c["id"]) for c in ticket.get("comments", []))
    for unit in ticket.get("units", []):
        repo = unit["repo"]
        yield from (("row", key, repo, phase) for phase in unit.get("derived", []))
        yield from (("review", key, repo, r["item"], str(r["id"])) for r in unit.get("reviews", []))
