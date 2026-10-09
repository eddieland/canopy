"""`canopy chore try`: one run of a chore in the foreground, outside any tick, that records nothing (DESIGN §19).

For writing a chore. It runs the chore's command in its working directory with the prompt a real run would get now,
and returns what the agent printed and what the harness made of it. No guard applies and `max_chores` may be 0: the
operator runs it by hand, as they could run the command. Nothing reaches the journal, so the overseer, the attention
list, and notifications never see it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.chores import execute, start
from canopy.core import agent_output, conversation
from canopy.core import chore_view as view

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.config import Chore
    from canopy.core.context import Context

# What the chore's agent sees as CANOPY_RUN_ID, so the operator's commands refuse inside it (DESIGN §22).
RUN_ID = "chore-try"


class TrialError(Exception):
    """The chore cannot be tried: it is not defined for this workspace, or something before its agent failed."""


@dataclass(frozen=True)
class Prepared:
    """A chore ready to try: its definition, where it runs, and the command with its rendered prompt."""

    name: str
    chore: Chore
    cwd: Path
    argv: list[str]


@dataclass(frozen=True)
class Trial:
    """What a try did: the harness's outcome, what the agent printed (text, session, cost), its stderr and exit code."""

    outcome: execute.Outcome
    output: agent_output.AgentOutput
    stderr: str
    returncode: int


def prepare(ctx: Context, name: str, context: str | None) -> Prepared:
    """Render chore `name`'s prompt as a run starting now would get it, and the command that runs it.

    Raises:
        TrialError: no such chore for this workspace, its prompt cannot be read, or its working directory is unusable.
    """
    chore = view.defined(ctx.config, ctx.workspace).get(name)
    if chore is None:
        raise TrialError(f"no chore named {name!r} is defined for this workspace")
    try:
        body = chore.prompt.read_text(encoding="utf-8").rstrip("\n")
    except OSError as e:
        raise TrialError(f"cannot read {chore.prompt}: {e.strerror}") from e
    state = view.state_of(ctx.conn, name, chore)
    prompt = start.render(body, state, None, context, conversation.chore_notes(ctx.conn, name))
    try:
        cwd, argv = execute.prepare(ctx, name, chore, prompt)
    except execute.SetupError as e:
        raise TrialError(str(e)) from e
    return Prepared(name, chore, cwd, argv)


def run(ctx: Context, prepared: Prepared) -> Trial:
    """Run the prepared chore to the end or its timeout, and read its result as `_chore` would."""
    done = ctx.runner.run(
        prepared.argv,
        cwd=prepared.cwd,
        env={conversation.RUN_ID_ENV: RUN_ID},
        timeout=prepared.chore.timeout_minutes * 60,
    )
    output = agent_output.read(done.stdout)
    return Trial(execute.outcome_of(done, output, prepared.chore), output, done.stderr, done.returncode)
