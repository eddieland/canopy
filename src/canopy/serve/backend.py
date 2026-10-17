"""What the server reads and writes through, handed to it by whoever runs it (DESIGN §22).

`serve` is a feature: it cannot import `loop`, `runs`, or `reviews`. The attention list (`loop.attention.listed`),
ending a stopped ticket's run (`runs.halt.end`, as `canopy stop --now` does), asking the loop to read its config again
(`loop.reread`, as SIGHUP does) or for a tick now (`loop.tick_now`, as `t` does), and the attempt and review limits
`canopy grant` raises (`runs.policy`, `reviews.grants`) are theirs, so `canopy loop` passes them in, and
`python -m canopy.serve --mock` passes stand-ins over its seeded journal. Reading a pool is the pool's own `status`
unless told otherwise: the mock has no pool to ask.

The loop's config and workspace map are read by each request as it opens, and replaced when the loop reads them again
(`use`), so a request runs on one config throughout, the one the loop runs on.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.core import chore_view, db, pools
from canopy.core.context import Context, db_path
from canopy.infra import procs

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Config
    from canopy.core.conversation import Ref
    from canopy.core.items import Item
    from canopy.core.workspace import Workspace


def _status(ctx: Context, repo: str) -> Sequence[pools.Slot]:
    return ctx.pool(repo).status()


@dataclass(frozen=True)
class Reloading:
    """What asking the loop to read its config again found, compared with the config it runs on now."""

    # Keys whose values differ, as `section.key`, and `workspace map` for the workspace file's repositories.
    changed: tuple[str, ...]
    # The changed keys that take effect only when the loop restarts.
    restart: tuple[str, ...]
    # A tick is running: it finishes on the config it started with, and the reload follows.
    after_tick: bool


@dataclass(frozen=True)
class Limit:
    """A limit `canopy grant` raises: a ticket's unit's runs of one kind, or a PR's review runs (DESIGN §22)."""

    # `implement`, `fix-ci`, or `resume` for a unit's; `review` for a PR's.
    kind: str
    # The unit's repository; a PR's, when it is a unit's PR.
    repo: str | None
    # The PR, for a review limit.
    pr_url: str | None
    # Its runs of the kind, however they ended: every one counts (D030).
    runs: int
    # The runs the operator granted it past the policy's limit.
    granted: int
    # The policy's limit plus `granted`.
    limit: int


@dataclass(frozen=True)
class Granted:
    """What a grant of one more run recorded: the unit's repository (none for a PR), its runs, and its limit now."""

    repo: str | None
    runs: int
    limit: int


@dataclass
class Backend:
    """The loop's config and workspace, its journal, and the functions the server borrows from the loop."""

    config: Config
    workspace: Workspace
    # The attention list as `canopy status` shows it.
    attention: Callable[[Context], list[Item]]
    # End a running run as `canopy stop --now` does; False if it had already ended.
    end_run: Callable[[Context, sqlite3.Row], bool]
    # Ask the loop to read its config again, as SIGHUP does. Raises ConfigError, naming the file, when it does not load.
    reload: Callable[[Context], Reloading]
    # Ask the loop for a tick now, as `t` at its terminal does. Returns whether a tick is running, which the one asked
    # for follows.
    tick_now: Callable[[], bool]
    # The ticket's units' attempt limits, each kind of each unit it has had runs in, as `canopy grant` raises them.
    limits: Callable[[Context, str], list[Limit]]
    # The PR's review limit, or None for a PR canopy has never reviewed.
    review_limit: Callable[[Context, str], Limit | None]
    # `canopy grant REF KIND [--repo NAME]` for one more run: a ticket's unit, or with `review` a PR. Raises Refused
    # with the CLI's guards.
    grant: Callable[[Context, Ref, str, str | None], Granted]
    # Fixture data, shown as `mock` in the UI's header.
    mock: bool = False
    # A repository's pool's slots, for the worktrees page: its `status`. Called on a thread per pool, each with a
    # Context of its own from `open`.
    slots: Callable[[Context, str], Sequence[pools.Slot]] = field(default=_status)
    # Now, for windows such as the spend figure's: the mock's is fixed, as its journal's times are.
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    # Rewrite `attention.md` after a write that changes the list without a tick, such as a dismissal. The mock's
    # writes nothing.
    write_attention: Callable[[Context], object] = field(default=lambda _ctx: None)
    # Held while `config` and `workspace` are read or replaced, so a request never gets one of each.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)
    # When chores' findings started, as the last read found them, handed to every Context opened, so a request or a
    # stream reads back only to there rather than through the whole history of a finding open for months.
    _finding_starts: chore_view.FindingStarts = field(
        default_factory=chore_view.FindingStarts, init=False, repr=False, compare=False
    )

    @contextmanager
    def open(self) -> Iterator[Context]:
        """A Context on a journal connection of its own, closed when the block ends. One per request or stream.

        Yields:
            A Context with the config and workspace served when the block started.
        """
        with self._lock:
            cfg, ws = self.config, self.workspace
        conn = db.connect(db_path(ws))
        try:
            yield Context(
                config=cfg,
                conn=conn,
                runner=procs.SubprocessRunner(),
                ws=ws,
                finding_starts=self._finding_starts,
            )
        finally:
            conn.close()

    def current(self, ctx: Context) -> Context:
        """`ctx` on the config and workspace served now, for a stream, which holds one Context while a page is open.

        Returns:
            `ctx` itself unless the loop has read its config again since; then a Context on the same connection with
            the config and workspace it read.
        """
        with self._lock:
            cfg, ws = self.config, self.workspace
        if cfg is ctx.config and ws is ctx.ws:
            return ctx
        return replace(ctx, config=cfg, ws=ws)

    def use(self, config: Config, workspace: Workspace) -> None:
        """Serve `config` and `workspace` from the next request on: the loop read its config again."""
        with self._lock:
            self.config, self.workspace = config, workspace
