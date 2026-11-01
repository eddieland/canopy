"""Helpers the web UI's tests share: a browser of the server, signed in or not (DESIGN §22)."""

import dataclasses
import socket  # noqa: TID251  (a test asks the OS for a free port; canopy itself opens no socket)
from datetime import datetime
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient

from canopy.core.context import Context
from canopy.loop import reread, tick_now, web
from canopy.serve import mock as serve_mock
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.backend import Backend
from canopy.serve.options import ServeOptions
from canopy.serve.schema import Capacity

SECRET = "s3cret-" + "x" * 40
ORIGIN = "http://127.0.0.1:8765"
#: What may run at once under the config a test starts with, which sets no `[capacity]` key.
DEFAULT_CAPACITY = Capacity(workers=2, reviews=1, chores=1)


def at(minutes: int) -> str:
    """A time of the mock journal's, `minutes` after it starts, as the API sends it."""
    return serve_mock.at(minutes).replace(".000Z", "Z")


def free_port() -> int:
    """A port no one is listening on now, for a server a test starts on a port it names."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def client(ui_dir: Path | None, backend: Backend, *, key: str | None = None, **options: object) -> TestClient:
    """A browser of `canopy serve` over `backend`, the mock unless `options` say otherwise, signed in to nothing."""
    opts = ServeOptions.model_validate({"ui_dir": ui_dir, "mock": True, "mock_event_seconds": None, **options})
    sessions = Sessions(key, port=opts.port, base_path=opts.base_path, hosts=opts.hosts)
    return TestClient(create_app(opts, backend, sessions), base_url=ORIGIN)


def signed_in(c: TestClient, *, base: str = "") -> dict[str, str]:
    """Sign `c` in with SECRET; return the headers a write needs."""
    response = c.post(f"{base}/api/session", json={"secret": SECRET})
    assert response.status_code == 200
    token = response.json()["token"]
    assert isinstance(token, str)
    return {"x-canopy-token": token, "origin": ORIGIN}


def signed_in_client(
    ctx: Context,
    reload: reread.Reload | None = None,
    asked: tick_now.TickNow | None = None,
    *,
    every: int | None = None,
    now: datetime | None = None,
) -> tuple[TestClient, dict[str, str]]:
    """A browser signed in to a server over `ctx`'s journal, as the loop builds it, and the headers a write needs.

    `every` is `canopy loop --every`'s minutes, as the loop hands them to the server; `now`, when given, is the
    server's clock, stopped there.
    """
    options = ServeOptions(port=8765)
    sessions = Sessions(SECRET, port=options.port, base_path="", hosts=options.hosts)
    backend = web.backend(ctx, reload or reread.Reload(), asked or tick_now.TickNow(), every)
    if now is not None:
        backend = dataclasses.replace(backend, clock=lambda: now)
    c = TestClient(create_app(options, backend, sessions), base_url=ORIGIN)
    return c, signed_in(c)


def refused(response: httpx2.Response) -> str:
    """The guard that refused a write, and why, as `guard: reason`."""
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    return f"{detail['guard']}: {detail['reason']}"
