"""Serve mock data for development and tests, or print the OpenAPI schema.

`python -m canopy.serve --mock [--port N] [--base-path /x] [--secret-file F]` serves the UI on loopback, over a journal
seeded from fixtures in a temporary directory (mock.py), until interrupted. Without `--secret-file` it signs nobody in.
`python -m canopy.serve openapi` prints the schema the UI's types are generated from (`npm run gen:api` in ui/).
Not an operator command: `canopy loop` serves the operator's own journal (DESIGN §22).
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import click
import uvicorn

from canopy.infra.resources import ui_dir
from canopy.serve import mock, secret
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.options import ServeOptions


def main(argv: Sequence[str] | None = None) -> int:
    """Parse `argv`, by default the process's own, and serve, or print the schema.

    Returns:
        The exit code: 0 once served or printed, 2 for a command line it cannot use.
    """
    try:
        found = cli.main(
            args=None if argv is None else list(argv),
            prog_name="python -m canopy.serve",
            standalone_mode=False,
        )
    except click.ClickException as e:
        e.show()
        return e.exit_code
    return found if isinstance(found, int) else 0


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("action", type=click.Choice(["serve", "openapi"]), default="serve", required=False)
@click.option("--host", default="127.0.0.1", show_default=True, help="A loopback address.")
@click.option("--port", type=int, default=8765, show_default=True)
@click.option("--base-path", default="", help="The path prefix to serve under, such as /canopy.")
@click.option("--mock", "seeded", is_flag=True, help="Serve a journal seeded from fixtures (required).")
@click.option(
    "--mock-event-seconds",
    type=float,
    default=3.0,
    show_default=True,
    help="Seconds between the mock journal's changes; 0 changes nothing, for screenshots.",
)
@click.option(
    "--secret-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Sign in with the listener secret in this file.",
)
@click.option(
    "--ui-dir",
    "built",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="The built UI. Default: the bundled one, or ui/dist.",
)
def cli(
    *,
    action: str,
    host: str,
    port: int,
    base_path: str,
    seeded: bool,
    mock_event_seconds: float,
    secret_file: Path | None,
    built: Path | None,
) -> None:
    """Serve mock data for development and tests, or print the OpenAPI schema with `openapi`."""
    options = ServeOptions(
        host=host,
        port=port,
        base_path=base_path,
        mock=True,
        mock_event_seconds=mock_event_seconds or None,
        ui_dir=built or ui_dir(),
    )
    _check(options, serving=action == "serve", seeded=seeded)
    key = secret.read(secret_file) if secret_file is not None else None
    sessions = Sessions(key, port=options.port, base_path=options.base_path, hosts=options.hosts)
    with tempfile.TemporaryDirectory(prefix="canopy-mock-") as directory:
        app = create_app(options, mock.seed(Path(directory)), sessions)
        if action == "openapi":
            click.echo(json.dumps(app.openapi(), indent=2, sort_keys=True))
            return
        uvicorn.run(app, host=options.host, port=options.port, log_level="info")


def _check(options: ServeOptions, *, serving: bool, seeded: bool) -> None:
    """Refuse to serve anything but mock data, and anywhere but loopback.

    Raises:
        UsageError: It is asked to serve without `--mock`, or `options` are not on loopback.
    """
    if serving and not seeded:
        raise click.UsageError("only --mock is served from here; `canopy loop` serves the operator's journal")
    if not options.loopback:
        raise click.UsageError("mock data is served on loopback only")


# Guarded: tests/canopy/test_models.py imports every module of canopy.
if __name__ == "__main__":
    sys.exit(main())
