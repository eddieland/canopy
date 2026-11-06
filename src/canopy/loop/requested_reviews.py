"""The operator's review requests, derived in shadow (DESIGN §21, §30, §37): what the harness would do with each.

Each tick, beside §7's table (`phases`), the harness derives for each open request what §37's row for it would do:
start its review at the PR's head, wait, or end the request. It reads as the overseer's prompt has it: a PR in no
repository of the workspace, or in one with no clone, ends `unknown_repo`, observed or not; one the `vcs` source left
stale, or never read, waits on it, recorded as stale; a merged or closed one ends so; one whose head has its `done`
review already, in each persona owed one, ends `reviewed`, as the `review-run` tool's refusal ends it; one with a review
running in each persona still owed, or a draft, waits; any other starts. The rows go in `request_derivations`; nothing
the overseer, a worker, or a guard reads changes, and the row stays the overseer's until a measurement shows the
derivation right on it (§37, The evidence gate).

Agreement is computed from those rows and the overseer's decisions about the PR in the same tick, never stored
(`compare`): a start agrees when the overseer asked for the review, whether a guard then refused it or it started, but
for a refusal `reviewed`; a wait when it asked for none and ended nothing, a `review-wait` or no decision at all; an end
when it ended the request for the same reason, or for `reviewed`, asked for the review and was refused `reviewed`. A
request resting on a stale observation is counted apart, never as a disagreement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple, assert_never

from canopy.core import conversation, db, observe, records, review_runs
from canopy.core.vocab import Decider, PrState, RequestAction, ReviewRunStatus
from canopy.loop.review_tools import END_ACTION
from canopy.loop.tools import RAISED, UNNAMED
from canopy.reviews import review_requests
from canopy.reviews import start as review_start

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from canopy.core.context import Context
    from canopy.core.workspace import Repo, Workspace
    from canopy.loop.phases import Verdict

#: The `refused:<guard>` decisions of the `review-end` tool, an end the overseer asked for, not a review.
_END_REFUSALS = frozenset({"refused:not_requested", "refused:bad_reason"})
#: The `refused:<guard>` decisions of the `attention` tool, which may name the PR too: an item, not a review.
_ATTENTION_REFUSALS = frozenset({f"refused:{RAISED}", f"refused:{UNNAMED}"})
#: The refusal that answers a request whose head is reviewed already (`review_requests.answered`).
_REVIEWED = f"refused:{review_requests.REVIEWED}"
#: The end each state of a PR that is not open makes of its request.
_ENDS: Mapping[PrState, str] = {PrState.MERGED: review_requests.MERGED, PrState.CLOSED: review_requests.CLOSED}
#: A PR's URL, `https://HOST/OWNER/REPO/pull/N`, as `conversation.PR_URL_RE` takes it: its host and repository.
_PR_URL_RE = re.compile(r"https://(?P<host>[^\s/]+)/(?P<path>[^\s/]+/[^\s/]+)/pull/[0-9]+/?")
#: A clone URL as `git clone` takes it: https (credentials allowed), ssh://, or scp-style SSH, with an optional `.git`
#: and trailing slash. An SSH URL's port is the SSH server's, so it is not part of the host.
_CLONE_RE = re.compile(
    r"(?:https://(?:[^@/\s]+@)?(?P<https>[^/\s]+)/|ssh://(?:[^@/\s]+@)?(?P<ssh>[^/\s:]+)(?::[0-9]+)?/|"
    r"[^@/\s:]+@(?P<scp>[^/\s:]+):)(?P<path>[^\s/]+/[^\s/]+?)(?:\.git)?/?",
)


@dataclass(frozen=True)
class Derived:
    """What the harness would do with one open request this tick."""

    request_id: int
    pr_url: str
    action: RequestAction
    #: Why it waits, or the end reason it ends with; None for a start.
    reason: str | None = None
    #: The PR's head as a fresh read observed it; None when none did.
    head_sha: str | None = None
    #: The stale or missing observation it rests on, which makes it wait; None when it was derived.
    stale: str | None = None


def derive(ctx: Context, now: datetime) -> list[Derived]:
    """Derive what the harness would do with each open request, from the observations and the journal, at `now`.

    Returns:
        One per open request, oldest first.
    """
    cutoff = now - timedelta(minutes=ctx.config.connect.max_age_minutes)
    return [_derived(ctx, request, cutoff) for request in review_requests.open_requests(ctx.conn)]


def record(conn: sqlite3.Connection, tick_id: int, derived: Iterable[Derived]) -> None:
    """Record what tick `tick_id` derived for the open requests, in one transaction."""
    columns = ("tick_id", "request_id", "pr_url", "action", "reason", "head_sha", "stale")
    rows = [(tick_id, d.request_id, d.pr_url, d.action, d.reason, d.head_sha, d.stale) for d in derived]
    with db.transaction(conn):
        records.insert_rows(records.RequestDerivation, columns).many(conn, rows)


@dataclass(frozen=True)
class Compared:
    """How one request's derivation compares with what the overseer did about its PR in one tick."""

    pr_url: str
    verdict: Verdict
    #: Why it disagrees, or what is stale; None when it agrees.
    why: str | None = None


def compare(conn: sqlite3.Connection, tick_id: int) -> list[Compared]:
    """Compare tick `tick_id`'s derivation of the open requests with the overseer's decisions about their PRs.

    The overseer's are its decisions that name the PR, and its ticket too when the PR is one of the loop's own, and are
    not the harness's: a review it asked for, started or refused, a `review-wait`, and a `review-end`, which a refusal
    of the tool records too. An attention item a guard recorded beside a refusal is the guard's, not a choice.

    Returns:
        One comparison per request the tick derived, by the PR's URL.
    """
    rows = records.select(records.RequestDerivation).where("tick_id = ?", tick_id).order_by("pr_url, id").all(conn)
    moves: dict[str, list[_Move]] = {}
    for d in db.decisions_for_tick(conn, tick_id):
        if d.pr is None or d.decider is Decider.HARNESS:
            continue
        move = _move(d)
        if move is not None:
            moves.setdefault(d.pr, []).append(move)
    return [_compared(row, moves.get(row.pr_url, [])) for row in rows]


class _Move(NamedTuple):
    """One of the overseer's decisions about a requested PR, read as what it means for the request."""

    action: RequestAction
    #: The end reason it names, for an end; None otherwise.
    reason: str | None
    #: How the comparison says it.
    said: str


def _move(decision: records.Decision) -> _Move | None:  # noqa: PLR0911  (one move per kind of decision)
    """What the overseer's `decision` about a requested PR means for the request.

    Returns:
        The move, or None for a decision that is none, such as an attention item a guard recorded.
    """
    action = decision.action
    if action == review_start.DISPATCH_ACTION:
        return _Move(RequestAction.START, None, "review")
    if action == _REVIEWED:
        return _Move(RequestAction.END, review_requests.REVIEWED, "review, refused reviewed")
    if action in _END_REFUSALS:
        return _Move(RequestAction.END, None, f"end, {action.replace(':', ' ')}")
    if action in _ATTENTION_REFUSALS:
        return None
    if action.startswith("refused:"):
        return _Move(RequestAction.START, None, f"review, {action.replace(':', ' ')}")
    if action == END_ACTION:
        # A dry run's rationale says so before the reason: the reason is its last word either way.
        reason = decision.rationale.rpartition(" ")[2]
        return _Move(RequestAction.END, reason, f"end {reason}")
    if action == "wait":
        return _Move(RequestAction.WAIT, None, "wait")
    return None


def _compared(row: records.RequestDerivation, moves: Sequence[_Move]) -> Compared:
    if row.stale is not None:
        return Compared(row.pr_url, "stale", row.stale)
    match row.action:
        case RequestAction.START:
            agrees = any(m.action is RequestAction.START for m in moves)
            derived = f"start at {row.head_sha}"
        case RequestAction.WAIT:
            agrees = all(m.action is RequestAction.WAIT for m in moves)
            derived = f"wait: {row.reason}"
        case RequestAction.END:
            agrees = any(m.action is RequestAction.END and m.reason == row.reason for m in moves)
            derived = f"end {row.reason}"
        case _:
            assert_never(row.action)
    if agrees:
        return Compared(row.pr_url, "agrees")
    decided = ", ".join(m.said for m in moves) or "nothing"
    return Compared(row.pr_url, "disagrees", f"derived {derived}; decided {decided}")


def _derived(ctx: Context, request: records.ReviewRequest, cutoff: datetime) -> Derived:
    """What the harness would do with `request`, reading an observation older than `cutoff` as stale.

    Returns:
        The derivation.
    """
    url = request.pr_url
    if not observe.is_pr_url(url):
        return Derived(request.id, url, RequestAction.WAIT, stale=f"{url} is not a PR's URL, so it is not observed")
    repo = _repo_of(ctx.workspace, url)
    if repo is None or not repo.cloned:
        return Derived(request.id, url, RequestAction.END, review_requests.UNKNOWN_REPO)
    pr = records.select(records.ObservedPr).where("url = ?", url).one(ctx.conn)
    stale = _stale(url, pr, cutoff)
    if stale is not None or pr is None:
        return Derived(request.id, url, RequestAction.WAIT, stale=stale)
    if pr.state in _ENDS:
        return Derived(request.id, url, RequestAction.END, _ENDS[pr.state])
    if pr.head_sha is None:
        return Derived(request.id, url, RequestAction.WAIT, stale=f"{url}'s head not observed")
    return _at_head(ctx.conn, request, pr, pr.head_sha)


def _repo_of(ws: Workspace, url: str) -> Repo | None:
    """The workspace's repository whose clone URL names the same host, owner, and repository as the PR's URL `url`.

    Returns:
        The repository, or None when none does, or `url` is not a PR's.
    """
    pr = _PR_URL_RE.fullmatch(url)
    if pr is None or conversation.PR_URL_RE.fullmatch(url) is None:
        return None
    wanted = (pr["host"].lower(), pr["path"].lower())
    for repo in ws.repos:
        clone = _CLONE_RE.fullmatch(repo.url or "")
        if clone is None:
            continue
        host = clone["https"] or clone["ssh"] or clone["scp"]
        if (host.lower(), clone["path"].lower()) == wanted:
            return repo
    return None


def _stale(url: str, pr: records.ObservedPr | None, cutoff: datetime) -> str | None:
    if pr is None:
        return f"{url} never observed"
    if db.parse_time(pr.observed_at) < cutoff:
        return f"{url} last observed {pr.observed_at}"
    return None


def _at_head(conn: sqlite3.Connection, request: records.ReviewRequest, pr: records.ObservedPr, sha: str) -> Derived:
    """What the harness would do with `request`, whose open PR `pr` a fresh read saw at head `sha`.

    Returns:
        The derivation: an end when the head has its reviews, a wait while they run or on a draft, else a start.
    """
    url = request.pr_url
    runs = review_runs.review_runs_of(conn, url)
    owed = _owed(conn, request, runs, sha)
    if not owed:
        return Derived(request.id, url, RequestAction.END, review_requests.REVIEWED, head_sha=sha)
    if not _startable(runs, owed):
        return Derived(request.id, url, RequestAction.WAIT, "a review of it is running", head_sha=sha)
    if pr.draft:
        return Derived(request.id, url, RequestAction.WAIT, "a draft", head_sha=sha)
    return Derived(request.id, url, RequestAction.START, head_sha=sha)


def _owed(
    conn: sqlite3.Connection,
    request: records.ReviewRequest,
    runs: Sequence[records.ReviewRun],
    sha: str,
) -> list[str | None]:
    """The personas still owed a review of `sha` on `request`, as the `review-run` tool's guards count them.

    A persona the operator chose for the request is owed one until it has a `done` review of `sha`, or one since the
    request was made; with none chosen, the reviewer's own is owed one until any review of `sha` is `done`.

    Returns:
        The personas owed, in the order chosen; `[None]` for the reviewer's own, owed one; none when none is.
    """
    chosen = review_requests.personas_of(conn, request.id)
    if chosen:
        return list(review_start.owed_by(runs, sha, chosen, since=request.created_at))
    done = any(r.sha == sha and r.status is ReviewRunStatus.DONE for r in runs)
    return [] if done else [None]


def _startable(runs: Iterable[records.ReviewRun], owed: Sequence[str | None]) -> bool:
    """Whether a review in one of the `owed` personas may start beside those of the PR running.

    A review running blocks another in its own persona, and every other when it is in one the request did not choose,
    as the reviewer's own is.

    Returns:
        True when one of them is not held by a review running.
    """
    running = [r.persona for r in runs if r.status is ReviewRunStatus.RUNNING]
    chosen = {p for p in owed if p is not None}
    return any(not any(r == p or r not in chosen for r in running) for p in owed)
