"""Run the server for development and tests, or print its OpenAPI schema.

`python -m canopy.serve [--mock] [--port N] [--base-path /x]` serves the UI on loopback until interrupted.
`python -m canopy.serve openapi` prints the schema the UI's types are generated from (`npm run gen:api` in ui/).
Not an operator command: `canopy loop` will run the server once TRUST_MODEL T8's listener secret exists (ROADMAP M20).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from canopy.infra.resources import ui_dir
from canopy.serve.app import create_app
from canopy.serve.options import ServeOptions


def main(argv: list[str] | None = None) -> None:
    """Parse `argv` and serve, or print the schema."""
    parser = argparse.ArgumentParser(prog="python -m canopy.serve", description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=("serve", "openapi"), default="serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--base-path", default="")
    parser.add_argument("--mock", action="store_true", help="serve fixture data (the only data there is for now)")
    parser.add_argument("--mock-event-seconds", type=float, default=3.0, help="0 sends no mock events")
    parser.add_argument("--ui-dir", type=Path, help="the built UI (default: the bundled one, or ui/dist)")
    args = parser.parse_args(argv)
    seconds = float(args.mock_event_seconds)
    options = ServeOptions(
        host=str(args.host),
        port=int(args.port),
        base_path=str(args.base_path),
        mock=bool(args.mock),
        mock_event_seconds=seconds or None,
        ui_dir=args.ui_dir if isinstance(args.ui_dir, Path) else ui_dir(),
    )
    app = create_app(options)
    if args.command == "openapi":
        sys.stdout.write(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
        return
    uvicorn.run(app, host=options.host, port=options.port, log_level="info")


if __name__ == "__main__":
    main()
