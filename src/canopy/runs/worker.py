"""`canopy _run <run_id>`: one worker execution in its leased slots (DESIGN §8, §18).

Sets up the branch in each slot, runs the operator's `setup_cmd` there, makes the desk of a joint run, runs
`worker_cmd` with a timeout, parses the result line, verifies the branch is pushed in each slot, removes the desk,
returns every slot, and closes the `runs` row. The slots are returned on every exit path this process can see: normal,
exception, and SIGTERM, SIGHUP, or SIGINT. SIGKILL cannot be caught; reconcile finds that run's dead pid on the next
tick.

A split run is the same up to the worker: each slot is checked out at its base, the splitter runs with `split_cmd` in
the desk, and nothing is pushed or verified. Its result names the tickets it created, which are validated and recorded
in `split_children` (DESIGN §18).

A plan run is checked out as a split is, and always works in a desk, even over one repository: the desk holds a copy of
the plan it replaces, if the ticket has one. The planner runs with `plan_cmd` and writes its plan to a file at the
desk's root, the one file it may edit; a `done` one is read from there, bounded, written to the plan's own file, and
recorded `proposed` (DESIGN §25).
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self, TextIO, assert_never

from pydantic import BaseModel, ConfigDict, StrictStr

from canopy.core import (
    agent_output,
    contract,
    conversation,
    db,
    definitions,
    drafts,
    hostgit,
    memory,
    outbox,
    plans,
    pools,
    replies,
    review_diff,
    transcript,
)
from canopy.core.config import render_command, setup_words
from canopy.core.vocab import PoolKind, ReplyMode, RunKind, RunStatus
from canopy.core.workspace import DESKS_DIR
from canopy.infra import logs, procs, stopping
from canopy.runs import desks, dispatch, drafted, policy, tidy

if TYPE_CHECKING:
    from canopy.core.context import Context

MAX_TEXT = 2000
# A child key is a ticket key, and bounded like every other value an agent reports.
MAX_CHILD_KEY = 100
MAX_PR_URL = 500
_GIT_TIMEOUT_SECONDS = 300
# The repository whose slot `setup_cmd` runs in, by its name in the map, and the run's branch, which the slot has
# checked out detached (DESIGN §8).
SETUP_REPO_ENV = "CANOPY_REPO"
SETUP_BRANCH_ENV = "CANOPY_BRANCH"


class WorkerError(Exception):
    """`_run` cannot start this run at all. Nothing was leased or changed."""


class _SetupError(Exception):
    """A git step before or after the worker failed."""


Text = Annotated[StrictStr, contract.bounded(MAX_TEXT)]
PrTitle = Annotated[StrictStr, contract.one_line, contract.bounded(contract.MAX_PR_TITLE)]


class WorkerResult(BaseModel):
    """The worker result contract (DESIGN §8, §18): the last line of the worker's stdout. Untrusted, so bounded.

    `prs` maps each repository's name to its PR, and `pr_titles` to that PR's title, which need not be the ticket's.
    `pr` is the contract before joint runs, still accepted for a run in one repository.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "blocked", "failed"]
    branch: Text | None = None
    pr: Text | None = None
    prs: dict[StrictStr, Text | None] | None = None
    pr_titles: dict[StrictStr, PrTitle | None] | None = None
    summary: Text = ""
    question: Text | None = None

    def for_repos(self, repos: Sequence[str]) -> Self:
        """Return this result with `prs` and `pr_titles` kept to `repos`, the repositories the run worked in.

        `prs` is filled from `pr`; a result old enough to use `pr` carries no titles.
        """
        prs = {r: self.prs.get(r) for r in repos if r in self.prs} if self.prs is not None else None
        if prs is None and self.pr is not None and len(repos) == 1:
            prs = {repos[0]: self.pr}
        titles = self.pr_titles
        if titles is not None:
            titles = {r: titles[r] for r in repos if r in titles}
        return self.model_copy(update={"prs": prs, "pr_titles": titles})


class SplitResult(BaseModel):
    """A split's result contract (DESIGN §18): the tickets it created, each with the repository it covers.

    Untrusted, so bounded; `_run` checks the children against the journal before recording any (`check_children`).
    `children` is bounded by that check, not here: a valid split names one child per repository it was dispatched with,
    and a refused one is stored without its children.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "failed"]
    summary: Text = ""
    children: dict[StrictStr, StrictStr] = {}


class PlanResult(BaseModel):
    """A plan's result contract (DESIGN §25). The plan itself is the file the planner wrote in its desk, not a field.

    Untrusted, so bounded. A `blocked` plan's question is recorded as a worker message, as any run's is (§22).
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "blocked", "failed"]
    summary: Text = ""
    question: Text | None = None


def parse_split(stdout: str) -> SplitResult | None:
    """Parse `stdout`'s result line (DESIGN §13) as a split's result. None if it is missing or invalid.

    Returns:
        The split's result, or None.
    """
    return contract.last_line(SplitResult, stdout)


def check_children(conn: sqlite3.Connection, parent: str, repos: Sequence[str], result: SplitResult) -> str:
    """Return why a split's reported children cannot be recorded, or "" if they can.

    Every key must be a ticket key, new to the journal (never a split's child, never dispatched, never in `tickets`) and
    not the parent, so a steered splitter cannot claim an existing ticket and pin it to a repository. Every repository
    must be one the split was dispatched with, each covered at most once. A `done` split names at least one child.
    """
    if result.status == "done" and not result.children:
        return "a done split must name the tickets it created"
    seen: set[str] = set()
    for key, repo in result.children.items():
        invalid = _check_child(conn, parent, repos, key, repo)
        if invalid:
            return invalid
        if repo in seen:
            return f"two children cover {repo}; a split makes at most one ticket per repository"
        seen.add(repo)
    return ""


def _check_child(conn: sqlite3.Connection, parent: str, repos: Sequence[str], key: str, repo: str) -> str:
    if len(key) > MAX_CHILD_KEY or dispatch.KEY_RE.fullmatch(key) is None:
        return f"child {key[:MAX_CHILD_KEY]!r} is not a ticket key"
    if key == parent:
        return f"child {key} is the ticket that was split"
    if db.split_child(conn, key) is not None or db.has_runs(conn, key) or db.get_ticket(conn, key) is not None:
        return f"child {key} is not a new ticket: the journal already knows it"
    if repo not in repos:
        return f"child {key}'s repository {repo[:MAX_CHILD_KEY]!r} is not one the split was dispatched with"
    return ""


@dataclass(frozen=True)
class Outcome:
    """How a run ended: its `runs.status` and the summary stored as `result_json`."""

    status: RunStatus
    result: WorkerResult | SplitResult | PlanResult | None
    note: str = ""
    # What the worker sent of agent memory, and the commit its branch was at when it ended (DESIGN §28).
    memory: memory.Fields | None = None
    head: str | None = None
    # The comments it drafted in place of posting them (DESIGN §29).
    drafts: drafts.Fields | None = None

    def result_json(self) -> str:
        """Return the summary stored in `runs.result_json`. Never raw output (DESIGN §11)."""
        data: dict[str, object] = self.result.model_dump(mode="json") if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


def parse_result(stdout: str) -> WorkerResult | None:
    """Parse `stdout`'s result line (DESIGN §13) as the result contract. None if it is missing or invalid.

    Returns:
        The worker's result, or None.
    """
    return contract.last_line(WorkerResult, stdout)


def execute(ctx: Context, run_id: int, *, out: TextIO) -> Outcome:
    """Do run `run_id` from branch setup to closing its row. Worker output is written to `out`, the run log.

    Returns:
        How the run ended, as its row was closed with. A setup failure, a signal, or an unexpected error is `crashed`,
        with why in its note.

    Raises:
        WorkerError: The run does not exist or is not waiting to start, for example because another `_run` has it.
    """  # noqa: DOC501  (the _SetupError raised below is caught below, into a crashed outcome)
    run = db.get_run(ctx.conn, run_id)
    if run is None:
        raise WorkerError(f"no run {run_id}")
    if not db.claim_run(ctx.conn, "runs", run_id, os.getpid()):
        raise WorkerError(f"run {run_id} is not waiting to start: it is {run['status']} or another process has it")
    slots = [_Slot.of(ctx, row) for row in db.run_slots(ctx.conn, run_id)]
    for slot in slots:
        # Before any git step: reconcile checks it for a `_run` that dies before putting a changed link back.
        db.set_slot_link(ctx.conn, run_id, slot.repo, slot.link)
    log = logs.for_tick(int(run["tick_id"]))
    fields = {"run_id": run_id, "ticket": run["ticket_key"], "kind": run["kind"]}
    where = {"slots": [str(s.path) for s in slots], "repos": [s.repo for s in slots]}
    log.info("run started", extra={**fields, **where, "branch": run["branch"]})

    outcome = Outcome(RunStatus.CRASHED, None, "the run stopped before the worker finished")
    with stopping.StopOnSignal() as stop:
        try:
            if not slots:
                raise _SetupError(f"run {run_id} has no slots")  # noqa: TRY301  (the same handling as git failures)
            tidy.make_objects(_objects(ctx, run))
            outcome = _doer(RunKind(run["kind"]))(ctx, run, slots, out, log)
        except stopping.Stopped as e:
            outcome = Outcome(RunStatus.CRASHED, None, str(e))
        except (_SetupError, desks.DeskError) as e:
            outcome = Outcome(RunStatus.CRASHED, None, str(e))
            log.error("run setup failed", extra={**fields, "error": str(e)})  # noqa: TRY400  (no traceback needed)
        except Exception as e:
            outcome = Outcome(RunStatus.CRASHED, None, f"{type(e).__name__}: {e}")
            log.exception("run failed", extra=fields)
        finally:
            # From here on a signal is ignored: returning the slots and closing the row must not be interrupted.
            stop.armed = False
            _release(ctx, run, slots, log)
            _record_prs(ctx, run, outcome)
            stored = outcome.result_json()
            remember = functools.partial(_record_reported, ctx, run_id, outcome)
            if not conversation.close_run(ctx.conn, ctx.config, run, outcome.status, stored, then=remember):
                log.warning("run was already closed; its outcome is not recorded", extra=fields)
            procs.drop_lifelock(Path(run["log_path"]))
            log.info("run finished", extra={**fields, "status": outcome.status})
            _check_drafts(ctx, run_id, stop, log)
    return outcome


def _check_drafts(ctx: Context, run_id: int, stop: stopping.StopOnSignal, log: logs.TickAdapter) -> None:
    """Read the PRs the run's drafts answer, after the run is closed: its slots are returned and it holds no capacity.

    A failure here is logged, never raised: the run is closed, and the tick's reconcile reads the PRs again. So a stop
    signal is heard again for the read, which it cuts short, rather than waiting out the reader's timeout.
    """
    try:
        stop.armed = True
        drafted.after_run(ctx, run_id, log)
    except stopping.Stopped:
        log.info("drafts not checked: the run was stopped", extra={"run_id": run_id})
    except Exception:
        log.exception("drafts not checked", extra={"run_id": run_id})
    finally:
        stop.armed = False


def _record_reported(ctx: Context, run_id: int, outcome: Outcome) -> None:
    """Write what the run reported beside its result, in the transaction that closes it: memory (§28), drafts (§29)."""
    memory.record_run(ctx.conn, run_id, outcome.memory, head=outcome.head)
    drafts.record_run(ctx.conn, run_id, outcome.drafts)


type _Doer = Callable[[Context, sqlite3.Row, Sequence[_Slot], TextIO, logs.TickAdapter], Outcome]


def _doer(kind: RunKind) -> _Doer:
    """What does a `kind` run, from checkout to its outcome.

    Returns:
        The function for the kind: a split's, a plan's, or a worker's.
    """
    match kind:
        case RunKind.SPLIT:
            return _split
        case RunKind.PLAN:
            return _plan
        case RunKind.IMPLEMENT | RunKind.FIX_CI | RunKind.RESUME:
            return _work
        case _:
            assert_never(kind)


@dataclass(frozen=True)
class _Slot:
    """One of a run's slots: the repository it is in, the worktree, its lease, git in it, and its `.git` link.

    `link` is what the worktree's `.git` file held when the run started, before any git step, or None if it is not a
    file (DESIGN §8). `pool` is the pool that made the lease, which the slot goes back to (DESIGN §18).
    """

    repo: str
    path: Path
    lease_id: str
    lease_holder: str
    base: str
    git: _Git
    link: bytes | None
    pool: PoolKind

    def rewritten(self) -> Path | None:
        """Return the file that says where the slot's git is, if the worker changed it: the `.git` file, or `commondir`.

        Returns:
            The `.git` file if it no longer holds what it did when the run started, else `commondir` in the slot's own
            git directory if it no longer names the common directory, else None. Always None when `.git` was not a
            file at the start.
        """
        if self.link is None:
            return None
        if hostgit.read_link(self.path) != self.link:
            return self.path / hostgit.LINK
        if hostgit.commondir_moved(self.path, self.link):
            own = hostgit.own_git_dir(self.path, self.link)
            return (own or self.path) / hostgit.COMMONDIR
        return None

    def reading(self, ctx: Context, objects: Path) -> _Slot:
        """The slot, with its git reading the run's object directory as well as the slot's own objects.

        Returns:
            A copy of the slot whose git has the environment that reads `objects` too.

        Raises:
            _SetupError: git could not be set up to read `objects`.
        """
        try:
            env = tidy.reading(ctx.runner, self.path, objects)
        except tidy.GitError as e:
            raise _SetupError(f"{self.git.where}{e}") from e
        return replace(self, git=_Git(ctx.runner, self.path, self.repo, env))

    @classmethod
    def of(cls, ctx: Context, row: sqlite3.Row) -> _Slot:
        repo = str(row["repo"])
        path = Path(row["slot_path"])
        return cls(
            repo,
            path,
            str(row["lease_id"]),
            str(row["lease_holder"]),
            str(row["base_branch"]),
            _Git(ctx.runner, path, repo),
            hostgit.read_link(path),
            PoolKind(row["pool"]),
        )


def session_title(conn: sqlite3.Connection, key: str, kind: str) -> str:
    """A run's session title: `<KEY> <kind>: <the ticket's title>`, or `<KEY> <kind>` before the overseer names it.

    Returns:
        The title.
    """
    ticket = db.get_ticket(conn, key)
    title = ticket.title if ticket is not None else None
    return f"{key} {kind}: {title}" if title else f"{key} {kind}"


def _run_agent(
    ctx: Context,
    run: sqlite3.Row,
    slots: Sequence[_Slot],
    out: TextIO,
    log: logs.TickAdapter,
    *,
    template: str,
    desk_files: Mapping[str, str] | None = None,
) -> tuple[procs.Result, str]:
    """Check the places the agent reads config from, make the run's desk if it has one, and run `template` in it.

    A private run's places, and a plan's, must also name none of the tracker server's tools (DESIGN §22, §25).
    `desk_files` are written into the desk, by name, readable only by the operator, before the agent starts.

    The session and cost the runtime reported are recorded on the run at once, so a git step after the agent that
    fails does not lose them (DESIGN §13).

    Returns:
        The agent's process and the text its result line is read from.

    Raises:
        _SetupError: a place the agent reads config from shadows canopy's definitions, or, for a private run or a
            plan, names one of the tracker server's tools.
    """
    prompt = dispatch.prompt_file(ctx, int(run["id"])).read_text(encoding="utf-8")
    desked = dispatch.in_desk(str(run["kind"]), slots)
    # Checked on the branch the worker will run on: OpenCode reads the worktree's config too (D044). A worker in a desk
    # starts in no repository, so OpenCode may look above it: the directories above it are checked.
    desk_parents = [ctx.workspace.root / DESKS_DIR, ctx.workspace.root] if desked else []
    places = [s.path for s in slots] + desk_parents
    shadowing = [found for place in places for found in definitions.shadowing(place)]
    if shadowing:
        raise _SetupError(definitions.shadowing_message(shadowing))
    tools = ctx.config.tracker.tools()
    if (run["private"] or run["kind"] == policy.PLAN) and tools is not None:
        naming = [found for place in places for found in definitions.naming_tools(place, tools.server)]
        if naming:
            raise _SetupError(definitions.naming_tools_message(tools.server, naming))
    title = session_title(ctx.conn, str(run["ticket_key"]), str(run["kind"]))
    snapshot = definitions.ensure(ctx.state_dir, ctx.config)
    argv = render_command(template, prompt, snapshot, title)
    if desked:
        cwd = desks.make(ctx.workspace.root, str(run["ticket_key"]), [(s.repo, s.path) for s in slots])
        for name, text in (desk_files or {}).items():
            try:
                logs.write_private(cwd / name, text)
            except OSError as e:
                raise _SetupError(f"could not write {name} in the desk {cwd}: {e}") from e
    else:
        cwd = slots[0].path
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    log.info(
        "running worker",
        extra={"run_id": run["id"], "cmd": argv[0], "cwd": str(cwd), "timeout_minutes": timeout_minutes},
    )
    run_id = int(run["id"])
    out.write("--- worker stdout ---\n")
    out.flush()
    result = ctx.runner.run(
        argv,
        cwd=cwd,
        # The operator's commands refuse inside canopy's own runs (DESIGN §22). A sandbox wrapper points git at the
        # object directory; an unsandboxed worker ignores it (DESIGN §8).
        env={conversation.RUN_ID_ENV: str(run_id), tidy.OBJECTS_ENV: str(_objects(ctx, run))},
        timeout=timeout_minutes * 60,
        on_start=lambda pid: db.set_agent_pid(ctx.conn, "runs", run_id, pid),
        on_line=_Progress(ctx, run_id, out, log),
    )
    out.write(f"\n--- worker stderr ---\n{result.stderr}\n")
    out.write(f"--- worker exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    # Also after a timeout: whatever it printed before the kill names its session and what it had spent.
    output = agent_output.read(result.stdout)
    if output.session_id is not None or output.usage is not None:
        db.set_run_report(
            ctx.conn, "runs", run_id, output.session_id, output.usage, digest=snapshot.name, tools=output.tools
        )
        spent = output.usage.spent() if output.usage else {}
        log.info("worker reported", extra={"run_id": run_id, "session_id": output.session_id, **spent})
    return result, output.text


class _Progress:
    """Each line the worker prints, as it prints it: written to the run log, and its events read (DESIGN §8).

    What they say so far is recorded on the run, so a running run shows its session, what it has spent, and its latest
    tool call. A line comes on `_run`'s own thread, so this may use the journal connection. A journal write that fails
    is logged, not raised: raising would kill the worker, and the session and spend are recorded again when it ends.
    """

    def __init__(self, ctx: Context, run_id: int, out: TextIO, log: logs.TickAdapter) -> None:
        self.ctx = ctx
        self.run_id = run_id
        self.out = out
        self.log = log
        self.tally = agent_output.Tally()

    def __call__(self, line: str) -> None:
        self.out.write(line)
        self.out.flush()
        event = agent_output.parse_event(line)
        if event is None:
            return
        seen = self.tally.session_id
        self.tally.add(event)
        session = self.tally.session_id
        if session is None:
            return
        usage = self.tally.usage if event["type"] == "step_finish" else None
        did = transcript.did(event)
        if session == seen and usage is None and did is None:
            return
        try:
            db.set_run_progress(self.ctx.conn, self.run_id, session, usage=usage, did=did)
        except sqlite3.Error as e:
            self.log.warning("worker progress not recorded", extra={"run_id": self.run_id, "error": str(e)})
        if seen is None:
            self.log.info("worker session started", extra={"run_id": self.run_id, "session_id": session})


def _split(ctx: Context, run: sqlite3.Row, slots: Sequence[_Slot], out: TextIO, log: logs.TickAdapter) -> Outcome:
    """Run the splitter in a desk of worktrees at their bases, and record the children it reports if they are valid.

    Returns:
        The splitter's status, `timeout` if it timed out, or `unknown` for a missing or invalid result line. A result
        whose children are refused is kept without them, with why in the note.
    """
    for slot in slots:
        _check_out(slot)
    result, text = _run_agent(ctx, run, slots, out, log, template=ctx.config.runtime.split_cmd)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    parsed = parse_split(text)
    if parsed is None:
        if result.timed_out:
            # Whatever it created is unknown to the journal; its comment on the parent lists it for a human.
            return Outcome(RunStatus.TIMEOUT, None, f"the splitter timed out after {timeout_minutes} minutes")
        return Outcome(RunStatus.UNKNOWN, None, "the splitter's last line was not a valid split result")
    key = str(run["ticket_key"])
    invalid = check_children(ctx.conn, key, [s.repo for s in slots], parsed)
    if invalid:
        log.warning("split result refused; no child recorded", extra={"run_id": run["id"], "reason": invalid})
        status = RunStatus.TIMEOUT if result.timed_out else RunStatus.UNKNOWN
        # Stored without its children: a refused map is unbounded, and its note says what was wrong with it.
        return Outcome(status, parsed.model_copy(update={"children": {}}), f"children not recorded: {invalid}")
    if parsed.children:
        # Also after a timeout: the children it reported exist in the tracker, and a retry must not make them again.
        db.record_split_children(ctx.conn, key, int(run["id"]), parsed.children)
        log.info("split children recorded", extra={"run_id": run["id"], "children": parsed.children})
    if result.timed_out:
        return Outcome(RunStatus.TIMEOUT, parsed, f"the splitter timed out after {timeout_minutes} minutes")
    return Outcome(RunStatus(parsed.status), parsed)


def _plan(ctx: Context, run: sqlite3.Row, slots: Sequence[_Slot], out: TextIO, log: logs.TickAdapter) -> Outcome:
    """Run the planner in a desk of worktrees at their bases, and write and record the plan it wrote (DESIGN §25).

    The desk holds a copy of the plan this one replaces, the ticket's current plan, if its file still reads as a plan.

    Returns:
        The planner's status; `timeout` if it timed out; `unknown` for a missing or invalid result line, or a `done`
        whose file in the desk is not a plan; or `crashed` when the plan's own file could not be written.
    """
    stopped = _stopped(ctx, run)
    if stopped:
        log.info("run not started", extra={"run_id": run["id"], "reason": stopped})
        return Outcome(RunStatus.STOPPED, None, stopped)
    for slot in slots:
        _check_out(slot)
    key = str(run["ticket_key"])
    replaced = plans.current(ctx.conn, key)
    copy = plans.read(plans.path_for(ctx.state_dir, key, replaced.run_id)).text if replaced is not None else None
    desk_files = {plans.REPLACED: copy} if copy is not None else {}
    template = ctx.config.runtime.plan_cmd
    result, text = _run_agent(ctx, run, slots, out, log, template=template, desk_files=desk_files)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    parsed = contract.last_line(PlanResult, text)
    if result.timed_out:
        return Outcome(RunStatus.TIMEOUT, parsed, f"the planner timed out after {timeout_minutes} minutes")
    if parsed is None:
        return Outcome(RunStatus.UNKNOWN, None, "the planner's last line was not a valid plan result")
    if parsed.status != "done":
        return Outcome(RunStatus(parsed.status), parsed)
    # Read before `_release` removes the desk: bounded, never through a link, and refused unless it is a plan.
    written = plans.read(desks.path(ctx.workspace.root, key) / plans.WRITTEN)
    if written.text is None:
        note = f"the planner reported done, but its {plans.WRITTEN} is {written.problem}; no plan was recorded"
        return Outcome(RunStatus.UNKNOWN, parsed, note)
    return _record_plan(ctx, run, parsed, written.text, log)


def _record_plan(ctx: Context, run: sqlite3.Row, parsed: PlanResult, text: str, log: logs.TickAdapter) -> Outcome:
    """Write a `done` plan's `text` to the plan's own file and record it `proposed` (DESIGN §25).

    Returns:
        `done` once it is recorded, or `crashed` when its file could not be written, its name taken included, and
        nothing is recorded.
    """
    key = str(run["ticket_key"])
    run_id = int(run["id"])
    try:
        written = plans.write(ctx.state_dir, key, run_id, text)
    except (plans.PlanFileError, OSError) as e:
        return Outcome(RunStatus.CRASHED, parsed, f"the plan was not written: {e}")
    # Should this fail, the file stays with no row: it is never read, and its name is this run's alone (DESIGN §25).
    plan = plans.record(ctx.conn, key, run_id, written, event=outbox.plan_proposed(ctx.config, key=key, run_id=run_id))
    log.info("plan recorded", extra={"run_id": run_id, "plan_id": plan.id, "size": written.size})
    return Outcome(RunStatus.DONE, parsed)


def _check_out(slot: _Slot, branch: str = "") -> _Start:
    """Check out the slot's base branch from origin, detached, or `branch` from origin if it is given and there.

    A split reads its base and creates no branch. A worker run passes its branch, which it continues if it was pushed.
    No run makes a local branch: every slot of a pool shares the repository's branch refs, so one would be state other
    slots see. The worker pushes `HEAD` to the branch by refspec (DESIGN §8, D109).

    Returns:
        HEAD's commit after the checkout, and how many entries HEAD's reflog then had.

    Raises:
        _SetupError: a git step failed, or the base branch is not on origin.
    """
    git = slot.git
    # --prune: a slot keeps remote-tracking refs from earlier runs, which would hide a branch since deleted on origin.
    git.run("fetch", "--quiet", "--prune", "origin")
    # Checked even when the branch is continued: the worker's prompt targets the PR at the base. A stacked run's base
    # is another ticket's branch, deleted when its PR merged (DESIGN §10).
    if not git.ok("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{slot.base}"):
        hint = "; if it was stacked on, its PR may have merged" if branch else ""
        raise _SetupError(f"{git.where}the base branch {slot.base} is not on origin{hint}")
    target = slot.base
    if branch and git.ok("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"):
        target = branch
    git.run("checkout", "--quiet", "--detach", f"refs/remotes/origin/{target}")
    if branch:
        _drop_local_branch(git, branch, target)
    commit = git.run("rev-parse", "HEAD")
    return _Start(commit, len(_head_log(git)), commit if target == branch else "")


def _drop_local_branch(git: _Git, branch: str, target: str) -> None:
    """Delete a local `branch` an earlier canopy's `checkout -B` left in the pool's repository, if origin has it all.

    A worker that made the branch again would fail, or fall back to the stale one. One with commits origin lacks is
    kept: they may be the only copy.
    """
    ref = f"refs/heads/{branch}"
    if git.ok("rev-parse", "--verify", "--quiet", ref) and git.ok(
        "merge-base", "--is-ancestor", ref, f"refs/remotes/origin/{target}"
    ):
        git.result("branch", "--quiet", "--delete", "--force", branch)  # refused if a worktree has it checked out


def _work(ctx: Context, run: sqlite3.Row, slots: Sequence[_Slot], out: TextIO, log: logs.TickAdapter) -> Outcome:
    stopped = _stopped(ctx, run)
    if stopped:
        log.info("run not started", extra={"run_id": run["id"], "reason": stopped})
        return Outcome(RunStatus.STOPPED, None, stopped)
    branch = str(run["branch"])
    starts = [_check_out(slot, branch) for slot in slots]
    for slot in slots:
        _run_setup(ctx, run, slot, out, log)
    copy = _plan_copy(ctx, run)
    desk_files = _place_copy(run, slots, copy)
    runtime = ctx.config.runtime
    template = runtime.private_worker_cmd if run["private"] else runtime.worker_cmd
    result, text = _run_agent(ctx, run, slots, out, log, template=template, desk_files=desk_files)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes

    parsed = parse_result(text)
    # Memory's fields are read only from a valid result line, and never stored with the result (DESIGN §28).
    remembered = memory.parse(text) if parsed is not None else None
    drafted = drafts.parse(text) if parsed is not None else None
    if parsed is not None:
        parsed = parsed.for_repos([s.repo for s in slots])
    if result.timed_out:
        status, note = RunStatus.TIMEOUT, f"the worker timed out after {timeout_minutes} minutes"
    elif parsed is None:
        status, note = RunStatus.UNKNOWN, "the worker's last line was not a valid result"
    else:
        status, note = RunStatus(parsed.status), ""

    rewritten = [(slot, path) for slot in slots if (path := slot.rewritten()) is not None]
    if rewritten:
        # The slot's git directory may be one the worker made: canopy runs no git in any slot of this run.
        notes = [f"{s.git.where}the worker rewrote {path}; nothing was checked or pushed" for s, path in rewritten]
        return Outcome(RunStatus.CRASHED, parsed, "; ".join(notes), memory=remembered, drafts=drafted)
    objects = _objects(ctx, run)
    if tidy.used(objects):
        # A sandboxed worker's commits are only in the run's object directory (DESIGN §8).
        slots = [slot.reading(ctx, objects) for slot in slots]

    # Every repository is checked, and pushed once if it needs it, even after one fails: a run is unpushed if any is.
    rebase = ctx.config.trust.rebase
    unpushed = [
        found
        for slot, start in zip(slots, starts, strict=True)
        if (found := _ensure_pushed(slot, branch, start, log, rebase=rebase))
    ]
    if unpushed:
        status, note = RunStatus.UNPUSHED, "; ".join(unpushed)
    committed = [found for slot in slots if copy is not None and (found := _committed_copy(slot, branch))]
    _keep_diffs(ctx, run, slots, log)
    head = _heads(slots, log) if remembered is not None and remembered.notes else None
    notes = "; ".join(n for n in [note, *committed] if n)
    return Outcome(status, parsed, notes, memory=remembered, head=head, drafts=drafted)


def _keep_diffs(ctx: Context, run: sqlite3.Row, slots: Sequence[_Slot], log: logs.TickAdapter) -> None:
    """Keep each slot's diff, for a run whose drafts the PR's page shows on it: one rendered under `approve`."""
    rendered = replies.run_replies(ctx.conn, int(run["id"]))
    if rendered is not None and rendered.mode is ReplyMode.APPROVE:
        for slot in slots:
            _keep_diff(slot, Path(run["log_path"]), log)


def _keep_diff(slot: _Slot, log_path: Path, log: logs.TickAdapter) -> None:
    """Keep the slot's diff at the run's head, from where it leaves its base, for the PR's page (DESIGN §29).

    Best effort, as a review's is (§21, The diff): the run does not need it, so any failure, git's or the disk's, is
    logged and the page shows the threads without a diff. The head is written before the diff, so a diff is never kept
    without the commit it was taken at.
    """
    fields = {"repo": slot.repo, "base": slot.base}
    try:
        head = slot.git.result("rev-parse", "HEAD")
        found = slot.git.result("merge-base", f"refs/remotes/origin/{slot.base}", "HEAD") if head.ok else head
        sha = head.stdout.strip()
        diff = slot.git.result(*review_diff.diff_args(found.stdout.strip(), sha)) if found.ok else found
        if not diff.ok:
            log.warning("run diff not kept", extra={**fields, "error": diff.stderr[:500]})
            return
        path = review_diff.run_path_for(log_path, slot.repo)
        review_diff.keep_head(path, sha)
        review_diff.keep(path, diff.stdout)
    except (_SetupError, OSError) as e:
        log.warning("run diff not kept", extra={**fields, "error": str(e)})


def _heads(slots: Sequence[_Slot], log: logs.TickAdapter) -> str | None:
    """Return the commit each slot's HEAD is at, which a note the run wrote was written against (DESIGN §28).

    Returns:
        The short commit in a run in one repository, `repo@commit` for each in a joint run, or None if git failed.
    """
    try:
        found = [(s.repo, s.git.run("rev-parse", "--short=12", "HEAD")) for s in slots]
    except _SetupError as e:
        log.warning("could not read the head a note was written against", extra={"error": str(e)})
        return None
    if len(found) == 1:
        return found[0][1]
    return " ".join(f"{repo}@{commit}" for repo, commit in found)


def _plan_copy(ctx: Context, run: sqlite3.Row) -> str | None:
    """Return the approved plan the run follows, the one its prompt names, read again from its file (DESIGN §25).

    Dispatch recorded the plan and checked its file against the approved hash; this checks both again, so the worker
    never gets a text the operator did not approve, nor a plan its prompt does not name.

    Returns:
        The plan's text, or None for a run dispatched to follow no plan.

    Raises:
        _SetupError: the plan was superseded or approved again since the dispatch, or its file changed or is gone.
    """
    if run["plan_id"] is None:
        return None
    approved = plans.approved_of(ctx.conn, str(run["ticket_key"]))
    # Approving again keeps the plan's id, but may approve another text than the one the prompt's outline is of.
    again = approved is not None and str(approved.approved_at) > str(run["started_at"])
    if approved is None or approved.id != run["plan_id"] or again:
        raise _SetupError(
            f"plan {run['plan_id']}, which the worker's prompt names, is no longer the plan approved for "
            f"{run['ticket_key']} when the run was dispatched; the worker did not start"
        )
    text = plans.approved_text(ctx.state_dir, approved)
    if text is None:
        path = plans.path_for(ctx.state_dir, approved.ticket_key, approved.run_id)
        raise _SetupError(
            f"plan {approved.id}'s file {path} is no longer the text the operator approved; the worker did not start"
        )
    return text


def _place_copy(run: sqlite3.Row, slots: Sequence[_Slot], copy: str | None) -> dict[str, str]:
    """Put the worker's copy of the plan where it starts: in its desk, or at its one worktree's root (DESIGN §25).

    Returns:
        The files `_run_agent` writes into the desk: the copy for a run in a desk, else none.
    """
    if copy is None:
        return {}
    if dispatch.in_desk(str(run["kind"]), slots):
        return {plans.COPY: copy}
    _write_copy(slots[0], copy)
    return {}


def _write_copy(slot: _Slot, text: str) -> None:
    """Write the worker's copy of the plan at the root of its worktree, ignored by git there (DESIGN §25).

    The repository's exclude file, which every slot shares, gets the copy's line once, so `git add -A` leaves it out.

    Raises:
        _SetupError: git could not name the repository's git directory, or the exclude file or the copy could not be
            written.
    """
    common = Path(slot.git.run("rev-parse", "--path-format=absolute", "--git-common-dir"))
    exclude = common / "info" / "exclude"
    line = f"/{plans.COPY}"
    try:
        held = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        if line not in held.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as f:
                f.write(f"{'' if not held or held.endswith(chr(10)) else chr(10)}{line}\n")
        logs.write_private(slot.path / plans.COPY, text)
    except OSError as e:
        raise _SetupError(f"{slot.git.where}could not write the plan's copy: {e}") from e


def _committed_copy(slot: _Slot, branch: str) -> str:
    """Return a harness note when the branch pushed from `slot` holds the plan's copy at its root, else "".

    Ignored is not untrackable: a worker can add the copy by name. canopy reports it and does not rewrite the branch
    (DESIGN §25, The worker's copy).
    """
    remote = _remote_head(slot.git, branch)
    if not remote:
        return ""
    found = slot.git.result("ls-tree", "--name-only", remote, "--", plans.COPY)
    if not (found.ok and found.stdout.strip()):
        return ""
    return f"{slot.git.where}the pushed {branch} holds {plans.COPY}, the plan's copy, committed by the worker"


def _stopped(ctx: Context, run: sqlite3.Row) -> str:
    """Return why the run must not start its worker, read again from the ticket's start record, or "" (DESIGN §22).

    A private run's ticket may have been stopped since the dispatch. A public run's may have been started privately
    since: its worker would write to the tracker, which a started ticket never has.
    """
    record = conversation.start_of(ctx.conn, str(run["ticket_key"]))
    if run["private"] and not conversation.is_started(record):
        return "the operator stopped the ticket before its worker started"
    if not run["private"] and record is not None:
        return "the operator started the ticket privately after this public run was dispatched"
    return ""


@dataclass(frozen=True)
class _Start:
    """Where a worker run's slot started: HEAD's commit, how many entries HEAD's reflog then had, and origin's branch.

    `pushed` is the commit the branch held on origin when the run started, or "" if origin did not have it.
    """

    commit: str
    moves: int
    pushed: str


def _run_setup(ctx: Context, run: sqlite3.Row, slot: _Slot, out: TextIO, log: logs.TickAdapter) -> None:
    """Run the operator's `setup_cmd` in the slot, at the run's branch, and fail the run if it fails (DESIGN §8).

    Unlike treehouse's `post_create`, which runs on the base before the branch is checked out and whose failure leaves
    the lease standing, this sees the branch the worker gets, and a failure stops the run before the worker starts.

    Raises:
        _SetupError: `setup_cmd` could not start, timed out, or exited non-zero.
    """
    argv = setup_words(ctx.config.runtime.setup_cmd)
    if not argv:
        return
    run_id = int(run["id"])
    timeout_minutes = ctx.config.runtime.setup_timeout_minutes
    log.info("running setup", extra={"run_id": run_id, "cmd": argv[0], "cwd": str(slot.path), "repo": slot.repo})
    try:
        result = ctx.runner.run(
            argv,
            cwd=slot.path,
            # The run's id, as the worker gets it: the operator's commands refuse inside canopy's runs (DESIGN §22).
            env={
                conversation.RUN_ID_ENV: str(run_id),
                SETUP_REPO_ENV: slot.repo,
                SETUP_BRANCH_ENV: str(run["branch"]),
                tidy.OBJECTS_ENV: str(_objects(ctx, run)),
            },
            timeout=timeout_minutes * 60,
        )
    except procs.ProcError as e:
        raise _SetupError(f"{slot.git.where}setup could not start: {e}") from e
    out.write(f"--- setup {slot.repo} stdout ---\n{result.stdout}\n--- setup {slot.repo} stderr ---\n{result.stderr}\n")
    out.write(f"--- setup {slot.repo} exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    if result.timed_out:
        raise _SetupError(f"{slot.git.where}setup timed out after {timeout_minutes} minutes; see the run log")
    if not result.ok:
        raise _SetupError(f"{slot.git.where}setup exited {result.returncode}; see the run log")


def _ensure_pushed(slot: _Slot, branch: str, start: _Start, log: logs.TickAdapter, *, rebase: bool) -> str:
    """Check the checkpoint invariant: the branch on origin is the slot's HEAD. Push HEAD to it once if it is not.

    Detached, HEAD is the only thing holding the worker's commits, so a worker that moved it off them leaves them
    behind: that is unpushed too. With `rebase` (`trust.rebase`), the push may replace the branch, but only if origin
    still has it where the run started: a worker that rebased and did not push loses nothing anyone else pushed.

    Returns:
        Why the work is not pushed, or "" if it is, or if the worker committed nothing.
    """
    git = slot.git
    local = git.run("rev-parse", "HEAD")
    remote = _remote_head(git, branch)
    # A HEAD that holds nothing past the start is no work of the worker's; whatever is on origin is its doing.
    if remote != local and not git.ok("merge-base", "--is-ancestor", local, start.commit):
        log.warning("worker left commits unpushed; pushing once", extra={"branch": branch, "repo": slot.repo})
        pushed = _push(git, branch, start.pushed if rebase else None)
        remote = _remote_head(git, branch)
        if not pushed.ok or remote != local:
            detail = (pushed.stderr.strip() or pushed.stdout.strip())[:500]
            return f"{git.where}commits on {branch} are not on origin; the push failed: {detail}"
    left = _left_behind(git, branch, start, remote)
    if left:
        return (
            f"{git.where}the worker moved HEAD off {len(left)} commit(s) not on origin, such as {left[0][:12]}; "
            "nothing was pushed for them"
        )
    return ""


def _push(git: _Git, branch: str, lease: str | None) -> procs.Result:
    """Push HEAD to `branch` on origin, and leave the shared refs as they were if git reads the run's objects.

    With a `lease`, the push may replace the branch, if origin has it at that commit, or does not have it when the
    lease is "". Without one, it only adds commits.

    A push also moves origin's remote-tracking ref, which every slot of the pool shares. Pointed at a commit only the
    run's object directory holds, it would break git in every slot, and in the primary clone, once that directory goes
    (DESIGN §8). The next fetch moves it, from origin's own objects.

    Returns:
        The push's result, whether or not it succeeded.
    """
    tracking = f"refs/remotes/origin/{branch}"
    before = git.result("rev-parse", "--verify", "--quiet", tracking).stdout.strip() if git.reads_run else ""
    force = () if lease is None else (f"--force-with-lease=refs/heads/{branch}:{lease}",)
    pushed = git.result("push", "--quiet", *force, "origin", f"HEAD:refs/heads/{branch}")
    if git.reads_run and before:
        git.result("update-ref", tracking, before)
    elif git.reads_run:
        git.result("update-ref", "-d", tracking)
    return pushed


def _left_behind(git: _Git, branch: str, start: _Start, remote: str) -> list[str]:
    """Commits HEAD held during the run whose changes neither HEAD nor origin holds.

    That is commits that neither HEAD, origin's `branch` now or when the run started, nor any of origin's branches
    holds, less those whose own change origin's `branch` already has (`_on_origin`). A worker that rebased, could not
    push the copies, and pushed the same work another way left nothing behind; one that rebased and pushed with a lease
    (`trust.rebase`) replaced the commits origin had, which were pushed before the run.

    Read from HEAD's reflog, the slot's own, so a worker that cleared it hides what it left; this catches a worker that
    checked something else out, not one that tried to hide its work.

    Returns:
        The commits left behind, none if HEAD did not move during the run.
    """
    entries = _head_log(git)
    held = list(dict.fromkeys(entries[: max(0, len(entries) - start.moves)]))
    if not held:
        return []
    keep = ["HEAD", start.pushed] if start.pushed else ["HEAD"]
    if remote and not git.ok("cat-file", "-e", f"{remote}^{{commit}}"):
        # --refmap=: no remote-tracking ref moves, only the slot's own FETCH_HEAD, which tidying drops.
        git.result("fetch", "--quiet", "--refmap=", "origin", f"refs/heads/{branch}")
    if not (remote and git.ok("cat-file", "-e", f"{remote}^{{commit}}")):
        return git.run("rev-list", *held, "--not", *keep, "--remotes=origin").split()
    left = git.run("rev-list", *held, "--not", *keep, remote, "--remotes=origin").split()
    tree = git.run("rev-parse", f"{remote}^{{tree}}")
    return [commit for commit in left if not _on_origin(git, commit, remote, tree)]


def _on_origin(git: _Git, commit: str, remote: str, tree: str) -> bool:
    """Whether `remote`, with tree `tree`, already has `commit`'s own change: applying it there changes nothing.

    A rebased copy of a commit origin has, or a commit whose change went up in another one, is not lost. It is a
    three-way merge of `commit` into `remote` on `commit`'s first parent, so a change made again by hand counts too, and
    a change origin has only in part does not. A root commit counts as not on origin, and so does every commit under
    git older than 2.40, which lacks `--merge-base`.

    Returns:
        True if the merge is clean and leaves `remote`'s tree as it is.
    """
    if not git.ok("rev-parse", "--verify", "--quiet", f"{commit}^"):
        return False
    merged = git.result("merge-tree", "--write-tree", f"--merge-base={commit}^", remote, commit)
    return merged.ok and merged.stdout.split()[:1] == [tree]


def _head_log(git: _Git) -> list[str]:
    """The commits in the slot's HEAD reflog, newest first, or none if it has no reflog.

    Returns:
        The commits' full hashes, one per reflog entry.
    """
    found = git.result("log", "--walk-reflogs", "--format=%H", "HEAD")
    return found.stdout.split() if found.ok else []


def _remote_head(git: _Git, branch: str) -> str:
    listed = git.run("ls-remote", "origin", f"refs/heads/{branch}")
    return listed.split()[0] if listed else ""


def _release(ctx: Context, run: sqlite3.Row, slots: Collection[_Slot], log: logs.TickAdapter) -> None:
    """Remove a joint run's desk, tidy each slot, return the ones tidied, and remove the run's object directory.

    A slot that could not be tidied is not returned, and the object directory is kept, so its objects can still be read.
    """
    if dispatch.in_desk(str(run["kind"]), slots):
        _remove_desk(ctx, str(run["ticket_key"]), log)
    objects = _objects(ctx, run)
    tidied = True
    for slot in slots:
        fields = {"run_id": run["id"], "slot": str(slot.path), "repo": slot.repo}
        ok = tidy.tidy(ctx.runner, slot.path, link=slot.link, base=slot.base, objects=objects, log=log, fields=fields)
        if ok:
            _return_slot(ctx, run, slot, log)
        tidied = tidied and ok
    if tidied:
        tidy.remove_objects(objects, log)


def _objects(ctx: Context, run: sqlite3.Row) -> Path:
    return tidy.objects_dir(dispatch.runs_dir(ctx), int(run["id"]))


def _return_slot(ctx: Context, run: sqlite3.Row, slot: _Slot, log: logs.TickAdapter) -> None:
    fields = {"run_id": run["id"], "slot": str(slot.path), "lease_id": slot.lease_id, "repo": slot.repo}
    try:
        outcome = ctx.pool_of(slot.pool, slot.repo).return_slot(
            slot.path, lease_id=slot.lease_id, lease_holder=slot.lease_holder
        )
    except pools.PoolError as e:
        # The next tick's reconcile returns a canopy lease with no running run.
        log.error("slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
        return
    if outcome is pools.ReturnOutcome.RETURNED:
        log.info("slot returned", extra=fields)
    else:
        log.warning("slot not returned", extra={**fields, "outcome": outcome.value})


def _remove_desk(ctx: Context, key: str, log: logs.TickAdapter) -> None:
    desk = desks.path(ctx.workspace.root, key)
    try:
        desks.remove(desk)
    except OSError as e:
        # Reconcile removes the desks of tickets with no running run.
        log.error("desk not removed", extra={"desk": str(desk), "error": str(e)})  # noqa: TRY400


def _record_prs(ctx: Context, run: sqlite3.Row, outcome: Outcome) -> None:
    """Record each PR the worker reported as its unit's, for display and the next worker's prompt, and its title."""
    if not isinstance(outcome.result, WorkerResult) or not outcome.result.prs:
        return
    titles = outcome.result.pr_titles or {}
    for repo, url in outcome.result.prs.items():
        if url and contract.plain_url(url, MAX_PR_URL):
            db.set_unit(ctx.conn, str(run["ticket_key"]), ctx.repo, repo, pr_url=url)
            if title := titles.get(repo):
                db.set_pr_title(ctx.conn, url, title)


class _Git:
    """git in one slot, through the runner. `name` is the slot's repository, for errors, or "" to leave it unnamed."""

    def __init__(self, runner: procs.Runner, slot: Path, name: str = "", env: Mapping[str, str] = hostgit.ENV) -> None:
        self.runner = runner
        self.slot = slot
        self.where = f"{name}: " if name else ""
        self.env = env
        # Whether git here reads the run's object directory, and so must write no shared ref (DESIGN §8).
        self.reads_run = "GIT_OBJECT_DIRECTORY" in env

    def result(self, *args: str) -> procs.Result:
        try:
            result = self.runner.run(hostgit.argv(*args), cwd=self.slot, env=self.env, timeout=_GIT_TIMEOUT_SECONDS)
        except procs.ProcError as e:
            raise _SetupError(f"{self.where}git {args[0]}: {e}") from e
        if result.timed_out:
            raise _SetupError(f"{self.where}git {args[0]} timed out")
        return result

    def ok(self, *args: str) -> bool:
        return self.result(*args).ok

    def run(self, *args: str) -> str:
        result = self.result(*args)
        if not result.ok:
            detail = (result.stderr.strip() or result.stdout.strip())[:500]
            raise _SetupError(f"{self.where}git {args[0]} exited {result.returncode}: {detail}")
        return result.stdout.strip()
