"""`canopy dispatch`: guards, lease, and the detached `canopy _run` (DESIGN §8).

Guards are code and the overseer cannot talk its way past them (DESIGN §4, TRUST_MODEL T3). A refusal is raised as
`Refusal`; the CLI records it as a `refused:<guard>` decision.
"""

from __future__ import annotations

import contextlib
import functools
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import conversation, db, notice, outbox, pools, prompts
from canopy.core.context import DISPATCH_LOCK
from canopy.core.vocab import PoolKind, RunKind, RunStatus
from canopy.core.workspace import DESKS_DIR
from canopy.infra import lock, logs, procs
from canopy.runs import policy

if TYPE_CHECKING:
    from canopy.core.context import Context

# A ticket key reaches branch names, lease holders, paths, and argv (DESIGN §17).
KEY_RE = conversation.KEY_RE
# The branch is `<branch_prefix><KEY>-<slug>`; the slug is the overseer's short name for the work. At most 40
# characters: lowercase words joined by single hyphens.
SLUG_RE = re.compile(r"(?=[a-z0-9-]{1,40}\Z)[a-z0-9]+(?:-[a-z0-9]+)*")
# A stacked run's base is another ticket's branch, `<branch_prefix><KEY>-<slug>`: what follows the prefix is one plain
# ref component, so it reaches git's argv as safely as a key.
BASE_TAIL_RE = re.compile(r"(?=.{1,200}\Z)[A-Za-z0-9][A-Za-z0-9_-]*")
DEFAULT_SLUG = "work"
JOINT_PR_NOTE = "one per repository, listed under Repositories"
# A prompt carries at most this much of `MAP.md`.
MAX_MAP = 20_000
RUNS_DIR = "runs"
# The kind a notice to workers can hold (DESIGN §8): a dispatch of it refuses when the notice moved mid-tick.
FIX_CI = RunKind.FIX_CI


class Refusal(Exception):  # noqa: N818  (a refusal is an outcome the overseer is told about, not an error)
    """A guard refused the dispatch. `guard` names it in the `refused:<guard>` decision.

    `repo` names the unit's repository when the refusal is about one unit of a ticket, such as the unit at its attempt
    limit; the attention item it raises is then about that unit.
    """

    def __init__(self, guard: str, reason: str, *, repo: str | None = None) -> None:
        """Name the guard and say why it refused."""
        super().__init__(f"{guard}: {reason}")
        self.guard = guard
        self.reason = reason
        self.repo = repo


@dataclass(frozen=True)
class Started:
    """A dispatched run: its branch, the slots it leased, one per repository, and the desk a joint run works in.

    `starts` says the run started its ticket privately, under `tracker.private` (DESIGN §22).
    """

    run_id: int
    branch: str
    slots: tuple[db.RunSlot, ...]
    pid: int
    label: str
    desk: Path | None = None
    starts: bool = False

    @property
    def repos(self) -> tuple[str, ...]:
        """The repositories the run works in."""
        return tuple(s.repo or "" for s in self.slots)


@dataclass(frozen=True)
class Leased:
    """A slot a dispatch leased, and the pool that made the lease, which it goes back to (DESIGN §18)."""

    lease: pools.Lease
    pool: PoolKind


@dataclass(frozen=True)
class Plan:
    """What a run would do: its branch, its base, its queue label, and its repositories.

    `base` is the branch it stacks on if `--base` named one, the label is in its configured spelling, and the
    repositories are the names of the units it covers, in the order the dispatch named them. A run over several is a
    joint run (DESIGN §18). A split has no branch (""): it reads the repositories it names and changes none of them. A
    private run works a ticket the operator started; its start record authorizes it, and it has no label (DESIGN §22).
    A run that `starts` the ticket is its first, under `tracker.private`: it is private, and writes the start record.
    """

    branch: str
    base: str | None
    label: str
    repos: tuple[str, ...]
    private: bool = False
    starts: bool = False

    @property
    def joint(self) -> bool:
        """Whether the run covers several repositories, and so works in a desk."""
        return len(self.repos) > 1


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
    review: str | None = None,
) -> Started:
    """Check the guards, lease a slot in each repository, record the run, and spawn `canopy _run` for it.

    `implement` works on `<branch_prefix><KEY>-<slug>`, and later dispatches of any kind continue the branch the
    ticket's first implement named, in every repository. `base` stacks the run on another ticket's branch (DESIGN §10);
    without it the run starts from each pool's base branch. `repos` names the units the run covers, one repository each.
    A run over several repositories is a joint run (DESIGN §18). A `split` names the authorized replier's comment that
    asked for it with `request`, and works no unit. A `resume` for a canopy review's findings carries them in `review`,
    read from the journal (DESIGN §21).

    Returns:
        The run that started: its id, branch, the slots it leased, the worker's pid, and its desk if it is joint.

    Raises:
        Refusal: a guard refused, or a slot could not be leased or the worker started. Nothing is left running and
            no slot is left leased: leases are all or nothing.
    """
    # One dispatch at a time, so two cannot both pass the capacity check. Held from the plan, which reads the ticket's
    # branch, across the leases and the spawn: two first implements must not each name a branch.
    with lock.hold(ctx.state_dir / DISPATCH_LOCK, wait=True):
        _check_notice(ctx, tick_id, kind)
        plan = _plan(ctx, key, kind, label=label, repos=repos, slug=slug, base=base, request=request)
        attempt, limit = _guard(ctx, key, kind, plan.repos)
        leases = _lease_all(ctx, key, plan.repos)
        try:
            return _spawn(
                ctx,
                tick_id=tick_id,
                key=key,
                kind=kind,
                plan=plan,
                leases=leases,
                attempt=attempt,
                limit=limit,
                context=context,
                request=request,
                review=review,
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
    request: str | None = None,
) -> Plan:
    """Check the guards a live dispatch would, for a dry run, and return the plan of the run it would start (D036).

    Nothing is leased, recorded, or spawned. The dry-run dispatches this tick already recorded stand in for the runs
    they would have started, so the `running` and `capacity` guards refuse what a live tick would. The leases, prompt,
    and spawn are not tried, so `no_slot`, `bad_prompt`, and `spawn_failed` never appear in a dry run.

    Returns:
        The plan: the run's branch, base, the queue label it was dispatched under, and its repositories.

    Raises:
        Refusal: a guard refused.
    """
    # Each stands for a run this dry run would have started: a worker run, or a review, which holds a slot too. A
    # review of a PR with no ticket is named by its PR, so it counts toward capacity and blocks no ticket.
    planned = [
        d.ticket_key or f"pr:{d.pr}"
        for d in db.decisions_for_tick(ctx.conn, tick_id)
        if d.action.startswith("dispatch:") and (d.ticket_key is not None or d.pr is not None)
    ]
    with lock.hold(ctx.state_dir / DISPATCH_LOCK, wait=True):
        _check_notice(ctx, tick_id, kind)
        plan = _plan(ctx, key, kind, label=label, repos=repos, slug=slug, base=base, request=request)
        _guard(ctx, key, kind, plan.repos, planned=planned)
    return plan


def runs_dir(ctx: Context) -> Path:
    """Where run logs and rendered worker prompts live, readable only by the operator (TRUST_MODEL T2).

    Returns:
        `<state_dir>/runs`, created if it is missing.
    """
    path = ctx.state_dir / RUNS_DIR
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def prompt_file(ctx: Context, run_id: int) -> Path:
    """Return the file holding run `run_id`'s rendered worker prompt."""
    return runs_dir(ctx) / f"{run_id}.prompt"


def desk_path(ctx: Context, key: str) -> Path:
    """Return where a joint run for `key` links its worktrees: `<workspace>/desks/<KEY>`. One worker per ticket."""
    return ctx.workspace.root / DESKS_DIR / key


def valid_slug(value: str) -> bool:
    """Slugs reach branch names and argv, like keys.

    Returns:
        True if `value` is lowercase words joined by single hyphens, at most 40 characters.
    """
    return SLUG_RE.fullmatch(value) is not None


def branch_name(prefix: str, key: str, slug: str) -> str:
    """Return the branch a ticket's work is pushed to."""
    return f"{prefix}{key}-{slug}"


def repositories_note(
    ctx: Context, branch: str, slots: Sequence[db.RunSlot], prs: Mapping[str, str], desk: Path | None
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


def map_note(ctx: Context) -> str:
    """Return `MAP.md`'s text for a prompt: an agent in a desk may not read files outside it (DESIGN §18)."""
    path = ctx.workspace.map_prose
    if path is None:
        return "None: this workspace has no MAP.md."
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as e:
        return f"None: MAP.md could not be read ({e.strerror})."
    if len(text) > MAX_MAP:
        return f"{text[:MAX_MAP]}\n\n[MAP.md is longer than {MAX_MAP} characters; the rest is left out.]"
    return text or "None: MAP.md is empty."


def split_repositories_note(ctx: Context, slots: Sequence[db.RunSlot], desk: Path | None) -> str:
    """Return a split's `{{REPOSITORIES}}` section: each repository it reads, checked out at its base branch."""
    lines = [
        (
            f"`{desk}` is a desk, a directory holding one link per repository's worktree, each checked out at its base "
            "branch. Read each repository through its link. Nothing you leave in the desk or the worktrees survives."
        ),
        "",
    ]
    for s in slots:
        name = s.repo or ""
        found = ctx.workspace.repo(name)
        summary = f" {found.summary}" if found is not None and found.summary else ""
        where = desk / name if desk is not None else s.slot_path
        lines.append(f"- `{name}` at `{where}`, at `{s.base_branch}`.{summary}")
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


def _plan(
    ctx: Context,
    key: str,
    kind: str,
    *,
    label: str | None,
    repos: Sequence[str],
    slug: str | None,
    base: str | None,
    request: str | None = None,
) -> Plan:
    private = _check_start(ctx, key, kind)
    # A started ticket's start record authorizes it, checked in code; a public ticket's `--label` is a claim (D051).
    configured = "" if private else _check_label(ctx.config.tracker.labels, key, label)
    starts = not private and _starts_privately(ctx, key, kind)
    if kind == policy.SPLIT and request is None:
        raise Refusal(
            "unauthorized",
            f"--request is required for a split: name the authorized replier's comment on {key} that asked for it",
        )
    if kind != policy.SPLIT and request is not None:
        raise Refusal("bad_request", "--request names the comment asking for a split; it is for split only")
    names = _check_repos(ctx, key, repos)
    split_into = db.children_of(ctx.conn, key)
    if split_into:
        # Its children carry the work now; working the parent too would do it twice (DESIGN §18).
        raise Refusal("bad_split", f"{key} was split into {', '.join(split_into)}; dispatch those instead")
    if kind == policy.SPLIT:
        _check_split(ctx, key, names, slug=slug, base=base)
        return Plan(branch="", base=None, label=configured, repos=names)
    _check_child_repo(ctx, key, names)
    branch = _branch(ctx, key, kind, slug, names)
    if base is not None:
        _check_base(ctx.config.trust.branch_prefix, branch, base)
    return Plan(branch=branch, base=base, label=configured, repos=names, private=private or starts, starts=starts)


def _check_start(ctx: Context, key: str, kind: str) -> bool:
    """Return whether `key` is a private ticket, refusing a dispatch its start record forbids (DESIGN §22).

    A started ticket is private whatever labels it carries. A stopped one is dispatched by nothing until the operator
    starts it again, and a split, which creates tickets in the tracker, is never run for a private one.

    Returns:
        True if the ticket has a start record and is started, False if it has none.

    Raises:
        Refusal: the ticket was stopped (`stopped`), a split was asked for a private ticket (`private`), or no tracker
            tools are known for a private worker (`no_read_tools`).
    """
    record = conversation.start_of(ctx.conn, key)
    if record is None:
        return False
    if not conversation.is_started(record):
        raise Refusal("stopped", f"{key} was stopped with `canopy stop`; nothing dispatches it until `canopy start`")
    if kind == policy.SPLIT:
        raise Refusal(
            "private", f"{key} is private: a split creates tickets in the tracker, which a private ticket never"
        )
    if ctx.config.tracker.tools() is None:
        raise Refusal(
            "no_read_tools", "no tracker tools are known for a private worker; set tracker.mcp_server and read_tools"
        )
    return True


def _starts_privately(ctx: Context, key: str, kind: str) -> bool:
    """Return whether this dispatch starts a labeled ticket privately, under `tracker.private` (DESIGN §22).

    Only a ticket canopy never ran is started so: one already worked in public keeps its conversation on the tracker.
    A split works no unit and leaves the ticket public; its children are started by their own first dispatch.

    Returns:
        True if the run will be private and write the ticket's start record, False if it stays public.

    Raises:
        Refusal: no tracker tools are known for a private worker (`no_read_tools`).
    """
    if not ctx.config.tracker.private or kind == policy.SPLIT or db.has_runs(ctx.conn, key):
        return False
    if ctx.config.tracker.tools() is None:
        raise Refusal(
            "no_read_tools",
            "tracker.private is set, but no tracker tools are known for a private worker; set tracker.mcp_server and "
            "read_tools",
        )
    return True


def _check_label(labels: Sequence[str], key: str, label: str | None) -> str:
    """Refuse a dispatch that does not name one of the operator's queue labels (DESIGN §8, D051).

    canopy cannot read the tracker, so this cannot prove the label is on the ticket. It makes the overseer name the
    label it read for every dispatch, a claim recorded with the decision, instead of a check it can skip. Labels match
    case-insensitively, as GitHub's do; the configured spelling is returned. The refusal never lists the configured
    labels, so an overseer cannot copy one from it without reading the ticket.

    Returns:
        The configured label `label` names.

    Raises:
        Refusal: `unauthorized`, when no label is named or it is not a configured queue label.
    """
    if label is None:
        raise Refusal("unauthorized", f"--label is required: name the queue label you read on {key}")
    for configured in labels:
        if configured.casefold() == label.casefold():
            return configured
    raise Refusal("unauthorized", f"{label!r} is not a configured queue label; name the one you read on {key}")


def _check_repos(ctx: Context, key: str, repos: Sequence[str]) -> tuple[str, ...]:
    """Refuse a repository the run cannot work in, and return the names of the ones it will (DESIGN §18).

    Every `--repo` must name a repository in the map with a primary clone; naming one the ticket has no unit in yet adds
    that unit. A repository named twice is one unit.

    Returns:
        Each repository's name once, in the order first named.

    Raises:
        Refusal: `unknown_repo`, when none is named, or one is not in the map or has no primary clone.
    """
    ws = ctx.workspace
    names = ", ".join(r.name for r in ws.repos) or "none yet"
    if not repos:
        raise Refusal("unknown_repo", f"--repo is required: name the repositories for {key} ({names})")
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


def _check_split(ctx: Context, key: str, repos: Sequence[str], *, slug: str | None, base: str | None) -> None:
    """Refuse a split that cannot make one child per repository from a ticket nobody has started (DESIGN §18).

    Raises:
        Refusal: a slug (`bad_slug`) or a base (`bad_base`) is given, or (`bad_split`) fewer than two repositories are
            named, the ticket is itself a split's child, or it already has a branch.
    """
    if slug is not None:
        raise Refusal("bad_slug", "a split creates tickets and names no branch; leave out --slug")
    if base is not None:
        raise Refusal("bad_base", "a split creates tickets and starts from no branch; leave out --base")
    if len(repos) < 2:  # noqa: PLR2004
        raise Refusal("bad_split", f"a split names every repository {key} covers, at least two; name each with --repo")
    child = db.split_child(ctx.conn, key)
    if child is not None:
        raise Refusal("bad_split", f"{key} was created by splitting {child['parent_key']}; it is not split again")
    ticket = db.get_ticket(ctx.conn, key)
    if ticket is not None and ticket["branch"]:
        raise Refusal("bad_split", f"{key} already has work on {ticket['branch']}; a started ticket is not split")


def _check_child_repo(ctx: Context, key: str, repos: Sequence[str]) -> None:
    """Refuse any repository for a split's child other than the one the split recorded for it (DESIGN §18).

    Raises:
        Refusal: `unknown_repo`, when `key` is a split's child and `repos` is not just its recorded repository.
    """
    child = db.split_child(ctx.conn, key)
    if child is None:
        return
    recorded = str(child["repo"])
    if tuple(repos) != (recorded,):
        raise Refusal(
            "unknown_repo",
            f"{key} was split from {child['parent_key']} to cover {recorded} only; dispatch it with --repo {recorded}",
        )


def _branch(ctx: Context, key: str, kind: str, slug: str | None, repos: Sequence[str]) -> str:
    """Return the run's branch: the ticket's, fixed by its first implement and the same in every unit (D058).

    Raises:
        Refusal: a slug is invalid, names another branch than the recorded one, or is given for a kind other than
            implement (`bad_slug`); or a kind other than implement has no recorded branch to continue, for the ticket
            or in one of `repos` (`no_branch`).
    """
    ticket = db.get_ticket(ctx.conn, key)
    recorded = str(ticket["branch"]) if ticket is not None and ticket["branch"] else None
    if kind == RunKind.IMPLEMENT:
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
    with_branch = {str(u["repo"]) for u in db.units(ctx.conn, key) if u["branch"]}
    for repo in repos:
        if repo not in with_branch:
            raise Refusal(
                "no_branch",
                f"{key} has no branch in {repo} for {kind} to continue; dispatch implement with --repo {repo}",
            )
    return recorded


def _check_base(prefix: str, branch: str, base: str) -> None:
    """Refuse a base that is not another ticket's agent branch, so a PR cannot target a release branch (DESIGN §10).

    Raises:
        Refusal: `bad_base`, when `base` is not the branch prefix and one plain ref component, or is `branch` itself.
    """
    tail = base.removeprefix(prefix)
    if tail == base or BASE_TAIL_RE.fullmatch(tail) is None:
        raise Refusal("bad_base", f"--base must be another ticket's branch, {prefix}<KEY>-<slug>")
    if base == branch:
        raise Refusal("bad_base", f"{branch} cannot be stacked on itself")


def _check_notice(ctx: Context, tick_id: int, kind: str) -> None:
    """Refuse a `fix-ci` when the operator set or cleared a notice to workers after this tick read the journal.

    The overseer decided from a state block without it, and a `fix-ci` at a failure the notice explains spends an
    attempt that never resets (D030); the loop's next tick, which the notice wakes, decides with it (DESIGN §8).

    Raises:
        Refusal: (`notice_changed`) the notice moved after the tick's read.
    """
    if kind != FIX_CI:
        return
    tick = db.get_tick(ctx.conn, tick_id)
    read = tick["read_at"] if tick is not None else None
    if read is not None and notice.moved_after(ctx.conn, str(read)):
        raise Refusal(
            "notice_changed",
            "the operator set or cleared a notice to workers after this tick read the journal; the next tick decides "
            "fix-ci with it",
        )


def _guard(ctx: Context, key: str, kind: str, repos: Sequence[str], *, planned: Sequence[str] = ()) -> tuple[int, int]:
    """Refuse unless a `kind` run for `key` over `repos` may start now. Returns the run's attempt number and limit.

    Attempt limits and the fix-ci cooldown are per unit: the run is refused if any unit it covers is at its limit or
    in its cooldown. A unit's limit is the policy's plus the runs the operator granted it (DESIGN §22). The run's
    attempt number and limit are those of the unit with the most runs of the kind. `planned` holds the tickets a dry
    run has already dispatched this tick; each counts as a running run.

    Returns:
        The run's attempt number and attempt limit.

    Raises:
        Refusal: a run is already working `key` or the dry run dispatched it (`running`), a unit or a split is at its
            attempt limit (`attempt_limit`) or a unit in its fix-ci cooldown (`cooldown`), or the workers are at
            capacity (`capacity`). A refusal about one unit names its repository.
    """
    running = db.running_runs(ctx.conn, "runs")
    for run in running:
        if run["ticket_key"] == key:
            raise Refusal("running", f"run {run['id']} is already working {key}")
    if key in planned:
        raise Refusal("running", f"this dry run already dispatched {key}")
    if kind == policy.SPLIT:
        # A split is the ticket's, not a unit's: its count is per ticket.
        done = policy.split_attempts(ctx.conn).get(key, 0)
        split_limit = policy.limits(ctx.config)[kind]
        refused = policy.blocked(key, kind, counts={kind: done}, limit=split_limit, cooldown_until=None)
        if refused is not None:
            raise Refusal(*refused)
        _check_capacity(ctx, running, planned)
        return done + 1, split_limit
    counts = policy.attempts(ctx.conn)
    granted = policy.grants(ctx.conn)
    cooldowns = policy.fix_ci_cooldowns(ctx.conn, ctx.config, datetime.now(UTC))
    # (attempt, -limit) per unit: the unit with the most runs sets both, and of those, the one with the lowest limit.
    numbered: list[tuple[int, int]] = []
    for repo in repos:
        unit = policy.unit(key, repo)
        unit_counts = counts.get(unit, dict.fromkeys(policy.KINDS, 0))
        limit = policy.unit_limits(ctx.config, granted.get(unit, {}))[kind]
        refused = policy.blocked(
            f"{key} in {repo}", kind, counts=unit_counts, limit=limit, cooldown_until=cooldowns.get(unit)
        )
        if refused is not None:
            raise Refusal(*refused, repo=repo)
        numbered.append((unit_counts[kind] + 1, -limit))
    _check_capacity(ctx, running, planned)
    attempt, negative_limit = max(numbered, default=(1, -policy.limits(ctx.config)[kind]))
    return attempt, -negative_limit


def _check_capacity(ctx: Context, running: Sequence[object], planned: Sequence[str]) -> None:
    """Refuse when `max_workers` runs and review runs are running: a review holds a slot too (DESIGN §21).

    Raises:
        Refusal: `capacity`, when running runs, review runs, and those in `planned` number `max_workers` or more.
    """
    max_workers = ctx.config.capacity.max_workers
    busy = len(running) + len(db.running_runs(ctx.conn, "review_runs")) + len(planned)
    if busy >= max_workers:
        planned_note = f", counting {len(planned)} this dry run dispatched" if planned else ""
        raise Refusal("capacity", f"{busy} of {max_workers} workers are running{planned_note}")


def _lease_all(ctx: Context, key: str, repos: Sequence[str]) -> list[tuple[str, Leased]]:
    """Lease a slot in each repository's pool, or none: a lease that fails returns those already made (DESIGN §18).

    Returns:
        Each repository's name and its lease, with the pool that made it, in the order of `repos`.

    Raises:
        Refusal: `no_slot`, when a repository's pool could not lease a slot.
    """
    kind = ctx.config.pools.backend
    leases: list[tuple[str, Leased]] = []
    for repo in repos:
        try:
            leases.append((repo, Leased(ctx.pool(repo).lease(key), kind)))
        except pools.PoolError as e:
            _return_all(ctx, leases)
            raise Refusal("no_slot", f"{repo}: {e}") from e
    return leases


def _return_all(ctx: Context, leases: Iterable[tuple[str, Leased]]) -> None:
    """Return slots a dispatch leased and cannot use. A return that fails is left to the next tick's reconcile."""
    for repo, leased in leases:
        lease = leased.lease
        with contextlib.suppress(pools.PoolError):
            ctx.pool_of(leased.pool, repo).return_slot(
                lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder
            )


def _spawn(
    ctx: Context,
    *,
    tick_id: int,
    key: str,
    kind: str,
    plan: Plan,
    leases: Iterable[tuple[str, Leased]],
    attempt: int,
    limit: int,
    context: str | None,
    request: str | None = None,
    review: str | None = None,
) -> Started:
    cfg = ctx.config
    branch = plan.branch
    # A stacked run starts from, and opens its PRs against, the other ticket's branch; `_run` checks it is on origin.
    slots = tuple(
        db.RunSlot(
            repo=repo,
            slot_path=leased.lease.path,
            lease_id=leased.lease.lease_id,
            lease_holder=leased.lease.lease_holder,
            base_branch=plan.base if plan.base is not None else leased.lease.base_branch,
            pool=leased.pool,
        )
        for repo, leased in leases
    )
    desk = desk_path(ctx, key) if plan.joint else None
    split = kind == policy.SPLIT
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
        "REPOSITORIES": split_repositories_note(ctx, slots, desk)
        if split
        else repositories_note(ctx, branch, slots, prs, desk),
        "PRS": json.dumps({s.repo: "<url or null>" for s in slots}, separators=(",", ":")),
        "TRACKER_PROVIDER": cfg.tracker.provider,
        "NEEDS_HUMAN_LABEL": cfg.tracker.needs_human_label,
        "TIMEOUT_MINUTES": str(cfg.runtime.worker_timeout_minutes),
        "ATTEMPT": str(attempt),
        "MAX_ATTEMPTS": str(limit),
        "PR_URL": JOINT_PR_NOTE if plan.joint else _pr_note(prs.get(first.repo or ""), branch),
        "CONTEXT": context or "None.",
        "REVIEW_FINDINGS": review or "None.",
        "AUTHORIZED_REPLIERS": repliers or "none (no reply may instruct you)",
        "TRUSTED_REVIEWERS": prompts.trusted_reviewers(cfg.trust.trusted_reviewers),
        "LABELS": ", ".join(f"`{label}`" for label in cfg.tracker.labels),
        "REQUEST": request or "",
        "MAP": map_note(ctx),
        "WORKER_COMMENT": prompts.worker_comment(cfg.trust.comment_prefix, cfg.trust.comment_suffix),
        "MARK_COMMENTS": prompts.mark_comments(cfg.trust.comment_prefix, cfg.trust.comment_suffix),
        "OPEN_PR": prompts.open_pr(cfg.runtime.pr_skill),
    }
    # A joint run's worker learns its repositories only from these, so an override without them fails closed. A
    # splitter's own check of who asked for the split needs the request.
    if split:
        required: tuple[str, ...] = prompts.REQUIRED_SPLIT
    else:
        required = prompts.REQUIRED_JOINT if plan.joint else ()
    if plan.private:
        values["CONVERSATION"] = conversation.prompt_conversation(ctx.conn, key)
    else:
        values["OPERATOR_MESSAGES"] = conversation.prompt_operator_messages(ctx.conn, key)
        values["PREVIOUS_RUNS"] = conversation.prompt_previous_runs(ctx.conn, key)
        if not split and conversation.has_operator_messages(ctx.conn, key):
            required = (*required, *prompts.REQUIRED_OPERATOR)
    if review is not None:
        required = (*required, *prompts.REQUIRED_REVIEW)
    try:
        prompt = prompts.render_worker(
            cfg, kind, values, required=required, private=plan.private, notice=notice.for_prompt(ctx.conn)
        )
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
        works_units=not split,
        started=outbox.run_started(cfg, key=key, kind=kind, branch=branch, attempt=attempt, limit=limit),
        private=plan.private,
        check=functools.partial(_check_start_again, ctx, key, plan),
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
        note = json.dumps({"harness": f"could not start the worker: {e}"})
        conversation.close_run(ctx.conn, cfg, run, RunStatus.CRASHED, note)
        raise Refusal("spawn_failed", str(e)) from e
    db.claim_run(ctx.conn, "runs", run_id, pid)
    return Started(run_id=run_id, branch=branch, slots=slots, pid=pid, label=plan.label, desk=desk, starts=plan.starts)


def _check_start_again(ctx: Context, key: str, plan: Plan) -> None:
    """Check the start record again inside the run's insert, writing it for a run that starts the ticket (DESIGN §22).

    `canopy stop` marks the record in a transaction of its own, so whichever commits first wins.

    Raises:
        Refusal: the ticket was stopped (`stopped`), or started privately (`private`), since the dispatch was planned.
    """
    if plan.starts and conversation.start_of(ctx.conn, key) is None:
        db.set_start(ctx.conn, conversation.TICKET, key, status="started", channel=conversation.LABEL)
    if plan.private != conversation.is_started(conversation.start_of(ctx.conn, key)):
        what = "was stopped" if plan.private else "was started privately"
        raise Refusal("stopped" if plan.private else "private", f"{key} {what} while this dispatch was planned")


def _unit_prs(ctx: Context, key: str) -> dict[str, str]:
    """Return the PR the journal recorded for each of `key`'s units, by repository name."""
    found: dict[str, str] = {}
    for u in db.units(ctx.conn, key):
        if u["pr_url"]:
            found[str(u["repo"])] = str(u["pr_url"])
    return found


def _pr_note(pr_url: str | None, branch: str) -> str:
    return pr_url or f"not recorded; look up the PR for `{branch}` through the GitHub MCP"
