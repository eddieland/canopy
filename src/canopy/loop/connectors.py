"""Each tick's run of the connectors (DESIGN §30, §6 step 3): the `tracker` source, then the `vcs` source, each once.

Each source is asked what the journal watches of its kind, and what it read whole replaces what the journal held; a
source that fails, or whose output cannot be recorded, keeps its previous observations, and the tick goes on. Nothing
the overseer reads changes: in M36 the observations are in shadow. The `vcs` run is also §29's reconcile read, so the
drafts it covers are checked after it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from canopy.core import connector_runs, conversation, db, drafts, drafts_manage, observe, review_drafts_manage, sql
from canopy.core.vocab import ConnectorRunStatus, PrState, SourceKind

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.infra import logs


def run(ctx: Context, tick_id: int | None, log: logs.TickAdapter) -> frozenset[str]:
    """Run every source that reads, recording each run, and return the PRs the `vcs` source read whole.

    `tick_id` is the tick running them, or None for the loop's poll between ticks (`poll.run`).

    Returns:
        The PRs the `vcs` run read whole, which the drafts that wait on them are checked against.
    """
    read: frozenset[str] = frozenset()
    for name, source in ctx.config.connect.named().items():
        kind = SourceKind(source.kind)
        request = tracker_request(ctx) if kind is SourceKind.TRACKER else vcs_request(ctx)
        started = db.now()
        try:
            observed = observe.observe(ctx.conn, ctx.config, ctx.runner, source, request, log=log)
        except Exception as e:
            # A bug, or a journal constraint the model let through, must not end the tick (DESIGN §30): what the run
            # was recording rolled back with its transaction, so the source keeps its old rows, as a failed run does.
            log.exception("connector's output not recorded", extra={"source": name})
            why = f"its output was not recorded: {type(e).__name__}: {e}"
            observed = observe.Observed(ConnectorRunStatus.FAILED, started, db.now(), missed=why)
        connector_runs.record(ctx.conn, tick_id, name=name, source=source, request=request, observed=observed)
        counts = {"recorded": observed.recorded, "refused": observed.refused}
        log.info("connector ran", extra={"source": name, "status": observed.status, **counts})
        # Config allows one source of each kind (`Connect._one_per_kind`), so this is the one `vcs` read.
        if kind is SourceKind.VCS:
            read = observed.whole.prs
    return read


def tracker_request(ctx: Context) -> observe.Request:
    """What a `tracker` source is asked: the query, and every ticket the state block lists, with its newest comment.

    The newest is the newest the connector recorded, in `observed_comments`: what the overseer mirrored is apart.

    Returns:
        The request.
    """
    stopped = conversation.stopped(ctx.conn)
    keys = [t.key for t in db.open_tickets(ctx.conn) if t.key not in stopped]
    newest = {
        str(r[0]): str(r[1])
        for r in sql.execute(
            ctx.conn,
            sql.select("ticket, max(commented_at)").from_("observed_comments").group_by("ticket"),
        )
    }
    return observe.Request(
        query=ctx.config.tracker.query,
        tickets=[observe.AskedTicket(key, newest.get(key)) for key in keys],
    )


def vcs_request(ctx: Context) -> observe.Request:
    """What a `vcs` source is asked: the PRs the journal watches, the map's repositories, and the review query.

    A PR is watched while its unit's ticket is not marked done, merged and closed ones included, while a draft waits
    on a read of it (§29), a review's draft among them (§34), and while the reader last saw it open, so no PR's
    observation stays open unread once its ticket is done or forgotten. A unit's PR that is not a PR's URL cannot be
    read, so it is not asked about.

    Returns:
        The request.
    """
    done = {str(r[0]) for r in sql.execute(ctx.conn, sql.select("key").from_("tickets").where("done = 1"))}
    prs = {
        unit.pr_url
        for key, units in db.all_units(ctx.conn).items()
        if key not in done
        for unit in units
        if unit.pr_url is not None and observe.is_pr_url(unit.pr_url)
    }
    # A publish whose process was killed waits on this read like any post of unknown outcome (§34).
    review_drafts_manage.expire_claims(ctx.conn, ctx.config)
    seen_open = sql.select("url").from_("observed_prs").where("state = ?", PrState.OPEN)
    prs.update(
        drafts.unchecked_prs(ctx.conn),
        drafts_manage.unsettled_prs(ctx.conn),
        review_drafts_manage.unsettled_prs(ctx.conn),
        (str(r[0]) for r in sql.execute(ctx.conn, seen_open)),
    )
    query = ctx.config.review.query.strip()
    return observe.Request(
        prs=sorted(prs),
        repositories=[
            observe.Repository(repo.name, None if repo.url is None else without_credentials(repo.url))
            for repo in ctx.workspace.repos
        ],
        branch_prefix=ctx.config.trust.branch_prefix,
        review_query=query or None,
    )


def without_credentials(url: str) -> str:
    """A clone URL with any user and password in an `http(s)` URL dropped: a connector holds its own credentials.

    Returns:
        The URL, its credentials dropped; any other URL, such as an SSH one, unchanged.
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))
