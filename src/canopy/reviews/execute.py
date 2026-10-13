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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from canopy.core import agent_output, conversation, db, definitions, hostgit, outbox, treehouse
from canopy.core.config import render_command
from canopy.infra import logs, procs, stopping
from canopy.reviews import result, start

if TYPE_CHECKING:
    import sqlite3

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

    status: str
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

    Raises:
        ReviewError: the run does not exist or is not waiting to start, for example because another `_review` has it.
    """
    run = db.get_review_run(ctx.conn, run_id)
    if run is None:
        raise ReviewError(f"no review run {run_id}")
    if not db.claim_review_run(ctx.conn, run_id, os.getpid()):
        raise ReviewError(f"review run {run_id} is not waiting to start: it is {run['status']} or another has it")
    log = logs.for_tick(int(run["tick_id"]))
    fields = {"review_run_id": run_id, "pr": run["pr_url"], "sha": run["sha"]}
    log.info("review run started", extra=fields)
    outcome = Outcome("crashed", None, "the review run stopped before its reviewer finished")
    with stopping.StopOnSignal() as stop:
        try:
            outcome = _work(ctx, run, out, log)
        except stopping.Stopped as e:
            outcome = Outcome("crashed", None, str(e))
        except _Unreviewable as e:
            outcome = Outcome("failed", None, str(e))
        except _SetupError as e:
            outcome = Outcome("crashed", None, str(e))
            log.error("review run not started", extra={**fields, "error": str(e)})  # noqa: TRY400
        except Exception as e:
            outcome = Outcome("crashed", None, f"{type(e).__name__}: {e}")
            log.exception("review run failed", extra=fields)
        finally:
            stop.armed = False
            clean_up(ctx, run, log)
            stored = outcome.result_json()
            ended = outbox.review_ended(ctx.config, run, outcome.status, stored)
            if not db.finish_review_run(ctx.conn, run_id, outcome.status, stored, event=ended):
                log.warning("review run was already closed; its outcome is not recorded", extra=fields)
            log.info("review run finished", extra={**fields, "status": outcome.status})
    return outcome


def _work(ctx: Context, run: sqlite3.Row, out: TextIO, log: logs.TickAdapter) -> Outcome:
    slot = Path(str(run["slot_path"]))
    sha = str(run["sha"])
    _check_out(ctx.runner, slot, sha)
    dropped = _drop_escaping_links(ctx.runner, slot)
    if dropped:
        log.warning("removed links that leave the checkout", extra={"review_run_id": run["id"], "links": dropped})
    cwd = start.run_dir(ctx, int(run["id"]))
    cwd.mkdir(mode=0o700)
    (cwd / start.CHECKOUT_LINK).symlink_to(slot, target_is_directory=True)
    # The reviewer's own directory is canopy's, but OpenCode may read config above it, as in a workspace's checkout.
    shadowing = [found for place in (cwd, ctx.workspace.root) for found in definitions.shadowing(place)]
    if shadowing:
        raise _SetupError(definitions.shadowing_message(shadowing))
    prompt = start.prompt_file(ctx, int(run["id"])).read_text(encoding="utf-8")
    argv = render_command(
        ctx.config.runtime.review_cmd,
        prompt,
        definitions.ensure(ctx.state_dir, ctx.config),
        f"review {run['pr_url']}",
    )
    timeout_minutes = ctx.config.runtime.review_timeout_minutes
    log.info(
        "running reviewer",
        extra={"review_run_id": run["id"], "cmd": argv[0], "cwd": str(cwd), "timeout_minutes": timeout_minutes},
    )
    run_id = int(run["id"])
    done = ctx.runner.run(
        argv,
        cwd=cwd,
        # The operator's commands refuse inside canopy's own runs (DESIGN §22).
        env={conversation.RUN_ID_ENV: f"review-{run_id}"},
        timeout=timeout_minutes * 60,
        on_start=lambda pid: db.set_review_agent_pid(ctx.conn, run_id, pid),
    )
    out.write(f"--- reviewer stdout ---\n{done.stdout}\n--- reviewer stderr ---\n{done.stderr}\n")
    out.write(f"--- reviewer exit {done.returncode}{' (timed out)' if done.timed_out else ''} ---\n")
    out.flush()
    if done.timed_out:
        return Outcome("timeout", None, f"the reviewer timed out after {timeout_minutes} minutes")
    parsed = result.parse(agent_output.read(done.stdout).text)
    if parsed is None:
        return Outcome("unknown", None, "the reviewer's last line was not a valid result")
    return judged(ctx, run, parsed)


def judged(ctx: Context, run: sqlite3.Row, parsed: result.ReviewResult) -> Outcome:
    """The outcome of a valid result, after the checks the harness can make itself (DESIGN §21)."""
    if parsed.status != "done":
        return Outcome("failed", parsed)
    if parsed.comment is None or not on_pr(parsed.comment, str(run["pr_url"])):
        # A comment's link begins with its PR's on GitHub. Without one, the commit's review is lost, not the PR's.
        note = "the reviewer reported done without the URL of a comment on this PR"
        return Outcome("failed", parsed, note)
    if parsed.impact == "low" and not ctx.config.review.low_impact.strip():
        note = "reported low impact, but review.low_impact is not set; recorded as normal"
        return Outcome("done", parsed.model_copy(update={"impact": "normal"}), note)
    return Outcome("done", parsed)


def _check_out(runner: procs.Runner, slot: Path, sha: str) -> None:
    """Fetch `sha` from origin and check it out, detached. A commit origin does not have fails the run."""
    for args in (("fetch", "--quiet", "origin", sha), ("checkout", "--quiet", "--detach", sha)):
        _git(runner, slot, *args)
    head = _git(runner, slot, "rev-parse", "HEAD")
    if head != sha:
        raise _Unreviewable(f"HEAD is {head} after checking out {sha}")


def on_pr(url: str, pr: str) -> bool:
    """Whether `url` is `pr` or a link within it, as a comment's is: `.../pull/7#...`, never `.../pull/70`."""
    return url == pr or url.startswith((f"{pr}#", f"{pr}/"))


def _drop_escaping_links(runner: procs.Runner, slot: Path) -> list[str]:
    """Remove the commit's symlinks that resolve outside the checkout, and return their paths (DESIGN §21).

    A PR can commit a link to any path, such as one of the operator's files, and the reviewer reads through links.
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


def clean_up(ctx: Context, run: sqlite3.Row, log: logs.TickAdapter) -> None:
    """Remove the reviewer's directory, never following its link, and return the slot with `--force`."""
    with contextlib.suppress(OSError):
        shutil.rmtree(start.run_dir(ctx, int(run["id"])))
    if run["slot_path"] is None:
        return
    fields = {"review_run_id": run["id"], "slot": run["slot_path"]}
    try:
        outcome = treehouse.return_slot(
            ctx.runner,
            Path(str(run["slot_path"])),
            lease_id=str(run["lease_id"]),
            lease_holder=str(run["lease_holder"]),
            pool=ctx.workspace.pool(run["repo"]),
        )
    except treehouse.TreehouseError as e:
        # The next tick's reconcile returns a canopy lease no running run holds.
        log.error("review slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
        return
    log.info("review slot returned", extra={**fields, "outcome": outcome.value})
