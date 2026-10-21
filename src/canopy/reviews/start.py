"""`canopy review run`: guards, a slot, the reviewer's prompt, and the detached `canopy _review` (DESIGN §21).

A review is keyed by its PR and commit. The guards hold one `done` review per commit, a per-PR limit (the policy's plus
the operator's grants, `grants.py`), a daily limit, and `max_reviews` within `max_workers`, whatever the overseer asks
for. A refusal is raised as `Refusal`; the CLI records it as `refused:<guard>`.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import contract, db, notice, outbox, personas, pools, prompts, review_requests
from canopy.core import review_result as result
from canopy.core.vocab import ReviewRunStatus
from canopy.infra import lock, logs, procs
from canopy.reviews import findings, grants

if TYPE_CHECKING:
    import sqlite3

    from canopy.core import records
    from canopy.core.context import Context

REVIEWS_DIR = "reviews"
CHECKOUT_LINK = "checkout"
DISPATCH_ACTION = "dispatch:review"
HOLDER_KEY = "review:"
# Why a review runs (DESIGN §21): one of the loop's own PRs, named by its ticket, a PR with the operator's open review
# request, or a `review.query` match.
OWN = "own"
REQUEST = review_requests.PURPOSE
QUERY = "query"
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
MAX_PR_URL = 300
KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_DAY = timedelta(hours=24)


class Refusal(Exception):  # noqa: N818  (an outcome the overseer is told about, not an error)
    """A guard refused the review. `guard` names it in the `refused:<guard>` decision.

    `attention` names the attention item the refusal raises, if any: one only the operator can clear.
    """

    def __init__(self, guard: str, reason: str, *, attention: str | None = None) -> None:
        """Name the guard and say why it refused, and the attention item the refusal raises, if any."""
        super().__init__(f"{guard}: {reason}")
        self.guard = guard
        self.reason = reason
        self.attention = attention


@dataclass(frozen=True)
class Request:
    """What the overseer asked to review: a PR at a commit, the ticket of one of the loop's own PRs, its repository."""

    pr: str
    sha: str
    ticket: str | None
    repo: str | None


@dataclass(frozen=True)
class Started:
    """A review run that was started: its id, the pid of its `canopy _review`, and its slot."""

    run_id: int
    pid: int
    slot: Path


def reviews_dir(ctx: Context) -> Path:
    """Where review logs and prompts live, and each run's working directory: the operator's only.

    Returns:
        `<state_dir>/reviews/`, created mode 0700 if it was missing.
    """
    path = ctx.state_dir / REVIEWS_DIR
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def run_dir(ctx: Context, run_id: int) -> Path:
    """The reviewer's working directory, `<state_dir>/reviews/<id>/`: outside the checkout, which it links to.

    Returns:
        The directory's path. It is not created here.
    """
    return reviews_dir(ctx) / str(run_id)


def prompt_file(ctx: Context, run_id: int) -> Path:
    """Return the file holding review run `run_id`'s rendered prompt."""
    return reviews_dir(ctx) / f"{run_id}.prompt"


def holder(run_id: int) -> str:
    """The lease holder of a review run's slot: `canopy:review:<id>`.

    Returns:
        The holder the pool records on the lease.
    """
    return pools.holder_for(f"{HOLDER_KEY}{run_id}")


def check(ctx: Context, *, tick_id: int, request: Request) -> str:
    """Check the guards for a dry run, counting what this dry run already started as running (D036).

    Returns:
        The repository the review would lease in.

    Raises:
        Refusal: a guard refused.
    """
    planned = db.decisions_for_tick(ctx.conn, tick_id)
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        repo = _guard(ctx, request, planned=planned)
        _persona(ctx, request.ticket)
        return repo


def start(ctx: Context, *, tick_id: int, request: Request, context: str | None) -> Started:
    """Check the guards, lease a slot, record the review run, render its prompt, and spawn `canopy _review`.

    Returns:
        The new review run's id, the pid of its `canopy _review`, and the slot it leased.

    Raises:
        Refusal: a guard refused, or the slot could not be leased, the prompt rendered, or the run started. Nothing is
            left running and no slot is left leased.
    """
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        repo = _guard(ctx, request)
        # Fixed before the run is recorded, so a persona that cannot be used costs the PR none of its reviews.
        persona = _persona(ctx, request.ticket)
        attempt = len(db.review_runs_of(ctx.conn, request.pr)) + 1
        run_id = db.insert_review_run(
            ctx.conn,
            tick_id=tick_id,
            pr_url=request.pr,
            sha=request.sha,
            ticket=request.ticket,
            repo=repo,
            purpose=_purpose(ctx.conn, request),
            logs_dir=reviews_dir(ctx),
            persona=persona.name,
            persona_digest=persona.digest,
        )
        pool = ctx.pool(repo)
        try:
            lease = pool.lease(f"{HOLDER_KEY}{run_id}")
        except pools.PoolError as e:
            db.delete_review_run(ctx.conn, run_id)
            raise Refusal("no_slot", str(e)) from e
        db.set_review_slot(
            ctx.conn,
            run_id,
            slot=lease.path,
            lease_id=lease.lease_id,
            lease_holder=lease.lease_holder,
            base_branch=lease.base_branch,
            pool=ctx.config.pools.backend,
        )
        try:
            return _spawn(ctx, run_id, request, lease, attempt=attempt, context=context, persona=persona)
        except BaseException:
            with contextlib.suppress(pools.PoolError):
                pool.return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
            raise


def _persona(ctx: Context, ticket: str | None) -> personas.Persona:
    """Return the reviewer's persona, `ticket`'s override else `[personas]`'s, read now (DESIGN §31).

    It is never fallen back from.

    Returns:
        The persona.

    Raises:
        Refusal: `persona_missing` or `bad_persona`, with its attention item, as a worker's dispatch refuses.
    """
    try:
        return personas.for_run(ctx.conn, ctx.config, "reviewer", ticket)
    except personas.PersonaError as e:
        raise Refusal(e.guard, e.reason, attention=e.guard) from e


def _purpose(conn: sqlite3.Connection, request: Request) -> str:
    """Why the review runs: `own` with a ticket, checked by `_check_ours`; `request` for a PR the operator asked for.

    Returns:
        `own`, `request`, or `query`, a PR the loop does not own and the operator has no open request on.
    """
    if request.ticket is not None:
        return OWN
    return REQUEST if review_requests.open_request(conn, request.pr) is not None else QUERY


def _spawn(
    ctx: Context,
    run_id: int,
    request: Request,
    lease: pools.Lease,
    *,
    attempt: int,
    context: str | None,
    persona: personas.Persona,
) -> Started:
    cfg = ctx.config
    values = {
        "PR_URL": request.pr,
        "SHA": request.sha,
        "CHECKOUT": str(run_dir(ctx, run_id) / CHECKOUT_LINK),
        "RUN_ID": str(run_id),
        "TICKET": request.ticket or "none: this PR is not one of the loop's own",
        "TRACKER_PROVIDER": cfg.tracker.provider,
        "LOW_IMPACT": cfg.review.low_impact.strip() or "None: never report `low`.",
        "ATTEMPT": str(attempt),
        "MAX_ATTEMPTS": str(grants.limit(ctx.conn, cfg, request.pr)),
        "CONTEXT": context or None,
        "TIMEOUT_MINUTES": str(cfg.runtime.review_timeout_minutes),
        "CONTRACT": result.CONTRACT,
    }
    run = db.get_review_run(ctx.conn, run_id)
    if run is None:
        raise RuntimeError(f"review run {run_id} vanished")
    try:
        prompt = prompts.render_reviewer(
            cfg,
            values,
            notice=notice.for_prompt(ctx.conn),
            notes=_notes(ctx.conn, run),
            previous=findings.for_reviewer(ctx.conn, request.pr, before=run_id),
            persona=persona,
        )
    except (OSError, prompts.PromptError) as e:
        # Nothing started, so it costs the PR none of its reviews; the caller returns the slot.
        db.delete_review_run(ctx.conn, run_id)
        raise Refusal("bad_prompt", str(e)) from e
    try:
        logs.write_private(prompt_file(ctx, run_id), prompt)
        # `python -m canopy`, not `canopy` from PATH: the child is this same installation.
        argv = [sys.executable, "-m", "canopy", "_review", str(run_id)]
        pid = ctx.runner.spawn(argv, cwd=ctx.repo_root, log_path=Path(run.log_path))
    except (OSError, procs.ProcError) as e:
        note = json.dumps({"harness": f"could not start the reviewer: {e}"})
        db.finish_run(
            ctx.conn,
            "review_runs",
            run_id,
            ReviewRunStatus.CRASHED,
            note,
            event=outbox.review_ended(cfg, run, ReviewRunStatus.CRASHED, note),
        )
        raise Refusal("spawn_failed", str(e)) from e
    db.claim_run(ctx.conn, "review_runs", run_id, pid)
    return Started(run_id, pid, lease.path)


def _notes(conn: sqlite3.Connection, run: records.ReviewRun) -> str | None:
    """The operator's notes on the open request a `request` review answers; None for any other review, or none.

    Returns:
        The notes, or None.
    """
    if run.purpose != REQUEST:
        return None
    found = review_requests.open_request(conn, run.pr_url)
    return found.notes if found is not None else None


def _guard(ctx: Context, request: Request, *, planned: Collection[records.Decision] | None = None) -> str:
    """Refuse unless a review of `request` may start now. Returns the repository it leases in.

    `planned` is a dry run's decisions this tick: its reviews and worker dispatches count as running.

    Returns:
        The name of the repository the review leases in.

    Raises:
        Refusal: reviews are off, or one of the shape, repository, ownership, running, and limit checks refused.
    """
    if not review_requests.reviews_on(ctx.conn, ctx.config):
        raise Refusal(
            "reviews_off",
            "reviews are off: no [review] agent_prs or query and no open review request, or capacity.max_reviews is 0",
        )
    _check_shape(request)
    repo = _check_repo(ctx, request.repo)
    _check_ours(ctx, request, repo)
    planned = planned or []
    planned_reviews = [d for d in planned if d.action == DISPATCH_ACTION]
    planned_runs = [d for d in planned if d.action.startswith("dispatch:") and d.action != DISPATCH_ACTION]
    _check_running(ctx, request, planned_reviews, planned_runs)
    _check_limits(ctx, request, planned_reviews, planned_runs)
    return repo


def _check_ours(ctx: Context, request: Request, repo: str) -> None:
    """`not_ours`: a review names a ticket only for the PR that ticket's unit in `repo` opened.

    The overseer's `--ticket` is a claim; the unit's PR is the journal's record of what the loop opened, from the worker
    that opened it. Checked here, a review's purpose is settled once, as it starts.

    Raises:
        Refusal: (`not_ours`) `--ticket` names a ticket whose unit in `repo` has not opened the PR.
    """
    if request.ticket is not None and not db.is_unit_pr(ctx.conn, request.ticket, request.pr, repo=repo):
        raise Refusal(
            "not_ours",
            f"{request.ticket}'s unit in {repo} did not open {request.pr}; --ticket is only for the loop's own PR",
        )


def _check_running(
    ctx: Context,
    request: Request,
    planned_reviews: Iterable[records.Decision],
    planned_runs: Iterable[records.Decision],
) -> None:
    """`running`: a review of this PR, or a worker on its ticket, is running.

    Raises:
        Refusal: (`running`) a review of the PR is running or planned, or a worker on its ticket is.
    """
    running = next((r for r in db.running_runs(ctx.conn, "review_runs") if r["pr_url"] == request.pr), None)
    if running is not None:
        raise Refusal("running", f"review run {running['id']} of this PR is running")
    if any(d.pr == request.pr for d in planned_reviews):
        raise Refusal("running", "this dry run already reviewed this PR")
    if request.ticket is None:
        return
    worker = next((r for r in db.running_runs(ctx.conn, "runs") if r["ticket_key"] == request.ticket), None)
    if worker is not None or any(d.ticket_key == request.ticket for d in planned_runs):
        # A review must not race the push it is meant to judge.
        raise Refusal("running", f"a worker run for {request.ticket} is running; review its PR once it ends")


def _check_limits(
    ctx: Context,
    request: Request,
    planned_reviews: Collection[records.Decision],
    planned_runs: Collection[records.Decision],
) -> None:
    """`reviewed`, `review_limit`, `daily_limit`, `review_capacity`, and `capacity`, in that order.

    Raises:
        Refusal: the commit already has a `done` review, the PR has used its reviews, the day's reviews are used, or
            the review runs or the workers and reviews together fill their capacity.
    """
    cfg = ctx.config
    runs = db.review_runs_of(ctx.conn, request.pr)
    done = next((r for r in runs if r.sha == request.sha and r.status is ReviewRunStatus.DONE), None)
    if done is not None:
        # The PR may be out of the state block's window by now, so the refusal says what the review found.
        stored = result.stored(done.result_json)
        found = f" ({stored.verdict}, impact {stored.impact})" if stored is not None else ""
        raise Refusal(
            "reviewed",
            f"review run {done.id} already reviewed {request.sha[:12]}{found}; one review per commit",
        )
    limit = grants.limit(ctx.conn, cfg, request.pr)
    if len(runs) >= limit:
        raise Refusal("review_limit", f"this PR has had {len(runs)} review runs and the limit is {limit}")
    since = db.format_time(datetime.now(UTC) - _DAY)
    today = len(db.review_runs_since(ctx.conn, since)) + len(planned_reviews)
    if today >= cfg.capacity.max_reviews_per_day:
        per_day = cfg.capacity.max_reviews_per_day
        raise Refusal("daily_limit", f"{today} review runs started in the last 24 hours; the limit is {per_day}")
    busy_reviews = len(db.running_runs(ctx.conn, "review_runs")) + len(planned_reviews)
    if busy_reviews >= cfg.capacity.max_reviews:
        raise Refusal("review_capacity", f"{busy_reviews} of {cfg.capacity.max_reviews} review runs are running")
    busy = len(db.running_runs(ctx.conn, "runs")) + busy_reviews + len(planned_runs)
    if busy >= cfg.capacity.max_workers:
        raise Refusal("capacity", f"{busy} of {cfg.capacity.max_workers} workers and reviews are running")


def _check_shape(request: Request) -> None:
    """`bad_pr`: the URL, commit, and ticket key reach the prompt, the journal, and git's argv.

    Raises:
        Refusal: (`bad_pr`) the URL is not a plain https:// URL, the commit is not a full sha, or the key is invalid.
    """
    if not contract.plain_url(request.pr, MAX_PR_URL):
        raise Refusal("bad_pr", f"--pr must be the PR's plain https:// URL, at most {MAX_PR_URL} characters")
    if SHA_RE.fullmatch(request.sha) is None:
        raise Refusal("bad_pr", "--sha must be the full head commit: 40 or 64 lowercase hex characters")
    if request.ticket is not None and KEY_RE.fullmatch(request.ticket) is None:
        raise Refusal("bad_pr", f"--ticket must match {KEY_RE.pattern}")


def _check_repo(ctx: Context, repo: str | None) -> str:
    """`unknown_repo`: the PR's repository must be named, in the map, and cloned.

    Returns:
        The repository's name as the map spells it.

    Raises:
        Refusal: (`unknown_repo`) `repo` is None, not in the map, or not cloned.
    """
    ws = ctx.workspace
    names = ", ".join(r.name for r in ws.repos) or "none yet"
    if repo is None:
        raise Refusal("unknown_repo", f"--repo is required: name the PR's repository ({names})")
    found = ws.repo(repo)
    if found is None:
        raise Refusal("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
    if not found.cloned:
        raise Refusal("unknown_repo", f"{repo} has no clone at {found.path}; the operator runs `canopy workspace sync`")
    return found.name
