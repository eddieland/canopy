"""`canopy-artifacts`, the local artifact store's command line (DESIGN §38).

`canopy-artifacts serve --store DIR` serves the store in DIR over stdio until stdin closes, as the agent runtime's
MCP config starts it. Its options are the scope a hosted store's token would carry, set by whoever writes that config,
never by a tool's caller. In a run canopy starts, the run's environment names the artifact's workspace, ticket, and
run (`RUN_ORIGIN`), as `--origin` would, so they are canopy's word and not the worker's.

`canopy-artifacts feed --store DIR` is canopy's `artifacts` source (DESIGN §30, §38): given `{"since": SEQ}` on stdin,
it prints each change to a comment or thread after SEQ, a JSON object to a line, oldest first, paging the comment feed,
and last the feed's `end` line, `{"kind": "end", "through": SEQ}`, the cursor the next run reads from. It reads, and
never writes.

Exit codes: 0 served until stdin closed, or the feed read; 2 the options, the request, or the store's directory are not
usable, and nothing was served or printed.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import click

from canopy_artifacts import server
from canopy_artifacts.store import MAX_FEED, Scope, Store, StoreError, agent, open_store

#: A namespace, such as `canopy/operator`, of at most 128 characters.
_NAMESPACE = re.compile(r"(?=.{1,128}\Z)[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
#: An agent's name, such as `implement` or `run-42`.
_AGENT = re.compile(r"[A-Za-z0-9._-]{1,64}")
#: The most changes one run of `feed` prints: a run past them ends its `end` line at the last, and the next run reads
#: on from there, so a store with a long backlog is read in steps that each fit what canopy reads of a source.
MOST = 1000
#: Who a reader is, in its scope: it writes nothing, so no comment is signed with it.
_READER = "feed"
#: The variables canopy sets on each run it starts, and the origin key each names. The agent runtime starts the store's
#: server as a child of the run's agent, with the run's environment, which no call of the agent's can change: so in a
#: run, canopy names the artifact's workspace, ticket, and run, over the caller's pairs and `--origin`'s.
RUN_ORIGIN: Mapping[str, str] = {
    "CANOPY_WORKSPACE": "canopy.workspace",
    "CANOPY_TICKET": "canopy.ticket",
    "CANOPY_RUN_ID": "canopy.run",
}


@click.group("canopy-artifacts", context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """The local artifact store canopy ships: pages workers publish, and the comments on them (DESIGN §38)."""


@main.command()
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
    # The run's pairs over the options': the command line is the same for every run, and the run is this one.
    scope = dataclasses.replace(scope, origin={**scope.origin, **run_origin(os.environ)})
    try:
        store = open_store(directory, scope)
    except StoreError as e:
        click.echo(f"canopy-artifacts: {e}", err=True)
        ctx.exit(2)
    try:
        ctx.exit(server.run_stdio(store))
    finally:
        store.close()


@main.command()
@click.option(
    "--store",
    "directory",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="The store's directory, as `serve` is given it.",
)
@click.option(
    "--namespace",
    default="local",
    show_default=True,
    help="The namespace whose artifacts' changes are read.",
)
@click.option(
    "--origin",
    "origin",
    multiple=True,
    metavar="KEY=VALUE",
    help="Read only the changes to artifacts whose origin holds this pair; repeat for each.",
)
@click.option(
    "--most",
    type=click.IntRange(1, 100_000),
    default=MOST,
    show_default=True,
    help="The most changes one run prints; the next run reads on from its end line.",
)
@click.pass_context
def feed(ctx: click.Context, directory: Path, namespace: str, origin: tuple[str, ...], most: int) -> None:
    """Print the changes after the request's `since`, then the `end` line: canopy's `artifacts` source (DESIGN §30)."""
    since = _since(sys.stdin.read())
    # A reader's scope makes no artifact, so its origin pairs are only the filter.
    scope = _scope(namespace, _READER, origin, read_only=True)
    try:
        store = open_store(directory, scope)
    except StoreError as e:
        click.echo(f"canopy-artifacts: {e}", err=True)
        ctx.exit(2)
    try:
        for line in _changes(store, scope.origin, since, most):
            # Not escaped to ASCII: a body's every character would be six, past what canopy reads of a line.
            click.echo(json.dumps(line, ensure_ascii=False))
    finally:
        store.close()


def run_origin(environ: Mapping[str, str]) -> dict[str, str]:
    """Read the origin pairs of the run canopy started this server in, from the environment the runtime gave it.

    Returns:
        A pair for each variable of `RUN_ORIGIN` that `environ` sets, and sets to more than nothing; none outside a run.
    """
    return {key: environ[name] for name, key in RUN_ORIGIN.items() if environ.get(name)}


def _since(request: str) -> int:
    """Read the cursor a source's request names: `since`, the `through` of the last run, or 0 for the first.

    Returns:
        The cursor.

    Raises:
        click.UsageError: The request is not a JSON object, or its `since` is not a whole number from 0.
    """
    try:
        found: object = json.loads(request or "{}")
    except json.JSONDecodeError as e:
        raise click.UsageError(f"the request on stdin is not JSON: {e}") from e
    if not isinstance(found, dict):
        raise click.UsageError("the request on stdin is not a JSON object")
    since = cast("dict[str, object]", found).get("since", 0)
    if not isinstance(since, int) or isinstance(since, bool) or since < 0:
        raise click.UsageError(f"the request's since is {since!r}, not a whole number from 0")
    return since


def _changes(store: Store, origin: Mapping[str, str], since: int, most: int) -> list[dict[str, object]]:
    """Page the feed from `since` until a page is not full or `most` changes are read, the last `end` line after them.

    Each page's `end` line names the next page's cursor, so no change is missed or read twice across pages.

    Returns:
        The changes, oldest first, and the `end` line of the last page read.
    """
    found: list[dict[str, object]] = []
    while True:
        limit = min(MAX_FEED, most - len(found))
        *changes, end = store.feed(origin, since, limit)
        found.extend(changes)
        through = int(cast("int", end["through"]))
        if len(changes) < limit or len(found) >= most or through == since:
            return [*found, end]
        since = through


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
