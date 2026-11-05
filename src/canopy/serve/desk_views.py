"""The operator's desk as a ticket's page shows it (DESIGN §18): the repositories it could cover, and the desk, if open.

A desk is read from the workspace's `checkouts/` through the backend, as `canopy desk KEY` finds it; the editor's link
opens its workspace file as VS Code's own URL handler does, through the WSL remote when canopy runs inside WSL, where a
`vscode://file` link would name a path the Windows side cannot open.
"""

from __future__ import annotations

import os
import shlex
from typing import TYPE_CHECKING
from urllib.parse import quote

from canopy.core import db
from canopy.serve.schema.desk import DeskSlot, OpenDesk, TicketDesk

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.core.context import Context
    from canopy.runs.checkouts import Desk
    from canopy.serve.backend import Backend

#: The variable WSL sets in every process it starts, naming the distribution: VS Code's remote names it too.
WSL_DISTRO = "WSL_DISTRO_NAME"


def ticket_desk(backend: Backend, ctx: Context, key: str) -> TicketDesk:
    """`key`'s desk as its page shows it: the repositories with its branch, in the map's order, and the desk if open.

    Returns:
        What a desk would cover, and the open desk, or None in its place.
    """
    with_branch = {str(u.repo) for u in db.units(ctx.conn, key) if u.repo and u.branch}
    desk = backend.find_desk(ctx, key)
    return TicketDesk(
        repos=[r.name for r in ctx.workspace.repos if r.name in with_branch],
        open=open_desk(desk, ctx.workspace.root) if desk is not None else None,
    )


def open_desk(desk: Desk, root: Path, environ: Mapping[str, str] | None = None) -> OpenDesk:
    """`desk` as the API sends it: its paths from the workspace `root`, and how to open it in VS Code.

    Returns:
        The desk, its slots in the order it holds them.
    """
    file = desk.workspace_file
    return OpenDesk(
        branch=desk.branch,
        path=_shown(desk.path, root),
        workspace_file=str(file),
        open_command=f"code {shlex.quote(str(file))}",
        editor_url=editor_url(file, environ),
        slots=[DeskSlot(repo=name, path=_shown(slot, root)) for name, slot in desk.slots.items()],
    )


def editor_url(file: Path, environ: Mapping[str, str] | None = None) -> str:
    """A `vscode:` link that opens `file`, through the WSL remote when `environ` (the process's, by default) is WSL's.

    Returns:
        `vscode://file/PATH`, or `vscode://vscode-remote/wsl+DISTRO/PATH` inside WSL.
    """
    env = os.environ if environ is None else environ
    path = quote(str(file))
    distro = env.get(WSL_DISTRO, "")
    if distro:
        return f"vscode://vscode-remote/wsl+{quote(distro, safe='')}{path}"
    return f"vscode://file{path}"


def _shown(path: Path, root: Path) -> str:
    # As `views.shown_path` shows a worktree, from the workspace root when under it; views imports this module.
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
