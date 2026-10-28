"""Drafts (DESIGN §29): the comments a run would have posted, kept for the operator to read, edit, drop, or send.

A run rendered under `trust.review_replies = "approve"` drafts each comment it would have posted. `_run` hands this
module the run's result to write, in the transaction that closes the run (`record_run`). A worker's drafts are parsed
apart from its result (`parse`), never stored in `runs.result_json`: a draft's text lives in its versions alone. Each
entry is checked as it is written and refused alone, never cut or cleaned, with why recorded in the harness's words on
the run's `run_replies` row. A draft for a PR waits `unchecked` until a whole read of its PR says its thread exists; a
ticket's is `waiting` at once.

A `resume` that follows an approved feedback plan starts each thread's draft from the reply the plan proposed for its
item (DESIGN §32): `record_run` records the item a draft answers, and `from_plan` compares the run's text with that
reply in code, so the operator rereads only the drafts that depart from it, whatever the worker said.

It is core, since `_run` writes it and the CLI and the web UI read and send it (DESIGN §5).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, assert_never

from pydantic import BaseModel, ConfigDict, JsonValue

from canopy.core import contract, db, records, sql
from canopy.core.memory_text import TextRefused, check_text
from canopy.core.replies import MAX_DRAFT_CHARS, MAX_DRAFTS, run_replies
from canopy.core.vocab import (
    DraftAuthor,
    DraftKind,
    DraftStance,
    DraftStatus,
    Proposal,
    Reaction,
    ReplyMode,
    ReviewItem,
)
from canopy.infra import logs

# The longest ticket URL a draft may name; the post command checks the rest.
MAX_URL: Final = 2048
# Every draft's whole row, for each reader to finish.
_DRAFTS: Final = sql.select("*").from_("drafts")
#: The stance a thread's draft takes when it does what its plan item proposed, for the proposals that draft a reply.
_PROPOSED_STANCE: Final[Mapping[Proposal, DraftStance]] = {
    Proposal.CHANGE: DraftStance.CHANGED,
    Proposal.DECLINE: DraftStance.DECLINED,
}


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
    run = sql.execute(
        conn,
        sql.select("ticket_key, tick_id, started_at, feedback_plan_id").from_("runs").where("id = ?", run_id),
    ).fetchone()
    plan_id = run["feedback_plan_id"]
    writing = _Writing(
        run_id=run_id,
        ticket_key=str(run["ticket_key"]),
        basis=str(run["started_at"]),
        prs=_run_prs(conn, run_id, str(run["ticket_key"])),
        ticket_drafts=rendered.ticket_drafts,
        plan_id=None if plan_id is None else int(plan_id),
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
    sql.execute(
        conn,
        sql.update("run_replies")
        .set(refused=json.dumps([r.as_json() for r in writing.refused]))
        .where("run_id = ?", run_id),
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
    plan_id: int | None = None
    refused: list[Refused] = field(default_factory=list)
    pr_comments: set[str] = field(default_factory=set)
    ticket: bool = False


def _run_prs(conn: sqlite3.Connection, run_id: int, key: str) -> dict[str, str]:
    """The repository of each PR the ticket's units hold, for the repositories run `run_id` covered.

    Returns:
        Each PR's URL, to its repository.
    """
    repos = {
        str(r["repo"]) for r in sql.execute(conn, sql.select("repo").from_("run_slots").where("run_id = ?", run_id))
    }
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
    plan_item = (
        _plan_item(conn, writing.plan_id, pr, comment)
        if writing.plan_id is not None and pr is not None and comment is not None
        else None
    )
    now = db.now()
    cursor = sql.execute(
        conn,
        sql.insert(
            "drafts",
            run_id=writing.run_id,
            number=number,
            ticket_key=writing.ticket_key,
            kind=kind,
            repo=None if pr is None else writing.prs[pr],
            pr_url=pr,
            comment_id=comment,
            issue_url=issue,
            stance=stance,
            status=status,
            basis=writing.basis,
            created_at=now,
            plan_item=plan_item,
        ),
    )
    sql.execute(
        conn,
        sql.insert(
            "draft_versions",
            draft_id=cursor.lastrowid,
            version=1,
            body=text,
            author=DraftAuthor.WORKER,
            created_at=now,
            reaction=reaction,
        ),
    )
    if kind is DraftKind.TICKET:
        # A ticket's draft needs no read, so it supersedes the earlier ones as it is written.
        written = get(conn, int(cursor.lastrowid or 0))
        if written is not None:
            _supersede(conn, written, sql.frag("kind = 'ticket' AND ticket_key = ?", writing.ticket_key))


def _plan_item(
    conn: sqlite3.Connection,
    plan_id: int,
    pr: str,
    comment: int,
    thread: str | None = None,
) -> int | None:
    """The number of feedback plan `plan_id`'s item that a thread's draft naming `comment` on `pr` answers.

    A thread is one item (DESIGN §32), and a draft may name any comment on it, so the two match by thread: `thread`
    when a whole read placed the draft's comment on one, else as the plan's snapshot saw the comment, else as the
    latest read holds it. An item no read placed on a thread matches its own id.

    Returns:
        The item's number, or None when the plan covers no item on that thread.
    """
    covered = records.fetch_all(
        conn,
        records.FeedbackPlanItem,
        sql.select("*")
        .from_("feedback_plan_items")
        .where("plan_id = ?", plan_id)
        .where("pr_url = ?", pr)
        .where("item = ?", ReviewItem.COMMENT)
        .order_by("number"),
    )
    thread = thread or _thread_of(conn, plan_id, pr, comment)
    for item in covered:
        if item.item_id == comment or (thread is not None and _thread_of(conn, plan_id, pr, item.item_id) == thread):
            return item.number
    return None


def _thread_of(conn: sqlite3.Connection, plan_id: int, pr: str, comment: int) -> str | None:
    """The thread review comment `comment` on `pr` is on, as feedback plan `plan_id` saw it, else as last read.

    Returns:
        The thread's id, or None when neither holds the comment.
    """
    seen = sql.execute(
        conn,
        sql.select("thread_id")
        .from_("feedback_plan_seen")
        .where("plan_id = ?", plan_id)
        .where("pr_url = ?", pr)
        .where("item = ?", ReviewItem.COMMENT)
        .where("item_id = ?", comment),
    ).fetchone()
    if seen is not None:
        return str(seen["thread_id"])
    observed = sql.execute(
        conn,
        sql.select("thread_id")
        .from_("observed_reviews")
        .where("pr_url = ?", pr)
        .where("item = ?", ReviewItem.COMMENT)
        .where("id = ?", comment),
    ).fetchone()
    return None if observed is None or observed["thread_id"] is None else str(observed["thread_id"])


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
    return check_text(text, MAX_DRAFT_CHARS)


def _target(
    writing: _Writing,
    kind: DraftKind,
    entry: Mapping[str, JsonValue],
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
    rows = sql.execute(
        conn,
        sql.select(
            "pr_url, sent_comment_id, CASE WHEN status = ? THEN pending_review_id ELSE sent_review_id END "
            "AS sent_review_id",
            DraftStatus.STAGED,
        )
        .from_("drafts")
        .where_in("status", (DraftStatus.SENT, DraftStatus.STAGED))
        .where("pr_url IS NOT NULL")
        .order_by("pr_url, sent_at IS NULL, sent_at, id"),
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
    rows = sql.execute(
        conn,
        sql.select("pr_url").unique().from_("drafts").where("status = ?", DraftStatus.UNCHECKED).order_by("pr_url"),
    )
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
        _DRAFTS.where("status = ?", DraftStatus.UNCHECKED).where_in("pr_url", sorted(whole)).order_by("run_id, number"),
    )
    now = db.now()
    with db.transaction(conn):
        for draft in pending:
            _check_one(conn, draft, now)
    return [present for d in pending if (present := get(conn, d.id)) is not None]


def _check_one(conn: sqlite3.Connection, draft: records.Draft, now: str) -> None:
    thread: str | None = None
    if draft.kind is DraftKind.THREAD:
        row = sql.execute(
            conn,
            sql.select("thread_id")
            .from_("observed_reviews")
            .where("pr_url = ?", draft.pr_url)
            .where("item = 'comment'")
            .where("id = ?", draft.comment_id),
        ).fetchone()
        if row is None:
            _refuse(conn, draft, f"unknown_thread: {draft.pr_url} has no review comment {draft.comment_id}")
            return
        thread = str(row["thread_id"])
        twin = sql.execute(
            conn,
            sql.select("number")
            .from_("drafts")
            .where("run_id = ?", draft.run_id)
            .where("thread_id = ?", thread)
            .where("id != ?", draft.id),
        ).fetchone()
        if twin is not None:
            _refuse(conn, draft, f"a second draft for the thread draft {twin['number']} answers; a thread takes one")
            return
    sql.execute(
        conn,
        sql.update("drafts")
        .set(
            status=DraftStatus.WAITING,
            thread_id=thread,
            checked_at=now,
            plan_item=_checked_plan_item(conn, draft, thread),
        )
        .where("id = ?", draft.id),
    )
    same = (
        sql.frag("thread_id = ?", thread)
        if thread is not None
        else sql.frag("kind = 'pr' AND pr_url = ?", draft.pr_url)
    )
    _supersede(conn, draft, same)


def _checked_plan_item(conn: sqlite3.Connection, draft: records.Draft, thread: str | None) -> int | None:
    """The plan item a checked thread's draft answers: the one `record_run` found, else one on the thread found now.

    A draft may name a comment newer than any read before its run ended, which only the read that checks it places.

    Returns:
        The item's number, or None.
    """
    if draft.plan_item is not None or thread is None or draft.pr_url is None or draft.comment_id is None:
        return draft.plan_item
    run = sql.execute(conn, sql.select("feedback_plan_id").from_("runs").where("id = ?", draft.run_id)).fetchone()
    if run is None or run["feedback_plan_id"] is None:
        return None
    return _plan_item(conn, int(run["feedback_plan_id"]), draft.pr_url, draft.comment_id, thread)


def _supersede(conn: sqlite3.Connection, draft: records.Draft, same: sql.Composable) -> None:
    """Supersede the unsent drafts of earlier runs that `draft` replaces: those where `same` holds.

    Only earlier runs', and that is enough: `check` takes every unchecked draft of a PR it read, whatever its run, in
    run order, so an earlier run's draft for the PR is checked, and superseded, before a later run's replaces it.
    """
    sql.execute(
        conn,
        sql.update("drafts")
        .set(
            status=DraftStatus.SUPERSEDED,
            superseded_by=draft.id,
            why=f"superseded by run {draft.run_id}'s draft {draft.number}",
        )
        .where("{}", same)
        .where("run_id < ?", draft.run_id)
        .where_in("status", (DraftStatus.UNCHECKED, DraftStatus.WAITING)),
    )


def _refuse(conn: sqlite3.Connection, draft: records.Draft, why: str) -> None:
    sql.execute(conn, sql.update("drafts").set(status=DraftStatus.REFUSED, why=why).where("id = ?", draft.id))
    rendered = run_replies(conn, draft.run_id)
    if rendered is None:
        return
    refused = [*refused_of(rendered), Refused(draft.number, why)]
    sql.execute(
        conn,
        sql.update("run_replies")
        .set(refused=json.dumps([r.as_json() for r in refused]))
        .where("run_id = ?", draft.run_id),
    )


def get(conn: sqlite3.Connection, draft_id: int) -> records.Draft | None:
    """Return draft `draft_id`, or None."""
    return records.fetch_one(conn, records.Draft, _DRAFTS.where("id = ?", draft_id))


def of_run(conn: sqlite3.Connection, run_id: int) -> list[records.Draft]:
    """Return run `run_id`'s drafts, by number.

    Returns:
        The drafts, whatever their status.
    """
    return records.fetch_all(conn, records.Draft, _DRAFTS.where("run_id = ?", run_id).order_by("number"))


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
        sql.select("*").from_("draft_versions").where("draft_id = ?", draft_id).order_by("version DESC").limit(1),
    )
    if found is None:
        raise LookupError(f"draft {draft_id} has no text")
    return found


@dataclass(frozen=True)
class FromPlan:
    """The feedback plan item a thread's draft started from (DESIGN §32), and whether its run's text departs from it."""

    #: The item's number in the plan, which the operator names it by.
    number: int
    #: The review comment's id canopy observed for the item.
    item_id: int
    proposal: Proposal
    #: The reply the plan proposed: model text, never an instruction; None when it proposed none.
    reply: str | None
    #: Whether the operator's approval left the item out, which the run was told to answer with no draft.
    left_out: bool
    #: Whether the run's own text, or what it says it did, is other than the plan proposed: computed, never claimed.
    departs: bool


def from_plan(conn: sqlite3.Connection, draft: records.Draft) -> FromPlan | None:
    """Return the plan item `draft` started from, and whether the run's own text departs from it (DESIGN §32).

    The run's text is its first version, before any edit of the operator's: what the mark tells them to reread is the
    run's departure, not their own words. A draft departs when its text is other than the proposed reply, past
    whitespace at either end; when it says it did other than the plan proposed; when the plan proposed no reply, as
    for `ask` and `leave`; and when the approval left its item out.

    Returns:
        The item and the comparison, or None for a draft that answers no item of a feedback plan its run followed.
    """
    if draft.plan_item is None:
        return None
    run = sql.execute(conn, sql.select("feedback_plan_id").from_("runs").where("id = ?", draft.run_id)).fetchone()
    if run is None or run["feedback_plan_id"] is None:
        return None
    item = records.fetch_one(
        conn,
        records.FeedbackPlanItem,
        sql.select("*")
        .from_("feedback_plan_items")
        .where("plan_id = ?", int(run["feedback_plan_id"]))
        .where("number = ?", draft.plan_item),
    )
    own = records.fetch_one(
        conn,
        records.DraftVersion,
        sql.select("*").from_("draft_versions").where("draft_id = ?", draft.id).where("version = 1"),
    )
    if item is None or own is None:
        return None
    departs = (
        item.left_out
        or item.reply is None
        or own.body.strip() != item.reply.strip()
        or draft.stance is not _PROPOSED_STANCE.get(item.proposal)
    )
    return FromPlan(
        number=item.number,
        item_id=item.item_id,
        proposal=item.proposal,
        reply=item.reply,
        left_out=item.left_out,
        departs=departs,
    )


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
