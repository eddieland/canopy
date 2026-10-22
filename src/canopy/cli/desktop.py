"""`canopy-notify-desktop`, the desktop sink's command line (DESIGN §20). What it shows, and how: canopy.notify.desktop.

Exit codes: 0 shown; 1 the notifier could not run or failed; 2 the command line is not usable, the message is empty,
or no notifier is installed.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

import click

from canopy.infra import procs
from canopy.notify import desktop


def main() -> int:
    """The `canopy-notify-desktop` command.

    Returns:
        The exit code, as `run` returns it.
    """
    return run(sys.argv[1:], sys.stdin, runner=procs.SubprocessRunner(), platform=sys.platform)


def run(argv: Sequence[str], stdin: TextIO, *, runner: procs.Runner, platform: str) -> int:
    """Run `canopy-notify-desktop` with `argv`: show the message on `stdin` through `runner`, as on `platform`.

    Returns:
        The exit code, as the module says.
    """
    try:
        found = command.main(
            args=list(argv),
            prog_name="canopy-notify-desktop",
            standalone_mode=False,
            obj=_Io(stdin, runner, platform),
        )
    except click.ClickException as e:
        e.show()
        return e.exit_code
    return found if isinstance(found, int) else 0


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def command(ctx: click.Context) -> None:
    """Show the canopy message on stdin as a desktop notification: canopy's desktop sink (DESIGN §20)."""
    io = ctx.find_object(_Io) or _Io(sys.stdin, procs.SubprocessRunner(), sys.platform)
    ctx.exit(desktop.show(io.stdin.read(), runner=io.runner, platform=io.platform))


@dataclass(frozen=True)
class _Io:
    """What the sink reads, and how it runs the notifier: the real ones, unless a test gives its own."""

    stdin: TextIO
    runner: procs.Runner
    #: `sys.platform`'s value: `darwin` runs `osascript`, any other `notify-send`.
    platform: str
