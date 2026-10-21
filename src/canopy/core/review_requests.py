"""Review requests (DESIGN §21, ROADMAP M42): the operator asks canopy to review a PR the loop does not own.

A request is a journal fact, like a start record (§22): the PR's URL, and when and through which channel it was made
and ended. It authorizes one review of its PR at its head, as `review.query` would, so only the operator makes or stops
one: every channel (`canopy start URL --review`, `canopy stop URL`, and the web UI) calls the functions here, and each
refuses inside canopy's own ticks and runs. The overseer names the PR's repository when it runs the review, as it does
for `review.query`'s matches. The harness ends a request when a review of its PR ends `done` (`db.finish_run`),
or when `canopy review run` refuses `reviewed` for it (`answered`); the overseer ends one whose PR merged or closed
first, or is in none of the workspace's repositories (`end`). At most one request per PR is open. A request may carry
the operator's notes, which the reviewer's prompt carries (`reviews.start`), and the persona its review is written in,
in place of `[personas] reviewer` (DESIGN §31), which only the operator chooses (`request`, `choose_persona`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import contract, conversation, db, personas, records, sql

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
        conn,
        records.ReviewRequest,
        sql.select("*").from_("review_requests").where("ended_at IS NULL").order_by("id"),
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


def persona_of(conn: sqlite3.Connection, request_id: int) -> str | None:
    """Return the persona the operator chose for request `request_id`'s review, or None when they chose none."""
    found = records.fetch_one(
        conn,
        records.ReviewRequestPersona,
        sql.select("*").from_("review_request_personas").where("request_id = ?", request_id),
    )
    return found.persona if found is not None else None


def persona_for(conn: sqlite3.Connection, config: Config, pr_url: str) -> personas.Persona | None:
    """Return the persona the operator chose for the review the PR's open request asks for, read now (DESIGN §31).

    Returns:
        The persona, read from its file, or None when the PR has no open request or its request chose none, and its
        review gets `[personas] reviewer`.

    Raises:
        PersonaError: (`MISSING`) the name has no file, or (`BAD`) its file is one canopy would not put in a prompt;
            never fallen back from.
    """
    found = open_request(conn, pr_url)
    name = persona_of(conn, found.id) if found is not None else None
    if name is None:
        return None
    try:
        return personas.load(config, name)
    except personas.PersonaError as e:
        clear = f"; or clear it: canopy persona {pr_url} --clear"
        raise personas.PersonaError(e.guard, f"{pr_url}'s review request: {e.reason}{clear}") from e


@dataclass(frozen=True)
class Requested:
    """What `request` did: the open request, and whether it was already open."""

    request: records.ReviewRequest
    already: bool


def request(
    conn: sqlite3.Connection,
    config: Config,
    ref: conversation.Ref,
    *,
    channel: str,
    notes: str | None = None,
    persona: str | None = None,
) -> Requested:
    """Ask for the PR `ref` names to be reviewed at its head, through `channel`, with `notes`. Operator only.

    `notes` is what the operator wants the reviewer to know, stripped; blank is none. `persona` is the persona its
    review is written in, in place of `[personas] reviewer`. On a request already open, notes or a persona replace its
    own, and none leaves them as they were. A review already running keeps the prompt it started with.

    Returns:
        The PR's open request, and whether one was already open.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `reviews_off` when `capacity.max_reviews` is 0;
            `bad_notes` for notes over `MAX_NOTES` characters; `unknown_persona` or `bad_persona` for a persona a run
            could not use; `bad_pr` for a subject that is not a PR's plain https:// URL; `loop_pr` for a PR a ticket's
            run pushed to, which `review.agent_prs` covers.
        RuntimeError: the request was not there to read back once written.
    """
    conversation.check_operator()
    if config.capacity.max_reviews <= 0:
        raise conversation.Refused("reviews_off", "capacity.max_reviews is 0, so no review can run")
    said = (notes or "").strip() or None
    if said is not None and len(said) > MAX_NOTES:
        raise conversation.Refused("bad_notes", f"the notes are {len(said)} characters; the most is {MAX_NOTES}")
    if persona is not None:
        personas.check(config, persona)
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
            if persona is not None:
                _set_persona(conn, found.id, persona)
            return Requested(request=found, already=True)
        sql.execute(conn, sql.insert("review_requests", pr_url=url, created_at=db.now(), channel=channel, notes=said))
        made = open_request(conn, url)
        if made is not None and persona is not None:
            _set_persona(conn, made.id, persona)
    if made is None:
        raise RuntimeError(f"the request for {url} vanished")
    return Requested(request=made, already=False)


def choose_persona(
    conn: sqlite3.Connection,
    config: Config,
    ref: conversation.Ref,
    name: str | None,
) -> records.ReviewRequest:
    """Set the persona the PR's open request is reviewed in, or clear it with None (DESIGN §31). Operator only.

    It covers the request's review from the next that starts; one already running keeps the prompt it started with.

    Returns:
        The PR's open request.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `unknown_persona` or `bad_persona` for a
            persona a run could not use, `bad_pr` for a subject that is not a PR's URL, and `not_requested` for a PR
            with no open request.
    """
    conversation.check_operator()
    if name is not None:
        personas.check(config, name)
    url = _pr_url(ref)
    with db.transaction(conn):
        found = open_request(conn, url)
        if found is None:
            raise conversation.Refused(
                "not_requested",
                f"{url} has no open review request; ask for one with its persona: canopy start {url} --review "
                f"--persona {name or 'NAME'}",
            )
        if name is None:
            sql.execute(conn, sql.delete("review_request_personas").where("request_id = ?", found.id))
        else:
            _set_persona(conn, found.id, name)
    return found


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


def _set_persona(conn: sqlite3.Connection, request_id: int, name: str) -> None:
    # In place of the request's own, inside the caller's transaction.
    sql.execute(conn, sql.delete("review_request_personas").where("request_id = ?", request_id))
    sql.execute(conn, sql.insert("review_request_personas", request_id=request_id, persona=name))


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
            "bad_pr",
            f"name the PR by its plain https:// URL, as `canopy review show` does, not {ref}",
        )
    return ref.id
