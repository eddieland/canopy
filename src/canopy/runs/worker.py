"""`canopy _run <run_id>`: one worker execution in its leased slots (DESIGN §8, §18).

Sets up the branch in each slot, runs the operator's `setup_cmd` there, makes the desk of a joint run, runs
`worker_cmd` with a timeout, parses the result line, verifies the branch is pushed in each slot, removes the desk,
returns every slot, and closes the `runs` row, recording the follow-up tickets its result names that pass their checks
(DESIGN §18). The slots are returned on every exit path this process can see: normal,
exception, and SIGTERM, SIGHUP, or SIGINT. SIGKILL cannot be caught; reconcile finds that run's dead pid on the next
tick.

A plan run checks each slot out at its base and pushes nothing, and always works in a desk, even over one repository:
the desk holds a copy of the plan it replaces, if the ticket has one. The planner runs with `plan_cmd` and writes its
plan to a file at the desk's root, the one file it may edit; a `done` one is read from there, bounded, written to the
plan's own file, and recorded `proposed` (DESIGN §25).

A feedback plan run checks each slot out at the ticket's branch, its PR's head, reads each PR whole through the `vcs`
source, and puts the items it may cover in its desk; the planner runs as a plan's does, and its result's items are
checked against those it was given, an id it was not given refused with a note (DESIGN §32).
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self, TextIO, assert_never, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt, StrictStr, model_validator

from canopy.core import (
    agent_models,
    cards,
    checklist_answers,
    checklists,
    commit_hooks,
    contract,
    conversation,
    db,
    definitions,
    git_tools,
    hostgit,
    memory,
    observe,
    outbox,
    plan_lengths,
    plans,
    pools,
    replies,
    review_answers,
    review_diff,
    run_models,
    run_offers,
    sandboxing,
)
from canopy.core.config import render_command, setup_words
from canopy.core.vocab import FlakyCause, PlanEffort, PoolKind, Proposal, ReplyMode, RunKind, RunStatus
from canopy.core.workspace import DESKS_DIR
from canopy.infra import logs, procs, stopping
from canopy.runs import (
    artifact_feed,
    attachments,
    checkpoint,
    desks,
    dispatch,
    drafted,
    drafts,
    feedback_items,
    feedback_plans,
    flaky_kick,
    follow_ups,
    plan_guards,
    policy,
    tidy,
)
from canopy.runs.checkpoint import SetupError
from canopy.runtime import agents, project_config, servers, stdout
from canopy.runtime.watch import Watch

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

MAX_TEXT = 2000
#: A planner's reason for saying its plan needs no review: a sentence, as a sink's line carries it.
MAX_REVIEW_REASON = 300
MAX_PR_URL = 500
#: A worker's line on why a check it left flaky failed: a sentence, as a sink's line carries it.
MAX_FLAKY_DETAIL = 300
#: A cause a worker named outside `FlakyCause`: a word or two, as a sink's line carries it.
MAX_OTHER_CAUSE = 60
# The repository whose slot `setup_cmd` runs in, by its name in the map, and the run's branch, which the slot has
# checked out detached (DESIGN §8).
SETUP_REPO_ENV = "CANOPY_REPO"
SETUP_BRANCH_ENV = "CANOPY_BRANCH"


class WorkerError(Exception):
    """`_run` cannot start this run at all. Nothing was leased or changed."""


Text = Annotated[StrictStr, contract.bounded(MAX_TEXT)]
PrTitle = Annotated[StrictStr, contract.one_line, contract.bounded(contract.MAX_PR_TITLE)]
Reply = Annotated[StrictStr, contract.bounded(feedback_plans.MAX_REPLY)]
#: A planner's one-line reason for saying its plan needs no review: shown with the plan, and sent to the sinks cut.
ReviewReason = Annotated[StrictStr, contract.one_line, contract.bounded(MAX_REVIEW_REASON)]


def _known_effort(value: object) -> object:
    """Return `value` if it is one of `PlanEffort`'s, else None: a misspelled estimate drops, never the plan with it."""
    # The `str` test first: `in` on an enum raises for an unhashable value, such as a list, before Python 3.13.
    return value if isinstance(value, str) and value in PlanEffort else None


#: A planner's estimate of how much work its plan is (DESIGN §25).
Effort = Annotated[PlanEffort | None, BeforeValidator(_known_effort)]
#: Whether a worker said a failed check was not its change's (DESIGN §23): only `true` says so, and anything else is
#: false, never a reason to drop the result with it.
Flaky = Annotated[bool, BeforeValidator(lambda value: value is True)]
#: Where a worker judged a flaky check failed (DESIGN §23): a value outside `FlakyCause` is no estimate, kept as
#: `flaky_cause_other` if it is text, never a reason to drop the result with it.
Cause = Annotated[
    FlakyCause | None,
    # The `str` test first: `in` on an enum raises for an unhashable value, such as a list, before Python 3.13.
    BeforeValidator(lambda value: value if isinstance(value, str) and value in FlakyCause else None),
]


def _line_within(limit: int) -> BeforeValidator:
    """Take a string to one line of at most `limit` characters, and anything else, or only whitespace, to None.

    Returns:
        A validator that never fails, so a wrong type drops the field, never the result with it.
    """

    def take(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        line = " ".join(value.split())
        return line if len(line) <= limit else line[: limit - 3] + "..."

    return BeforeValidator(take)


#: A worker's one line on why a check it left flaky failed (DESIGN §23): model text, kept with the run, never shown to
#: the overseer.
FlakyDetail = Annotated[str | None, _line_within(MAX_FLAKY_DETAIL)]
#: A cause a worker named that `FlakyCause` does not hold (DESIGN §23): model text, kept with the run so the word is
#: not lost, told to the sinks, never shown to the overseer.
OtherCause = Annotated[str | None, _line_within(MAX_OTHER_CAUSE)]


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
    #: Whether a `resume` for `ci` left a failed check as not the change's, such as a flaky test, for the operator to
    #: rerun (DESIGN §23). The checks and the evidence are in `summary`.
    flaky: Flaky = False
    #: With `flaky`, where the worker judged the check failed, given only when its evidence says so (DESIGN §23).
    flaky_cause: Cause = None
    #: With `flaky`, one line on why the check failed, such as the error it ended with; None when the worker gave none.
    flaky_detail: FlakyDetail = None
    #: The worker's `flaky_cause` when it was not one of `FlakyCause`'s, as it said it; set from that field alone.
    flaky_cause_other: OtherCause = None

    @model_validator(mode="before")
    @classmethod
    def _keep_other_cause(cls, data: object) -> object:
        """Keep a `flaky_cause` outside the vocabulary as `flaky_cause_other`, so the worker's word is not dropped.

        Returns:
            The result's fields, with `flaky_cause_other` set from `flaky_cause` alone, whatever the worker sent for it.
        """
        if not isinstance(data, dict):
            return data
        given = cast("dict[str, object]", data)
        cause = given.get("flaky_cause")
        other = cause if isinstance(cause, str) and cause not in FlakyCause else None
        return given | {"flaky_cause_other": other}

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


class PlanResult(BaseModel):
    """A plan's result contract (DESIGN §25). The plan itself is the file the planner wrote in its desk, not a field.

    Untrusted, so bounded. A `blocked` plan's question is recorded as a worker message, as any run's is (§22).
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "blocked", "failed"]
    summary: Text = ""
    question: Text | None = None
    #: Whether the plan needs the operator's review, as the planner judged it. Only `not_needed`, with a reason, lets
    #: the harness approve it, and only under `policy.planner_may_approve` (DESIGN §25); a result without it needs one.
    review: Literal["needed", "not_needed"] = "needed"
    review_reason: ReviewReason | None = None
    #: How much work the plan is for the worker that follows it, as the planner judged: recorded with the plan, for
    #: the operator to read beside it (DESIGN §25). Nothing reads it to decide.
    effort: Effort = None

    def no_review(self) -> str | None:
        """Return the planner's reason for saying its plan needs no review, or None when it did not say so with one."""
        if self.status != "done" or self.review != "not_needed" or self.review_reason is None:
            return None
        return self.review_reason if self.review_reason.strip() else None


class FeedbackItem(BaseModel):
    """One item a feedback plan's result names: its id, what it proposes, and the reply it would draft."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    id: StrictInt
    proposal: Proposal
    reply: Reply | None = None


class FeedbackPlanResult(PlanResult):
    """A feedback plan's result contract (DESIGN §32): a plan's, with the items it covers. Untrusted, so bounded."""

    items: Annotated[list[FeedbackItem], Field(max_length=4 * feedback_plans.MAX_ITEMS)] = []


@dataclass(frozen=True)
class Outcome:
    """How a run ended: its `runs.status` and the summary stored as `result_json`."""

    status: RunStatus
    result: WorkerResult | PlanResult | None
    note: str = ""
    # What the worker sent of agent memory, and the commit its branch was at when it ended (DESIGN §28).
    memory: memory.Fields | None = None
    head: str | None = None
    # The comments it drafted in place of posting them (DESIGN §29).
    drafts: drafts.Fields | None = None
    #: The follow-up tickets the worker reported, checked: those to record, and those refused (DESIGN §18).
    follow_ups: follow_ups.Checked | None = None
    #: What a resume's worker answered of the review findings it was handed, checked (DESIGN §21).
    answers: review_answers.Checked | None = None
    #: Whether the worker left a failed check flaky, and the branches the harness kicked to rerun it (DESIGN §23).
    kicks: flaky_kick.Kicks = field(default_factory=flaky_kick.Kicks)
    #: What the worker answered of each item of the lists it was given, checked (DESIGN §42); None when it got none.
    checklist: checklist_answers.Checked | None = None

    def result_json(self) -> str:
        """Return the summary stored in `runs.result_json`. Never raw output (DESIGN §11).

        A refused follow-up is kept with it, by key, for the attention item it raises (DESIGN §18), and the repositories
        the harness kicked, for the overseer (DESIGN §23).
        """
        data: dict[str, object] = self.result.model_dump(mode="json") if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        if self.follow_ups is not None:
            data |= self.follow_ups.stored()
        if self.kicks.kicked:
            data["kicked"] = list(self.kicks.kicked)
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
    """  # noqa: DOC501  (the SetupError raised below is caught below, into a crashed outcome)
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
            kind = RunKind(run["kind"])
            if not slots:
                raise SetupError(f"run {run_id} has no slots")  # noqa: TRY301  (the same handling as git failures)
            tidy.make_objects(_objects(ctx, run))
            cards.make_answers(_answers(ctx, run))
            _write_checklists(ctx, run, kind, slots)
            outcome = _doer(kind)(ctx, run, slots, out, log)
        except stopping.Stopped as e:
            outcome = Outcome(RunStatus.CRASHED, None, str(e))
        except (SetupError, desks.DeskError) as e:
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
            remember = functools.partial(_record_reported, ctx, run, outcome)
            if not conversation.close_run(ctx.conn, ctx.config, run, outcome.status, stored, then=remember):
                log.warning("run was already closed; its outcome is not recorded", extra=fields)
            procs.drop_lifelock(Path(run["log_path"]))
            log.info("run finished", extra={**fields, "status": outcome.status})
            _check_drafts(ctx, run_id, stop, log)
            run_models.read_ended(ctx, "runs", run_id, log)
    return outcome


def _write_checklists(ctx: Context, run: sqlite3.Row, kind: RunKind, slots: Iterable[_Slot]) -> None:
    """Write the lists of the run's repositories to its answers directory, where canopy's `pre-push` reads them (§42).

    A run that pushes nothing, or none of whose repositories has a list, gets no file and is never held.

    Raises:
        SetupError: a list cannot be used or written: dispatch read it, so it changed since, and the run never runs
            without it.
    """
    if not checklists.reminded(kind):
        return
    try:
        checklists.write(_answers(ctx, run), checklists.for_repos(ctx.config, [s.repo for s in slots]))
    except (checklists.ChecklistError, OSError) as e:
        raise SetupError(str(e)) from e


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


def _record_reported(ctx: Context, run: sqlite3.Row, outcome: Outcome) -> None:
    """Write what the run reported beside its result, in the transaction that closes it.

    That is its memory (§28), drafts (§29), and the follow-ups it filed (§18), with the event that tells the sinks of
    them, and the event that tells them it left a check flaky (§23), so a run reconcile closed first writes none. So
    are its answers to review findings (§21), but only from a run that ended `done` or `blocked`: one that did not
    finish its work cannot say what it fixed. Its answers to its checklists are recorded however it ended (§42): an item
    it was given and did not answer is counted unanswered.
    """
    run_id = int(run["id"])
    memory.record_run(ctx.conn, run_id, outcome.memory, head=outcome.head)
    drafts.record_run(ctx.conn, run_id, outcome.drafts)
    checklist_answers.record(ctx.conn, run_id, outcome.checklist)
    if outcome.status in (RunStatus.DONE, RunStatus.BLOCKED):
        review_answers.record(ctx.conn, run_id, outcome.answers)
    if outcome.follow_ups is not None and outcome.follow_ups.recorded:
        key = str(run["ticket_key"])
        recorded = follow_ups.record(ctx.conn, outcome.follow_ups, parent=key, run_id=run_id)
        log = logs.for_tick(int(run["tick_id"]))
        log.info("follow-ups recorded", extra={"run_id": run_id, "ticket": key, "follow_ups": recorded})
        filed = {k: outcome.follow_ups.recorded[k] for k in recorded}
        event = outbox.follow_ups_filed(ctx.config, key=key, run_id=run_id, filed=filed)
        if event is not None:
            db.record_event(ctx.conn, event)
    if outcome.kicks.flaky and isinstance(outcome.result, WorkerResult):
        flaky = outbox.ci_flaky(
            ctx.config,
            key=str(run["ticket_key"]),
            run_id=run_id,
            prs=[pr for pr in (outcome.result.prs or {}).values() if pr],
            kicked=outcome.kicks.kicked,
            estimate=outcome.result.flaky_detail or outcome.result.summary,
            cause=outcome.result.flaky_cause,
            other_cause=outcome.result.flaky_cause_other,
            note="; ".join(outcome.kicks.notes),
        )
        if flaky is not None:
            db.record_event(ctx.conn, flaky)


type _Doer = Callable[[Context, sqlite3.Row, Sequence[_Slot], TextIO, logs.TickAdapter], Outcome]


def _doer(kind: RunKind) -> _Doer:
    """What does a `kind` run, from checkout to its outcome.

    Returns:
        The function for the kind: a plan's or a worker's.

    Raises:
        SetupError: for `split` or `needs-plan`, retired kinds nothing dispatches now (M46, M55).
    """
    match kind:
        case RunKind.SPLIT | RunKind.NEEDS_PLAN:
            raise SetupError(f"{kind} is retired; nothing runs it")
        case RunKind.PLAN:
            return _plan
        case RunKind.FEEDBACK_PLAN:
            return _feedback_plan
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
    git: checkpoint.Git
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
            SetupError: git could not be set up to read `objects`.
        """
        try:
            env = tidy.reading(ctx.runner, self.path, objects)
        except tidy.GitError as e:
            raise SetupError(f"{self.git.where}{e}") from e
        return replace(self, git=checkpoint.Git(ctx.runner, self.path, self.repo, env))

    @classmethod
    def of(cls, ctx: Context, row: records.RunSlot) -> _Slot:
        repo = str(row.repo)
        path = Path(row.slot_path)
        return cls(
            repo,
            path,
            row.lease_id,
            row.lease_holder,
            str(row.base_branch),
            checkpoint.Git(ctx.runner, path, repo),
            hostgit.read_link(path),
            row.pool,
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
    marks: commit_hooks.Marks = commit_hooks.NONE,
) -> tuple[procs.Result, str]:
    """Check the places the agent reads config from, make the run's desk if it has one, and run `template` in it.

    `template` runs between `runtime.worker_cmd_prefix` and `worker_cmd_suffix` (DESIGN §12), for the worker's timeout,
    behind the sandbox wrapper when a slot's repository is one `runtime.sandbox_repos` names (DESIGN §24).
    A private run's places and a plan's must also name none of the tracker server's tools (DESIGN §22, §25).
    `desk_files` are written into the desk, by name, readable only by the operator, before the agent starts.
    `marks` are what canopy's git hooks put on every commit the agent makes (`commit_hooks`).

    The session and cost the runtime reported are recorded on the run at once, so a git step after the agent that
    fails does not lose them (DESIGN §13).

    Returns:
        The agent's process and the text its result line is read from.

    Raises:
        SetupError: a place the agent reads config from shadows canopy's definitions, or, for a private run or a
            plan, names one of the tracker server's tools.
    """
    prompt = dispatch.prompt_file(ctx, int(run["id"])).read_text(encoding="utf-8")
    desked = dispatch.in_desk(str(run["kind"]), slots)
    trees = [(s.repo, s.path) for s in slots]
    # Checked on the branch the worker will run on: the runtime reads the worktree's config too (D044). A worker in a
    # desk starts in no repository, so the runtime may look above it: the directories above it are checked.
    desk_parents = [ctx.workspace.root / DESKS_DIR, ctx.workspace.root] if desked else []
    places = [path for _, path in trees] + desk_parents
    tools = ctx.config.tracker.tools()
    read_only = run["private"] or run["kind"] in (policy.PLAN, policy.FEEDBACK_PLAN)
    refused = project_config.refusal(
        places,
        version=ctx.config.runtime.version,
        tracker_server=tools.server if read_only and tools is not None else None,
    )
    if refused is not None:
        raise SetupError(refused)
    # The model the run recorded, which its ticket's override may have chosen in place of config's (DESIGN §13).
    models = agent_models.of_run(ctx.config, template, run["model"])
    # The prompt's fixed instructions are its agent's body, in a snapshot every run of its kind shares (DESIGN §13).
    bodies, message = definitions.run_prompt(prompt, template)
    snapshot = definitions.ensure(ctx.state_dir, ctx.config, models, bodies)
    command = ctx.config.runtime.worker_template(template)
    rendered = render_command(
        command,
        message,
        snapshot,
        session_title(ctx.conn, str(run["ticket_key"]), str(run["kind"])),
    )
    argv = sandboxing.wrap(ctx.config.runtime, [s.repo for s in slots], "worker", rendered.argv, snapshot)
    if desked:
        cwd = desks.make(ctx.workspace.root, str(run["ticket_key"]), trees)
        for name, text in (desk_files or {}).items():
            try:
                # The attachments' copies are in a directory of their own (`_place_attachments`).
                (cwd / name).parent.mkdir(mode=0o700, exist_ok=True)
                logs.write_private(cwd / name, text)
            except OSError as e:
                raise SetupError(f"could not write {name} in the desk {cwd}: {e}") from e
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
    # The operator's commands refuse inside canopy's own runs (DESIGN §22). A sandbox wrapper points git at the object
    # directory; an unsandboxed worker ignores it (DESIGN §8). A planner, which has no shell, reads its worktrees'
    # history through canopy's read-only git tools, over those worktrees alone, each named for its repository (§27).
    # The operator's answer to a question its card asks reaches it in its answers directory, through canopy's plugin
    # (DESIGN §41).
    env = {
        conversation.RUN_ID_ENV: str(run_id),
        tidy.OBJECTS_ENV: str(_objects(ctx, run)),
        cards.ANSWERS_ENV: str(_answers(ctx, run)),
    }
    # A public worker that may publish names its ticket to the store through canopy, not its own word (DESIGN §38).
    publishing = ctx.config.artifacts.publishing()
    if not read_only and publishing is not None and agents.WORKER in publishing.agents:
        env |= artifact_feed.origin_env(ctx.workspace.name, str(run["ticket_key"]), run_id)
    # Every run here says where its work stands through canopy's `status` tool, which writes nothing (DESIGN §41).
    served: dict[str, Sequence[str]] = {cards.SERVER: cards.SERVER_COMMAND}
    if run["kind"] in (policy.PLAN, policy.FEEDBACK_PLAN):
        served[git_tools.SERVER] = git_tools.command({s.repo: s.path for s in slots})
    env |= servers.env(served, version=ctx.config.runtime.version, cwd=ctx.workspace.root.absolute())
    env |= commit_hooks.env(snapshot, marks, os.environ, _held_for(_answers(ctx, run), slots))
    with run_offers.probing(
        ctx.conn,
        "runs",
        run_id,
        ctx.runner,
        argv,
        version=ctx.config.runtime.version,
        cwd=cwd,
        env=env,
        log=log,
    ):
        result = ctx.runner.run(
            argv,
            cwd=cwd,
            env=env,
            stdin=rendered.stdin,
            timeout=timeout_minutes * 60,
            on_start=lambda pid: db.set_agent_pid(ctx.conn, "runs", run_id, pid),
            on_line=_Progress(ctx, run_id, out, log),
        )
    out.write(f"\n--- worker stderr ---\n{result.stderr}\n")
    out.write(f"--- worker exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    # Also after a timeout: whatever it printed before the kill names its session and what it had spent.
    output = stdout.read(result.stdout, version=ctx.config.runtime.version)
    if output.session_id is not None or output.usage is not None:
        db.set_run_report(
            ctx.conn,
            "runs",
            run_id,
            output.session_id,
            output.usage,
            digest=snapshot.name,
            tools=output.tools,
        )
        spent = output.usage.spent() if output.usage else {}
        log.info("worker reported", extra={"run_id": run_id, "session_id": output.session_id, **spent})
    return result, output.text


def _held_for(answers: Path, slots: Iterable[_Slot]) -> dict[Path, Path]:
    """Return the list, in the answers directory at `answers`, that each slot's push is held for (DESIGN §42).

    Returns:
        Each slot's path, to the file of its repository's list; none for a slot whose repository has no list.
    """
    return {s.path: listed for s in slots if (listed := checklists.file_of(answers, s.repo)).is_file()}


class _Progress:
    """Each line the worker prints, as it prints it: written to the run log, and its events read (DESIGN §8).

    What they say so far is recorded on the run, so a running run shows its session, what it has spent, its latest
    tool call, and its card, with the tool calls since. A line comes on `_run`'s own thread, so this may use the journal
    connection. A journal write that fails is logged, not raised: raising would kill the worker, and the session and
    spend are recorded again when it ends.
    """

    def __init__(self, ctx: Context, run_id: int, out: TextIO, log: logs.TickAdapter) -> None:
        self.ctx = ctx
        self.run_id = run_id
        self.out = out
        self.log = log
        self.watch = Watch(version=ctx.config.runtime.version)

    def __call__(self, line: str) -> None:
        self.out.write(line)
        self.out.flush()
        change = self.watch.read(line)
        if change is None:
            return
        try:
            # One transaction, so a tool call's progress and its card are recorded together or not at all.
            with db.transaction(self.ctx.conn):
                db.set_run_progress(self.ctx.conn, self.run_id, change.session_id, usage=change.usage, did=change.did)
                if change.called is not None:
                    cards.record_call(self.ctx.conn, "runs", self.run_id, cards.read_call(change.called))
        except sqlite3.Error as e:
            self.log.warning("worker progress not recorded", extra={"run_id": self.run_id, "error": str(e)})
        if change.started:
            self.log.info("worker session started", extra={"run_id": self.run_id, "session_id": change.session_id})


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
        checkpoint.check_out(slot.git, slot.base)
    key = str(run["ticket_key"])
    replaced = plans.current(ctx.conn, key)
    copy = plans.read(plans.path_for(ctx.state_dir, key, replaced.run_id)).text if replaced is not None else None
    desk_files = {plans.REPLACED: copy} if copy is not None else {}
    desk_files |= _place_attachments(run, slots, _attachment_copies(ctx, run))
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
    plan = plans.record(
        ctx.conn,
        key,
        run_id,
        written,
        event=outbox.plan_recorded(ctx.config, key=key, run_id=run_id),
        no_review=parsed.no_review() if ctx.config.policy.planner_approves() else None,
        effort=parsed.effort,
    )
    # Measured once, here, from the text as its planner wrote it, for the Plans report (`plan_lengths`).
    plan_lengths.keep(ctx.conn, plan.id, text)
    log.info(
        "plan recorded",
        extra={"run_id": run_id, "plan_id": plan.id, "size": written.size, "approved_by": plan.approved_channel},
    )
    return Outcome(RunStatus.DONE, parsed)


def _feedback_plan(
    ctx: Context,
    run: sqlite3.Row,
    slots: Sequence[_Slot],
    out: TextIO,
    log: logs.TickAdapter,
) -> Outcome:
    """Run the planner on what came back to the run's PRs, and write and record the feedback plan (DESIGN §32).

    Each slot is checked out at the ticket's branch, as its PR's head was pushed. Each PR is read whole through the
    `vcs` source first: the items the planner may cover are what that read observed, its reviews and threads, failed
    checks, conflicts, and merged blockers, written to its desk with a copy of the feedback plan this one replaces, if
    the ticket has one, and what changed on its PRs since that plan saw them.
    An item the result names that it was not given is refused, with a harness note; the rest are recorded with the
    plan, and with what the read saw, its snapshot (DESIGN §32, Planning again).

    Returns:
        The planner's status; `timeout` if it timed out; `unknown` for a missing or invalid result line, or a `done`
        whose file in the desk is not a plan; or `crashed` when the plan's own file could not be written.

    Raises:
        SetupError: a PR could not be read whole, so the planner would plan from less than its feedback.
    """
    stopped = _stopped(ctx, run)
    if stopped:
        log.info("run not started", extra={"run_id": run["id"], "reason": stopped})
        return Outcome(RunStatus.STOPPED, None, stopped)
    key = str(run["ticket_key"])
    for slot in slots:
        checkpoint.check_out(slot.git, slot.base, str(run["branch"]))
    units = {str(u.repo): str(u.pr_url) for u in db.units(ctx.conn, key) if u.pr_url}
    prs = [units[s.repo] for s in slots if s.repo in units]
    read = observe.read(ctx.conn, ctx.config, ctx.runner, prs, log)
    if not prs or read.failure is not None:
        raise SetupError(f"the PRs were not read whole, so nothing was planned: {read.failure or 'no PR to read'}")
    reviews = feedback_items.offered(ctx.conn, ctx.config.trust, key, prs)
    not_ci = feedback_items.not_ci(ctx.conn, ctx.workspace, prs)
    snapshot = feedback_items.take(ctx.conn, prs, reviews, not_ci)
    offered = [*reviews, *feedback_items.raised(ctx.conn, key, prs, not_ci)]
    desk_files = _feedback_desk(ctx, key, offered) | _place_attachments(run, slots, _attachment_copies(ctx, run))
    result, text = _run_agent(ctx, run, slots, out, log, template=ctx.config.runtime.plan_cmd, desk_files=desk_files)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes
    parsed = contract.last_line(FeedbackPlanResult, text)
    if result.timed_out:
        return Outcome(RunStatus.TIMEOUT, parsed, f"the planner timed out after {timeout_minutes} minutes")
    if parsed is None:
        return Outcome(RunStatus.UNKNOWN, None, "the planner's last line was not a valid feedback plan result")
    if parsed.status != "done":
        return Outcome(RunStatus(parsed.status), parsed)
    written = plans.read(desks.path(ctx.workspace.root, key) / plans.WRITTEN)
    if written.text is None:
        note = f"the planner reported done, but its {plans.WRITTEN} is {written.problem}; no plan was recorded"
        return Outcome(RunStatus.UNKNOWN, parsed, note)
    matched = feedback_plans.match(offered, [feedback_plans.Named(i.id, i.proposal, i.reply) for i in parsed.items])
    return _record_feedback_plan(ctx, run, parsed, written.text, matched=matched, snapshot=snapshot, log=log)


def _feedback_desk(ctx: Context, key: str, offered: Sequence[feedback_items.Item]) -> dict[str, str]:
    """Return the files a feedback planner's desk holds, each data to it (DESIGN §32).

    Returns:
        Its PRs' items with their replies, and, when the ticket has a feedback plan this one replaces, that plan's file
        as it stands, the operator's edits included, and what changed on its PRs since that plan saw them.
    """
    desk_files = {feedback_items.ITEMS: feedback_items.items_file(offered)}
    replaced = feedback_plans.current(ctx.conn, key)
    if replaced is None:
        return desk_files
    copy = plans.read(plans.path_for(ctx.state_dir, key, replaced.run_id)).text
    if copy is not None:
        desk_files[plans.REPLACED] = copy
    changed = feedback_items.changes(ctx.conn, ctx.config.trust, replaced, ctx.workspace)
    if changed:
        desk_files[feedback_items.CHANGES] = feedback_items.changes_file(changed)
    return desk_files


def _record_feedback_plan(
    ctx: Context,
    run: sqlite3.Row,
    parsed: FeedbackPlanResult,
    text: str,
    *,
    matched: feedback_plans.Matched,
    snapshot: feedback_items.Snapshot,
    log: logs.TickAdapter,
) -> Outcome:
    """Write a `done` feedback plan's `text` to its own file and record it `proposed`, with its items and `snapshot`.

    Returns:
        `done` once it is recorded, with a note naming the items refused, or `crashed` when its file could not be
        written, and nothing is recorded.
    """
    key = str(run["ticket_key"])
    run_id = int(run["id"])
    try:
        file = plans.write(ctx.state_dir, key, run_id, text)
    except (plans.PlanFileError, OSError) as e:
        return Outcome(RunStatus.CRASHED, parsed, f"the plan was not written: {e}")
    plan = feedback_plans.record(
        ctx.conn,
        key,
        run_id,
        file,
        matched.kept,
        snapshot=snapshot,
        event=outbox.plan_recorded(ctx.config, key=key, run_id=run_id, feedback=True),
        no_review=parsed.no_review() if ctx.config.policy.planner_approves() else None,
        effort=parsed.effort,
    )
    log.info(
        "feedback plan recorded",
        extra={
            "run_id": run_id,
            "plan_id": plan.id,
            "items": len(matched.kept),
            "refused": len(matched.refused),
            "approved_by": plan.approved_channel,
        },
    )
    return Outcome(RunStatus.DONE, parsed, matched.note())


def _work(ctx: Context, run: sqlite3.Row, slots: Sequence[_Slot], out: TextIO, log: logs.TickAdapter) -> Outcome:
    stopped = _stopped(ctx, run)
    if stopped:
        log.info("run not started", extra={"run_id": run["id"], "reason": stopped})
        return Outcome(RunStatus.STOPPED, None, stopped)
    branch = str(run["branch"])
    starts = [checkpoint.check_out(slot.git, slot.base, branch) for slot in slots]
    for slot in slots:
        _run_setup(ctx, run, slot, out, log)
    copy = _plan_copy(ctx, run)
    attached = _attachment_copies(ctx, run)
    desk_files = _place_copy(run, slots, copy) | _place_attachments(run, slots, attached)
    runtime = ctx.config.runtime
    template = runtime.private_worker_cmd if run["private"] else runtime.worker_cmd
    # As the prompt names them: the run's model, and its planner's when it follows a plan (DESIGN §25).
    planner = plan_guards.planner_model(ctx, run["plan_id"], run["feedback_plan_id"])
    marks = commit_hooks.marks(ctx.config, key=str(run["ticket_key"]), model=run["model"], planner_model=planner)
    result, text = _run_agent(ctx, run, slots, out, log, template=template, desk_files=desk_files, marks=marks)
    timeout_minutes = ctx.config.runtime.worker_timeout_minutes

    parsed = parse_result(text)
    # Memory's fields are read only from a valid result line, and never stored with the result (DESIGN §28).
    remembered = memory.parse(text) if parsed is not None else None
    drafted = drafts.parse(text) if parsed is not None else None
    # So are the tickets it filed, recorded whatever its status, a timeout's included: they exist in the tracker, and
    # a side output must not cost the run its PRs (DESIGN §18).
    filed = _check_follow_ups(ctx, run, follow_ups.parse(text)) if parsed is not None else None
    answered = _check_answers(ctx, run, text) if parsed is not None else None
    listed = _check_checklist(ctx, run, slots, text if parsed is not None else "")
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
        # A run that tampered with its slot records no follow-up: what it reported is named, and needs a label (§18).
        filed = filed.refusing("the run rewrote its slot's git") if filed is not None else None
        note = "; ".join(n for n in [*notes, filed.note() if filed is not None else ""] if n)
        return Outcome(
            RunStatus.CRASHED,
            parsed,
            note,
            memory=remembered,
            drafts=drafted,
            follow_ups=filed,
            checklist=listed,
        )
    objects = _objects(ctx, run)
    if tidy.used(objects):
        # A sandboxed worker's commits are only in the run's object directory (DESIGN §8).
        slots = [slot.reading(ctx, objects) for slot in slots]

    # Every repository is checked, and pushed once if it needs it, even after one fails: a run is unpushed if any is.
    rebase = ctx.config.trust.rebase
    unpushed = [
        found
        for slot, start in zip(slots, starts, strict=True)
        if (found := checkpoint.ensure_pushed(slot.git, branch, start, log, rebase=rebase))
    ]
    if unpushed:
        status, note = RunStatus.UNPUSHED, "; ".join(unpushed)
    committed = [found for slot in slots if copy is not None and (found := _committed_copy(slot, branch))]
    committed += [found for slot in slots if attached and (found := _committed_attachments(slot, branch))]
    for slot, start in zip(slots, starts, strict=True):
        committed += checkpoint.unmarked(slot.git, branch, start, slot.base, marks)
    # After the marks are read: a kick replaces the branch's commits with copies the run did not make (DESIGN §23).
    kicks = flaky_kick.after_run(
        ctx,
        run,
        status,
        flaky=parsed is not None and parsed.flaky,
        places=[(slot.git, slot.base, start) for slot, start in zip(slots, starts, strict=True)],
        prs=(parsed.prs if parsed is not None else None) or {},
        log=log,
    )
    committed += kicks.notes
    _keep_diffs(ctx, run, slots, log)
    head = _heads(slots, log) if remembered is not None and remembered.notes else None
    checked = [found.note() for found in (filed, answered, listed) if found is not None]
    notes = "; ".join(n for n in [note, *committed, *checked] if n)
    return Outcome(
        status,
        parsed,
        notes,
        memory=remembered,
        head=head,
        drafts=drafted,
        follow_ups=filed,
        answers=answered,
        kicks=kicks,
        checklist=listed,
    )


def _check_follow_ups(ctx: Context, run: sqlite3.Row, created: object) -> follow_ups.Checked:
    """Check the tickets a worker reported it created against the journal, the workspace, and the policy (§18).

    Returns:
        The entries to record when the run is closed, and those refused.
    """
    return follow_ups.check(
        ctx.conn,
        created,
        parent=str(run["ticket_key"]),
        repos={r.name for r in ctx.workspace.repos},
        limit=ctx.config.policy.max_follow_ups,
    )


def _check_answers(ctx: Context, run: sqlite3.Row, text: str) -> review_answers.Checked | None:
    """Check the answers a worker gave to the review findings it was handed, which only a resume is (DESIGN §21).

    Returns:
        The answers to record when the run is closed, and those refused; None for a run of another kind.
    """
    if run["kind"] != RunKind.RESUME:
        return None
    return review_answers.check(ctx.conn, review_answers.parse(text), key=str(run["ticket_key"]))


def _check_checklist(
    ctx: Context,
    run: sqlite3.Row,
    slots: Iterable[_Slot],
    text: str,
) -> checklist_answers.Checked | None:
    """Check what a worker answered of the lists it was given, read back from its answers directory (DESIGN §42).

    `text` is its output, or "" when its last line was no valid result, whose fields are not read.

    Returns:
        An answer for every item of every list it was given; None for a run given none.
    """
    if not checklists.reminded(run["kind"]):
        return None
    lists = checklists.given(_answers(ctx, run), [s.repo for s in slots])
    if not lists:
        return None
    return checklist_answers.check(lists, checklist_answers.parse(text) if text else None)


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
    except (SetupError, OSError) as e:
        log.warning("run diff not kept", extra={**fields, "error": str(e)})


def _heads(slots: Sequence[_Slot], log: logs.TickAdapter) -> str | None:
    """Return the commit each slot's HEAD is at, which a note the run wrote was written against (DESIGN §28).

    Returns:
        The short commit in a run in one repository, `repo@commit` for each in a joint run, or None if git failed.
    """
    try:
        found = [(s.repo, s.git.run("rev-parse", "--short=12", "HEAD")) for s in slots]
    except SetupError as e:
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
        SetupError: the plan was superseded or approved again since the dispatch, or its file changed or is gone.
    """
    if run["feedback_plan_id"] is not None:
        return _feedback_plan_copy(ctx, run)
    if run["plan_id"] is None:
        return None
    approved = plans.approved_of(ctx.conn, str(run["ticket_key"]))
    # Approving again keeps the plan's id, but may approve another text than the one the prompt's outline is of.
    again = approved is not None and str(approved.approved_at) > str(run["started_at"])
    if approved is None or approved.id != run["plan_id"] or again:
        raise SetupError(
            f"plan {run['plan_id']}, which the worker's prompt names, is no longer the plan approved for "
            f"{run['ticket_key']} when the run was dispatched; the worker did not start",
        )
    text = plans.approved_text(ctx.state_dir, approved)
    if text is None:
        path = plans.path_for(ctx.state_dir, approved.ticket_key, approved.run_id)
        raise SetupError(
            f"plan {approved.id}'s file {path} is no longer the text the operator approved; the worker did not start",
        )
    return text


def _feedback_plan_copy(ctx: Context, run: sqlite3.Row) -> str:
    """Return the approved feedback plan a `resume` follows, which it spent, read again from its file (DESIGN §32).

    Returns:
        The plan's text.

    Raises:
        SetupError: the plan was superseded since the dispatch, is not the one this run spent, or its file changed.
    """
    plan = feedback_plans.get(ctx.conn, int(run["feedback_plan_id"]))
    if plan is None or plan.spent_run_id != run["id"] or feedback_plans.current(ctx.conn, plan.ticket_key) != plan:
        raise SetupError(
            f"feedback plan {run['feedback_plan_id']}, which the worker's prompt names, is no longer the one approved "
            f"for {run['ticket_key']} when the run was dispatched; the worker did not start",
        )
    text = feedback_plans.approved_text(ctx.state_dir, plan)
    if text is None:
        path = plans.path_for(ctx.state_dir, plan.ticket_key, plan.run_id)
        raise SetupError(
            f"feedback plan {plan.id}'s file {path} is no longer the text the operator approved; the worker did not "
            "start",
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

    Raises:
        SetupError: git could not name the repository's git directory, or the exclude file or the copy could not be
            written.
    """
    checkpoint.ignore(slot.git, plans.COPY)
    try:
        logs.write_private(slot.path / plans.COPY, text)
    except OSError as e:
        raise SetupError(f"{slot.git.where}could not write the plan's copy: {e}") from e


def _committed_copy(slot: _Slot, branch: str) -> str:
    """Return a harness note when the branch pushed from `slot` holds the plan's copy at its root, else "".

    Ignored is not untrackable: a worker can add the copy by name. canopy reports it and does not rewrite the branch
    (DESIGN §25, Workers follow the plan).
    """
    remote = checkpoint.remote_head(slot.git, branch)
    if not remote:
        return ""
    found = slot.git.result("ls-tree", "--name-only", remote, "--", plans.COPY)
    if not (found.ok and found.stdout.strip()):
        return ""
    return f"{slot.git.where}the pushed {branch} holds {plans.COPY}, the plan's copy, committed by the worker"


def _attachment_copies(ctx: Context, run: sqlite3.Row) -> list[attachments.Copy]:
    """Return the ticket's attachments the run's prompt names and the ticket still holds, read again (DESIGN §22).

    Returns:
        Their copies, in the order they were attached.

    Raises:
        SetupError: an attachment's file is gone or changed since it was attached, so the worker gets none of them.
    """
    ref = conversation.Ref(conversation.TICKET, str(run["ticket_key"]))
    try:
        return attachments.copies(ctx.conn, ctx.state_dir, ref, str(run["started_at"]))
    except attachments.AttachmentFileError as e:
        raise SetupError(f"{e}; the worker did not start") from e


def _place_attachments(run: sqlite3.Row, slots: Sequence[_Slot], found: Sequence[attachments.Copy]) -> dict[str, str]:
    """Put the run's copies of its ticket's attachments where it starts: in its desk, or in its one worktree (§22).

    In a worktree they are in a directory at its root that git ignores, made afresh.

    Returns:
        The files `_run_agent` writes into the desk: the copies, for a run in a desk, else none.

    Raises:
        SetupError: git could not name the repository's git directory, or the exclude file or a copy could not be
            written.
    """
    if not found:
        return {}
    if dispatch.in_desk(str(run["kind"]), slots):
        return {f"{attachments.RUN_DIR}/{c.name}": c.text for c in found}
    slot = slots[0]
    checkpoint.ignore(slot.git, attachments.RUN_DIR)
    try:
        attachments.place(slot.path / attachments.RUN_DIR, found)
    except OSError as e:
        raise SetupError(f"{slot.git.where}could not write the attachments' copies: {e}") from e
    return {}


def _committed_attachments(slot: _Slot, branch: str) -> str:
    """Return a harness note when the branch pushed from `slot` holds the attachments' copies, else "" (§22).

    As with the plan's copy, canopy reports it and does not rewrite the branch (`_committed_copy`).
    """
    remote = checkpoint.remote_head(slot.git, branch)
    if not remote:
        return ""
    found = slot.git.result("ls-tree", "--name-only", remote, "--", attachments.RUN_DIR)
    if not (found.ok and found.stdout.strip()):
        return ""
    return f"{slot.git.where}the pushed {branch} holds {attachments.RUN_DIR}, the attachments' copies"


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


def _run_setup(ctx: Context, run: sqlite3.Row, slot: _Slot, out: TextIO, log: logs.TickAdapter) -> None:
    """Run the operator's `setup_cmd` in the slot, at the run's branch, and fail the run if it fails (DESIGN §8).

    Unlike treehouse's `post_create`, which runs on the base before the branch is checked out and whose failure leaves
    the lease standing, this sees the branch the worker gets, and a failure stops the run before the worker starts.

    Raises:
        SetupError: `setup_cmd` could not start, timed out, or exited non-zero.
    """
    argv = setup_words(ctx.config.runtime.setup_cmd)
    if not argv:
        return
    argv = sandboxing.wrap(ctx.config.runtime, [slot.repo], "setup", argv)
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
        raise SetupError(f"{slot.git.where}setup could not start: {e}") from e
    out.write(f"--- setup {slot.repo} stdout ---\n{result.stdout}\n--- setup {slot.repo} stderr ---\n{result.stderr}\n")
    out.write(f"--- setup {slot.repo} exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    if result.timed_out:
        raise SetupError(f"{slot.git.where}setup timed out after {timeout_minutes} minutes; see the run log")
    if not result.ok:
        raise SetupError(f"{slot.git.where}setup exited {result.returncode}; see the run log")


def _release(ctx: Context, run: sqlite3.Row, slots: Collection[_Slot], log: logs.TickAdapter) -> None:
    """Remove the run's answers directory and a joint run's desk, tidy and return each slot, and remove its objects.

    A slot that could not be tidied is not returned, and the object directory is kept, so its objects can still be read.
    """
    if dispatch.in_desk(str(run["kind"]), slots):
        _remove_desk(ctx, str(run["ticket_key"]), log)
    cards.remove_answers(_answers(ctx, run))
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


def _answers(ctx: Context, run: sqlite3.Row) -> Path:
    return cards.answers_dir(ctx.state_dir, str(run["id"]))


def _return_slot(ctx: Context, run: sqlite3.Row, slot: _Slot, log: logs.TickAdapter) -> None:
    fields = {"run_id": run["id"], "slot": str(slot.path), "lease_id": slot.lease_id, "repo": slot.repo}
    try:
        outcome = ctx.pool_of(slot.pool, slot.repo).return_slot(
            slot.path,
            lease_id=slot.lease_id,
            lease_holder=slot.lease_holder,
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
