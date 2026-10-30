"""`canopy _review <run_id>`: one review run (DESIGN §21), or one revision of a review's draft (§34).

Checks the slot out at the reviewed commit, runs the reviewer in a directory of its own outside the checkout, parses the
result, and always returns the slot with `--force`, which discards anything the reviewer left there. The checkout holds
code the loop did not write, and an agent runtime reads its configuration from its working directory, so the reviewer
works in `<state_dir>/reviews/<id>/`, where a link leads to the checkout. The harness runs nothing from the checkout.

A `done` review of one of the loop's own PRs holds for the operator, as its run closes, each finding that rebuts a
worker's decline and each that is late (`late`), which is read while the slot is still at the reviewed commit.

A revision runs the same way, as the reviewer does, and its `done` result becomes the newest version of the draft it
revises (`review_revisions.revised`) before its run closes, so a publish waiting on the revision sees that version.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import json
import os
import shutil
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from canopy.core import (
    agent_models,
    cards,
    conversation,
    db,
    definitions,
    git_tools,
    hostgit,
    outbox,
    pools,
    progress,
    review_answers,
    review_diff,
    review_drafts,
    review_revisions,
    review_runs,
    run_models,
    run_offers,
    sandboxing,
)
from canopy.core import review_result as result
from canopy.core.config import render_command
from canopy.core.vocab import ReviewRunStatus
from canopy.infra import logs, procs, stopping
from canopy.reviews import impact, late, start
from canopy.runtime import project_config, servers, stdout

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context
    from canopy.runtime.agents import Model
    from canopy.runtime.report import AgentOutput

_GIT_TIMEOUT_SECONDS = 300


class ReviewError(Exception):
    """`_review` cannot start this run at all: it does not exist or is not waiting to start."""


class Unreviewable(Exception):  # noqa: N818  (a run that ends `failed`, with a note)
    """The commit could not be checked out, so the reviewer never ran."""


class SetupError(Exception):
    """Something before the reviewer ran failed: the run is `crashed`."""


@dataclass(frozen=True)
class Outcome:
    """How a review run ended: its status and the validated result, with a note when the harness decided the status."""

    status: ReviewRunStatus
    #: The reviewer's validated result, or a reviser's.
    result: result.ReviewResult | result.RevisionResult | None
    note: str = ""
    #: The numbers, from 1, of a review's late findings, to hold for the operator as the run closes (DESIGN §21).
    late: Sequence[int] = ()

    def result_json(self) -> str:
        """Return what `review_runs.result_json` stores: the validated result and the harness's note."""
        data: dict[str, object] = self.result.model_dump() if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


@dataclass(frozen=True)
class Reviewer:
    """The reviewer's process as a review starts it: argv, stdin, environment, and the definitions it loads."""

    argv: Sequence[str]
    #: The prompt, when the command template places none in `argv`.
    stdin: str | None
    env: Mapping[str, str]
    #: The snapshot of canopy's agent definitions the command names (D040).
    snapshot: Path


def execute(ctx: Context, run_id: int, *, out: TextIO) -> Outcome:
    """Do review run `run_id`, from claiming it to returning its slot and closing its row.

    Returns:
        How the run ended, as recorded on its row: the reviewer's validated result, if any, and the harness's note.

    Raises:
        ReviewError: the run does not exist or is not waiting to start, for example because another `_review` has it.
    """
    run = review_runs.get_review_run(ctx.conn, run_id)
    if run is None:
        raise ReviewError(f"no review run {run_id}")
    if not db.claim_run(ctx.conn, "review_runs", run_id, os.getpid()):
        raise ReviewError(f"review run {run_id} is not waiting to start: it is {run.status} or another has it")
    log = logs.for_tick(run.tick_id)
    fields = {"review_run_id": run_id, "pr": run.pr_url, "sha": run.sha}
    log.info("review run started", extra=fields)
    outcome = Outcome(ReviewRunStatus.CRASHED, None, "the review run stopped before its reviewer finished")
    with stopping.StopOnSignal() as stop:
        try:
            outcome = _work(ctx, run, out, log)
        except stopping.Stopped as e:
            outcome = Outcome(ReviewRunStatus.CRASHED, None, str(e))
        except Unreviewable as e:
            outcome = Outcome(ReviewRunStatus.FAILED, None, str(e))
        except SetupError as e:
            outcome = Outcome(ReviewRunStatus.CRASHED, None, str(e))
            log.error("review run not started", extra={**fields, "error": str(e)})  # noqa: TRY400
        except Exception as e:
            outcome = Outcome(ReviewRunStatus.CRASHED, None, f"{type(e).__name__}: {e}")
            log.exception("review run failed", extra=fields)
        finally:
            stop.armed = False
            clean_up(ctx, run, log)
            stored = outcome.result_json()
            ended = outbox.review_ended(ctx.config, run, outcome.status, stored)
            hold = functools.partial(_hold, ctx, run, outcome, log)
            if not db.finish_run(ctx.conn, "review_runs", run_id, outcome.status, stored, event=ended, then=hold):
                log.warning("review run was already closed; its outcome is not recorded", extra=fields)
            else:
                if isinstance(outcome.result, result.ReviewResult) and outcome.result.pr_title:
                    # The PR's title as the reviewer read it, for display: the newest report wins, a worker's or a
                    # review's.
                    db.set_pr_title(ctx.conn, run.pr_url, outcome.result.pr_title)
                # A `done` review of a PR the loop does not own is the first version of a review on it (DESIGN §34).
                # Its draft is made from what the run recorded, so a failure here leaves the run as it ended, and the
                # operator's first verb on the draft makes it.
                try:
                    review_drafts.make(ctx.conn, run_id)
                except Exception:
                    log.exception("review draft not made", extra=fields)
            procs.drop_lifelock(Path(run.log_path))
            log.info("review run finished", extra={**fields, "status": outcome.status})
            run_models.read_ended(ctx, "review_runs", run_id, log)
    return outcome


def _hold(ctx: Context, run: records.ReviewRun, outcome: Outcome, log: logs.TickAdapter) -> None:
    """Hold for the operator a `done` review's rebuttals of a worker's declines, then its late findings (§21).

    A late finding that is also a rebuttal keeps the rebuttal's hold. Called as the run closes, in its transaction.
    """
    if outcome.status is not ReviewRunStatus.DONE or not isinstance(outcome.result, result.ReviewResult):
        return
    rebuttals = review_answers.hold_rebuttals(ctx.conn, run, outcome.result)
    if rebuttals:
        log.info("rebuttals held for the operator", extra={"review_run_id": run.id, "findings": rebuttals})
    held = [n for n in outcome.late if n not in rebuttals]
    for number in held:
        review_runs.hold(ctx.conn, run.id, number, rebuts=None)
    if held:
        log.info("late findings held for the operator", extra={"review_run_id": run.id, "findings": held})


def judged(ctx: Context, parsed: result.ReviewResult, changed: Collection[str] | None, repo: str | None) -> Outcome:
    """The outcome of a valid result, after the checks the harness can make itself (DESIGN §21).

    Args:
        ctx: The workspace's context, whose map holds the repository's `high_impact_paths` and whose config holds
            `review.low_impact`.
        parsed: The reviewer's validated result.
        changed: The paths the reviewed change touches, or None when git could not name them.
        repo: The repository of the PR reviewed, as its run names it.

    Returns:
        `failed` for a result that is not `done`, else `done`. A change to a high-impact path of `repo`
        (`impact.paths_for`) is recorded as high impact, before `review.low_impact` is read, and a low impact with
        `review.low_impact` unset as normal, each with a note saying so; a change whose paths could not be read keeps
        the reviewer's impact, with a note saying the paths went unchecked.
    """
    if parsed.status != "done":
        return Outcome(ReviewRunStatus.FAILED, parsed)
    found = impact.matched(impact.paths_for(ctx.workspace.repo(repo)), changed or ())
    if found is not None and parsed.impact != "high":
        raised = parsed.model_copy(update={"impact": "high"})
        return Outcome(ReviewRunStatus.DONE, raised, found.note(str(parsed.impact)))
    unchecked = (
        "the change's paths could not be read, so its high-impact paths went unchecked"
        if changed is None and parsed.impact != "high"
        else ""
    )
    if parsed.impact == "low" and not ctx.config.review.low_impact.strip():
        note = "reported low impact, but review.low_impact is not set; recorded as normal"
        lowered = parsed.model_copy(update={"impact": "normal"})
        return Outcome(ReviewRunStatus.DONE, lowered, "; ".join(n for n in (note, unchecked) if n))
    return Outcome(ReviewRunStatus.DONE, parsed, unchecked)


def _revised(ctx: Context, run: records.ReviewRun, parsed: result.RevisionResult | None) -> Outcome:
    """The outcome of a revision's result line: a `done` one made the draft's newest version, if the draft waited on it.

    Returns:
        `unknown` for no valid result, `failed` for a result that is not `done`, else `done`, with a note when the
        draft took no version from it.
    """
    if parsed is None:
        return Outcome(ReviewRunStatus.UNKNOWN, None, "the reviser's last line was not a valid result")
    if parsed.status != "done":
        return Outcome(ReviewRunStatus.FAILED, parsed)
    made = review_revisions.revised(ctx.conn, run, parsed)
    if made.version is None:
        return Outcome(ReviewRunStatus.DONE, parsed, made.why)
    return Outcome(ReviewRunStatus.DONE, parsed, f"made version {made.version.number} of the draft")


def clean_up(ctx: Context, run: records.ReviewRun, log: logs.TickAdapter) -> None:
    """Remove the reviewer's directory, never following its link, and its answers directory; return the slot, forced."""
    with contextlib.suppress(OSError):
        shutil.rmtree(start.run_dir(ctx, run.id))
    with contextlib.suppress(OSError):
        cards.remove_answers(cards.answers_dir(ctx.state_dir, f"review-{run.id}"))
    if run.slot_path is None:
        return
    fields = {"review_run_id": run.id, "slot": run.slot_path}
    try:
        outcome = ctx.pool_of(run.pool, run.repo).return_slot(
            Path(str(run.slot_path)),
            lease_id=str(run.lease_id),
            lease_holder=str(run.lease_holder),
        )
    except pools.PoolError as e:
        # The next tick's reconcile returns a canopy lease no running run holds.
        log.error("review slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
        return
    log.info("review slot returned", extra={**fields, "outcome": outcome.value})


def check_out(runner: procs.Runner, slot: Path, sha: str) -> list[str]:
    """Check `sha` out in `slot`, detached, and remove the commit's links that resolve outside the checkout.

    Returns:
        The removed links' paths, relative to the checkout.

    Raises:
        Unreviewable: git could not fetch or check out `sha`.
        SetupError: git could not be run.
    """
    _check_out(runner, slot, sha)
    return _drop_escaping_links(runner, slot)


def reviewer_dir(ctx: Context, cwd: Path, slot: Path) -> None:
    """Make `cwd`, the reviewer's own directory outside the checkout, private, with a link to the checkout in `slot`.

    Raises:
        SetupError: the runtime would read config of its own from `cwd` or above it, in the workspace.
    """
    cwd.mkdir(mode=0o700)
    (cwd / start.CHECKOUT_LINK).symlink_to(slot, target_is_directory=True)
    # The reviewer's own directory is canopy's, but the runtime may read config above it, as in a workspace's checkout.
    refused = project_config.refusal((cwd, ctx.workspace.root), version=ctx.config.runtime.version)
    if refused is not None:
        raise SetupError(refused)


def reviewer(
    ctx: Context,
    prompt: str,
    slot: Path,
    *,
    models: Mapping[str, Model] | None,
    title: str,
    repo: str | None,
    run: str,
) -> Reviewer:
    """The reviewer's process for a review of the checkout in `slot`, named `run` to the agent, on `models`.

    Makes a review run's answers directory, where the operator's answer to its card's question reaches it (DESIGN §41).

    Returns:
        Its argv behind the sandbox, if `repo` is sandboxed, its stdin, its environment, and its definitions.
    """
    # The prompt's fixed instructions are the reviewer's body, in a snapshot every review shares (DESIGN §13).
    bodies, message = definitions.run_prompt(prompt, ctx.config.runtime.review_cmd)
    snapshot = definitions.ensure(ctx.state_dir, ctx.config, models, bodies)
    command = render_command(ctx.config.runtime.review_cmd, message, snapshot, title)
    argv = sandboxing.wrap(ctx.config.runtime, [repo], "review", command.argv, snapshot)
    # The operator's commands refuse inside canopy's own runs (DESIGN §22). The reviewer reads its checkout's history
    # through canopy's read-only git tools, over that checkout alone, named as its link is (DESIGN §27), and says
    # where its review stands through the `status` tool (§41).
    served = {git_tools.SERVER: git_tools.command({start.CHECKOUT_LINK: slot}), cards.SERVER: cards.SERVER_COMMAND}
    env = {
        conversation.RUN_ID_ENV: run,
        **servers.env(served, version=ctx.config.runtime.version, cwd=ctx.ws.root.absolute()),
    }
    # An eval's review keeps no card, so it is asked nothing (DESIGN §21).
    if cards.may_ask(run):
        answers = cards.answers_dir(ctx.state_dir, run)
        cards.make_answers(answers)
        env[cards.ANSWERS_ENV] = str(answers)
    return Reviewer(argv, command.stdin, env, snapshot)


def reviewed(
    ctx: Context,
    done: procs.Result,
    output: AgentOutput,
    *,
    changed: Collection[str] | None,
    repo: str | None,
) -> Outcome:
    """The outcome of a reviewer's process: timed out, no valid result line, or what `judged` makes of its result.

    Args:
        ctx: The workspace's context.
        done: The reviewer's finished process.
        output: What it printed, read.
        changed: The paths the reviewed change touches, as `judged` takes them.
        repo: The repository reviewed, whose high-impact paths apply.

    Returns:
        `timeout`, `unknown`, or `judged`'s outcome.
    """
    if done.timed_out:
        minutes = ctx.config.runtime.review_timeout_minutes
        return Outcome(ReviewRunStatus.TIMEOUT, None, f"the reviewer timed out after {minutes} minutes")
    parsed = result.parse(output.text)
    if parsed is None:
        return Outcome(ReviewRunStatus.UNKNOWN, None, "the reviewer's last line was not a valid result")
    return judged(ctx, parsed, changed, repo)


def _work(ctx: Context, run: records.ReviewRun, out: TextIO, log: logs.TickAdapter) -> Outcome:
    slot = Path(str(run.slot_path))
    dropped = check_out(ctx.runner, slot, run.sha)
    if dropped:
        log.warning("removed links that leave the checkout", extra={"review_run_id": run.id, "links": dropped})
    changed = None
    if run.revises is None:
        # A revision's comments sit on the diff its review kept, never one of its own.
        changed = _save_diff(ctx.runner, slot, run, log)
    cwd = start.run_dir(ctx, run.id)
    reviewer_dir(ctx, cwd, slot)
    prompt = start.prompt_file(ctx, run.id).read_text(encoding="utf-8")
    title = f"{'revise' if run.revises is not None else 'review'} {run.pr_url}"
    run_id = run.id
    process = reviewer(ctx, prompt, slot, models=_models(ctx, run), title=title, repo=run.repo, run=f"review-{run_id}")
    argv, env, snapshot = process.argv, process.env, process.snapshot
    timeout_minutes = ctx.config.runtime.review_timeout_minutes
    log.info(
        "running reviewer",
        extra={"review_run_id": run.id, "cmd": argv[0], "cwd": str(cwd), "timeout_minutes": timeout_minutes},
    )
    out.write("--- reviewer stdout ---\n")
    out.flush()
    with run_offers.probing(
        ctx.conn,
        "review_runs",
        run_id,
        ctx.runner,
        argv,
        version=ctx.config.runtime.version,
        cwd=cwd,
        env=env,
        log=log,
    ):
        done = ctx.runner.run(
            argv,
            cwd=cwd,
            env=env,
            stdin=process.stdin,
            timeout=timeout_minutes * 60,
            on_start=lambda pid: db.set_agent_pid(ctx.conn, "review_runs", run_id, pid),
            # Each line reaches the run log as the reviewer prints it, so a running review's transcript is what it did
            # so far.
            on_line=progress.Progress(
                ctx.conn,
                "review_runs",
                run_id,
                out,
                log,
                agent="reviewer",
                fields={"review_run_id": run_id},
                version=ctx.config.runtime.version,
            ),
        )
    out.write(f"\n--- reviewer stderr ---\n{done.stderr}\n")
    out.write(f"--- reviewer exit {done.returncode}{' (timed out)' if done.timed_out else ''} ---\n")
    out.flush()
    # Also after a timeout: whatever it printed before the kill names its session and what it had spent.
    output = stdout.read(done.stdout, version=ctx.config.runtime.version)
    if output.session_id is not None or output.usage is not None:
        db.set_run_report(
            ctx.conn,
            "review_runs",
            run_id,
            output.session_id,
            output.usage,
            digest=snapshot.name,
            tools=output.tools,
        )
        spent = output.usage.spent() if output.usage else {}
        log.info("reviewer reported", extra={"review_run_id": run_id, "session_id": output.session_id, **spent})
    if run.revises is not None and not done.timed_out:
        return _revised(ctx, run, result.parse_revision(output.text))
    outcome = reviewed(ctx, done, output, changed=changed, repo=run.repo)
    parsed = outcome.result
    if outcome.status is ReviewRunStatus.DONE and isinstance(parsed, result.ReviewResult) and parsed.findings:
        # Read now, while the slot is at the reviewed commit: it goes back before the run closes.
        found = late.late(ctx.conn, ctx.runner, run, parsed, slot=slot, log=log)
        outcome = dataclasses.replace(outcome, late=tuple(found))
    return outcome


def _models(ctx: Context, run: records.ReviewRun) -> dict[str, Model]:
    """Each agent's model by its name for `run`: config's, but the reviewer's, the one the run recorded (DESIGN §13).

    The run recorded its ticket's override for the reviewer, else config's, so what is recorded is what runs.

    Returns:
        Each agent with a model, by its name, for the runtime to write into the run's definitions.
    """
    return agent_models.of_run(ctx.config, ctx.config.runtime.review_cmd, run.model)


def _check_out(runner: procs.Runner, slot: Path, sha: str) -> None:
    """Fetch `sha` from origin and check it out, detached. A commit origin does not have fails the run.

    Raises:
        Unreviewable: git failed to fetch or check out `sha`, or HEAD is not `sha` afterwards.
    """
    for args in (("fetch", "--quiet", "origin", sha), ("checkout", "--quiet", "--detach", sha)):
        _git(runner, slot, *args)
    head = _git(runner, slot, "rev-parse", "HEAD")
    if head != sha:
        raise Unreviewable(f"HEAD is {head} after checking out {sha}")


def _drop_escaping_links(runner: procs.Runner, slot: Path) -> list[str]:
    """Remove the commit's symlinks that resolve outside the checkout, and return their paths (DESIGN §21).

    A PR can commit a link to any path, such as one of the operator's files, and the reviewer reads through links.

    Returns:
        The removed links' paths, relative to the checkout.
    """
    root = slot.resolve()
    dropped: list[str] = []
    for entry in _git(runner, slot, "ls-files", "--stage", "-z").split("\0"):
        mode, _, name = entry.partition("\t")
        if not mode.startswith("120000 "):
            continue
        link = slot / name
        if not link.resolve().is_relative_to(root):
            link.unlink(missing_ok=True)
            dropped.append(name)
    return dropped


def _save_diff(
    runner: procs.Runner,
    slot: Path,
    run: records.ReviewRun,
    log: logs.TickAdapter,
) -> frozenset[str] | None:
    """Write the commit's diff against where it leaves its base branch beside the run's log, for the web UI.

    The base is the branch the PR merges into, fetched to `origin/<base>`, where the reviewer's git tools read it too.
    Best effort: the review does not need it, so a failure is logged and the page shows no diff. Diff drivers and
    textconv filters are off, since the commit's `.gitattributes` can name them.

    Returns:
        Every path the diff touches, as git names them, for its high-impact paths; None when git could not.
    """
    base = run.base_branch
    if not base:
        return None
    fields: dict[str, object] = {"review_run_id": run.id, "base": base}
    sha = run.sha
    tracking = f"refs/remotes/origin/{base}"
    fetched = _git_or_none(runner, slot, log, fields, "fetch", "--quiet", "origin", f"+refs/heads/{base}:{tracking}")
    fork = None if fetched is None else _git_or_none(runner, slot, log, fields, "merge-base", tracking, sha)
    if fork is None:
        return None
    diff = _git_or_none(runner, slot, log, fields, *review_diff.diff_args(fork.strip(), sha))
    if diff is not None:
        review_diff.keep(review_diff.path_for(run.log_path), diff)
    # Named apart from the kept diff, which is cut at a bound and quotes unusual names.
    names = _git_or_none(runner, slot, log, fields, *review_diff.names_args(fork.strip(), sha))
    return None if names is None else frozenset(name for name in names.split("\0") if name)


def _git_or_none(
    runner: procs.Runner,
    slot: Path,
    log: logs.TickAdapter,
    fields: Mapping[str, object],
    *args: str,
) -> str | None:
    """`git <args>`'s stdout, or None, logged, if it fails: for steps the review can do without.

    Returns:
        git's stdout, or None when git could not start or exited nonzero.
    """
    try:
        done = runner.run(hostgit.argv(*args), cwd=slot, env=hostgit.ENV, timeout=_GIT_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        log.warning("review diff not saved", extra={**fields, "step": args[0], "error": str(e)})
        return None
    if not done.ok:
        log.warning("review diff not saved", extra={**fields, "step": args[0], "error": done.stderr[:500]})
        return None
    return done.stdout


def _git(runner: procs.Runner, slot: Path, *args: str) -> str:
    try:
        done = runner.run(hostgit.argv(*args), cwd=slot, env=hostgit.ENV, timeout=_GIT_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        raise SetupError(f"git {args[0]}: {e}") from e
    if not done.ok:
        detail = (done.stderr.strip() or done.stdout.strip())[:500]
        # A PR of another repository fails here: its commit is not on this origin (DESIGN §21).
        raise Unreviewable(f"git {args[0]} failed: {detail}")
    return done.stdout.strip()
