"""`canopy dispatch`: guards, lease, and the detached `canopy _run` (DESIGN §8).

Guards are code and the overseer cannot talk its way past them (DESIGN §4, TRUST_MODEL T3). A refusal is raised as
`Refusal`; the CLI records it as a `refused:<guard>` decision.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db, prompts, treehouse
from canopy.infra import lock, logs, procs
from canopy.runs import policy

if TYPE_CHECKING:
    from canopy.core.context import Context

# The branch is `<branch_prefix><KEY>-<slug>`; the slug is the overseer's short name for the work. At most 40
# characters: lowercase words joined by single hyphens.
SLUG_RE = re.compile(r"(?=[a-z0-9-]{1,40}\Z)[a-z0-9]+(?:-[a-z0-9]+)*")
# A stacked run's base is another ticket's branch, `<branch_prefix><KEY>-<slug>`: what follows the prefix is one plain
# ref component, so it reaches git's argv as safely as a key.
BASE_TAIL_RE = re.compile(r"(?=.{1,200}\Z)[A-Za-z0-9][A-Za-z0-9_-]*")
DEFAULT_SLUG = "work"
# Creates the ticket's children in the tracker, one per repository, and pushes nothing (DESIGN §18).
SPLIT = "split"
DISPATCH_LOCK = "dispatch.lock"
RUNS_DIR = "runs"


class Refusal(Exception):  # noqa: N818  (a refusal is an outcome the overseer is told about, not an error)
    """A guard refused the dispatch. `guard` names it in the `refused:<guard>` decision."""

    def __init__(self, guard: str, reason: str) -> None:
        """Name the guard and say why it refused."""
        super().__init__(f"{guard}: {reason}")
        self.guard = guard
        self.reason = reason


@dataclass(frozen=True)
class Started:
    """A dispatched run."""

    run_id: int
    branch: str | None
    slot: Path | None
    pid: int
    label: str
    repos: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """What a run would do: its branch, its base, its queue label, and its repositories.

    `base` is the branch it stacks on if `--base` named one, and the label is in its configured spelling. `repos` names
    the one repository in the workspace the run works in, or for a split, every repository its children are for. A
    split has no branch: it pushes nothing, and `request` is the id of the comment that asked for it.
    """

    branch: str | None
    base: str | None
    label: str
    repos: tuple[str, ...]
    request: str | None = None


def valid_slug(value: str) -> bool:
    """Slugs reach branch names and argv, like keys."""
    return SLUG_RE.fullmatch(value) is not None


def branch_name(prefix: str, key: str, slug: str) -> str:
    """Return the branch a ticket's work is pushed to."""
    return f"{prefix}{key}-{slug}"


def runs_dir(ctx: Context) -> Path:
    """Where run logs and rendered worker prompts live, readable only by the operator (TRUST_MODEL T2)."""
    path = ctx.state_dir / RUNS_DIR
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def prompt_file(ctx: Context, run_id: int) -> Path:
    """Return the file holding run `run_id`'s rendered worker prompt."""
    return runs_dir(ctx) / f"{run_id}.prompt"


def start(
    ctx: Context,
    *,
    tick_id: int,
    key: str,
    kind: str,
    label: str | None,
    slug: str | None,
    base: str | None,
    context: str | None,
    repos: Sequence[str] = (),
    request: str | None = None,
) -> Started:
    """Check the guards, lease a slot, record the run, and spawn `canopy _run` for it.

    `implement` works on `<branch_prefix><KEY>-<slug>`. `fix-ci` and `resume` continue the branch the journal recorded
    for the ticket, so they take no slug. `base` stacks the run on another ticket's branch (DESIGN §10); without it the
    run starts from the pool's base branch. `repos` names the repository in the workspace; it may be left out only in
    a workspace of one. A `split` names every repository the ticket covers and the comment that asked for it in
    `request`, and leases nothing (DESIGN §18).

    Raises:
        Refusal: a guard refused, or the slot could not be leased or the worker started. Nothing is left running and
            no slot is left leased.
    """
    plan = _plan(ctx, key, kind, label=label, repos=repos, slug=slug, base=base, request=request)

    # One dispatch at a time, so two cannot both pass the capacity check. Held across the lease and the spawn.
    with lock.hold(ctx.state_dir / DISPATCH_LOCK, wait=True):
        attempt = _guard(ctx, key, kind)
        if plan.branch is None:
            return _spawn(
                ctx, tick_id=tick_id, key=key, kind=kind, plan=plan, lease=None, attempt=attempt, context=context
            )
        pool = ctx.workspace.pool(plan.repos[0])
        try:
            lease = treehouse.lease(ctx.runner, key, pool=pool)
        except treehouse.TreehouseError as e:
            raise Refusal("no_slot", str(e)) from e
        try:
            return _spawn(
                ctx, tick_id=tick_id, key=key, kind=kind, plan=plan, lease=lease, attempt=attempt, context=context
            )
        except BaseException:
            with contextlib.suppress(treehouse.TreehouseError):
                treehouse.return_slot(
                    ctx.runner, lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder, pool=pool
                )
            raise


def check(
    ctx: Context,
    *,
    tick_id: int,
    key: str,
    kind: str,
    label: str | None,
    slug: str | None,
    base: str | None,
    repos: Sequence[str] = (),
    request: str | None = None,
) -> Plan:
    """Check the guards a live dispatch would, for a dry run, and return the plan of the run it would start (D036).

    Nothing is leased, recorded, or spawned. The dry-run dispatches this tick already recorded stand in for the runs
    they would have started, so the `running` and `capacity` guards refuse what a live tick would. The lease, prompt,
    and spawn are not tried, so `no_slot`, `bad_prompt`, and `spawn_failed` never appear in a dry run.

    Raises:
        Refusal: a guard refused.
    """
    plan = _plan(ctx, key, kind, label=label, repos=repos, slug=slug, base=base, request=request)
    planned = [
        str(d["ticket_key"])
        for d in db.decisions_for_tick(ctx.conn, tick_id)
        if str(d["action"]).startswith("dispatch:") and d["ticket_key"] is not None
    ]
    with lock.hold(ctx.state_dir / DISPATCH_LOCK, wait=True):
        _guard(ctx, key, kind, planned=planned)
    return plan


def _plan(
    ctx: Context,
    key: str,
    kind: str,
    *,
    label: str | None,
    repos: Sequence[str],
    slug: str | None,
    base: str | None,
    request: str | None,
) -> Plan:
    configured = _check_label(ctx.config.tracker.labels, key, label)
    if kind == SPLIT:
        # Creating tickets is a human's call, never the overseer's own: a split names the authorized replier's comment
        # that asked for it, and the splitter reads that comment again before creating anything (D055).
        if request is None:
            raise Refusal(
                "unauthorized",
                f"split needs --request naming the authorized replier's comment on {key} that asked for it",
            )
        names = _check_split_repos(ctx, key, repos)
        if slug is not None:
            raise Refusal("bad_slug", "split creates tickets and pushes no branch; --slug is for implement")
        if base is not None:
            raise Refusal("bad_base", "split creates tickets and pushes no branch, so it has no base")
        return Plan(branch=None, base=None, label=configured, repos=names, request=request)
    if request is not None:
        raise Refusal("bad_request", f"--request names the comment that asked for a split; {kind} takes none")
    if len(set(repos)) > 1:
        raise Refusal(
            "unknown_repo",
            f"{kind} works in one repository; only split names several until joint runs (ROADMAP M7, D052)",
        )
    name = _check_repo(ctx, key, repos[0] if repos else None)
    branch = _branch(ctx, key, kind, slug)
    if base is not None:
        _check_base(ctx.config.trust.branch_prefix, branch, base)
    return Plan(branch=branch, base=base, label=configured, repos=(name,))


def _check_repo(ctx: Context, key: str, repo: str | None) -> str:
    """Refuse a repository the run cannot work in, and return the name of the one it will (DESIGN §18).

    In a workspace, `--repo` must name a repository in the map with a primary clone. A ticket stays in the repository
    of its first dispatch: its branch and PR are there, and a run over several repositories is ROADMAP M7 (D052). A
    ticket a split created is worked only in the repository the split recorded for it. In a workspace of one, `--repo`
    may be left out, and if given must name the repository.
    """
    ws = ctx.workspace
    if repo is None:
        if not ws.single:
            names = ", ".join(r.name for r in ws.repos) or "none yet"
            raise Refusal("unknown_repo", f"--repo is required in a workspace: name the repository for {key} ({names})")
        return ws.repos[0].name
    name = _known_repo(ctx, repo)
    child = db.split_child(ctx.conn, key)
    if child is not None and child["repo"] != name:
        raise Refusal(
            "unknown_repo", f"{key} was split from {child['parent_key']} for {child['repo']}; it is worked only there"
        )
    recorded = None if ws.single else db.ticket_repo(ctx.conn, key)
    if recorded is not None and recorded != name:
        raise Refusal(
            "unknown_repo",
            f"{key} is worked in {recorded}; a ticket stays in the repository of its first dispatch (D052)",
        )
    return name


def _check_split_repos(ctx: Context, key: str, repos: Sequence[str]) -> tuple[str, ...]:
    """Refuse a split that does not name at least two repositories it can read, and return their names (DESIGN §18).

    A ticket already worked in one repository is not split (D052), and neither is a ticket a split created.
    """
    ws = ctx.workspace
    if ws.single:
        raise Refusal("unknown_repo", "split needs a workspace of several repositories; this is a single repository")
    names = tuple(dict.fromkeys(repos))
    if len(names) < 2:  # noqa: PLR2004
        listed = ", ".join(r.name for r in ws.repos)
        raise Refusal(
            "unknown_repo", f"split names every repository {key} covers, at least two, each with --repo ({listed})"
        )
    for name in names:
        _known_repo(ctx, name)
    child = db.split_child(ctx.conn, key)
    if child is not None:
        raise Refusal(
            "unknown_repo", f"{key} was split from {child['parent_key']} for {child['repo']}; it is not split again"
        )
    recorded = db.ticket_repo(ctx.conn, key)
    if recorded is not None:
        raise Refusal(
            "unknown_repo", f"{key} is worked in {recorded}; a ticket with work in one repository is not split"
        )
    return names


def _known_repo(ctx: Context, repo: str) -> str:
    """Refuse a repository that is not in the map or has no clone; return its name."""
    found = ctx.workspace.repo(repo)
    if found is None:
        names = ", ".join(r.name for r in ctx.workspace.repos) or "none yet"
        raise Refusal("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
    if not found.cloned:
        raise Refusal("unknown_repo", f"{repo} has no clone at {found.path}; the operator runs `canopy workspace sync`")
    return found.name


def _check_label(labels: Sequence[str], key: str, label: str | None) -> str:
    """Refuse a dispatch that does not name one of the operator's queue labels (DESIGN §8, D051).

    canopy cannot read the tracker, so this cannot prove the label is on the ticket. It makes the overseer name the
    label it read for every dispatch, a claim recorded with the decision, instead of a check it can skip. Labels match
    case-insensitively, as GitHub's do; the configured spelling is returned. The refusal never lists the configured
    labels, so an overseer cannot copy one from it without reading the ticket.
    """
    if label is None:
        raise Refusal("unauthorized", f"--label is required: name the queue label you read on {key}")
    for configured in labels:
        if configured.casefold() == label.casefold():
            return configured
    raise Refusal("unauthorized", f"{label!r} is not a configured queue label; name the one you read on {key}")


def _check_base(prefix: str, branch: str, base: str) -> None:
    """Refuse a base that is not another ticket's agent branch (DESIGN §10, D045)."""
    tail = base.removeprefix(prefix)
    if tail == base or BASE_TAIL_RE.fullmatch(tail) is None:
        raise Refusal("bad_base", f"--base must be another ticket's branch, {prefix}<KEY>-<slug>")
    if base == branch:
        raise Refusal("bad_base", f"{branch} cannot be stacked on itself")


def _branch(ctx: Context, key: str, kind: str, slug: str | None) -> str:
    if kind == "implement":
        slug = DEFAULT_SLUG if slug is None else slug
        if not valid_slug(slug):
            raise Refusal("bad_slug", f"slug must match {SLUG_RE.pattern}")
        return branch_name(ctx.config.trust.branch_prefix, key, slug)
    if slug is not None:
        raise Refusal("bad_slug", f"{kind} continues the ticket's recorded branch; --slug is for implement")
    ticket = db.get_ticket(ctx.conn, key)
    if ticket is None or not ticket["branch"]:
        raise Refusal("no_branch", f"{key} has no branch in the journal for {kind} to continue; dispatch implement")
    return str(ticket["branch"])


def _guard(ctx: Context, key: str, kind: str, *, planned: Sequence[str] = ()) -> int:
    """Refuse unless a `kind` run for `key` may start now. Returns the attempt number the run would be.

    `planned` holds the tickets a dry run has already dispatched this tick; each counts as a running run.
    """
    running = db.running_runs(ctx.conn)
    for run in running:
        if run["ticket_key"] == key:
            raise Refusal("running", f"run {run['id']} is already working {key}")
    if key in planned:
        raise Refusal("running", f"this dry run already dispatched {key}")
    counts = policy.ticket_attempts(ctx.conn, key)
    cooldown = policy.fix_ci_cooldowns(ctx.conn, ctx.config, datetime.now(UTC)).get(key)
    refused = policy.blocked(key, kind, counts=counts, limit=policy.limits(ctx.config)[kind], cooldown_until=cooldown)
    if refused is not None:
        raise Refusal(*refused)
    limit = ctx.config.capacity.max_workers
    busy = len(running) + len(planned)
    if busy >= limit:
        planned_note = f", counting {len(planned)} this dry run dispatched" if planned else ""
        raise Refusal("capacity", f"{busy} of {limit} workers are running{planned_note}")
    return counts[kind] + 1


def _spawn(
    ctx: Context,
    *,
    tick_id: int,
    key: str,
    kind: str,
    plan: Plan,
    lease: treehouse.Lease | None,
    attempt: int,
    context: str | None,
) -> Started:
    """Render the worker prompt, record the run, and start `canopy _run`. A split run has no lease and no branch."""
    cfg = ctx.config
    values = {
        "KEY": key,
        "TRACKER_PROVIDER": cfg.tracker.provider,
        "TIMEOUT_MINUTES": str(cfg.runtime.worker_timeout_minutes),
        "ATTEMPT": str(attempt),
        "MAX_ATTEMPTS": str(policy.limits(cfg)[kind]),
        "CONTEXT": context or "None.",
        "AUTHORIZED_REPLIERS": ", ".join(f"`{r}`" for r in cfg.trust.authorized_repliers)
        or "none (no reply may instruct you)",
        "LABELS": ", ".join(f"`{label}`" for label in cfg.tracker.labels),
    }
    run_lease = None
    if lease is None or plan.branch is None:
        values |= _split_values(ctx, plan.repos, plan.request)
    else:
        # A stacked run starts from, and opens its PR against, the other ticket's branch; `_run` checks it is on origin.
        base = plan.base if plan.base is not None else lease.base_branch
        run_lease = db.RunLease(lease.path, lease.lease_id, lease.lease_holder, base)
        values |= _branch_values(ctx, key, branch=plan.branch, base=base, stacked_on=plan.base, slot=lease.path)
    try:
        prompt = prompts.render_worker(cfg, kind, values)
    except (OSError, prompts.PromptError) as e:
        raise Refusal("bad_prompt", str(e)) from e

    split = run_lease is None
    run_id = db.insert_run(
        ctx.conn,
        tick_id=tick_id,
        key=key,
        kind=kind,
        lease=run_lease,
        branch=plan.branch,
        runs_dir=runs_dir(ctx),
        repo=None if split else plan.repos[0],
        repos=plan.repos if split else (),
    )
    run = db.get_run(ctx.conn, run_id)
    if run is None:
        raise RuntimeError(f"run {run_id} vanished")
    try:
        logs.write_private(prompt_file(ctx, run_id), prompt)
        # `python -m canopy`, not `canopy` from PATH: the child is this same installation.
        argv = [sys.executable, "-m", "canopy", "_run", str(run_id)]
        pid = ctx.runner.spawn(argv, cwd=ctx.repo_root, log_path=Path(run["log_path"]))
    except (OSError, procs.ProcError) as e:
        db.finish_run(ctx.conn, run_id, "crashed", json.dumps({"harness": f"could not start the worker: {e}"}))
        raise Refusal("spawn_failed", str(e)) from e
    db.claim_run(ctx.conn, run_id, pid)
    slot = None if run_lease is None else run_lease.slot_path
    return Started(run_id=run_id, branch=plan.branch, slot=slot, pid=pid, label=plan.label, repos=plan.repos)


def _branch_values(
    ctx: Context, key: str, *, branch: str, base: str, stacked_on: str | None, slot: Path
) -> dict[str, str]:
    """The placeholders of a run that works on a branch in a leased slot: implement, fix-ci, and resume."""
    cfg = ctx.config
    ticket = db.get_ticket(ctx.conn, key)
    pr_url = ticket["pr_url"] if ticket is not None else None
    return {
        "SLOT": str(slot),
        "BRANCH": branch,
        "BASE": base,
        "STACKING": stacking_note(branch, stacked_on),
        "NEEDS_HUMAN_LABEL": cfg.tracker.needs_human_label,
        "PR_LABEL": cfg.trust.pr_label,
        "PR_URL": str(pr_url) if pr_url else f"not recorded; look up the PR for `{branch}` through the GitHub MCP",
    }


def _split_values(ctx: Context, repos: Sequence[str], request: str | None) -> dict[str, str]:
    """The placeholders of a split run: the comment that asked for it, the workspace it reads, and the repositories."""
    ws = ctx.workspace
    lines: list[str] = []
    for name in repos:
        repo = ws.repo(name)
        summary = f": {repo.summary}" if repo is not None and repo.summary else ""
        path = repo.path if repo is not None else ws.root
        lines.append(f"- `{name}`, cloned at `{path}`{summary}")
    prose = ws.map_prose
    return {
        "REQUEST": f"`{request}`",
        "WORKSPACE": str(ws.root),
        "REPOS": "\n".join(lines),
        "MAP": f"`{prose}`" if prose is not None else "none: this workspace has no MAP.md",
    }


def stacking_note(branch: str, base: str | None) -> str:
    """Return the worker prompt's `{{STACKING}}` paragraph: whether the run builds on another ticket's open PR."""
    if base is None:
        return "This ticket is not stacked on another ticket's branch."
    return (
        f"This ticket is stacked: `{base}` is the branch of another ticket's open PR, and this work builds on it. "
        f"Never push to `{base}` or change its PR. The PR for `{branch}` targets `{base}`, so it shows only this "
        "ticket's commits; its body names the PR it builds on and says it merges after that one."
    )
