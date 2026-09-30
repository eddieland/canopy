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
from canopy.core.workspace import DESKS_DIR
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
JOINT_PR_NOTE = "one per repository, listed under Repositories"
DISPATCH_LOCK = "dispatch.lock"
RUNS_DIR = "runs"


class Refusal(Exception):  # noqa: N818  (a refusal is an outcome the overseer is told about, not an error)
    """A guard refused the dispatch. `guard` names it in the `refused:<guard>` decision.

    `repo` names the unit's repository when the refusal is about one unit of a ticket in a workspace of several, such as
    the unit at its attempt limit; the attention item it raises is then about that unit.
    """

    def __init__(self, guard: str, reason: str, *, repo: str | None = None) -> None:
        """Name the guard and say why it refused."""
        super().__init__(f"{guard}: {reason}")
        self.guard = guard
        self.reason = reason
        self.repo = repo


@dataclass(frozen=True)
class Started:
    """A dispatched run: its branch, the slots it leased, one per repository, and the desk a joint run works in."""

    run_id: int
    branch: str
    slots: tuple[db.RunSlot, ...]
    pid: int
    label: str
    desk: Path | None = None

    @property
    def repos(self) -> tuple[str, ...]:
        """The repositories the run works in."""
        return tuple(s.repo or "" for s in self.slots)


@dataclass(frozen=True)
class Plan:
    """What a run would do: its branch, its base, its queue label, and its repositories.

    `base` is the branch it stacks on if `--base` named one, the label is in its configured spelling, and the
    repositories are the names of the units it covers, in the order the dispatch named them. A run over several is a
    joint run (DESIGN §18).
    """

    branch: str
    base: str | None
    label: str
    repos: tuple[str, ...]

    @property
    def joint(self) -> bool:
        """Whether the run covers several repositories, and so works in a desk."""
        return len(self.repos) > 1


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


def desk_path(ctx: Context, key: str) -> Path:
    """Return where a joint run for `key` links its worktrees: `<workspace>/desks/<KEY>`. One worker per ticket."""
    return ctx.workspace.root / DESKS_DIR / key


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
) -> Started:
    """Check the guards, lease a slot in each repository, record the run, and spawn `canopy _run` for it.

    `implement` works on `<branch_prefix><KEY>-<slug>`, and later dispatches of any kind continue the branch the
    ticket's first implement named, in every repository. `base` stacks the run on another ticket's branch (DESIGN §10);
    without it the run starts from each pool's base branch. `repos` names the units the run covers, one repository each;
    it may be left out only in a workspace of one. A run over several repositories is a joint run (DESIGN §18).

    Raises:
        Refusal: a guard refused, or a slot could not be leased or the worker started. Nothing is left running and
            no slot is left leased: leases are all or nothing.
    """
    plan = _plan(ctx, key, kind, label=label, repos=repos, slug=slug, base=base)

    # One dispatch at a time, so two cannot both pass the capacity check. Held across the leases and the spawn.
    with lock.hold(ctx.state_dir / DISPATCH_LOCK, wait=True):
        attempt = _guard(ctx, key, kind, plan.repos)
        leases = _lease_all(ctx, key, plan.repos)
        try:
            return _spawn(
                ctx, tick_id=tick_id, key=key, kind=kind, plan=plan, leases=leases, attempt=attempt, context=context
            )
        except BaseException:
            _return_all(ctx, leases)
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
) -> Plan:
    """Check the guards a live dispatch would, for a dry run, and return the plan of the run it would start (D036).

    Nothing is leased, recorded, or spawned. The dry-run dispatches this tick already recorded stand in for the runs
    they would have started, so the `running` and `capacity` guards refuse what a live tick would. The leases, prompt,
    and spawn are not tried, so `no_slot`, `bad_prompt`, and `spawn_failed` never appear in a dry run.

    Raises:
        Refusal: a guard refused.
    """
    plan = _plan(ctx, key, kind, label=label, repos=repos, slug=slug, base=base)
    planned = [
        str(d["ticket_key"])
        for d in db.decisions_for_tick(ctx.conn, tick_id)
        if str(d["action"]).startswith("dispatch:") and d["ticket_key"] is not None
    ]
    with lock.hold(ctx.state_dir / DISPATCH_LOCK, wait=True):
        _guard(ctx, key, kind, plan.repos, planned=planned)
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
) -> Plan:
    configured = _check_label(ctx.config.tracker.labels, key, label)
    names = _check_repos(ctx, key, repos)
    branch = _branch(ctx, key, kind, slug, names)
    if base is not None:
        _check_base(ctx.config.trust.branch_prefix, branch, base)
    return Plan(branch=branch, base=base, label=configured, repos=names)


def _check_repos(ctx: Context, key: str, repos: Sequence[str]) -> tuple[str, ...]:
    """Refuse a repository the run cannot work in, and return the names of the ones it will (DESIGN §18).

    In a workspace, every `--repo` must name a repository in the map with a primary clone; naming one the ticket has no
    unit in yet adds that unit. In a workspace of one, `--repo` may be left out, and if given must name the repository.
    A repository named twice is one unit.
    """
    ws = ctx.workspace
    names = ", ".join(r.name for r in ws.repos) or "none yet"
    if not repos:
        if not ws.single:
            raise Refusal(
                "unknown_repo", f"--repo is required in a workspace: name the repositories for {key} ({names})"
            )
        return (ws.repos[0].name,)
    chosen: list[str] = []
    for repo in repos:
        found = ws.repo(repo)
        if found is None:
            raise Refusal("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
        if not found.cloned:
            raise Refusal(
                "unknown_repo", f"{repo} has no clone at {found.path}; the operator runs `canopy workspace sync`"
            )
        if found.name not in chosen:
            chosen.append(found.name)
    return tuple(chosen)


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


def _branch(ctx: Context, key: str, kind: str, slug: str | None, repos: Sequence[str]) -> str:
    """Return the run's branch: the ticket's, fixed by its first implement and the same in every unit (D055)."""
    ticket = db.get_ticket(ctx.conn, key)
    recorded = str(ticket["branch"]) if ticket is not None and ticket["branch"] else None
    if kind == "implement":
        if recorded is None:
            slug = DEFAULT_SLUG if slug is None else slug
            if not valid_slug(slug):
                raise Refusal("bad_slug", f"slug must match {SLUG_RE.pattern}")
            return branch_name(ctx.config.trust.branch_prefix, key, slug)
        if slug is not None and branch_name(ctx.config.trust.branch_prefix, key, slug) != recorded:
            raise Refusal("bad_slug", f"{key}'s branch is {recorded}, named by its first implement; leave out --slug")
        return recorded
    if slug is not None:
        raise Refusal("bad_slug", f"{kind} continues the ticket's recorded branch; --slug is for implement")
    if recorded is None:
        raise Refusal("no_branch", f"{key} has no branch in the journal for {kind} to continue; dispatch implement")
    if not ctx.workspace.single:
        with_branch = {str(u["repo"]) for u in db.units(ctx.conn, key) if u["branch"]}
        for repo in repos:
            if repo not in with_branch:
                raise Refusal(
                    "no_branch",
                    f"{key} has no branch in {repo} for {kind} to continue; dispatch implement with --repo {repo}",
                )
    return recorded


def _guard(ctx: Context, key: str, kind: str, repos: Sequence[str], *, planned: Sequence[str] = ()) -> int:
    """Refuse unless a `kind` run for `key` over `repos` may start now. Returns the attempt number the run would be.

    Attempt limits and the fix-ci cooldown are per unit: the run is refused if any unit it covers is at its limit or
    in its cooldown. `planned` holds the tickets a dry run has already dispatched this tick; each counts as a running
    run.
    """
    running = db.running_runs(ctx.conn)
    for run in running:
        if run["ticket_key"] == key:
            raise Refusal("running", f"run {run['id']} is already working {key}")
    if key in planned:
        raise Refusal("running", f"this dry run already dispatched {key}")
    single = ctx.workspace.single
    counts = policy.attempts(ctx.conn, single=single)
    cooldowns = policy.fix_ci_cooldowns(ctx.conn, ctx.config, datetime.now(UTC), single=single)
    limit = policy.limits(ctx.config)[kind]
    attempt = 1
    for repo in repos:
        unit = policy.unit(key, repo, single=single)
        unit_counts = counts.get(unit, dict.fromkeys(policy.KINDS, 0))
        name = key if single else f"{key} in {repo}"
        refused = policy.blocked(name, kind, counts=unit_counts, limit=limit, cooldown_until=cooldowns.get(unit))
        if refused is not None:
            raise Refusal(*refused, repo=None if single else repo)
        attempt = max(attempt, unit_counts[kind] + 1)
    max_workers = ctx.config.capacity.max_workers
    busy = len(running) + len(planned)
    if busy >= max_workers:
        planned_note = f", counting {len(planned)} this dry run dispatched" if planned else ""
        raise Refusal("capacity", f"{busy} of {max_workers} workers are running{planned_note}")
    return attempt


def _lease_all(ctx: Context, key: str, repos: Sequence[str]) -> list[tuple[str, treehouse.Lease]]:
    """Lease a slot in each repository's pool, or none: a lease that fails returns those already made (DESIGN §18)."""
    leases: list[tuple[str, treehouse.Lease]] = []
    for repo in repos:
        try:
            leases.append((repo, treehouse.lease(ctx.runner, key, pool=ctx.workspace.pool(repo))))
        except treehouse.TreehouseError as e:
            _return_all(ctx, leases)
            where = "" if ctx.workspace.single else f"{repo}: "
            raise Refusal("no_slot", f"{where}{e}") from e
    return leases


def _return_all(ctx: Context, leases: Sequence[tuple[str, treehouse.Lease]]) -> None:
    """Return slots a dispatch leased and cannot use. A return that fails is left to the next tick's reconcile."""
    for repo, lease in leases:
        with contextlib.suppress(treehouse.TreehouseError):
            treehouse.return_slot(
                ctx.runner,
                lease.path,
                lease_id=lease.lease_id,
                lease_holder=lease.lease_holder,
                pool=ctx.workspace.pool(repo),
            )


def _spawn(
    ctx: Context,
    *,
    tick_id: int,
    key: str,
    kind: str,
    plan: Plan,
    leases: Sequence[tuple[str, treehouse.Lease]],
    attempt: int,
    context: str | None,
) -> Started:
    cfg = ctx.config
    branch = plan.branch
    # A stacked run starts from, and opens its PRs against, the other ticket's branch; `_run` checks it is on origin.
    slots = tuple(
        db.RunSlot(
            repo=repo,
            slot_path=lease.path,
            lease_id=lease.lease_id,
            lease_holder=lease.lease_holder,
            base_branch=plan.base if plan.base is not None else lease.base_branch,
        )
        for repo, lease in leases
    )
    desk = desk_path(ctx, key) if plan.joint else None
    prs = _unit_prs(ctx, key)
    bases = {s.base_branch for s in slots}
    repliers = ", ".join(f"`{r}`" for r in cfg.trust.authorized_repliers)
    first = slots[0]
    values = {
        "KEY": key,
        "SLOT": str(desk if desk is not None else first.slot_path),
        "BRANCH": branch,
        "BASE": first.base_branch if len(bases) == 1 else "each repository's base branch, listed under Repositories",
        "STACKING": stacking_note(branch, plan.base),
        "REPOSITORIES": repositories_note(ctx, branch, slots, prs, desk),
        "PRS": json.dumps({s.repo: "<url or null>" for s in slots}, separators=(",", ":")),
        "TRACKER_PROVIDER": cfg.tracker.provider,
        "NEEDS_HUMAN_LABEL": cfg.tracker.needs_human_label,
        "PR_LABEL": cfg.trust.pr_label,
        "TIMEOUT_MINUTES": str(cfg.runtime.worker_timeout_minutes),
        "ATTEMPT": str(attempt),
        "MAX_ATTEMPTS": str(policy.limits(cfg)[kind]),
        "PR_URL": JOINT_PR_NOTE if plan.joint else _pr_note(prs.get(first.repo or ""), branch),
        "CONTEXT": context or "None.",
        "AUTHORIZED_REPLIERS": repliers or "none (no reply may instruct you)",
        "LABELS": ", ".join(f"`{label}`" for label in cfg.tracker.labels),
    }
    # A joint run's worker learns its repositories only from these, so an override without them fails closed.
    required = prompts.REQUIRED_JOINT if plan.joint else ()
    try:
        prompt = prompts.render_worker(cfg, kind, values, required=required)
    except (OSError, prompts.PromptError) as e:
        raise Refusal("bad_prompt", str(e)) from e

    run_id = db.insert_run(
        ctx.conn,
        tick_id=tick_id,
        key=key,
        kind=kind,
        branch=branch,
        slots=slots,
        runs_dir=runs_dir(ctx),
        single=ctx.workspace.single,
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
    return Started(run_id=run_id, branch=branch, slots=slots, pid=pid, label=plan.label, desk=desk)


def _unit_prs(ctx: Context, key: str) -> dict[str, str]:
    """Return the PR the journal recorded for each of `key`'s units, by repository name."""
    found: dict[str, str] = {}
    for u in db.units(ctx.conn, key):
        if u["pr_url"]:
            # A workspace of one's unit may predate its repository's name (migration 0005).
            name = ctx.workspace.repos[0].name if ctx.workspace.single else str(u["repo"])
            found[name] = str(u["pr_url"])
    return found


def _pr_note(pr_url: str | None, branch: str) -> str:
    return pr_url or f"not recorded; look up the PR for `{branch}` through the GitHub MCP"


def repositories_note(
    ctx: Context, branch: str, slots: Sequence[db.RunSlot], prs: dict[str, str], desk: Path | None
) -> str:
    """Return the worker prompt's `{{REPOSITORIES}}` section: each repository the run works in (DESIGN §18)."""
    if desk is None:
        lines = ["This run works in one repository:"]
    else:
        lines = [
            (
                f"This is a joint run over {len(slots)} repositories: one change, held in one context. `{desk}` is a "
                "desk, a directory holding one link per repository's worktree. Work in each repository through its "
                "link, and run git inside it (`git -C <name> ...`). Anything else you leave in the desk is discarded."
            ),
            "",
        ]
    for s in slots:
        name = s.repo or ""
        found = ctx.workspace.repo(name)
        summary = f" {found.summary}" if found is not None and found.summary else ""
        where = desk / name if desk is not None else s.slot_path
        pr = prs.get(name) or f"not recorded; look up the PR for `{branch}` in `{name}` through the GitHub MCP"
        lines.append(f"- `{name}` at `{where}`: branch `{branch}` from `{s.base_branch}`; PR: {pr}.{summary}")
    if desk is not None:
        lines += [
            "",
            (
                "Each repository gets its own PR against its own base branch, with the same title prefix. Each PR's "
                "body links its sibling PRs and says which one merges first. Your ticket comment lists every PR."
            ),
        ]
    return "\n".join(lines)


def stacking_note(branch: str, base: str | None) -> str:
    """Return the worker prompt's `{{STACKING}}` paragraph: whether the run builds on another ticket's open PR."""
    if base is None:
        return "This ticket is not stacked on another ticket's branch."
    return (
        f"This ticket is stacked: `{base}` is the branch of another ticket's open PR, and this work builds on it. "
        f"Never push to `{base}` or change its PR. The PR for `{branch}` targets `{base}`, so it shows only this "
        "ticket's commits; its body names the PR it builds on and says it merges after that one."
    )
