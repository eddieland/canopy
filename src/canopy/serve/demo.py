"""The mock server as a public demo, for a host that runs the ASGI app itself (Vercel; `vercel_app.py`).

`create` seeds a journal from fixtures (mock.py) and serves the UI over it, as `python -m canopy.serve --mock` does
without a secret: every visitor is signed in, and their writes change the fixtures, which a new instance seeds afresh.
It serves mock data and nothing else (D122), so it needs neither the listener secret nor a loopback address.

To deploy it, import the repository as a Vercel project: `vercel.json` and `[tool.vercel]` in pyproject.toml set the
rest, and installing canopy from uv.lock builds the UI into its wheel. Set the function's memory to the least Vercel
offers: an open page's event stream keeps an instance up, and the free plan meters memory by the hour.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from canopy.infra.resources import ui_dir
from canopy.serve import mock
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.options import ServeOptions

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

#: How long the demo keeps an event stream open: under the shortest limit Vercel sets on a request, so the stream ends
#: on its own rather than being cut.
STREAM_SECONDS = 60.0
#: The variables naming the demo's public host names: Vercel's own, for this deployment, its branch, and the
#: project's production domain, and `CANOPY_DEMO_HOSTS` for any other domain, comma-separated.
HOST_VARIABLES = ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL", "CANOPY_DEMO_HOSTS")


def create(environ: Mapping[str, str], directory: Path) -> FastAPI:
    """Return the demo's app, over a journal seeded under `directory`, allowing the host names `environ` gives.

    Returns:
        The app, which serves the UI bundled with canopy and the API over the mock journal.
    """
    options = ServeOptions(
        mock=True, public_hosts=public_hosts(environ), ui_dir=ui_dir(), stream_seconds=STREAM_SECONDS
    )
    sessions = Sessions(None, port=options.port, base_path=options.base_path, hosts=options.hosts)
    return create_app(options, mock.seed(directory), sessions)


def public_hosts(environ: Mapping[str, str]) -> frozenset[str]:
    """The host names `environ` names in `HOST_VARIABLES`, lowercased, each without a scheme or a trailing slash.

    Returns:
        Every name given, none if no variable is set.
    """
    names = (name for variable in HOST_VARIABLES for name in environ.get(variable, "").split(","))
    cleaned = (name.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/") for name in names)
    return frozenset(name for name in cleaned if name)
