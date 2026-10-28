"""Reading the config again while `canopy loop` runs (DESIGN §6): on SIGHUP, or from the web UI's settings page.

Every `canopy` command the overseer and workers run reads the config files when it starts. The loop's own copy is read
once, at its start: the tick's limits, the pace, and what the web UI serves. A reload replaces that copy. It is asked
for here (`Reload.request`) and applied by the loop between ticks or during the wait, never inside a tick, so each tick
runs on one config from its start to its end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from canopy.core import config, workspace

if TYPE_CHECKING:
    from canopy.core.config import Config
    from canopy.core.context import Context
    from canopy.core.workspace import Workspace

# How a reload names a change to the workspace file's map, its `[workspace]` and `[repos]` tables.
WORKSPACE_MAP: Final = "workspace map"
# Keys whose change takes effect only when the loop restarts: the web UI's listener is started once, with the loop.
RESTART_PREFIX: Final = "serve."


@dataclass
class Reload:
    """Whether the operator asked the loop to read its config again. Set by SIGHUP and by the web UI's thread."""

    requested: bool = False
    # Set by the loop while a tick runs: a reload asked for then waits for the tick to end.
    ticking: bool = False

    def request(self) -> bool:
        """Ask for a reload.

        Returns:
            Whether a tick is running, so that the reload waits for it to end.
        """
        self.requested = True
        return self.ticking


@dataclass(frozen=True)
class Reread:
    """The config and the workspace map as their files say now, and which keys differ from the ones running."""

    config: Config
    ws: Workspace
    changed: tuple[str, ...]

    @property
    def restart(self) -> tuple[str, ...]:
        """The changed keys a reload cannot apply: they take effect when the loop restarts."""
        return tuple(k for k in self.changed if k.startswith(RESTART_PREFIX))


def load(ctx: Context) -> Reread:
    """Read the workspace file and the config files again, as `canopy` commands do, and compare them with `ctx`'s.

    Returns:
        The config and workspace map as their files say now, and the keys that differ from `ctx`'s, with
        `workspace map` among them when the map changed.

    Raises:
        ConfigError: either does not load. The message names the file.
    """
    ws = workspace.load(ctx.repo_root)
    cfg = config.load(ctx.repo_root, runner=ctx.runner)
    changed = config.changed(ctx.config, cfg)
    if ws != ctx.ws:
        changed.append(WORKSPACE_MAP)
    return Reread(cfg, ws, tuple(changed))
