"""The web UI for `canopy loop` (DESIGN §22, D073): the listener secret checked, the server's backend wired, started.

The server is a feature (`canopy.serve`) and cannot import the loop or `runs`, so this hands it the attention list as
`canopy status` shows it and `runs.halt.end`, which `canopy stop --now` uses, for a stop with `now`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.infra import logs, resources
from canopy.loop import attention
from canopy.runs import halt
from canopy.serve import secret
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.backend import Backend
from canopy.serve.options import ServeOptions
from canopy.serve.server import WebServer

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context


@dataclass(frozen=True)
class Serving:
    """What the loop's header says about the web UI, and the server to stop, if one started."""

    note: str
    url: str | None = None
    server: WebServer | None = None


def start(ctx: Context, log: logs.TickAdapter) -> Serving:
    """Start the web UI's server for the loop, or say why it serves nothing. Never raises: the loop goes on."""
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
    server = WebServer(create_app(options, backend(ctx), sessions), options, log)
    server.start()
    url = options.url()
    log.info("web UI served", extra={"url": url})
    built = "" if options.ui_dir is not None else "; the UI is not built into this installation"
    return Serving(f"{url}  sign in with the secret `canopy secret` prints{built}", url, server)


def backend(ctx: Context) -> Backend:
    """The server's view of the loop's journal: its config and workspace, the attention list, and `halt.end`."""

    def end_run(run_ctx: Context, run: sqlite3.Row) -> bool:
        return halt.end(run_ctx, run, logs.for_tick(None))

    return Backend(
        config=ctx.config,
        repo_root=ctx.repo_root,
        workspace=ctx.ws,
        attention=attention.listed,
        end_run=end_run,
    )
