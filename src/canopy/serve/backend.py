"""What the server reads and writes through, handed to it by whoever runs it (DESIGN §22).

`serve` is a feature: it cannot import `loop`, `runs`, `reviews`, or `chores`. The attention list
(`loop.attention.listed`), ending a stopped ticket's or task's run (`runs.halt.end`, `runs.task_run.stop_now`, as
`canopy stop --now` does), asking the loop to read its config again (`loop.reread`, as SIGHUP does) or for a tick now
(`loop.tick_now`, as `t` does), the attempt
and review limits `canopy grant` raises (`runs.policy`, `reviews.grants`), and trying a chore (`chores.trial`) are
theirs, so `canopy loop` passes them in, and `python -m canopy.serve --mock` passes stand-ins over its seeded journal.
Reading a pool is the pool's own `status` unless told otherwise, and the models and the skills the runtime lists its
own answers: the mock has no pool or runtime to ask. The server keeps the model list it read for a
few minutes (`Backend.model_list`), since each read starts the runtime; a run's dispatch reads its own.

The loop's config and workspace map are read by each request as it opens, and replaced when the loop reads them again
(`use`), so a request runs on one config throughout, the one the loop runs on.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import chore_view, config, conversation, db, definitions, pools, ticket_models
from canopy.core.context import Context, db_path
from canopy.core.vocab import RunStatus
from canopy.infra import procs
from canopy.runs import tasks
from canopy.runtime import definitions as runtime_definitions
from canopy.runtime import models as runtime_models
from canopy.runtime import offerings
from canopy.runtime.agents import Skills
from canopy.serve import host
from canopy.serve.host import Samples
from canopy.serve.processes import ProcessWatch

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.config import Config
    from canopy.core.conversation import Ref
    from canopy.core.items import Item
    from canopy.core.workspace import Workspace
    from canopy.runtime.report import ModelList
    from canopy.serve.schema.host import HostProcesses, HostResources

#: Seconds the server serves a model list the runtime gave before it asks the runtime again: long enough that opening
#: the ticket page's menus one after another starts it once, short enough to see a provider set up meanwhile.
MODEL_LIST_SECONDS = 300.0


def _status(ctx: Context, repo: str) -> Sequence[pools.Slot]:
    return ctx.pool(repo).status()


def _models(ctx: Context) -> ModelList:
    # Read in the workspace root, as a run's model is looked up (DESIGN §13), with the variants a choice may name.
    return runtime_models.listed(ctx.runner, version=ctx.config.runtime.version, cwd=ctx.workspace.root, variants=True)


def _skills(ctx: Context) -> Skills:
    # Asked as `canopy agents` asks, in the workspace root with canopy's definitions, but for the skills alone: no
    # agent's rules, which on OpenCode 1 cost a start of the runtime each.
    try:
        snapshot = definitions.ensure(ctx.ws.state_dir, ctx.config)
    except definitions.DefinitionsError as e:
        return Skills(error=f"skills: {e}")
    return offerings.skills(
        ctx.runner,
        version=ctx.config.runtime.version,
        cwd=ctx.ws.root,
        definitions_dir=snapshot,
        agents=runtime_definitions.agent_names(),
    )


def _close_task_run(ctx: Context, run: records.TaskRun) -> bool:
    # The mock's, which has no process to kill and no pool to return a slot to: it closes the run's row alone.
    note = json.dumps({"harness": "the operator stopped the task (mock: no process was killed)"})
    return tasks.close_run(ctx.conn, ctx.config, run.id, RunStatus.STOPPED, note, head=None)


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

    # `implement` or `resume` for a unit's; `review` for a PR's.
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
    end_run: Callable[[Context, records.Run], bool]
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
    # `canopy chore try NAME`, recorded, its run going on in a process of its own: the new chore run's id. Raises
    # Refused: `running` while a run of the chore is running, `not_started` when it could not start.
    try_chore: Callable[[Context, str], int]
    # Fixture data, shown as `mock` in the UI's header.
    mock: bool = False
    # A repository's pool's slots, for the worktrees page: its `status`. Called on a thread per pool, each with a
    # Context of its own from `open`.
    slots: Callable[[Context, str], Sequence[pools.Slot]] = field(default=_status)
    # The models the runtime lists to run an agent on, and each one's variants, for a ticket's model menus to
    # choose from and for a choice of one to be looked up in: what `canopy models` prints.
    models: Callable[[Context], ModelList] = field(default=_models)
    #: Every skill the runtime finds where canopy's agents start, each with its file and text, for the skills page:
    #: one ask of the runtime. The mock's are made up, as it has no runtime to ask.
    skills: Callable[[Context], Skills] = field(default=_skills)
    # Now, for windows such as the spend figure's: the mock's is fixed, as its journal's times are.
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    # Rewrite `attention.md` after a write that changes the list without a tick, such as a dismissal. The mock's
    # writes nothing.
    write_attention: Callable[[Context], object] = field(default=lambda _ctx: None)
    # The process runner each Context gets. The mock's answers for canopy's GitHub programs from its own journal, so a
    # draft sent from the mock posts nowhere.
    runner: Callable[[], procs.Runner] = field(default=procs.SubprocessRunner)
    #: End a stopped task's running run as `canopy stop task:N --now` does; False if it had already ended. The loop
    #: passes `runs.task_run.stop_now`; the default, the mock's, closes the run's row and kills nothing.
    end_task_run: Callable[[Context, records.TaskRun], bool] = field(default=_close_task_run)
    # The user config the loop read, under the private file the settings page edits (config_edit.py).
    user_file: Path = field(default_factory=config.user_config_path)
    # `canopy loop --every`'s minutes, which set the pace whatever `loop.interval_minutes` says, or None.
    every: int | None = None
    #: The machine the loop runs on, for the system resources page: read from the operating system. The mock's is a
    #: fixed reading, so its pages show the same machine every time and the demo shows none of its host's.
    host: Callable[[Config, Workspace], HostResources] = field(default=host.read)
    #: The readings of the machine the page's graphs draw, kept in memory across the server's restarts in the loop.
    samples: Samples = field(default_factory=Samples)
    #: Whether the server reads the machine into `samples` while it runs (`host.sampling`). The mock's does not: its
    #: readings are seeded, as fixed as its machine.
    sampling: bool = True
    #: The machine's processes, for the system resources page, each measured against the read before (processes.py).
    #: The mock's are a fixed list, as its machine is.
    processes: Callable[[], HostProcesses] = field(default_factory=lambda: ProcessWatch().read)
    #: Seconds on a clock that only moves forward, for how long a model list read from the runtime is served.
    monotonic: Callable[[], float] = field(default=time.monotonic)
    # Held while `config` and `workspace` are read or replaced, so a request never gets one of each.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)
    #: Held while the model list is looked up or read, so requests that find none kept start one runtime, not one each.
    _models_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)
    #: The model list last read, with what it was read on and when; None before the first and after one that failed.
    _listed: _Listed | None = field(default=None, init=False, repr=False, compare=False)
    # When chores' findings started, as the last read found them, handed to every Context opened, so a request or a
    # stream reads back only to there rather than through the whole history of a finding open for months.
    _finding_starts: chore_view.FindingStarts = field(
        default_factory=chore_view.FindingStarts,
        init=False,
        repr=False,
        compare=False,
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
                runner=self.runner(),
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

    def read_host(self) -> HostResources:
        """The machine the loop runs on, read now on the config and workspace served now.

        Returns:
            What `host` reads.
        """
        with self._lock:
            cfg, ws = self.config, self.workspace
        return self.host(cfg, ws)

    def model_list(self, ctx: Context, *, refresh: bool = False) -> ModelList:
        """The models `models` lists on `ctx`'s config and workspace, read at most MODEL_LIST_SECONDS ago.

        The list is read again on a config or workspace other than the one it was read on, as after the loop reads its
        config again, which may name another runtime version; when `refresh` asks; and after a read that failed, which
        is never kept, so a runtime that failed once is asked again by the next request rather than minutes later.

        Returns:
            The list kept, or the one just read.
        """
        with self._models_lock:
            kept = self._listed
            now = self.monotonic()
            if (
                not refresh
                and kept is not None
                and kept.config is ctx.config
                and kept.workspace is ctx.ws
                and now - kept.at < MODEL_LIST_SECONDS
            ):
                return kept.found
            found = self.models(ctx)
            self._listed = None if found.error is not None else _Listed(ctx.config, ctx.ws, now, found)
            return found

    def model_list_for(self, ctx: Context, model: str | None) -> ModelList:
        """The list the operator's choice of `model` is checked against: the one kept, read again if it lacks `model`.

        A model, or a variant of one, set up since the list was kept is then not refused for minutes; a list that could
        not be read is not read twice, and a model the runtime does not list costs one more read to refuse. It may be
        minutes old: a run checks its model against a list read for it as it starts.

        Returns:
            The list.
        """
        kept = self.model_list(ctx)
        if kept.error is not None or model is None:
            return kept
        try:
            ticket_models.check(model, kept)
        except conversation.Refused:
            return self.model_list(ctx, refresh=True)
        return kept


@dataclass(frozen=True)
class _Listed:
    """A model list the runtime gave, kept by `Backend.model_list`."""

    #: The config it was read on: the one served, until the loop reads its config again.
    config: Config
    #: The workspace it was read in.
    workspace: Workspace
    #: When it was read, by `Backend.monotonic`.
    at: float
    #: What the runtime listed.
    found: ModelList
