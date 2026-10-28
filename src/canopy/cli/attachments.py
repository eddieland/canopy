"""`canopy attach` and `canopy detach`: text files on a ticket or a task, for its runs to read (DESIGN §22).

Both write through `canopy.core.attachments`, which refuses inside canopy's own ticks and runs (`inside_run`) and holds
attachments to `policy`'s limits; `canopy show` lists a subject's attachments with `listed`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import click

from canopy.cli.common import CliError, open_context
from canopy.core import attachments, conversation, plans
from canopy.core.items import age
from canopy.infra import logs

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.core.conversation import Ref

CLI: Final = "cli"


@click.command("attach")
@click.argument("ref", metavar="REF")
@click.argument("file", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--name", metavar="NAME", help="What runs see it as. The file's own name, made plain, by default.")
@click.pass_context
def cmd_attach(click_ctx: click.Context, ref: str, file: str, name: str | None) -> int:
    """Attach FILE, a text file such as a design doc, to a ticket or `task:N`, or stdin with `-` and --name.

    Each later run of it gets a copy beside its worktree, outside git, and reads it as data: say what to do with it in
    a reply, or in the task's text. Only UTF-8 text is taken; export a PDF or a document as Markdown or plain text
    first. policy.max_attachments, max_attachment_kib, and max_attachments_total_kib bound what one ticket or task
    holds. `canopy detach` removes one.
    """
    subject = _ref(ref, "attach")
    chosen = name if name is not None else (None if file == "-" else attachments.name_from(file))
    if chosen is None:
        raise click.UsageError("name it with --name: stdin has no name, and nothing of FILE's name is plain")
    ctx = open_context(click_ctx)
    limits = attachments.Limits.from_policy(ctx.config.policy)
    try:
        # One byte past the bound is enough to refuse it, so a large file is never read whole.
        with click.open_file(file, "rb") as f:
            data = f.read(limits.file_bytes + 1)
    except OSError as e:
        raise CliError(f"attach refused: {file} could not be read: {e.strerror}") from None
    try:
        attached = attachments.attach(
            ctx.conn,
            ctx.state_dir,
            subject,
            chosen,
            data,
            limits=limits,
            channel=CLI,
        )
    except conversation.Refused as r:
        raise CliError(f"attach refused ({r.guard}): {r.reason}") from None
    except plans.PlanFileError as e:
        raise CliError(f"attach refused: {e}") from None
    fields = {"subject": str(subject), "attachment": attached.id, "size": attached.size, "channel": CLI}
    logs.for_tick(None).info("operator attached a file", extra=fields)
    click.echo(f"Attached {attached.name} ({attached.size} bytes) to {subject}; its next run reads it.")
    return 0


@click.command("detach")
@click.argument("ref", metavar="REF")
@click.argument("name", metavar="NAME")
@click.pass_context
def cmd_detach(click_ctx: click.Context, ref: str, name: str) -> int:
    """Remove the attachment NAME from a ticket or `task:N`: its file is deleted, and later runs no longer get it.

    A run already working keeps its copy. `canopy show REF` lists the attachments it has.
    """
    subject = _ref(ref, "detach")
    ctx = open_context(click_ctx)
    try:
        removed = attachments.remove(ctx.conn, ctx.state_dir, subject, name, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"detach refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "operator removed an attachment",
        extra={"subject": str(subject), "attachment": removed.id},
    )
    click.echo(f"Removed {removed.name} from {subject}.")
    return 0


def listed(ctx: Context, ref: Ref) -> None:
    """Print the attachments `ref` holds, for `canopy show`: nothing when it has none."""
    found = attachments.of(ctx.conn, ref)
    if not found:
        return
    click.echo(f"\nAttachments ({len(found)}):")
    for a in found:
        click.echo(f"  {a.name}  {a.size} bytes  attached {age(a.added_at)} ago via {a.channel}")


def _ref(text: str, verb: str) -> Ref:
    try:
        conversation.check_operator()
        ref = conversation.parse_ref(text)
        conversation.check_verb(ref, verb)
    except conversation.Refused as r:
        raise CliError(f"{verb} refused ({r.guard}): {r.reason}") from None
    return ref
