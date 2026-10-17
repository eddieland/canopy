"""`canopy memory`: what workers recorded of what they learn, and the operator's lessons (DESIGN §28).

The listing commands say each tier's mode in words first, so recorded memory is never taken for memory in use, and
print what a worker wrote as plain text with every character that hides text named. The commands that write refuse
inside canopy's own ticks and runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, Group, open_context
from canopy.cli.params import TICKET_KEY
from canopy.core import conversation, db, memory, records
from canopy.core.memory_text import visible
from canopy.core.vocab import MemoryMode
from canopy.infra import logs
from canopy.memory import manage

if TYPE_CHECKING:
    from canopy.core.context import Context


@click.group("memory", cls=Group)
def memory_group() -> None:
    """Read and manage agent memory: ticket notes, proposals, and lessons, while `[memory]` turns them on."""


@memory_group.command("list")
@click.argument("key", type=TICKET_KEY, required=False)
@click.option("--all", "every", is_flag=True, help="Also list superseded and invalid notes, and tombstones.")
@click.option("--run", "run_id", type=int, help="List what this run wrote and read, and what it had refused.")
@click.option(
    "--digest", is_flag=True, help="Print the notes KEY's next run would get, as its prompt would carry them."
)
@click.pass_context
def cmd_list(click_ctx: click.Context, key: str | None, *, every: bool, run_id: int | None, digest: bool) -> int:
    """List the ticket notes workers recorded, of KEY or of every ticket, after each tier's mode in words."""
    if digest and key is None:
        raise click.UsageError("--digest prints one ticket's digest: name its KEY")
    ctx = open_context(click_ctx)
    _print_modes(ctx)
    if run_id is not None:
        _print_run(ctx, run_id)
        return 0
    if digest and key is not None:
        _print_digest(ctx, key)
        return 0
    found = memory.notes(ctx.conn, key, every=every)
    if not found:
        click.echo(f"\nNo notes{f' for {key}' if key else ''}.")
    shown: str | None = None
    for note in found:
        if note.ticket_key != shown:
            shown = note.ticket_key
            click.echo(f"\n{shown}:")
        click.echo(_line(note))
    return 0


@memory_group.command("forget")
@click.argument("memory_id", metavar="ID", type=int)
@click.pass_context
def cmd_forget(click_ctx: click.Context, memory_id: int) -> int:
    """Delete one memory's text, a note's, a proposal's, or a lesson's. Its row stays, without the text."""
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        found, scrubbed = manage.forget(ctx.conn, memory_id)
    except conversation.Refused as r:
        raise CliError(f"forget refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("memory forgotten", extra={"memory": memory_id, "scope": found.scope})
    click.echo(f"Memory {memory_id} ({found.scope} `{found.key}`) is forgotten: its text is deleted.")
    _print_checkpoint(scrubbed)
    return 0


@memory_group.command("purge")
@click.option("--ticket", "key", type=TICKET_KEY, help="Every note and proposal this ticket's runs wrote.")
@click.option("--run", "run_id", type=int, help="Every note and proposal this run wrote.")
@click.option("--all", "every", is_flag=True, help="Every memory, the lessons you promoted included.")
@click.pass_context
def cmd_purge(click_ctx: click.Context, key: str | None, run_id: int | None, *, every: bool) -> int:
    """Delete the text of many memories at once. Their rows stay, without the text."""
    if sum((key is not None, run_id is not None, every)) != 1:
        raise click.UsageError("name what to purge: one of --ticket, --run, or --all")
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        scrubbed = manage.purge(ctx.conn, ticket=key, run=run_id, every=every)
    except conversation.Refused as r:
        raise CliError(f"purge refused ({r.guard}): {r.reason}") from None
    what = f"ticket {key}'s runs" if key is not None else f"run {run_id}" if run_id is not None else "every memory"
    logs.for_tick(None).info("memory purged", extra={"ticket": key, "run_id": run_id, "count": scrubbed.count})
    click.echo(
        f"Purged {scrubbed.count} memor{'y' if scrubbed.count == 1 else 'ies'} of {what}: their text is deleted."
    )
    _print_checkpoint(scrubbed)
    return 0


def _print_modes(ctx: Context) -> None:
    settings = ctx.config.memory
    if not settings.on:
        click.echo(
            "Memory is off: memory.ticket_notes and memory.proposals are both off, so no worker writes memory and no "
            "run reads it."
        )
        return
    click.echo(
        f"{memory.NOTES_TIER}: {memory.mode_words(settings.ticket_notes)}. {memory.notes_band(settings.ticket_notes)}"
    )
    click.echo(f"{memory.LESSONS_TIER}: {memory.mode_words(settings.proposals)}.")


def _line(note: records.Memory) -> str:
    by = f"run {note.run_id}" if note.run_id is not None else "the operator"
    status = note.status if note.why is None else f"{note.status}, {note.why}"
    text = visible(note.body) if note.body is not None else "(text deleted)"
    return f"  {note.id}  `{note.key}`  {status}; by {by} at {note.created_at}; {_use(note)}\n      {text}"


def _use(entry: records.Memory) -> str:
    if entry.use_count == 0:
        return "read by no run"
    runs = f"{entry.use_count} run{'s' if entry.use_count != 1 else ''}"
    return f"used by {runs}, last at {entry.last_used_at}"


def _print_digest(ctx: Context, key: str) -> None:
    mode = ctx.config.memory.ticket_notes
    digest = memory.ticket_digest(ctx.conn, key)
    label = "served to its next run" if mode is MemoryMode.USE else "would be served at use"
    click.echo(f"\n{key}'s notes, {label}:\n")
    click.echo(digest.text.rstrip())


def _print_run(ctx: Context, run_id: int) -> None:
    run = db.get_run(ctx.conn, run_id)
    if run is None:
        raise CliError(f"no run {run_id}")
    rendered = memory.run_memory(ctx.conn, run_id)
    if rendered is None:
        click.echo(f"\nRun {run_id} was rendered with memory off: it wrote and read nothing.")
        return
    click.echo(f"\nRun {run_id} ({run['kind']} of {run['ticket_key']}), rendered with {_rendered(rendered)}.")
    wrote = memory.written_by(ctx.conn, run_id)
    click.echo("Wrote:" if wrote else "Wrote: none")
    for entry in wrote:
        click.echo(_line(entry))
    read = memory.read_by(ctx.conn, run_id)
    if read:
        click.echo("Read:")
        for entry in read:
            click.echo(_line(entry))
    else:
        # A run rendered with no tier at use read nothing because nothing was served, not because nothing was there.
        served = MemoryMode.USE in (rendered.ticket_notes, rendered.proposals)
        click.echo("Read: none" if served else "Read: none, recording only")
    refused = memory.refused_of(rendered)
    if refused:
        click.echo("Refused:")
    for r in refused:
        key = f" `{r.key}`" if r.key else ""
        click.echo(f"  {r.field}{key}: {r.why}")


def _rendered(rendered: records.RunMemory) -> str:
    return (
        f"{memory.NOTES_TIER} {memory.mode_words(rendered.ticket_notes)}, "
        f"{memory.LESSONS_TIER} {memory.mode_words(rendered.proposals)}"
    )


def _print_checkpoint(scrubbed: manage.Scrubbed) -> None:
    if not scrubbed.checkpointed:
        click.echo(
            "A reader held the journal's write-ahead log open, so the deleted text may stay in the log until SQLite's "
            "next checkpoint."
        )
