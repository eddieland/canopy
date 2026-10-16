"""Serve mock data for development and tests, or print the OpenAPI schema.

`python -m canopy.serve --mock [--port N] [--base-path /x] [--secret-file F]` serves the UI on loopback, over a journal
seeded from fixtures in a temporary directory (mock.py), until interrupted. Without `--secret-file` it signs nobody in.
`python -m canopy.serve openapi` prints the schema the UI's types are generated from (`npm run gen:api` in ui/).
Not an operator command: `canopy loop` serves the operator's own journal (DESIGN §22).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from canopy.infra.resources import ui_dir
from canopy.serve import mock, secret
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.options import ServeOptions


def main(argv: Sequence[str] | None = None) -> None:
    """Parse `argv` and serve, or print the schema."""
    parser = argparse.ArgumentParser(prog="python -m canopy.serve", description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=("serve", "openapi"), default="serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--base-path", default="")
    parser.add_argument("--mock", action="store_true", help="serve a journal seeded from fixtures (required)")
    parser.add_argument("--mock-event-seconds", type=float, default=3.0, help="0 changes nothing, for screenshots")
    parser.add_argument("--secret-file", type=Path, help="sign in with the listener secret in this file")
    parser.add_argument("--ui-dir", type=Path, help="the built UI (default: the bundled one, or ui/dist)")
    args = parser.parse_args(argv)
    if args.command == "serve" and not args.mock:
        parser.error("only --mock is served from here; `canopy loop` serves the operator's journal")
    seconds = float(args.mock_event_seconds)
    options = ServeOptions(
        host=str(args.host),
        port=int(args.port),
        base_path=str(args.base_path),
        mock=True,
        mock_event_seconds=seconds or None,
        ui_dir=args.ui_dir if isinstance(args.ui_dir, Path) else ui_dir(),
    )
    if not options.loopback:
        parser.error("mock data is served on loopback only")
    key = secret.read(args.secret_file) if isinstance(args.secret_file, Path) else None
    sessions = Sessions(key, port=options.port, base_path=options.base_path, hosts=options.hosts)
    with tempfile.TemporaryDirectory(prefix="canopy-mock-") as directory:
        app = create_app(options, mock.seed(Path(directory)), sessions)
        if args.command == "openapi":
            sys.stdout.write(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
            return
        uvicorn.run(app, host=options.host, port=options.port, log_level="info")


if __name__ == "__main__":
    main()
