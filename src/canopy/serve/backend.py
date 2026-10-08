"""What the server reads and writes through, handed to it by whoever runs it (DESIGN §22).

`serve` is a feature: it cannot import `loop` or `runs`. The attention list (`loop.attention.listed`) and ending a
stopped ticket's run (`runs.halt.end`, as `canopy stop --now` does) are theirs, so `canopy loop` passes them in, and
`python -m canopy.serve --mock` passes stand-ins over its seeded journal.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core.context import Context, db_path
from canopy.infra import procs

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.config import Config
    from canopy.core.items import Item
    from canopy.core.workspace import Workspace


@dataclass(frozen=True)
class Backend:
    """The loop's config and workspace, its journal, and the two functions the server borrows from the loop."""

    config: Config
    repo_root: Path
    workspace: Workspace | None
    # The attention list as `canopy status` shows it.
    attention: Callable[[Context], list[Item]]
    # End a running run as `canopy stop --now` does; False if it had already ended.
    end_run: Callable[[Context, sqlite3.Row], bool]
    # Fixture data, shown as `mock` in the UI's header.
    mock: bool = False

    @contextmanager
    def open(self) -> Iterator[Context]:
        """A Context on a journal connection of its own, closed when the block ends. One per request or stream."""
        conn = db.connect(db_path(self.config))
        try:
            yield Context(
                config=self.config,
                repo_root=self.repo_root,
                conn=conn,
                runner=procs.SubprocessRunner(),
                ws=self.workspace,
            )
        finally:
            conn.close()
