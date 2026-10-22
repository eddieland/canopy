"""The development server: the web UI on loopback over a journal seeded from fixtures, and the UI's OpenAPI schema.

Its command line is `python -m canopy.serve` (canopy.cli.devserver). Each seeds its journal (mock.py) in a temporary
directory, removed when it ends. Not the operator's: `canopy loop` serves the operator's own journal (DESIGN §22).
"""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn

from canopy.serve import mock, secret
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions

if TYPE_CHECKING:
    from fastapi import FastAPI

    from canopy.serve.options import ServeOptions


def serve(options: ServeOptions, secret_file: Path | None) -> None:
    """Serve as `options` say until interrupted, signing in with the listener secret in `secret_file`, or nobody."""
    with _app(options, secret_file) as app:
        uvicorn.run(app, host=options.host, port=options.port, log_level="info")


def openapi(options: ServeOptions) -> Mapping[str, Any]:
    """The API's OpenAPI schema, as the server `options` describe serves it.

    Returns:
        The schema, which the UI's types are generated from (`npm run gen:api` in ui/).
    """
    with _app(options, None) as app:
        return app.openapi()


@contextlib.contextmanager
def _app(options: ServeOptions, secret_file: Path | None) -> Iterator[FastAPI]:
    key = secret.read(secret_file) if secret_file is not None else None
    sessions = Sessions(key, port=options.port, base_path=options.base_path, hosts=options.hosts)
    with tempfile.TemporaryDirectory(prefix="canopy-mock-") as directory:
        yield create_app(options, mock.seed(Path(directory)), sessions)
