"""Reading the threads a run's drafts answer (DESIGN §29): once the run closes, and each tick until a read is whole.

A draft for a PR waits `unchecked` until a whole read of that PR says its thread exists. `_run` reads its own PRs as
soon as it has closed the run, its slots already returned, and the tick's reconcile reads every PR a draft still waits
on. A read that fails refuses nothing: the drafts stay unchecked, so an outage delays the replies and never drops them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import drafts, drafts_manage, observe
from canopy.core.vocab import DraftStatus, PrState

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection

    from canopy.core.context import Context
    from canopy.infra import logs


def after_run(ctx: Context, run_id: int, log: logs.TickAdapter) -> None:
    """Read the PRs run `run_id`'s drafts wait on, and check them against what was read."""
    rows = ctx.conn.execute(
        "SELECT DISTINCT pr_url FROM drafts WHERE run_id = ? AND status = ?", (run_id, DraftStatus.UNCHECKED)
    )
    _read_and_check(ctx, [str(r["pr_url"]) for r in rows], log)


def reconcile(ctx: Context, log: logs.TickAdapter) -> None:
    """Read every PR a draft waits on, a send left unconfirmed, or one staged, and settle its drafts (§6 step 3)."""
    _read_and_check(ctx, {*drafts.unchecked_prs(ctx.conn), *drafts_manage.unsettled_prs(ctx.conn)}, log)


def _read_and_check(ctx: Context, prs: Collection[str], log: logs.TickAdapter) -> None:
    if not prs:
        return
    read = observe.read(ctx.conn, ctx.config, ctx.runner, prs, log)
    settled = drafts_manage.settle_by_read(ctx.conn, read.whole)
    if settled:
        log.info("drafts settled", extra={"drafts": {d.id: d.status for d in settled}})
    checked = drafts.check(ctx.conn, read.whole)
    if checked:
        counts = {s: sum(d.status is s for d in checked) for s in (DraftStatus.WAITING, DraftStatus.REFUSED)}
        log.info("drafts checked", extra={"prs": sorted(read.whole), **counts})


# The attention reason drafts waiting on the operator raise (DESIGN §14, §29): the harness's, and the operator's alone.
WAITING_REASON = "drafts_waiting"


@dataclass(frozen=True)
class Item:
    """One `drafts_waiting` item: its ticket, its unit's repository, how many drafts wait, and its detail.

    The repository is None for a ticket's own draft.
    """

    ticket_key: str
    repo: str | None
    count: int
    detail: str


def waiting(conn: sqlite3.Connection) -> list[Item]:
    """Return a `drafts_waiting` item for each unit with a PR's draft unsent, and each ticket with a ticket's.

    A PR's drafts stop waiting once the reader saw the PR merged or closed; they can still be sent. A staged draft
    waits on the operator to submit its review on GitHub. Superseded, refused, dropped, and sent drafts wait on nobody.

    Returns:
        The items, by ticket, then repository, the ticket's own after its units'.
    """
    rows = conn.execute(
        "SELECT d.ticket_key, d.repo, d.pr_url, count(*) AS n, sum(d.status = ?) AS unchecked, "
        "sum(d.status = ?) AS staged "
        "FROM drafts d LEFT JOIN observed_prs p ON p.url = d.pr_url "
        "WHERE d.status IN (?, ?, ?) AND (p.state IS NULL OR p.state = ?) "
        "GROUP BY d.ticket_key, d.repo, d.pr_url "
        "ORDER BY d.ticket_key, d.repo IS NULL, d.repo, d.pr_url",
        (
            DraftStatus.UNCHECKED,
            DraftStatus.STAGED,
            DraftStatus.UNCHECKED,
            DraftStatus.WAITING,
            DraftStatus.STAGED,
            PrState.OPEN,
        ),
    ).fetchall()
    found: list[Item] = []
    for r in rows:
        n, unchecked, staged = int(r["n"]), int(r["unchecked"]), int(r["staged"])
        what = f"{n} drafts wait on you" if n > 1 else "1 draft waits on you"
        if r["pr_url"] is None:
            found.append(Item(str(r["ticket_key"]), None, n, f"{what}, for the ticket"))
            continue
        detail = f"{what}, for {r['pr_url']}"
        if staged:
            detail += f"; {staged} in the review you staged there, for you to submit on GitHub"
        if unchecked:
            detail += f"; its threads could not be read yet, so {unchecked} cannot be sent until they are"
        found.append(Item(str(r["ticket_key"]), str(r["repo"]), n, detail))
    return found
