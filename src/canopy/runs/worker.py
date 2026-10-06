"""`canopy _run <run_id>`: one worker execution in a leased slot (DESIGN §8).

Sets up the branch, runs `worker_cmd` with a timeout, parses the result line, verifies the branch is pushed, returns the
slot, and closes the `runs` row. The slot is returned on every exit path this process can see: normal, exception, and
SIGTERM, SIGHUP, or SIGINT. SIGKILL cannot be caught; reconcile finds that run's dead pid on the next tick.

A split run leases no slot and pushes nothing (DESIGN §18). It runs `split_cmd` at the workspace root, and records the
children its result names once they pass `check_children`.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType, TracebackType
from typing import TYPE_CHECKING, Annotated, Literal, Self, TextIO

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, ValidationError

from canopy.core import db, definitions, treehouse
from canopy.core.config import render_command
from canopy.infra import logs, procs
from canopy.runs import dispatch

if TYPE_CHECKING:
    from canopy.core.context import Context

MAX_TEXT = 2000
# A child's key is rendered into the overseer's prompt every tick until its parent is done.
MAX_CHILD_KEY = 100
_GIT_TIMEOUT_SECONDS = 300
# Never let git wait for credentials on a terminal nobody is watching.
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}


class WorkerError(Exception):
    """`_run` cannot start this run at all. Nothing was leased or changed."""


class _SetupError(Exception):
    """A git step before or after the worker failed."""


class Stopped(BaseException):
    """This process got a signal asking it to stop. A BaseException, so only the cleanup code catches it."""

    def __init__(self, signum: int) -> None:
        """Record which signal."""
        super().__init__(f"stopped by signal {signal.Signals(signum).name}")
        self.signum = signum


def _bounded(value: str) -> str:
    return value if len(value) <= MAX_TEXT else value[: MAX_TEXT - 3] + "..."


Text = Annotated[StrictStr, AfterValidator(_bounded)]


class WorkerResult(BaseModel):
    """The worker result contract (DESIGN §8): the last line of the worker's stdout. Untrusted, so bounded."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    status: Literal["done", "blocked", "failed"]
    branch: Text | None = None
    pr: Text | None = None
    summary: Text = ""
    question: Text | None = None


class SplitResult(WorkerResult):
    """A split run's result: the worker contract plus `children`, each created ticket's key and repository.

    A splitter has no label tools, so it cannot ask a question the way a blocked worker does: `blocked` is invalid.
    """

    status: Literal["done", "failed"]
    children: dict[StrictStr, StrictStr] = Field(default_factory=dict[str, str])


@dataclass(frozen=True)
class Outcome:
    """How a run ended: its `runs.status` and the summary stored as `result_json`.

    `children` are the tickets a split run created, validated and ready to record.
    """

    status: str
    result: WorkerResult | None
    note: str = ""
    children: Mapping[str, str] = field(default_factory=dict[str, str])

    def result_json(self) -> str:
        """Return the summary stored in `runs.result_json`. Never raw output (DESIGN §11)."""
        data: dict[str, object] = self.result.model_dump() if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


def parse_result[R: WorkerResult](stdout: str, model: type[R]) -> R | None:
    """Parse the last non-empty line of `stdout` as the result contract. None if it is missing or invalid."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return model.model_validate_json(lines[-1])
    except ValidationError:
        return None


def check_children(conn: sqlite3.Connection, parent: str, result: SplitResult, repos: Sequence[str]) -> str:
    """Return why a split result's `children` cannot be recorded, or "" if they can (DESIGN §18).

    Each child is a valid ticket key, new to the journal, for one of the repositories the split was dispatched with, and
    no repository has two. A `done` split names at least one child.
    """
    if result.status == "done" and not result.children:
        return "a done split names the tickets it created in children"
    named = list(result.children.values())
    twice = sorted({repo for repo in named if named.count(repo) > 1})
    if twice:
        return f"two children are for {twice[0][:MAX_CHILD_KEY]}"
    for key, repo in result.children.items():
        problem = _child_problem(conn, parent, key, repo, repos)
        if problem:
            return problem
    return ""


def _child_problem(conn: sqlite3.Connection, parent: str, key: str, repo: str, repos: Sequence[str]) -> str:
    if len(key) > MAX_CHILD_KEY or db.KEY_RE.fullmatch(key) is None:
        return f"{key[:MAX_CHILD_KEY]!r} is not a ticket key"
    if key == parent:
        return f"{key} is the ticket that was split"
    if repo not in repos:
        return f"{key}'s repository {repo[:MAX_CHILD_KEY]!r} is not one the split was dispatched with"
    recorded = db.split_child(conn, key)
    if recorded is not None:
        return f"{key} is already a child of {recorded['parent_key']}"
    if db.has_runs(conn, key):
        return f"{key} already has runs, so this split did not create it"
    return ""


def execute(ctx: Context, run_id: int, *, out: TextIO) -> Outcome:
    """Do run `run_id` from branch setup to closing its row. Worker output is written to `out`, the run log.

    Raises:
        WorkerError: The run does not exist or is not waiting to start, for example because another `_run` has it.
    """
    run = db.get_run(ctx.conn, run_id)
    if run is None:
        raise WorkerError(f"no run {run_id}")
    if not db.claim_run(ctx.conn, run_id, os.getpid()):
        raise WorkerError(f"run {run_id} is not waiting to start: it is {run['status']} or another process has it")
    log = logs.for_tick(int(run["tick_id"]))
    fields = {"run_id": run_id, "ticket": run["ticket_key"], "kind": run["kind"]}
    log.info("run started", extra={**fields, "slot": run["slot_path"], "branch": run["branch"], "repo": run["repo"]})

    outcome = Outcome("crashed", None, "the run stopped before the worker finished")
    with _StopOnSignal() as stop:
        try:
            outcome = _split(ctx, run, out, log) if run["kind"] == dispatch.SPLIT else _work(ctx, run, out, log)
        except Stopped as e:
            outcome = Outcome("crashed", None, str(e))
        except _SetupError as e:
            outcome = Outcome("crashed", None, str(e))
            log.error("run setup failed", extra={**fields, "error": str(e)})  # noqa: TRY400  (no traceback needed)
        except Exception as e:
            outcome = Outcome("crashed", None, f"{type(e).__name__}: {e}")
            log.exception("run failed", extra=fields)
        finally:
            # From here on a signal is ignored: returning the slot and closing the row must not be interrupted.
            stop.armed = False
            if run["lease_id"] is not None:
                _return_slot(ctx, run, log)
            if outcome.result is not None and outcome.result.pr and _plain_url(outcome.result.pr):
                db.set_pr_url(ctx.conn, str(run["ticket_key"]), outcome.result.pr)
            if not db.finish_run(ctx.conn, run_id, outcome.status, outcome.result_json(), children=outcome.children):
                log.warning("run was already closed; its outcome is not recorded", extra=fields)
            log.info("run finished", extra={**fields, "status": outcome.status})
    return outcome


def _work(ctx: Context, run: sqlite3.Row, out: TextIO, log: logs.TickAdapter) -> Outcome:
    slot = Path(run["slot_path"])
    branch = str(run["branch"])
    base = str(run["base_branch"])
    git = _Git(ctx.runner, slot)

    # --prune: a slot keeps remote-tracking refs from earlier runs, which would hide a branch since deleted on origin.
    git.run("fetch", "--quiet", "--prune", "origin")
    # Checked even when the branch is continued: the worker's prompt targets the PR at the base. A stacked run's base
    # is another ticket's branch, deleted when its PR merged (DESIGN §10).
    if not git.ok("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{base}"):
        raise _SetupError(f"the base branch {base} is not on origin; if it was stacked on, its PR may have merged")
    if git.ok("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"):
        git.run("checkout", "--quiet", "-B", branch, f"refs/remotes/origin/{branch}")
    else:
        git.run("checkout", "--quiet", "--no-track", "-B", branch, f"refs/remotes/origin/{base}")
    start = git.run("rev-parse", f"refs/heads/{branch}")

    # Run on the branch the worker will work on: OpenCode reads the worktree's config too (D044).
    result = _run_agent(ctx, run, template=ctx.config.runtime.worker_cmd, cwd=slot, out=out, log=log)
    parsed = parse_result(result.stdout, WorkerResult)
    status, note = _status(ctx, result, parsed)

    unpushed = _ensure_pushed(git, branch, start, log)
    if unpushed:
        status, note = "unpushed", unpushed
    return Outcome(status, parsed, note)


def _split(ctx: Context, run: sqlite3.Row, out: TextIO, log: logs.TickAdapter) -> Outcome:
    """Run the splitter at the workspace root, where it reads the repositories' clones, and check its children."""
    # The workspace root is where the overseer runs too: its OpenCode config must not define one of canopy's agents.
    result = _run_agent(ctx, run, template=ctx.config.runtime.split_cmd, cwd=ctx.repo_root, out=out, log=log)
    parsed = parse_result(result.stdout, SplitResult)
    status, note = _status(ctx, result, parsed)
    if parsed is None or note:
        return Outcome(status, parsed, note)
    problem = check_children(ctx.conn, str(run["ticket_key"]), parsed, db.run_repos(ctx.conn, int(run["id"])))
    if problem:
        # Nothing is recorded, so no child's repository comes from a result the harness could not check.
        unchecked = parsed.model_copy(update={"children": {}})
        return Outcome("unknown", unchecked, f"the split's children were not recorded: {problem}")
    return Outcome(parsed.status, parsed, children=parsed.children)


def _run_agent(
    ctx: Context, run: sqlite3.Row, *, template: str, cwd: Path, out: TextIO, log: logs.TickAdapter
) -> procs.Result:
    """Run the worker agent from `template` in `cwd` with the run's prompt, writing its output to the run log."""
    prompt = dispatch.prompt_file(ctx, int(run["id"])).read_text(encoding="utf-8")
    # OpenCode reads the config in `cwd` too (D044).
    shadowing = definitions.shadowing(cwd)
    if shadowing:
        raise _SetupError(definitions.shadowing_message(shadowing))
    argv = render_command(template, prompt, definitions.ensure(ctx.state_dir))
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    log.info("running worker", extra={"run_id": run["id"], "cmd": argv[0], "timeout_minutes": timeout_minutes})
    run_id = int(run["id"])
    result = ctx.runner.run(
        argv,
        cwd=cwd,
        timeout=timeout_minutes * 60,
        on_start=lambda pid: db.set_worker_pid(ctx.conn, run_id, pid),
    )
    out.write(f"--- worker stdout ---\n{result.stdout}\n--- worker stderr ---\n{result.stderr}\n")
    out.write(f"--- worker exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    return result


def _status(ctx: Context, result: procs.Result, parsed: WorkerResult | None) -> tuple[str, str]:
    """Return the run's status and the harness note saying why it differs from what the worker reported, if it does."""
    if result.timed_out:
        return "timeout", f"the worker timed out after {ctx.config.runtime.worker_timeout_minutes} minutes"
    if parsed is None:
        return "unknown", "the worker's last line was not a valid result"
    return parsed.status, ""


def _ensure_pushed(git: _Git, branch: str, start: str, log: logs.TickAdapter) -> str:
    """Check the checkpoint invariant: the branch on origin is the branch here. Push once if it is not.

    Returns why the branch is not pushed, or "" if it is, or if the worker committed nothing.
    """
    local = git.run("rev-parse", f"refs/heads/{branch}")
    if _remote_head(git, branch) == local:
        return ""
    if local == start:
        return ""  # nothing new here; whatever is on origin is the worker's doing
    log.warning("worker left commits unpushed; pushing once", extra={"branch": branch})
    pushed = git.result("push", "--quiet", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
    if pushed.ok and _remote_head(git, branch) == local:
        return ""
    detail = (pushed.stderr.strip() or pushed.stdout.strip())[:500]
    return f"commits on {branch} are not on origin; the push failed: {detail}"


def _remote_head(git: _Git, branch: str) -> str:
    listed = git.run("ls-remote", "origin", f"refs/heads/{branch}")
    return listed.split()[0] if listed else ""


def _return_slot(ctx: Context, run: sqlite3.Row, log: logs.TickAdapter) -> None:
    fields = {"run_id": run["id"], "slot": run["slot_path"], "lease_id": run["lease_id"]}
    try:
        outcome = treehouse.return_slot(
            ctx.runner,
            Path(run["slot_path"]),
            lease_id=str(run["lease_id"]),
            lease_holder=str(run["lease_holder"]),
            pool=ctx.workspace.pool(run["repo"]),
        )
    except treehouse.TreehouseError as e:
        # The next tick's reconcile returns a canopy lease with no running run.
        log.error("slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
        return
    if outcome is treehouse.ReturnOutcome.RETURNED:
        log.info("slot returned", extra=fields)
    else:
        log.warning("slot not returned", extra={**fields, "outcome": outcome.value})


def _plain_url(value: str) -> bool:
    return value.startswith("https://") and len(value) <= 500 and not any(c.isspace() for c in value)  # noqa: PLR2004


class _StopOnSignal:
    """While armed, SIGTERM, SIGHUP, and SIGINT raise `Stopped`, so cleanup runs. Disarmed, they are ignored."""

    SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)

    def __init__(self) -> None:
        self.armed = True
        self._previous: dict[signal.Signals, Callable[[int, FrameType | None], object] | int | None] = {}

    def _handle(self, signum: int, frame: FrameType | None) -> None:  # noqa: ARG002
        if self.armed:
            self.armed = False
            raise Stopped(signum)

    def __enter__(self) -> Self:
        for s in self.SIGNALS:
            self._previous[s] = signal.signal(s, self._handle)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        for s, handler in self._previous.items():
            signal.signal(s, handler)


class _Git:
    """git in one slot, through the runner."""

    def __init__(self, runner: procs.Runner, slot: Path) -> None:
        self.runner = runner
        self.slot = slot

    def result(self, *args: str) -> procs.Result:
        try:
            result = self.runner.run(["git", *args], cwd=self.slot, env=_GIT_ENV, timeout=_GIT_TIMEOUT_SECONDS)
        except procs.ProcError as e:
            raise _SetupError(f"git {args[0]}: {e}") from e
        if result.timed_out:
            raise _SetupError(f"git {args[0]} timed out")
        return result

    def ok(self, *args: str) -> bool:
        return self.result(*args).ok

    def run(self, *args: str) -> str:
        result = self.result(*args)
        if not result.ok:
            detail = (result.stderr.strip() or result.stdout.strip())[:500]
            raise _SetupError(f"git {args[0]} exited {result.returncode}: {detail}")
        return result.stdout.strip()
