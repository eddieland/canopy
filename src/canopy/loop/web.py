"""The web UI for `canopy loop` (DESIGN §22, D073): the listener secret checked, the server's backend wired, started.

The server is a feature (`canopy.serve`) and cannot import the loop or `runs`, so this hands it the attention list as
`canopy status` shows it, `runs.halt.end`, which `canopy stop --now` uses, for a stop with `now`, and a way to ask the
loop to read its config again, as SIGHUP does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.infra import logs, resources
from canopy.loop import attention, reread
from canopy.runs import halt
from canopy.serve import secret
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.backend import Backend, Reloading
from canopy.serve.options import ServeOptions
from canopy.serve.server import WebServer

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context


@dataclass(frozen=True)
class Serving:
    """What the loop's header says about the web UI, the server to stop, if one started, and the backend it serves."""

    note: str
    url: str | None = None
    server: WebServer | None = None
    backend: Backend | None = None


def start(ctx: Context, log: logs.TickAdapter, reload: reread.Reload) -> Serving:
    """Start the web UI's server for the loop, or say why it serves nothing. Never raises: the loop goes on.

    The UI's reload asks through `reload`, as SIGHUP does.
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
    served = backend(ctx, reload)
    server = WebServer(create_app(options, served, sessions), options, log)
    server.start()
    url = options.url()
    log.info("web UI served", extra={"url": url})
    built = "" if options.ui_dir is not None else "; the UI is not built into this installation"
    return Serving(f"{url}  sign in with the secret `canopy secret` prints{built}", url, server, served)


def backend(ctx: Context, reload: reread.Reload) -> Backend:
    """The server's view of the loop's journal: its config and workspace, the attention list, `halt.end`, and reload."""

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
    )
