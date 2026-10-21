"""`canopy _review <run_id>`: one review run (DESIGN §21).

Checks the slot out at the reviewed commit, runs the reviewer in a directory of its own outside the checkout, parses the
result, and always returns the slot with `--force`, which discards anything the reviewer left there. The checkout holds
code the loop did not write, and an agent runtime reads its configuration from its working directory, so the reviewer
works in `<state_dir>/reviews/<id>/`, where a link leads to the checkout. The harness runs nothing from the checkout.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from canopy.core import conversation, db, definitions, hostgit, outbox, pools, review_diff, review_drafts, run_offers
from canopy.core import review_result as result
from canopy.core.config import render_command
from canopy.core.vocab import ReviewRunStatus
from canopy.infra import logs, procs, stopping
from canopy.reviews import start
from canopy.runtime import project_config, stdout

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

_GIT_TIMEOUT_SECONDS = 300


class ReviewError(Exception):
    """`_review` cannot start this run at all: it does not exist or is not waiting to start."""


class _Unreviewable(Exception):  # noqa: N818  (a run that ends `failed`, with a note)
    """The commit could not be checked out, so the reviewer never ran."""


class _SetupError(Exception):
    """Something before the reviewer ran failed: the run is `crashed`."""


@dataclass(frozen=True)
class Outcome:
    """How a review run ended: its status and the validated result, with a note when the harness decided the status."""

    status: ReviewRunStatus
    result: result.ReviewResult | None
    note: str = ""

    def result_json(self) -> str:
        """Return what `review_runs.result_json` stores: the validated result and the harness's note."""
        data: dict[str, object] = self.result.model_dump() if self.result is not None else {}
        if self.note:
            data["harness"] = self.note
        return json.dumps(data)


def execute(ctx: Context, run_id: int, *, out: TextIO) -> Outcome:
    """Do review run `run_id`, from claiming it to returning its slot and closing its row.

    Returns:
        How the run ended, as recorded on its row: the reviewer's validated result, if any, and the harness's note.

    Raises:
        ReviewError: the run does not exist or is not waiting to start, for example because another `_review` has it.
    """
    run = db.get_review_run(ctx.conn, run_id)
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
        except _Unreviewable as e:
            outcome = Outcome(ReviewRunStatus.FAILED, None, str(e))
        except _SetupError as e:
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
            if not db.finish_run(ctx.conn, "review_runs", run_id, outcome.status, stored, event=ended):
                log.warning("review run was already closed; its outcome is not recorded", extra=fields)
            else:
                if outcome.result is not None and outcome.result.pr_title:
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
    return outcome


def judged(ctx: Context, parsed: result.ReviewResult) -> Outcome:
    """The outcome of a valid result, after the checks the harness can make itself (DESIGN §21).

    Returns:
        `failed` for a result that is not `done`, else `done`. A low impact with `review.low_impact` unset is recorded
        as normal, with a note saying so.
    """
    if parsed.status != "done":
        return Outcome(ReviewRunStatus.FAILED, parsed)
    if parsed.impact == "low" and not ctx.config.review.low_impact.strip():
        note = "reported low impact, but review.low_impact is not set; recorded as normal"
        return Outcome(ReviewRunStatus.DONE, parsed.model_copy(update={"impact": "normal"}), note)
    return Outcome(ReviewRunStatus.DONE, parsed)


def clean_up(ctx: Context, run: records.ReviewRun, log: logs.TickAdapter) -> None:
    """Remove the reviewer's directory, never following its link, and return the slot with `--force`."""
    with contextlib.suppress(OSError):
        shutil.rmtree(start.run_dir(ctx, run.id))
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


def _work(ctx: Context, run: records.ReviewRun, out: TextIO, log: logs.TickAdapter) -> Outcome:
    slot = Path(str(run.slot_path))
    sha = run.sha
    _check_out(ctx.runner, slot, sha)
    dropped = _drop_escaping_links(ctx.runner, slot)
    if dropped:
        log.warning("removed links that leave the checkout", extra={"review_run_id": run.id, "links": dropped})
    _save_diff(ctx.runner, slot, run, log)
    cwd = start.run_dir(ctx, run.id)
    cwd.mkdir(mode=0o700)
    (cwd / start.CHECKOUT_LINK).symlink_to(slot, target_is_directory=True)
    # The reviewer's own directory is canopy's, but the runtime may read config above it, as in a workspace's checkout.
    refused = project_config.refusal((cwd, ctx.workspace.root))
    if refused is not None:
        raise _SetupError(refused)
    prompt = start.prompt_file(ctx, run.id).read_text(encoding="utf-8")
    snapshot = definitions.ensure(ctx.state_dir, ctx.config)
    argv = render_command(ctx.config.runtime.review_cmd, prompt, snapshot, f"review {run.pr_url}")
    timeout_minutes = ctx.config.runtime.review_timeout_minutes
    log.info(
        "running reviewer",
        extra={"review_run_id": run.id, "cmd": argv[0], "cwd": str(cwd), "timeout_minutes": timeout_minutes},
    )
    run_id = run.id
    # The operator's commands refuse inside canopy's own runs (DESIGN §22).
    env = {conversation.RUN_ID_ENV: f"review-{run_id}"}
    with run_offers.probing(ctx.conn, "review_runs", run_id, ctx.runner, argv, cwd=cwd, env=env, log=log):
        done = ctx.runner.run(
            argv,
            cwd=cwd,
            env=env,
            timeout=timeout_minutes * 60,
            on_start=lambda pid: db.set_agent_pid(ctx.conn, "review_runs", run_id, pid),
        )
    out.write(f"--- reviewer stdout ---\n{done.stdout}\n--- reviewer stderr ---\n{done.stderr}\n")
    out.write(f"--- reviewer exit {done.returncode}{' (timed out)' if done.timed_out else ''} ---\n")
    out.flush()
    # Also after a timeout: whatever it printed before the kill names its session and what it had spent.
    output = stdout.read(done.stdout)
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
    if done.timed_out:
        return Outcome(ReviewRunStatus.TIMEOUT, None, f"the reviewer timed out after {timeout_minutes} minutes")
    parsed = result.parse(output.text)
    if parsed is None:
        return Outcome(ReviewRunStatus.UNKNOWN, None, "the reviewer's last line was not a valid result")
    return judged(ctx, parsed)


def _check_out(runner: procs.Runner, slot: Path, sha: str) -> None:
    """Fetch `sha` from origin and check it out, detached. A commit origin does not have fails the run.

    Raises:
        _Unreviewable: git failed to fetch or check out `sha`, or HEAD is not `sha` afterwards.
    """
    for args in (("fetch", "--quiet", "origin", sha), ("checkout", "--quiet", "--detach", sha)):
        _git(runner, slot, *args)
    head = _git(runner, slot, "rev-parse", "HEAD")
    if head != sha:
        raise _Unreviewable(f"HEAD is {head} after checking out {sha}")


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


def _save_diff(runner: procs.Runner, slot: Path, run: records.ReviewRun, log: logs.TickAdapter) -> None:
    """Write the commit's diff against where it leaves its base branch beside the run's log, for the web UI.

    Best effort: the review does not need it, so a failure is logged and the page shows no diff. Diff drivers and
    textconv filters are off, since the commit's `.gitattributes` can name them; for a PR stacked on another branch,
    the diff holds that branch's commits too.
    """
    base = run.base_branch
    if not base:
        return
    fields: dict[str, object] = {"review_run_id": run.id, "base": base}
    sha = run.sha
    fetched = _git_or_none(runner, slot, log, fields, "fetch", "--quiet", "origin", f"refs/heads/{base}")
    fork = None if fetched is None else _git_or_none(runner, slot, log, fields, "merge-base", "FETCH_HEAD", sha)
    if fork is None:
        return
    diff = _git_or_none(runner, slot, log, fields, *review_diff.diff_args(fork.strip(), sha))
    if diff is not None:
        review_diff.keep(review_diff.path_for(run.log_path), diff)


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
        raise _SetupError(f"git {args[0]}: {e}") from e
    if not done.ok:
        detail = (done.stderr.strip() or done.stdout.strip())[:500]
        # A PR of another repository fails here: its commit is not on this origin (DESIGN §21).
        raise _Unreviewable(f"git {args[0]} failed: {detail}")
    return done.stdout.strip()
