"""The web UI for `canopy loop` (DESIGN §22, D073): the listener secret checked, the server's backend wired, started.

The server is a feature (`canopy.serve`) and cannot import the loop, `runs`, or `reviews`, so this hands it the
attention list as `canopy status` shows it, `runs.halt.end`, which `canopy stop --now` uses, for a stop with `now`, a
way to ask the loop to read its config again, as SIGHUP does, and the attempt and review limits with the grants that
`canopy grant` records (`runs.policy`, `reviews.grants`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.infra import logs, resources
from canopy.loop import attention, reread
from canopy.reviews import grants
from canopy.runs import halt, policy
from canopy.serve import secret
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.backend import Backend, Granted, Limit, Reloading
from canopy.serve.options import ServeOptions
from canopy.serve.server import WebServer

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context
    from canopy.core.conversation import Ref


@dataclass(frozen=True)
class Serving:
    """What the loop's header says about the web UI, the server to stop, if one started, and the backend it serves."""

    note: str
    url: str | None = None
    server: WebServer | None = None
    backend: Backend | None = None


def start(ctx: Context, log: logs.TickAdapter, reload: reread.Reload, every: int | None = None) -> Serving:
    """Start the web UI's server for the loop, or say why it serves nothing. Never raises: the loop goes on.

    The UI's reload asks through `reload`, as SIGHUP does. `every` is `--every`'s minutes, which the settings page
    names beside `loop.interval_minutes`.

    Returns:
        The note for the loop's header, with the URL, server, and backend when the server started.
    """
    cfg = ctx.config.serve
    options = ServeOptions(host=cfg.bind, port=cfg.port, base_path=cfg.base_path, ui_dir=resources.ui_dir())
    try:
        key = secret.read(secret.path())
    except secret.SecretError as e:
        log.warning("web UI not served", extra={"reason": str(e)})
        return Serving(f"not served: {e}")
    except OSError as e:
        log.warning("web UI not served", extra={"reason": str(e)})
        return Serving(f"not served: cannot read the listener secret: {e}")

    sessions = Sessions(key, port=options.port, base_path=options.base_path, hosts=options.hosts)
    served = backend(ctx, reload, every)
    server = WebServer(create_app(options, served, sessions), options, log)
    server.start()
    url = options.url()
    log.info("web UI served", extra={"url": url})
    built = "" if options.ui_dir is not None else "; the UI is not built into this installation"
    return Serving(f"{url}  sign in with the secret `canopy secret` prints{built}", url, server, served)


def backend(ctx: Context, reload: reread.Reload, every: int | None = None) -> Backend:
    """The server's view of the loop's journal: the config, the attention list, `halt.end`, reload, and grants.

    Returns:
        The backend the server calls into, bound to `ctx` and `reload`, editing the user config the loop read.
    """

    def end_run(run_ctx: Context, run: sqlite3.Row) -> bool:
        return halt.end(run_ctx, run, logs.for_tick(None))

    def reload_config(current: Context) -> Reloading:
        # Read here first, so a config that does not load is refused to the operator who asked, not only logged.
        found = reread.load(current)
        return Reloading(changed=found.changed, restart=found.restart, after_tick=reload.request())

    return Backend(
        config=ctx.config,
        workspace=ctx.ws,
        attention=attention.listed,
        end_run=end_run,
        reload=reload_config,
        limits=limits,
        review_limit=review_limit,
        grant=grant,
        write_attention=lambda current: attention.write(current, logs.for_tick(None)),
        every=every,
    )


def limits(ctx: Context, key: str) -> list[Limit]:
    """Each kind's limit of each unit of `key`'s that has had runs, as the state block counts them (DESIGN §8, §22).

    A forgotten ticket's runs still name their repositories, so its units are here though the journal has none.

    Returns:
        Every kind of every unit, by repository, then kind as `policy.KINDS` orders them.
    """
    granted = policy.grants(ctx.conn)
    found: list[Limit] = []
    for (ticket, repo), counts in sorted(policy.attempts(ctx.conn, ticket=key).items(), key=lambda u: str(u[0][1])):
        # A slot with no repository name names no unit `canopy grant` can raise.
        if ticket != key or repo is None:
            continue
        extra = granted.get(policy.unit(key, repo), {})
        most = policy.unit_limits(ctx.config, extra)
        found.extend(Limit(k, repo, None, counts[k], extra.get(k, 0), most[k]) for k in policy.KINDS)
    return found


def review_limit(ctx: Context, url: str) -> Limit | None:
    """The PR's review limit (DESIGN §21), or None for one canopy has never reviewed, which has none to grant past.

    Returns:
        Its review runs, the runs granted it, and its limit, with no repository: the PR's own page names that.
    """
    runs = len(db.review_runs_of(ctx.conn, url))
    if runs == 0:
        return None
    return Limit(grants.KIND, None, url, runs, grants.granted(ctx.conn, url), grants.limit(ctx.conn, ctx.config, url))


def grant(ctx: Context, ref: Ref, kind: str, repo: str | None) -> Granted:
    """`canopy grant` for one more run, with its guards: a PR's reviews with `review`, else a ticket's unit's attempts.

    Returns:
        The unit's repository (none for a PR), its runs, and its limit with the grant counted.
    """
    if kind == grants.KIND:
        reviewed = grants.grant(ctx.conn, ctx.config, ref, runs=1)
        return Granted(repo=None, runs=reviewed.runs, limit=reviewed.limit)
    granted = policy.grant(ctx.conn, ctx.config, ref.id, kind, repo=repo, runs=1)
    return Granted(repo=granted.repo, runs=granted.runs, limit=granted.limit)
