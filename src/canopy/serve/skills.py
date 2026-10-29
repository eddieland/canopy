"""The skills page (DESIGN §13): every skill the runtime finds, where its file is, and which of canopy's agents get it.

The runtime is asked as `canopy agents` asks it, in the workspace root with canopy's definitions, so the list is the
merge the runtime itself makes, the operator's own skills among it, not a reading of the directories it looks in. A
repository's own skills load in the runs started in its worktrees, and are not asked about here. Each read starts the
runtime for every agent, so it is made when the page asks, never by the event stream. A skill's text is the
repository's or the operator's, so the UI renders it as text, like everything from the journal.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import reports
from canopy.serve.schema.skill import AgentUnread, Skill, SkillList, SkillSource

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.runtime.agents import SkillFile
    from canopy.serve.backend import Backend


def listed(backend: Backend, ctx: Context) -> SkillList:
    """Every skill the runtime finds, by name, each with its file and the agents offered it and denied it.

    Returns:
        The skills, and the agents whose rules could not be read; only `error` when the runtime could not list them,
        or canopy's definitions could not be written for it to read.
    """
    try:
        found = backend.offerings(ctx)
    except reports.Refused as e:
        return SkillList(error=str(e))
    if found.error is not None:
        return SkillList(error=found.error)
    read = [a for a in found.agents if a.error is None]
    return SkillList(
        skills=[
            _skill(
                f,
                ctx,
                offered=[a.agent for a in read if f.name in a.skills],
                denied=[a.agent for a in read if f.name in a.denied_skills],
            )
            for f in found.skill_files
        ],
        unread=[AgentUnread(agent=a.agent, error=a.error) for a in found.agents if a.error is not None],
    )


def _skill(found: SkillFile, ctx: Context, *, offered: list[str], denied: list[str]) -> Skill:
    source, path = _where(found.path, state_dir=ctx.ws.state_dir, root=ctx.ws.root, home=Path.home())
    return Skill(
        name=found.name,
        description=found.description,
        source=source,
        path=path,
        offered=offered,
        denied=denied,
        body=found.body,
    )


# Where a file the runtime names is, and how the page shows it. A link is followed first: a runtime's snapshot of
# canopy's definitions may link to the operator's own config, whose skills are theirs. The state directory, where the
# snapshot is, is under the workspace root, and the root may be under the home.
def _where(named: str, *, state_dir: Path, root: Path, home: Path) -> tuple[SkillSource, str]:
    # A runtime's mark, such as `<built-in>`, is no path.
    if not Path(named).is_absolute():
        return "built-in", named
    path = Path(named).resolve()
    workspace = root.resolve()
    if path.is_relative_to(workspace):
        shown = str(path.relative_to(workspace))
        return ("canopy" if path.is_relative_to(state_dir.resolve()) else "workspace"), shown
    if path.is_relative_to(own := home.resolve()):
        return "home", f"~/{path.relative_to(own)}"
    return "other", named
