"""`canopy memory`: what workers recorded of what they learn, and the operator's lessons (DESIGN §28).

The listing commands say each tier's mode in words first, so recorded memory is never taken for memory in use, and
print what a worker wrote as plain text with every character that hides text named. The commands that write refuse
inside canopy's own ticks and runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, Group, open_context
from canopy.cli.params import REPO, TICKET_KEY
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
    """Delete one memory's text, a note's, a proposal's, or a lesson's. Its row stays, without the text.

    Forgetting a lesson retires it: no run reads it again.
    """
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


@memory_group.command("proposals")
@click.pass_context
def cmd_proposals(click_ctx: click.Context) -> int:
    """List the lessons workers proposed that wait on you, each with where it came from."""
    ctx = open_context(click_ctx)
    _print_modes(ctx)
    waiting = memory.pending_proposals(ctx.conn)
    if not waiting:
        click.echo("\nNo proposals wait on you.")
    for p in waiting:
        click.echo(f"\n{_provenance(ctx, p)}\n      {visible(p.body or '')}")
        if p.run_id is not None and _private(ctx, p.run_id):
            click.echo(
                "      Warning: from a private ticket's run: its text may hold what you kept off the tracker. Promote "
                "it only in words fit for every worker."
            )
    if waiting:
        click.echo(
            f"\nPromote one with `canopy memory promote ID [--text TEXT]`, or `canopy memory reject ID`. Nobody "
            f"reviewing one lets it expire {memory.PROPOSAL_DAYS} days after it was written."
        )
    return 0


@memory_group.command("lessons")
@click.option("--repo", type=REPO, help="Only the lessons a run in this repository is served: its own and every one's.")
@click.option("--digest", is_flag=True, help="Print the lessons a run would get, as its prompt would carry them.")
@click.pass_context
def cmd_lessons(click_ctx: click.Context, repo: str | None, *, digest: bool) -> int:
    """List the lessons you promoted, each with its review date, its use, and any run's report that it is wrong."""
    ctx = open_context(click_ctx)
    _print_modes(ctx)
    if digest:
        found = memory.lessons_digest(ctx.conn, None if repo is None else (repo,), cite=False)
        label = "served to every run" if ctx.config.memory.proposals is MemoryMode.USE else "would be served at use"
        click.echo(f"\nThe lessons{f' for {repo}' if repo else ''}, {label}:\n\n{found.text}")
        return 0
    lessons = [m for m in memory.active_lessons(ctx.conn) if repo is None or m.repo in (None, repo)]
    if not lessons:
        click.echo("\nNo lessons.")
    for m in lessons:
        where = f" for {m.repo}" if m.repo else ""
        wrong = f"; run {m.wrong_run_id} reported it wrong at {m.wrong_at}" if m.wrong_at is not None else ""
        click.echo(
            f"\n  {m.id}  `{m.key}`{where}; promoted at {m.approved_at} from proposal {m.promoted_from}; review at "
            f"{m.review_at}; {_use(m)}{wrong}\n      {visible(m.body or '')}"
        )
    return 0


@memory_group.command("promote")
@click.argument("proposal_id", metavar="ID", type=int)
@click.option("--text", help="The lesson in your words, in place of the proposal's own.")
@click.pass_context
def cmd_promote(click_ctx: click.Context, proposal_id: int, text: str | None) -> int:
    """Make a proposal a lesson in your name, which every run reads while memory.proposals is use."""
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        promoted = manage.promote(ctx.conn, ctx.config, proposal_id, text=text)
    except conversation.Refused as r:
        raise CliError(f"promote refused ({r.guard}): {r.reason}") from None
    lesson = promoted.lesson
    logs.for_tick(None).info("lesson promoted", extra={"proposal": proposal_id, "lesson": lesson.id})
    click.echo(f"Proposal {proposal_id} is lesson {lesson.id} (`{lesson.key}`), due for review at {lesson.review_at}.")
    if promoted.superseded is not None:
        click.echo(f"It replaces lesson {promoted.superseded}, which was under the same key.")
    if promoted.served:
        click.echo("Every run dispatched from now on reads it.")
    else:
        click.echo("It is recorded, not served: memory.proposals is record, so no run reads it until it is use.")
    return 0


@memory_group.command("reject")
@click.argument("proposal_id", metavar="ID", type=int)
@click.pass_context
def cmd_reject(click_ctx: click.Context, proposal_id: int) -> int:
    """End a proposal: no lesson is made of it."""
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        manage.reject(ctx.conn, ctx.config, proposal_id)
    except conversation.Refused as r:
        raise CliError(f"reject refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("proposal rejected", extra={"proposal": proposal_id})
    click.echo(f"Proposal {proposal_id} is rejected.")
    return 0


@memory_group.command("renew")
@click.argument("lesson_id", metavar="ID", type=int)
@click.pass_context
def cmd_renew(click_ctx: click.Context, lesson_id: int) -> int:
    """Keep a lesson: it comes up for review again later, and a run's report that it is wrong is cleared."""
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        due = manage.renew(ctx.conn, ctx.config, lesson_id)
    except conversation.Refused as r:
        raise CliError(f"renew refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info("lesson renewed", extra={"lesson": lesson_id})
    click.echo(f"Lesson {lesson_id} is renewed: due for review at {due}.")
    return 0


def _provenance(ctx: Context, p: records.Memory) -> str:
    run = db.get_run(ctx.conn, p.run_id) if p.run_id is not None else None
    ticket = db.get_ticket(ctx.conn, p.ticket_key) if p.ticket_key is not None else None
    how = f"run {p.run_id} ({run['kind']}, {run['status']})" if run is not None else "a run"
    private = ", private" if run is not None and run["private"] else ""
    merged = "its ticket marked done" if ticket is not None and ticket.done else "its ticket not yet done"
    where = f" for {p.repo}" if p.repo else ""
    return f"  {p.id}  `{p.key}`{where}; from {p.ticket_key}{private}, {how}, {merged}; at {p.created_at}"


def _private(ctx: Context, run_id: int) -> bool:
    run = db.get_run(ctx.conn, run_id)
    return run is not None and bool(run["private"])


def _print_modes(ctx: Context) -> None:
    settings = ctx.config.memory
    if not settings.on:
        click.echo(
            "Memory is off: memory.ticket_notes and memory.proposals are both off, so no worker writes memory and no "
            "run reads it."
        )
        return
    # Each band starts with its mode in words, which no two modes share.
    click.echo(f"{memory.NOTES_TIER}: {memory.notes_band(settings.ticket_notes)}")
    click.echo(f"{memory.LESSONS_TIER}: {memory.lessons_band(settings.proposals)}")


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
