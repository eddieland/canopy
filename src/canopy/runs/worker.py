"""`canopy _run <run_id>`: one worker execution in its leased slots (DESIGN §8, §18).

Sets up the branch in each slot, runs the operator's `setup_cmd` there, makes the desk of a joint run, runs
`worker_cmd` with a timeout, parses the result line, verifies the branch is pushed in each slot, removes the desk,
returns every slot, and closes the `runs` row. The slots are returned on every exit path this process can see: normal,
exception, and SIGTERM, SIGHUP, or SIGINT. SIGKILL cannot be caught; reconcile finds that run's dead pid on the next
tick.

A split run is the same up to the worker: each slot is checked out at its base, the splitter runs with `split_cmd` in
the desk, and nothing is pushed or verified. Its result names the tickets it created, which are validated and recorded
in `split_children` (DESIGN §18).
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self, TextIO

from pydantic import BaseModel, ConfigDict, StrictStr

from canopy.core import agent_output, contract, conversation, db, definitions, hostgit, treehouse
from canopy.core.config import render_command, setup_words
from canopy.core.workspace import DESKS_DIR
from canopy.infra import logs, procs, stopping
from canopy.runs import desks, dispatch, policy, tidy

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


class WorkerResult(BaseModel):
    """The worker result contract (DESIGN §8, §18): the last line of the worker's stdout. Untrusted, so bounded.

    `prs` maps each repository's name to its PR. `pr` is the contract before joint runs, still accepted for a run in
    one repository.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    status: Literal["done", "blocked", "failed"]
    branch: Text | None = None
    pr: Text | None = None
    prs: dict[StrictStr, Text | None] | None = None
    summary: Text = ""
    question: Text | None = None

    def for_repos(self, repos: Sequence[str]) -> Self:
        """Return this result with `prs` kept to `repos`, the repositories the run worked in, and filled from `pr`."""
        prs = {r: self.prs.get(r) for r in repos if r in self.prs} if self.prs is not None else None
        if prs is None and self.pr is not None and len(repos) == 1:
            prs = {repos[0]: self.pr}
        return self.model_copy(update={"prs": prs})


class SplitResult(BaseModel):
    """A split's result contract (DESIGN §18): the tickets it created, each with the repository it covers.

    Untrusted, so bounded; `_run` checks the children against the journal before recording any (`check_children`).
    `children` is bounded by that check, not here: a valid split names one child per repository it was dispatched with,
    and a refused one is stored without its children.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    status: Literal["done", "failed"]
    summary: Text = ""
    children: dict[StrictStr, StrictStr] = {}


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

    status: str
    result: WorkerResult | SplitResult | None
    note: str = ""

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
    if not db.claim_run(ctx.conn, run_id, os.getpid()):
        raise WorkerError(f"run {run_id} is not waiting to start: it is {run['status']} or another process has it")
    slots = [_Slot.of(ctx, row) for row in db.run_slots(ctx.conn, run_id)]
    for slot in slots:
        # Before any git step: reconcile checks it for a `_run` that dies before putting a changed link back.
        db.set_slot_link(ctx.conn, run_id, slot.repo, slot.link)
    log = logs.for_tick(int(run["tick_id"]))
    fields = {"run_id": run_id, "ticket": run["ticket_key"], "kind": run["kind"]}
    where = {"slots": [str(s.path) for s in slots], "repos": [s.repo for s in slots]}
    log.info("run started", extra={**fields, **where, "branch": run["branch"]})

    outcome = Outcome("crashed", None, "the run stopped before the worker finished")
    with stopping.StopOnSignal() as stop:
        try:
            if not slots:
                raise _SetupError(f"run {run_id} has no slots")  # noqa: TRY301  (the same handling as git failures)
            tidy.make_objects(_objects(ctx, run))
            work = _split if run["kind"] == policy.SPLIT else _work
            outcome = work(ctx, run, slots, out, log)
        except stopping.Stopped as e:
            outcome = Outcome("crashed", None, str(e))
        except (_SetupError, desks.DeskError) as e:
            outcome = Outcome("crashed", None, str(e))
            log.error("run setup failed", extra={**fields, "error": str(e)})  # noqa: TRY400  (no traceback needed)
        except Exception as e:
            outcome = Outcome("crashed", None, f"{type(e).__name__}: {e}")
            log.exception("run failed", extra=fields)
        finally:
            # From here on a signal is ignored: returning the slots and closing the row must not be interrupted.
            stop.armed = False
            _release(ctx, run, slots, log)
            _record_prs(ctx, run, outcome)
            stored = outcome.result_json()
            if not conversation.close_run(ctx.conn, ctx.config, run, outcome.status, stored):
                log.warning("run was already closed; its outcome is not recorded", extra=fields)
            log.info("run finished", extra={**fields, "status": outcome.status})
    return outcome


@dataclass(frozen=True)
class _Slot:
    """One of a run's slots: the repository it is in, the worktree, its lease, git in it, and its `.git` link.

    `link` is what the worktree's `.git` file held when the run started, before any git step, or None if it is not a
    file (DESIGN §8).
    """

    repo: str
    path: Path
    lease_id: str
    lease_holder: str
    base: str
    git: _Git
    link: bytes | None

    def link_moved(self) -> bool:
        """Whether the `.git` file no longer holds what it did when the run started.

        Returns:
            True if it changed; always False when it was not a file at the start.
        """
        return self.link is not None and hostgit.read_link(self.path) != self.link

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
        )


def session_title(conn: sqlite3.Connection, key: str, kind: str) -> str:
    """A run's session title: `<KEY> <kind>: <the ticket's title>`, or `<KEY> <kind>` before the overseer names it.

    Returns:
        The title.
    """
    ticket = db.get_ticket(conn, key)
    title = ticket["title"] if ticket is not None else None
    return f"{key} {kind}: {title}" if title else f"{key} {kind}"


def _run_agent(
    ctx: Context, run: sqlite3.Row, slots: list[_Slot], out: TextIO, log: logs.TickAdapter, *, template: str
) -> tuple[procs.Result, str]:
    """Check the places the agent reads config from, make a joint run's desk, and run `template` in it.

    A private run's places must also name none of the tracker server's tools (DESIGN §22).

    The session and cost the runtime reported are recorded on the run at once, so a git step after the agent that
    fails does not lose them (DESIGN §13).

    Returns:
        The agent's process and the text its result line is read from.

    Raises:
        _SetupError: a place the agent reads config from shadows canopy's definitions, or, for a private run, names
            one of the tracker server's tools.
    """
    prompt = dispatch.prompt_file(ctx, int(run["id"])).read_text(encoding="utf-8")
    # Checked on the branch the worker will run on: OpenCode reads the worktree's config too (D044). A joint run's
    # worker starts in a desk, not a repository, so OpenCode may look above it: the directories above it are checked.
    desk_parents = [ctx.workspace.root / DESKS_DIR, ctx.workspace.root] if len(slots) > 1 else []
    places = [s.path for s in slots] + desk_parents
    shadowing = [found for place in places for found in definitions.shadowing(place)]
    if shadowing:
        raise _SetupError(definitions.shadowing_message(shadowing))
    tools = ctx.config.tracker.tools()
    if run["private"] and tools is not None:
        naming = [found for place in places for found in definitions.naming_tools(place, tools.server)]
        if naming:
            raise _SetupError(definitions.naming_tools_message(tools.server, naming))
    title = session_title(ctx.conn, str(run["ticket_key"]), str(run["kind"]))
    argv = render_command(template, prompt, definitions.ensure(ctx.state_dir, ctx.config), title)
    if len(slots) > 1:
        cwd = desks.make(ctx.workspace.root, str(run["ticket_key"]), [(s.repo, s.path) for s in slots])
    else:
        cwd = slots[0].path
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    log.info(
        "running worker",
        extra={"run_id": run["id"], "cmd": argv[0], "cwd": str(cwd), "timeout_minutes": timeout_minutes},
    )
    run_id = int(run["id"])
    result = ctx.runner.run(
        argv,
        cwd=cwd,
        # The operator's commands refuse inside canopy's own runs (DESIGN §22). A sandbox wrapper points git at the
        # object directory; an unsandboxed worker ignores it (DESIGN §8).
        env={conversation.RUN_ID_ENV: str(run_id), tidy.OBJECTS_ENV: str(_objects(ctx, run))},
        timeout=timeout_minutes * 60,
        on_start=lambda pid: db.set_worker_pid(ctx.conn, run_id, pid),
    )
    out.write(f"--- worker stdout ---\n{result.stdout}\n--- worker stderr ---\n{result.stderr}\n")
    out.write(f"--- worker exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    # Also after a timeout: whatever it printed before the kill names its session and what it had spent.
    output = agent_output.read(result.stdout)
    if output.session_id is not None or output.usage is not None:
        db.set_run_report(ctx.conn, run_id, output.session_id, output.usage)
        spent = {"cost_usd": output.usage.cost_usd, "tokens": output.usage.tokens} if output.usage else {}
        log.info("worker reported", extra={"run_id": run_id, "session_id": output.session_id, **spent})
    return result, output.text


def _split(ctx: Context, run: sqlite3.Row, slots: list[_Slot], out: TextIO, log: logs.TickAdapter) -> Outcome:
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
            return Outcome("timeout", None, f"the splitter timed out after {timeout_minutes} minutes")
        return Outcome("unknown", None, "the splitter's last line was not a valid split result")
    key = str(run["ticket_key"])
    invalid = check_children(ctx.conn, key, [s.repo for s in slots], parsed)
    if invalid:
        log.warning("split result refused; no child recorded", extra={"run_id": run["id"], "reason": invalid})
        status = "timeout" if result.timed_out else "unknown"
        # Stored without its children: a refused map is unbounded, and its note says what was wrong with it.
        return Outcome(status, parsed.model_copy(update={"children": {}}), f"children not recorded: {invalid}")
    if parsed.children:
        # Also after a timeout: the children it reported exist in the tracker, and a retry must not make them again.
        db.record_split_children(ctx.conn, key, int(run["id"]), parsed.children)
        log.info("split children recorded", extra={"run_id": run["id"], "children": parsed.children})
    if result.timed_out:
        return Outcome("timeout", parsed, f"the splitter timed out after {timeout_minutes} minutes")
    return Outcome(parsed.status, parsed)


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


def _work(ctx: Context, run: sqlite3.Row, slots: list[_Slot], out: TextIO, log: logs.TickAdapter) -> Outcome:
    stopped = _stopped(ctx, run)
    if stopped:
        log.info("run not started", extra={"run_id": run["id"], "reason": stopped})
        return Outcome("stopped", None, stopped)
    branch = str(run["branch"])
    starts = [_check_out(slot, branch) for slot in slots]
    for slot in slots:
        _run_setup(ctx, run, slot, out, log)
    runtime = ctx.config.runtime
    template = runtime.private_worker_cmd if run["private"] else runtime.worker_cmd
    result, text = _run_agent(ctx, run, slots, out, log, template=template)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes

    parsed = parse_result(text)
    if parsed is not None:
        parsed = parsed.for_repos([s.repo for s in slots])
    if result.timed_out:
        status, note = "timeout", f"the worker timed out after {timeout_minutes} minutes"
    elif parsed is None:
        status, note = "unknown", "the worker's last line was not a valid result"
    else:
        status, note = parsed.status, ""

    moved = [slot for slot in slots if slot.link_moved()]
    if moved:
        # The slot's git directory may be one the worker made: canopy runs no git in any slot of this run.
        notes = [
            f"{s.git.where}the worker rewrote {s.path / hostgit.LINK}; nothing was checked or pushed" for s in moved
        ]
        return Outcome("crashed", parsed, "; ".join(notes))
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
        status, note = "unpushed", "; ".join(unpushed)
    return Outcome(status, parsed, note)


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


def _release(ctx: Context, run: sqlite3.Row, slots: list[_Slot], log: logs.TickAdapter) -> None:
    """Remove a joint run's desk, tidy each slot, return the ones tidied, and remove the run's object directory.

    A slot that could not be tidied is not returned, and the object directory is kept, so its objects can still be read.
    """
    if len(slots) > 1:
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
        outcome = treehouse.return_slot(
            ctx.runner,
            slot.path,
            lease_id=slot.lease_id,
            lease_holder=slot.lease_holder,
            pool=ctx.workspace.pool(slot.repo),
        )
    except treehouse.TreehouseError as e:
        # The next tick's reconcile returns a canopy lease with no running run.
        log.error("slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
        return
    if outcome is treehouse.ReturnOutcome.RETURNED:
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
    """Record each PR the worker reported as its unit's, for display and the next worker's prompt."""
    if not isinstance(outcome.result, WorkerResult) or not outcome.result.prs:
        return
    for repo, url in outcome.result.prs.items():
        if url and contract.plain_url(url, MAX_PR_URL):
            db.set_unit(ctx.conn, str(run["ticket_key"]), ctx.repo, repo, pr_url=url)


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
