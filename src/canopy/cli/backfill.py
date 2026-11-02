"""`canopy backfill`: read GitHub's times for the PRs canopy observed before it kept them, for the reports."""

from __future__ import annotations

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, observe
from canopy.infra import logs

#: How many unread PRs the summary names before it counts the rest.
_NAMED = 5


@click.command("backfill")
@click.option("--dry-run", is_flag=True, help="Say how many PRs a backfill would read, and read none.")
@click.pass_context
def cmd_backfill(click_ctx: click.Context, *, dry_run: bool) -> int:
    """Read GitHub's times for merged and closed PRs observed before canopy kept them.

    The reports time a PR from when it was opened, became ready, was asked for review, and merged, as the `vcs` source
    reads them. A PR merged before canopy kept those times is never read again, so its figures fall back to a proxy.
    This asks the `vcs` source about each such PR once more and fills in only the times it lacks: its reviews, checks,
    and state stay as they were. Running it again asks only about the PRs still without times.

    Raises:
        CliError: it runs inside one of canopy's ticks or runs, or the source could not read a PR.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"backfill refused ({r.guard}): {r.reason}") from None
    ctx = open_context(click_ctx)
    prs = observe.missing_times(ctx.conn)
    if not prs:
        click.echo("Every merged or closed PR canopy observed has GitHub's times; nothing to read.")
        return 0
    if dry_run:
        click.echo(f"{_prs(len(prs))} merged or closed without GitHub's times; a backfill would read them. Read none.")
        return 0
    done = observe.backfill_times(ctx.conn, ctx.config, ctx.runner, prs, log=logs.for_tick(None))
    click.echo(f"Read {_prs(done.asked - len(done.unread))} of {done.asked}; filled in times on {done.filled}.")
    if done.unread:
        more = f" and {len(done.unread) - _NAMED} more" if len(done.unread) > _NAMED else ""
        why = "".join(f"\n  {failure}" for failure in dict.fromkeys(done.failures))
        raise CliError(f"could not read {', '.join(done.unread[:_NAMED])}{more}{why}")
    return 0


def _prs(count: int) -> str:
    return f"{count} PR{'' if count == 1 else 's'}"
