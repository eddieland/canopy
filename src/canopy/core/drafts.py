"""Drafts (DESIGN §29): the comments a run would have posted, kept for the operator to read, edit, drop, or send.

A run rendered under `trust.review_replies = "approve"` drafts each comment it would have posted. `_run` hands this
module the run's result to write, in the transaction that closes the run (`record_run`). A worker's drafts are parsed
apart from its result (`parse`), never stored in `runs.result_json`: a draft's text lives in its versions alone. Each
entry is checked as it is written and refused alone, never cut or cleaned, with why recorded in the harness's words on
the run's `run_replies` row. A draft for a PR waits `unchecked` until a whole read of its PR says its thread exists; a
ticket's is `waiting` at once.

It is core, since `_run` writes it and the CLI and the web UI read and send it (DESIGN §5).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import assert_never

from pydantic import BaseModel, ConfigDict, JsonValue

from canopy.core import contract, db, records
from canopy.core.memory_text import TextRefused, check_text
from canopy.core.replies import MAX_DRAFT_CHARS, MAX_DRAFTS, run_replies
from canopy.core.vocab import DraftAuthor, DraftKind, DraftStance, DraftStatus, Reaction, ReplyMode
from canopy.infra import logs

# The longest ticket URL a draft may name; the post command checks the rest.
MAX_URL = 2048


class Fields(BaseModel):
    """A worker's drafts, read from its result line apart from the result. Untrusted: each entry is checked alone."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    drafts: JsonValue = None


def parse(text: str) -> Fields | None:
    """Parse the drafts of `text`'s result line, the last line that starts with `{` (DESIGN §13).

    Returns:
        The fields, or None when there is no such line or it is not a JSON object.
    """
    return contract.last_line(Fields, text)


@dataclass(frozen=True)
class Refused:
    """A draft `_run` did not write: its number in the run's list, and why, in the harness's words."""

    number: int
    why: str

    def as_json(self) -> dict[str, int | str]:
        """Return the entry as `run_replies.refused` holds it."""
        return {"number": self.number, "why": self.why}


def record_run(conn: sqlite3.Connection, run_id: int, fields: Fields | None) -> list[Refused]:
    """Write the drafts run `run_id` sent, if its prompt was rendered under `approve` (DESIGN §29).

    Call inside the transaction that closes the run. The ticket is the run's own, read from its row, and a draft for a
    PR must name one of the PRs its units hold for the repositories it covered, so no run drafts for another's. A run
    rendered under `post`, or of a kind that comments nowhere, writes nothing, whatever it sent; so does one whose
    result line was not a valid result, which is why `fields` is None.

    Returns:
        The drafts refused, as recorded in the run's `run_replies.refused`.
    """
    rendered = run_replies(conn, run_id)
    if rendered is None or rendered.mode is not ReplyMode.APPROVE or fields is None or fields.drafts is None:
        return []
    run = conn.execute("SELECT ticket_key, tick_id, started_at FROM runs WHERE id = ?", (run_id,)).fetchone()
    writing = _Writing(
        run_id=run_id,
        ticket_key=str(run["ticket_key"]),
        basis=str(run["started_at"]),
        prs=_run_prs(conn, run_id, str(run["ticket_key"])),
        ticket_drafts=rendered.ticket_drafts,
    )
    entries: list[JsonValue] = fields.drafts if isinstance(fields.drafts, list) else []
    if not isinstance(fields.drafts, list):
        writing.refused.append(Refused(0, "`drafts` is not a list"))
    for number, entry in enumerate(entries, start=1):
        if number > MAX_DRAFTS:
            writing.refused.append(Refused(number, f"over {MAX_DRAFTS} drafts a run"))
            continue
        try:
            _write(conn, writing, number, entry)
        except TextRefused as e:
            writing.refused.append(Refused(number, str(e)))
    conn.execute(
        "UPDATE run_replies SET refused = ? WHERE run_id = ?",
        (json.dumps([r.as_json() for r in writing.refused]), run_id),
    )
    log = logs.for_tick(int(run["tick_id"]))
    for r in writing.refused:
        log.info("draft refused", extra={"run_id": run_id, **r.as_json()})
    return writing.refused


@dataclass
class _Writing:
    """One run's drafts as they are written: its ticket, its PRs by URL, and what it wrote or refused so far."""

    run_id: int
    ticket_key: str
    basis: str
    prs: Mapping[str, str]
    ticket_drafts: bool
    refused: list[Refused] = field(default_factory=list)
    pr_comments: set[str] = field(default_factory=set)
    ticket: bool = False


def _run_prs(conn: sqlite3.Connection, run_id: int, key: str) -> dict[str, str]:
    """The repository of each PR the ticket's units hold, for the repositories run `run_id` covered.

    Returns:
        Each PR's URL, to its repository.
    """
    repos = {str(r["repo"]) for r in conn.execute("SELECT repo FROM run_slots WHERE run_id = ?", (run_id,))}
    return {str(u.pr_url): str(u.repo) for u in db.units(conn, key) if u.pr_url and u.repo in repos}


def _write(conn: sqlite3.Connection, writing: _Writing, number: int, entry: JsonValue) -> None:
    """Check one entry and write it as a draft with its first version.

    Raises:
        TextRefused: The entry is not one canopy keeps, saying why.
    """
    if not isinstance(entry, dict):
        raise TextRefused("it is not an object")
    on = entry.get("on")
    kind = next((k for k in DraftKind if k == on), None)
    if kind is None:
        raise TextRefused("its `on` is not thread, pr, or ticket")
    text, reaction = _words(kind, entry)
    pr, comment, stance, issue = _target(writing, kind, entry)
    status = DraftStatus.WAITING if kind is DraftKind.TICKET else DraftStatus.UNCHECKED
    now = db.now()
    cursor = conn.execute(
        "INSERT INTO drafts (run_id, number, ticket_key, kind, repo, pr_url, comment_id, issue_url, stance, status, "
        "basis, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            writing.run_id,
            number,
            writing.ticket_key,
            kind,
            None if pr is None else writing.prs[pr],
            pr,
            comment,
            issue,
            stance,
            status,
            writing.basis,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO draft_versions (draft_id, version, body, author, created_at, reaction) VALUES (?, 1, ?, ?, ?, ?)",
        (cursor.lastrowid, text, DraftAuthor.WORKER, now, reaction),
    )
    if kind is DraftKind.TICKET:
        # A ticket's draft needs no read, so it supersedes the earlier ones as it is written.
        written = get(conn, int(cursor.lastrowid or 0))
        if written is not None:
            _supersede(conn, written, "kind = 'ticket' AND ticket_key = ?", writing.ticket_key)


def _words(kind: DraftKind, entry: Mapping[str, JsonValue]) -> tuple[str, Reaction | None]:
    """An entry's text and the reaction it stages, which only a thread's draft may, beside its text or alone.

    Returns:
        The text, empty for a reaction alone, and the reaction, or None.

    Raises:
        TextRefused: A reaction GitHub does not offer, or one on a draft that is not a thread's; a text canopy would
            not keep, or none without a reaction.
    """
    raw = entry.get("react")
    if raw is None:
        return check_words(entry.get("text"), None), None
    reaction = next((r for r in Reaction if r == raw), None)
    if reaction is None:
        raise TextRefused(f"its `react` is not one of {', '.join(Reaction)}")
    if kind is not DraftKind.THREAD:
        raise TextRefused("its `react` is on a draft that is not a thread's; only a review comment takes one")
    return check_words(entry.get("text"), reaction), reaction


def check_words(text: object, reaction: Reaction | None) -> str:
    """Return a draft's text, checked as DESIGN §29 bounds it: empty only beside a reaction, which then goes alone.

    Returns:
        The text, trimmed, or empty.

    Raises:
        TextRefused: The text is one canopy would not keep, or there is none and no reaction.
    """
    if reaction is not None and text in (None, ""):
        return ""
    return check_text(text, MAX_DRAFT_CHARS, lines=True)


def _target(
    writing: _Writing, kind: DraftKind, entry: Mapping[str, JsonValue]
) -> tuple[str | None, int | None, DraftStance | None, str | None]:
    """Where an entry goes: a thread's or a PR's PR, a thread's comment and stance, or a ticket's issue.

    Returns:
        The PR, the comment, the stance, and the issue, each None where the kind has none.

    Raises:
        TextRefused: It names a PR not the run's, a comment or stance that is not one, a second of what a run takes
            one of, or a ticket's draft the run was not asked for.
    """
    match kind:
        case DraftKind.THREAD:
            did = entry.get("did")
            stance = next((s for s in DraftStance if s == did), None)
            pr, comment = _pr(writing.prs, entry.get("pr")), _comment(entry.get("comment"))
            if stance is None:
                raise TextRefused("its `did` is not changed, declined, or answered")
            return pr, comment, stance, None
        case DraftKind.PR:
            pr = _pr(writing.prs, entry.get("pr"))
            if pr in writing.pr_comments:
                raise TextRefused(f"a second draft for {pr}'s own comment; a PR takes one")
            writing.pr_comments.add(pr)
            return pr, None, None, None
        case DraftKind.TICKET:
            if not writing.ticket_drafts:
                raise TextRefused("no_post: this run was asked for no ticket's draft")
            if writing.ticket:
                raise TextRefused("a second draft for the ticket; a run takes one")
            issue = _url(entry.get("url"))
            writing.ticket = True
            return None, None, None, issue
        case _:
            assert_never(kind)


def _pr(prs: Mapping[str, str], value: object) -> str:
    if not isinstance(value, str) or value not in prs:
        raise TextRefused("not_ours: its `pr` is not one of this run's PRs")
    return value


def _comment(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TextRefused("its `comment` is not a review comment's id")
    return value


def _url(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("https://")
        or len(value) > MAX_URL
        or any(c.isspace() or not c.isprintable() for c in value)
    ):
        raise TextRefused("its `url` is not the ticket's https:// URL")
    return value


def sent_by_pr(conn: sqlite3.Connection) -> dict[str, dict[str, list[int]]]:
    """Return what the operator sent through canopy on each PR, by GitHub's ids: the comments and the reviews.

    A sent reply carries no mark and is by the operator's login, so these ids are how the loop knows it (DESIGN §29).
    A staged draft's reply and review count from the start: the operator may submit them on GitHub before canopy reads
    the PR, and GitHub keeps a pending review's id, and each of its comments', when it is submitted.

    Returns:
        Each PR's URL, to its sent `comments` and `reviews`, each list of ids in order.
    """
    found: dict[str, dict[str, list[int]]] = {}
    rows = conn.execute(
        "SELECT pr_url, sent_comment_id, CASE WHEN status = ? THEN pending_review_id ELSE sent_review_id END "
        "AS sent_review_id FROM drafts WHERE status IN (?, ?) AND pr_url IS NOT NULL "
        "ORDER BY pr_url, sent_at IS NULL, sent_at, id",
        (DraftStatus.STAGED, DraftStatus.SENT, DraftStatus.STAGED),
    )
    for r in rows:
        sent = found.setdefault(str(r["pr_url"]), {"comments": [], "reviews": []})
        for name, column in (("comments", "sent_comment_id"), ("reviews", "sent_review_id")):
            value = r[column]
            if value is not None and int(value) not in sent[name]:
                sent[name].append(int(value))
    return found


def unchecked_prs(conn: sqlite3.Connection) -> list[str]:
    """Return the PRs with a draft that waits on a whole read, which each tick's reconcile reads again.

    Returns:
        The PRs' URLs, in order.
    """
    rows = conn.execute("SELECT DISTINCT pr_url FROM drafts WHERE status = ? ORDER BY pr_url", (DraftStatus.UNCHECKED,))
    return [str(r["pr_url"]) for r in rows]


def check(conn: sqlite3.Connection, whole: Collection[str]) -> list[records.Draft]:
    """Check the unchecked drafts of the PRs read whole against what that read recorded (DESIGN §29).

    A thread's draft names a review comment: found, the draft waits on the operator with the comment's thread; not
    found, it is refused `unknown_thread`, recorded on its run as `_run`'s refusals are. A PR's draft needs only the
    read. Once checked, a draft supersedes the unsent drafts of earlier runs for the same thread or the same PR's
    comment, and a second one of the same run for the same thread is refused.

    Returns:
        The drafts checked, in the order checked, as they now stand.
    """
    if not whole:
        return []
    pending = records.fetch_all(
        conn,
        records.Draft,
        f"SELECT * FROM drafts WHERE status = ? AND pr_url IN ({db.marks(whole)}) ORDER BY run_id, number",  # noqa: S608
        (DraftStatus.UNCHECKED, *sorted(whole)),
    )
    now = db.now()
    with db.transaction(conn):
        for draft in pending:
            _check_one(conn, draft, now)
    return [present for d in pending if (present := get(conn, d.id)) is not None]


def _check_one(conn: sqlite3.Connection, draft: records.Draft, now: str) -> None:
    thread: str | None = None
    if draft.kind is DraftKind.THREAD:
        row = conn.execute(
            "SELECT thread_id FROM observed_reviews WHERE pr_url = ? AND item = 'comment' AND id = ?",
            (draft.pr_url, draft.comment_id),
        ).fetchone()
        if row is None:
            _refuse(conn, draft, f"unknown_thread: {draft.pr_url} has no review comment {draft.comment_id}")
            return
        thread = str(row["thread_id"])
        twin = conn.execute(
            "SELECT number FROM drafts WHERE run_id = ? AND thread_id = ? AND id != ?", (draft.run_id, thread, draft.id)
        ).fetchone()
        if twin is not None:
            _refuse(conn, draft, f"a second draft for the thread draft {twin['number']} answers; a thread takes one")
            return
    conn.execute(
        "UPDATE drafts SET status = ?, thread_id = ?, checked_at = ? WHERE id = ?",
        (DraftStatus.WAITING, thread, now, draft.id),
    )
    same = "thread_id = ?" if thread is not None else "kind = 'pr' AND pr_url = ?"
    _supersede(conn, draft, same, thread if thread is not None else draft.pr_url)


def _supersede(conn: sqlite3.Connection, draft: records.Draft, same: str, value: object) -> None:
    """Supersede the unsent drafts of earlier runs that `draft` replaces: those where `same` holds for `value`.

    Only earlier runs', and that is enough: `check` takes every unchecked draft of a PR it read, whatever its run, in
    run order, so an earlier run's draft for the PR is checked, and superseded, before a later run's replaces it.
    """
    conn.execute(
        f"UPDATE drafts SET status = ?, superseded_by = ?, why = ? WHERE {same} AND run_id < ? "  # noqa: S608
        "AND status IN (?, ?)",
        (
            DraftStatus.SUPERSEDED,
            draft.id,
            f"superseded by run {draft.run_id}'s draft {draft.number}",
            value,
            draft.run_id,
            DraftStatus.UNCHECKED,
            DraftStatus.WAITING,
        ),
    )


def _refuse(conn: sqlite3.Connection, draft: records.Draft, why: str) -> None:
    conn.execute("UPDATE drafts SET status = ?, why = ? WHERE id = ?", (DraftStatus.REFUSED, why, draft.id))
    rendered = run_replies(conn, draft.run_id)
    if rendered is None:
        return
    refused = [*refused_of(rendered), Refused(draft.number, why)]
    conn.execute(
        "UPDATE run_replies SET refused = ? WHERE run_id = ?",
        (json.dumps([r.as_json() for r in refused]), draft.run_id),
    )


def get(conn: sqlite3.Connection, draft_id: int) -> records.Draft | None:
    """Return draft `draft_id`, or None."""
    return records.fetch_one(conn, records.Draft, "SELECT * FROM drafts WHERE id = ?", (draft_id,))


def of_run(conn: sqlite3.Connection, run_id: int) -> list[records.Draft]:
    """Return run `run_id`'s drafts, by number.

    Returns:
        The drafts, whatever their status.
    """
    return records.fetch_all(conn, records.Draft, "SELECT * FROM drafts WHERE run_id = ? ORDER BY number", (run_id,))


def text_of(conn: sqlite3.Connection, draft_id: int) -> records.DraftVersion:
    """Return draft `draft_id`'s text as it stands: its latest version.

    Returns:
        The version.

    Raises:
        LookupError: The draft has no version, which `record_run` never writes.
    """
    found = records.fetch_one(
        conn,
        records.DraftVersion,
        "SELECT * FROM draft_versions WHERE draft_id = ? ORDER BY version DESC LIMIT 1",
        (draft_id,),
    )
    if found is None:
        raise LookupError(f"draft {draft_id} has no text")
    return found


def refused_of(rendered: records.RunReplies) -> list[Refused]:
    """Return the drafts `_run` refused of a run, as recorded with it.

    Returns:
        Each refusal, in the order recorded.
    """
    raw: object = json.loads(rendered.refused)
    entries: Sequence[object] = raw if isinstance(raw, list) else []
    return [
        Refused(int(e["number"]), str(e["why"]))
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("number"), int)
    ]
