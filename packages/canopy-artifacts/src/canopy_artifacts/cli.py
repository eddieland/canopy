"""`canopy-artifacts`, the local artifact store's command line (DESIGN §38).

`canopy-artifacts serve --store DIR` serves the store in DIR over stdio until stdin closes, as the agent runtime's
MCP config starts it. Its options are the scope a hosted store's token would carry, set by whoever writes that config,
never by a tool's caller.

Exit codes: 0 served until stdin closed; 2 the options or the store's directory are not usable, and nothing was served.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from pathlib import Path

import click

from canopy_artifacts import server
from canopy_artifacts.store import Scope, StoreError, agent, open_store

#: A namespace, such as `canopy/operator`, of at most 128 characters.
_NAMESPACE = re.compile(r"(?=.{1,128}\Z)[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
#: An agent's name, such as `implement` or `run-42`.
_AGENT = re.compile(r"[A-Za-z0-9._-]{1,64}")


def main() -> int:
    """The `canopy-artifacts` command.

    Returns:
        The exit code.
    """
    return run(sys.argv[1:])


def run(argv: Sequence[str]) -> int:
    """Run `canopy-artifacts` with `argv`.

    Returns:
        The exit code.
    """
    try:
        found = command.main(args=list(argv), prog_name="canopy-artifacts", standalone_mode=False)
    except click.ClickException as e:
        e.show()
        return e.exit_code
    return found if isinstance(found, int) else 0


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def command() -> None:
    """The local artifact store canopy ships: pages workers publish, and the comments on them (DESIGN §38)."""


@command.command()
@click.option(
    "--store",
    "directory",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="The store's directory, made if it is not there; it must be yours alone. canopy's state directory in use.",
)
@click.option(
    "--namespace",
    default="local",
    show_default=True,
    help="The namespace artifacts are made in, and the only one read or written.",
)
@click.option(
    "--agent",
    "agent_name",
    default="agent",
    show_default=True,
    help="The name every comment written here is signed with: an agent's, on the operator's behalf.",
)
@click.option(
    "--origin",
    "origin",
    multiple=True,
    metavar="KEY=VALUE",
    help="An origin pair set on every artifact made here, over the caller's; repeat for each.",
)
@click.option("--read-only", is_flag=True, help="Refuse every write.")
@click.pass_context
def serve(
    ctx: click.Context,
    directory: Path,
    namespace: str,
    agent_name: str,
    origin: tuple[str, ...],
    *,
    read_only: bool,
) -> None:
    """Serve the store's tools over MCP on stdin and stdout, until stdin closes. Opens no socket."""
    scope = _scope(namespace, agent_name, origin, read_only=read_only)
    try:
        store = open_store(directory, scope)
    except StoreError as e:
        click.echo(f"canopy-artifacts: {e}", err=True)
        ctx.exit(2)
    try:
        ctx.exit(server.run_stdio(store))
    finally:
        store.close()


def _scope(namespace: str, agent_name: str, origin: tuple[str, ...], *, read_only: bool) -> Scope:
    """Read the scope the options name.

    Returns:
        The scope.

    Raises:
        click.BadParameter: The namespace, the agent's name, or an origin pair is not one.
    """
    if not _NAMESPACE.fullmatch(namespace):
        raise click.BadParameter(f"{namespace!r} is not a namespace, such as canopy/operator", param_hint="--namespace")
    if not _AGENT.fullmatch(agent_name):
        raise click.BadParameter(f"{agent_name!r} is not an agent's name, such as implement", param_hint="--agent")
    pairs: dict[str, str] = {}
    for given in origin:
        key, sep, value = given.partition("=")
        if not sep or not key:
            raise click.BadParameter(f"{given!r} is not KEY=VALUE", param_hint="--origin")
        pairs[key] = value
    return Scope(namespace, agent(agent_name), pairs, read_only=read_only)
