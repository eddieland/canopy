"""The skills page (DESIGN §13): every skill the runtime finds where canopy's agents start, and where its file is.

The runtime is asked as `canopy agents` asks it, in the workspace root with canopy's definitions, so the list is what
the runtime itself finds, the operator's own skills among it, not a reading of the directories it looks in. It is
asked for the skills alone, not which agent is offered each, which would start it again for every agent. A
repository's own skills load in the runs started in its worktrees, and are not asked about here. A read starts the
runtime, so it is made when the page asks, never by the event stream. A skill's text is the repository's or the
operator's, so the UI renders it as text, like everything from the journal.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from canopy.serve.schema.skill import Skill, SkillList, SkillSource

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.runtime.agents import SkillFile
    from canopy.serve.backend import Backend


def listed(backend: Backend, ctx: Context) -> SkillList:
    """Every skill the runtime finds, by name, each with where its file is and its text.

    Returns:
        The skills; only `error` when the runtime could not list them, or canopy's definitions could not be written
        for it to read.
    """
    found = backend.skills(ctx)
    if found.error is not None:
        return SkillList(error=found.error)
    return SkillList(skills=[_skill(f, ctx) for f in found.files])


def _skill(found: SkillFile, ctx: Context) -> Skill:
    source, path = _where(found.path, state_dir=ctx.ws.state_dir, root=ctx.ws.root, home=Path.home())
    return Skill(name=found.name, description=found.description, source=source, path=path, body=found.body)


# Where a file the runtime names is, and how the page shows it. A link is followed first: a runtime's snapshot of
# canopy's definitions may link to the operator's own config, whose skills are theirs. The state directory, where the
# snapshot is, is under the workspace root, and the root may be under the home.
def _where(named: str, *, state_dir: Path, root: Path, home: Path) -> tuple[SkillSource, str]:
    # A skill the runtime names no file for is not one it carries: only its own mark, such as `<built-in>`, says so.
    if not named:
        return "other", named
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
