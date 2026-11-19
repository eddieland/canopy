"""`canopy instructions check`: whether a run would take an agent's standing instructions, live or proposed (§12).

A file a run refuses refuses every run of its agent, so text is checked before it is saved. The command only reads,
and what it says is `prompts.check_standing`'s, which every run's prompt reads its file through.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import click

from canopy.cli.common import open_context
from canopy.core import prompts, standing

if TYPE_CHECKING:
    from canopy.core.config import StandingAgent
    from canopy.core.prompts import StandingCheck

#: The FILE that reads stdin.
_STDIN: Final = Path("-")


@click.group("instructions")
def instructions_group() -> None:
    """Check an agent's standing instructions. Edit the file itself, or the web UI's page, to change them."""


@instructions_group.command("check")
@click.argument("agent", type=click.Choice(standing.AGENTS))
@click.argument("file", type=click.Path(dir_okay=False, allow_dash=True, path_type=Path), required=False)
@click.option("--text", help="The text to check, in place of FILE.")
@click.option("--json", "as_json", is_flag=True, help="Print what was found as one JSON object instead.")
@click.pass_context
def cmd_check(
    click_ctx: click.Context,
    agent: StandingAgent,
    file: Path | None,
    text: str | None,
    *,
    as_json: bool,
) -> int:
    """Check text as AGENT's standing instructions, as a run of it would read them. Writes nothing.

    The text is FILE's, stdin's when FILE is `-`, or --text's: text you mean to save, checked first. Without any, it is
    the file AGENT's runs read now. A run takes at most 4096 bytes of UTF-8, counted in bytes, not characters, and a
    file it does not take refuses every run of the agent. A character that hides text from a person, such as a
    zero-width or bidi one, is named with its line; a run reads it all the same.

    Exits 1 when a run would refuse the text, 0 when it would read it.
    """
    if file is not None and text is not None:
        raise click.UsageError("give FILE or --text, not both")
    source, data = _source(click_ctx, agent, file, text)
    if isinstance(data, str):
        return _report(agent, source, None, data, as_json=as_json)
    return _report(agent, source, prompts.check_standing(data), None, as_json=as_json)


def _source(
    click_ctx: click.Context,
    agent: StandingAgent,
    file: Path | None,
    text: str | None,
) -> tuple[str, bytes | str]:
    """Read the text to check.

    Returns:
        Where it is from, in words, and its bytes, or as a string why it cannot be read, which refuses a run as well.
    """
    if text is not None:
        # An argument that was not UTF-8 reaches Python with its bytes escaped; this gives them back as they were.
        return "the text given", text.encode("utf-8", "surrogateescape")
    if file == _STDIN:
        return "stdin", sys.stdin.buffer.read()
    if file is None:
        found = open_context(click_ctx).config.paths.instructions_read(agent)
        if found is None:
            return "no file: none is set", b""
        file = found
    try:
        return str(file), file.read_bytes()
    except OSError as e:
        return str(file), f"cannot be read: {e.strerror or e}"


def _report(
    agent: StandingAgent,
    source: str,
    check: StandingCheck | None,
    unread: str | None,
    *,
    as_json: bool,
) -> int:
    """Print what the check found, as lines or as one JSON object.

    Returns:
        The exit code: 1 when a run would refuse the text, or it could not be read.
    """
    refusal = unread if check is None else check.refusal
    hidden = (
        [] if check is None else [f"line {line}: {name}, a character that hides text" for line, name in check.hidden]
    )
    limit = prompts.MAX_STANDING_BYTES
    if as_json:
        found = {
            "agent": agent,
            "source": source,
            "ok": refusal is None,
            "bytes": None if check is None else check.size,
            "max_bytes": limit,
            "bytes_left": None if check is None else limit - check.size,
            "blank": check is not None and check.blank,
            "problems": [r for r in (refusal,) if r is not None],
            "warnings": hidden,
        }
        click.echo(json.dumps(found, indent=2))
        return int(refusal is not None)
    if check is None or check.refusal is not None:
        click.echo(f"{agent} instructions ({source}): refused: {refusal}. Every run of the agent would be refused.")
        if check is not None and check.size > limit:
            click.echo(f"  {check.size} of {limit} bytes: trim {check.size - limit}.")
        return 1
    click.echo(f"{agent} instructions ({source}): ok, {check.size} of {limit} bytes, {limit - check.size} left.")
    if check.blank:
        click.echo("  blank: a run reads no instructions in it.")
    for line in hidden:
        click.echo(f"  warning: {line}; a run reads it all the same.")
    return 0
