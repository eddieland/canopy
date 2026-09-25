"""`canopy _run <run_id>`: one worker execution in a leased slot (DESIGN §8).

Sets up the branch, runs `worker_cmd` with a timeout, parses the result line, verifies the branch is pushed, returns the
slot, and closes the `runs` row. The slot is returned on every exit path this process can see: normal, exception, and
SIGTERM, SIGHUP, or SIGINT. SIGKILL cannot be caught; reconcile finds that run's dead pid on the next tick.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType, TracebackType
from typing import TYPE_CHECKING, Annotated, Literal, Self, TextIO

from pydantic import AfterValidator, BaseModel, ConfigDict, StrictStr, ValidationError

from canopy.core import db, definitions, treehouse
from canopy.core.config import render_command
from canopy.infra import logs, procs
from canopy.runs import dispatch

if TYPE_CHECKING:
    from canopy.core.context import Context

MAX_TEXT = 2000
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


@dataclass(frozen=True)
class Outcome:
    """How a run ended: its `runs.status` and the summary stored as `result_json`."""

    status: str
    result: WorkerResult | None
    note: str = ""

    def result_json(self) -> str:
        """Return the summary stored in `runs.result_json`. Never raw output (DESIGN §11)."""
        data: dict[str, object] = self.result.model_dump() if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


def parse_result(stdout: str) -> WorkerResult | None:
    """Parse the last non-empty line of `stdout` as the result contract. None if it is missing or invalid."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return WorkerResult.model_validate_json(lines[-1])
    except ValidationError:
        return None


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
    log.info("run started", extra={**fields, "slot": run["slot_path"], "branch": run["branch"]})

    outcome = Outcome("crashed", None, "the run stopped before the worker finished")
    with _StopOnSignal() as stop:
        try:
            outcome = _work(ctx, run, out, log)
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
            _return_slot(ctx, run, log)
            if outcome.result is not None and outcome.result.pr and _plain_url(outcome.result.pr):
                db.set_pr_url(ctx.conn, str(run["ticket_key"]), outcome.result.pr)
            if not db.finish_run(ctx.conn, run_id, outcome.status, outcome.result_json()):
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

    prompt = dispatch.prompt_file(ctx, int(run["id"])).read_text(encoding="utf-8")
    # Checked on the branch the worker will run on: OpenCode reads the worktree's config too (D044).
    shadowing = definitions.shadowing(slot)
    if shadowing:
        raise _SetupError(definitions.shadowing_message(shadowing))
    argv = render_command(ctx.config.runtime.worker_cmd, prompt, definitions.ensure(ctx.state_dir))
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    log.info("running worker", extra={"run_id": run["id"], "cmd": argv[0], "timeout_minutes": timeout_minutes})
    run_id = int(run["id"])
    result = ctx.runner.run(
        argv,
        cwd=slot,
        timeout=timeout_minutes * 60,
        on_start=lambda pid: db.set_worker_pid(ctx.conn, run_id, pid),
    )
    out.write(f"--- worker stdout ---\n{result.stdout}\n--- worker stderr ---\n{result.stderr}\n")
    out.write(f"--- worker exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()

    parsed = parse_result(result.stdout)
    if result.timed_out:
        status, note = "timeout", f"the worker timed out after {timeout_minutes} minutes"
    elif parsed is None:
        status, note = "unknown", "the worker's last line was not a valid result"
    else:
        status, note = parsed.status, ""

    unpushed = _ensure_pushed(git, branch, start, log)
    if unpushed:
        status, note = "unpushed", unpushed
    return Outcome(status, parsed, note)


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
