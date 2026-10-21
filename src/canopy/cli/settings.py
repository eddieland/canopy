"""`canopy config show`: the keys a person or an agent tunes, with each one's value, default, and the file that set it.

And `canopy config commands`: the commands canopy starts its agents with, rendered, for the operator alone.

Both read only, but for the definitions snapshot `config commands` writes if it is missing, the one a run would write.
Config is changed in the files, with the operator's editor: no command here writes one (ROADMAP M41).
"""

from __future__ import annotations

import dataclasses
import json
import shlex
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, Group, open_context
from canopy.cli.render import report_json
from canopy.core import agent_commands, config, conversation, definitions, settings

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from canopy.core.agent_commands import Command
    from canopy.core.settings import Setting


@click.group("config", cls=Group)
def config_group() -> None:
    """Read the config canopy runs with. Edit the files themselves to change it."""


@config_group.command("show")
@click.option("--json", "as_json", is_flag=True, help="Print the files and the keys as one JSON object instead.")
@click.pass_context
def cmd_show(click_ctx: click.Context, *, as_json: bool) -> int:
    """Print each number, switch, and choice in the config, each chore's too, with its default and the file that set it.

    A key that holds text, a command, a path, or a table of those is left out: it may name a host or carry a token, and
    an agent may read what this prints. Bounds and choices are the schema's.
    """
    ctx = open_context(click_ctx)
    files = config.config_files(ctx.ws.root)
    found = settings.settings(ctx.config, config.origins(ctx.ws.root, runner=ctx.runner), files)
    if as_json:
        layers = {str(layer): str(path) for layer, path in zip(settings.Layer, files, strict=True)}
        click.echo(report_json({"files": layers, "settings": [dataclasses.asdict(s) for s in found]}))
        return 0
    for line in render(found, files):
        click.echo(line)
    return 0


@config_group.command("commands")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the commands as one JSON object instead, each as its argv.",
)
@click.pass_context
def cmd_commands(click_ctx: click.Context, *, as_json: bool) -> int:
    """Print each command canopy starts its agents with, rendered from your config as a run would render it.

    Each is quoted for a shell, so you can see where one word ends: `<prompt>` stands for the prompt, the title is an
    example, and the definitions directory is the one a run would use. A worker run's prefix and suffix are in place,
    and each chore with a command of its own, and `runtime.setup_cmd`, follow. A command may carry a token, so only you
    read them: it is refused inside one of canopy's own ticks or runs.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"config commands refused ({r.guard}): {r.reason}") from None
    ctx = open_context(click_ctx)
    try:
        snapshot = definitions.ensure(ctx.ws.state_dir, ctx.config)
    except (definitions.DefinitionsError, OSError) as e:
        raise CliError(f"config commands: {e}") from None
    files = config.config_files(ctx.ws.root)
    layers = dict(zip(files, settings.Layer, strict=True))
    origin = config.origins(ctx.ws.root, runner=ctx.runner)
    found = agent_commands.commands(ctx.config, {key: layers[path] for key, path in origin.items()}, snapshot)
    if as_json:
        click.echo(report_json({"definitions_dir": str(snapshot), "commands": [dataclasses.asdict(c) for c in found]}))
        return 0
    for line in render_commands(found):
        click.echo(line)
    return 0


def render(found: list[Setting], files: tuple[Path, Path, Path]) -> list[str]:
    """The settings as `canopy config show` prints them: the files, then a key to a line.

    Returns:
        Its lines, without line ends.
    """
    lines = [
        "Numbers, switches, and choices, each chore's too; text, commands, and paths are left out. Later files win:",
        *(
            f"  {layer} file: {path}{'' if path.exists() else ' (none)'}"
            for layer, path in zip(settings.Layer, files, strict=True)
        ),
        "",
    ]
    width = max((len(s.key) for s in found), default=0)
    lines.extend(f"  {s.key.ljust(width)}  {json.dumps(s.value)}  ({_note(s)})" for s in found)
    return lines


def _note(s: Setting) -> str:
    where = f"{s.set_in} file" if s.set_in is not None else "default"
    if s.required:
        default = "; required"
    elif s.set_in is not None and s.default != s.value:
        default = f"; default {json.dumps(s.default)}"
    else:
        default = ""
    choices = f"; one of {', '.join(s.choices)}" if s.choices else ""
    low = f"; at least {s.minimum}" if s.minimum is not None else ""
    high = f"; at most {s.maximum}" if s.maximum is not None else ""
    return f"{where}{default}{choices}{low}{high}"


def render_commands(found: Sequence[Command]) -> list[str]:
    """The commands as `canopy config commands` prints them: each one's role and keys, then its words on one line.

    Returns:
        Its lines, without line ends.
    """
    lines = [f"Each command as a run starts it, with no shell; {agent_commands.PROMPT} stands for the prompt."]
    for command in found:
        keys = ", ".join(f"{k.key} ({f'{k.set_in} file' if k.set_in is not None else 'default'})" for k in command.keys)
        lines.extend(["", f"{command.role}: {keys}", f"  {shlex.join(command.argv)}"])
    return lines
