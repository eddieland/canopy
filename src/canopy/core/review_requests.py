"""Review requests (DESIGN §21, ROADMAP M42): the operator asks canopy to review a PR the loop does not own.

A request is a journal fact, like a start record (§22): the PR's URL, and when and through which channel it was made
and ended. It authorizes one review of its PR at its head, as `review.query` would, so only the operator makes or stops
one: every channel (`canopy start URL --review`, `canopy stop URL`, and the web UI) calls the functions here, and each
refuses inside canopy's own ticks and runs. The overseer names the PR's repository when it runs the review, as it does
for `review.query`'s matches. The harness ends a request when a review of its PR ends `done` (`db.finish_run`),
or when `canopy review run` refuses `reviewed` for it (`answered`); the overseer ends one whose PR merged or closed
first, or is in none of the workspace's repositories (`end`). At most one request per PR is open. A request may carry
the operator's notes, which the reviewer's prompt carries (`reviews.start`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import contract, conversation, db, records, sql

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Config
    from canopy.core.review_result import ReviewResult

#: `review_runs.purpose` of a review that answers the operator's request, rather than one the loop started on its own.
PURPOSE = "request"

# Why a request ended: a `done` review of its PR; the PR merged or closed before one, or is in none of the
# workspace's repositories (the overseer's reading); or the operator stopped it.
REVIEWED = "reviewed"
MERGED = "merged"
CLOSED = "closed"
UNKNOWN_REPO = "unknown_repo"
STOPPED = "stopped"
# The reasons the overseer may give `canopy review end`: what it read on the PR, never the operator's own.
OVERSEER_REASONS = (MERGED, CLOSED, UNKNOWN_REPO)
#: The most characters a request's notes may hold, after stripping: the operator's bound on what they write (§22).
MAX_NOTES = conversation.MAX_OPERATOR


def reviews_on(conn: sqlite3.Connection, config: Config) -> bool:
    """Whether reviews run at all: `max_reviews` above 0, and `agent_prs`, `query`, or an open request (DESIGN §21).

    Returns:
        True when the config turns reviews on, or `max_reviews` is above 0 and a request is open.
    """
    return config.reviews_on or (config.capacity.max_reviews > 0 and bool(open_requests(conn)))


def open_requests(conn: sqlite3.Connection) -> list[records.ReviewRequest]:
    """Return the open requests, oldest first."""
    return records.fetch_all(
        conn, records.ReviewRequest, sql.select("*").from_("review_requests").where("ended_at IS NULL").order_by("id")
    )


def waiting_requests(conn: sqlite3.Connection) -> list[records.ReviewRequest]:
    """Return the open requests no review of their PR is running for, newest first: each waits on a tick to start one.

    A request whose review ended any way but `done` waits again, since only a `done` review ends it.
    """
    return records.fetch_all(
        conn,
        records.ReviewRequest,
        sql.select("*")
        .from_("review_requests q")
        .where("q.ended_at IS NULL")
        .where("NOT EXISTS (SELECT 1 FROM review_runs r WHERE r.pr_url = q.pr_url AND r.status = 'running')")
        .order_by("q.id DESC"),
    )


def open_request(conn: sqlite3.Connection, pr_url: str) -> records.ReviewRequest | None:
    """Return the PR's open request, or None when it has none."""
    return records.fetch_one(
        conn,
        records.ReviewRequest,
        sql.select("*").from_("review_requests").where("pr_url = ? AND ended_at IS NULL", pr_url),
    )


def latest_request(conn: sqlite3.Connection, pr_url: str) -> records.ReviewRequest | None:
    """Return the PR's latest request, open or ended, or None when the operator never asked for it to be reviewed."""
    return records.fetch_one(
        conn,
        records.ReviewRequest,
        sql.select("*").from_("review_requests").where("pr_url = ?", pr_url).order_by("id DESC").limit(1),
    )


@dataclass(frozen=True)
class Requested:
    """What `request` did: the open request, and whether it was already open."""

    request: records.ReviewRequest
    already: bool


def request(
    conn: sqlite3.Connection, config: Config, ref: conversation.Ref, *, channel: str, notes: str | None = None
) -> Requested:
    """Ask for the PR `ref` names to be reviewed at its head, through `channel`, with `notes`. Operator only.

    `notes` is what the operator wants the reviewer to know, stripped; blank is none. On a request already open, notes
    replace its own, and none leaves them as they were. A review already running keeps the prompt it started with.

    Returns:
        The PR's open request, and whether one was already open.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `reviews_off` when `capacity.max_reviews` is 0;
            `bad_notes` for notes over `MAX_NOTES` characters; `bad_pr` for a subject that is not a PR's plain https://
            URL; `loop_pr` for a PR a ticket's run pushed to, which `review.agent_prs` covers.
        RuntimeError: the request was not there to read back once written.
    """
    conversation.check_operator()
    if config.capacity.max_reviews <= 0:
        raise conversation.Refused("reviews_off", "capacity.max_reviews is 0, so no review can run")
    said = (notes or "").strip() or None
    if said is not None and len(said) > MAX_NOTES:
        raise conversation.Refused("bad_notes", f"the notes are {len(said)} characters; the most is {MAX_NOTES}")
    url = _pr_url(ref)
    if sql.execute(conn, sql.select("1").from_("ticket_units").where("pr_url = ?", url)).fetchone() is not None:
        raise conversation.Refused(
            "loop_pr",
            f"{url} is one of the loop's own PRs, a ticket's unit's; `review.agent_prs` reviews those",
        )
    with db.transaction(conn):
        found = open_request(conn, url)
        if found is not None and said is not None:
            sql.execute(conn, sql.update("review_requests").set(notes=said).where("id = ?", found.id))
            found = open_request(conn, url)
        if found is not None:
            return Requested(request=found, already=True)
        sql.execute(conn, sql.insert("review_requests", pr_url=url, created_at=db.now(), channel=channel, notes=said))
        made = open_request(conn, url)
    if made is None:
        raise RuntimeError(f"the request for {url} vanished")
    return Requested(request=made, already=False)


@dataclass(frozen=True)
class Stopped:
    """What `stop` did: the request it ended, and a review of the PR still running, which finishes."""

    request: records.ReviewRequest
    running: records.ReviewRun | None


def stop(conn: sqlite3.Connection, ref: conversation.Ref) -> Stopped:
    """End the open request on the PR `ref` names, as `stopped`. Operator only.

    A review of the PR already running finishes, and its findings stay in the journal.

    Returns:
        The request as it was before it ended, and the PR's running review run, if one is.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `bad_pr` for a subject that is not a PR's URL,
            and `not_requested` for a PR with no open request.
    """
    conversation.check_operator()
    url = _pr_url(ref)
    with db.transaction(conn):
        found = open_request(conn, url)
        if found is None:
            raise conversation.Refused("not_requested", f"{url} has no open review request to stop")
        _end(conn, found.id, STOPPED)
        running = records.fetch_one(
            conn,
            records.ReviewRun,
            sql.select("*")
            .from_("review_runs")
            .where("pr_url = ? AND status = 'running'", url)
            .order_by("id DESC")
            .limit(1),
        )
    return Stopped(request=found, running=running)


def end(conn: sqlite3.Connection, pr_url: str, reason: str, *, dry_run: bool = False) -> records.ReviewRequest:
    """End the open request on `pr_url`, before a review of it: the overseer's, in a tick.

    `reason` is what the overseer read: the PR `merged` or `closed`, or is in none of the workspace's repositories
    (`unknown_repo`), so no review of it can run here.

    A steered overseer could end one early; that costs a review, never adds one, and the PR's page shows the reason.
    A dry run checks the same and ends nothing (D036).

    Returns:
        The request as it was before it ended.

    Raises:
        Refused: `bad_reason` for a reason other than `merged`, `closed`, or `unknown_repo`, and `not_requested` for a
            PR with no open request.
    """
    if reason not in OVERSEER_REASONS:
        raise conversation.Refused("bad_reason", f"--reason must be one of {', '.join(OVERSEER_REASONS)}")
    with db.transaction(conn):
        found = open_request(conn, pr_url)
        if found is None:
            raise conversation.Refused("not_requested", f"{pr_url[: conversation.MAX_PR_URL]} has no open request")
        if not dry_run:
            _end(conn, found.id, reason)
    return found


def answered(conn: sqlite3.Connection, pr_url: str) -> bool:
    """End the PR's open request as `reviewed`: a `done` review of the head the overseer read already exists.

    `canopy review run` calls it when it refuses `reviewed`, so a request made after its PR's head was reviewed, which
    no new review will end, ends with the review that answers it.

    Returns:
        True if this call ended a request.
    """
    with db.transaction(conn):
        cur = sql.execute(
            conn,
            sql.update("review_requests")
            .set(ended_at=db.now(), end_reason=REVIEWED)
            .where("pr_url = ? AND ended_at IS NULL", pr_url),
        )
    return cur.rowcount == 1


def has_news(run: records.ReviewRun, found: ReviewResult | None) -> bool:
    """Whether review run `run`, which stored `found`, has a result for the operator to read (DESIGN §22).

    It has once it ended with a verdict that found something, or with any verdict when the operator asked for it: a
    clean review the loop started on its own tells them nothing they need to read.

    Returns:
        True when the result is one to bring to the operator.
    """
    if run.ended_at is None or found is None or found.verdict is None:
        return False
    return found.verdict == "findings" or run.purpose == PURPOSE


def _end(conn: sqlite3.Connection, request_id: int, reason: str) -> None:
    sql.execute(
        conn,
        sql.update("review_requests")
        .set(ended_at=db.now(), end_reason=reason)
        .where("id = ? AND ended_at IS NULL", request_id),
    )


def _pr_url(ref: conversation.Ref) -> str:
    """The PR's URL, as review runs record it.

    Returns:
        `ref`'s id, a PR's plain https:// URL.

    Raises:
        Refused: (`bad_pr`) `ref` is not a PR, or names one as `REPO#N`, which a review run cannot fetch by.
    """
    if ref.kind != conversation.PR or not contract.plain_url(ref.id, conversation.MAX_PR_URL):
        raise conversation.Refused(
            "bad_pr", f"name the PR by its plain https:// URL, as `canopy review show` does, not {ref}"
        )
    return ref.id
